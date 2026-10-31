# Startup crash, stale launch requests and unified console

## Evidence

The owner's 31 October dedicated-server dumps match engine commit
`71cf107cf06e8abace2b6c11624ee3fa45e9a00b`, GitHub build `41129739664`.
The private PDB archive was checked against the authenticated CI metadata.
The faulting instruction resolves to `CALifeTimeManager::game_time`, with
`rcx == 0`. Stack addresses also resolve to `get_time_struct`, a Lua callback
and `CALifeSimulator` construction at `start_game_callback`.

`CALifeSimulator` publishes itself to AI before this callback. The callback
runs before `load/reload` allocates `m_time_manager`. The previous time API
checked only whether the simulator existed. This crash is separate from
the earlier `system.ltx` archive-order defect, already fixed in release .3.
No private dump, account data or credentials were uploaded.

## Changes

- `__game_time` reads ALife only after `initialized()`. Otherwise it reads a
  ready level, or a validated, read-only configured starting calendar.
  This fallback never initializes or resets the persistent world clock.
- Day/hour/minute Lua helpers use the same safe fallback while the level
  game state is absent. The first premature request is logged once.
- Background location fatal errors retain logging/crash capture and end
  with a nonzero process exit instead of waiting behind a modal dialog.
- Opening a master cancels persisted starts/restarts/automatic modes and
  wake files for locations without a live matching process. Adopted live
  servers and pending stop requests are retained. A new explicit start is
  required for previously queued, unstarted locations.
- PID display accepts signed and unsigned positive JSON integers within
  the Windows PID range.
- The standalone master opens a black, monospace, unified console by
  default. Command results and incrementally read location logs share one
  view and journal. Location lines have `[location:<map>]` tags. The reader
  bounds initial history, per-tick reads and unfinished lines, handles
  CP1251/UTF-8 and truncation, and avoids reading the master's own journal.
- Sensitive diagnostic filtering also covers prefixed names such as
  `sv_password`, before console/file/stdout delivery.

## Verification and release

Engine commit: `c55dd8244e54ea8d4250fb3420fca5217041b7e4`.
Engine CI: <https://github.com/Gostn1ght/hueta/actions/runs/41207431425>.
Standalone master commit: `d2e0639246825747723a36ff470ab64ff99016bd`.
Master CI: <https://github.com/Gostn1ght/hueta/actions/runs/41208495999>.

Native fixtures run only in GitHub Actions, without a game or location
process: partial/null simulator and level, configured/leap calendars,
committed clock priority, teardown, unattended errors, saved request
cancellation, IPv4/IPv6 process adoption, merged log routing/encoding,
partial lines, no duplicate reads, truncation and bounded history.
The master CI also exercises the actual window and captures its screenshot.
The window selftest checks positive, negative and overflowing PID integers
through the actual host-view parser.

The .4 candidate keeps protected patch-000047 archives byte-identical;
only native code, release metadata and accompanying text change. Both
client and server require the newly built engine. Do not claim in-game
acceptance: the owner will test the actual locations and gameplay.

## Remaining feature work from the same conversation

The account/character redesign remains separate work: direct 3D-room entry,
inline authentication on character interaction, one character per account,
and a new loner life after death with starter inventory/money and a new
Russian nickname. The owner explicitly confirmed that behavior. These
features are not claimed as included in the startup hotfix.
