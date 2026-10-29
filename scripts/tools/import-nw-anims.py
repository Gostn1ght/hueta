"""Import New Way's RP animations (owner 2026-10-24; NW's developers
authorized taking their work) into the client overlay.

From an unpacked New Way build (Kall\\nw_unpack.py + the scratch picker for
textures\\ui\\ui_actor_anims_icons.dds and textures\\ui\\anim_preview\\*):
- configs/alife/actor_anims.ltx + configs/ui/ui_anim_previews.ltx
  -> configs/netcoop/rp_anims.ltx (our format: in / mid / out / loop, plus the
     wheel's group, icon cell and preview timing);
- the motions our actor OMFs lack -> meshes/actors/modded_stalker_animations/
  nw_*.omf (scripts/tools/merge-player-anims.py --only-new; ours stay), and
  the ones a pose names from New Way's other actor OMFs (a scene's motions);
- the icon atlas and the animated previews -> BC3 DDS (previews at 64 px a
  frame to keep the patch small).
Walking poses (legs by the movement, torso in its pose: walk = true, legs,
torso) and weapon poses (slot = the slot whose item is in the hands) are
played by the engine too (ActorAnimation.cpp rp_walk, rp_start).

usage: import-nw-anims.py <NW unpacked dir> <overlay client dir>
"""
import importlib.util
import re
import struct
import subprocess
import sys
from pathlib import Path

import etcpak
from PIL import Image

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("merge", HERE / "merge-player-anims.py")
merge = importlib.util.module_from_spec(_spec)
sys.argv, _argv = [sys.argv[0], "--import-only"], sys.argv
_spec.loader.exec_module(merge)
sys.argv = _argv
OMFS = ("stalker_animation", "stalker_scripts_animation", "stalker_smart_cover_animation")
PREVIEW_FRAME, PREVIEW_COLUMNS = 64, 32
RP_ITEMS = {20:"wpn_binoc", 28:"kolbasa", 29:"bread", 30:"vodka, vodka2, vodka_quality", 31:"energy_drink",
            40:"guitar_a", 41:"guitar_a", 42:"harmonica_a", 43:"harmonica_a", 50:"hand_radio",
            51:"anomaly_scaner, detector_geiger", 52:"anomaly_scaner, detector_geiger", 53:"detector_geiger, detector_radio"}


def read_ltx(path):
    secs, cur = {}, None
    for line in path.read_text(encoding="cp1251").splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^\[([^\]]+)\]", line)
        if m:
            cur = secs.setdefault(m.group(1), {})
            continue
        m = re.match(r"^([A-Za-z_0-9]+)\s*=\s*(.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip().strip('"')
    return secs


def dds_bc3(image, path):
    """A one-mip BC3 (DXT5) DDS of an RGBA image whose sides are multiples of 4."""
    w, h = image.size
    data = etcpak.compress_bc3(image.convert("RGBA").tobytes(), w, h)
    header = struct.pack("<4sIIIIIII44sIIIIIIIIIIIII", b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, h, w,
                         len(data), 0, 1, b"\0" * 44, 32, 0x4, 0x35545844, 0, 0, 0, 0, 0, 0x1000, 0, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + data)


def main(nw, client):
    nw, client = Path(nw), Path(client)
    anims = read_ltx(nw / "configs/alife/actor_anims.ltx")
    previews = read_ltx(nw / "configs/ui/ui_anim_previews.ltx").get("anim_previews", {})
    out = ["; Lost Zone RP animations: New Way's (owner 2026-10-24; NW's developers",
           "; authorized taking their work), imported by scripts/tools/import-nw-anims.py.",
           "; [rp_list] order; each [rp_<name>]: in / mid / out motion chains (in once,",
           "; mid repeats while loop = true, out once on leaving; once = true: a gesture",
           "; that ends by itself), title (a string id or",
           "; the text itself), group (the wheel's category), icon (cell of",
           "; ui\\ui_actor_anims_icons, 8x8, 128 px), group_icon (shows the category),",
           "; preview = frames, intro frames (once), intro ms, loop ms",
           "; (ui\\anim_preview\\anim_<icon>, 32 columns of 64 px);",
           "; walk = true: legs = forward, back, left, right, standing; torso = walking,",
           "; standing (no chains); slot = a weapon pose: that slot's item in the hands.", "", "[rp_list]"]
    body, kept, skipped, needed = [], [], [], set()
    for key in sorted((k for k in anims if re.match(r"anim_\d+$", k)), key=lambda k: int(k[5:])):
        a, index = anims[key], int(key[5:])
        if index == 0:
            continue  # NW's "stop" entry: the wheel's centre button here
        if a.get("enabled") == "false":
            continue
        walk = a.get("anim_walk") == "true"
        slot = a.get("anim_use_slot", "3") if a.get("anim_need_weapon") == "true" else None
        legs = [a.get("anim_legs_" + k, "") for k in ("fwd", "back", "ls", "rs", "idle")]
        torso = [a.get("anim_torso_walk", ""), a.get("anim_torso_idle", "")]
        if walk and not all(legs + torso):
            skipped.append(a.get("anim_descr", key))
            continue
        chain_in = a.get("anim_in") or a.get("anim_posture_in", "")
        chain_out = a.get("anim_out") or a.get("anim_posture_out", "")
        mid = a.get("anim_middle", "")
        once = not (chain_in or mid) and not walk  # NW's one-shot gestures name only an "out" chain
        if once and not chain_out:
            skipped.append(a.get("anim_descr", key))
            continue
        name = "nw_%d" % index
        kept.append(name)
        body += ["", "[rp_%s]" % name, "title = " + a.get("anim_descr", name), "group = " + a.get("ui_group", ""),
                 "icon = %d" % index]
        if a.get("ui_group_icon") == "true":
            body.append("group_icon = true")
        if walk:
            body += ["walk = true", "legs = " + ", ".join(legs), "torso = " + ", ".join(torso)]
        elif once:
            body += ["in = " + chain_out, "mid = ", "out = ", "loop = false", "once = true"]
        else:
            body += ["in = " + chain_in, "mid = " + mid, "out = " + chain_out,
                     "loop = " + ("true" if a.get("anim_loop", "true") == "true" else "false")]
        if slot:
            body.extend(["slot = " + slot, "weapon = rifle"])
        if index in (19, 62):
            body.append("weapon = pistol")
        if index in RP_ITEMS:
            body.append("items = " + RP_ITEMS[index])
        for chain in [chain_in, chain_out, mid] + legs + torso:
            needed.update(x.strip() for x in chain.split(",") if x.strip())
        if "anim_%d" % index in previews:
            body.append("preview = " + previews["anim_%d" % index])
    out += kept + body
    (client / "configs/netcoop/rp_anims.ltx").write_text("\n".join(out) + "\n", encoding="cp1251", newline="\r\n")
    print("rp animations:", len(kept), "| not taken:", len(skipped), skipped)

    target = client / "meshes/actors/modded_stalker_animations"
    for omf in OMFS:
        subprocess.run([sys.executable, str(HERE / "merge-player-anims.py"), "--only-new",
                        str(client / "meshes/actors" / (omf + ".omf")), str(nw / "meshes/actors" / (omf + ".omf")),
                        str(target / ("nw_" + omf + ".omf"))], check=True)
    have = set()
    for omf in list((client / "meshes/actors").glob("*.omf")) + list(target.glob("*.omf")):
        have.update(d["name"] for d in merge.parse(str(omf))["defs"])
    for omf in sorted((nw / "meshes/actors").glob("*.omf")):
        if omf.stem in OMFS or not needed - have:
            continue
        keep = [d for d in merge.parse(str(omf))["defs"] if d["name"] in needed - have]
        if keep:
            merge.subset(str(omf), str(target / ("nw_" + omf.stem + ".omf")), "motions the poses name", keep)
            have.update(d["name"] for d in keep)
    assert not needed - have, sorted(needed - have)

    dds_bc3(Image.open(nw / "textures/ui/ui_actor_anims_icons.dds"), client / "textures/ui/ui_actor_anims_icons.dds")
    used = {int(n[3:]) for n in kept}
    for src in sorted((nw / "textures/ui/anim_preview").glob("anim_*.dds")):
        index = int(src.stem[5:])
        if index not in used:
            continue
        image = Image.open(src)
        columns, rows = image.size[0] // 128, image.size[1] // 128
        small = image.convert("RGBA").resize((columns * PREVIEW_FRAME, rows * PREVIEW_FRAME), Image.LANCZOS)
        dds_bc3(small, client / "textures/ui/anim_preview" / src.name)
    print("previews:", len(used))


if __name__ == "__main__":
    main(*sys.argv[1:3])
