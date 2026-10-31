"""CI: link a small production GUI master from the tested engine master objects.

Recompile the entry without LZM_TEST_FIXTURES; exclude the fixture object.
The resulting application has no engine/game entry or embedded game keys.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Production native compilation is GitHub-only')
output=Path('master-test');production=Path('master-production');production.mkdir()
subprocess.run(['cl','/nologo','/c','/std:c++17','/EHsc','/O2','/Zi','/utf-8','/W3','/permissive-',
    '/DWIN32','/D_WINDOWS','/D_CRT_SECURE_NO_WARNINGS','src/xrEngine/netcoop_master/lzm_standalone.cpp',
    '/Fo:'+str(production/'lzm_standalone.obj'),'/Fd:'+str(production/'master.pdb')],check=True)
objects=[str(p) for p in sorted(output.glob('*.obj')) if p.stem not in ('lzm_standalone','lzm_test_storage')]
assert len(objects)>10
executable=output/'LostZoneMaster.exe'
subprocess.run(['link','/NOLOGO','/DEBUG','/SUBSYSTEM:WINDOWS','/ENTRY:wmainCRTStartup','/OUT:'+str(executable),
    '/PDB:'+str(production/'LostZoneMaster.pdb'),*objects,str(production/'lzm_standalone.obj'),
    'user32.lib','gdi32.lib','shell32.lib','comctl32.lib','uxtheme.lib','dwmapi.lib','ws2_32.lib','bcrypt.lib'],check=True)
with executable.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
(output/'master-production.json').write_text(json.dumps(dict(schema=1,commit=os.environ['GITHUB_SHA'],
    run=int(os.environ['GITHUB_RUN_ID']),attempt=int(os.environ['GITHUB_RUN_ATTEMPT']),executable=executable.name,
    sha256=digest,size=executable.stat().st_size,subsystem='windows',fixture_code_linked=False),indent=2)+'\n')
print('Production GUI master linked without fixture code:',digest)
