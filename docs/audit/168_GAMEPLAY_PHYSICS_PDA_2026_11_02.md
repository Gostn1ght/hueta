# Gameplay follow-up after 2026.11.02.1

Status: PDA work released in 2026.11.02.2; follow-up 2026.11.02.3 is being
validated. Vehicle, loose-item/corpse physics, prone and PDA rendering work
remain open. Offline checks do not establish in-game acceptance.

Owner evidence: eleven attached screenshots, 2026-11-02. The previous isolated
fixtures did not establish game acceptance. In particular the added primitive
Mi-24 wheels visibly duplicate original, textured, stowed landing gear.

Required work:

- Replace the bad crawl motion/pose with an acceptable full-body crawl, with weapon grips.
- Mi-24: use and articulate original landing gear, remove added cylinders;
  investigate floating body, contact geometry, balance and ground state.
- Physical contact for tracked vehicles, not just a visual track shell.
- ZIL-131 cargo-bed seating and walking/riding on its moving platform;
  increased damage after falling off it.
- Vehicle HUD controls, horn with NPC response, handbrake.
- Vegetation bending under vehicles and walking actors, with recovery.
- Loose-item friction, pushable weapons and corpses, sleeping/waking physics;
  restore Shift+F corpse dragging with server authority.
- Mutant contacts must not launch players into the air.
- Consistent world-anchored interaction prompts for items/actions/vehicles.
- PDA screen: angle transparency and remote black screen.
- PDA marks can be created and remain on their own physical device.
- Each physical PDA has independent photos and other device data, including
  switching devices, transfer, reconnect and interrupted photo capture.

All native compilation and fixture execution remain in GitHub Actions. No
owner game/client/location/master is launched for testing without a new request.

Initial finding: `netcoop_pdanet_photo.script` indexes gallery files by
`netcoop_pdanet_client.me.uid`, which is the character/network identity, not
the physical PDA UID. Its asynchronous capture also resolves that UID again
when committing a completed photo, so a device switch can misattribute data.


Owner additions: all physical PDA data is isolated, with a data USB drive for
explicit copy/restore and a separate decryption USB; gameplay keys must not leak
through the open PDA, Escape closes it and editing keys remain usable.

PDA implementation (released in .2; subsequent refinements pending .3):

- The actual `held_device` local forward declaration was never exported. Real
  logs repeatedly showed `netcoop_map_known:144` and `netcoop_pda_store:8` calling
  nil. Exported it; fixtures now load the actual network module for this API.
- Profiles, network number, contacts, requests, private/group chat membership,
  notes, password and stash discoveries now use persistent physical item UID.
  Old account records are claimed once by one device, with a durable completion
  marker so removing a password/resetting a PDA cannot resurrect legacy data.
- Map pins and discoveries follow authorized physical devices. Password/foreign
  device closes access. Old map table literals are parsed as bounded data,
  never executed. Photo completion checks its originating physical device.
- Gallery and dictaphone indices/pixels/audio are stored by the server; background
  uploads acknowledge persistence. A cache-free client can fetch the same device.
  Locally pending media remains device-specific. Legacy local media is migrated
  only for the one server-designated legacy device.
- Every network response carries the physical item ID/UID; late replies for a
  removed object are rejected. Cached UI drafts/selections clear when switching
  devices, factory resetting or importing data.
- Real native store keys forbid `.`. Existing audio/photo chunk keys used dots
  and writes were unchecked: replaced them with underscores, check writes, and
  enforce the actual 96-character/key and 64-KiB/value rules in Lua fixtures.
- `lz_pda_data_usb`: one backup per unique physical flash drive. Data includes
  pins/discoveries, contacts, notes, preferences, gallery and recordings, stash
  data and full current private/group chat histories. Chat copies are read-only
  archives; no private-chat membership, password, hardware serial/network number,
  friend requests, character progression or money is cloned. Imports replace
  personal data but retain the target's own live conversations and identity.
  Archives are paged/chunked and restored with media access to copied attachments.
- Backup sections have checksums. Restore and factory reset use a durable journal;
  recovery completes before exposing the profile, including after changing maps.
- `lz_pda_hack_usb`: five successful timed decryptions; real inventory parent and
  unique tool UID checked; changing/removing the PDA/tool or death interrupts it.
  Protection/password affect duration; remaining charges persist between servers.
- New Data and USB tab: choose an inventory flash drive, backup/confirm restore,
  charge display, refresh and imported conversation archive. The two flash drives
  reuse verified supplied flash-drive meshes and icons as ordinary inventory
  objects, with stock in Lost Zone mini-trader catalogues.
- Native input gate consumes PDA press/release/hold before RP/gameplay callbacks;
  letters/edit shortcuts reach UI and Escape closes it. Native fixtures run in
  GitHub Actions only. Earlier CI attempts failed because fixture API/name/warning
  stubs lagged the new code, and were corrected; not reported as runtime fixes.

Local validations: actual Lua 5.1 two-server network, photo/voice, physical map,
USB ACL/migration/media/archive, interrupted restore/hack, cache-free media recovery
and stale-reply/recording isolation. These fixtures do not establish in-game UI,
model, physics, shader or performance acceptance. All other initial audit items
remain open; this PDA change must not be described as completing vehicle work.


Offline Mi-24 inspection (not a model fix): original FBX has 1009 welded
connected components. The original textured twin nose tyres are components
42/43 in `J:/LostZone_Work/_work/mi24_original_gear_inspect/components.json`.
Their bounds are x +/-0.058..0.294, y 1.147..1.656, z 0.489..0.999 in the
builder's normalized Blender coordinates. Components 49/50 are main bay DOORS,
not tyres (confirmed with an offline colored underbelly render). Main gear
requires further segmentation; do not label these doors as wheels or ship them
as a completed landing-gear solution. Offline QA only; no owner game launched.


Packaging correction before release: client base archive has the two stock
`dev_flash_1/2` meshes and `prop/prop_item3` texture, but the dedicated-only
candidate's managed shared assets did not. Extracted the authenticated original
meshes and their real texture/THM into the shared overlay; both roles now receive
the exact dependencies. Staged, unpublished patch 000051 is superseded by 000052;
its directory is retained as an unused candidate, never published or installed.


Final pre-publication regression: native recordings can reach 6 MiB binary
(8 MiB base64), above the old 700-command transport ceiling. Raised the library
and chat transport bound to 2300 chunks, retaining the native 600-second limit.
Remote dictaphone entries download audio only on explicit play/send, avoiding
bulk downloads of every long recording at login. Actual scripted USB/notes tab
constructors are exercised with widgets stubbed; private edit drafts clear on
physical device change. Unpublished candidate 000052/v9 is superseded by
000053/v10 before publication. Native binary remains exact CI 41397841797.

Follow-up .3: native CI 41402744980 at 26c27baa0 passed shaders, offline
checks, DX11/DX8 builds and the real PDA keyboard fixture. Opening the PDA
while holding jump/use could swallow their release and leave jump/pickup
latched. Only the stop edges now reach the actor directly; the open PDA still
blocks new gameplay, RP/global shortcuts and ordinary game input.

Lua refinements: the known password opens a foreign physical PDA without a
hacking charge; an owner can use the physical decryption tool to remove a
forgotten password without losing data or changing UID. Owned unlocked devices
can be explicitly factory-reset; locked devices cannot bypass protection by
resetting. Actual USB tab constructors and foreign password controls run in
the Lua UI fixture. Imported photo/voice attachments open through the existing
authorized media helpers; stale overlays/drafts clear on device changes.

The fixed one-minute media upload deadline broke full-length recordings even
after raising the chunk limit. A complete 8 MiB base64 upload at 10 ticks/s now
passes the real transport/server persistence fixture. The acknowledgment timeout
starts after the last chunk, with an absolute 10-minute ceiling.

Owner explicitly asked again about corpses, loose-item physics and ZIL-131.
Confirmed these are NOT complete: dragging/pushing bodies, item friction,
cargo seats/platform movement and fall damage still need implementation and
verification. This PDA release does not fulfill those gameplay tasks.

2026.11.02.3 delivered: native 26c27baa0, CI 41402744980; Lua/resources
22f852072, CI 41435413583; patch 000054. Signed manifest
manifests/2026.11.02.3-c696b141.bin was verified and changed file bytes
reconstructed. Public J:/LostZone_Work/Lost Zone Server.zip: 2,774,644,926 bytes,
47 entries, SHA256 1bd9c364cbc898d3eef00a6a9cca1a8f99b245dda6798b1a35891aa42ee825a1.
All CRC/SHA checks passed. Owner client, public server folder and optional local
dedicated addon updated; runtime/saves preserved; no game/master launched.
Remote hoster installation still requires transferring this archive.

Next native candidate, NOT part of published .3: Shift+F corpse dragging routes
to the existing authoritative PHCapture joint instead of fixing a local replica.
Server validates connected character, live unseated capturer, actual physical
bone, dead unparented ragdoll, <=2.5 m reach, static wall visibility and body
exclusivity. Capture stops on F, failed joint, death/disconnect/transition or
object replacement. Client acknowledges hand/weapon state from the server.
Candidate CI fixture exercises the actual bridge with physics/network stubs;
it does not establish ODE dynamics or in-game dragging acceptance. Loose-item
friction, pushable bodies and ZIL-131 riding remain separate open work.

Loose-item candidate: ordinary live-player drops previously forced 3 m/s
forward +1.5 m/s upward and a strong fixed spin, with every item starting at
exactly the same point. Replaced with a gentle 0.45 m/s horizontal drop, lower
spin, and per-inventory short burst position reservations sized to the model.
Static walls and existing loose items reject candidate positions. Reservation
happens before inventory mutation; if the bounded search is full, normal native
shape correction is retained instead of desynchronizing already rejected shared
ownership. Sales/destruction, dead-player/NPC drops and missile throwing are
excluded. New CI fixture covers 64-item separation, large footprints, blocked
candidates, per-inventory isolation and clock wrap; no live physics acceptance.

First corpse-drag CI 41437420636 stopped in its test harness on MSVC warnings:
CRT sscanf deprecation and int-to-u16 map fixture keys. Updated the harness to
match project CRT settings and use explicit u16 keys; not a claimed runtime fix.

Corpse foot-contact candidate: a tiny impulse on one light limb (0.28 m/s)
was below the Coulomb ground-friction budget for a whole ragdoll. Walking contact
now gives a bounded horizontal mass-scaled nudge across the ragdoll's parts;
very heavy bodies (>200 kg) are excluded. Active captured bodies are not also
kicked. Loose-item contact speed is reduced from 1.5 to 0.75 m/s. Fixture checks
whole-body momentum, zero upward impulse and per-part velocity bounds. This
still requires in-game contact/solver acceptance; not described as completed
vehicle or general collision work.

ZIL-131 source measured offline: actual DCP model is veh_zil_u_02 (not _01).
Body/bench geometry uses game z = Blender y; the first inspection selected the
cab area and was corrected. Cargo horizontal bench surfaces are at ~1.42-1.44 m,
body floor ~1.12 m, sides x +/-1.20, rear ~-3.75. Current dcp_zil131 has only
two cabin seats. Cargo seats, suitable low-bench pose, moving-platform support
and fall damage remain open; geometry measurement alone is not an implementation.

Owner additions, 2026-11-02: ALL grenades reportedly crash; grenades/bolts/RPG
travel in jumps; grenade launchers do not fire. No fresh crash log is available
(owner will supply later); latest local player log is a clean menu exit. Audit
both projectile lifecycle and interpolation without claiming the exact reported
crash reproduced. RocketLauncher::DetachRocket dereferences the loaded-list
iterator in the already-launched-list branch; that iterator may be erased/end.
Physics import also clears all interpolation samples whenever displacement is
>3 m, even for a legitimately fast projectile between ordinary snapshots.

Additional required work: placed backpack must become the stash's actual item,
not remain in the player's inventory; pickup and take-all behavior like original;
physical backpack on ground, container capacity. Trunks need weight capacity,
vehicle must stall on overload. Review vehicle bulletproof glass, penetrative
occupant damage, hull durability (~three RPG hits to destroy as requested),
third/first-person door entry/exit/steering animations. Source external animation
assets only with suitable availability/permissions; none has been acquired yet.

Owner clarified moving platforms are NOT seat assignment: standing/walking on
any suitable flat vehicle deck must retain platform motion. Seat counts must
match each actual model across the fleet: one-seat buggy must not admit two;
buses/multiseat cars must not be restricted to two. ZIL-only changes do not meet
this requirement. All these tasks remain open.

PDA follow-up regression: decryption/known-password permission survives reconnect
and location changes; returning the device to its owner revokes foreign access.
Unlocked owner-session cache now includes the current password digest, so an old
session does not bypass a changed password. Actual two-server fixtures pass.
