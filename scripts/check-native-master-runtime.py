"""CI only: verify a published CI runtime and execute its actual master entry.

No engine compilation, game data, location processes or game launch. A full
engine executable renamed LostZoneMaster.exe must take the early master path.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile

if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Packaged native runtime checks run only on Windows GitHub Actions')
ap=argparse.ArgumentParser()
ap.add_argument('--run',required=True,type=int)
ap.add_argument('--commit',required=True)
ap.add_argument('--out',required=True,type=Path)
args=ap.parse_args()
assert args.run>0 and len(args.commit)==40 and all(c in '0123456789abcdef' for c in args.commit)
repo='Gostn1ght/hueta'
def gh(*arguments):return subprocess.run(['gh',*arguments],check=True,capture_output=True).stdout
def api(path):return json.loads(gh('api','repos/'+repo+'/'+path))
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
build=api(f'actions/runs/{args.run}')
assert build['head_sha']==args.commit and build['conclusion']=='success' and build['name']=='Lost Zone DX11'
tag=f'ci-native-{args.run}-{build["run_attempt"]}'
release=next(row for row in api('releases?per_page=100') if row['tag_name']==tag)
assert release['draft'] and release['target_commitish']==args.commit
with tempfile.TemporaryDirectory(prefix='lz actual master runtime ') as temporary:
    work=Path(temporary)
    assets={row['name']:row for row in release['assets']}
    for name in ('native-ci.json','LostZone-native-runtime.zip'):
        gh('release','download',tag,'--repo',repo,'--pattern',name,'--dir',str(work))
        assert (work/name).stat().st_size==assets[name]['size']
        if assets[name].get('digest'):assert assets[name]['digest']=='sha256:'+sha(work/name)
    metadata=json.loads((work/'native-ci.json').read_text())
    assert metadata['commit']==args.commit and metadata['run']==args.run and metadata['attempt']==build['run_attempt']
    packed=work/'LostZone-native-runtime.zip'
    assert packed.stat().st_size==metadata['runtime']['size'] and sha(packed)==metadata['runtime']['sha256']
    runtime=work/'server'
    with zipfile.ZipFile(packed) as archive:
        manifest=json.loads(archive.read('native-files.json'))
        assert manifest['commit']==args.commit and manifest['run']==args.run
        rows={row['path']:row for row in manifest['files']}
        assert len(rows)==len(manifest['files']) and set(archive.namelist())==set(rows)|{'native-files.json'}
        assert rows['bin/LostZoneClientDX11.exe']['sha256']==rows['dedicated/LostZoneServerDX11.exe']['sha256']
        for relative,row in rows.items():
            path=PurePosixPath(relative)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in relative and '\\' not in relative
            info=archive.getinfo(relative)
            assert not info.is_dir() and info.file_size==row['size'] and info.file_size<512*1024**2
            with archive.open(relative) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
            if relative.startswith('dedicated/'):
                assert len(path.parts)==2 and path.suffix.lower() in ('.exe','.dll')
                target=runtime/relative;target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(relative) as incoming,target.open('xb') as outgoing:shutil.copyfileobj(incoming,outgoing)
    dedicated=runtime/'dedicated'
    executable=dedicated/'LostZoneMaster.exe'
    shutil.copy2(dedicated/'LostZoneServerDX11.exe',executable)
    assert sha(executable)==rows['dedicated/LostZoneServerDX11.exe']['sha256']
    (dedicated/'fsgame_server.template').write_text('$fs_root$ = false | false | {ROOT}\n',encoding='ascii')
    subprocess.run([str(executable),'bootstrap','--root',str(runtime)],cwd=dedicated,check=True,timeout=45)
    plan=runtime/'appdata/server/netcoop_cluster.ltx'
    assert 'l08_yantar =' in plan.read_text() and (runtime/'appdata/master/config.json').is_file()
    result=work/'selftest.json'
    subprocess.run([str(executable),'window','--root',str(runtime),'--port','0','--gateway-port','0',
        '--initialized','--selftest',str(result)],cwd=dedicated,check=True,timeout=120)
    tested=json.loads(result.read_text())
    assert tested['ok'] and tested['stopped'] and tested['screenshot'] and tested['locations']==33
    args.out.mkdir(parents=True,exist_ok=True)
    shutil.copy2(str(result)+'.bmp',args.out/'master-runtime-window.bmp')
    report=dict(schema=1,source_commit=args.commit,build_run=args.run,executable_sha256=sha(executable),
        actual_full_engine_named_master_entry=True,native_bootstrap=True,all_33_ports=True,
        actual_window_selftest=tested,no_game_or_location_started=True)
    (args.out/'runtime-reviewed.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS actual packaged engine: renamed native master bootstraps, opens its window, serves and closes; no game data or locations started')
