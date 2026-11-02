# Gameplay follow-up after 2026.11.02.1

Status: investigating; no fixes in this audit are released yet.

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

Implemented in source, pending release and in-game acceptance:

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
