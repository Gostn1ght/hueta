#pragma once
#include "particle_cpu.h"

namespace PAPI
{
// Pair forces depend only on immutable positions. Each worker accumulates one
// particle's velocity locally: lower-index -= contributions, then upper-index
// += contributions, exactly matching the old pair loop's per-particle order.
// Forces are evaluated twice to avoid a quadratic buffer or serial apply pass.
// Do not use for forces that depend on earlier velocity updates.
template<class Read,class Evaluate,class Write>
bool particle_pair_forces(unsigned count,Read&& read,Evaluate&& evaluate,Write&& write)
{
    if(count<512 || xr_cpu::concurrency()<3 || strstr(Core.Params,"-cpu_serial") ||
       strstr(Core.Params,"-cpu_particles_legacy"))return false;
    particle_ranges(count,512,[&](unsigned begin,unsigned end) noexcept
    {
        for(unsigned index=begin;index<end;++index)
        {
            pVector velocity=read(index),force;
            for(unsigned other=0;other<index;++other)
                if(evaluate(other,index,force))velocity-=force;
            for(unsigned other=index+1;other<count;++other)
                if(evaluate(index,other,force))velocity+=force;
            write(index,velocity);
        }
    },128);
    return true;
}
}
