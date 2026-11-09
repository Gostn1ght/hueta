"""Build game-named motion libraries from verified private retarget outputs.

Raw Mixamo FBX stays private. Preserves unrelated original motions and the
previous RPG fallback while the dedicated RPG grip remains under review.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('merge',root/'scripts/tools/merge-player-anims.py')
merge=importlib.util.module_from_spec(spec);spec.loader.exec_module(merge)

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def write_library(template,entries,path):
    data=template['data'];definitions=[];motions=[merge.chunk(0,struct.pack('<I',len(entries)))]
    for index,(name,definition,payload) in enumerate(entries):
        tail=definition['raw'][len(definition['name'])+1:]
        # Blender exports v4 (an extra zero motion-mark count); the existing
        # standalone library is v3. These captured cycles have no event marks.
        if template['version']==3 and len(tail)==28:
            assert tail[24:]==b'\0'*4, 'Event marks need explicit version conversion'
            tail=tail[:24]
        assert len(tail)==24 if template['version']==3 else len(tail)>=28
        tail=tail[:6]+struct.pack('<H',index)+tail[8:]
        definitions.append(name.encode('ascii')+b'\0'+tail)
        motions.append(merge.chunk(index+1,name.encode('ascii')+b'\0'+payload))
    result=b''
    for kind,start,size in template['top']:
        if kind==merge.OGF_S_SMPARAMS:
            reader=merge.Reader(data,start);reader.u16()
            for _ in range(reader.u16()):
                reader.strz()
                for _ in range(reader.u16()):reader.strz();reader.u32()
            payload=data[start:reader.p]+struct.pack('<H',len(entries))+b''.join(definitions)
        elif kind==merge.OGF_S_MOTIONS:payload=b''.join(motions)
        else:payload=data[start:start+size]
        result+=merge.chunk(kind,payload)
    path.write_bytes(result)
    check=merge.parse(path)
    assert len(check['defs'])==len(entries)
    assert len({row['name'] for row in check['defs']})==len(entries)
    for row,(name,_,blob) in zip(check['defs'],entries):
        assert row['name']==name and check['blobs'][row['motion']]==(name,blob)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',action='append',required=True,help='grip=private verified directory')
    p.add_argument('--driver',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    overlay=root/'scripts/netcoop-overlay/client/meshes/actors/modded_stalker_animations'
    original=merge.parse(overlay/'netcoop_player_prone.omf')
    entries={row['name']:(row['name'],row,original['blobs'][row['motion']][1]) for row in original['defs']}
    original_rows=dict(entries);sources=[];connected=[]
    for value in args.source:
        grip,folder=value.split('=',1);folder=Path(folder)
        assert grip in ('empty','rifle','pistol','knife')
        receipt=json.loads((folder/'review.json').read_text())
        path=folder/'candidate.omf'
        assert receipt['source']=='https://www.mixamo.com/' and receipt['raw_files_private']
        assert receipt['root_mode']=='in-place' and receipt['lock_facing']
        assert receipt['roundtrip_max_error_metres']<.001 and digest(path)==receipt['candidate_sha256']
        source=merge.parse(path)
        assert source['parts']==original['parts']
        by_name={row['name']:row for row in source['defs']}
        for direction in ('fwd','idle','back','left','right'):
            name=f'lz_prone_{grip}_{direction}';old='review_'+grip+'_'+direction
            row=by_name[old];entries[name]=(name,row,source['blobs'][row['motion']][1]);connected.append(name)
        sources.append(dict(grip=grip,sha256=digest(path),clips=receipt['clips'],roundtrip_max_error_metres=receipt['roundtrip_max_error_metres']))
    assert {row['grip'] for row in sources}=={'empty','rifle','pistol','knife'}
    # Native RPG routing used the old rifle clips when no launcher clip existed.
    # Preserve those exact motions explicitly so replacing rifles does not
    # silently install an unverified RPG grip as a side effect.
    launcher=[]
    for direction in ('fwd','idle','back','left','right'):
        name='lz_prone_launcher_'+direction
        if name not in entries:
            _,row,blob=original_rows['lz_prone_rifle_'+direction]
            entries[name]=(name,row,blob)
        launcher.append(name)
    target=args.out/'netcoop_player_prone.omf'
    write_library(original,list(entries.values()),target)
    receipt=json.loads((args.driver/'review.json').read_text())
    driver=args.driver/'candidate.omf'
    assert receipt['roundtrip_max_error_metres']<.001 and digest(driver)==receipt['candidate_sha256']
    driver_rows=merge.parse(driver)
    assert driver_rows['parts']==original['parts']
    bindings={}
    for row in receipt['rows']:
        if 'clips' not in row:continue
        assert len(row['clips'])==3 and row['max_contact_error_metres']<.00001
        bindings[row['visual']]=dict(section=row['section'],model_sha256=row['sha256'],
            idle=row['clips'][0],left=row['clips'][1],right=row['clips'][2],
            wheel=row['wheel'],torso_lean_degrees=row['torso_lean_degrees'],lower_body_motion=row['lower_body_motion'])
    assert set(row['name'] for row in driver_rows['defs'])=={name for row in bindings.values() for name in (row['idle'],row['left'],row['right'])}
    (args.out/'netcoop_vehicle_driving.omf').write_bytes(driver.read_bytes())
    (args.out/'dcp-driver-pose-fits.json').write_text(json.dumps(bindings,indent=2)+'\n')
    result=dict(source='https://www.mixamo.com/',license_reference='https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html',
        raw_files_private=True,prone=dict(sha256=digest(target),connected=connected,preserved_launcher_fallback=launcher,sources=sources),
        driving=dict(sha256=digest(driver),models=len(bindings),motions=len(driver_rows['defs']),roundtrip_max_error_metres=receipt['roundtrip_max_error_metres'],
            skipped=[row for row in receipt['rows'] if 'skipped' in row]))
    (args.out/'connected-motions.json').write_text(json.dumps(result,indent=2)+'\n')
    print('CONNECTED_MOTIONS',len(connected),'prone,',len(driver_rows['defs']),'driver,',len(bindings),'models')

if __name__=='__main__':main()
