# Truncated entry response, actual CI evidence (2026-11-15)

Foundation43753726005, source370986261: actual CheckpointWorker fixture PASS
inside the Windows step. Real native_save HTTP delayed400ms:162 samples,
submit36.6us, paired status/poll p95=5.3us/p99=7.7us, peak1 capture/246bytes,
heartbeat delta2, joined shutdown0.1832ms. Disk-refusal, durable replay,
concurrent producers,32jobs/64MiB and fencing checks also passed. These numbers
do not measure game frame time or target server population.

The overall Windows job FAILED afterwards in the extended entry fixture.
A truncated reply with a syntactically complete JSON prefix was accepted:
WinHttpReadData can report EOF, so EOF alone is not adequate HTTP completion
proof. Match the exact bounded Content-Length, as the native writer already
does. Master always emits Content-Length. No fallback on a partial response.
Add the failing case name to fixture output. The process-handle check was not
reached in that run and remains unproven.

097e30ab5 / DX11 run43753976101 used the superseded EOF-only code and must not
be accepted. Revalidate actual source in Foundation and full DX11/DX8 CI after
this change. No game/local native execution or live delivery. Existing old
dump13004 is the already analysed000075 startup diagnostic (audit225), not fresh
Radar evidence.
