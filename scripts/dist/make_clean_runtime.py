"""Prepare complete role archives and isolated clean packages; never runs a game.

Preparation extracts only verified public resources and copies public configs.
Packing is a separate immutable step after the inputs have been reviewed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/lzpack'))
import lzpack
from runtime_layout import effective, safe

def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def fnv(path):
    value=14695981039346656037
    with path.open('rb') as stream:
        while data:=stream.read(1024*1024):
            for byte in data: value=((value^byte)*1099511628211)&0xffffffffffffffff
    return value

def link(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    try: os.link(source,target)
    except OSError: shutil.copy2(source,target)

def copy_tree(source,target):
    if not source.exists(): return
    for path in source.rglob('*'):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()): raise ValueError('Linked input is forbidden')
        if path.is_file():
            dst=target/path.relative_to(source);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dst)

def extract(index,target):
    records={}
    for number,(name,(archive,virtual)) in enumerate(sorted(index.items())):
        if not safe(name): raise ValueError('Invalid input namespace')
        path=target/Path(name.replace('\\','/'))
        records[name.replace('\\','/')]=archive.extract(virtual,path)
        if number%500==0: print('Extract verified public files',target.name,number,'/',len(index),flush=True)
    return records

def prepare(args):
    output=args.out.resolve()
    if output.exists(): raise FileExistsError('Preparation output exists; inspect it before selecting a new candidate directory')
    output.mkdir(parents=True)
    key=lzpack.master(args.key)
    review={'schema':2,'prepared_utc':datetime.now(timezone.utc).isoformat(),
            'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'roles':{}}
    maps={}
    for role,source in [('client',args.client),('server',args.server)]:
        role_input=output/'input'/role
        arcs,scripts,assets,configs=effective(source/'resources',key,role)
        if len(scripts)<1000: raise ValueError('Incomplete effective '+role+' script library')
        script_records=extract(scripts,role_input/'scripts')
        extract(configs,role_input/'configs')
        copy_tree(source/role/'configs',role_input/'configs')
        if len(list((role_input/'configs').rglob('*.*')))<4000: raise ValueError('Incomplete '+role+' config tree')
        if role=='client':
            baseline=[]
            for path in sorted((role_input/'configs').rglob('*')):
                if path.is_file(): baseline.append((path.relative_to(role_input/'configs').as_posix().replace('/','\\').lower(),path.stat().st_size,fnv(path)))
            marker=role_input/'configs/netcoop/config_migration_000047.ltx';marker.parent.mkdir(parents=True,exist_ok=True)
            marker.write_bytes(('[old_configs]\r\n'+''.join('%s = %d,%016x\r\n'%row for row in baseline)).encode('cp1251'))
        overlay=ROOT/'scripts/netcoop-overlay'/role
        copy_tree(overlay/'configs',role_input/'configs')
        for path in overlay.rglob('*'):
            if not path.is_file(): continue
            rel=path.relative_to(overlay)
            if path.suffix in ('.script','.lua') and rel.parts[0] not in ('configs','gamedata','shaders','textures','meshes','sounds'):
                dst=role_input/'scripts'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dst)
        maps[role]=extract(assets,role_input/'assets')
        candidate=output/role
        (candidate/'resources').mkdir(parents=True)
        for path in (source/'resources').iterdir():
            if path.is_file() and not path.name.startswith(('90_lostzone_lz_misc','90_lostzone_lz_scripts','95_server_','99_')):
                link(path,candidate/'resources'/path.name)
        native='bin' if role=='client' else 'dedicated'
        copy_tree(source/native,candidate/native)
        if role=='client':
            copy_tree(source/'notices',candidate/'bin/notices')
            shutil.copy2(ROOT/'scripts/dist/fsgame_client.template',candidate/'fsgame.template')
            shutil.copy2(ROOT/'scripts/dist/Play Lost Zone.cmd',candidate/'Play Lost Zone.cmd')
        else:
            copy_tree(source/'notices',candidate/'dedicated/notices')
            shutil.copy2(ROOT/'scripts/dist/fsgame_server.template',candidate/'dedicated/fsgame_server.template')
        review['roles'][role]={'source_archives':[a.path.name for a in arcs],'scripts':len(script_records),'assets':len(maps[role]),
            'configs':sum(p.is_file() for p in (role_input/'configs').rglob('*'))}
    shared={name for name,row in maps['client'].items() if name in maps['server'] and row['sha256']==maps['server'][name]['sha256']}
    review['shared_assets']=len(shared)
    for role in ('client','server'):
        for name in sorted(shared):
            path=output/'input'/role/'assets'/name
            if role=='client': link(path,output/'input/shared/assets'/name)
            assert path.resolve().is_relative_to(output)
            path.unlink() # staging-only duplicate; shared immutable input is retained
        # Empty directory remnants do not enter the archives.
    inputs=[]
    for path in sorted((output/'input').rglob('*')):
        if path.is_file(): inputs.append(dict(path=path.relative_to(output).as_posix(),size=path.stat().st_size,sha256=sha(path)))
    review['inputs']=inputs
    (output/'layout-prepared.json').write_text(json.dumps(review,indent=2)+'\n',encoding='utf-8')
    print('Clean runtime inputs prepared:',{k:v for k,v in review.items() if k!='inputs'},flush=True)

def pack(args):
    output=args.out.resolve();review=json.loads((output/'layout-prepared.json').read_text())
    if not args.version or len(args.version)!=6 or not args.version.isdigit(): raise ValueError('A new six-digit immutable version is required')
    destination=output/'archives'
    if destination.exists(): raise FileExistsError('Archive output already exists; version is immutable')
    for row in review['inputs']:
        path=output/row['path']
        if path.stat().st_size!=row['size'] or sha(path)!=row['sha256']: raise ValueError('Prepared input changed: '+row['path'])
    key=lzpack.master(args.key);destination.mkdir();plain=output/'retained-plain';plain.mkdir()
    report=[]
    for role,kind,order,alias in [('shared','assets','10','$game_data$\\'),('client','assets','20','$game_data$\\'),
        ('server','assets','20','$game_data$\\'),('client','configs','30','$game_config$\\'),('server','configs','30','$game_config$\\'),
        ('client','scripts','40','$game_scripts$\\'),('server','scripts','40','$game_scripts$\\')]:
        folder=output/'input'/role/kind
        if not folder.exists(): continue
        rows=lzpack.files_under(folder);groups=[];group=[];size=0
        for name,path in rows:
            length=path.stat().st_size
            if length>lzpack.MAX_VOLUME: raise ValueError('Single runtime file exceeds archive volume limit')
            if group and size+length>lzpack.MAX_VOLUME: groups.append(group);group=[];size=0
            group.append((name,path));size+=length
        if group: groups.append(group)
        for volume,group in enumerate(groups):
            stem=f'99_v2_{args.version}_{order}_{role}_{kind}_{volume:03d}.db0'
            raw=plain/stem;protected=destination/stem
            lzpack.make_db(group,raw,alias);lzpack.protect(raw,protected,key)
            row=dict(path=stem,role=role,kind=kind,files=len(group),size=protected.stat().st_size,sha256=sha(protected))
            report.append(row)
            for target in ('client','server') if role=='shared' else (role,):
                # Keep server overrides out of the client's nonrecursive scan
                # when a hoster installs the server alongside an existing game.
                directory=output/target/'resources'/('server' if role=='server' else '')
                directory.mkdir(parents=True,exist_ok=True)
                link(protected,directory/stem)
            print('Verified runtime archive',stem,'files',len(group),'bytes',row['size'],flush=True)
    (output/'layout-archives.json').write_text(json.dumps({'version':args.version,'archives':report},indent=2)+'\n',encoding='utf-8')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','pack'])
    parser.add_argument('--client',type=Path)
    parser.add_argument('--server',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--key',required=True,type=Path)
    parser.add_argument('--version')
    args=parser.parse_args()
    if args.mode=='prepare': prepare(args)
    else: pack(args)
if __name__=='__main__': main()
