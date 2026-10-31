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
All five recent startup dumps (Marsh, Darkscape and Military) have the same
access violation and null clock receiver. No private dump, account data or
credentials were uploaded.

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

Published and installed: **2026.10.31.4**. Both pinned CI runs succeeded.

- Client signed manifest: `manifests/2026.10.31.4-a0d2e7ba.bin`, 138 files;
  Ed25519 signature, BLAKE3 manifest/chunks, reconstructed changed files and
  unchanged protected archive Merkles verified. P2P delivery is online.
- Engine SHA-256:
  `a15ad37d1826deb1e0bf13df8fee8d70ecaf23378c168d675ad2dba522b561a5`.
- Standalone master SHA-256:
  `1a5c1594e4b1731bd712e468eccc3ace6d278ee82ff1e8c85e8f0b3fd331bfa1`.
- Public server ZIP: `J:/LostZone_Work/Lost Zone Server.zip`, 37 files,
  2,717,707,305 bytes. Every archived file's SHA-256 and CRC verified.
  ZIP SHA-256:
  `9cb4fd5f659a2bc72c22bad33291e75f66358f54456adcb41c2cb114427e8a12`.
- Public server folder restored from the reviewed candidate: the owner's
  previous public folder contained only the old README. Its remainder and
  the previous ZIP were preserved separately before replacement.
- Owner runtime `J:/LostZone/Lost Zone` updated with no native process
  running or started. Worlds/accounts were untouched; changed previous
  binaries and metadata were retained. Launcher service was reused.

Private preparation, signature/delivery, ZIP and installation receipts are
under `J:/LostZone_Work/_work/startup_hotfix_20261031_v4`.

## Remaining feature work from the same conversation

The account/character redesign remains separate work: direct 3D-room entry,
inline authentication on character interaction, one character per account,
and a new loner life after death with starter inventory/money and a new
Russian nickname. The owner explicitly confirmed that behavior. These
features are not claimed as included in the startup hotfix.
