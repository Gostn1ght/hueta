# Character handoff, optional vehicle assets and one account/character

Status: delivered as **2026.10.31.5**, data patch **000048**. Native DX11 CI and
offline checks passed; the game was not launched for validation. Previous
release was 2026.10.31.4 with data patch 000047 (audit 164).

## Reported failures and changes

* `CCar::Init` asserted on optional `damage_items.back_door` without a physical
  door. Ignore that optional entry with a diagnostic; real wheel/door damage
  initialization is retained. Missing optional damage-particle bones are
  reported and duplicate entries are ignored.
* An absent KamAZ exhaust effect asserted in the renderer. Query the actual
  particle library before allocating optional car effects, try the common
  exhaust, and safely omit it if neither effect exists. Dedicated servers do
  not allocate visual exhaust. Missing exhaust physics elements are reported.
  The importer and both roles' affected profiles use `vehiclefx\exhaust_1`.
* Character restore, admission, transfer completion and disconnected-account
  cleanup used the once-per-100-frame maintenance path. Poll these every
  100 ms of real time instead. After restoring progress, wait
  for actual equipment placement and a successful script-ready callback.
  Restore failures continue to hold gameplay/saving and retain the checkpoint.
* The old ten-second player-state fallback could send defaults before restore
  completed. Send only after readiness, resend after every incarnation, and tag
  the HUD snapshot with its target actor ID. Ignore another actor's snapshot.
* God mode and unlimited ammunition are captured in the server-owned progress
  image and restored through native role checks. New lives clear both. The
  client clears inherited flags at authentication and receives the server's
  restored values at readiness; role revocation clears both immediately.
* A 200 header without a complete verified body was incorrectly classified as
  a permanent checkpoint authority rejection. Retry the same idempotent
  command without accepting that reply. 403/409 fencing refusals remain final.
  Location leases allow 60 seconds and renew at most five seconds apart.
  Authority diagnostics now report the renewal HTTP status and failure count.
* Master location rows update cells without rebuilding unchanged identities.
  Preserve selection, focus and scroll. Console output follows the bottom only
  while the reader is at the bottom. Layout runs when counts/service status or
  window geometry change. Add isolated CI control-preservation checks.
* Master startup memory uses a fixed small physical budget and each map's own
  measured commit peak. A heavy map no longer raises every other map's gate.
  Empty maps request hibernation after one second. Hibernation does not remove
  process commit; OS/commit reserves are retained.

## Account equals character

Owner confirmed one character for every account, including administrators.
The account and access credentials survive death. After death the player must
choose a different Russian call sign and starts a fresh life as a loner with
starter equipment and money. This is not account deletion.

* Open the 3D room before authentication; account interaction is on the avatar.
  Use a compact nickname card, without a character-slot list or equipment
  picker in the normal entry flow. Keep account recovery and email verification.
* Native requests allow only character slot 1, plus slot 0 for front-end account
  authentication. Existing legacy files in slots 2–10 are retained on disk.
* Existing living saves, including Latin names, remain readable. New call signs
  accept CP1251 Russian letters (including Ё/ё), spaces and hyphens, at least
  two letters, no leading/trailing/repeated separator. Enforce on the server.
* A new life resets the actor image, items, safe, progress and biography; keeps
  the storage revision monotonic; uses the server's mandatory loner kit plus
  PB, novice outfit, flashlight, medkit, bread and mineral water. Starting
  ammunition and money come from the installed freeplay configuration.
* Preserve the old checkpoint if starter validation or saving fails. Faction,
  ratings, bounty and goodwill resets are idempotent and gate readiness.
* Death is saved before returning to the room; the normal disconnect cleanup
  retains the corpse. No automatic new actor is spawned under the old life.

## Verification and remaining release work

Offline Lua checks cover account form/recovery ordering, the new entry flow,
Russian call-sign validation, ignored dead drafts, admin toggle persistence,
readiness ordering, targeted limb state and idempotent faction reset. DCP source
checks cover all 50 imported car models, physical shapes, masses, wheel/door
joints, profile references and seats. This does not establish in-game stability.

CI fixtures execute actual native car initialization/exhaust paths and actual
character selection/restore code, including missing optional assets, real
wheel/door damage, a missing fallback, headless operation, slot refusal, death
reset, save-failure rollback and delayed placement/callback admission. Master
CI additionally checks selection/scroll preservation in real Windows controls.

## Delivery evidence

* DX11 source: `7f2c5635c5535ac757f099bf9de6118c013ef2e4`, mandatory checks/build/package
  passed in [run 41226798422](https://github.com/Gostn1ght/hueta/actions/runs/41226798422).
  Client/server executable SHA256:
  `0cfaaa814babd76e11624dfe4ec50064d2d601ea673f686719b613db6ee360e9`.
* Production GUI master: `6f9a78f10bc84f0d43ed161009c1e43aba99fde8`,
  [run 41226015132](https://github.com/Gostn1ght/hueta/actions/runs/41226015132)
  succeeded, including real Windows list/console preservation checks.
  SHA256: `1208486b9d3c546ba9d732ffdd4417878a429764b32e605357707a41310ab965`.
* Signed launcher release: `manifests/2026.10.31.5-517469f0.bin`, 140 files.
  Ed25519 signature, manifest BLAKE3, file Merkle trees and reconstructed changed
  payloads verified. The previous resource archive hashes are unchanged; two
  client delta archives are added. Publisher is running with the existing node.
* All 35 delta payloads were extracted, compared byte-for-byte to committed
  inputs, and checked for Lua/XML syntax. The server has two corresponding
  dedicated delta archives; these do not enter the client manifest.
* Final hoster folder and ZIP: `J:/LostZone_Work/Lost Zone Server` and
  `J:/LostZone_Work/Lost Zone Server.zip`, 39 files, 2,718,095,373 bytes.
  ZIP CRC and every file SHA256 verified. Final ZIP SHA256:
  `f50a41a3b95a8cc50bef2e2c4bbc473066fcd8ca1ff2dd53c6be68fcca7dc98f`.
* Owner client, location executable, master and all four delta archives are
  installed under `J:/LostZone/Lost Zone`. Account/world data were not changed
  by deployment. No owner game, location or world-master process was launched.

### Dedicated archive precedence regression

Final installation review found that newer server archives placed at the
resources root could be overwritten by older archives in `resources/server`,
which the engine mounts afterwards. Both 000048 server deltas are now in
`resources/server`, alongside 000047, so filename/version order applies within
the role directory. This matters for overlays onto existing hoster installations.

The actual effective namespace was checked for both the final canonical server
and the owner game: all 16 changed server files resolve to 000048. The canonical
packager now refuses server-role archives at the root. A local Python regression
test exercises refusal before partial output and acceptance in the dedicated
directory; it is also added to future CI runs. This packaging-only check was
added after the native build and did not change its C++ source or binaries.

Private byte-verification receipts are in
`J:/LostZone_Work/_work/character_hotfix_20261031_v5`, including
`acceptance-reviewed.json`, `publication-reviewed.json`,
`role-precedence-reviewed.json` and `delivery-reviewed-final.json`.
