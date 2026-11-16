// Exception-enabled CPU boundary, deliberately without engine/PCH headers.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "xr_cpu_jobs.h"
#include "../3rd party/tbb/blocked_range.h"
#include "../3rd party/tbb/parallel_for.h"
#include "../3rd party/tbb/task_arena.h"
#include <algorithm>
#include <atomic>
#include <cfenv>
#include <thread>

namespace xr_cpu
{
namespace
{
thread_local bool inside=false;
struct Scope
{
    bool previous;
    std::fenv_t saved{};
    bool restored=false;
    explicit Scope(const std::fenv_t* caller) noexcept:previous(inside)
    {
        inside=true;
        if(caller && std::fegetenv(&saved)==0){restored=true;std::fesetenv(caller);}
    }
    ~Scope(){if(restored)std::fesetenv(&saved);inside=previous;}
};
tbb::task_arena& arena(unsigned n)
{
    // Lazy TBB activation; these are settings, not 8 separate OS thread pools.
    static tbb::task_arena arenas[]={tbb::task_arena(1),tbb::task_arena(2),tbb::task_arena(3),tbb::task_arena(4),
        tbb::task_arena(5),tbb::task_arena(6),tbb::task_arena(7),tbb::task_arena(8)};
    return arenas[n-1];
}
}
unsigned concurrency(unsigned limit) noexcept
{
    const auto hw=std::max(1u,std::thread::hardware_concurrency());
    const auto automatic=hw>2 ? hw-1:hw;
    return std::max(1u,std::min(8u,std::min(hw,limit ? limit:automatic)));
}
BatchStats parallel_for(std::size_t count,std::size_t grain,RangeTask task,void* context,unsigned limit) noexcept
{
    BatchStats result;
    if(!count || !task)return result;
    grain=std::max(std::size_t(1),grain);
    const auto slots=concurrency(limit);
    if(inside || slots==1 || count<grain || count-grain<grain){Scope scope(nullptr);task(context,0,count);result.blocks=1;return result;}
    try
    {
        std::fenv_t caller{};const bool env=std::fegetenv(&caller)==0;
        std::atomic<unsigned> used{0};std::atomic<std::size_t> blocks{0};
        arena(slots).execute([&]{
            tbb::parallel_for(tbb::blocked_range<std::size_t>(0,count,grain),[&](const tbb::blocked_range<std::size_t>& range){
                Scope scope(env ? &caller:nullptr);
                const int slot=tbb::this_task_arena::current_thread_index();
                if(slot>=0 && slot<8)used.fetch_or(1u<<unsigned(slot),std::memory_order_relaxed);
                blocks.fetch_add(1,std::memory_order_relaxed);
                task(context,range.begin(),range.end());
            });
        });
        result.slots=0;
        for(auto mask=used.load();mask;mask>>=1)result.slots+=mask&1u;
        result.slots=std::max(1u,result.slots);result.blocks=blocks.load();return result;
    }
    catch(...)
    {
        // TBB completes/cancels its children before propagating failure.
        Scope scope(nullptr);task(context,0,count);result.blocks=1;result.fallback=true;return result;
    }
}
}
