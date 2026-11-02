"""Third-person animations (owner 2026-10-10, doc 90 §4): the overlay's OMF
files (GAMMA's motions with xAGNA/xrMPE motion data merged in by
scripts/tools/merge-player-anims.py) are well-formed: every motion
definition has its motion data at its index, under its name; stalker_animation
keeps GAMMA's device, PDA, binocular and eating motions; partitions are the
stalker skeleton's. xAGNA's configs do not change NPC behaviour: no movement
speeds, no fire/shell points (NPC shots stay GAMMA's). Device poses
(xrRazom's xrMPE set, modded_stalker_animations): only xrr_ names (nothing
shadows GAMMA's motions), held-up poses for a flashlight/glow stick and
detector poses for every hand combination; the engine picks them by device."""
from pathlib import Path
import importlib.util
import re

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("merge", root / "tools/merge-player-anims.py")
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)

actors = root / "netcoop-overlay/client/meshes/actors"
files = sorted(actors.glob("*.omf")) + sorted(actors.glob("modded_stalker_animations/*.omf"))
assert files and (actors / "stalker_animation.omf") in files
for f in files:
    o = merge.parse(str(f))
    assert len(o["defs"]) == o["count"] == len(o["blobs"]), f.name
    assert [p[0] for p in o["parts"]] == ["legs", "torso", "head"], f.name
    for d in o["defs"]:
        name, blob = o["blobs"][d["motion"]]
        assert name == d["name"] and blob, (f.name, d["name"])
main = {d["name"] for d in merge.parse(str(actors / "stalker_animation.omf"))["defs"]}
assert len(main) == 1652
for kept in ("norm_torso_0+detector_aim_0", "norm_torso_pda_idle_1", "binoculars_draw_0", "banka_anim_use_medkit",
             "norm_torso_0_walk_1", "norm_escape_0", "cr_torso_5+detector_aim_0"):
    assert kept in main, kept

for role in ("client", "server"):
    cfg = root / f"netcoop-overlay/{role}/configs"
    step = (cfg / "mod_system_zzzzzzzzzzzzzz_xagna_m_stalker.ltx").read_text(encoding="latin1")
    wpn = (cfg / "mod_system_zzzzzzzzzz_xagna_wpn_pos.ltx").read_text(encoding="latin1")
    assert "[stalker_step_manager]" in step and not re.search(r"^!?\[stalker_movement_speeds\]", step, re.M)
    assert not re.search(r"^\s*(fire_point|shell_point)", wpn, re.M | re.I)
    assert len(re.findall(r"^!\[wpn_", wpn, re.M)) > 100
dev = {d["name"] for d in merge.parse(str(actors / "modded_stalker_animations/netcoop_player_devices.omf"))["defs"]}
assert all(n.startswith("xrr_") for n in dev) and not dev & main
for kind in ("torchelo", "detector"):
    for base in ("0", "6", "knife", "pistol"):
        actions = ["idle_1", "run_1", "escape_0", "drawdevice_0", "holsterdevice_0", "aim_0"]
        actions += ["reload_0"] if base == "pistol" else ["walk_1"]
        for action in actions:
            assert f"xrr_norm_torso_{base}_{kind}_{action}" in dev, (base, kind, action)
    for action in ("aim_0", "aim_1", "aim_2", "aim_3"):
        assert f"xrr_cr_torso_0_{kind}_{action}" in dev
anim = (root.parent / "src/xrGame/ActorAnimation.cpp").read_text(encoding="utf-8-sig", errors="replace")
assert 'smart_cast<CFlashlight*>(device) ? "torchelo" : "detector"' in anim
assert '"xrr_%s_torso_%s_%s_%s"' in anim and '"walk_1"' in anim
assert "xrr_cr_torso_1_detector_aim_1" in dev and "xrr_cr_torso_1_torchelo_aim_1" in dev and '? "1" : base' in anim
for action in ('"drawall_0"', '"holsterall_0"', '"draw_0"', '"holster_0"', "CMissile::eThrowStart", '"reload_0"'):
    assert action in anim, action
for kind in ("torchelo", "detector"):
    for base, actions in (("pistol", ("draw_0", "holster_0", "drawall_0", "holsterall_0", "attack_0", "attack_1", "reload_0")),
                          ("knife", ("draw_0", "holster_0", "drawall_0", "holsterall_0", "attack_0", "attack_1")),
                          ("6", ("draw_0", "holster_0", "drawall_0", "holsterall_0", "attack_0", "attack_1", "attack_2"))):
        for action in actions:
            assert f"xrr_norm_torso_{base}_{kind}_{action}" in dev, (base, kind, action) and '#include "Flashlight.h"' in anim
prone=merge.parse(str(actors/'modded_stalker_animations/netcoop_player_prone.omf'))
expected={f'lz_prone_{grip}_{direction}' for grip in ('empty','knife','pistol','rifle') for direction in ('idle','fwd','back','left','right')}
assert {d['name'] for d in prone['defs']}==expected | {'lz_vehicle_passenger','lz_vehicle_enter_driver','lz_vehicle_exit_driver','lz_vehicle_enter_passenger','lz_vehicle_exit_passenger'}
assert all(not d['flags']&2 for d in prone['defs']), 'prone movement must loop'
import hashlib,json
qa=json.loads((root.parent/'docs/audit/167_PRONE_POSE_QA.json').read_text())
assert qa['omf_sha256']==hashlib.sha256(prone['data']).hexdigest()
assert 0.2<qa['sampled_head_height'][0]<=qa['sampled_head_height'][1]<0.5
for grip in ('empty','knife','pistol','rifle'):
    samples=[s for s in qa['samples'] if s['clip']==f'lz_prone_{grip}_fwd']
    assert len(samples)==4
    for side in ('l','r'):
        foot=[s['bones'][f'bip01_{side}_foot'] for s in samples]
        assert max(p[1] for p in foot)-min(p[1] for p in foot)>.12
        assert all(.02<p[2]<.3 for p in foot)
print("netcoop anims: OK; 20 isolated prone cycles, low body, moving feet, exact QA asset checksum")
