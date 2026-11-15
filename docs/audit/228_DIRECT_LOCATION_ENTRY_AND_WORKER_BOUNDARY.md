# Direct location entry and exception-safe route worker (2026-11-15)

Scope: TASK-E00-012 / TASK-E11-008, adjacent E09/E10 route-worker lifetime.
Baseline engine-restructure / 13a08c531; signed local latest verified as
2026.11.15.1, manifest 5818086bd70da8a55f0aedeab318545bd6c26530363533c6c23ffdfb85a19540.

## Cause and owner path

`netcoop_login_ui.route_addr -> WithRoute/PollRoute -> frontend_auth(slot0)` or
`EnterWorld(slot1) -> native auth -> cluster_on_login -> AdmissionCoordinator.admit`
`-> Master slot/home -> Elsewhere redirect OR authoritative checkpoint -> character_select`.
The menu queried HTTP on every typed port except1267, which it rewrote to5446.
Location ports speak UDP, so direct1319 waited ten minutes without authenticating.
Now explicit location ports reach their game protocol;5446 retains fail-closed
Master routing. No world identity is inferred from a common host or NAT. Per-endpoint
UI drafts/caches are isolated and are not the character authority.

Managed character identity remains world+seed+account+slot. Master admission,
leases/fences, durable bytes and server-side Elsewhere redirects are unchanged.
No migration/deletion of player data, stale checkpoint fallback or new identities.

`master_entry_query/ClientEntryWorker` previously lived in netcoop_client.inc,
compiled as part of netcoop.cpp with ExceptionHandling=false. JSON/std::thread
exceptions had no normal C++ destructor unwinding; the old fixture compiled
extracted code under EHsc, masking that production mismatch. JSON/HTTP/thread
ownership now lives in netcoop_entry_worker.cpp, EHsc and no PCH. A fixed buffer,
noexcept interface crosses back into the engine. Thread creation failure leaves
the worker idle/retryable, not permanently done=false. Internet handles use RAII.

A253-byte advertised hostname formerly passed validation but exceeded string256
when formatted with its port (MSVC invalid-parameter handler). Host/port/buffer
budgets now agree. Embedded NUL hosts, overflowing ports, deep/oversized/partial
responses and wrong schemas are rejected; HTTP redirects are not followed.

## Checks and limits

Local actual Lua menu fixture PASS, including explicit1267/1319/65535,
account/world isolation and numeric/string5446 wait/error/cancel semantics.
Lua scope PASS; Python syntax and git diff checks PASS. Native tests run ONLY
in GitHub Actions: compile the actual transport translation unit and verify
its project EHsc/PCH properties, real WinHTTP replies, malformed input,
handle stability, recovery and joined in-flight shutdown. Exact run pending.
No game launched. No release/install performed. Tasks remain open to game PASS.

The LuaJIT source explicitly documents asynchronous lua_sethook; watchdog changes
were rejected without a reproducer. No claim this identifies the Radar crash.
The newest local client log had no fatal-error markers; it is not crash evidence.
Next: exact-SHA CI, then matched two-client direct-port/reconnect/cross-map acceptance.
