"""Read effective X-Ray namespaces for a role, with authenticated block IO.

No engine process and no key in output. Archive payload CRC may use the old
engine's raw hardware CRC32C; both that format and standard IEEE are verified.
"""
from collections import OrderedDict
import hashlib
import importlib.util
from pathlib import Path, PureWindowsPath
import re
import struct
import zlib
import lzokay
import lzpack

_path = Path(__file__).resolve().parents[1] / 'read-xray-sound-archive.py'
_spec = importlib.util.spec_from_file_location('xray_table_reader', _path)
_tables = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tables)

def safe(name):
    p = PureWindowsPath(name)
    return (name and not p.is_absolute() and not p.drive and not p.root and
            all(s not in ('', '.', '..') for s in name.replace('/', '\\').split('\\')) and '\0' not in name)

_crc32c = []
for _i in range(256):
    _v = _i
    for _ in range(8): _v = (_v >> 1) ^ (0x82f63b78 if _v & 1 else 0)
    _crc32c.append(_v)

def raw_crc32c(path):
    value = 0xffffffff
    with path.open('rb') as stream:
        while chunk := stream.read(1024*1024):
            for byte in chunk: value = (value >> 8) ^ _crc32c[(value ^ byte) & 255]
    return value

class Archive:
    def __init__(self, path, key, role):
        self.path = Path(path)
        with self.path.open('rb') as stream: magic = stream.read(8)
        self.reader = lzpack.Reader(self.path, key) if magic == lzpack.MAGIC else None
        self.size = self.reader.size if self.reader else self.path.stat().st_size
        self.cache = OrderedDict()
        position, table, entry = 0, None, '$fs_root$'
        while position + 8 <= self.size:
            kind, size = struct.unpack('<II', self.read(position, 8)); position += 8
            if position + size > self.size: raise ValueError('Archive chunk bounds: ' + self.path.name)
            if kind & 0x7fffffff in (1, 666):
                data = self.read(position, size)
                if kind & 0x80000000: data = _tables.decompress_lzhuf(data)
                if kind & 0x7fffffff == 1: table = data
                else:
                    match = re.search(rb'^entry_point\s*=\s*(.*?)\s*$', data, re.M)
                    if match: entry = match[1].decode('cp1251')
            position += size
        if position != self.size or table is None: raise ValueError('Missing/corrupt archive table: ' + self.path.name)
        entry = entry.replace('/', '\\').lower().rstrip('\\')
        aliases = {'$fs_root$': '', '$game_data$': 'gamedata', '$game_scripts$': role+'\\scripts', '$game_config$': role+'\\configs'}
        for alias, prefix in aliases.items():
            if entry == alias or entry.startswith(alias+'\\'):
                entry = prefix + entry[len(alias):]; break
        entry = entry.strip('\\')
        if '$' in entry or (entry and not safe(entry)): raise ValueError('Unknown archive mount: ' + self.path.name)
        self.files = {}
        offset = 0
        while offset < len(table):
            if offset + 2 > len(table): raise ValueError('Truncated archive row')
            length, = struct.unpack_from('<H', table, offset); offset += 2
            if length < 16 or offset + length > len(table): raise ValueError('Invalid archive row')
            real, packed, crc = struct.unpack_from('<III', table, offset)
            name = table[offset+12:offset+length-4].decode('cp1251').replace('/', '\\').lower()
            at, = struct.unpack_from('<I', table, offset+length-4)
            if name.endswith('\\') and real == packed == at == 0 and safe(name[:-1]):
                offset += length; continue # xrCompress's explicit directory entries
            if not safe(name) or real > 1024**3 or at+packed > self.size:
                raise ValueError(f'Invalid archive row {self.path.name}: {name!r}, offset={at}, real={real}, packed={packed}, archive={self.size}')
            virtual = (entry+'\\' if entry else '') + name
            if virtual in self.files: raise ValueError('Duplicate archive path')
            self.files[virtual] = (at, real, packed, crc)
            offset += length

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset+length > self.size: raise ValueError('Archive read bounds')
        if not self.reader:
            with self.path.open('rb') as stream: stream.seek(offset); data = stream.read(length)
            if len(data) != length: raise ValueError('Short archive read')
            return data
        output = bytearray()
        while length:
            block, inside = divmod(offset, lzpack.BLOCK)
            data = self.cache.pop(block, None)
            if data is None: data = self.reader.read(block*lzpack.BLOCK, min(lzpack.BLOCK,self.size-block*lzpack.BLOCK))
            self.cache[block] = data
            while len(self.cache) > 16: self.cache.popitem(last=False)
            take = min(length,len(data)-inside); output += data[inside:inside+take]; offset += take; length -= take
        return bytes(output)

    def extract(self, name, target):
        at, real, packed, expected = self.files[name]
        target = Path(target); target.parent.mkdir(parents=True,exist_ok=True)
        crc = 0; digest = hashlib.sha256(); size = 0
        with target.open('xb') as output:
            if real != packed:
                data = lzokay.decompress(self.read(at,packed),real)
                output.write(data); crc = zlib.crc32(data); digest.update(data); size = len(data)
            else:
                while size < real:
                    data = self.read(at+size,min(1024*1024,real-size)); output.write(data)
                    crc = zlib.crc32(data,crc); digest.update(data); size += len(data)
        if size != real: raise ValueError('Archive payload size mismatch: '+name)
        kind = 'ieee'
        if crc != expected:
            raw = raw_crc32c(target)
            if expected not in (raw, raw ^ 0xffffffff): raise ValueError('Archive CRC mismatch: '+name)
            kind = 'legacy-crc32c'
        return dict(sha256=digest.hexdigest(),size=size,crc=kind)

def effective(resources, key, role):
    archives, scripts, assets, configs = [], {}, {}, {}
    root=Path(resources)
    for path in sorted(root.rglob('*'),key=lambda p:(len(p.relative_to(root).parts),p.as_posix().lower())):
        relative=path.relative_to(root)
        if len(relative.parts)>1 and (role!='server' or relative.parts[:-1]!=('server',)): continue
        if path.name.startswith('99_v2_') and ('_client_' in path.name if role=='server' else '_server_' in path.name): continue
        if not path.is_file() or not path.name.startswith(('90_lostzone_lz_misc','90_lostzone_lz_scripts','95_server_','99_')) or not path.suffix.startswith('.db'): continue
        archive = Archive(path,key,role); archives.append(archive)
        for name in archive.files:
            prefix = role+'\\scripts\\'
            if name.startswith(prefix): scripts[name[len(prefix):]] = (archive,name)
            elif name.startswith(role+'\\configs\\'): configs[name[len(role+'\\configs\\'):]] = (archive,name)
            elif name.startswith('gamedata\\'): assets[name[len('gamedata\\'):]] = (archive,name)
    return archives, scripts, assets, configs
