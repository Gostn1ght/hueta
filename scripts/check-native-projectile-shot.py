"""Actual weapon dispatch methods with engine boundaries mocked; GHA only."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os, subprocess
if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
def method(path,signature):
    text=(root/path).read_text(encoding='utf-8');start=text.index(signature);brace=text.index('{',start);depth=1;end=brace+1
    while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]
source=r'''
#include <cassert>
#include <vector>
#include <set>
#include <string>
#include <list>
#include <algorithm>
#include <cstdio>
using u8=unsigned char;using u16=unsigned short;using u32=unsigned;
using shared_str=std::string;using BOOL=bool;using LPCSTR=const char*;
#define CROCKETLAUNCHER_CHANGE
#define READ_IF_EXISTS(ini,method,section,key,fallback) ((ini)->line_exist(section,key)?(ini)->method(section,key):fallback)
struct CSE_Abstract{};
struct Fvector{float x=0,y=0,z=0;void set(const Fvector& v){*this=v;}};
struct Cartridge{shared_str m_ammoSect="3";struct {float impair=1;}param_s;};
struct Parent{u16 id=42;u16 ID(){return id;}}parent;
using CActor=Parent;
template<class T>T smart_cast(Parent* value){return static_cast<T>(value);}
struct {u32 dwTimeGlobal=100;}Device;
int fixture_scope_depth=0;
struct Settings{
 shared_str r_string(const shared_str& section,const char*){return "fake"+section;}
 bool line_exist(LPCSTR,LPCSTR){return true;}
 float r_float(LPCSTR section,LPCSTR){return std::string(section)=="34"?90.f:30.f;}
}settings;
Settings* pSettings=&settings;
struct NET_Packet{u16 id=10;void r_u16(u16& out){out=id;}};
namespace netcoop {
 bool enabled(){return true;}
 struct ServerVictimScope{explicit ServerVictimScope(CActor* value){assert(value);++fixture_scope_depth;}~ServerVictimScope(){--fixture_scope_depth;}};
}
class CWeapon{
public:
 std::vector<Cartridge>m_magazine;int iAmmoElapsed=0;Cartridge m_lastCartridge;
 struct{struct{float condition_shot_dec=1;}dummy;}unused;
 struct{float condition_shot_dec=1;}cur_silencer_koef;
 unsigned sounds=0,bullets=0,launches=0;float condition=1;
 int last_scope=0;Fvector m_netcoop_aim_pos,m_netcoop_aim_dir;u32 m_netcoop_aim_time=0;
 virtual ~CWeapon()=default;
 virtual BOOL net_Spawn(CSE_Abstract*){return true;}
 void OnShot(){++sounds;last_scope=fixture_scope_depth;}void FireTrace(const Fvector&,const Fvector&){++bullets;netcoop_consume_projectile();}
 float GetWeaponDeterioration(){return 0.1f;}void ChangeCondition(float change){condition+=change;}
 virtual bool netcoop_fire_shot(u8,const Fvector&,const Fvector&);
 virtual void netcoop_shot_effect(u8);void netcoop_consume_projectile();
};
#define VERIFY(x) assert(x)
struct CRocketLauncher{
 struct Rocket{shared_str section;const shared_str& cNameSect(){return section;}};
 std::list<Rocket> fixture_rockets;std::vector<Rocket*> m_rockets;
 static unsigned spawned;float m_fLaunchSpeed=30;
 void SpawnRocket(int,void*){++spawned;}
 std::vector<shared_str> spawned_sections;
 void SpawnRocket(const shared_str& section,void*){++spawned;spawned_sections.push_back(section);}
 template<class T>void AttachRocket(u16 id,T* weapon){if(id && weapon->attached.insert(id).second)weapon->fixture_load(weapon->next_section);}
};unsigned CRocketLauncher::spawned=0;
class CWeaponRPG7:public CWeapon,public CRocketLauncher{
public:
 bool m_netcoop_rocket_spawning=false,m_netcoop_launch_pending=false,ready=true;
 u16 m_netcoop_launch_owner=0;Fvector m_netcoop_launch_pos,m_netcoop_launch_dir;int m_sRocketSection=0;
 Parent* H_Parent(){return &parent;}unsigned getRocketCount(){return ready?1:0;}
 bool netcoop_launch_rocket(const Fvector&,const Fvector&){++launches;return ready;}
 void UpdateMissileVisibility(){}
 bool netcoop_fire_shot(u8,const Fvector&,const Fvector&)override;void netcoop_shot_effect(u8)override;
};
class CWeaponMagazinedWGrenade:public CWeapon,public CRocketLauncher{
 using inherited=CWeapon;
public:
 bool m_bGrenadeMode=false,server=true,destroyed=false;
 bool m_netcoop_grenade_pending=false,m_netcoop_grenade_spawning=false;
 u16 m_netcoop_grenade_owner=65535;shared_str m_netcoop_grenade_ammo,next_section="fake3",last_section;
 Fvector m_netcoop_grenade_pos,m_netcoop_grenade_dir,last_pos,last_dir;
 std::set<u16>attached;Parent* owner=&parent;
 CWeaponMagazinedWGrenade(){fixture_load("fake3");}
 void fixture_load(const shared_str& section){fixture_rockets.push_back({section});m_rockets.push_back(&fixture_rockets.back());}
 unsigned getRocketCount(){return unsigned(m_rockets.size());}
 Parent*H_Parent(){return owner;}bool OnServer(){return server;}bool getDestroy(){return destroyed;}
 void LaunchGrenade(){assert(!m_rockets.empty());last_section=m_rockets.back()->section;m_rockets.pop_back();
  last_pos=m_netcoop_aim_pos;last_dir=m_netcoop_aim_dir;++launches;netcoop_consume_projectile();}
 void netcoop_spawn_grenade(const shared_str&);bool netcoop_select_grenade(const shared_str&);
 void netcoop_finish_pending_grenade();void take(NET_Packet&);
 bool netcoop_fire_shot(u8,const Fvector&,const Fvector&)override;void netcoop_shot_effect(u8)override;
};
class CWeaponRG6:public CWeapon,public CRocketLauncher{
 using inheritedRL=CRocketLauncher;
 using inheritedSG=CWeapon;
public:
 bool m_netcoop_launch_pending=false,server=true,destroyed=false;
 u32 m_netcoop_rockets_spawning=0;std::set<u16> attached;
 shared_str m_netcoop_launch_section,next_section="fake3",last_section;
 u16 m_netcoop_launch_owner=65535;float m_netcoop_launch_speed=0;
 Fvector m_netcoop_launch_pos,m_netcoop_launch_dir,last_pos,last_dir;
 Parent* owner=&parent;
 Parent* H_Parent(){return owner;}bool OnServer(){return server;}bool getDestroy(){return destroyed;}
 u32 getRocketCount(){return u32(m_rockets.size());}
 void* getCurrentRocket(){return m_rockets.empty()?nullptr:m_rockets.back();}
 void fixture_load(const shared_str& section){fixture_rockets.push_back({section});m_rockets.push_back(&fixture_rockets.back());}
 bool netcoop_select_grenade(const shared_str&);
 float last_speed=0;
 BOOL net_Spawn(CSE_Abstract*)override;
 bool netcoop_launch_grenade(const Fvector& pos,const Fvector& dir,float speed){
  assert(!m_rockets.empty());last_section=m_rockets.back()->section;m_rockets.pop_back();
  last_speed=speed;++launches;last_pos=pos;last_dir=dir;return true;
 }
 bool netcoop_fire_shot(u8,const Fvector&,const Fvector&)override;
 void netcoop_shot_effect(u8)override;
 void netcoop_finish_pending_launch();void take(NET_Packet&);
};
'''
for path,signatures in (
 ('src/xrGame/WeaponFire.cpp',('bool CWeapon::netcoop_fire_shot(','void CWeapon::netcoop_shot_effect(','void CWeapon::netcoop_consume_projectile(')),
 ('src/xrGame/WeaponRPG7.cpp',('bool CWeaponRPG7::netcoop_fire_shot(','void CWeaponRPG7::netcoop_shot_effect(')),
 ('src/xrGame/WeaponMagazinedWGrenade.cpp',('bool CWeaponMagazinedWGrenade::netcoop_fire_shot(','void CWeaponMagazinedWGrenade::netcoop_shot_effect(',
   'void CWeaponMagazinedWGrenade::netcoop_spawn_grenade(','bool CWeaponMagazinedWGrenade::netcoop_select_grenade(',
   'void CWeaponMagazinedWGrenade::netcoop_finish_pending_grenade(')),
 ('src/xrGame/WeaponRG6.cpp',('BOOL CWeaponRG6::net_Spawn(','bool CWeaponRG6::netcoop_fire_shot(','bool CWeaponRG6::netcoop_select_grenade(','void CWeaponRG6::netcoop_finish_pending_launch(','void CWeaponRG6::netcoop_shot_effect('))):
    source+='\n'+'\n'.join(method(path,s)for s in signatures)
rg6=(root/'src/xrGame/WeaponRG6.cpp').read_text(encoding='utf-8')
take=rg6[rg6.index('case GE_OWNERSHIP_TAKE:'):rg6.index('case GE_OWNERSHIP_REJECT:')]
source+='\nvoid CWeaponRG6::take(NET_Packet& P){u16 id;switch(1){'+take.replace('case GE_OWNERSHIP_TAKE:','case 1:')+'}}\n'
spawn=method('src/xrGame/WeaponRG6.cpp','BOOL CWeaponRG6::net_Spawn(')
assert spawn.index('m_netcoop_rockets_spawning = 0') < spawn.index('inheritedSG::net_Spawn(DC)')
underbarrel=(root/'src/xrGame/WeaponMagazinedWGrenade.cpp').read_text(encoding='utf-8')
under_take=underbarrel[underbarrel.index('case GE_OWNERSHIP_TAKE:'):underbarrel.index('case GE_OWNERSHIP_REJECT:')]
source+='\nvoid CWeaponMagazinedWGrenade::take(NET_Packet& P){u16 id;switch(1){'+under_take.replace('case GE_OWNERSHIP_TAKE:','case 1:')+'}}\n'
under_spawn=method('src/xrGame/WeaponMagazinedWGrenade.cpp','BOOL CWeaponMagazinedWGrenade::net_Spawn(')
assert under_spawn.index('m_netcoop_grenade_pending = m_netcoop_grenade_spawning = false') < under_spawn.index('inherited::net_Spawn(DC)')
launch=method('src/xrGame/WeaponMagazinedWGrenade.cpp','void CWeaponMagazinedWGrenade::LaunchGrenade()')
assert 'm_magazine.back().m_ammoSect.c_str()' in launch and 'm_magazine.empty()' in launch
source+=r'''
int main(){
 Fvector pos,dir;CWeapon rifle;rifle.iAmmoElapsed=1;rifle.m_magazine.resize(1);
 assert(!rifle.netcoop_fire_shot(1,pos,dir)&&rifle.sounds==0&&rifle.iAmmoElapsed==1);
 assert(rifle.netcoop_fire_shot(0,pos,dir)&&rifle.bullets==1&&rifle.sounds==1&&rifle.iAmmoElapsed==0);
 CWeaponRPG7 rpg;rpg.iAmmoElapsed=1;rpg.m_magazine.resize(1);
 assert(!rpg.netcoop_fire_shot(0,pos,dir)&&rpg.iAmmoElapsed==1);
 assert(rpg.netcoop_fire_shot(1,pos,dir)&&rpg.launches==1&&rpg.bullets==0&&rpg.sounds==1&&rpg.iAmmoElapsed==0);
 assert(!rpg.netcoop_fire_shot(1,pos,dir)&&rpg.launches==1);
 CWeaponRPG7 fresh;fresh.ready=false;fresh.iAmmoElapsed=1;fresh.m_magazine.resize(1);
 assert(fresh.netcoop_fire_shot(1,pos,dir)&&fresh.m_netcoop_launch_pending&&CRocketLauncher::spawned==1);
 assert(fresh.iAmmoElapsed==0&&!fresh.netcoop_fire_shot(1,pos,dir)&&CRocketLauncher::spawned==1);
 CWeaponMagazinedWGrenade gl;gl.iAmmoElapsed=1;gl.m_magazine.resize(1);
 assert(!gl.netcoop_fire_shot(2,pos,dir)&&gl.iAmmoElapsed==1);
 gl.m_bGrenadeMode=true;assert(!gl.netcoop_fire_shot(0,pos,dir));
 assert(gl.netcoop_fire_shot(2,pos,dir)&&gl.bullets==0&&gl.launches==1&&gl.sounds==1&&gl.iAmmoElapsed==0);
 gl.netcoop_shot_effect(2);assert(gl.sounds==1);
 CWeaponMagazinedWGrenade queued;queued.m_rockets.clear();queued.m_bGrenadeMode=true;
 queued.iAmmoElapsed=1;queued.m_magazine.resize(1);Fvector original_pos{2,3,4},original_dir{0,1,0};
 assert(queued.netcoop_fire_shot(2,original_pos,original_dir));
 assert(queued.m_netcoop_grenade_pending&&queued.m_netcoop_grenade_spawning&&queued.iAmmoElapsed==1&&queued.sounds==0);
 assert(queued.spawned_sections.size()==1&&!queued.netcoop_fire_shot(2,original_pos,original_dir));
 queued.netcoop_spawn_grenade("fake3");assert(queued.spawned_sections.size()==1);
 queued.m_netcoop_aim_pos={9,9,9};queued.m_netcoop_aim_dir={1,0,0};
 NET_Packet under_arrival;queued.take(under_arrival);
 assert(!queued.m_netcoop_grenade_pending&&!queued.m_netcoop_grenade_spawning&&queued.iAmmoElapsed==0);
 assert(queued.sounds==1&&queued.launches==1&&queued.last_pos.x==2&&queued.last_dir.y==1);
 assert(queued.last_scope==1&&fixture_scope_depth==0);
 queued.netcoop_finish_pending_grenade();assert(queued.launches==1&&queued.sounds==1);
 for(int cancel=0;cancel<6;++cancel){
  CWeaponMagazinedWGrenade cancelled;cancelled.m_rockets.clear();cancelled.m_bGrenadeMode=true;
  cancelled.iAmmoElapsed=1;cancelled.m_magazine.resize(1);
  assert(cancelled.netcoop_fire_shot(2,original_pos,original_dir));
  Parent other_holder;other_holder.id=43;
  if(cancel==0)cancelled.owner=&other_holder;
  if(cancel==1)cancelled.owner=nullptr;
  if(cancel==2)cancelled.destroyed=true;
  if(cancel==3)cancelled.server=false;
  if(cancel==4)cancelled.m_bGrenadeMode=false;
  if(cancel==5)cancelled.m_magazine.back().m_ammoSect="34";
  cancelled.take(under_arrival);
  assert(!cancelled.m_netcoop_grenade_pending&&cancelled.launches==0&&cancelled.iAmmoElapsed==1&&cancelled.sounds==0);
 }
 CWeaponMagazinedWGrenade wrong;wrong.m_rockets.clear();wrong.m_bGrenadeMode=true;
 wrong.iAmmoElapsed=1;wrong.m_magazine.resize(1);wrong.m_netcoop_grenade_spawning=true;
 assert(wrong.netcoop_fire_shot(2,original_pos,original_dir)&&wrong.spawned_sections.empty());
 wrong.next_section="fake12";under_arrival.id=12;wrong.take(under_arrival);
 assert(wrong.launches==0&&wrong.m_netcoop_grenade_pending&&wrong.spawned_sections.size()==1);
 wrong.next_section="fake3";under_arrival.id=3;wrong.take(under_arrival);
 assert(wrong.launches==1&&wrong.last_section=="fake3"&&wrong.iAmmoElapsed==0&&wrong.sounds==1);
 std::puts("PASS actual underbarrel async shot: reserved aim/actor, one child and cartridge, repeat refusal, mode/ammo/owner cancellation and wrong-type arrival recovery");
 pos.x=2;dir.z=1;
 CWeaponRG6 rg6;rg6.iAmmoElapsed=2;rg6.m_magazine.resize(2);rg6.fixture_load("fake3");
 assert(rg6.netcoop_fire_shot(1,pos,dir)&&rg6.launches==1&&rg6.iAmmoElapsed==1&&rg6.sounds==1);
 CWeaponRG6 waiting;waiting.iAmmoElapsed=2;waiting.m_magazine.resize(2);
 const auto before_spawn=CRocketLauncher::spawned;
 assert(!waiting.netcoop_fire_shot(0,pos,dir));
 assert(waiting.netcoop_fire_shot(1,pos,dir));
 assert(waiting.m_netcoop_launch_pending&&waiting.iAmmoElapsed==1&&waiting.launches==0&&waiting.sounds==1);
 assert(CRocketLauncher::spawned==before_spawn+1&&waiting.m_netcoop_rockets_spawning==1);
 assert(!waiting.netcoop_fire_shot(1,pos,dir)&&waiting.iAmmoElapsed==1);
 waiting.netcoop_finish_pending_launch();assert(waiting.m_netcoop_launch_pending);
 NET_Packet arrival;waiting.take(arrival);
 assert(!waiting.m_netcoop_launch_pending&&waiting.launches==1&&waiting.iAmmoElapsed==1&&waiting.sounds==1);
 assert(waiting.last_pos.x==2&&waiting.last_dir.z==1&&waiting.m_netcoop_rockets_spawning==0);
 waiting.netcoop_finish_pending_launch();assert(waiting.launches==1);
 CWeaponRG6 loading;loading.iAmmoElapsed=1;loading.m_magazine.resize(1);loading.m_netcoop_rockets_spawning=1;
 assert(loading.netcoop_fire_shot(1,pos,dir)&&CRocketLauncher::spawned==before_spawn+1);
 loading.take(arrival);assert(loading.launches==1&&loading.iAmmoElapsed==0);
 Parent another;another.id=43;
 for(int cancel=0;cancel<4;++cancel){
  CWeaponRG6 changed;changed.iAmmoElapsed=1;changed.m_magazine.resize(1);
  assert(changed.netcoop_fire_shot(1,pos,dir));
  if(cancel==0)changed.owner=&another;
  if(cancel==1)changed.owner=nullptr;
  if(cancel==2)changed.destroyed=true;
  if(cancel==3)changed.server=false;
  changed.take(arrival);assert(!changed.m_netcoop_launch_pending&&changed.launches==0);
 }
 CWeaponRG6 mixed;mixed.iAmmoElapsed=2;mixed.m_magazine.resize(2);
 mixed.m_magazine[0].m_ammoSect="12";mixed.m_magazine[1].m_ammoSect="34";
 assert(mixed.net_Spawn(nullptr));
 assert(mixed.m_netcoop_rockets_spawning==2&&mixed.spawned_sections.size()==2);
 assert(mixed.spawned_sections[0]=="fake12"&&mixed.spawned_sections[1]=="fake34");
 // A wrong-type creation arrives first. It must not satisfy the reserved shot.
 assert(mixed.netcoop_fire_shot(1,pos,dir)&&mixed.m_netcoop_launch_pending);
 mixed.next_section="fake12";arrival.id=12;mixed.take(arrival);
 assert(mixed.launches==0&&mixed.m_netcoop_launch_pending&&mixed.iAmmoElapsed==1);
 mixed.next_section="fake34";arrival.id=34;mixed.take(arrival);
 assert(mixed.launches==1&&mixed.last_section=="fake34"&&mixed.last_speed==90.f&&mixed.iAmmoElapsed==1);
 assert(mixed.netcoop_fire_shot(1,pos,dir)&&mixed.last_section=="fake12"&&mixed.iAmmoElapsed==0);
 assert(mixed.sounds==2&&mixed.spawned_sections.size()==2);
 // A stale reload's final outstanding creation must not strand the new type.
 CWeaponRG6 stale;stale.iAmmoElapsed=1;stale.m_magazine.resize(1);stale.m_netcoop_rockets_spawning=1;
 assert(stale.netcoop_fire_shot(1,pos,dir));
 stale.next_section="fake12";arrival.id=12;stale.take(arrival);
 assert(stale.launches==0&&stale.spawned_sections.size()==1&&stale.spawned_sections[0]=="fake3");
 stale.netcoop_finish_pending_launch();assert(stale.spawned_sections.size()==1);
 stale.next_section="fake3";arrival.id=3;stale.take(arrival);
 assert(stale.launches==1&&stale.last_section=="fake3"&&!stale.m_netcoop_launch_pending);
 // Selection follows the cartridge even when the wrong type is last.
 CWeaponRG6 reordered;reordered.iAmmoElapsed=1;reordered.m_magazine.resize(1);
 reordered.fixture_load("fake3");reordered.fixture_load("fake12");
 assert(reordered.netcoop_fire_shot(1,pos,dir)&&reordered.last_section=="fake3");
 assert(reordered.getRocketCount()==1&&reordered.m_rockets.back()->section=="fake12");
 std::puts("PASS actual RG6 mixed cylinder: typed selection, exact cartridge speed, reversed creation order and stale reload recovery without duplicate spawn");
 std::puts("PASS actual RG6 delayed shot: one spawn/reservation/dose, arrival launches once with saved aim, pre-existing spawn retained, owner/drop/destroy/client cancellation");
 std::puts("PASS actual weapon dispatch: projectile class/mode validation, no hitscan or duplicate launch, one cartridge, asynchronous RPG reservation, single grenade effects");
}
'''
with TemporaryDirectory() as tmp:
 cpp=Path(tmp)/'weapon.cpp';exe=Path(tmp)/('weapon.exe' if os.name=='nt' else 'weapon');cpp.write_text(source)
 command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
          ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(exe)])
 subprocess.run(command,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
