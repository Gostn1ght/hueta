# One entry worker/session per menu lifetime (2026-11-15)

Foundation43754737321, source6a713b542, entry-windows: FAIL after30s cleanup.
Process handles190->214. Type enumeration: Event63->87; Thread9->9, File10->10,
EtwRegistration48->48 and all other observed types unchanged. Thus this was
not merely a5s cleanup delay. These observations do not identify the OS/CRT
subsystem retaining events and do not by themselves prove an unbounded leak.

The old route implementation created a new std::thread and WinHTTP session
for every retry/account/slot query. Replace that churn with one persistent,
condition-variable driven worker and one anonymous read-only HTTP session per
menu lifetime. Only one request is outstanding. Results remain keyed by exact
address/account/slot; cache and pending state cannot cross an account switch.
The worker receives copied plain values, never engine objects or Lua. Session
initialization can retry after failure. stop signals, joins bounded in-flight
IO and clears state; MainMenu destructor remains its owner. All HTTP handles
still close in request/connection/session order under EHsc RAII.

Fixture steady-state churn keeps the worker alive across24 alternating bad/good
requests and retains the same strict +4 process-handle budget. Teardown/reopen
stress is a separate12-cycle test, including real200ms server replies joined
after50ms, each with a5s bound. Aggregate process events across repeated new
menu lifetimes are diagnostic, not asserted to be application-owned handles.
This is a change to match the production ownership contract, not a larger
handle budget. Await new remote results before claiming PASS.

Reference: Microsoft [WinHTTP concurrency](https://learn.microsoft.com/en-us/windows/win32/winhttp/concurrency-in-winhttp)
and [WinHTTP overview](https://learn.microsoft.com/en-us/gaming/gdk/docs/features/console/networking/web-requests/intro-winhttp).
The latter documents asynchronous handle cleanup; the30s evidence above rules
out treating this fixture's growth as a short cleanup delay alone.

No live/native/game execution locally. Existing000080 stays installed/published.
Candidate000081 is being prepared separately and is not a release approval.
