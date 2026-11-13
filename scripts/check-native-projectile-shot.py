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
#include <cstdio>
using u8=unsigned char;using u16=unsigned short;using u32=unsigned;
using shared_str=std::string;using BOOL=bool;
struct CSE_Abstract{};
struct Fvector{float x=0,y=0,z=0;void set(const Fvector& v){*this=v;}};
struct Cartridge{int m_ammoSect=3;struct {float impair=1;}param_s;};
struct Parent{u16 id=42;u16 ID(){return id;}}parent;
struct Settings{shared_str r_string(int section,const char*){return "fake"+std::to_string(section);}}settings;
Settings* pSettings=&settings;
struct NET_Packet{u16 id=10;void r_u16(u16& out){out=id;}};
namespace netcoop {bool enabled(){return true;}}
class CWeapon{
public:
 std::vector<Cartridge>m_magazine;int iAmmoElapsed=0;Cartridge m_lastCartridge;
 struct{struct{float condition_shot_dec=1;}dummy;}unused;
 struct{float condition_shot_dec=1;}cur_silencer_koef;
 unsigned sounds=0,bullets=0,launches=0;float condition=1;
 virtual ~CWeapon()=default;
 virtual BOOL net_Spawn(CSE_Abstract*){return true;}
 void OnShot(){++sounds;}void FireTrace(const Fvector&,const Fvector&){++bullets;netcoop_consume_projectile();}
 float GetWeaponDeterioration(){return 0.1f;}void ChangeCondition(float change){condition+=change;}
 virtual bool netcoop_fire_shot(u8,const Fvector&,const Fvector&);
 virtual void netcoop_shot_effect(u8);void netcoop_consume_projectile();
};
#define VERIFY(x) assert(x)
struct CRocketLauncher{
 static unsigned spawned;float m_fLaunchSpeed=30;
 void SpawnRocket(int,void*){++spawned;}
 std::vector<shared_str> spawned_sections;
 void SpawnRocket(const shared_str& section,void*){++spawned;spawned_sections.push_back(section);}
 template<class T>void AttachRocket(u16 id,T* weapon){if(id && weapon->attached.insert(id).second)++weapon->rockets;}
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
class CWeaponMagazinedWGrenade:public CWeapon{
 using inherited=CWeapon;
public:
 bool m_bGrenadeMode=false,ready=true;unsigned getRocketCount(){return ready?1:0;}
 void LaunchGrenade(){++launches;netcoop_consume_projectile();}
 bool netcoop_fire_shot(u8,const Fvector&,const Fvector&)override;void netcoop_shot_effect(u8)override;
};
class CWeaponRG6:public CWeapon,public CRocketLauncher{
 using inheritedRL=CRocketLauncher;
 using inheritedSG=CWeapon;
public:
 bool m_netcoop_launch_pending=false,server=true,destroyed=false;
 u32 m_netcoop_rockets_spawning=0,rockets=0;std::set<u16> attached;
 u16 m_netcoop_launch_owner=65535;float m_netcoop_launch_speed=0;
 Fvector m_netcoop_launch_pos,m_netcoop_launch_dir,last_pos,last_dir;
 Parent* owner=&parent;
 Parent* H_Parent(){return owner;}bool OnServer(){return server;}bool getDestroy(){return destroyed;}
 u32 getRocketCount(){return rockets;}
 void* getCurrentRocket(){return rockets?this:nullptr;}
 BOOL net_Spawn(CSE_Abstract*)override;
 bool netcoop_launch_grenade(const Fvector& pos,const Fvector& dir,float speed){
  assert(rockets&&speed==30);--rockets;++launches;last_pos=pos;last_dir=dir;return true;
 }
 bool netcoop_fire_shot(u8,const Fvector&,const Fvector&)override;
 void netcoop_shot_effect(u8)override;
 void netcoop_finish_pending_launch();void take(NET_Packet&);
};
'''
for path,signatures in (
 ('src/xrGame/WeaponFire.cpp',('bool CWeapon::netcoop_fire_shot(','void CWeapon::netcoop_shot_effect(','void CWeapon::netcoop_consume_projectile(')),
 ('src/xrGame/WeaponRPG7.cpp',('bool CWeaponRPG7::netcoop_fire_shot(','void CWeaponRPG7::netcoop_shot_effect(')),
 ('src/xrGame/WeaponMagazinedWGrenade.cpp',('bool CWeaponMagazinedWGrenade::netcoop_fire_shot(','void CWeaponMagazinedWGrenade::netcoop_shot_effect(')),
 ('src/xrGame/WeaponRG6.cpp',('BOOL CWeaponRG6::net_Spawn(','bool CWeaponRG6::netcoop_fire_shot(','void CWeaponRG6::netcoop_finish_pending_launch(','void CWeaponRG6::netcoop_shot_effect('))):
    source+='\n'+'\n'.join(method(path,s)for s in signatures)
rg6=(root/'src/xrGame/WeaponRG6.cpp').read_text(encoding='utf-8')
take=rg6[rg6.index('case GE_OWNERSHIP_TAKE:'):rg6.index('case GE_OWNERSHIP_REJECT:')]
source+='\nvoid CWeaponRG6::take(NET_Packet& P){u16 id;switch(1){'+take.replace('case GE_OWNERSHIP_TAKE:','case 1:')+'}}\n'
spawn=method('src/xrGame/WeaponRG6.cpp','BOOL CWeaponRG6::net_Spawn(')
assert spawn.index('m_netcoop_rockets_spawning = 0') < spawn.index('inheritedSG::net_Spawn(DC)')
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
 pos.x=2;dir.z=1;
 CWeaponRG6 rg6;rg6.iAmmoElapsed=2;rg6.m_magazine.resize(2);rg6.rockets=1;
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
 mixed.m_magazine[0].m_ammoSect=12;mixed.m_magazine[1].m_ammoSect=34;
 assert(mixed.net_Spawn(nullptr));
 assert(mixed.m_netcoop_rockets_spawning==2&&mixed.spawned_sections.size()==2);
 assert(mixed.spawned_sections[0]=="fake12"&&mixed.spawned_sections[1]=="fake34");
 std::puts("PASS actual RG6 delayed shot: one spawn/reservation/dose, arrival launches once with saved aim, pre-existing spawn retained, owner/drop/destroy/client cancellation");
 std::puts("PASS actual weapon dispatch: projectile class/mode validation, no hitscan or duplicate launch, one cartridge, asynchronous RPG reservation, single grenade effects");
}
'''
with TemporaryDirectory() as tmp:
 cpp=Path(tmp)/'weapon.cpp';exe=Path(tmp)/('weapon.exe' if os.name=='nt' else 'weapon');cpp.write_text(source)
 command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
          ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(exe)])
 subprocess.run(command,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
