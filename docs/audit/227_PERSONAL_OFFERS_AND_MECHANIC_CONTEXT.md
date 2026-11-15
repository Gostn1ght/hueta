# Personal NPC work and server mechanic context — 15 November 2026

Owner reports: intermittent offers at traders/technicians and simulation NPCs;
quests must survive server restart; NPC recruitment and mechanic services still
fail. No new release has been installed or published by this change.

## Ordinary tasks

GAMMA keeps simulation NPC `dyn_quest_rand` on a shared NPC storage entry. A
cached choice, including its string `nil`, could affect every remote player.
The dedicated wrapper now uses the bound character's persisted quest context,
keyed by NPC spawn name rather than an ephemeral network ID. It restores the
NPC global even when a condition throws. The ordinary offer arrays are also
separate per character, with transient skipped-task scratch state cleared when
switching characters.

The original generator still validates prerequisites, community, task section
and the player's task history. If its remembered choice no longer qualifies
or SP's no-work roll leaves it empty, the wrapper picks another eligible job
and sends that choice back through the original generator. It cannot offer a
locked job when no eligible candidates exist. Valid remembered offers do not
reroll after restart; newly selected offers use the normal random source.

Ordinary fetch/material templates may be active for multiple players, each
with their existing private task manager and item requirements. The existing
exclusive claim remains for story/world/escort templates. Different players
can legitimately draw the same job; randomness does not promise uniqueness.

Accepted task stage/status and material requirements already use the character
save/restore path described in 222 and 224. This change adds durable personal
offer selection rather than replacing task saves with new jobs on restart.

A further persistence defect was found in the original save/load sequence:
`load_state` leaves the Lua task's `t` unset until its first update; `save_state`
omits tasks with no `t` and no repeat cooldown. Saving or transitioning again
before that update could lose the restored Lua progress while the native task
still existed. The dedicated save wrapper now reattaches the existing active
native task before the original serializer runs. It does not issue a new task,
rerun `on_init`, replace an objective or reset its stage. The real GAMMA
save/load fixture covers an immediate second save with no intervening tick.

## Technician

The deployed `upgrade_rank_pricing` accesses `ui_inventory.GUI.upgr.sec` in
both its validation and native-install effect. There is no real UI window on
a dedicated server, so the previous mechanic RPC could throw before installing
or charging. The server now supplies a temporary selected-item context through
the entire operation, including the native install/effect, and restores the
previous UI/speaker state after success, refusal or an exception. The actual
mechanic discount conditions are evaluated before upgrade validation.

Repairs retain GAMMA's effect/price and mechanic-feature delay behavior. No
client-side money or installed-upgrade flag is treated as authoritative.

The owning client's authoritative UI-open reply also sets `used_npc_id` before
opening trade/repair. Its remote dialogue bypasses the ordinary NPC binder's
SP use callback; otherwise `get_speaker()` could be nil or a different NPC
while the repair window evaluates available upgrades. Unknown UI kinds and
missing NPCs do not change the speaker.

Native replication follow-up: `SetCondition` changed the server's actual item,
but ordinary owner-predicted condition deltas are deliberately filtered out.
For a mechanic RPC, the old item-action touch marked its NPC argument rather
than the repaired inventory item. The Lua condition setter now marks the
actual changed item for an authoritative owner snapshot on the server. Client
prediction and SP retain their former behavior. A CI-only native fixture
executes the real setter and inventory clamp, checking exact item ID, repair
value, bounds, client/SP isolation and invalid-object handling. A new full
native build is required; the earlier in-progress build alone cannot include
this follow-up.

## NPC recruitment

The global non-task companion count previously included other players' hired
NPCs, exhausting the small recruitment limit. The dedicated count now includes
only NPCs owned by the bound player's login, including offline ALife members.
World callbacks without a player retain the original count. This addresses
one concrete recruitment blocker; dialogue/rank/friendship conditions and live
following across location servers still require verification.

The installed individual-recruitment addon clones an NPC and finishes free or
paid recruitment from a later time event using `db.actor`. The world event
queue runs for whichever player was last bound, so a second player's update
could make that player the recruiter's replacement. Only these two addon
recruitment events now capture the original login and rebind to that owner's
current actor for the callback. They wait while the owner is offline; a
reconnect can change actor ID without changing ownership. The outer actor,
task context and scheduler are restored on errors as well. The addon's
original cloning and hire/reputation conditions remain in force.

Review of the actual native call at the end of that addon found another
dedicated crash: `CActor::RunTalkDialog` unconditionally accessed
`CurrentGameUI()->TopInputReceiver()` in its ALife branch. After recruitment
the addon calls this method to reopen the conversation. Remote actors now
send an owner-only `open_ui talk` message and return before touching server
UI or starting an orphaned local conversation. The client uses its existing
conversation opener, whose UI requests a normal validated server dialogue.
Headless actors without a remote owner return safely when no UI exists.
Opening just a conversation does not initialize a trade profile. Original
client and SP paths are retained. The native fixture executes the actual
method; the real client reply handler also tests the added talk kind.

## Verification

- Actual GAMMA generator + production context in Lua 5.1: two players, stale
  no-work choice, active/locked tasks, exception unwind, a fresh Lua VM restart
  with different NPC network IDs, and independent fetch vs exclusive story
  acceptance.
- Actual GAMMA rank-pricing and MP repair functions + production workshop RPC:
  headless selected item, native-effect money deduction, real repair charge,
  insufficient funds, and UI/speaker restoration including failure.
- Existing task hand-in/identity/runtime and item/companion tests are retained.
- CI caught reverse traction remaining engaged after releasing S. The manual
  ReleaseBack path now explicitly disengages clutch/traction before resuming
  W if appropriate. Actual native pedal checks must pass in GitHub Actions.

Native build/runtime validation remains CI-only. A matched native + resource
release is necessary: the inspected 000078 server resources still accompany
the older 12 November native executable (see 225/226).

## Final candidate validation

Full CI **43696650732**, source
`8af66605c1d865ab666225c7720a9a0d09596a28`, completed successfully:
DX11, DX8, GCC/MSVC fixtures, actual Lua and shaders. Both renderer build
steps succeeded, including the new scripted talk/condition fixtures and the
Windows process-ownership tests. Intermediate native runs 43694313883 and
43695629758 were superseded, not accepted as builds of the final candidate.

Candidate **000080** is prepared under
`C:/Users/Mahito/Downloads/LostZone-candidate-000080/`:

- Six protected resource archives, all 23 entries authenticated and extracted
  bytes compared with staged sources from the same commit.
- CI DX11 runtime and separate matching symbols downloaded and checked by
  CI identity, ZIP CRC and every recorded file size/SHA256. Client/server EXEs
  are identical: `07a7f3db130825961073abb8865d2cbbd0659e0dbceaa3ce586a96dfd2bc7366`.
- DX8 artifact from the same successful run:
  `6529ece3bd0856d85d3ec8cdc055950b3e11736d59b9f0965043b673d9e931ea`.
  Both renderer binaries contain the matching owner archive key; no key bytes
  were printed or added to verification reports.
- Static PE import check passed for all 46 images after adding DX8. Nothing
  was loaded or executed locally.
- Standalone server candidate ZIP prepared from the existing explicit
  immutable-file whitelist and new verified native/resources. All 72 files,
  all CRCs and file hashes verified. No player saves, live databases, host
  settings, private keys or logs included. ZIP size **2,922,141,749 bytes**,
  SHA256 `4cd0aa4b1d360739e448f605c50bd0a364c6a5993f84b5fc3e9b4e98df51bfa6`.

The server ZIP is
`C:/Users/Mahito/Downloads/LostZone-candidate-000080/Lost Zone Server candidate-000080.zip`.
Its metadata explicitly identifies an unpublished candidate requiring the
matching client. Candidate 000079 is marked superseded. Verification reports
are retained beside the candidate. The installed J: client/server and public
launcher distribution were not changed, and the existing server archives
were preserved. No live multiplayer acceptance or closure of the entire bug
backlog is claimed. The owner requested release after the blocking list is
closed; this candidate has not been published.
