"""Convert reviewed original albedo to game DDS with full mip chains."""
import argparse
from io import BytesIO
from pathlib import Path
import hashlib
import json
import struct
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('--candidate', type=Path, required=True)
args = parser.parse_args()
base = args.candidate
records = json.loads((base/'conversion.json').read_text(encoding='utf-8'))
done = {}
for model in records:
    for row in model['textures']:
        key = row['texture']
        if key in done:
            continue
        image = Image.open(row['source']).convert('RGBA' if row['alpha'] else 'RGB')
        size = image.size
        level = image
        payloads = []
        headers = []
        while True:
            stream = BytesIO()
            level.save(stream, format='DDS', pixel_format='DXT5' if row['alpha'] else 'DXT1')
            data = stream.getvalue()
            headers.append(data[:128])
            payloads.append(data[128:])
            block = 16 if row['alpha'] else 8
            assert len(payloads[-1]) == ((level.width+3)//4)*((level.height+3)//4)*block
            if level.size == (1, 1):
                break
            level = level.resize((max(1, level.width//2), max(1, level.height//2)), Image.Resampling.LANCZOS)
        header = bytearray(headers[0])
        struct.pack_into('<I', header, 8, struct.unpack_from('<I', header, 8)[0] | 0x20000)
        struct.pack_into('<I', header, 20, len(payloads[0]))
        struct.pack_into('<I', header, 28, len(payloads))
        struct.pack_into('<I', header, 108, struct.unpack_from('<I', header, 108)[0] | 0x400008)
        destination = base/'textures'/key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(header+b''.join(payloads))
        assert Image.open(destination).size == size
        done[key] = dict(source_sha256=hashlib.sha256(Path(row['source']).read_bytes()).hexdigest(),
            sha256=hashlib.sha256(destination.read_bytes()).hexdigest(), size=size,
            mips=len(payloads), format='DXT5' if row['alpha'] else 'DXT1', bytes=destination.stat().st_size)
(base/'textures-reviewed.json').write_text(json.dumps(done, indent=2)+'\n', encoding='utf-8')
print('Converted', len(done), 'original textures; dimensions retained, full DDS mip chains')
