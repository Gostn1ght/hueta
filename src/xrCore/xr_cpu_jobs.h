#pragma once
#include <cstddef>

namespace xr_cpu
{
using RangeTask=void (*)(void*,std::size_t,std::size_t) noexcept;
using IndexTask=void (*)(void*,std::size_t) noexcept;
struct BatchStats {unsigned slots=1;std::size_t blocks=0;bool fallback=false;};
// Synchronous fence over the existing TBB pool, capped at8 CPU slots. Tasks
// receive immutable inputs and disjoint output ranges; no Lua, engine objects,
// network/device calls, mutation of shared state or background lifetime.
// An idempotent task may be replayed serially after scheduler failure.
BatchStats parallel_for(std::size_t count,std::size_t grain,RangeTask task,void* context,unsigned limit=0) noexcept;
unsigned concurrency(unsigned limit=0) noexcept;
// For disjoint mutable domains (e.g. independent physics islands). Each index
// is claimed once; scheduler fallback completes only unclaimed work. The caller
// freezes topology/lifetimes until return. No engine callbacks/shared mutation.
BatchStats for_each_once(std::size_t count,IndexTask task,void* context,unsigned limit=0) noexcept;
#ifdef LZ_CPU_JOB_TESTS
void test_fail_after_blocks(int blocks) noexcept;
#endif
}
