# Bounded CPU jobs for client and server (2026-11-16)

Owner request: actual client/server CPU parallelism is the next priority after
the entry-worker fix. Gameplay acceptance will be performed by the owner.

## Boundaries

`xr_cpu::parallel_for` reuses the already shipped TBB runtime, synchronously joins
each batch, caps concurrency at 8 slots and keeps nested/small jobs serial.
Workers inherit and restore the caller's floating-point environment. A scheduler
exception completes/cancels children before replaying the idempotent batch
serially. The exception-enabled implementation has no engine/PCH headers.

Client: `xrCPU_Pipe` binds all four software skinning variants to range wrappers,
instead of only 4W. Existing scalar kernels, source vertices and bone transforms
are unchanged. Each task writes disjoint 512-vertex blocks in the already mapped
vertex buffer; the caller waits before unlock/draw. Fewer than 1024 vertices stay
serial. This does not parallelize GPU skinning, device calls, Lua or arbitrary
`seqFrameMT` callbacks. `-cpu_serial` preserves scalar bindings for comparison.
The soft-skinning caller holds the existing `UCalc_Mutex` before mapping through
task completion/unmap. `CalculateBones` already uses it; both visibility setters
now share it, including recursive visibility changes (Windows critical sections
are recursive). Thus no pose writer may alter matrices consumed by these tasks.
This is an explicit lifetime/data contract, not evidence for an old crash cause.

Server: `SendUpdatesAOI` snapshots plain serialized-chunk metadata and observer
positions. `ReplicationPlan` calculates distance/cadence over these immutable
values in parallel, preserving chunk order and private-owner filtering. Full-rate
creatures/equipment remain full-rate. The owner still performs budget decisions,
keepalive mutations, entity serialization and sends. It rechecks connection ID,
actor ID and position before consuming a selection. Changed or invalid inputs
use the existing serial path. The owner lazily computes each immutable chunk's
hash at most once per frame, after cadence and budget eligibility, instead of
once per recipient. Unsent chunks are not hashed. No persistence/admission/
identity rules change.

The planner requires at least 4 eligible clients and 32768 world-object/client
pairs. Output is bounded at 32 MiB, 65536 records and 512 observers; allocation,
validation or budget failure falls back serially. The previous spatial index
remains opt-in and unchanged. `-cpu_serial` disables planning; optional
`-netcoop_cpu_trace` reports actual used slots/blocks in the replication log.

## Verification

`scripts/check-native-cpu-jobs.py` is guarded for Windows GitHub Actions only. It
compiles the actual new pool and planner, and extracts the actual engine's 1-4W
scalar kernels and wrappers. Matrix/vector boundary doubles isolate the fixture;
full DX11/DX8 builds check actual engine types and linkage.

Checks: simultaneous client/server first-use batches, inherited/restored floating
environment, multiple OS threads, bounded slots, synchronous and nested fences,
serial/parallel skinning byte equality including boundary counts, output canaries,
unchanged vertices/bones, planner equality against a scalar oracle, exact distance
thresholds, unsigned tick wrap, owner-only data, full-rate entities, invalid input,
bounded allocation and invalidation of stale results. Planner serial/4-slot
p50/p95 measurements describe this CPU fixture, not game FPS or whole-server
capacity. Existing frozen legacy-cadence/index checks remain in the full suite.

Wired into both the short Foundation workflow and full native workflow. Local
validation is limited to Python syntax, project XML and diff checks. CI results
and exact source SHA must be recorded separately; no gameplay PASS is claimed.

## Remaining owner requirements

Graphics/settings hot-apply and renderer switching need a separate lifecycle
change: R1 and R4 are currently separate statically linked executables. Do not
claim a working in-session renderer switch from a console `vid_restart` alone.
The owner's DLL-count question is a future packaging task, not permission to
remove runtime dependencies during this CPU change.
