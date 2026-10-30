# 160. Hoster startup, stopped maps and missing DCP particles

Continue after release 000045. No game, location server or world master is
started locally for testing. The owner is doing gameplay tests himself.

## Evidence supplied on October 30

- Hoster client `xray_Антон (1).log`: fatal at DX11 cube texture creation,
  `dx10Texture.cpp:451`, insufficient memory, two 12,583,063-byte OOM reports.
  Its executable image is 40,259,584 bytes, built October 30 under `hueta`.
- Yantar reaches local connection/configuration, then disconnects and enters
  the 3D menu at 6.8 seconds. Bar, Agroprom underground and Pole also show
  normal disconnect/teardown, not a recorded fatal exception. These logs do
  not establish who originally requested each disconnect. New diagnostics
  distinguish window close and unexpected loss of the dedicated level.
- Some still-running maps report the required master unavailable. A stopped
  master must not be mistaken for a functioning authority merely because its
  GUI process exists.
- Owner Cordon car-spawn failure: missing particle group
  `vehiclefx\exhausts\exhaust_kamaz`. The owner's log still has the older
  40,210,432-byte executable with `AnomalyMP` source paths. A launcher update
  is required for the new native fixes too.

## Changes

- Read the installed base `particles.xr` offline, verified its archive CRC,
  and catalogued all 2,225 effect/group names. The KamAZ effect exists as
  `vehiclefx\exhaust_kamaz`. Correct 14 profiles on each side; update the DCP
  importer so a future import cannot restore the broken alias. Validate every
  vehicle profile's particle references against the real library catalogue,
  in addition to the existing 50-model physics/seat audit. Do not replace the
  game's particle library or substitute an unrelated visual effect.
- Watchdog startup no longer blocks its entire control loop while a map
  loads. Every initial/queued/restart launch uses one serialized load queue,
  private committed-memory accounting and a minimum 6 GB loading budget.
  Commands remain responsive during load; stopped maps stay off. Claim command
  files by rename so retiring one cannot delete a newer request.
- Recheck late readiness after the old loading timeout. Retry unexpected
  exits after a delay; three consecutive failures stop automatic retries until
  an explicit start. Keep exit code/retry state visible. A deliberate clean
  close of a running console stops its automatic respawn.
- Explicit master stop pauses future map launches; starting its service
  resumes the queue while preserving individual maps' off modes. Reject new
  map starts while the master service is stopped. Existing map processes are
  not forcibly killed and world/account data is not reset.
- Watchdog launches carry `-netcoop_background`; device/window updates honour
  it and avoid activation. Dedicated instances do not process gameplay keyboard
  input. A dedicated instance that loses its level exits instead of remaining
  in an unusable hidden 3D menu. Controller logs classify this as a failure.
- DX11 texture creation retries only memory failures, at most three times,
  using lower DDS mips or the loader's documented resize of a mipless image.
  Both cube and 2D paths use it; format/cube flags and real image content are
  retained. Normal successful loads keep their original resolution. Other
  errors are not hidden, and exhausted retries retain the original failure.
  This does not guarantee operation when the system cannot allocate memory.

## Validation / delivery

Local offline checks pass: actual PowerShell control/queue logic with its
process API replaced by an inert fixture, persistent stops and master pause,
loading cancellation commands, serialized memory gate, late readiness,
failure backoff/quarantine, reset by explicit start, lost-level classification,
command replacement race, master argument quoting, menu and DCP references.

New CI fixture compiles the actual texture retry header and dedicated input
method; checks unchanged success/non-memory failures, cube flags, available
mips, mipless resizing, bounded retries, tiny images and invalid LOD bounds.
Native engine compilation and publication are still pending at creation of
this document. Do not call this a completed gameplay acceptance.
