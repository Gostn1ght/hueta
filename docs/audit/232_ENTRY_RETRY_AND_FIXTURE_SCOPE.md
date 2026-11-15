# Entry retry semantics and current evidence (2026-11-15)

Foundation43755218687 on d31d96f43: all3 jobs PASS. Actual entry worker
steady churn169->162 handles and Event43->38; malformed/truncated/deep/bounded
responses, account cache isolation and12 joined stop/reopen cycles PASS.

Full DX11 run43755237084 on the SAME source passed checks/shaders and repeated
the same169->162 handle result. It FAILED later in a stop/reopen assertion
that expected the first valid LAN reply always to succeed. The fixture's
200ms simulated server delay left only300ms scheduling slack under the actual
500ms production transport timeout. The public protocol explicitly permits
`wait|master_unavailable||3` and the real Lua UI waits/retries that state.
Do not increase production timeouts or accept a wrong route to make CI green.

Fixture correction: normal replies50ms, deliberate in-flight cancellation
still200ms; positive responses follow ONLY the explicit retryable unavailable
state with its3s delay and a15s cap. Malformed/truncated/redirect negative cases
still require unavailable without falling through to any route. Add an actual
first503/empty-response -> successful next request scenario, and keep the exact
same handle budget. Expected broken-pipe errors after deliberate cancellation
are ignored by the fake server, not production transport errors.

This changes tests only. Native production code remains exactly d31d96f43.
The full DX11/DX8 build is still required and no failed/cancelled run is an
accepted artifact. Full byte validation of186 client baseline files and the
canonical server whitelist completed in isolated000081 staging. Nothing was
installed or published. Resource archives must be compared against canonical
Git bytes (working-tree CRLF differs from Git LF); do not claim byte identity
without that comparison.
