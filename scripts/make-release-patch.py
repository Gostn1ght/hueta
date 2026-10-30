"""Build a cumulative Lost Zone release patch from the overlay.

Everything under scripts/netcoop-overlay/<role> that changed since the role's
last shipped base commit goes into the patch:
  *.script (top level)       -> input/<role>/scripts -> 99_lz_patch_<v>[_server].db0
  sounds, textures, shaders  -> input/gamedata/...    (in both archives)
  configs/...                -> loose/<role>/configs  (copied loose over the game)
Usage:
  python scripts/make-release-patch.py --version 000009 --out J:\\LostZone_Work\\_work\\patch_000009
      [--client-base a0e8bb64f] [--server-base 13b0430bf] [--key ...\\keys\\secret.key]
The key is read by lzpack only; it is never printed or copied.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = "scripts/netcoop-overlay"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def changed(base, role):
    prefix = f"{OVERLAY}/{role}/"
    out = git("diff", "--name-status", f"{base}..HEAD", "--", prefix)
    files, deleted = [], []
    for line in out.splitlines():
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        if not path.startswith(prefix):
            continue
        (deleted if status.startswith("D") else files).append(path[len(prefix):])
    return files, deleted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--client-base", default="a0e8bb64f")
    ap.add_argument("--server-base", default="13b0430bf")
    ap.add_argument("--key", default=r"J:\LostZone_Work\Compressor\private\lzpack-v1.key")
    ap.add_argument("--lzpack", default=r"J:\LostZone_Work\Compressor\lzpack.py")
    a = ap.parse_args()
    clean=int(a.version)>=47
    out = Path(a.out)
    if out.exists():
        sys.exit(f"{out} exists; patch numbers are never reused")
    out.mkdir(parents=True)
    head = git("rev-parse", "HEAD").strip()
    summary = {"head": head, "client_base": a.client_base, "server_base": a.server_base, "version": a.version,
               "client": {}, "server": {}}
    for role, base in (("client", a.client_base), ("server", a.server_base)):
        files, deleted = changed(base, role)
        scripts, loose = [], []
        for rel in files:
            src = ROOT / OVERLAY / role / rel
            if "/" not in rel and rel.endswith(".script"):
                dst = out / "input" / role / "scripts" / rel
                scripts.append(rel)
            elif rel.startswith("configs/"):
                # Native config IO supports archived defaults since 000047.
                dst = out / ("input" if clean else "loose") / role / rel
                (scripts if clean else loose).append(rel)
            else:
                # Sounds, textures, shaders: inside the archive (the launcher
                # does not ship a gamedata folder).
                inner = rel[len("gamedata/"):] if rel.startswith("gamedata/") else rel
                dst = out / "input" / role / "assets" / inner if clean else out / "input" / "gamedata" / inner
                scripts.append(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        summary[role] = {"scripts": len(scripts), "loose": loose, "deleted": deleted}
        print(f"{role}: {len(scripts)} scripts, {len(loose)} loose files, {len(deleted)} deleted since {base}")
        for rel in deleted:
            print(f"  ! deleted in the overlay (remove by hand if shipped): {rel}")
    if any(summary[role]["scripts"] for role in ("client", "server")):
        builder=str(ROOT/'tools/lzpack/lzpack.py') if clean else a.lzpack
        subprocess.run([sys.executable, builder, "patch", "--key", a.key, "--input", str(out / "input"),
                        "--output", str(out / "archives"), "--version", a.version, "--role", "both"]+(['--layout','v2'] if clean else []), check=True)
    else:
        print("Loose-config/native-only update: no resource archive is needed")
    (out / "source.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"patch {a.version} from {head[:9]} in {out}")


if __name__ == "__main__":
    main()
