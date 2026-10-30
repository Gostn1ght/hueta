"""The Definitive Car Pack's cars (owner 2026-10-24, tools/import-dcp.py): every
dcp_* section has its model, the profile the model includes (client and
server: the server drives), seats on bones the model has, and a name; GAMMA's
old cars are out of both spawners and removed from worlds (netcoop_vehicles)."""
import re
import json
import struct
import math
import importlib.util
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


def model_physics(data):
    chunks, pos = {}, 0
    while pos < len(data):
        cid, size = struct.unpack_from('<II', data, pos)
        assert not cid & 0x80000000 and pos + 8 + size <= len(data)
        chunks[cid] = data[pos + 8:pos + 8 + size]
        pos += 8 + size
    names, pos, raw = [], 4, chunks[13]
    for _ in range(struct.unpack_from('<I', raw)[0]):
        end = raw.index(0, pos)
        name, pos = raw[pos:end].decode('cp1251'), end + 1
        end = raw.index(0, pos)
        parent, pos = raw[pos:end].decode('cp1251'), end + 1 + 60
        names.append((name, parent))
    assert pos == len(raw) and len(names) <= 64
    raw, pos, bones = chunks[16], 0, {}
    for name, parent in names:
        version = struct.unpack_from('<I', raw, pos)[0]
        pos = raw.index(0, pos + 4) + 1
        shape, flags = struct.unpack_from('<HH', raw, pos)
        geometry = struct.unpack_from('<27f', raw, pos + 4)
        pos += 112  # packed SBoneShape, identical to the runtime loader
        joint = struct.unpack_from('<I', raw, pos)[0]
        limits = struct.unpack_from('<12f', raw, pos + 4)
        pos += 72 + (4 if version else 0)
        bind_mass = struct.unpack_from('<10f', raw, pos)
        pos += 40
        assert name not in bones and all(math.isfinite(v) for v in bind_mass)
        assert shape in range(4) and joint in range(6)
        if shape and not flags & 4:
            assert bind_mass[6] > 0, (name, 'nonpositive physical mass')
            sizes = {1: geometry[12:15], 2: geometry[18:19], 3: geometry[25:27]}[shape]
            assert all(math.isfinite(v) and v > 0 for v in sizes), (name, 'invalid collision shape', sizes)
        bones[name] = dict(parent=parent, shape=shape if not flags & 4 else 0, joint=joint, limits=limits)
    assert pos == len(raw)
    assert sum(not b['parent'] for b in bones.values()) == 1
    for name, bone in bones.items():
        seen = {name}
        parent = bone['parent']
        while parent:
            assert parent in bones and parent not in seen, (name, parent)
            seen.add(parent)
            parent = bones[parent]['parent']
    return bones


spec = importlib.util.spec_from_file_location('dcp_import', ROOT / 'tools/import-dcp.py')
dcp_import = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dcp_import)


def profile_text(path):
    text = path.read_text(encoding='cp1251')
    return re.sub(r'^\s*#include\s+"([^"]+)"',
                  lambda m: profile_text(path.parent / m.group(1).replace('\\', '/')), text, flags=re.M)


cars = sections(CLIENT / "configs/mod_system_lz_dcp_vehicles.ltx")
particle_catalog = json.loads((ROOT / 'scripts/fixtures/gamma-particle-names.json').read_text(encoding='utf-8'))
particle_names = set(particle_catalog['names'])
assert len(particle_names) > 2000 and re.fullmatch('[0-9a-f]{64}', particle_catalog['sha256'])
old_particle = b'vehiclefx\\exhausts\\exhaust_kamaz'
new_particle = b'vehiclefx\\exhaust_kamaz'
assert dcp_import.adapt_particle_paths(b'physics unchanged\nexhaust_particles = ' + old_particle) == b'physics unchanged\nexhaust_particles = ' + new_particle
assert new_particle.decode() in particle_names and old_particle.decode() not in particle_names
for side in (CLIENT, SERVER):
    for path in (side / 'configs/models/vehicles').rglob('*.ltx'):
        profile = dcp_import.sections(profile_text(path))
        for section, keys in profile.items():
            for key, value in keys.items():
                if 'particle' in key and key.endswith(('particles', 'particles1', 'particles2')) and value:
                    assert value in particle_names, (side.name, path.name, section, key, 'missing particle', value)
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
    bones = model_physics(data)
    profile = dcp_import.sections(profile_text(CLIENT / 'configs' / include.group(1).replace('\\', '/')))
    definition = profile['car_definition']
    for field in ('reference_radius', 'fuel_tank', 'max_engine_rpm', 'idling_engine_rpm', 'main_gear_ratio'):
        if field in definition:
            value = float(definition[field])
            assert math.isfinite(value) and value > 0, (name, field, definition[field])
    for field in ('driving_wheels', 'steering_wheels', 'breaking_wheels', 'doors', 'exhausts', 'driver_place', 'steer'):
        for bone_name in filter(None, map(str.strip, definition.get(field, '').split(','))):
            assert bone_name in bones, (name, field, bone_name)
            bone = bones[bone_name]
            if field.endswith('_wheels'):
                assert bone['shape'] and bone['joint'] == 3, (name, field, bone_name, 'no physical wheel joint')
            if field == 'doors' and bone['shape'] and bone['joint'] != 0:
                assert bone['joint'] == 2, (name, bone_name, 'not a door hinge')
                axes = sum(abs(bone['limits'][i] - bone['limits'][i+1]) > 0.0001 for i in (0, 4, 8))
                assert axes == 1, (name, bone_name, 'hinge axes', axes)
    for seat in keys["netcoop_seats"].split(","):
        bone = seat.strip().split(":")[0]
        assert re.match(r"^seat_", bone) and (bone.encode() + b"\0") in data, (name, bone)
    assert '<string id="%s">' % keys["inv_name"] in names, (name, keys["inv_name"])
car_source = (ROOT / 'src/xrGame/Car.cpp').read_text(encoding='utf-8')
assert 'm_steer_angle = m_steering_wheels.empty() ? 0.f :' in car_source
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
print("PASS DCP: %d complete models, physical shapes/masses, wheel and door joints, profile bone references, client/server configs and seat names; %d old cars cut" % (len(cars), len(old)))
