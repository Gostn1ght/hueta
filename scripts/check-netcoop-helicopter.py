"""Flyable Mi-2 (doc 137): the shipped model, its car profile and the item
section agree with each other and with what Car.cpp reads.

- veh_mi2_pilot.ogf's userdata includes the shipped profile;
- every bone the seats and the profile name exists in the model;
- the profile has every key CCar::ParseDefinitions reads without a default;
- every heli_* key of the section is one netcoop_heli_load reads;
- client and server configs are byte-identical;
- the model carries the "idle" motion the rotors turn with.
"""
import re
import math
import struct
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "scripts/netcoop-overlay"
OGF = OVERLAY / "client/meshes/dynamics/vehicles/mi2/veh_mi2_pilot.ogf"


def chunks(data):
    pos, out = 0, {}
    while pos + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, pos)
        out[cid & 0x7fffffff] = data[pos + 8:pos + 8 + size]
        pos += 8 + size
    assert pos == len(data)
    return out


def ini(text):
    sections, current = {}, None
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"!?\[([^\]]+)\]", line)
        if m:
            current = sections.setdefault(m.group(1), {})
            continue
        key, _, value = line.partition("=")
        current[key.strip()] = value.strip()
    return sections


car = (ROOT / "src/xrGame/Car.cpp").read_text(encoding="utf-8", errors="replace") + (ROOT / "src/xrGame/CarHelicopter.cpp").read_text(encoding="utf-8", errors="replace")
parse = car[car.index("void CCar::ParseDefinitions()"):car.index("void CCar::CreateSkeleton(")]
parse = re.sub(r"#else.*?#endif", "", parse, flags=re.S)  # CAR_NEW is defined: optional wheels
init = car[car.index("void CCar::Init()"):car.index("void CCar::Revert()")]
required = set(re.findall(r'ini->r_\w+\("car_definition", "(\w+)"\)', parse + init))
required -= set(re.findall(r'line_exist\("car_definition", "(\w+)"\)', parse + init))
load = car[car.index("void CCar::netcoop_heli_load()"):car.index("void CCar::netcoop_heli_rotors()")]
read = set(re.findall(r'"(heli_\w+)"', load))
inc = ''.join((ROOT / f'src/xrGame/{n}').read_text(encoding='utf-8-sig') for n in ('netcoop_vehicles.inc', 'netcoop_vehicle_server.inc', 'netcoop_vehicle_client.inc', 'netcoop_vehicle_seat.inc'))
items = ini((OVERLAY / "client/configs/mod_system_zzzzzzzz_netcoop_helicopters.ltx").read_text(encoding="ascii"))
name = "configs/mod_system_zzzzzzzz_netcoop_helicopters.ltx"
assert (OVERLAY / "client" / name).read_bytes() == (OVERLAY / "server" / name).read_bytes(), name

# Mi-2 (doc 137) and the owner's Mi-24 (doc 141).
HELICOPTERS = {"veh_mi2_heli": ("mi2", "veh_mi2_pilot"), "veh_mi24_heli": ("mi24_lz", "veh_mi24_pilot")}
report = []
for section, (folder, model_name) in HELICOPTERS.items():
    ogf = OVERLAY / f"client/meshes/dynamics/vehicles/{folder}/{model_name}.ogf"
    model = chunks(ogf.read_bytes())
    userdata = model[17].rstrip(b"\0").decode("ascii")
    assert userdata == '#include "models\\vehicles\\' + model_name + '.ltx"', userdata
    body = model[13]
    count, = struct.unpack_from("<I", body, 0)
    pos, bones, bone_order = 4, set(), []
    for _ in range(count):
        z = body.index(b"\0", pos); name=body[pos:z].decode();bones.add(name);bone_order.append(name);pos = z + 1
        z = body.index(b"\0", pos); pos = z + 1 + 60
    assert b"idle" in model[15], "the rotor motion"
    if section=='veh_mi24_heli':
        assert {'gear_left','gear_right','gear_nose'}<=bones and len(bones)<=64
        properties={};boxes={};at=0;raw=model[16]
        for name in bone_order:
            version,=struct.unpack_from('<I',raw,at);at=raw.index(0,at+4)+1
            shape,flags=struct.unpack_from('<HH',raw,at);joint,=struct.unpack_from('<I',raw,at+112)
            if shape==1:boxes[name]=struct.unpack_from('<15f',raw,at+4)
            properties[name]=(shape,flags,joint);at+=112+72+(4 if version else 0)+40
        assert at==len(raw)
        for name in ('gear_left','gear_right','gear_nose'):
            shape,flags,joint=properties[name]
            assert shape==1 and not flags&4 and joint==0,(name,properties[name])
        windows=[n for n in bones if n.startswith('glass_')];assert len(windows)==8
        assert all(properties[n][0]==1 and properties[n][1]&4 for n in windows)
        # CCF_Skeleton ray-picks physics primitives, not the visible mesh.
        # The former full-height root box masked all cockpit/side glass.
        assert abs(boxes['root'][13]-.5)<1e-5
        assert abs(boxes['korpus1'][12]-.8)<1e-5 and properties['korpus1'][2]==0
        qa=json.loads((ROOT/'docs/audit/167_MI24_COLLISION_QA.json').read_text())
        assert qa['ogf_sha256']==hashlib.sha256(ogf.read_bytes()).hexdigest()
        assert set(qa['shapes'])==set(boxes) and len(qa['rays'])==8
        def ray_box(start,direction,box):
            near,far=0.,100.
            for i in range(3):
                if not direction[i]:
                    if not box['lo'][i]<=start[i]<=box['hi'][i]:return None
                else:
                    a=(box['lo'][i]-start[i])/direction[i];b=(box['hi'][i]-start[i])/direction[i]
                    near=max(near,min(a,b));far=min(far,max(a,b))
                    if near>far:return None
            return near
        assert {r['target'] for r in qa['rays']}==set(windows)
        for ray in qa['rays']:
            hits=[(distance,name) for name,box in qa['shapes'].items()
                  if (distance:=ray_box(ray['start'],ray['direction'],box)) is not None]
            distance,name=min(hits)
            assert name.startswith('glass_') and name==ray['first'] and abs(distance-ray['distance'])<1e-4
        triangles=0
        for data in chunks(model[9]).values():
            mesh=chunks(data);indices=mesh[4];count,=struct.unpack_from('<I',indices)
            vertex_count,=struct.unpack_from('<I',mesh[3],4)
            assert vertex_count<=65535 and len(indices)==4+count*2 and count%3==0
            assert max(struct.unpack_from('<'+'H'*count,indices,4))<vertex_count
            triangles+=count//3
        assert triangles>=163924,triangles
        assert b'models\\lz_heli_glass\0' in ogf.read_bytes()
    profile_name = f"configs/models/vehicles/{model_name}.ltx"
    client, server = (OVERLAY / "client" / profile_name).read_bytes(), (OVERLAY / "server" / profile_name).read_bytes()
    assert client == server and b"\x0b" not in client, f"{profile_name}: client and server differ"
    profile = ini(client.decode("ascii"))
    heli = items[section]
    missing = required - set(profile["car_definition"])
    assert not missing, f"{model_name} lacks {sorted(missing)}"
    assert {"R", "N1"} <= set(profile["transmission_gear_ratio"])
    for part in ("explosion", "damage_bones", "immunities", "car_sound", "damage_particles"):
        assert part in profile, part
    assert profile["car_definition"]["damage"] in profile
    assert profile["car_definition"]["driver_place"] in bones
    for key in ("particle_bones1", "particle_bones2"):
        assert profile["damage_particles"][key] in bones, key
    for bone in profile["collision_damage"]:
        assert bone in bones, bone
    seats = heli["netcoop_seats"].split(",")
    assert len(seats) <= 8
    for item in seats:
        bone, *offset = item.strip().split(":")
        assert bone in bones and len(offset) == 3, item
        [float(v) for v in offset]
    if "netcoop_seat_eyes" in heli:
        eyes = [tuple(map(float, item.split(':'))) for item in heli['netcoop_seat_eyes'].split(',')]
        assert 0 < len(eyes) <= len(seats)
        box = struct.unpack_from('<6f', model[1], 4)
        for eye in eyes:
            assert len(eye) == 3 and all(math.isfinite(v) for v in eye)
            assert all(box[j] < eye[j] < box[j+3] for j in range(3)), (model_name, eye, box)
        if section == 'veh_mi24_heli':
            # Cabin envelopes measured from the shipped mesh, excluding the
            # rotor/tail extents of its much larger overall bounding box.
            front, rear = eyes
            assert abs(front[0]) < .5 and 1.15 < front[1] < 2.1 and 3.5 < front[2] < 5
            assert abs(rear[0]) < .5 and 1.5 < rear[1] < 2.75 and 2 < rear[2] < 3.4
            camera = tuple(map(float, profile['car_definition']['camera_pos'].split(',')))
            assert camera == front and rear[1] > front[1] and rear[2] < front[2]
    given = {key for key in heli if key.startswith("heli_")}
    assert given <= read, f"unknown keys {sorted(given - read)}"
    assert read <= given, f"{section}: keys left at the engine default {sorted(read - given)}"
    assert heli["netcoop_heli"] == "true" and heli["visual"] == "dynamics\\vehicles\\" + folder + "\\" + model_name + ".ogf"
    for key in ("netcoop_center_x", "netcoop_half_width", "netcoop_rear_z"):
        assert f'"{key}"' in inc and key in heli, key
    # Lift must hold the weight with room to climb at the default collective rate.
    assert 1.1 < float(heli["heli_lift_ratio"]) < 3
    # Every texture the model names ships (overlay) or is a base-game Mi-2 one.
    textures = set(re.findall(rb"(veh[\\][a-z0-9_]+)\x00", ogf.read_bytes()))
    assert textures, "no textures found"
    for texture in textures:
        name_ = texture.decode()
        assert (OVERLAY / "client/textures" / (name_.replace("\\", "/") + ".dds")).is_file() or name_ in ("veh\\veh_mi2", "veh\\veh_mi24_vint"), name_
    report.append(f"{section}: {len(bones)} bones, {len(seats)} seats, {len(textures)} textures")

print("Helicopters: " + "; ".join(report) + f"; {len(read)} flight keys, profiles and sections agree with Car.cpp, client = server PASS")
