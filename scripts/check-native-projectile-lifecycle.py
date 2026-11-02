"""CI-only actual projectile attachment/detachment and high-speed snapshot policy."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess
if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
def method(path,signature):
    s=(root/path).read_text(encoding='utf-8');a=s.index(signature);b=s.index('{',a);depth=1;e=b+1
    while depth:depth+=(s[e]=='{')-(s[e]=='}');e+=1
    return s[a:e]
rocket='src/xrGame/RocketLauncher.cpp'
native=method(rocket,'void CRocketLauncher::AttachRocket(')+'\n'+method(rocket,'void CRocketLauncher::DetachRocket(')
native+='\n'+method('src/xrGame/PhysicsShellHolder.cpp','static bool netcoop_physics_discontinuous(')
missile=(root/'src/xrGame/Missile.cpp').read_text(encoding='utf-8')
start=missile.index('case GE_OWNERSHIP_TAKE:',missile.index('void CMissile::OnEvent('))
take=missile[start:missile.index('case GE_OWNERSHIP_REJECT:',start)]
take=take.replace('case GE_OWNERSHIP_TAKE:','case 1:')
native+='\nvoid CMissile::take(NET_Packet& P) {u16 id;switch(1){'+take+'}}\n'
fire=method('src/xrGame/WeaponRG6.cpp','void CWeaponRG6::FireStart()')
# The real input gate and network dispatch; legacy ballistic code is exercised
# separately by the complete production build.
native+='\n'+fire[:fire.index('#ifdef CROCKETLAUNCHER_CHANGE')]+'\n}\n}\n'
source=r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <map>
#include <vector>
using u16=unsigned short;using u32=unsigned;using LPCSTR=const char*;
#define VERIFY(v) assert(v)
template<class...T>void Msg(LPCSTR,T...){}
struct Fvector{float x=0,y=0,z=0;void set(const Fvector&v){*this=v;}};
struct SPHNetState{Fvector position,linear_vel;};
struct CObject{virtual~CObject()=default;u16 fixture_id=1;bool destroyed=false;
 u16 ID(){return fixture_id;}bool getDestroy(){return destroyed;}};
struct CGameObject:CObject{CGameObject*parent=nullptr;unsigned detach=0;Fvector position;
 CGameObject*H_Parent(){return parent;}CGameObject*H_Root(){return parent?parent:this;}
 void H_SetParent(CGameObject*p){if(parent&&!p)++detach;parent=p;}Fvector&Position(){return position;}};
struct CCustomRocket:CGameObject{CGameObject*m_pOwner=nullptr;bool m_bLaunched=false;};
template<class T>T smart_cast(CObject*p){return dynamic_cast<T>(p);}
struct Objects{std::map<u16,CObject*>values;CObject*net_Find(u16 id){auto i=values.find(id);return i==values.end()?nullptr:i->second;}};
struct World{::Objects Objects;}world;World&Level(){return world;}
struct CRocketLauncher{using ROCKETIT=std::vector<CCustomRocket*>::iterator;
 std::vector<CCustomRocket*>m_rockets,m_launched_rockets;
 void AttachRocket(u16,CGameObject*);void DetachRocket(u16,bool);};
bool authority=true;bool OnServer(){return authority;}
struct NET_Packet{u16 id=0;void r_u16(u16&v){v=id;}};
struct CMissile:CGameObject{CMissile*m_fake_missile=nullptr;bool m_netcoop_throw_pending=false;unsigned throws=0;
 void netcoop_server_throw(){++throws;}void take(NET_Packet&);};
namespace netcoop{bool on=true,client=true;bool enabled(){return on;}bool pure_client(){return client;}bool server_player_copy(CObject*){return !client;}}
struct Shotgun{unsigned started=0;void FireStart(){++started;}};
constexpr int eIdle=0;
struct CWeaponRG6:Shotgun{using inheritedSG=Shotgun;int state=0,iAmmoElapsed=1;unsigned rockets=0;bool actor=true;CGameObject parent;
 int GetState(){return state;}unsigned getRocketCount(){return rockets;}bool ParentIsActor(){return actor;}
 CGameObject*H_Parent(){return &parent;}void FireStart();};
'''+native+r'''
int main(){
 CGameObject owner;CCustomRocket rocket;rocket.fixture_id=2;world.Objects.values[u16(2)]=&rocket;
 CRocketLauncher launcher;launcher.AttachRocket(99,&owner);assert(launcher.m_rockets.empty());
 launcher.AttachRocket(2,&owner);launcher.AttachRocket(2,&owner);assert(launcher.m_rockets.size()==1);
 launcher.m_launched_rockets.push_back(&rocket);launcher.DetachRocket(2,true);
 assert(rocket.detach==1&&rocket.m_bLaunched&&launcher.m_rockets.empty()&&launcher.m_launched_rockets.empty());
 launcher.DetachRocket(2,true);assert(rocket.detach==1);
 rocket.parent=&owner;launcher.m_launched_rockets.push_back(&rocket);launcher.DetachRocket(2,true);
 assert(rocket.detach==2&&launcher.m_launched_rockets.empty());
 rocket.parent=&owner;launcher.m_rockets.push_back(&rocket);launcher.DetachRocket(2,false);
 assert(rocket.detach==3&&!rocket.m_bLaunched&&launcher.m_rockets.empty());
 launcher.DetachRocket(99,true);
 CMissile held,child;held.fixture_id=3;child.fixture_id=4;world.Objects.values[u16(4)]=&child;
 NET_Packet packet;packet.id=99;held.take(packet);assert(!held.m_fake_missile);
 packet.id=4;held.m_netcoop_throw_pending=true;held.take(packet);assert(held.m_fake_missile==&child&&child.parent==&held&&held.throws==1);
 // 15 metres per snapshot is normal at 300 m/s. A genuine relocation
 // with no matching velocity still resets interpolation immediately.
 SPHNetState a,b;a.linear_vel.z=b.linear_vel.z=300;b.position.z=15;
 assert(!netcoop_physics_discontinuous(a,b,50));
 b.position.z=30;assert(netcoop_physics_discontinuous(a,b,50));
 a.linear_vel={0,0,0};b.linear_vel={0,0,0};b.position.z=4;
 assert(netcoop_physics_discontinuous(a,b,50));
 // Analytic ballistic trajectory over several server frame intervals.
 for(u32 ms:{50u,100u,250u,500u}){
  const float t=float(ms)/1000.f;a.position={0,1,0};a.linear_vel={0,8,90};
  b.position={0,1+8*t-4.905f*t*t,90*t};b.linear_vel={0,8-9.81f*t,90};
  assert(!netcoop_physics_discontinuous(a,b,ms));
 }
 CWeaponRG6 rg6;rg6.FireStart();assert(rg6.started==1); // zero child replicas on the client
 rg6.iAmmoElapsed=0;rg6.FireStart();assert(rg6.started==1);
 netcoop::on=false;rg6.iAmmoElapsed=1;rg6.FireStart();assert(rg6.started==1);
 rg6.rockets=1;rg6.FireStart();assert(rg6.started==2);
 std::puts("PASS actual projectile lifecycle: missing/duplicate attach, either/both rocket lists, one detach, repeated event, missing missile, loaded client without child replica, fast and ballistic snapshots versus true teleport");
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'projectile.cpp';exe=Path(tmp)/('projectile.exe' if os.name=='nt' else 'projectile')
    cpp.write_text(source,encoding='utf-8')
    cmd=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
         ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(cmd,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
