"""Exercise the canonical server builder with inert bytes; no native process."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
root=Path(__file__).resolve().parents[1]
builder=root/'scripts/dist/make_standalone_server.py'
with tempfile.TemporaryDirectory(prefix='lz clean server builder ') as temporary:
    work=Path(temporary);source=work/'candidate'
    data={'dedicated/LostZoneMaster.exe':b'inert native bytes','dedicated/LostZoneServerDX11.exe':b'inert native bytes',
        'dedicated/sqlite3.dll':b'inert library','Start Lost Zone Master.cmd':b'inert start',
        'runtime-layout.json':b'{"schema":2}','resources/99_v2_000047_40_server_scripts_000.db0':b'inert archive'}
    for name,payload in data.items():
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
    def metadata():
        (source/'server-release.json').write_text(json.dumps(dict(schema=2,compatible_client_release='fixture',files=[
            dict(path=name,size=len(payload),sha256=hashlib.sha256(payload).hexdigest()) for name,payload in data.items()])))
    def run(output,valid):
        result=subprocess.run([sys.executable,str(builder),'--clean-runtime',str(source),'--version','fixture','--out',str(output)],capture_output=True)
        assert (result.returncode==0)==valid,result.stderr.decode(errors='replace')
    metadata();run(work/'copy',True)
    assert {p.relative_to(work/'copy').as_posix() for p in (work/'copy').rglob('*') if p.is_file()}==set(data)|{'server-release.json'}
    for name,payload in data.items():assert (work/'copy'/name).read_bytes()==payload
    (source/'dedicated/sqlite3.dll').unlink();run(work/'missing',False)
    (source/'dedicated/sqlite3.dll').write_bytes(data['dedicated/sqlite3.dll'])
    (source/'extra.txt').write_bytes(b'unreviewed');run(work/'unreviewed',False);(source/'extra.txt').unlink()
    (source/'appdata').mkdir();run(work/'private-folder',False);(source/'appdata').rmdir()
    data['dedicated/private.key']=b'private';(source/'dedicated/private.key').write_bytes(b'private');metadata();run(work/'private-key',False)
print('PASS canonical builder: exact reviewed file list, native alias, missing/tampered/unreviewed/private inputs rejected; no game or master launched')
