"""Actual canonical packager refuses a root patch hidden by an older role archive."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib,json,subprocess,sys

root=Path(__file__).resolve().parents[1]
with TemporaryDirectory(prefix='lz-server-precedence-') as temporary:
    work=Path(temporary).resolve();source=work/'source'
    files={
        'dedicated/LostZoneMaster.exe':b'master fixture, never executed',
        'dedicated/LostZoneServerDX11.exe':b'location fixture, never executed',
        'dedicated/sqlite3.dll':b'dependency fixture',
        'Start Lost Zone Master.cmd':b'@echo off\r\n',
        'runtime-layout.json':b'{"schema":2,"role":"server"}',
        'resources/server/99_v2_000047_40_server_scripts_000.db0':b'old role script fixture',
        'resources/99_v2_000048_40_server_scripts_000.db0':b'new role script fixture',
    }
    for name,data in files.items():
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    def manifest():
        rows=[dict(path=p.relative_to(source).as_posix(),size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
              for p in sorted(source.rglob('*')) if p.is_file() and p.name!='server-release.json']
        metadata=dict(schema=2,compatible_client_release='test',files=rows,
                      master_executable_sha256=hashlib.sha256(files['dedicated/LostZoneMaster.exe']).hexdigest())
        (source/'server-release.json').write_text(json.dumps(metadata),encoding='utf8')
    def package(output):
        return subprocess.run([sys.executable,str(root/'scripts/dist/make_standalone_server.py'),
            '--clean-runtime',str(source),'--version','test','--out',str(output)],capture_output=True,text=True)
    manifest();bad=package(work/'bad')
    assert bad.returncode and 'Server role archive must be in resources/server' in bad.stderr
    assert not (work/'bad').exists(),'rejected namespace must not partially package a server'
    name='99_v2_000048_40_server_scripts_000.db0'
    (source/'resources'/name).rename(source/'resources/server'/name)
    manifest();good=package(work/'good');assert good.returncode==0,good.stderr
    assert (work/'good/resources/server'/name).read_bytes()==files['resources/'+name]
    assert not (work/'good/resources'/name).exists()
print('PASS actual server packager: older nested role patch cannot shadow a newer root patch; canonical role directory accepted; no native process started')
