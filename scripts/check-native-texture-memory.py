"""Compile the actual bounded texture retry and dedicated input path on CI."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
texture = (root / 'src/Layers/xrRenderDX10/dx10Texture.cpp').read_text(encoding='utf-8')
assert texture.count('R_CHK2(create_texture_with_memory_retry(S, IMG, LoadInfo, pTexture2D, img_loaded_lod, fn), fn)') == 2
assert 'result == E_OUTOFMEMORY || result == HRESULT_FROM_WIN32(ERROR_NOT_ENOUGH_MEMORY)' in texture
text = (root / 'src/xrEngine/Xr_input.cpp').read_text(encoding='utf-8')
start = text.index('void CInput::OnFrame(void)')
input_method = text[start:text.index('\nIInputReceiver* CInput::CurrentIR', start)]
source = r'''
#include <cassert>
#include <cstdio>
#include <initializer_list>
''' + '#include "' + (root / 'src/Layers/xrRender/texture_memory_retry.h').as_posix() + '"\n' + r'''
struct Info { unsigned Width=1024,Height=1024,FirstMipLevel=0,MipLevels=11,BindFlags=7,MiscFlags=6,Format=42; };
struct Counter { unsigned begins=0,ends=0; void Begin(){++begins;}void End(){++ends;} };
struct Device { struct {Counter Input;} statistic; decltype(statistic)* Statistic=&statistic;unsigned TimerAsync_MMT(){return 10;} } RDEVICE;
bool g_dedicated_server=false;
struct CInput {void* pKeyboard=this;void* pMouse=this;unsigned dwCurTime=0,keys=0,mouse=0;void KeyUpdate(){++keys;}void MouseUpdate(){++mouse;}void OnFrame();};
''' + input_method + r'''
int main(){
 CInput input;g_dedicated_server=true;input.OnFrame();
 assert(input.keys==0&&input.mouse==0&&RDEVICE.statistic.Input.begins==0);
 g_dedicated_server=false;input.OnFrame();
 assert(input.keys==1&&input.mouse==1&&RDEVICE.statistic.Input.begins==1&&RDEVICE.statistic.Input.ends==1);
 auto oom=[](int result){return result==-3;};
 {
  Info info;int lod=0;unsigned calls=0,releases=0;
  auto result=create_texture_with_mip_retry(info,1024,1024,11,lod,[&](){++calls;return 0;},[&](){++releases;},oom,[](){});
  assert(result==0&&calls==1&&releases==0&&lod==0&&info.Width==1024&&info.MipLevels==11);
 }
 {
  Info info;int lod=0;unsigned calls=0,releases=0,notifications=0;
  auto result=create_texture_with_mip_retry(info,1024,1024,11,lod,[&](){++calls;return calls<3?-3:0;},[&](){++releases;},oom,[&](){++notifications;assert(releases==notifications);});
  assert(result==0&&calls==3&&releases==2&&lod==2&&info.Width==256&&info.Height==256&&info.FirstMipLevel==2&&info.MipLevels==9);
  assert(info.BindFlags==7&&info.MiscFlags==6&&info.Format==42);
 }
 {
  // Mipless DDS cubemaps are common: retain mip 0 and resize the real image.
  Info info;info.MipLevels=1;int lod=0;unsigned calls=0;
  auto result=create_texture_with_mip_retry(info,1024,1024,1,lod,[&](){++calls;return calls==1?-3:0;},[](){},oom,[](){});
  assert(result==0&&calls==2&&lod==1&&info.Width==512&&info.FirstMipLevel==0&&info.MipLevels==1&&info.MiscFlags==6);
 }
 {
  Info info;int lod=0;unsigned calls=0;
  auto result=create_texture_with_mip_retry(info,1024,1024,11,lod,[&](){++calls;return -3;},[](){},oom,[](){});
  assert(result==-3&&calls==4&&lod==3&&info.Width==128);
 }
 {
  Info info;int lod=0;unsigned calls=0;
  auto result=create_texture_with_mip_retry(info,1024,1024,11,lod,[&](){++calls;return -4;},[](){assert(false);},oom,[](){assert(false);});
  assert(result==-4&&calls==1&&lod==0&&info.Width==1024);
 }
 for(int lod:{-1,31}){
  Info info;unsigned calls=0;
  auto result=create_texture_with_mip_retry(info,1024,1024,11,lod,[&](){++calls;return -3;},[](){assert(false);},oom,[](){assert(false);});
  assert(result==-3&&calls==1);
 }
 {
  Info info;info.Width=info.Height=4;int lod=0;unsigned calls=0;
  auto result=create_texture_with_mip_retry(info,4,4,1,lod,[&](){++calls;return -3;},[](){assert(false);},oom,[](){assert(false);});
  assert(result==-3&&calls==1);
 }
 std::puts("PASS actual texture retry: unchanged success/other errors, bounded OOM retries, real lower mips/mipless image resize, preserved cube/format flags; dedicated gameplay input disabled");
}
'''
with TemporaryDirectory() as tmp:
    cpp = Path(tmp) / 'texture_memory.cpp'
    exe = Path(tmp) / ('texture_memory.exe' if os.name == 'nt' else 'texture_memory')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)]
               if os.name == 'nt' else ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=tmp,check=True)
    subprocess.run([str(exe)],cwd=tmp,check=True)
