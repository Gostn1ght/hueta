"""Preserve native CI outputs in a private draft release, outside Actions quota."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def package(source, output, commit, run, attempt):
    if not re.fullmatch(r'[0-9a-f]{40}',commit) or run <= 0 or attempt <= 0:
        raise ValueError('Invalid CI identity')
    if (source/'built-from.txt').read_text(encoding='utf-8-sig').strip()!=commit:
        raise ValueError('Package commit differs from CI')
    output.mkdir(parents=True,exist_ok=False)
    files=[]
    for role in ('bin','dedicated'):
        for path in sorted((source/role).iterdir()):
            if path.is_file() and path.suffix.lower() in ('.exe','.dll'):
                files.append(path)
    files += [source/'built-from.txt']
    files += sorted(path for path in (source/'notices').rglob('*') if path.is_file())
    required={'bin/LostZoneClientDX11.exe','dedicated/LostZoneServerDX11.exe','dedicated/sqlite3.dll'}
    rows=[dict(path=p.relative_to(source).as_posix(),size=p.stat().st_size,sha256=digest(p)) for p in files]
    if not required <= {r['path'] for r in rows}:
        raise ValueError('Missing deployable runtime')
    if digest(source/'bin/LostZoneClientDX11.exe')!=digest(source/'dedicated/LostZoneServerDX11.exe'):
        raise ValueError('Client/server executable mismatch')
    runtime=output/'LostZone-native-runtime.zip'
    manifest=dict(schema=1,commit=commit,run=run,attempt=attempt,files=rows)
    with zipfile.ZipFile(runtime,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as packed:
        for path in files:
            packed.write(path,path.relative_to(source).as_posix())
        packed.writestr('native-files.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(runtime) as packed:
        assert len(packed.namelist())==len(rows)+1
        for row in rows:
            with packed.open(row['path']) as stream:
                assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
    # One matching PDB is enough: the client and server are the same executable.
    pdb=source/'bin/LostZoneClientDX11.pdb'
    symbols=output/'LostZone-native-symbols.zip'
    with zipfile.ZipFile(symbols,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as packed:
        packed.write(pdb,'LostZoneDX11.pdb')
        packed.writestr('built-from.txt',commit+'\n')
    result=dict(schema=1,commit=commit,run=run,attempt=attempt,
                runtime=dict(name=runtime.name,size=runtime.stat().st_size,sha256=digest(runtime)),
                symbols=dict(name=symbols.name,size=symbols.stat().st_size,sha256=digest(symbols)))
    (output/'native-ci.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':
        raise SystemExit('Native publication runs only inside GitHub Actions')
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path('lostzone-package'))
    parser.add_argument('--out',type=Path,default=Path('native-release'))
    args=parser.parse_args()
    commit=os.environ['GITHUB_SHA']
    run,attempt=int(os.environ['GITHUB_RUN_ID']),int(os.environ['GITHUB_RUN_ATTEMPT'])
    result=package(args.source,args.out,commit,run,attempt)
    tag=f'ci-native-{run}-{attempt}'
    notes=args.out/'release-notes.md'
    notes.write_text(f'Internal CI output for `{commit}`. Run {run}, attempt {attempt}.\n\n'
                     'Draft only. This is not an approved player release. Runtime and matching symbols have SHA-256 manifests.\n',encoding='utf-8')
    subprocess.run(['gh','release','create',tag,'--repo',os.environ['GITHUB_REPOSITORY'],
                    '--target',commit,'--draft','--title',f'Native CI {commit[:9]} ({run}/{attempt})',
                    '--notes-file',str(notes),str(args.out/result['runtime']['name']),
                    str(args.out/result['symbols']['name']),str(args.out/'native-ci.json')],check=True)
    print('Private draft CI outputs preserved:',tag,flush=True)


if __name__=='__main__':
    main()
