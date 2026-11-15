# Slow checkpoint transport measurement (2026-11-15)

TASK-E10-001. Extend the existing actual CheckpointWorker/real durable HTTP
Master fixture, without changing production queue/lease behavior. A separate
loopback HTTP proxy delays each native_save command by400ms while lease renewals
use independent requests without that artificial delay. The fixture samples
producer submit and paired status/poll calls for2.5s, reports p95/p99 in us,
peak count/bytes and heartbeat delta. A conservative100ms producer/p99 bound
detects accidental synchronous network IO, not a gameplay frame budget.

The same worker then experiences an exclusive outbox file lock for3.5s; its
heartbeat must continue, accepted bytes remain owned and latest generation is
restored exactly. Report joined shutdown duration with a5s bound. Existing
32-capture/64MiB budgets, concurrent producers, disk replay, wrong world/fence,
lost Finish and hard process death checks remain. These are fixture measurements,
not in-game frame times, target-population throughput or emission profiling.

New entry-worker boundary tests also include a200-byte valid hostname and a
truncated response whose prefix is valid JSON, in addition to malformed/deep
JSON,253-byte host, embedded NUL and overflowing port. The Foundation Windows
job compiles the actual isolated transport module under its production EHsc
contract. No game/GPU or native fixture is launched locally.

Local Python syntax/diff checks PASS; remote exact-SHA results and metrics
must be recorded after CI. Production source remains byte-identical to e49340440.
No release/install. E10 acceptance stays open until required target-load/game
frame evidence exists.

First full CI43753138362 failed the entry fixture's immediate process-handle
comparison after HTTP churn. The actual module compiled, but that failure
prevents accepting its runtime. Refine the fixture with settled before/after
samples, a bounded5s cleanup wait and explicit counts; do not change production
code or relax the handle budget to hide the failure. Await actual results.
