#pragma once
#include "../3rd party/ode/include/ode/parallel_step.h"
#include "../xrCore/xr_cpu_jobs.h"
namespace xr_physics
{
struct IslandJob {dWorldID world;bool exact;unsigned seed;};
struct IslandBatchStats
{
    bool accepted=false;
    std::size_t eligible=0;
    xr_cpu::BatchStats cpu;
};
// Worlds must be disjoint active roots after collision merging. The owner
// freezes lists/joints/bodies/materials and defers callbacks until this returns.
// Large exact/quick solvers retain the owner's larger stack. No solver switch.
IslandBatchStats step_islands(const IslandJob*,std::size_t,dReal step,unsigned limit=0) noexcept;
}
