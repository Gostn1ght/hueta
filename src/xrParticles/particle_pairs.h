#pragma once
#include "../xrCore/xr_cpu_jobs.h"
#include <memory>
#include <new>

namespace PAPI
{
// Calculate pair forces from immutable positions, then apply them on the
// owner in the original i/j order. Never use this for velocity-dependent pair
// actions: earlier velocity updates are part of their input and ordering.
template<class Evaluate,class Apply>
bool particle_pairs(unsigned count,Evaluate&& evaluate,Apply&& apply)
{
    if(count<512 || xr_cpu::concurrency()<3 || strstr(Core.Params,"-cpu_serial") ||
       strstr(Core.Params,"-cpu_particles_legacy"))return false;
    struct Pair {unsigned first,second;bool active;pVector force;};
    constexpr std::size_t capacity=65536; // <=1.5 MiB, independent of particle count.
    static_assert(sizeof(Pair)<=24,"Keep pair scratch bounded");
    std::unique_ptr<Pair[]> pairs(new(std::nothrow) Pair[capacity]);
    if(!pairs)return false; // No particle has been changed before allocation.
    struct Work
    {
        Pair* pairs;
        Evaluate& evaluate;
        static void run(void* opaque,std::size_t begin,std::size_t end) noexcept
        {
            auto& work=*static_cast<Work*>(opaque);
            for(auto index=begin;index<end;++index)
            {
                auto& pair=work.pairs[index];
                pair.active=work.evaluate(pair.first,pair.second,pair.force);
            }
        }
    } work{pairs.get(),evaluate};
    unsigned first=0,second=1;
    while(first+1<count)
    {
        std::size_t size=0;
        while(size<capacity && first+1<count)
        {
            auto& pair=pairs[size++];pair.first=first;pair.second=second;
            if(++second==count){++first;second=first+1;}
        }
        // Output-only calculation may safely replay after scheduler failure.
        xr_cpu::parallel_for(size,256,Work::run,&work);
        for(std::size_t index=0;index<size;++index)
        {
            const auto& pair=pairs[index];
            if(pair.active)apply(pair.first,pair.second,pair.force);
        }
    }
    return true;
}
}
