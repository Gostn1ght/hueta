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
import math,json

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
expected={f'lz_prone_{grip}_{direction}' for grip in ('empty','knife','pistol','rifle','launcher') for direction in ('idle','fwd','back','left','right')}
import json
launcher_qa=json.loads((root.parent/'docs/audit/195_CONNECTED_LAUNCHER_MOTIONS.json').read_text(encoding='utf-8'))
assert {d['name'] for d in prone['defs']}==expected | set(launcher_qa['connected']) | {'lz_vehicle_passenger','lz_vehicle_enter_driver','lz_vehicle_exit_driver','lz_vehicle_enter_passenger','lz_vehicle_exit_passenger'}
assert all(not d['flags']&2 for d in prone['defs']), 'prone movement must loop'
import hashlib,json
qa=json.loads((root.parent/'docs/audit/190_CONNECTED_MOTIONS.json').read_text())
assert qa['prone']['sha256']==launcher_qa['base_sha256']
assert launcher_qa['sha256']==hashlib.sha256(prone['data']).hexdigest()
for name,blob in prone['blobs'].values():
    if name in launcher_qa['preserved_motion_hashes']:
        assert hashlib.sha256(blob).hexdigest()==launcher_qa['preserved_motion_hashes'][name],name
assert len(qa['prone']['connected'])==20 and qa['raw_files_private']
for name,blob in prone['blobs'].values():
    if name in qa['preserved_motion_hashes']:
        assert hashlib.sha256(blob).hexdigest()==qa['preserved_motion_hashes'][name],name
print('PASS 20 connected captured prone cycles; legacy RPG and vehicle motions preserved exactly')

# Independently decode exported keys, not authoring-scene metadata. Verify
# that the passenger remains upright, faces the seat and keeps both feet
# below the pelvis throughout breathing, without a twisted asymmetric hip.
reader_spec=importlib.util.spec_from_file_location('poses',root/'read-omf-poses.py')
poses=importlib.util.module_from_spec(reader_spec);reader_spec.loader.exec_module(poses)
skeleton=json.loads((root.parent/'assets/animations/mesh2motion/game-skeleton-47.json').read_text())
assert len(skeleton['parents'])==47
motion=poses.Motions(actors/'modded_stalker_animations/netcoop_player_prone.omf',parents=skeleton['parents'])
for phase in (0,.125,.25,.375,.5,.625,.75,.875,.99):
    bones=motion.pose('lz_vehicle_passenger',phase,matrices=True)
    hip=bones['bip01_pelvis'][:3,3];head=bones['bip01_head'][:3,3]
    assert all(math.isfinite(float(v)) for mat in bones.values() for row in mat for v in row)
    assert max(abs(float(v)) for v in hip)<.0005
    assert .55<head[1]<.8 and abs(head[0])<.04
    assert bones['bip01_head'][2,2]>.93, 'head must face along the seat, not sideways'
    feet=[bones[f'bip01_{side}_foot'][:3,3] for side in ('l','r')]
    assert abs(feet[0][1]-feet[1][1])<.03
    assert abs(feet[0][2]-feet[1][2])<.03
    assert -.65<feet[0][1]<-.25 and -.65<feet[1][1]<-.25
    assert feet[0][0]<-.1 and feet[1][0]>.1
    assert .2<feet[0][2]<.65 and .2<feet[1][2]<.65
print('PASS decoded passenger keys: upright facing seat, hip at anchor, symmetric low feet; legacy passenger pose retained')

# Low cabins cannot use an ankle half a metre below the seat. Validate the
# actual additional keys, including every skeleton segment (no stretched legs).
fit_qa=json.loads((root.parent/'docs/audit/183_PASSENGER_FITS.json').read_text())
fit_path=actors/'modded_stalker_animations/netcoop_vehicle_passengers.omf'
assert hashlib.sha256(fit_path.read_bytes()).hexdigest()==fit_qa['candidate_sha256']
fit_data=merge.parse(str(fit_path))
assert {d['name'] for d in fit_data['defs']}==set(fit_qa['ankle_drops'])
assert all(not d['flags']&2 for d in fit_data['defs'])
fitted=poses.Motions(fit_path,parents=skeleton['parents'])
for name,drop in fit_qa['ankle_drops'].items():
    for phase in (0,.125,.25,.375,.5,.625,.75,.875,.99):
        bones=fitted.pose(name,phase,matrices=True)
        original=motion.pose('lz_vehicle_passenger',phase,matrices=True)
        points={bone:matrix[:3,3] for bone,matrix in bones.items()}
        assert all(math.isfinite(float(v)) for matrix in bones.values() for row in matrix for v in row)
        assert max(abs(float(v)) for v in points['bip01_pelvis'])<.0005
        for bone,parent in skeleton['parents'].items():
            if not parent:continue
            length=float(sum((points[bone]-points[parent])**2))**.5
            prior=float(sum((original[bone][:3,3]-original[parent][:3,3])**2))**.5
            assert abs(length-prior)<.001,(name,bone,'limb stretched',length,prior)
        for side,sign in [('l',-1),('r',1)]:
            foot=points[f'bip01_{side}_foot'];hand=points[f'bip01_{side}_hand']
            assert abs(float(foot[0])-sign*.12)<.001
            assert abs(float(foot[1])+drop)<.001 and abs(float(foot[2])-fit_qa['foot_forward'][name])<.001
            assert abs(float(hand[0]))<.17 and float(hand[1])>.14
        assert bones['bip01_head'][2,2]>.93
print('PASS fitted passenger keys: three low-seat heights, compact feet/hands, all 47 bone lengths preserved')

# Independently decode the actual newly connected clips: finite poses, real
# articulated gait and stable bone lengths through all weapon variants.
reference=motion.pose('lz_prone_empty_fwd',0,matrices=True)
for name in qa['prone']['connected']:
    frames=[]
    for phase in (0,.125,.25,.375,.5,.625,.75,.875,.99):
        pose=motion.pose(name,phase,matrices=True);frames.append(pose)
        assert all(math.isfinite(float(v)) for matrix in pose.values() for row in matrix for v in row)
        assert .10<float(pose['bip01_head'][1,3])<.75,(name,'not prone')
        for bone,parent in skeleton['parents'].items():
            if not parent or bone in ('bip01','bip01_pelvis'):continue
            length=float(sum((pose[bone][:3,3]-pose[parent][:3,3])**2))**.5
            rest=float(sum((reference[bone][:3,3]-reference[parent][:3,3])**2))**.5
            assert abs(length-rest)<.001,(name,bone,length,rest)
    if not name.endswith('_idle'):
        excursion=max(float(sum((pose[f'bip01_{side}_foot'][:3,3]-frames[0][f'bip01_{side}_foot'][:3,3])**2))**.5 for pose in frames for side in ('l','r'))
        assert excursion>.015,(name,'frozen gait')

bindings=json.loads((root.parent/'tools/dcp-driver-pose-fits.json').read_text())

# A crawling donor plants and rolls its wrist. The rifle hold is an authored
# assembly: both hands retain their relative grip, elbows remain below the
# shoulders, and the barrel does not inherit that planting roll. Decode every
# stored key, rather than checking only the attractive idle preview.
for direction in ('idle','fwd','back','left','right'):
    name='lz_prone_rifle_'+direction
    row=next(d for d in prone['defs'] if d['name']==name)
    import struct
    count=struct.unpack_from('<I',prone['blobs'][row['motion']][1])[0]
    reference_distance=None
    for frame in range(count):
        pose=motion.pose(name,frame/count,matrices=True)
        def point(bone):return pose[bone][:3,3]
        delta=point('bip01_r_finger11')-point('bip01_r_finger1')
        assert float(delta[2])/float(sum(delta*delta))**.5>.995,(name,frame,'rifle planting roll')
        assert point('bip01_r_forearm')[1]<point('bip01_r_upperarm')[1]-.05,(name,frame,'raised elbow')
        distance=float(sum((point('bip01_l_hand')-point('bip01_r_hand'))**2))**.5
        if reference_distance is None:reference_distance=distance
        assert abs(distance-reference_distance)<.001,(name,frame,'hands separated from grip')
print('PASS every rifle key: reviewed grip follows the body without planting roll or raised elbow')

# Dedicated RPG uses a paired authored motion/mount; preserve the 30 older
# motions and validate every decoded key, not a posed preview scene.
import numpy as np
config_name='mod_system_zzzzzzzz_netcoop_prone_rpg.ltx'
mount=np.eye(4)
for role in ('client','server'):
    config=root/f'netcoop-overlay/{role}/configs'/config_name
    assert hashlib.sha256(config.read_bytes()).hexdigest()==launcher_qa['config_sha256']
    text=config.read_text(encoding='ascii');assert '![wpn_rpg7]' in text
    for label,column in (('right',0),('up',1),('forward',2),('position',3)):
        values=re.search(r'^netcoop_prone_'+label+r'\s*=([^\n]+)',text,re.M).group(1)
        mount[:3,column]=[float(v.strip()) for v in values.split(',')]
    assert np.max(np.abs(mount-np.array(launcher_qa['matrix_game'])))<1e-7
assert np.all(np.isfinite(mount)) and abs(np.linalg.det(mount[:3,:3])-1)<.002
assert np.max(np.abs(mount[:3,:3].T@mount[:3,:3]-np.eye(3)))<.002
assert np.linalg.norm(mount[:3,3])<1
reference_hands=None;checked=0
for direction in ('idle','fwd','back','left','right'):
    name='lz_prone_launcher2_'+direction
    definition=next(row for row in prone['defs'] if row['name']==name)
    count=struct.unpack_from('<I',prone['blobs'][definition['motion']][1])[0]
    for frame in range(count):
        pose=motion.pose(name,frame/count,matrices=True)
        for bone,parent in skeleton['parents'].items():
            assert np.all(np.isfinite(pose[bone]))
            if parent and bone not in ('bip01','bip01_pelvis'):
                actual=np.linalg.norm(pose[bone][:3,3]-pose[parent][:3,3])
                expected_length=np.linalg.norm(reference[bone][:3,3]-reference[parent][:3,3])
                assert abs(actual-expected_length)<.001,(name,frame,bone)
        first=pose['bip01_r_finger1'];following=pose['bip01_r_finger11']
        forward=following[:3,3]-first[:3,3];forward/=np.linalg.norm(forward)
        side=np.cross(first[:3,1],forward);side/=np.linalg.norm(side)
        basis=np.eye(4);basis[:3,:3]=np.column_stack((side,np.cross(forward,side),forward));basis[:3,3]=first[:3,3]
        gun=basis@mount
        assert gun[2,2]/np.linalg.norm(gun[:3,2])>.995,(name,frame,'launcher aim')
        relative_hands=[np.linalg.inv(gun)@pose['bip01_'+side+'_hand'] for side in ('r','l')]
        if reference_hands is None:reference_hands=relative_hands
        assert max(np.max(np.abs(a-b)) for a,b in zip(relative_hands,reference_hands))<.002,(name,frame,'grip drift')
        assert all(0<=pose['bip01_'+side+'_forearm'][1,3]<.2 for side in ('r','l')),(name,frame,'elbow support')
        checked+=1
assert checked==launcher_qa['verified_keys']==323
assert 'lz_prone_launcher2_%s' in anim
print('PASS 323 decoded RPG keys: paired mount, level aim, both fixed grips, supported elbows, 47 bone lengths; 30 legacy motions unchanged')

driver_path=actors/'modded_stalker_animations/netcoop_vehicle_driving.omf'
assert hashlib.sha256(driver_path.read_bytes()).hexdigest()==qa['driving']['sha256']
driver_data=merge.parse(driver_path)
assert len(bindings)==qa['driving']['models']==43
assert {d['name'] for d in driver_data['defs']}=={row[key] for row in bindings.values() for key in ('idle','left','right')}
driving=poses.Motions(driver_path,parents=skeleton['parents'])
geometry_qa=json.loads((root.parent/'docs/audit/200_BMW_DRIVER_GEOMETRY.json').read_text(encoding='utf-8'))
assert geometry_qa['library_sha256']==hashlib.sha256(driver_path.read_bytes()).hexdigest()
layouts=json.loads((root.parent/'tools/dcp-seat-layouts.json').read_text(encoding='utf-8'))
assert hashlib.sha256(json.dumps(layouts,sort_keys=True,separators=(',',':')).encode()).hexdigest()==geometry_qa['layout_canonical_sha256']
assert geometry_qa['body_shell_and_door_clear'] and geometry_qa['floor_clear']
assert layouts['physics/vehicles/bmw/veh_bmw_u_01.ogf']['seats'][0]==geometry_qa['driver_anchor_after']
bmw_checked=0
for definition in driver_data['defs']:
    name=definition['name'];blob=driver_data['blobs'][definition['motion']][1]
    if name in geometry_qa['preserved_motion_hashes']:
        assert hashlib.sha256(blob).hexdigest()==geometry_qa['preserved_motion_hashes'][name], ('Unrelated driving motion changed',name)
        continue
    assert name in {'lz_drive_bmw7_'+mode for mode in ('idle','left','right')}
    count=struct.unpack_from('<I',blob)[0]
    for frame in range(count):
        pose=driving.pose(name,frame/count,matrices=True)
        for bone,parent in skeleton['parents'].items():
            assert np.all(np.isfinite(pose[bone]))
            if parent and bone not in ('bip01','bip01_pelvis'):
                actual=np.linalg.norm(pose[bone][:3,3]-pose[parent][:3,3])
                expected_length=np.linalg.norm(reference[bone][:3,3]-reference[parent][:3,3])
                assert abs(actual-expected_length)<.001,(name,frame,bone,'Changed joint length')
        bmw_checked+=1
assert bmw_checked==geometry_qa['verified_keys']==213 and len(geometry_qa['preserved_motion_hashes'])==126
print('PASS 213 BMW driver keys, seat review binding and 126 byte-identical unrelated driving motions')
for visual,row in bindings.items():
    assert hashlib.sha256((root/'netcoop-overlay/client/meshes'/visual).read_bytes()).hexdigest()==row['model_sha256']
    for role in ('client','server'):
        config=(root/f'netcoop-overlay/{role}/configs/mod_system_lz_dcp_vehicles.ltx').read_text(encoding='cp1251')
        block=config.split('['+row['section']+']',1)[1].split('\n[',1)[0]
        for field,key in [('netcoop_driver_pose','idle'),('netcoop_driver_steer_left','left'),('netcoop_driver_steer_right','right')]:
            assert field+' = '+row[key] in block,(row['section'],field)
    base=driving.pose(row['idle'],0,matrices=True)
    for key in ('idle','left','right'):
        for phase in (0,.5,.99):
            pose=driving.pose(row[key],phase,matrices=True)
            assert max(abs(float(v)) for v in pose['bip01_pelvis'][:3,3])<.001
            assert all(math.isfinite(float(v)) for matrix in pose.values() for line in matrix for v in line)
            for bone,parent in skeleton['parents'].items():
                if not parent or bone in ('bip01','bip01_pelvis'):continue
                length=float(sum((pose[bone][:3,3]-pose[parent][:3,3])**2))**.5
                rest=float(sum((base[bone][:3,3]-base[parent][:3,3])**2))**.5
                assert abs(length-rest)<.001,(row['section'],key,bone)
print('PASS decoded 20 prone cycles and 129 fitted driver motions: articulated gait, 47 bone lengths, exact model bindings in both roles')
