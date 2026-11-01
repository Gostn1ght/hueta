# Five lives, physical PDA, admission and DCP corrections

Status: source changes; native GitHub validation and delivery pending. No owner game processes launched for verification.

## User rule
One account owns one character. It has five lives. After the first four deaths the same name and faction resume at the nearest available authored safe zone, with service/arrival fallbacks on the current level. One persisted random draw retains half of the non-PDA root items (rounding up); the remaining originals stay on the corpse. The physical PDA is always retained. On the fifth death the whole inventory, including the PDA, remains on the final corpse; the account room requires a different Russian call sign and a starter-kit selection.

NCHA extends NCH9 with one bounded server-owned lives byte. Both masters accept it and legacy NCH3..9. Repeated processing of one dead body cannot spend another life. Reserved corpse inventory cannot be looted during the physical transfer, including by NPC script transfers. The reservation is world-persisted, and restoration waits for the actual parent and item state. This uses the existing world/character durability barriers; it is not a new atomic transaction across the two stores.

## Other changes
- Matching .5 client dump resolves to CScriptGameObject::IsTalking; stale wrapper membership is checked before dereferencing its owner. Generic object access raises a controlled Lua error.
- Player health state has a request/ack retry and waits for BHS initialization. Pending state retains its target actor ID; duplicate initial snapshots cannot overwrite current health.
- Before the new body's first binder update, old lethal limb globals/raw keys are neutralized; the authoritative snapshot is applied and acknowledged after initialization. New ownership releases interrupted script input locks and closes old-body inventory/dialog/PDA windows.
- PDA markers and map discoveries are keyed by the physical device UID. Transfers are always shown; reconnect/save acknowledgements and late map initialization retry.
- The starter picker uses the chosen loner kit and supplies mandatory valid sections, instead of refusing unavailable legacy entries.
- Master child controls are clipped and tab visibility is checked in its GUI fixture. Idle demand maps save and exit after 180 seconds, then remain armed for requested wakeup. Memory diagnostics include resident and private commit; this does not guarantee 6-10 occupied maps plus a client fit in 16 GB.
- Service traders and mechanics are protected against damage without making every combat NPC immortal.
- Barter layout uses two offers/backpacks and a central equipment/status panel.
- DCP optional physical panels are included in profiles. Zero damage health cannot divide by zero. Suspension considers actual mass and wheel count. Auxiliary lamps, broken-glass state, a compact car HUD, bounded hit impulses and swept run-over detection are added.
- Voluntary dismount checks a standing volume against static geometry and nearby objects, tries ten side/longitudinal points, and remains seated when all are occupied. The controller position is assigned before recreation. Car/player contacts keep collision but bound penetration correction and restitution; static/prop car contacts retain their existing parameters. This does not prove every physical launch is eliminated.
- Gravitational zones no longer enroll transport in idle telekinesis, apply their direct pull, or disable its normal gravity. Zone hits still run the damage path, with zero physical lift impulse. Other hit impulses are capped against the struck physical element's mass (walking to its nearest physical ancestor), rather than applying the whole vehicle's allowance to a light door/wheel.
- Admin noclip is authorized on the server; demo teleport allows authenticated admins. The weather editor sends bounded server commands and disallows online asset-path changes.

## Limits and required acceptance
Native compile/fixtures must pass in GitHub before deployment. Gameplay, ride height, glass hit geometry, collision/exit behavior and every DCP model still require owner gameplay acceptance. The safe-zone respawn search stays within the loaded level and checks walkable vertices inside authored safe restrictors first. A reliable cross-level nearest-safe-zone selection is not implemented here. No claim that every random crash or all vehicle physics issues are resolved.

## Offline validation
Actual Lua survival tests cover stable draw, PDA retention, no partial transfer with absent items, retries, ownership, NPC reservation protection and final death. Existing relevant Lua suites and native-save Python tests are run; full native checks run only in GitHub. Exact build/release receipts will be appended after validation.

Initial CI: master run 41300308525 on 1ced4f6d3 passed all production GUI/parity/process/storage checks. Engine run 41302586438 on 2ec30e711 passed Lua and all Windows regression fixtures except the trunk-reset harness, which needed the new HUD cache in its stub. The added native noclip/lifetime/five-life/checksum/suspension tests passed there; full engine compilation remains pending.

Current offline evidence: all 83 workflow resource/script checks passed on `99a572b3f`; final delta 000049 has 42 client and 35 server payloads. Effective archive mounting was simulated over the actual .5 release: every changed payload selects 000049 and matches its input bytes, including nested server overrides. Receipts are stored privately in `bugs_20261031_v6/offline-final.json` and `delta49-reviewed.json`.

Master production run 41303334526 on `3129c3c59` passed the cold-process/wakeup and GUI tab/scroll regression checks; its production executable metadata and screenshot are downloaded. Engine run 41318306772 stopped on a strict-MSVC name-shadowing warning in the new exit fixture (its global `world`, not a production variable); fixed in `16bbda869`, run 41318861869. Cold status withdrawal and the updated host-stop fixture passed in that first run. Delivery must still wait for a successful full native build.

Run 41319554942 on `c1548e5b3` passed the exit/contact fixture; the new zone fixture needed its movement-control alias and a member name correction. On `4aec729a6`, run 41320133234 passed all mandatory resource, Windows native and regression checks, including both new vehicle fixtures. Full DX11 compilation is in progress. The resource delta remains byte-identical to `99a572b3f`; later commits change native code, tests and this audit.

Safe-zone scope communicated to the owner: service NPC invulnerability and nearest safe-area respawn on the loaded level are included. A universal weapon-draw/fire prohibition in every safe zone is not implemented by these changes.
