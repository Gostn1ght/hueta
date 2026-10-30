"""Packer roundtrip, tampering, patch table/precedence and no private inputs."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import os
import random
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/lzpack'))
import lzpack
from cryptography.exceptions import InvalidTag

def rejected(fn):
    try:fn()
    except (ValueError,InvalidTag,FileExistsError):return
    raise AssertionError('Invalid archive/input was accepted')

with TemporaryDirectory() as tmp:
    folder=Path(tmp);key=bytes(range(32));raw=folder/'source.db';encrypted=folder/'base.db0'
    original=bytes((i*13)%251 for i in range(3*lzpack.BLOCK+37));raw.write_bytes(original)
    lzpack.protect(raw,encrypted,key)
    assert lzpack.verify(encrypted,key,raw)==hashlib.sha256(original).hexdigest()
    reader=lzpack.Reader(encrypted,key)
    rng=random.Random(42)
    for _ in range(100):
        offset=rng.randint(0,len(original));count=rng.randint(0,len(original)-offset)
        assert reader.read(offset,count)==original[offset:offset+count]
    rejected(lambda:reader.read(reader.size,1));rejected(lambda:reader.read(-1,2))
    rejected(lambda:lzpack.verify(encrypted,bytes(reversed(key))))
    source=encrypted.read_bytes()
    for position in (24,40,48,48+lzpack.BLOCK, len(source)-1):
        data=bytearray(source);data[position]^=1;bad=folder/'bad.db0';bad.write_bytes(data)
        rejected(lambda:lzpack.verify(bad,key))
    bad.write_bytes(source[:-1]);rejected(lambda:lzpack.Reader(bad,key))
    # Whole valid block swapped with another is also rejected: index is in AAD/nonce.
    data=bytearray(source);width=lzpack.BLOCK+lzpack.TAG
    data[48:48+width],data[48+width:48+2*width]=data[48+width:48+2*width],data[48:48+width]
    bad.write_bytes(data);rejected(lambda:lzpack.verify(bad,key))
    patchdir=folder/'patch';(patchdir/'client/scripts').mkdir(parents=True)
    (patchdir/'client/scripts/fix.script').write_bytes(b'return "fixed"')
    output=lzpack.patch(patchdir,folder/'updates',key,'000002');patch=lzpack.Reader(output,key)
    data=patch.read(0,patch.size);off=0;chunks={}
    while off<len(data):
        kind,size=struct.unpack_from('<II',data,off);off+=8;chunks[kind]=(off,data[off:off+size]);off+=size
    assert b'entry_point = $fs_root$\\' in chunks[666][1]
    table=chunks[1][1];size=struct.unpack_from('<H',table)[0];entry=table[2:2+size]
    real,compressed,crc=struct.unpack_from('<III',entry);ptr=struct.unpack_from('<I',entry,len(entry)-4)[0]
    assert entry[12:-4]==b'client\\scripts\\fix.script' and data[ptr:ptr+real]==b'return "fixed"' and real==compressed
    rejected(lambda:lzpack.patch(patchdir,folder/'updates',key,'000002'))
    (patchdir/'server/scripts').mkdir(parents=True)
    (patchdir/'server/scripts/server_only.script').write_bytes(b'return "server-only"')
    clientpack=lzpack.patch(patchdir,folder/'client-updates',key,'000003','client')
    serverpack=lzpack.patch(patchdir,folder/'server-updates',key,'000003','server')
    clientreader=lzpack.Reader(clientpack,key);serverreader=lzpack.Reader(serverpack,key)
    clientdata=clientreader.read(0,clientreader.size);serverdata=serverreader.read(0,serverreader.size)
    assert b'server-only' not in clientdata and b'client\\scripts' not in serverdata
    (patchdir/'client/configs').mkdir();(patchdir/'client/configs/system.ltx').write_bytes(b'client-config')
    (patchdir/'server/configs').mkdir();(patchdir/'server/configs/system.ltx').write_bytes(b'server-config')
    (patchdir/'client/assets').mkdir();(patchdir/'client/assets/fixture.bin').write_bytes(b'client-asset')
    (patchdir/'server/assets').mkdir();(patchdir/'server/assets/fixture.bin').write_bytes(b'server-asset')
    for role in ('client','server'):
        volumes=lzpack.patch_v2(patchdir,folder/('v2-'+role),key,'000048',role)
        assert len(volumes)==3
        for archive in volumes:
            reader=lzpack.Reader(archive,key);data=reader.read(0,reader.size)
            other='server' if role=='client' else 'client'
            assert (other+'-asset').encode() not in data and (other+'-config').encode() not in data
            assert b'client\\scripts' not in data and b'server\\scripts' not in data
            alias=b'$game_config$\\' if '_configs_' in archive.name else b'$game_scripts$\\' if '_scripts_' in archive.name else b'$game_data$\\'
            assert b'entry_point = '+alias in data
            assert '99_v2_000047_40_server_scripts_000.db0' < archive.name
        rejected(lambda:lzpack.patch_v2(patchdir,folder/('v2-'+role),key,'000048',role))
    (patchdir/'appdata').mkdir();(patchdir/'appdata/account.key').write_bytes(b'private')
    rejected(lambda:lzpack.patch(patchdir,folder/'updates',key,'000003'))
    root=Path(__file__).resolve().parents[1]
    for role in ('client','server'):
        template=(root/f'scripts/dist/fsgame_{role}.template').read_text()
        if '$arch_dir_lostzone_updates$' in template:
            assert template.index('$arch_dir_lostzone_updates$')>template.index('$game_scripts$')
        else:
            # The server mounts one resources folder. Archive filename order
            # gives 99_lz_patch_* precedence over the 95_server_* base; the
            # actual release builder and mounted layout are checked below by
            # check-lzpack-release.py as well.
            aliases=[line.split('=')[0].strip() for line in template.splitlines()
                     if line.startswith('$arch_dir')]
            assert aliases==['$arch_dir$'], aliases
            assert '$arch_dir$ = false | false | {ROOT}resources\\' in template
            assert '95_server_base.db0' < '99_lz_patch_000006_server.db0'
print('PASS protected archives: random reads, full roundtrip, wrong key/tampered headers/cipher/tags/block swaps rejected, patch table and latest precedence, no private files')
