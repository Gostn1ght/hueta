// Exception-enabled, no PCH or engine object headers.
#include "netcoop_replication_plan.h"
#include <cmath>
#include <memory>
#include <vector>

namespace netcoop_world
{
struct ReplicationPlan::State
{
    std::vector<std::uint32_t> output;
    std::vector<std::size_t> counts;
    std::size_t width=0;
    bool ready=false;
    xr_cpu::BatchStats statistics;
};
namespace
{
struct Work
{
    const PlanRecord* records;std::size_t width;const PlanObserver* observers;
    std::uint32_t tick;unsigned far_scale;
    std::uint32_t* output;std::size_t* counts;
};
void calculate(void* opaque,std::size_t begin,std::size_t end) noexcept
{
    auto& w=*static_cast<Work*>(opaque);
    for(auto observer=begin;observer<end;++observer)
    {
        const auto& eye=w.observers[observer];std::size_t count=0;
        auto out=w.output+observer*w.width;
        for(std::size_t i=0;i<w.width;++i)
        {
            const auto& r=w.records[i];
            if(r.owner_only!=0xffff && r.owner_only!=eye.owner)continue;
            const float dx=eye.x-r.x,dy=eye.y-r.y,dz=eye.z-r.z;
            const float d=r.full_rate || r.id==eye.owner ? 0.f:std::sqrt(dx*dx+dy*dy+dz*dz);
            unsigned every=r.full_rate ? 1:d<50.f ? 1:d<150.f ? 2:d<300.f ? 4:16;
            const bool close=r.full_rate || d<50.f;
            if(!close)every*=w.far_scale;
            if((w.tick+r.id)%every)continue;
            out[count++]=std::uint32_t(i)|(close ? plan_close:0);
        }
        w.counts[observer]=count;
    }
}
}
ReplicationPlan::~ReplicationPlan(){delete state_;}
bool ReplicationPlan::prepare(const PlanRecord* records,std::size_t width,const PlanObserver* observers,std::size_t count,
    std::uint32_t tick,unsigned far_scale,unsigned limit) noexcept
{
    if(state_)state_->ready=false;
    // Maximum32MiB of selections. Overflow/oversized frames use the legacy path.
    if(width>65536 || count>512 || (width && !records) || (count && !observers) ||
        (far_scale!=1 && far_scale!=2 && far_scale!=4) || (count && width>(8u*1024u*1024u)/count))return false;
    try
    {
        for(std::size_t i=0;i<count;++i)
            if(!std::isfinite(observers[i].x)||!std::isfinite(observers[i].y)||!std::isfinite(observers[i].z))return false;
        for(std::size_t i=0;i<width;++i)
            if(!records[i].full_rate && (!std::isfinite(records[i].x)||!std::isfinite(records[i].y)||!std::isfinite(records[i].z)))return false;
        if(!state_)state_=std::make_unique<State>().release();
        auto& s=*state_;s.width=width;s.output.resize(width*count);s.counts.assign(count,0);
        Work work{records,width,observers,tick,far_scale,s.output.data(),s.counts.data()};
        if(width && count)s.statistics=xr_cpu::parallel_for(count,1,calculate,&work,limit);
        else s.statistics={};
        s.ready=true;return true;
    }
    catch(...){return false;}
}
PlanSelection ReplicationPlan::select(std::size_t observer) const noexcept
{
    if(!state_ || !state_->ready || observer>=state_->counts.size())return {};
    return {state_->width ? state_->output.data()+observer*state_->width:nullptr,state_->counts[observer],true};
}
xr_cpu::BatchStats ReplicationPlan::stats() const noexcept{return state_ ? state_->statistics:xr_cpu::BatchStats{};}
}
