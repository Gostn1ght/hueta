"""Owner packer: X-Ray DB compression first, authenticated protection second.

The engine reads blocks on demand, including streamed OGG. Key stays with
the owner/GHA; it must never be included in player or dedicated packages.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import zlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b'LZPACK1\0'
HEADER = struct.Struct('<8sIIQ16s8s')
BLOCK, TAG = 65536, 16
MAX_VOLUME = 850 * 1024 * 1024

def master(path):
    value = Path(path).read_bytes()
    if len(value) != 32: raise ValueError('Archive key must be exactly 32 bytes')
    return value

def protect(source, dest, key):
    source, dest = Path(source), Path(dest)
    if source.resolve() == dest.resolve(): raise ValueError('Use a separate destination until verification finishes')
    size = source.stat().st_size
    if not 0 < size < 4 * 1024**3: raise ValueError('Archive size is outside X-Ray limits')
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(8)
    header = HEADER.pack(MAGIC, 1, BLOCK, size, salt, nonce)
    aes = AESGCM(hashlib.sha256(key + salt).digest())
    temporary = dest.with_name(dest.name + '.writing')
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or temporary.exists(): raise FileExistsError('Destination already exists')
    try:
        with source.open('rb') as incoming, temporary.open('xb') as outgoing:
            outgoing.write(header)
            i = 0
            while chunk := incoming.read(BLOCK):
                index = struct.pack('<I', i)
                outgoing.write(aes.encrypt(nonce + index, chunk, header + index))
                i += 1
            outgoing.flush(); os.fsync(outgoing.fileno())
        verify(temporary, key, expected_source=source)
        os.replace(temporary, dest)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.file_digest(dest.open('rb'), 'sha256').hexdigest()

class Reader:
    def __init__(self, path, key):
        self.path = Path(path)
        self.header = self.path.open('rb').read(HEADER.size)
        if len(self.header) != HEADER.size: raise ValueError('Truncated header')
        magic, version, chunk, self.size, salt, self.nonce = HEADER.unpack(self.header)
        if magic != MAGIC or version != 1 or chunk != BLOCK or not 0 < self.size < 4 * 1024**3:
            raise ValueError('Invalid archive header')
        expected = HEADER.size + self.size + ((self.size + BLOCK - 1) // BLOCK) * TAG
        if self.path.stat().st_size != expected: raise ValueError('Truncated archive')
        self.aes = AESGCM(hashlib.sha256(key + salt).digest())
    def read(self, offset, count):
        with self.path.open('rb') as stream:
            return self.read_stream(stream, offset, count)
    def read_stream(self, stream, offset, count):
        if offset < 0 or count < 0 or offset > self.size or count > self.size - offset:
            raise ValueError('Read outside archive')
        data = bytearray()
        while count:
            block, within = divmod(offset, BLOCK)
            length = min(BLOCK, self.size - block * BLOCK)
            stream.seek(HEADER.size + block * (BLOCK + TAG))
            index = struct.pack('<I', block)
            plain = self.aes.decrypt(self.nonce + index, stream.read(length + TAG), self.header + index)
            take = min(count, length - within)
            data.extend(plain[within:within+take]); offset += take; count -= take
        return bytes(data)

def verify(path, key, expected_source=None):
    reader = Reader(path, key)
    digest = hashlib.sha256()
    with Path(expected_source).open('rb') if expected_source else open(os.devnull, 'rb') as source, reader.path.open('rb') as encrypted:
        for offset in range(0, reader.size, BLOCK):
            chunk = reader.read_stream(encrypted, offset, min(BLOCK, reader.size - offset))
            if expected_source and source.read(len(chunk)) != chunk: raise ValueError('Archive roundtrip mismatch')
            digest.update(chunk)
    return digest.hexdigest()

def files_under(folder):
    folder = Path(folder).resolve()
    result = []
    for path in sorted(folder.rglob('*')):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('Packaging a link is forbidden')
        if not path.is_file(): continue
        name = path.relative_to(folder).as_posix().lower()
        if any(part in ('appdata', '.git', '_build') for part in Path(name).parts) or path.suffix.lower() in ('.pdb','.key','.secret'):
            raise ValueError('Private/state/build file in package input: ' + name)
        if name.startswith('netcoop_debug_') or '/netcoop_debug_' in name:
            raise ValueError('Private debug probe in package input')
        result.append((name.replace('/', '\\'), path))
    return result

def make_db(rows, dest, entry_point):
    # Standard uncompressed DB for small script/bugfix patches. Big base
    # archives keep xrCompress's compression; protection never recompresses.
    # level_name/level_ver: older engines read them from every archive header.
    header = ('[header]\nauto_load = true\nentry_point = ' + entry_point + '\nlevel_name = lostzone\nlevel_ver = 1.0\n').encode('cp1251')
    offset = 8 + len(header) + 8
    table, names = bytearray(), set()
    total = sum(p.stat().st_size for _,p in rows)
    if total > MAX_VOLUME: raise ValueError('Split the patch into volumes smaller than 850 MiB')
    with Path(dest).open('xb') as output:
        output.write(struct.pack('<II', 666, len(header))); output.write(header)
        output.write(struct.pack('<II', 0, total))
        for name, path in rows:
            if name in names: raise ValueError('Duplicate case-insensitive archive path')
            names.add(name)
            encoded = name.encode('cp1251')
            if len(encoded) > 240: raise ValueError('Archive path is too long')
            crc, size = 0, path.stat().st_size
            with path.open('rb') as incoming:
                while chunk := incoming.read(1024*1024):
                    output.write(chunk); crc = zlib.crc32(chunk, crc)
            entry = struct.pack('<III', size, size, crc) + encoded + struct.pack('<I', offset)
            table.extend(struct.pack('<H', len(entry)) + entry); offset += size
        output.write(struct.pack('<II', 1, len(table))); output.write(table)

def patch(source, dest, key, version, role='client'):
    if not version.isdecimal() or len(version) != 6: raise ValueError('Patch version must have six digits, e.g. 000001')
    rows = files_under(source)
    if not rows: raise ValueError('Patch input is empty')
    for name,_ in rows:
        if not any(name.startswith(prefix) for prefix in ('gamedata\\','client\\scripts\\','server\\scripts\\')):
            raise ValueError('Use gamedata/, client/scripts/ or server/scripts/; mutable configs and GHA binaries are separate updates: ' + name)
    rows = [(name,p) for name,p in rows if name.startswith('gamedata\\') or name.startswith(role+'\\scripts\\')]
    if not rows: return None
    dest = Path(dest); dest.mkdir(parents=True, exist_ok=True)
    # resources/ mounts in name order: 99_ sorts after every base archive. A
    # server patch has its own name: a host may keep the game and the server
    # add-on in one resources folder (it holds only server\scripts files).
    stem = f'99_lz_patch_{version}' + ('_server' if role == 'server' else '')
    output = dest / f'{stem}.db0'
    raw = dest / f'{stem}.raw-building'
    if output.exists() or raw.exists(): raise FileExistsError('Patch version already exists')
    try:
        make_db(rows, raw, '$fs_root$\\')
        digest = protect(raw, output, key)
    finally: raw.unlink(missing_ok=True)
    manifest = {'format':'LZPACK1','version':version,'archive':output.name,'sha256':digest,
                'files':[{ 'path':name,'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest()} for name,p in rows]}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return output

def patch_v2(source, dest, key, version, role='client'):
    """Role aliases for clean runtimes; numbered deltas sort after the base."""
    if not version.isdecimal() or len(version)!=6 or int(version)<47: raise ValueError('Clean layout starts at 000047')
    source,dest=Path(source),Path(dest)
    all_rows=files_under(source)
    prefixes=('gamedata\\','client\\scripts\\','server\\scripts\\','client\\configs\\','server\\configs\\','client\\assets\\','server\\assets\\')
    if any(not name.startswith(prefixes) for name,_ in all_rows): raise ValueError('Unexpected clean patch input')
    dest.mkdir(parents=True,exist_ok=True)
    outputs=[]
    for kind,order,alias in (('assets','20','$game_data$\\'),('configs','30','$game_config$\\'),('scripts','40','$game_scripts$\\')):
        prefix=role+'\\'+kind+'\\'
        rows=[(name[len(prefix):],path) for name,path in all_rows if name.startswith(prefix)]
        if kind=='assets':
            shared={name[len('gamedata\\'):]:path for name,path in all_rows if name.startswith('gamedata\\')}
            shared.update(dict(rows));rows=sorted(shared.items())
        if not rows: continue
        groups=[];group=[];size=0
        for name,path in rows:
            length=path.stat().st_size
            if length>MAX_VOLUME: raise ValueError('Single patch file exceeds volume limit')
            if group and size+length>MAX_VOLUME: groups.append(group);group=[];size=0
            group.append((name,path));size+=length
        if group: groups.append(group)
        for index,group in enumerate(groups):
            stem=f'99_v2_{version}_{order}_{role}_{kind}_{index:03d}.db0'
            output=dest/stem;raw=dest/(stem+'.raw-building')
            if output.exists() or raw.exists(): raise FileExistsError('Patch version already exists')
            try:
                make_db(group,raw,alias);protect(raw,output,key)
            finally: raw.unlink(missing_ok=True)
            outputs.append(output)
    return outputs

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('protect','verify','patch'):
        p=sub.add_parser(command);p.add_argument('--key',required=True);p.add_argument('--input',required=True)
        if command!='verify':p.add_argument('--output',required=True)
        if command=='patch':
            p.add_argument('--version',required=True)
            p.add_argument('--role',choices=('client','server','both'),default='both')
            p.add_argument('--layout',choices=('legacy','v2'),default='legacy')
    args=parser.parse_args();key=master(args.key)
    if args.command=='protect':print(protect(args.input,args.output,key))
    elif args.command=='verify':print(verify(args.input,key))
    else:
        roles=('client','server') if args.role=='both' else (args.role,)
        for role in roles:
            if args.layout=='v2':
                for result in patch_v2(args.input,Path(args.output)/role,key,args.version,role): print(result)
            else:
                result=patch(args.input,Path(args.output)/role,key,args.version,role)
                if result:print(result)
if __name__=='__main__':main()
