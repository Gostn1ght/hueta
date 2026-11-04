"""CI-only actual prone selector/playback, including use overlays and recovery."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
text=(root/'src/xrGame/ActorAnimation.cpp').read_text(encoding='utf8')
start=text.index('bool CActor::netcoop_prone_animation(')
code=text[start:text.index('void CActor::netcoop_consumption_end(',start)]
source=r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <map>
#include <string>
#include <vector>
using u16=unsigned short;using u32=unsigned;using LPCSTR=const char*;using string128=char[128];
constexpr bool TRUE=true,FALSE=false;constexpr u16 BI_NONE=65535;
constexpr u32 mcFwd=1,mcBack=2,mcLStrafe=4,mcRStrafe=8,mcAnyMove=15,mcCrouch=16,mcAccel=32,mcClimb=64,mcJump=128,mcFall=256,mcSprint=512;
template<class T>T _min(T a,T b){return std::min(a,b);}template<class T>T _max(T a,T b){return std::max(a,b);}
template<size_t N,class... A>void xr_sprintf(char(&out)[N],LPCSTR format,A...args){std::snprintf(out,N,format,args...);}
void Msg(LPCSTR,...){}void netcoop_tp_note(LPCSTR,LPCSTR){}
struct Fvector{float x=0,y=0,z=0;float magnitude()const{return std::sqrt(x*x+y*y+z*z);}};
bool _valid(float v){return std::isfinite(v);}bool _valid(const Fvector& v){return _valid(v.x)&&_valid(v.y)&&_valid(v.z);}
struct MotionID{int id=-1;bool valid()const{return id>=0;}void invalidate(){id=-1;}bool operator!=(MotionID other)const{return id!=other.id;}};
struct CBlend{float speed=1;};struct CMotionDef{float Speed(){return 1;}};
struct Item{virtual ~Item()=default;};using PIItem=Item*;
struct CWeapon:Item{unsigned slot=2;unsigned animation_slot(){return slot;}};
struct CWeaponPistol:CWeapon{};struct CWeaponKnife:CWeapon{};struct CWeaponBinoculars:CWeapon{};struct CWeaponRPG7:CWeapon{};
template<class T,class U>T smart_cast(U* value){return dynamic_cast<T>(value);}
struct Inventory{PIItem active=nullptr;PIItem ActiveItem(){return active;}};
struct Movement{Fvector velocity{.5f,0,0};const Fvector& GetVelocity(){return velocity;}};
struct PhysicsSupport{Movement value;Movement* movement(){return &value;}};
namespace netcoop{bool client=true;bool pure_client(){return client;}}
struct IKinematicsAnimated{
 virtual ~IKinematicsAnimated()=default;
 std::map<std::string,MotionID> motions;std::string last;CBlend blends[128];unsigned plays=0;bool fail=false,missing_part=false;
 CMotionDef def;
 MotionID ID_Cycle_Safe(LPCSTR name){last=name;auto i=motions.find(name);return i==motions.end()?MotionID{}:i->second;}
 CMotionDef* LL_GetMotionDef(MotionID){return &def;}
 u16 LL_PartID(LPCSTR name){return missing_part?BI_NONE:std::string(name)=="legs"?0:std::string(name)=="torso"?1:2;}
 CBlend* LL_PlayCycle(u16 part,MotionID,bool,float,float,float speed,bool once,void*,void*,int){
  assert(part<3 && !once && speed>0);if(fail)return nullptr;assert(plays<128);auto& result=blends[plays++];result.speed=speed;return &result;
 }
};
struct CActor{
 bool alive=true,seated=false,m_bAnimTorsoPlayed=false;int m_rp_index=-1;
 MotionID m_netcoop_prone_motion,m_current_legs,m_current_torso,m_current_head;
 CBlend* m_netcoop_prone_blends[3]{};CBlend* m_current_legs_blend=nullptr;CBlend* m_current_torso_blend=nullptr;
 bool m_netcoop_prone_torso_free=true;Inventory inv;PhysicsSupport test_physics;
 IKinematicsAnimated* test_model=nullptr;
 Inventory& inventory(){return inv;}bool g_Alive(){return alive;}bool netcoop_seated(){return seated;}
 PhysicsSupport* character_physics_support(){return &test_physics;}
 bool IsZoomAimingMode(){return false;}bool isActorAccelerated(u32 m,bool){return !(m&mcAccel);}
 IKinematicsAnimated* Visual(){return test_model;}unsigned ID(){return 42;}
 bool netcoop_prone_animation(u32);
};
'''+code+r'''
int main(){
 IKinematicsAnimated model;CActor actor;actor.test_model=&model;unsigned id=0;
 for(LPCSTR grip:{"empty","knife","pistol","rifle","launcher"})for(LPCSTR direction:{"idle","fwd","back","left","right"})
  model.motions[std::string("lz_prone_")+grip+"_"+direction]={int(id++)};
 constexpr u32 prone=mcCrouch|mcAccel;
 assert(!actor.netcoop_prone_animation(mcCrouch));
 assert(actor.netcoop_prone_animation(prone|mcFwd) && model.last=="lz_prone_empty_fwd" && model.plays==3);
 auto before=model.plays;assert(actor.netcoop_prone_animation(prone|mcFwd) && model.plays==before);
 CWeapon rifle,generic_pistol;CWeaponPistol pistol;CWeaponKnife knife;CWeaponBinoculars binoculars;CWeaponRPG7 launcher;generic_pistol.slot=1;
 for(auto pair:{std::make_pair(PIItem(&rifle),"rifle"),std::make_pair(PIItem(&generic_pistol),"pistol"),std::make_pair(PIItem(&pistol),"pistol"),std::make_pair(PIItem(&knife),"knife"),std::make_pair(PIItem(&binoculars),"empty"),std::make_pair(PIItem(&launcher),"launcher")}) {
  actor.inv.active=pair.first;assert(actor.netcoop_prone_animation(prone|mcBack));
  assert(model.last==std::string("lz_prone_")+pair.second+"_back");
 }
 for(auto pair:{std::make_pair(mcLStrafe,"left"),std::make_pair(mcRStrafe,"right"),std::make_pair(0u,"idle")}) {
  actor.inv.active=&binoculars;
  assert(actor.netcoop_prone_animation(prone|pair.first));assert(model.last==std::string("lz_prone_empty_")+pair.second);
 }
 actor.inv.active=&launcher;
 for(auto pair:{std::make_pair(mcLStrafe,"left"),std::make_pair(mcRStrafe,"right"),std::make_pair(mcFwd,"fwd"),std::make_pair(0u,"idle")}) {
  assert(actor.netcoop_prone_animation(prone|pair.first));assert(model.last==std::string("lz_prone_launcher_")+pair.second);
 }
 model.motions.erase("lz_prone_launcher_idle");
 assert(actor.netcoop_prone_animation(prone) && model.last=="lz_prone_rifle_idle");
 actor.m_bAnimTorsoPlayed=true;actor.m_current_torso={77};before=model.plays;
 assert(actor.netcoop_prone_animation(prone) && model.plays==before+2 && actor.m_current_torso.id==77);
 actor.m_bAnimTorsoPlayed=false;before=model.plays;assert(actor.netcoop_prone_animation(prone) && model.plays==before+3);
 assert(!actor.netcoop_prone_animation(mcCrouch) && !actor.m_netcoop_prone_motion.valid() && !actor.m_current_legs.valid());
 for(u32 prohibited:{mcClimb,mcJump,mcFall,mcSprint}) assert(!actor.netcoop_prone_animation(prone|prohibited));
 actor.seated=true;assert(!actor.netcoop_prone_animation(prone));actor.seated=false;
 actor.m_rp_index=1;assert(!actor.netcoop_prone_animation(prone));actor.m_rp_index=-1;
 actor.alive=false;assert(!actor.netcoop_prone_animation(prone));actor.alive=true;
 netcoop::client=false;assert(!actor.netcoop_prone_animation(prone));netcoop::client=true;
 model.fail=true;assert(!actor.netcoop_prone_animation(prone));model.fail=false;
 assert(actor.netcoop_prone_animation(prone));actor.netcoop_prone_animation(0);
 model.motions.clear();assert(!actor.netcoop_prone_animation(prone));
 std::puts("PASS actual prone: low stance only, five grips/five directions, RPG-specific grip and legacy-pack fallback, live blend speed, no restart, item-use overlay, exit reset, server/death/seat/RP exclusions, missing clip and failed blend fallback");
}
'''
with TemporaryDirectory(prefix='prone-native-') as temporary:
    folder=Path(temporary);cpp=folder/'prone.cpp';exe=folder/'prone.exe';cpp.write_text(source,encoding='utf8')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)],cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=15)
