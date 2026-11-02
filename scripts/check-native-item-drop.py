"""CI-only drop burst placement and native inventory/activation integration."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess
if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
layout=(root/'src/xrGame/netcoop_drop_layout.h').read_text(encoding='utf-8').replace('#pragma once','')
inventory=(root/'src/xrGame/Inventory.cpp').read_text(encoding='latin-1')
drop=inventory[inventory.index('bool CInventory::DropItem('):inventory.index('bool CInventory::DropItem(')+12000]
assert drop.index('m_netcoop_drop_layout.reserve')<drop.index('m_all.erase(')
assert 'drop_velocity.mul(forward, .45f)' in drop and 'velocity.y += 1.5f' not in drop
assert '!dont_create_shell && drop_actor && drop_actor->g_Alive()' in drop
assert 'drop_holder->netcoop_set_throw(drop_start, drop_velocity)' in drop
shell=(root/'src/xrGame/PhysicsShellHolder.cpp').read_text(encoding='latin-1')
assert 'spin.set(0.12f, 0.06f, 0.18f)' in shell
source=r'''
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
using u32=unsigned;
template<class T>T _min(T a,T b){return a<b?a:b;}
template<class T>T _max(T a,T b){return a>b?a:b;}
bool _valid(float f){return std::isfinite(f);}
struct Fvector{float x=0,y=0,z=0;float distance_to(const Fvector&v)const{return std::sqrt((x-v.x)*(x-v.x)+(y-v.y)*(y-v.y)+(z-v.z)*(z-v.z));}};
'''+layout+r'''
int main(){
 NetcoopDropLayout burst;Fvector origin={10,1,10},forward={0,0,1},out;
 std::vector<Fvector> placed;
 for(int i=0;i<64;++i){
  assert(burst.reserve(100,.08f,origin,forward,out,[](const Fvector&,float){return true;}));
  for(const auto&p:placed)assert(p.distance_to(out)>=.2f-1e-5f);
  assert(out.y==1&&out.z>origin.z);placed.push_back(out);
 }
 // Reset after a quiet half-second; an inventory instance owns its own burst.
 assert(burst.reserve(1000,.08f,origin,forward,out,[](const Fvector&,float){return true;}));
 assert(out.distance_to(placed.front())<1e-5f);
 NetcoopDropLayout other;
 assert(other.reserve(100,.08f,origin,forward,out,[](const Fvector&,float){return true;}));
 assert(out.distance_to(placed.front())<1e-5f);
 // Existing items and walls reject candidate positions before reservation.
 NetcoopDropLayout blocked;
 assert(!blocked.reserve(100,.08f,origin,forward,out,[](const Fvector&,float){return false;}));
 assert(blocked.reserve(100,.08f,origin,forward,out,[](const Fvector&p,float){return p.z>=11.5f;}));
 assert(out.z>=11.5f);
 assert(!blocked.reserve(100,std::numeric_limits<float>::quiet_NaN(),origin,forward,out,[](const Fvector&,float){return true;}));
 // Weapon-sized objects reserve their real footprint instead of tiny grid cells.
 NetcoopDropLayout mixed;std::vector<Fvector> big;
 for(int i=0;i<6;++i){assert(mixed.reserve(10,.5f,origin,forward,out,[](const Fvector&,float){return true;}));
  for(const auto&p:big)assert(p.distance_to(out)>=1.04f-1e-5f);big.push_back(out);}
 // Unsigned clock rollover does not strand reservations forever.
 NetcoopDropLayout wrap;
 assert(wrap.reserve(0xffffff00u,.1f,origin,forward,out,[](const Fvector&,float){return true;}));
 const Fvector first=out;
 assert(wrap.reserve(1000,.1f,origin,forward,out,[](const Fvector&,float){return true;}));
 assert(out.distance_to(first)<1e-5f);
 std::puts("PASS native drop layout: separated 64-item burst, large footprints, wall/existing-body rejection, per-inventory state, timeout/rollover; gentle velocity wired before physical activation");
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'drop.cpp';exe=Path(tmp)/('drop.exe' if os.name=='nt' else 'drop')
    cpp.write_text(source,encoding='utf-8')
    cmd=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
         ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(cmd,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
