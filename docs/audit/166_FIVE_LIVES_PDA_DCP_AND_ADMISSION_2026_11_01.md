# Five lives, physical PDA, admission and DCP corrections

Status: source changes; native GitHub validation and delivery pending. No owner game processes launched for verification.

## User rule
One account owns one character. It has five lives. After the first four deaths the same name and faction resume at the nearest available authored safe zone, with service/arrival fallbacks on the current level. One persisted random draw retains half of the non-PDA root items (rounding up); the remaining originals stay on the corpse. The physical PDA is always retained. On the fifth death the whole inventory, including the PDA, remains on the final corpse; the account room requires a different Russian call sign and a starter-kit selection.

NCHA extends NCH9 with one bounded server-owned lives byte. Both masters accept it and legacy NCH3..9. Repeated processing of one dead body cannot spend another life. Reserved corpse inventory cannot be looted during the physical transfer, including by NPC script transfers. The reservation is world-persisted, and restoration waits for the actual parent and item state. This uses the existing world/character durability barriers; it is not a new atomic transaction across the two stores.

## Other changes
- Matching .5 client dump resolves to CScriptGameObject::IsTalking; stale wrapper membership is checked before dereferencing its owner. Generic object access raises a controlled Lua error.
- Player health state has a request/ack retry and waits for BHS initialization. Pending state retains its target actor ID; duplicate initial snapshots cannot overwrite current health.
- PDA markers and map discoveries are keyed by the physical device UID. Transfers are always shown; reconnect/save acknowledgements and late map initialization retry.
- The starter picker uses the chosen loner kit and supplies mandatory valid sections, instead of refusing unavailable legacy entries.
- Master child controls are clipped and tab visibility is checked in its GUI fixture. Idle demand maps save and exit after 180 seconds, then remain armed for requested wakeup. Memory diagnostics include resident and private commit; this does not guarantee 6-10 occupied maps plus a client fit in 16 GB.
- Service traders and mechanics are protected against damage without making every combat NPC immortal.
- Barter layout uses two offers/backpacks and a central equipment/status panel.
- DCP optional physical panels are included in profiles. Zero damage health cannot divide by zero. Suspension considers actual mass and wheel count. Auxiliary lamps, broken-glass state, a compact car HUD, bounded hit impulses and swept run-over detection are added.
- Admin noclip is authorized on the server; demo teleport allows authenticated admins. The weather editor sends bounded server commands and disallows online asset-path changes.

## Limits and required acceptance
Native compile/fixtures must pass in GitHub before deployment. Gameplay, ride height, glass hit geometry, collision/exit behavior and every DCP model still require owner gameplay acceptance. The safe-zone respawn search stays within the loaded level and checks walkable vertices inside authored safe restrictors first. A reliable cross-level nearest-safe-zone selection is not implemented here. No claim that every random crash or all vehicle physics issues are resolved.

## Offline validation
Actual Lua survival tests cover stable draw, PDA retention, no partial transfer with absent items, retries, ownership, NPC reservation protection and final death. Existing relevant Lua suites and native-save Python tests are run; full native checks run only in GitHub. Exact build/release receipts will be appended after validation.

Initial CI: master run 41300308525 on 1ced4f6d3 passed all production GUI/parity/process/storage checks. Engine run 41302586438 on 2ec30e711 passed Lua and all Windows regression fixtures except the trunk-reset harness, which needed the new HUD cache in its stub. The added native noclip/lifetime/five-life/checksum/suspension tests passed there; full engine compilation remains pending.
