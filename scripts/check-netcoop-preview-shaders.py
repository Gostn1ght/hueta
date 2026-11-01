"""Compile menu/glass shaders with the real Direct3D compiler on GitHub."""
from pathlib import Path
import argparse
import ctypes as C
import os
import shutil
from tempfile import TemporaryDirectory
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Shader compilation must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--headers',type=Path,default=root.parent/'gamma-runtime/gamedata/shaders/r3')
args=parser.parse_args()
temporary=TemporaryDirectory(prefix='lz-dx11-shaders-')
fixtures=Path(temporary.name)
shutil.copytree(args.headers, fixtures, dirs_exist_ok=True)
for source in (root/'scripts/netcoop-overlay/client/shaders/r3').iterdir():
    shutil.copy2(source, fixtures/source.name)
class Macro(C.Structure):
    _fields_ = [('name', C.c_char_p), ('value', C.c_char_p)]
compiler = C.WinDLL('d3dcompiler_47.dll').D3DCompileFromFile
compiler.argtypes = [C.c_wchar_p, C.POINTER(Macro), C.c_void_p, C.c_char_p, C.c_char_p,
                    C.c_uint, C.c_uint, C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)]
compiler.restype = C.c_long
def take(blob):
    methods = C.cast(blob, C.POINTER(C.POINTER(C.c_void_p))).contents
    pointer = C.WINFUNCTYPE(C.c_void_p, C.c_void_p)(methods[3])(blob)
    size = C.WINFUNCTYPE(C.c_size_t, C.c_void_p)(methods[4])(blob)
    result = C.string_at(pointer, size)
    C.WINFUNCTYPE(C.c_ulong, C.c_void_p)(methods[2])(blob)
    return result
for shader in ['netcoop_preview', 'netcoop_room', 'netcoop_depth', 'netcoop_room_depth', 'netcoop_preview_bump', 'netcoop_room_bump', 'lz_heli_glass', 'model_env_lq']:
    for stage in (['vs'] if shader == 'model_env_lq' else ['ps'] if shader.endswith(('depth','bump','glass')) else ['vs', 'ps']):
        for skin in (['NONE', '0', '1', '2', '3', '4'] if stage == 'vs' and shader in ('netcoop_preview','model_env_lq') else ['NONE']):
            macros = (Macro*3)(Macro(('SKIN_'+skin).encode(), b'1'), Macro(b'USE_DX11', b'1'), Macro(None,None))
            code, errors = C.c_void_p(), C.c_void_p()
            result = compiler(str(fixtures/(shader+'.'+stage)), macros, C.c_void_p(1), b'main',
                              (stage+'_5_0').encode(), 0, 0, C.byref(code), C.byref(errors))
            if errors:
                diagnostics = take(errors).decode(errors='replace')
                if result < 0:
                    print(diagnostics)
            if result < 0:
                raise SystemExit(f'Shader compile failed: {shader}.{stage} SKIN_{skin}')
            binary = take(code)
            print(f'{shader}.{stage} SKIN_{skin} PASS ({len(binary)} bytes)')
