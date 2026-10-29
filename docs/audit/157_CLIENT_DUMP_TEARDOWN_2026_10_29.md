# 157. Four additional client exceptions, 2026-10-29

All five dumps in the owner's appdata/player/logs have the 25afdf144 module's
timestamp 1792924635 and SizeOfImage 40210432. Resolve with the matching PDB,
the exception context and AMD64 unwind metadata, not raw stack candidates.
Car failure and its offline regression are documented separately in 156.

## Other four dumps

- 10-25 20:31:41: CCustomDevice::UpdateVisibility+0xB8, read 0xAA8 from a null
  Actor. UpdateCL used only H_Parent()==CurrentEntity: both could be null
  during teardown. Require a parent; visibility also requires its local Actor
  and a live player HUD, and uses that Actor's inventory.
- 10-26 22:26:31: CMissile::render_item_ui_query+0xE, null inventory +0x88.
  Do not draw the throw meter for a detached/destroying/non-Actor-owned item.
- 10-25 21:11:57: dwfChooseAction+0x455 through CMonsterEnemyManager::update,
  UpdateMemory and CBaseMonster::net_Relcase. A group member has no condition
  object (read +8 from null). Client replicas must release links without
  running tactical AI; server/SP retain the AI update. Exclude null/destroying
  group members, and an entity without a condition is not alive.
- 10-25 21:39:35: r_dsgraph_insert_dynamic+0x19B, null shader +0x10 during
  shader selection for a skeleton child. A visual without shader/render passes
  cannot enter the graph. Obtain the optional distortion element via _get().

New check-native-detached-objects.py compiles the actual missile UI query,
entity alive predicate and monster relcase method with fixture dependencies.
It compiles the actual device/render entry guards separately, leaving the
unchanged animation/render pipeline out of the fixture. Cover both refused
transitional states and valid ordinary paths; verify client link cleanup and
server AI update. Full engine compilation is still required in GitHub Actions.

This does not establish that unrelated crashes, resource exhaustion, or all
visual artifacts are fixed. No game was launched and no patch was published
at the time of this source change. Preserve account/world saves.
