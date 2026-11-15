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
