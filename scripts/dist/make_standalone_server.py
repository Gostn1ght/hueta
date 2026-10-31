"""Clean native server: --clean-runtime <reviewed-server> --version ... --out ...

The legacy recipe below now requires --legacy-layout explicitly. It cannot
silently reintroduce client/bin/hoster trees into a new release.

One self-contained server folder (owner 2026-10-12: "one folder with the
dedicated and everything; I send it as an archive to the hoster").

    python make_standalone_server.py --game "J:\\LostZone\\Lost Zone" --previous "J:\\LostZone_Work\\Lost Zone Server"
        --dedicated <CI artifact>\\dedicated --python <Python 3.13 install> --version "..." --out <folder>

* resources: every game archive except textures (the UI ones stay: fonts) and
  music, plus the server archives (95_server_*, 99_*_server) of --previous;
  hard links on the same drive, copies otherwise;
* dedicated: the CI build (no .pdb);
* server: the loose server configs/scripts of --previous;
* hoster: the panel, watchdog, master control, plans and the portable master;
* top level: the start scripts, fsgame_server.template and README.txt.
No appdata and no master runtime: worlds, accounts and keys stay on the
hoster's PC.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKIP = ("90_lostzone_lz_textures", "50_textures_", "40_sounds_sounds_music")
KEEP = ("50_textures_textures_ui",)


def link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--clean-runtime",type=Path,help="Verified schema-2 dedicated-only server candidate (000047 and newer)")
    p.add_argument("--legacy-layout",action='store_true',help="Explicitly reproduce the retired pre-000047 layout")
    p.add_argument("--game")
    p.add_argument("--previous")
    p.add_argument("--dedicated")
    p.add_argument("--python")
    p.add_argument("--version", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    if a.clean_runtime:
        source,out=a.clean_runtime.resolve(),Path(a.out).resolve()
        if out.exists() or out==source or out.is_relative_to(source):p.error('Use a new output outside the source candidate')
        metadata=json.loads((source/'server-release.json').read_text(encoding='utf-8'))
        if metadata.get('schema')!=2 or metadata.get('compatible_client_release')!=a.version:p.error('Wrong canonical release metadata/version')
        if any((source/name).exists() for name in ('client','server','bin','hoster','notices','appdata')):p.error('Not a canonical public server')
        listed={row['path']:row for row in metadata['files']}
        listed['server-release.json']={'size':(source/'server-release.json').stat().st_size}
        required={'dedicated/LostZoneMaster.exe','dedicated/LostZoneServerDX11.exe','dedicated/sqlite3.dll',
            'Start Lost Zone Master.cmd','runtime-layout.json'}
        if not required.issubset(listed):p.error('Incomplete canonical native master package')
        expected_master=metadata.get('master_executable_sha256',listed['dedicated/LostZoneServerDX11.exe']['sha256'])
        if listed['dedicated/LostZoneMaster.exe']['sha256']!=expected_master:p.error('Master is not the reviewed native executable')
        actual={path.relative_to(source).as_posix():path for path in source.rglob('*') if path.is_file()}
        if set(listed)!=set(actual):p.error('Canonical file list differs from reviewed metadata')
        for relative,path in actual.items():
            if path.is_symlink() or not path.resolve().is_relative_to(source):p.error('Linked/private source path')
            low=relative.lower()
            if low.endswith(('.key','.secret','.sqlite','.sqlite-wal','.sqlite-shm','.pdb','.log')) or '/private/' in low:p.error('Private file in canonical source')
            if low.startswith('resources/') and ('_client_' in low or low.startswith('resources/90_lostzone_lz_scripts')):p.error('Client resource in server source')
            if path.stat().st_size!=listed[relative]['size']:p.error('File size differs: '+relative)
            if 'sha256' in listed[relative]:
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=listed[relative]['sha256']:p.error('File digest differs: '+relative)
        for relative,path in actual.items():
            destination=out/relative;destination.parent.mkdir(parents=True,exist_ok=True);link_or_copy(path,destination)
        print('Verified canonical standalone server:',out,'files:',len(actual))
        return
    if not a.legacy_layout:p.error('Use --clean-runtime for the native layout; the old builder requires --legacy-layout explicitly')
    if not all((a.game,a.previous,a.dedicated,a.python)):p.error('Legacy layout requires --game, --previous, --dedicated and --python')
    game, prev, out = Path(a.game), Path(a.previous), Path(a.out)
    if out.exists():
        sys.exit(f"{out} exists; remove it first")
    (out / "resources").mkdir(parents=True)
    size = 0
    for f in sorted((game / "resources").iterdir()):
        if f.name.startswith(SKIP) and not f.name.startswith(KEEP):
            continue
        link_or_copy(f, out / "resources" / f.name)
        size += f.stat().st_size
    for f in sorted((prev / "resources").iterdir()):
        if (f.name.startswith("95_server_") or f.name.endswith("_server.db0")) and not (out / "resources" / f.name).exists():
            link_or_copy(f, out / "resources" / f.name)
            size += f.stat().st_size
    shutil.copytree(a.dedicated, out / "dedicated", ignore=shutil.ignore_patterns("*.pdb"))
    shutil.copytree(prev / "server", out / "server")
    hoster = out / "hoster"
    hoster.mkdir()
    for f in (REPO / "scripts" / "netcoop-cluster").iterdir():
        if f.suffix == ".ps1" or f.name in ("netcoop_cluster.ltx.six", "netcoop_cluster.ltx.full"):
            shutil.copy2(f, hoster / f.name)
    subprocess.run([sys.executable, str(HERE / "make_master_runtime.py"), "--python", a.python,
                    "--out", str(hoster / "master")], check=True)
    for name in ("Start Server Panel.cmd", "Start Locations.cmd", "Start Master.cmd", "Admin Rights.cmd", "fsgame_server.template"):
        shutil.copy2(HERE / name, out / name)
    readme = (HERE / "README-server.txt").read_text(encoding="utf-8").replace("{VERSION}", a.version)
    (out / "README.txt").write_bytes(b"\xef\xbb\xbf" + readme.replace("\n", "\r\n").encode("utf-8"))
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"standalone server: {out} ({total / 2**30:.1f} GiB, resources {size / 2**30:.1f} GiB)")


if __name__ == "__main__":
    main()
