# Parallel physics island solver phase

User priority: complete client/server CPU work before renderer switching and the deferred crash/memory queue. Local game/native execution remains prohibited; native validation runs in GitHub Actions only.

CPHWorld keeps collision, island merging, Lua/gameplay callbacks, island reinitialization and spatial updates on their original owner. After collision/tuning completes, independent active island roots can solve synchronously in the bounded shared CPU pool. Existing exact versus QuickStep policy remains unchanged. Large islands stay on the owner because ODE uses stack scratch; worker bounds are 64 bodies and 24 exact or 128 QuickStep joints. Small batches retain the original path.

ODE body integration defers geometry notifications per thread. After joining all solvers the owner flushes geometry changes in original root/body order, avoiding concurrent writes to shared collision-space dirty lists. QuickStep has a scoped per-island seeded shuffle stream, so scheduling cannot choose the random stream. This changes the previous nondeterministic random sequence, not solver equations. `-cpu_physics_legacy` restores the original phase; `-cpu_serial` keeps the same seeded batch on one thread. Debug builds retain their original instrumentation sequence.

Mutable solver jobs use the new at-most-once API: a scheduler failure after some blocks completed cannot advance bodies twice. Allocation and root validation happen before mutation. Duplicate roots and invalid inputs reject the batch before stepping.

CI fixture compiles the actual vendored ODE and coordinator. It compares direct ODE, serial batch and parallel batch for 120 frames including contacts, joint feedback, mixed solver types, a large owner-only island, injected partial scheduler failure and shared-space AABB refresh. It also checks maximum allowed six-row joints on a 512 KiB stack and rejects duplicate/invalid input before mutation. Foundation and full native workflows include it. Native results are pending at this commit; no game acceptance, FPS or server capacity claim.
