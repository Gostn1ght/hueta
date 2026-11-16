// Exception-enabled CPU boundary; no engine/PCH objects or Lua callbacks.
#include "PHIslandBatch.h"
#include "../3rd party/ode/ode/src/objects.h"
#include <algorithm>
#include <cmath>
#include <functional>
#include <vector>

namespace xr_physics
{
namespace
{
struct DeferGeoms
{
    int previous;
    DeferGeoms():previous(dThreadSetGeomNotificationsDeferred(1)){}
    ~DeferGeoms(){dThreadSetGeomNotificationsDeferred(previous);}
};
bool worker_safe(const IslandJob& job) noexcept
{
    // Both solvers use alloca. These bounds keep scratch below256 KiB with
    // the shipped single-precision x2 exact solver / QuickStep (not TIMING).
    return job.world->nb>0 && job.world->nb<=64 && job.world->nj<=(job.exact ? 24:128);
}
void integrate(const IslandJob& job,dReal step) noexcept
{
    if(job.exact)dWorldStep(job.world,step);
    else if(job.world->nj)dWorldQuickStepSeeded(job.world,step,job.seed);
    else dWorldQuickStep(job.world,step);
}
struct Work
{
    const IslandJob* jobs;
    const std::size_t* indices;
    dReal step;
    static void run(void* opaque,std::size_t index) noexcept
    {
        auto& work=*static_cast<Work*>(opaque);
        DeferGeoms defer;
        integrate(work.jobs[work.indices[index]],work.step);
    }
};
}
IslandBatchStats step_islands(const IslandJob* jobs,std::size_t count,dReal step,unsigned limit) noexcept
{
    IslandBatchStats result;
    if(!count){result.accepted=true;return result;}
    if(!jobs || count<4 || count>65536 || !std::isfinite(step) || step<=0 || xr_cpu::concurrency()<2)return result;
    try
    {
        // Validate before any integration. Root ownership comes from the
        // engine's serial island Merge; duplicate roots must never race.
        std::vector<dWorldID> roots;
        std::vector<std::size_t> indices;
        roots.reserve(count);indices.reserve(count);
        std::size_t effort=0;
        for(std::size_t index=0;index<count;++index)
        {
            const auto& job=jobs[index];
            if(!job.world || job.world->nb<0 || job.world->nj<0)return result;
            roots.push_back(job.world);
            if(worker_safe(job))
            {
                indices.push_back(index);
                const auto joints=std::size_t(job.world->nj);
                effort+=std::size_t(job.world->nb)+(job.exact ? joints*joints:6*joints);
            }
        }
        std::sort(roots.begin(),roots.end(),std::less<dWorldID>{});
        if(std::adjacent_find(roots.begin(),roots.end())!=roots.end() || indices.size()<4 || effort<128)return result;

        int previous=0;
        {
            DeferGeoms owner;previous=owner.previous;
            for(std::size_t index=0;index<count;++index)
                if(!worker_safe(jobs[index]))integrate(jobs[index],step);
            Work work{jobs,indices.data(),step};
            result.cpu=xr_cpu::for_each_once(indices.size(),Work::run,&work,limit);
        }
        // Match the original world's/body notification order. Shared parent
        // space dirty lists are touched exclusively by this owner after join.
        if(!previous)
            for(std::size_t index=0;index<count;++index)dWorldRefreshGeoms(jobs[index].world);
        result.eligible=indices.size();result.accepted=true;return result;
    }
    catch(...){return result;} // Allocation happened before any world mutation.
}
}
