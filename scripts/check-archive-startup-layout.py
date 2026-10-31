"""Check one-pass archive entry points and co-located client/server precedence.

CLocatorAPI::_initialize recurses each path immediately, before registering the
next alias. A template must therefore define the archive's target aliases before
its archive scan. No game/native process or private data is needed.
"""
from pathlib import Path
import ntpath

ROOT=Path(__file__).resolve().parents[1]
BASE='j:\\fixture\\'

def resolve(text):
    aliases={}
    scans=[]
    events=[]
    for line in text.replace('{ROOT}',BASE).splitlines():
        if not line.strip() or line.lstrip().startswith(';'):continue
        alias,fields=line.split('=',1)
        alias=alias.strip();fields=[x.strip() for x in fields.split('|')]
        value=aliases.get(fields[2],fields[2])+(fields[3] if len(fields)>3 else '')
        if alias in ('$arch_dir$','$lz_server_archives$'):
            assert fields[0]=='false','Nested role archives must not leak into another role'
            scans.append((value,dict(aliases)))
        events.append((alias,value))
        aliases[alias]=value
    return aliases,scans,events

def check(role,text):
    aliases,scans,events=resolve(text)
    assert len(scans)==(1 if role=='client' else 2)
    assert scans[0][0]==BASE+'resources\\'
    for _,known in scans:
        for alias in ('$fs_root$','$game_data$','$game_config$','$game_scripts$'):
            assert alias in known,f'{role} scans archives before defining {alias}'
        system=ntpath.join(known['$game_config$'],'system.ltx')
        assert system==BASE+'appdata\\'+('player' if role=='client' else 'server')+'\\configs\\system.ltx'
    # Registration is last-writer-wins. Defaults must not override physical
    # user settings or loose mod assets that were discovered earlier.
    mounted={}
    for alias,folder in events:
        if alias in ('$arch_dir$','$lz_server_archives$'):mounted.update(setting='archive',mesh='archive')
        if alias=='$lz_asset_overrides$':
            assert folder==aliases['$game_data$'];mounted['mesh']='loose'
        if alias=='$lz_config_overrides$':
            assert folder==aliases['$game_config$'];mounted['setting']='personal'
    assert mounted=={'setting':'personal','mesh':'loose'},'Archives shadow physical overrides'
    return scans

client=(ROOT/'scripts/dist/fsgame_client.template').read_text(encoding='utf-8-sig')
server=(ROOT/'scripts/dist/fsgame_server.template').read_text(encoding='utf-8-sig')
c=check('client',client);s=check('server',server)
assert s[1][0]==BASE+'resources\\server\\'
# Simulate both packages in the same root: only server sees its nested overrides.
files={BASE+'resources\\':{'system':'client','scripts':'client'},BASE+'resources\\server\\':{'system':'server','scripts':'server'}}
for scans,expected in [(c,'client'),(s,'server')]:
    mounted={}
    for folder,_ in scans:mounted.update(files[folder])
    assert mounted=={'system':expected,'scripts':expected}
# The old template must reproduce the missing-system.ltx failure, rather than
# merely exercising an order that happens to pass with the new templates.
line='$arch_dir$ = false | false | {ROOT}resources\\'
old=client.replace(line,'')
old=old.replace('$game_data$',line+'\n$game_data$',1)
try:check('client',old)
except AssertionError:pass
else:raise AssertionError('Missing-alias startup regression was not detected')
print('PASS one-pass startup: system.ltx/config/script aliases known before archive mount; shared client/server folder keeps role overrides isolated; old order rejected; no game started')
