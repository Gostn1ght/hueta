"""CI-only actual R1 reset handlers; fake resource objects, no GPU/game."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess
if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks run only in Windows GitHub Actions')
root=Path(__file__).resolve().parents[1]
s=(root/'src/Layers/xrRenderPC_R1/FStaticRender.cpp').read_text(encoding='utf-8-sig')
def block(name):
 start=s.index(name);opening=s.index('{',start);depth=0
 for i in range(opening,len(s)):
  if s[i]=='{':depth+=1
  if s[i]=='}':
   depth-=1
   if depth==0:return s[start:i+1]
 raise AssertionError(name)
code=r'''
#include <cassert>
#include <cstdio>
#include <initializer_list>
unsigned dm_current_size=24,dm_size=24,loads=0,unloads=0,destructions=0;
float ps_r__Detail_density=.2f,ps_current_detail_density=.2f,ps_r__Detail_height=1,ps_current_detail_height=1;
struct CDetailManager{~CDetailManager(){++destructions;}void Unload(){++unloads;}void Load(){++loads;dm_size=dm_current_size;ps_current_detail_density=ps_r__Detail_density;ps_current_detail_height=ps_r__Detail_height;}};
struct CRenderTarget{};struct Projector{void invalidate(){}};
template<class T>void xr_delete(T*& p){delete p;p=nullptr;}
template<class T>T* xr_new(){return new T;}
struct CRender{bool b_loaded=true,m_bFirstFrameAfterReset=false;CDetailManager*Details=nullptr;CRenderTarget*Target=nullptr;Projector*L_Projector=nullptr;void reset_begin();void reset_end();};
'''+block('void CRender::reset_begin()')+'\n'+block('void CRender::reset_end()')+r'''
int main(){
 for(bool loaded:{false,true})for(unsigned mask=0;mask<8;++mask){
  dm_size=dm_current_size=24;ps_r__Detail_density=ps_current_detail_density=.2f;ps_r__Detail_height=ps_current_detail_height=1;
  CRender renderer;renderer.b_loaded=loaded;renderer.Details=loaded?new CDetailManager:nullptr;renderer.Target=new CRenderTarget;
  auto* original=renderer.Details;loads=unloads=destructions=0;
  if(mask&1)dm_current_size=40;if(mask&2)ps_r__Detail_density=.4f;if(mask&4)ps_r__Detail_height=1.5f;
  renderer.reset_begin();assert(renderer.Target==nullptr);
  if(loaded && mask)assert(renderer.Details==nullptr && unloads==1 && destructions==1);
  renderer.reset_end();assert(renderer.Target && renderer.m_bFirstFrameAfterReset);
  if(loaded){assert(renderer.Details);if(mask)assert(loads==1);else assert(renderer.Details==original && loads==0);}
  else assert(renderer.Details==nullptr && !loads);
  if(loaded){const auto old_loads=loads;renderer.reset_begin();renderer.reset_end();assert(loads==old_loads && renderer.Details);}
  xr_delete(renderer.Target);xr_delete(renderer.Details);
 }
 std::puts("PASS actual R1 reset: height-only/density-only/radius-only/mixed/unchanged, loaded/unloaded, repeated reset, resource destroyed/recreated once; no GPU/game");
}
'''
with TemporaryDirectory(prefix='lz-r1-reset-') as temporary:
 folder=Path(temporary);cpp=folder/'check.cpp';cpp.write_text(code,encoding='utf-8');exe=folder/'check.exe'
 subprocess.run(['cl','/nologo','/EHsc','/std:c++17','/W4','/WX',str(cpp),'/Fe:'+str(exe),'/Fo:'+str(folder/'check.obj')],cwd=folder,check=True)
 subprocess.run([str(exe)],cwd=folder,check=True,timeout=30)
