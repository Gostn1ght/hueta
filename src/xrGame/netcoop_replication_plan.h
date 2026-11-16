#pragma once
#include <cstddef>
#include <cstdint>
#include "../xrCore/xr_cpu_jobs.h"
namespace netcoop_world
{
struct PlanRecord {std::uint16_t id,owner_only;bool full_rate;float x,y,z;};
struct PlanObserver {std::uint32_t client;std::uint16_t owner;float x,y,z;};
struct PlanSelection {const std::uint32_t* entries=nullptr;std::size_t count=0;bool valid=false;};
constexpr std::uint32_t plan_close=0x80000000u;
// Owner snapshots one already-serialized frame. Worker tasks only calculate
// distance/cadence over plain values. Results expire at the next prepare().
// Budget, keepalive history, ownership, sends and entity access stay on owner.
class ReplicationPlan
{
    struct State;State* state_=nullptr;
public:
    ReplicationPlan() noexcept=default;
    ~ReplicationPlan();
    ReplicationPlan(const ReplicationPlan&)=delete;
    ReplicationPlan& operator=(const ReplicationPlan&)=delete;
    bool prepare(const PlanRecord*,std::size_t,const PlanObserver*,std::size_t,std::uint32_t tick,unsigned far_scale,unsigned limit=0) noexcept;
    PlanSelection select(std::size_t observer) const noexcept;
    xr_cpu::BatchStats stats() const noexcept;
};
}
