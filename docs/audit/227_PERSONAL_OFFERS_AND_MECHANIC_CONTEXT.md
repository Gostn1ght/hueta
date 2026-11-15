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

## NPC recruitment

The global non-task companion count previously included other players' hired
NPCs, exhausting the small recruitment limit. The dedicated count now includes
only NPCs owned by the bound player's login, including offline ALife members.
World callbacks without a player retain the original count. This addresses
one concrete recruitment blocker; dialogue/rank/friendship conditions and live
following across location servers still require verification.

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
