# Candidate 169: vehicle platforms and recurring transition failures

Not released. Installed public version remains 2026.11.02.5.
Native builds and execution of native fixtures are restricted to GitHub Actions.
No owner game/client/location/master is launched for testing.

## Fresh evidence
Read-only copies of the local 17:56 crash and location logs are retained privately
in J:/LostZone_Work/_work/bugs_20261102_latest. Exact c7fcbdc64 PDB resolves
0x1400b7e4d to CObjectList::SingleUpdate, xr_object_list.cpp:128. Exception stack
includes recursive SingleUpdate and CGrenade::UpdateCL; preceding diagnostic:
child 26372 grenade_rgd5 still parented to destroyed inventory grenade 23554.

Online grenade cleanup now waits for child reject; fuse starts after release.
Packed destroy/reject events preserve the source timestamp. Missile relcase
clears both hidden-child pointers and a deleted parent before recursive update.
CI fixture exercises actual relcase ownership cleanup, including repetition.

PDA StopAnyMove now blocks DialogHolder's secondary gameplay forwarding path.
A bounded watchdog completes stalled PDA show/hide animation callbacks.
Noclip reads live camera orientation, rotates the body, moves at 16/64 m/s;
server speed budget changes only for server-authorized noclip.
Admin teleports fence old owner snapshots until the destination is acknowledged
by an owner position, bounded to three seconds.

BHS caches progress widgets and scuffed_fix/timers across replacement game UI.
Its new per-connection reset drops UI references and previews without healing
limbs; authoritative limb restore remains separate. DotMarks likewise discards
old widgets, pending interactions and deadlines after location clock reset.

## Four active requested items — implemented candidate, not installed
- All 50 actual donor meshes inspected offline in Blender (full cutaway contact
  sheet, enlarged bus/van/truck interiors and bind-space measurements). Explicit
  layouts now contain 247 seats, range 1–24, with passenger pelvis normalized to
  zero and side-bench yaw. Buggy is one seat; PAZ 24, PAZ3206 12, ZIL131 13.
  Audit 169_FLEET_SEATS_AND_DECKS.json records each model hash and layout count.
  check-netcoop-dcp validates exact coverage, config parity, unique positions,
  named model bones, physics profile and imported layout equality for all 50.
  This is geometry evidence, not an in-game seated-body clipping acceptance.
- Standing decks: three contacts on an actual horizontal vehicle collider,
  previous/current rigid frame transport, bounded car-history owner validation,
  walking relative to the deck, point velocity inheritance and departure budget.
  Applies to flat supported surfaces throughout the fleet, not just ZIL131.
  Nearby observers receive separate car-local rider positions; their render
  placement follows the same interpolated vehicle pose. Destroy/death/jump/
  noclip/seat transitions detach. No extra invisible seat for standing riders.
- Prone: 20 authored grip/direction cycles retained byte-for-byte. Standing
  foot IK and spine/head callbacks bypass authored prone and vehicle poses.
  Actual human mesh rendered offline with four rifle crawl phases and entry
  poses. The renderer confirms moving limbs and low body; live network and
  terrain animation acceptance remains for owner testing after native delivery.
- Entry/exit/open/close/steering: server reserves a real seat, opens the nearest
  enterable physical door, runs a 1.8-second body/eye transition and closes the
  door. Exit is preflighted and rechecks a clear standing volume at completion.
  Five authored vehicle clips appended to the existing shared animation file;
  hand reach pulses, driver/passenger poses, exit reverse. Third-person and
  first-person full body follow the same seat frame. Steering reads actual
  wheel angle and freezes the corresponding authored pose by angle. This is
  a generic transition, not model-specific mocap/hand IK for every doorway.

## Verification and release status
Installed public version remains 2026.11.02.5. No owner game, client, location
server or master was launched for tests. Native builds/fixtures run only in CI.
Full CI 41488364942 at f916b80af995df971acc107c341cb281f1aaa79b:
resource checks and DX11 shaders succeeded; engine job stopped before the main
build on two outdated test harness assumptions (teleport actor/world stub lacked
new platform/fence members; exit check expected the old immediate-unseat call).
Other actual native fixtures passed, including three-contact/history platform
validation, manual ignition/held pedals/transition reservation, projectile
attachment/relcase cleanup, prone selector and 11520 PDA routing cases.
The harnesses now include the new state and phase completion checks; full CI
must be rerun and all mandatory gates succeed before binary packaging.
Offline all-fleet and animation checks pass with the latest 247-seat layouts
and rebuilt five vehicle clips. Local Windows dummy batch test timed out;
Ubuntu full resource CI passed, no native-test exception was taken.
