"""Check actual model payloads, skin palettes, mip chains and mirrored item definitions."""
from pathlib import Path
import hashlib
import json
import math
import re
import struct
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
client = root / 'scripts/netcoop-overlay/client'
server = root / 'scripts/netcoop-overlay/server'
manifest = json.loads((root / 'assets/admin-models/provenance.json').read_text(encoding='utf-8'))


def chunks(data):
    position = 0
    result = {}
    while position < len(data):
        assert position + 8 <= len(data)
        kind, size = struct.unpack_from('<II', data, position)
        position += 8
        assert kind not in result and position + size <= len(data)
        result[kind] = data[position:position+size]
        position += size
    return result


def mirrored(relative):
    data = (client / relative).read_bytes()
    assert data == (server / relative).read_bytes(), relative
    return data


models = 0
vertices = 0
for model in manifest['models']:
    data = mirrored(model['model'])
    assert hashlib.sha256(data).hexdigest() == model['sha256']
    body = chunks(data)
    assert struct.unpack_from('<I', body[13])[0] == 47
    for child in chunks(body[9]).values():
        fields = chunks(child)
        texture, shader, *_ = fields[2].decode('cp1251').split('\0')
        assert shader in {'models\\model', 'models\\model_aref'}
        relative = texture.replace('\\', '/') + '.dds'
        assert relative in manifest['textures'], relative
        vertex_type, count = struct.unpack_from('<II', fields[3])
        sizes = {1: 60, 2: 64, 3: 70, 4: 76}
        assert vertex_type in sizes and 0 < count <= 65535
        size = sizes[vertex_type]
        assert len(fields[3]) == 8 + count * size
        for index in range(count):
            offset = 8 + index * size
            if vertex_type == 1:
                assert struct.unpack_from('<I', fields[3], offset+56)[0] < 47
                floats = struct.unpack_from('<14f', fields[3], offset)
            else:
                bones = struct.unpack_from('<'+str(vertex_type)+'H', fields[3], offset)
                assert max(bones) < 47
                floats = struct.unpack_from('<'+str((size-vertex_type*2)//4)+'f', fields[3], offset+vertex_type*2)
                weights = floats[12:12+vertex_type-1]
                assert all(-1e-6 <= weight <= 1.000001 for weight in weights) and sum(weights) <= 1.00001
            assert all(math.isfinite(value) for value in floats)
        indices = fields[4]
        number = struct.unpack_from('<I', indices)[0]
        assert number % 3 == 0 and len(indices) == 4 + number * 2
        assert max(struct.unpack_from('<'+str(number)+'H', indices, 4)) < count
        vertices += count
    models += 1

for relative, texture in manifest['textures'].items():
    data = mirrored('textures/'+relative)
    assert hashlib.sha256(data).hexdigest() == texture['sha256']
    assert data[:4] == b'DDS ' and struct.unpack_from('<I', data, 4)[0] == 124
    height, width = struct.unpack_from('<II', data, 12)
    mips = struct.unpack_from('<I', data, 28)[0]
    assert [width, height] == texture['size'] and mips == texture['mips']
    code = data[84:88]
    assert code in {b'DXT1', b'DXT5'}
    expected = 128
    for _ in range(mips):
        expected += ((width+3)//4) * ((height+3)//4) * (8 if code == b'DXT1' else 16)
        width, height = max(1, width//2), max(1, height//2)
    assert width == height == 1 and len(data) == expected

config = mirrored('configs/mod_system_zzzzzzzzzzzz_lostzone_admin_models.ltx').decode('ascii')
assert '[lz_admin_mahito]:exo_outfit' in config and '[lz_admin_areke]:lz_admin_mahito' in config
assert 'can_trade = false' in config and 'additional_inventory_weight = 1000' in config
assert 'visual = dynamics\\outfit\\exo_outfit' in config and 'visual = dynamics\\outfit\\merc_exo_outfit' in config
radiation = re.search(r'^radiation_restore_speed\s*=\s*([-+.\d]+)', config, re.M)
assert radiation and float(radiation[1]) < 0, 'Outfits must remove radiation, not irradiate their wearer'
for language in ['rus', 'eng']:
    strings = ET.fromstring(mirrored('configs/text/'+language+'/st_lz_admin_models.xml'))
    values = {row.attrib['id']: row.findtext('text') for row in strings}
    assert values['st_lz_admin_mahito'] == 'Mahito' and values['st_lz_admin_areke'] == 'Areke'
print(f'PASS actual admin assets: {models} models, {vertices} finite skinned vertices, 47-bone palettes, index bounds, {len(manifest["textures"])} complete DDS chains, matching server/client and CP1251 names')
