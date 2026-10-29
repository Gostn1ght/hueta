# 155. Character handoff and RP regressions, 2026-10-29

Continue `engine-restructure`, based on b4f532db2. Do not resume the old
`engine-steamnet` or `engine-master-cpp` worktrees. No game was launched.

## Evidence

Owner supplied the hoster's startup/location logs in Downloads. Cordon and
Pole assert in `calculate_config_sun_dir` after a 553484-second calendar catch-up.
The sun normalization fix is already in 60822625d/current source; those logs
do not establish that the hoster installed its binaries. Garbage also has a
separate out-of-memory failure. This patch cannot claim to fix OS memory
exhaustion or every unsymbolicated client exception.

## Changes

- RP walking used the explicit-partition `PlayCycle` overload, whose interface
  defaults its speed argument to zero. Play both partitions with their actual
  motion speed and loop them, cache only successfully started motions.
- Pistol/long-gun poses select matching equipped firearms across slots; a knife
  or device cannot satisfy a firearm requirement. Wait for asynchronous weapon
  activation before the intro. Add pistol requirements to the sentry and suicide
  *emote* (no death/damage action); add inventory requirements and cosmetic props
  for food, binoculars, guitar/harmonica, radio and measuring instruments.
  The importer retains these requirements on reimport.
- Client player state can arrive before its Actor: retain it until spawn;
  reset reporting readiness on Actor replacement. Include BHS limb health and
  temporary healing, restore both module tables and first-update pstor keys.
  Report every five seconds and flush before the reliable ordered changer
  request. A fresh body does not retain the former body's damaged HUD.
- Rebase condition elapsed time after a large calendar discontinuity. Normal
  accelerated/scheduled updates and single-player elapsed time are unchanged.
- Clear pending item snapshots, known versions and owner report baselines when
  disconnecting from a location.
- With a configured master, admit only after successful master admission;
  never fall back to an old local body on master timeout. Select the character
  after the master image arrives, so a broken/stale local backup cannot reject
  a valid master checkpoint first. Always download an existing master revision,
  even if a local file hash matches: that does not validate the process cache.
- Parse master NCH images directly in bounded memory with the same checked
  decoder used by legacy files. Replace the cache only after complete decoding;
  malformed replies never overwrite disk backups. Refuse save/handoff when
  the checkpoint worker refuses its capture.
- Bound partial restore to 60 seconds, preserving the previous checkpoint.
  On disconnect discard partial copies, release the account/session and clear
  restore/cache state; do not retry saving an incomplete body forever. Existing
  live-body save failures still retain the Actor and retry without losing items.

## Verification / delivery

Local Lua/asset checks: player-state, respawn, RP assets, item state, backpack
animation, inventory compatibility, trade, live role/dialogue, third person,
server HUD and Lua scopes pass. New/expanded actual-body native fixtures cover
RP selectors/playback, condition time, item cache reset, memory NCH decoding,
master admission, partial restore timeout and disconnect cleanup. Run them and
the full engine build **only in GitHub Actions**.

Not released yet. Current published delivery is 2026.10.25.2, native 25afdf144,
resources 000042. New native and resources must be pinned to a successful CI
commit, then packaged/signed with the existing release tools. Keep owner and
hoster saves; no account/world deletion or automatic game launch.

Doc 154 is still incomplete: master-backed runtime admission/checkpoints are
improved here, but local character mirror writes, front-end detached inventory
and slot-list reads, master A-Life blobs, archived config IO, native location
watchdog and clean server packaging still need migration/verification. Do not
describe all seven stages or all reported crashes as completed.
