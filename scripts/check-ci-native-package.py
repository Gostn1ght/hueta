"""Check release packaging with inert bytes, without compiling/loading binaries."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_package',root/'scripts/publish-ci-native.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
commit='0123456789abcdef0123456789abcdef01234567'
with TemporaryDirectory() as temporary:
    folder=Path(temporary)
    source=folder/'input'
    for role in ('bin','dedicated'):
        (source/role).mkdir(parents=True)
        (source/role/('LostZoneClientDX11.exe' if role=='bin' else 'LostZoneServerDX11.exe')).write_bytes(b'inert-test-bytes')
        (source/role/'runtime.dll').write_bytes(b'inert-dll')
    (source/'dedicated/sqlite3.dll').write_bytes(b'inert-sqlite')
    (source/'bin/LostZoneClientDX11.pdb').write_bytes(b'inert-symbols')
    (source/'built-from.txt').write_text(commit+'\n')
    (source/'notices').mkdir()
    (source/'notices/LICENSE.txt').write_text('Test license')
    (source/'private').mkdir()
    (source/'private/secret.key').write_text('MUST NEVER BE PACKAGED')
    out=folder/'output'
    metadata=module.package(source,out,commit,17,2)
    assert metadata['run']==17 and metadata['attempt']==2
    with zipfile.ZipFile(out/metadata['runtime']['name']) as packed:
        rows=json.loads(packed.read('native-files.json'))
        assert rows['commit']==commit and len(rows['files'])==7
        assert 'private/secret.key' not in packed.namelist()
        assert not any(name.endswith('.pdb') for name in packed.namelist())
    with zipfile.ZipFile(out/metadata['symbols']['name']) as packed:
        assert packed.namelist()==['LostZoneDX11.pdb','built-from.txt']
    for wrong in ('invalid','f'*40):
        try:
            module.package(source,folder/'bad',wrong,17,2)
        except ValueError:
            pass
        else:
            raise AssertionError('Wrong CI identity accepted')
    (source/'dedicated/LostZoneServerDX11.exe').write_bytes(b'wrong server')
    try:
        module.package(source,folder/'mismatch',commit,17,2)
    except ValueError:
        pass
    else:
        raise AssertionError('Mismatched native files accepted')
print('PASS native CI packaging: pinned identity, runtime hashes, separate symbols, licenses, excluded private data and rejected mismatch')
