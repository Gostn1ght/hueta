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
#include <memory>
#include <new>
#include <thread>

namespace xr_cpu
{
namespace
{
thread_local bool inside=false;
#ifdef LZ_CPU_JOB_TESTS
std::atomic<int> failure_after{-1};
#endif
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
#ifdef LZ_CPU_JOB_TESTS
                if(failure_after.load()>=0 && failure_after.fetch_sub(1)==0)throw std::bad_alloc();
#endif
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
namespace
{
struct OnceWork
{
    IndexTask task;
    void* context;
    std::atomic<unsigned char>* claimed;
    static void run(void* opaque,std::size_t begin,std::size_t end) noexcept
    {
        auto& work=*static_cast<OnceWork*>(opaque);
        for(auto index=begin;index<end;++index)
            if(!work.claimed[index].exchange(1,std::memory_order_relaxed))work.task(work.context,index);
    }
};
}
BatchStats for_each_once(std::size_t count,IndexTask task,void* context,unsigned limit) noexcept
{
    if(!count || !task)return {};
    // Bound claims at64 KiB. No mutation has started if allocation fails.
    std::unique_ptr<std::atomic<unsigned char>[]> claimed;
    if(!inside && count>=2 && count<=65536 && concurrency(limit)>1)
    {
        try{claimed=std::make_unique<std::atomic<unsigned char>[]>(count);}
        catch(...){/* Complete serially without partially applied work. */}
    }
    if(!claimed)
    {
        Scope scope(nullptr);
        for(std::size_t index=0;index<count;++index)task(context,index);
        return {1,1,false};
    }
    for(std::size_t index=0;index<count;++index)claimed[index].store(0,std::memory_order_relaxed);
    OnceWork work{task,context,claimed.get()};
    return parallel_for(count,1,OnceWork::run,&work,limit);
}
#ifdef LZ_CPU_JOB_TESTS
void test_fail_after_blocks(int blocks) noexcept{failure_after.store(blocks);}
#endif
}
