"""The Definitive Car Pack's cars (owner 2026-10-24, tools/import-dcp.py): every
dcp_* section has its model, the profile the model includes (client and
server: the server drives), seats on bones the model has, and a name; GAMMA's
old cars are out of both spawners and removed from worlds (netcoop_vehicles)."""
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "scripts/netcoop-overlay"
CLIENT, SERVER = OVERLAY / "client", OVERLAY / "server"


def sections(path):
    out, cur = {}, None
    for line in path.read_text(encoding="cp1251").splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^\[([^\]]+)\]", line)
        if m:
            cur = out.setdefault(m.group(1), {})
            continue
        m = re.match(r"^([$a-z_]+)\s*=\s*(.+)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip()
    return out


def userdata(data):
    pos = 0
    while pos + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, pos)
        if cid & 0x7fffffff == 17:
            return data[pos + 8:pos + 8 + size].split(b"\0")[0].decode("cp1251")
        pos += 8 + size
    return ""


cars = sections(CLIENT / "configs/mod_system_lz_dcp_vehicles.ltx")
assert (CLIENT / "configs/mod_system_lz_dcp_vehicles.ltx").read_bytes() == (SERVER / "configs/mod_system_lz_dcp_vehicles.ltx").read_bytes()
assert len(cars) >= 40, len(cars)
names = (CLIENT / "configs/text/rus/st_lz_dcp_vehicles.xml").read_text(encoding="cp1251")
for name, keys in cars.items():
    assert name.startswith("dcp_"), name
    model = CLIENT / "meshes" / keys["visual"].replace("\\", "/")
    data = model.read_bytes()
    include = re.search(r'#include\s+"([^"]+)"', userdata(data))
    assert include, (name, "no profile include")
    for side in (CLIENT, SERVER):
        assert (side / "configs" / include.group(1).replace("\\", "/")).is_file(), (name, side.name, include.group(1))
    for seat in keys["netcoop_seats"].split(","):
        bone = seat.strip().split(":")[0]
        assert re.match(r"^seat_", bone) and (bone.encode() + b"\0") in data, (name, bone)
    assert '<string id="%s">' % keys["inv_name"] in names, (name, keys["inv_name"])
old = re.search(r"OLD_CARS = \{(.*?)\}", (SERVER / "netcoop_vehicles.script").read_text(encoding="utf-8"), re.S).group(1)
old = re.findall(r"(veh_[a-z0-9_]+) = true", old)
assert len(old) == 17 and "veh_mi2_heli" not in old and "veh_mi24_heli" not in old
for side in (CLIENT, SERVER):
    black = (side / "configs/plugins/spawner_blacklist.ltx").read_text(encoding="cp1251")
    ignore = black.split("[ignore_sections]", 1)[1]
    for car in old:
        assert re.search(r"^" + car + r"\s*$", ignore, re.M), (side.name, car)
# DCP lights (owner 2026-10-25: spawning a car crashed every client on
# [f1o] without spot_angle): point lights have no cone, texture or glow.
lights = (Path(__file__).resolve().parents[1] / "src/xrGame/CarLights.cpp").read_text(encoding="utf-8")
for need in ('if (spot) light_render->set_cone(', 'ini->line_exist(section, "spot_texture")',
             'ini->line_exist(section, "glow_texture")', 'READ_IF_EXISTS(ini, r_s32, section, "type"',
             'READ_IF_EXISTS(ini, r_string, "lights", "headlights", "")'):
    assert need in lights, need
print("PASS DCP: %d cars with models, profiles on client and server, seat bones and names; %d old cars cut" % (len(cars), len(old)))
