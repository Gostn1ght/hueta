# Historical Lost Zone menu artwork

The generated background below is historical and is no longer used by the current candidate. Active menu backgrounds now come from the original Anomaly add-on documented in `addons/README.md` and `addons/manifest.json`. The player portrait is separate from the background replacement.

Generated with the built-in image_gen tool. The exact prompts are saved in prompts.json.

- lost_zone_background.png: railway maintenance yard at dusk; original 1672 x 941.
- lost_zone_portrait.png: illustrated novice stalker dossier portrait; original 1086 x 1448.
- The portrait is menu artwork, not a render of equipped armor.
- Native RGBA DDS copies live in scripts/netcoop-overlay/client/textures/ui.
- All standalone textures use explicit pixel rectangles in XML. This avoids interpreting a widescreen background as a 256-pixel atlas region.
- The executable emblem is deliberately absent from the game menu.
