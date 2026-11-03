"""Read PE import tables; never load or execute the game, server or DLLs."""
from pathlib import Path
import argparse
import struct

SYSTEM=set('msvfw32 avifil32 winmm kernel32 user32 gdi32 dinput8 cfgmgr32 d3dcompiler_47 d3d11 dxgi bcrypt version winhttp crypt32 dnsapi imm32 advapi32 shell32 ole32 oleaut32 ws2_32 iphlpapi ktmw32 msvcrt ucrtbase ntdll rpcrt4 combase shlwapi setupapi psapi comdlg32 comctl32 uxtheme d3d9 dwmapi wininet wldap32 xinput1_4'.split())
REQUIRED=('GameNetworkingSockets.dll','libprotobuf.dll','libcrypto-3-x64.dll','discord_game_sdk.dll','icuuc65.dll','icudt65.dll','tbb.dll','soft_oal.dll','D3DX9_43.dll','d3dx11_43.dll','D3DCompiler_43.dll','msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')
# The native master uses Windows' signed System32 DbgHelp for crash stacks.
# It is supplied by the OS, like kernel32, rather than an app-local runtime.
SYSTEM.add('dbghelp')

def imports(path):
    data=path.read_bytes()
    def u16(offset):return struct.unpack_from('<H',data,offset)[0]
    def u32(offset):return struct.unpack_from('<I',data,offset)[0]
    if data[:2]!=b'MZ':raise ValueError('Missing PE header: '+str(path))
    pe=u32(0x3c)
    if data[pe:pe+4]!=b'PE\0\0':raise ValueError('Invalid PE signature: '+str(path))
    machine=u16(pe+4);count=u16(pe+6);opt=pe+24;size=u16(pe+20);magic=u16(opt)
    if magic not in (0x10b,0x20b):raise ValueError('Invalid optional PE header')
    sections=[]
    for index in range(count):
        offset=opt+size+index*40
        virtual_size,virtual,raw_size,raw=struct.unpack_from('<4I',data,offset+8)
        sections.append((virtual,virtual_size,raw,raw_size))
    def rva(value):
        for base,virtual_size,raw,raw_size in sections:
            if base<=value<base+max(virtual_size,raw_size):
                displacement=value-base
                if displacement>=raw_size:raise ValueError('PE RVA outside raw bytes')
                return raw+displacement
        if value<u32(opt+60):return value
        raise ValueError('Unmapped PE RVA')
    def string(value):
        offset=rva(value);end=data.index(b'\0',offset,offset+512)
        return data[offset:end].decode('ascii').lower()
    directories=opt+(112 if magic==0x20b else 96)
    names=[]
    # Imports and delay imports. Delay descriptors must contain RVAs.
    for index,width,name_offset in ((1,20,12),(13,32,4)):
        address,length=struct.unpack_from('<II',data,directories+index*8)
        if not address:continue
        offset=rva(address)
        for _ in range(length//width+1):
            descriptor=data[offset:offset+width]
            if len(descriptor)!=width:raise ValueError('Truncated PE import table')
            if not any(descriptor):break
            if index==13 and not u32(offset)&1:raise ValueError('Unsupported VA delay import')
            names.append(string(u32(offset+name_offset)));offset+=width
        else:raise ValueError('Unterminated PE import table')
    # ICU's data DLL is a resource-only PE32 image, even in the x64 release.
    resource_only=machine==0x14c and not names and u32(opt+16)==0
    if machine!=0x8664 and not resource_only:raise ValueError('Non-x64 code image: '+str(path))
    return names

def check(package):
    errors=[];checked=0
    for subfolder,exe in (('bin','LostZoneClientDX11.exe'),('dedicated','LostZoneServerDX11.exe')):
        folder=package/subfolder
        files={p.name.lower():p for p in folder.iterdir() if p.is_file()}
        for name in (exe,)+REQUIRED:
            if name.lower() not in files:errors.append(subfolder+': missing '+name)
        for name,path in files.items():
            if path.suffix.lower() not in ('.exe','.dll'):continue
            checked+=1
            for dependency in imports(path):
                if dependency in files:continue
                if dependency.startswith(('api-ms-win-','ext-ms-win-')):continue
                if dependency.endswith('.dll') and dependency[:-4] in SYSTEM:continue
                errors.append(subfolder+'/'+path.name+': unresolved '+dependency)
    if errors:raise ValueError('\n'.join(errors))
    print(f'PASS PE imports: {checked} images, app-local engine/transport/VC/DirectX dependencies present; nothing executed')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('package',type=Path)
    check(parser.parse_args().package)
