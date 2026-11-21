# Empty-server save retry after sub-minute idle delays

The native Master starts locations with-netcoop_hibernate=1. On a failed durable world save, warm hibernation previously encoded its next retry as empty_since=now-after+60000. For a one-second delay this is a timestamp in the future; unsigned elapsed subtraction makes it appear already overdue on the next frame. The server could repeatedly serialize/save every frame while the backend is failing, never reaching its intended sleep. Cold idle exit has the same defect when configured below60seconds.

Retry now has an independent monotonic last-attempt timestamp and explicit retry state. All failed cold-stop stages, including receipt/status-file locks, wait60seconds before another expensive save. New/joining players or closed admission reset the timer and prevent sleep/exit. The world must still save successfully before trimming, sleeping or quitting. No process is force-stopped, no save/ownership guard is removed and no promise is made to release commit through working-set trimming.

CI compiles the actual warm/cold functions with controlled save/client/admission/file-lock inputs. It covers a1second delay, tens of thousands of failed-save ticks, exact60second retry,32bit timer wrap, receipt/status ordering, reconnect wake and admission barriers. Warm trim/sleep are intercepted in the fixture; no real game, process trimming or sleep is executed locally. Evidence pending at this commit. This fixes a concrete retry busy-loop, not every remaining server hibernation/memory issue.

HOM CPU preparation remains under full DX11/DX8 ABI validation on be51ce840/44926913355; new server code is a later source and needs its own full build. Publication stays deferred; installed84/public80 remain unchanged.
