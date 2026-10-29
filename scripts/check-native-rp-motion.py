"""CI: actual RP item selection and partition playback, including the zero-speed regression."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
text = (root / 'src/xrGame/ActorAnimation.cpp').read_text(encoding='utf-8')
selectors = text[text.index('static bool rp_weapon_matches('):text.index('void CActor::rp_attach_item(')]
walk = text[text.index('void CActor::rp_walk('):text.index('void CActor::rp_request_stop(')]
source = r'''
#include <cassert>
#include <map>
#include <vector>
#include <string>
#include <cstdio>
using u8=unsigned char;using u16=unsigned short;using u32=unsigned;
using shared_str=std::string;
constexpr u16 NO_ACTIVE_SLOT=65535,BI_NONE=65535;
constexpr bool TRUE=true,FALSE=false;
constexpr u32 mcFwd=1,mcBack=2,mcLStrafe=4,mcRStrafe=8;
template<class T,class U>T smart_cast(U* value){return dynamic_cast<T>(value);}
struct Item{virtual ~Item()=default;shared_str section;Item& object(){return *this;}const shared_str& cNameSect(){return section;}};
using PIItem=Item*;
struct CWeapon:Item{int GetAmmoMagSize(){return capacity;}int capacity=30;};
struct CWeaponPistol:CWeapon{};struct CWeaponKnife:CWeapon{};
struct CInventory{
 std::map<u16,PIItem> slots;std::vector<PIItem> m_all;u16 active=NO_ACTIVE_SLOT;
 PIItem ItemFromSlot(u16 slot){auto i=slots.find(slot);return i==slots.end()?nullptr:i->second;}
 PIItem ActiveItem(){return ItemFromSlot(active);}u16 GetActiveSlot(){return active;}
 u16 FirstSlot(){return 0;}u16 LastSlot(){return 15;}
};
namespace netcoop{struct RpAnim{u8 weapon=0,slot=0;std::vector<shared_str>items,legs,torso;};}
struct MotionID{int id=-1;bool valid()const{return id>=0;}bool operator!=(MotionID o)const{return id!=o.id;}};
struct CMotionDef{float Accrue(){return .2f;}float Falloff(){return .1f;}float Speed(){return 1.25f;}};
struct CBlend{};
struct IKinematicsAnimated{
 virtual ~IKinematicsAnimated()=default;
 std::map<std::string,MotionID> motions;CMotionDef definition;CBlend blend;
 struct Call{u16 part;MotionID id;float speed;bool once;};std::vector<Call> calls;
 bool fail=false,missing_part=false;
 MotionID ID_Cycle_Safe(const char* name){auto i=motions.find(name);return i==motions.end()?MotionID{}:i->second;}
 u16 LL_PartID(const char* name){return missing_part?BI_NONE:std::string(name)=="legs"?0:1;}
 CMotionDef* LL_GetMotionDef(MotionID){return &definition;}
 CBlend* LL_PlayCycle(u16 part,MotionID id,bool,float,float,float speed,bool once,void*,void*){
  calls.push_back({part,id,speed,once});return fail?nullptr:&blend;
 }
};
struct CActor{IKinematicsAnimated* model=nullptr;MotionID m_rp_walk_legs,m_rp_walk_torso;
 IKinematicsAnimated* Visual(){return model;}void rp_walk(const netcoop::RpAnim&,u32);};
''' + selectors + walk + r'''
int main(){
 CInventory inventory;CWeapon rifle;CWeaponPistol pistol;CWeaponKnife knife;Item device,food;
 rifle.section="rifle";pistol.section="pistol";food.section="bread";
 netcoop::RpAnim pose;pose.weapon=2;pose.slot=3;
 inventory.slots[3]=&rifle;inventory.slots[2]=&pistol;inventory.active=3;
 assert(rp_weapon_slot(inventory,pose)==2);
 inventory.slots[2]=&device;assert(rp_weapon_slot(inventory,pose)==NO_ACTIVE_SLOT);
 inventory.slots[2]=&knife;assert(rp_weapon_slot(inventory,pose)==NO_ACTIVE_SLOT);
 inventory.slots[8]=&pistol;assert(rp_weapon_slot(inventory,pose)==8);
 pose.weapon=1;assert(rp_weapon_slot(inventory,pose)==3);
 inventory.active=8;assert(rp_weapon_slot(inventory,pose)==3);
 rifle.capacity=0;assert(rp_weapon_slot(inventory,pose)==NO_ACTIVE_SLOT);
 pose.weapon=0;assert(rp_weapon_slot(inventory,pose)==NO_ACTIVE_SLOT);
 assert(rp_has_item(inventory,pose));pose.items={"kolbasa","bread"};
 assert(!rp_has_item(inventory,pose));inventory.m_all={&device,&food};assert(rp_has_item(inventory,pose));
 pose.items={"vodka"};assert(!rp_has_item(inventory,pose));
 IKinematicsAnimated model;CActor actor;actor.model=&model;
 pose.legs={"fwd","back","left","right","idle"};pose.torso={"pose_walk","pose_idle"};
 for(int n=0;n<5;++n)model.motions[pose.legs[n]]={n};
 model.motions["pose_walk"]={5};model.motions["pose_idle"]={6};
 for(u32 move:{mcFwd,mcBack,mcLStrafe,mcRStrafe,0u}){
  const auto before=model.calls.size();actor.rp_walk(pose,move);
  assert(model.calls.size()>before);
  for(const auto& call:model.calls){assert(call.part<=1&&call.speed>0&&!call.once);}
  const auto after=model.calls.size();actor.rp_walk(pose,move);assert(model.calls.size()==after);
 }
 actor.m_rp_walk_legs={};model.fail=true;actor.rp_walk(pose,mcFwd);assert(!actor.m_rp_walk_legs.valid());
 model.fail=false;actor.rp_walk(pose,mcFwd);assert(actor.m_rp_walk_legs.valid());
 actor.m_rp_walk_legs={};model.missing_part=true;auto before=model.calls.size();actor.rp_walk(pose,mcFwd);assert(model.calls.size()==before);
 actor.model=nullptr;actor.rp_walk(pose,mcFwd);
 std::puts("PASS actual RP selection: either weapon slot, pistol/rifle/knife/device distinctions, rucksack requirements; actual walking partitions: positive speed, loops, direction changes, no restarts, failed blend retried");
}
'''
with TemporaryDirectory(prefix='rp-motion-') as temporary:
    folder = Path(temporary)
    cpp, exe = folder / 'rp.cpp', folder / ('rp.exe' if os.name == 'nt' else 'rp')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)]
               if os.name == 'nt' else ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
