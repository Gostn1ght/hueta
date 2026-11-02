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

## Four active requested items
- Seats: native ceiling raised to 64, importer no longer invents a second
  seat for one-seat models. Actual fleet config corrections still pending.
- Moving decks: candidate three-contact car support, previous-to-current rigid
  frame transport, local walking validated against bounded car history,
  velocity inheritance and a short server departure budget. Needs CI and game QA.
- Prone: authored poses bypass standing foot IK and spine/head callbacks;
  visual QA and playback-speed verification pending.
- Enter/exit/open/close/steering: full animation phase and first-person body
  integration still pending; do not claim this item complete.

Offline Lua state, vehicle, source/model audit, respawn and scope checks pass.
No vehicle models, textures or authored clips have been changed in this candidate.
