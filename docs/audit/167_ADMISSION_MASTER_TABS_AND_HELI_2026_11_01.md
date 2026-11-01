# Follow-up: admission, master tabs, observer animation and Mi-24

Status: implementation in progress, not released. Previous release 2026.11.01.1 is delivered (audit 166).

## Confirmed failures

The owner server log at `J:/LostZone/Lost Zone/appdata/server/logs/xray_srv_l01_escape_mahito.log` reports checkpoint submission refusal immediately before character-selection refusal for two accounts. The NCHA writer and both master decoders were updated, but the native checkpoint worker and upload/download envelope still rejected every format newer than NCH9. The native worker now shares the envelope validator; both accept exactly NCH3..9 and NCHA. Unknown formats remain refused. Coordinator admission and durable outbox tests now send actual NCHA fixtures through the master, including resume and transfer, rather than exercising only NCH9.

The hidden console and hidden lists were re-shown when background updates sent WM_SETREDRAW(TRUE), which adds WS_VISIBLE in DefWindowProc (Microsoft documentation: https://learn.microsoft.com/en-us/windows/win32/gdi/wm-setredraw). Redraw batching now runs only for controls that were visible before the update. The native GUI fixture now appends real log text and replaces list rows between every tab switch before asserting visibility.

Native compilation and fixtures run only in GitHub. No owner game/server/master is launched for tests.

## Delivered urgent follow-up

Release 2026.11.01.2 is published and installed in the owner client and public server folder. Native commit `be1423662e8e8fd4733705d4ea143721b1906b51`, run `41344514845`: all mandatory DX11 checks, compile, package and private preservation passed. This run exercises actual NCHA captures, resume and transfer. Executable SHA256 `c68c3498d4fcb150d24fe247af293184ac425749fa8446a32a13ab88f7b1b11b`. Production master from the same commit, run `41344434446`, passed its GUI/background-update fixture and parity/storage/process checks. Resource bytes remain exactly the checked 000049 data of 6b26b802a; later helicopter work is excluded.

Signed client manifest `manifests/2026.11.01.2-780d5c0e.bin`, BLAKE3 `780d5c0e127b9def62b7c58e61961e2fa435b5f546db2cfd53aa0cc6cfebb78b`, 142 files. All changed files reconstructed from published chunks; signature valid, P2P online. The distribution process was stopped when publishing began; the existing distribution executable was started hidden with --no-browser (PID 83596), without launching a game or world master.

Public `J:/LostZone_Work/Lost Zone Server.zip`: 2,718,811,843 bytes, 41 files, all hashes and CRC verified, SHA256 `4448338c3ee3db82b10fed87209fef66e23641ac6e07359845e4ded110472767`. Client/server/save preservation and delivery receipts: `J:/LostZone_Work/_work/world_hotfix_20261101_v7`. No local game tests were run.

## Next source work (not part of .2)

Full original Mi-24 airframe/rotor mesh retained, split into 16-bit draw chunks without decimation. Three new rigid landing-gear assemblies and eight independently hideable, ray-pickable/no-physics glass groups. Gear hydraulic travel and physical collision shapes share a position; server validates pilot ownership, weight-on-wheels/power lock, emergency extension and touchdown damage. N/night-vision binding toggles gear only while seated. Manual Mi-24 collective/attitude control replaces automatic height/level holds; slow spool, wheel-plane ground probe, supported-weight friction and bounded server weather forces. Mi-2 retains assisted controls.

The body normal maps retain original 4K resolution; detail/rotor source normals remain 2K. DX11 helicopter-only material adds weather-driven glass drops/trails; legacy renderer fallback retains normal transparency. Real shader compilation and native flight/gear fixtures are required before release. Actual in-game appearance, flight model, gear collision and bullet/glass geometry still require owner testing.

Observer animation work resets old-model RP/use caches, provides a missing-specific-motion fallback, and logs body/movement/held item/clip phases. Pistol poses accept generic BAS pistol classes by grip, independent of magazine capacity, and exclude binoculars/knives. A separate authored prone set is being visually checked; it is not yet enabled or delivered.


Prone source update: 20 original full-body clips (empty/knife/pistol/rifle, idle/forward/back/left/right) now use an analytic two-segment joint solve on the common human bind skeleton. They are isolated `lz_prone_` names, so existing NPC animation names are untouched. Partition bone mappings match the main actor OMF exactly. QA receipt `167_PRONE_POSE_QA.json` binds sampled low head/foot positions and gait variation to the exact OMF SHA256; offline Blender frames of empty and rifle poses were inspected. Native low-stance selection, overlay preservation, grip/direction changes and recovery still require GitHub execution; multiplayer appearance is not locally tested.
