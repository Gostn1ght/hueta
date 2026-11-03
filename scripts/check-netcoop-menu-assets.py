"""Validate original add-on streams and their actual UI references, offline."""
import hashlib
import json
import struct
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
client = root / 'scripts/netcoop-overlay/client'
manifest = json.loads((root / 'assets/menu/addons/manifest.json').read_text(encoding='utf-8'))
assert manifest['source_url'].startswith('https://www.moddb.com/mods/stalker-anomaly/addons/')
assert manifest['author'] == 'karatel_196rus'
assert {r['id'] for r in manifest['images']} == {'classic', 'campfire', 'night'}
for row in manifest['images']:
    data = (client / 'textures' / row['texture']).read_bytes()
    assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
    # Actual Ogg lacing, including the non-video metadata stream before Theora.
    offset = 0
    partial = {}
    video = False
    video_serial = None
    video_hash = hashlib.sha256()
    video_packets = 0
    while offset < len(data):
        assert data[offset:offset+4] == b'OggS' and data[offset+4] == 0
        serial, = struct.unpack_from('<I', data, offset+14)
        count = data[offset+26]
        laces = data[offset+27:offset+27+count]
        begin = offset+27+count
        assert begin+sum(laces) <= len(data)
        packet = partial.get(serial, bytearray())
        for size in laces:
            packet += data[begin:begin+size]
            begin += size
            if size < 255:
                if packet.startswith(b'\x80theora'):
                    width = int.from_bytes(packet[14:17], 'big')
                    height = int.from_bytes(packet[17:20], 'big')
                    assert (width, height) == (row['width'], row['height']) == (1920, 1080)
                    video = True
                    video_serial = serial
                if serial == video_serial and packet and not packet[0] & 128:
                    video_hash.update(struct.pack('<I', len(packet)))
                    video_hash.update(packet)
                    video_packets += 1
                # These menu clips must not introduce music or other audio.
                assert not packet.startswith((b'\x01vorbis', b'OpusHead', b'fLaC'))
                packet = bytearray()
        partial[serial] = packet
        offset = begin
    assert video and offset == len(data) and not any(partial.values())
    assert video_hash.hexdigest() == row['encoded_video_sha256'] and video_packets == row['video_packets']

for path in (client / 'configs/ui').glob('*.xml'):
    data = path.read_bytes()
    assert b'ui\\lost_zone_background' not in data and b'ui\\lz_menu_' not in data, path
    if b'ui\\lz_addon_' in data:
        xml = ET.fromstring(data)
        for texture in xml.iter('texture'):
            if (texture.text or '').startswith('ui\\lz_addon_'):
                assert texture.attrib['width'] == '1920' and texture.attrib['height'] == '1080'
assert (client / 'netcoop_login_ui.script').read_bytes().isascii()
print('PASS original add-on hashes, complete silent Theora/Ogg streams, 1920x1080 UI rectangles, no active AI background references')
