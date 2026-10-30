"""Import the Definitive Car Pack's vehicles into the overlay (owner
2026-10-24: "the Definitive pack, cut all the old cars"), from the folder
tools/extract-dcp.py made.

- Every drivable vehicle_* section of the pack (not the broken, dead or
  burnt ones) becomes dcp_<name>:m_car in configs/mod_system_lz_dcp_vehicles.ltx
  (client and server): its model, its name, the seats from the model's seat
  bones (driver first: the profile's driver_place), a trunk when it has one.
- The models (meshes\\physics\\vehicles), the profiles they include
  (configs\\models\\vehicles), the car sounds and the textures go to the
  client overlay; textures larger than 2048 (bump maps: 1024) are scaled
  down with their mip maps to keep the download in bounds.
- The pack's Russian and English names: configs/text/<lang>/st_lz_dcp_vehicles.xml.
- GAMMA's old cars (veh_* of vehicles.ltx; the helicopters stay) leave the
  spawner (plugins/spawner_blacklist.ltx); netcoop_vehicles removes old
  cars standing in a world.

usage: import-dcp.py <DCP gamedata> <overlay folder> <GAMMA client configs>
"""
import concurrent.futures
import re
import shutil
import struct
import sys
from pathlib import Path

SKIP = re.compile(r"_(broken|dead|blown|nogun)$")
OLD_CARS = ("veh_niva", "veh_uaz_01", "veh_uaz_02", "veh_uaz_buhanka", "veh_zaz", "veh_zaz_968", "veh_moskvich", "veh_tr13",
            "veh_zil_130", "veh_zil_131", "veh_kamaz_fura", "veh_kamaz", "veh_laz", "veh_kavz", "veh_gaz", "veh_btr",
            "veh_hl2baggi")
DIFFUSE_CAP, BUMP_CAP = 2048, 1024


def sections(text):
    out, parents, cur = {}, {}, None
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^\[([^\]]+)\]\s*(?::\s*(.+))?$", line)
        if m:
            cur = m.group(1).strip()
            out.setdefault(cur, {})
            if m.group(2):
                parents[cur] = [p.strip() for p in m.group(2).split(",")]
            continue
        m = re.match(r"^([$A-Za-z_0-9]+)\s*=\s*(.*)$", line)
        if m and cur:
            out[cur][m.group(1)] = m.group(2).strip()

    def resolved(name, seen=()):
        keys = {}
        for p in parents.get(name, []):
            if p in out and p not in seen:
                keys.update(resolved(p, seen + (name,)))
        keys.update(out.get(name, {}))
        return keys
    return {name: resolved(name) for name in out}


def userdata(path):
    data = path.read_bytes()
    pos = 0
    while pos + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, pos)
        if cid & 0x7fffffff == 17:
            return data[pos + 8:pos + 8 + size].split(b"\0")[0].decode("cp1251", "replace")
        pos += 8 + size
    return ""


def model_bones(path):
    data = path.read_bytes()
    found = []
    for name in re.findall(rb"(seat[a-z0-9_]*|[a-z_]*back[a-z_]*door[a-z0-9_]*|[a-z_]*door[a-z_]*back[a-z0-9_]*)\x00", data):
        found.append(name.decode())
    return found


def seats_for(dcp, visual, profile):
    names = model_bones(dcp / "meshes" / visual.replace("\\", "/"))
    # seat_left / seat_right / seat_back... are places; "seat", "seats" are the seats' meshes
    seats = sorted({n for n in names if re.match(r"^seat_(left|right|back|rear|middle)[a-z0-9_]*$", n)})
    driver = profile.get("car_definition", {}).get("driver_place", "seat_left").strip()
    if driver not in seats:
        seats.insert(0, driver)
    ordered = [driver] + [s for s in seats if s != driver]
    rear = any("back" in n and "door" in n for n in names)
    if rear and len(ordered) == 2:
        ordered += [ordered[0] + ":0:0:-0.85", ordered[1] + ":0:0:-0.85"]
    if len(ordered) == 1:
        ordered.append(ordered[0] + ":0.6:0:0")  # one seat bone: the passenger beside the driver
    return ordered[:8]


def scale_texture(job):
    src, dst, cap = job
    data = src.read_bytes()
    if data[:4] != b"DDS " or len(data) < 128:
        dst.write_bytes(data)
        return 0
    h, w = struct.unpack_from("<II", data, 12)
    four = data[84:88]
    if max(w, h) <= cap or four not in (b"DXT1", b"DXT5"):
        dst.write_bytes(data)
        return 0
    from PIL import Image
    import etcpak
    img = Image.open(src).convert("RGBA")
    k = max(w, h) / cap
    img = img.resize((max(4, int(w / k)), max(4, int(h / k))), Image.LANCZOS)
    chain = [img]
    while min(chain[-1].size) > 4:
        cw, ch = chain[-1].size
        chain.append(chain[-1].resize((max(4, cw // 2), max(4, ch // 2)), Image.LANCZOS))
    compress = etcpak.compress_bc1 if four == b"DXT1" else etcpak.compress_bc3
    body = b"".join(compress(m.tobytes(), m.size[0], m.size[1]) for m in chain)
    W, H = img.size
    linear = len(compress(img.tobytes(), W, H))
    header = struct.pack("<4sIIIIIII44s", b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000, H, W, linear, 0,
                         len(chain), b"\0" * 44)
    header += struct.pack("<II4sIIIII", 32, 0x4, four, 0, 0, 0, 0, 0) + struct.pack("<IIIII", 0x1000 | 0x8 | 0x400000, 0, 0, 0, 0)
    dst.write_bytes(header + body)
    return 1


def strings(dcp, lang):
    path = dcp / "configs/text" / lang / "string_table_enc_vehicles.xml"
    text = path.read_text(encoding="cp1251", errors="replace") if path.is_file() else ""
    return dict(re.findall(r'<string id="([^"]+)">\s*<text>(.*?)</text>', text, re.S))


def adapt_particle_paths(data):
    # Lost Alpha DCP adds an "exhausts" folder absent from GAMMA's library.
    # The same KamAZ effect already exists in the installed particles.xr.
    return data.replace(b'vehiclefx\\exhausts\\exhaust_kamaz', b'vehiclefx\\exhaust_kamaz')


def main(dcp, overlay, gamma):
    dcp, overlay, gamma = Path(dcp), Path(overlay), Path(gamma)
    client = overlay / "client"
    vehicles = sections((dcp / "configs/items/vehicles.ltx").read_text(encoding="cp1251", errors="replace"))
    lines = ["; The Definitive Car Pack's vehicles (owner 2026-10-24), by tools/import-dcp.py.",
             "; Seats from the models' seat bones (netcoop_vehicles.inc), the driver first.", ""]
    names_needed, kept = set(), []
    for name, keys in sorted(vehicles.items()):
        if not name.startswith("vehicle_") or SKIP.search(name) or "visual" not in keys:
            continue
        visual = keys["visual"].replace(".ogf", "")
        model = dcp / "meshes" / (visual.replace("\\", "/") + ".ogf")
        if not model.is_file():
            print("   no model for", name, visual)
            continue
        include = re.search(r'#include\s+"([^"]+)"', userdata(model))
        profile_path = dcp / "configs" / include.group(1).replace("\\", "/") if include else None
        if not (profile_path and profile_path.is_file()):
            print("   no profile for", name)
            continue
        profile = sections(profile_path.read_text(encoding="cp1251", errors="replace"))
        section = "dcp_" + name[len("vehicle_"):]
        seats = seats_for(dcp, visual + ".ogf", profile)
        lines += ["[%s]:m_car" % section, '$spawn = "vehicles\\%s"' % section, "visual = " + visual + ".ogf"]
        if keys.get("inv_name"):
            lines += ["inv_name = " + keys["inv_name"], "inv_name_short = " + keys["inv_name"]]
            names_needed.add(keys["inv_name"])
        lines.append("netcoop_seats = " + ", ".join(seats))
        if keys.get("has_trunk", "true").lower() == "false":
            lines.append("netcoop_trunk = false")
        lines.append("")
        kept.append(section)
    for side in ("client", "server"):
        (overlay / side / "configs/mod_system_lz_dcp_vehicles.ltx").write_text("\n".join(lines), encoding="cp1251", newline="\r\n")
    for lang in ("rus", "eng"):
        table = strings(dcp, lang)
        out = ['<?xml version="1.0" encoding="windows-1251"?>', "<string_table>"]
        for sid in sorted(names_needed):
            # a name the pack lacks: its id without "_name"
            text = table[sid].strip() if sid in table else (sid[:-5] if sid.endswith("_name") else sid).upper()
            out += ['\t<string id="%s">' % sid, "\t\t<text>%s</text>" % text, "\t</string>"]
        out.append("</string_table>")
        dst = client / "configs/text" / lang / "st_lz_dcp_vehicles.xml"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("\n".join(out) + "\n", encoding="cp1251", errors="replace", newline="\r\n")
    print("DCP vehicles:", len(kept))

    # assets: models, profiles, sounds as they are; textures scaled
    # the server drives the cars: it reads the profiles the models include too
    for folder, sides in (("meshes/physics/vehicles", ("client",)), ("configs/models/vehicles", ("client", "server")),
                          ("sounds/car", ("client",))):
        src = dcp / folder
        for side in sides:
            dst = overlay / side / folder
            for f in src.rglob("*"):
                if f.is_file():
                    target = dst / f.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if folder == "configs/models/vehicles":
                        target.write_bytes(adapt_particle_paths(f.read_bytes()))
                    else:
                        shutil.copyfile(f, target)
    jobs = []
    for f in (dcp / "textures").rglob("*"):
        if not f.is_file():
            continue
        target = client / "textures" / f.relative_to(dcp / "textures")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.stat().st_mtime >= f.stat().st_mtime:
            continue  # done by an earlier run
        jobs.append((f, target, BUMP_CAP if "_bump" in f.name else DIFFUSE_CAP))
    with concurrent.futures.ProcessPoolExecutor() as pool:
        scaled = sum(pool.map(scale_texture, jobs, chunksize=8))
    print("textures:", len(jobs), "copied,", scaled, "scaled down")

    # the old cars leave the spawner
    black = (gamma / "plugins/spawner_blacklist.ltx").read_text(encoding="cp1251", errors="replace")
    head, sep, rest = black.partition("[ignore_sections]")
    assert sep, "spawner blacklist has no [ignore_sections]"
    added = "\n".join(c for c in OLD_CARS if not re.search(r"^" + c + r"\s*$", rest, re.M))
    text = head + sep + "\n; GAMMA's old cars (owner 2026-10-24: the Definitive Car Pack instead)\n" + added + rest
    for side in ("client", "server"):
        dst = overlay / side / "configs/plugins/spawner_blacklist.ltx"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="cp1251", errors="replace", newline="\r\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
