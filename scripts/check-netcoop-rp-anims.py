"""The RP wheel's animations (configs/netcoop/rp_anims.ltx, New Way's, owner
2026-10-24): every motion they name is in one of the client's actor OMFs, a
walking pose has its five legs and two torso motions, a weapon pose names a
slot, and the engine reads every key (netcoop_rp_anims.inc)."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "scripts/netcoop-overlay/client"
spec = importlib.util.spec_from_file_location("merge", ROOT / "scripts/tools/merge-player-anims.py")
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)

motions = set()
for omf in list((CLIENT / "meshes/actors").glob("*.omf")) + list((CLIENT / "meshes/actors/modded_stalker_animations").glob("*.omf")):
    motions.update(d["name"] for d in merge.parse(str(omf))["defs"])

sections, order, cur = {}, [], None
for line in (CLIENT / "configs/netcoop/rp_anims.ltx").read_text(encoding="cp1251").splitlines():
    line = line.split(";", 1)[0].strip()
    m = re.match(r"^\[([^\]]+)\]$", line)
    if m:
        cur = sections.setdefault(m.group(1), {})
        continue
    if cur is sections.get("rp_list") and line:
        order.append(line)
        continue
    m = re.match(r"^([a-z_]+)\s*=\s*(.*)$", line)
    if m and cur is not None:
        cur[m.group(1)] = m.group(2).strip()

walks = weapons = 0
for name in order:
    a = sections["rp_" + name]
    chains = {k: [x.strip() for x in a.get(k, "").split(",") if x.strip()] for k in ("in", "mid", "out", "legs", "torso")}
    for k, names in chains.items():
        for motion in names:
            assert motion in motions, (name, k, motion)
    if a.get("walk") == "true":
        assert len(chains["legs"]) == 5 and len(chains["torso"]) == 2, name
        assert not (chains["in"] or chains["mid"] or chains["out"]), name
        walks += 1
    else:
        assert chains["in"] or chains["mid"] or chains["out"], name
    if "slot" in a:
        assert 0 < int(a["slot"]) < 16, name
        weapons += 1
assert len(order) >= 61 and walks >= 5 and weapons >= 7, (len(order), walks, weapons)

engine = (ROOT / "src/xrGame/netcoop_rp_anims.inc").read_text(encoding="utf-8")
for key in ("in", "mid", "out", "loop", "once", "walk", "legs", "torso", "slot", "weapon", "items"):
    assert '"%s"' % key in engine, key
animation = (ROOT / "src/xrGame/ActorAnimation.cpp").read_text(encoding="utf-8", errors="replace")
assert "gop_stop" not in animation  # the weapon comes from the slot, not a name
assert sections['rp_nw_19']['weapon'] == sections['rp_nw_62']['weapon'] == 'pistol'
for name in order:
    a = sections['rp_' + name]
    if 'slot' in a:
        assert a.get('weapon') == 'rifle', name
    if name in {'nw_20', 'nw_28', 'nw_29', 'nw_30', 'nw_31', 'nw_40', 'nw_41', 'nw_42', 'nw_43', 'nw_50', 'nw_51', 'nw_52', 'nw_53'}:
        assert a.get('items'), (name, 'missing inventory requirement')
print("PASS RP animations: %d (%d walking, %d with a weapon), every motion in the actor OMFs, all keys the engine reads"
      % (len(order), walks, weapons))
