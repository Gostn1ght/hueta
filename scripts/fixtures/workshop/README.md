# GAMMA workshop crafting fixture

Unmodified installed GAMMA scripts (gamedata/scripts/<name>.script), CR removed
(LF), ASCII. check-netcoop-workshop.py runs the server's headless craft
(netcoop_workshop) against them. SHA256 of these LF files:

- `craft_use_low_cond.lua` `a801b1ebc96cc9944d1893e1839632112780fd0b3b71140371cd40aae4130148`
- `ui_workshop.lua` `ae9eacef9ac90de9ea687e917ccea81febab37a71480bdd9d0ee28354f5d67f1`
- `zz_ui_workshop_keep_crafting_window_open.lua` `f5606ba5c80440c6196e32992fa22ec7f0050ae8522bc0cb6acf40396759318e`
- `zzzzzz_craft_use_low_cond_nearby_stashes.lua` `9de2c51a216326b5976400fc04dc38a970cf3b3a63f21add0036640e7f8386f0`
- `zzzzzz_ui_workshop_nearby_stashes.lua` `43a3b6f3c91a290ea1af805eebce245cabd80b8d65d4fee7ce7a237f37a71196`

The unchanged installed `upgrade_rank_pricing.script` and
`inventory_upgrades_mp.script` are also included as UTF-8 LF `.lua` fixtures.
They exercise GAMMA's real selected-item price lookup, installation effect and
repair charge against the server mechanic wrapper. Engine inventory/native
upgrade installation and configuration lookups are boundary doubles; this
does not replace a live client/server mechanic check.
