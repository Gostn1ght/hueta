# Native master: memory admission and cancelled launches

Owner report: locations display "ждёт память" before selection; pressing Start
does not start a process. Actual host snapshot: zero location PIDs, 5.68 GiB
remaining after the old fixed 3 GiB reserve, 17.38 GiB commit headroom after
that reserve, and a fixed 6 GiB requirement for both. Thus 8.68 GiB available
physical RAM could not start even the first dedicated process.

Changes are confined to the standalone native master and its fixtures/UI:

- Physical and commit admission have separate estimates (initially 1.5/3 GiB).
  Physical OS reserve is 10% of installed RAM, clamped to 0.5–2 GiB; commit
  reserve is 1 GiB. Observed peak working set/private commit of running maps
  increases the respective estimate, with 20% headroom. These are admission
  estimates, not guarantees that every map fits or all locations run together.
- Keep serial loading and genuine physical/commit shortage blocking. Publish
  available, required and reserved quantities; display an actionable Russian
  explanation in the location detail instead of an opaque budget error.
- Missing/invalid persistent mode means off. Explicit on/auto/off survives
  restart; a running server adopted without a mode file is preserved as on.
  A fresh master does not start warm locations before an operator's request.
- Cancelling an unstarted map transitions it to stopped immediately. Previously
  the off branch skipped state updates, retaining the memory/queue label.
- The UI distinguishes a requested launch from an actual loading process and
  shows stopped maps as off even when an expired lease exists.

Native executable regression checks run only in GitHub Actions. They exercise
the actual controller with the observed 8.68 GiB case, independent RAM/commit
shortage, learned peaks, manual defaults (including a warm map), cancellation,
and reaching CreateProcess with sufficient budget. The fixture deliberately
has no game executable. No local game/location test is required or claimed.
