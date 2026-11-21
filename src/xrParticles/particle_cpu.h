#pragma once
#include "../xrCore/xr_cpu_jobs.h"

namespace PAPI
{
// The caller owns particle storage and action parameters until the fence.
// Only independent per-particle math belongs here: no random draws, callbacks,
// array resizing, removal, or reading another particle's mutable fields.
template<class Function>
xr_cpu::BatchStats particle_ranges(unsigned count,unsigned minimum,Function&& function,unsigned grain=512)
{
    if(count<minimum || strstr(Core.Params,"-cpu_serial") || strstr(Core.Params,"-cpu_particles_legacy"))
    {
        function(0,count);
        return {1,count ? 1u:0u,false};
    }
    struct Work
    {
        unsigned count,grain;
        Function& function;
        static void run(void* opaque,std::size_t block) noexcept
        {
            auto& work=*static_cast<Work*>(opaque);
            const auto begin=unsigned(block*work.grain);
            const auto remaining=work.count-begin;
            work.function(begin,begin+(remaining<work.grain ? remaining:work.grain));
        }
    } work{count,grain,function};
    // Mutating actions must not replay completed chunks after scheduler failure.
    return xr_cpu::for_each_once((std::size_t(count)+grain-1)/grain,Work::run,&work);
}
}
