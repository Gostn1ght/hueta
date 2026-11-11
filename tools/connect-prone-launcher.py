"""Stage five fully audited launcher clips beside unchanged installed motions."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True)
p.add_argument('--grip',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('connect',root/'tools/connect-player-motions.py')
connect=importlib.util.module_from_spec(spec);spec.loader.exec_module(connect)
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
receipt=json.loads((a.source/'review.json').read_text(encoding='utf-8'))
verified=json.loads((a.source/'complete-verification.json').read_text(encoding='utf-8'))
assert receipt['candidate_sha256']==digest(a.source/'candidate.omf')
assert receipt['verified_keys']==323 and receipt['roundtrip_max_error_metres']<.001
assert receipt['aim_layer']['sha256']==digest(a.grip/'candidate.omf')
grip=json.loads((a.grip/'review.json').read_text(encoding='utf-8'))
assert grip['full_hand_wrap']['pairs']==0
skeleton=json.loads((root/'assets/animations/mesh2motion/game-skeleton-47.json').read_text(encoding='utf-8'))
assert sum(row['frames'] for row in verified['clips'])==323
for row in verified['clips']:
    assert not row['bad'] and row['body_min']>.005 and row['weapon_min']>.005 and row['aim_min']>.995
    folder=a.source/('verified-'+row['motion'])
    inputs=json.loads((folder/'review-inputs.json').read_text(encoding='utf-8'))
    assert inputs['omf_sha256']==receipt['candidate_sha256'] and inputs['actor_sha256']==skeleton['source_sha256']
    assert inputs['samples']==row['frames'] and inputs['surface_audit']
    assert inputs['report_sha256']==digest(folder/'weapon-directions.json')
base=root/'scripts/netcoop-overlay/client/meshes/actors/modded_stalker_animations/netcoop_player_prone.omf'
original=connect.merge.parse(base);source=connect.merge.parse(a.source/'candidate.omf')
assert original['parts']==source['parts']
entries=[(row['name'],row,original['blobs'][row['motion']][1]) for row in original['defs']]
assert not any(name.startswith('lz_prone_launcher2_') for name,_,_ in entries),'Already connected; review replacement explicitly'
connected=[]
for row in source['defs']:
    assert row['name'].startswith('review_launcher2_')
    name=row['name'].replace('review_','lz_prone_',1)
    entries.append((name,row,source['blobs'][row['motion']][1]));connected.append(name)
assert set(connected)=={'lz_prone_launcher2_'+d for d in ('idle','fwd','back','left','right')}
target=a.out/'netcoop_player_prone.omf';connect.write_library(original,entries,target)
matrix=grip['attachment_review']['matrix_game']
config=['; Dedicated authored RPG pose; legacy/standing/NPC mounts remain unchanged.','![wpn_rpg7]']
for label,column in (('right',0),('up',1),('forward',2),('position',3)):
    config.append('netcoop_prone_'+label+' = '+', '.join(format(matrix[r][column],'.9g') for r in range(3)))
config_path=a.out/'mod_system_zzzzzzzz_netcoop_prone_rpg.ltx'
config_path.write_text('\n'.join(config)+'\n',encoding='ascii')
result=dict(installed=False,base_sha256=digest(base),sha256=digest(target),connected=connected,
            source_sha256=receipt['candidate_sha256'],grip_sha256=digest(a.grip/'candidate.omf'),
            matrix_game=matrix,config_sha256=digest(config_path),verified_keys=323,
            preserved_motion_hashes={row['name']:hashlib.sha256(original['blobs'][row['motion']][1]).hexdigest() for row in original['defs']},
            raw_files_private=True,verification=verified)
(a.out/'launcher-connected.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print('Staged five launcher clips; preserved',len(original['defs']),'existing motions')
