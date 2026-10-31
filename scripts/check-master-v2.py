"""CI executable fixtures: bootstrap, WAL migration, native controller/world store.

Never starts a game/location process. The controller fixture has no game exe.
"""
from pathlib import Path
import json
import os
import sqlite3
import shutil
import subprocess
import sys
import tempfile
from contextlib import closing

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
exe = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='lz native v2 ') as temporary:
    root = Path(temporary)
    for mode in ('storage', 'host'):
        subprocess.run([str(exe), mode + '-selftest', str(root / mode)], check=True, timeout=90)
    game = root / 'bootstrap'
    plan = game / 'appdata/server/netcoop_cluster.ltx'
    plan.parent.mkdir(parents=True)
    resources=game/'resources';resources.mkdir()
    archive_name='99_v2_000047_30_server_configs_000.db0'
    (resources/archive_name).write_bytes(b'inert old server archive')
    (resources/'99_v2_000047_30_client_configs_000.db0').write_bytes(b'inert client archive')
    (game / 'fsgame_server.template').write_text('$fs_root$ = false | false | {ROOT}\n$game_saves$ = true | false | {ROOT}appdata/server/savedgames/\n')
    plan.write_text('[cluster]\nentry_port=9446\nper_server=42\n[locations]\nk00_marsh=127.0.0.1:18001\n'
                    'l01_escape=127.0.0.1:18003\n[launch]\nl01_escape=custom_start\n[on_demand]\nl01_escape=1\n')
    legacy = game / 'hoster/master/runtime'
    legacy.mkdir(parents=True)
    config = legacy / 'config.json'
    subprocess.run([str(exe), 'init', '--config', str(config), '--location', 'k00_marsh',
                    '--world-id', '71', '--seed', '9'], check=True)
    original = json.loads(config.read_text())
    connection = sqlite3.connect(legacy / 'world.sqlite')
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA wal_autocheckpoint=0')
    connection.execute('CREATE TABLE migration_probe(value TEXT)')
    connection.execute('INSERT INTO migration_probe VALUES(?)', ('live WAL snapshot',))
    connection.commit()
    subprocess.run([str(exe), 'bootstrap', '--root', str(game)], check=True, timeout=30)
    assert not (resources/archive_name).exists()
    assert (resources/'server'/archive_name).read_bytes()==b'inert old server archive'
    assert (resources/'99_v2_000047_30_client_configs_000.db0').exists()
    # Overlay reinstall: an identical old root name is safely eliminated.
    (resources/archive_name).write_bytes(b'inert old server archive')
    subprocess.run([str(exe), 'bootstrap', '--root', str(game)], check=True, timeout=30)
    assert not (resources/archive_name).exists()
    # A different nested file must never be silently overwritten or deleted.
    (resources/archive_name).write_bytes(b'conflicting archive')
    conflict=subprocess.run([str(exe),'bootstrap','--root',str(game)],capture_output=True,timeout=30)
    assert conflict.returncode!=0 and (resources/archive_name).read_bytes()==b'conflicting archive'
    assert (resources/'server'/archive_name).read_bytes()==b'inert old server archive'
    (resources/archive_name).unlink() # inert test fixture only
    migrated = game / 'appdata/master/config.json'
    actual = json.loads(migrated.read_text())
    assert actual['world_id'] == 71 and actual['seed'] == 9
    assert actual['signing_key'] == original['signing_key']
    with closing(sqlite3.connect(migrated.parent / 'world.sqlite')) as copied:
        assert copied.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert copied.execute('SELECT value FROM migration_probe').fetchone()[0] == 'live WAL snapshot'
    assert config.exists() and (legacy / 'world.sqlite').exists()
    text = plan.read_text()
    assert 'k00_marsh = 127.0.0.1:18001' in text and 'l01_escape = 127.0.0.1:18003' in text
    assert 'l01_escape = custom_start' in text and 'entry_port = 9446' in text
    assert 'appdata\\master\\pending\\worlds\\' in (game / 'fsgame_server.ltx').read_text()
    assert 'l08_yantar = 127.0.0.1:1319' in text and 'l13u_warlab = 127.0.0.1:1359' in text
    assert len([c for c in actual['credentials'] if c.startswith('location:')]) == 33
    writer = game / 'appdata/server/netcoop_world_writer_l08_yantar.json'
    damaged = json.loads(writer.read_text())
    damaged['token'] = 'x' * 64
    writer.write_text(json.dumps(damaged))
    subprocess.run([str(exe), 'bootstrap', '--root', str(game)], check=True, timeout=30)
    assert json.loads(writer.read_text())['token'] == actual['credentials']['location:l08_yantar']['token']
    assert (plan.with_name(plan.name + '.before-native-completion.bak')).exists()
    migrated.unlink() # crash after DB installation, before config installation
    subprocess.run([str(exe), 'bootstrap', '--root', str(game)], check=True, timeout=30)
    assert json.loads(migrated.read_text())['world_id']==71
    with closing(sqlite3.connect(migrated.parent / 'world.sqlite')) as copied:
        assert copied.execute('SELECT value FROM migration_probe').fetchone()[0]=='live WAL snapshot'
    connection.close()
    relocated = root/'relocated'
    shutil.copytree(legacy,relocated/'appdata/master/legacy-runtime')
    shutil.copy2(game/'fsgame_server.template',relocated/'fsgame_server.template')
    subprocess.run([str(exe),'bootstrap','--root',str(relocated)],check=True,timeout=30)
    assert json.loads((relocated/'appdata/master/config.json').read_text())['world_id']==71
    assert not (relocated/'hoster').exists()
print('PASS actual native bootstrap: all 33 ports, custom settings retained, stale credentials repaired, consistent live-WAL migration, idempotent rerun; no game started')
print('PASS actual native archive migration: root server overrides relocated, identical overlay duplicate removed, conflicting files both retained, client archive untouched; no game started')
