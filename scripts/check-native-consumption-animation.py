"""CI-only actual observer animation methods and bounded server vocabulary;
New Way's third-person motion and item for an item that has them."""
import importlib.util
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT/'src/xrGame/ActorAnimation.cpp').read_text(encoding='utf-8')
start = text.index('void CActor::netcoop_consumption_end(')
stop = text.index('void CActor::g_SetAnimation(', start)

# The actual shipped animation set must contain every referenced clip; no
# success stub or assumed/imaginary motion names.
spec = importlib.util.spec_from_file_location('merge', ROOT/'scripts/tools/merge-player-anims.py')
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)
parsed = merge.parse(str(ROOT/'scripts/netcoop-overlay/client/meshes/actors/stalker_animation.omf'))
names = {d['name'] for d in parsed['defs']}
for name in ('medkit','bandage','antirad','energy','universal','vodka'):
    assert 'banka_anim_use_'+name in names
assert [p[0] for p in parsed['parts']] == ['legs','torso','head']

source = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <string>
#include <initializer_list>
#include "netcoop_consumption.h"
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;using s32=int32_t;using LPCSTR=const char*;
constexpr bool TRUE=true,FALSE=false;
template<class T>T _min(T a,T b){return std::min(a,b);}template<class T>T _max(T a,T b){return std::max(a,b);}
bool _valid(float value){return std::isfinite(value);}
struct MotionID{bool exists=false;bool valid()const{return exists;}void invalidate(){exists=false;}};
struct CBlend{void* CallbackParam=nullptr;float timeTotal=2;};
using PlayCallback=void(*)(CBlend*);
struct CMotionDef{float speed=2;float Speed(){return speed;}float Accrue(){return 1;}float Falloff(){return 1;}};
struct VisualBase{virtual ~VisualBase()=default;};
struct IKinematicsAnimated:VisualBase{
 bool has_motion=true,has_torso=true,has_def=true,has_blend=true;unsigned plays=0;CMotionDef def;
 CBlend blends[32];PlayCallback callback=nullptr;u16 last_partition=99;bool last_noloop=false;
 std::string last_motion;
 MotionID ID_Cycle_Safe(LPCSTR name){last_motion=name;assert(last_motion.find("banka_anim_use_")==0||last_motion.find("nw_tp_")==0);return {has_motion};}
 u16 LL_PartID(LPCSTR name){assert(std::string(name)=="torso");return has_torso?1:u16(-1);}
 CMotionDef* LL_GetMotionDef(MotionID){return has_def?&def:nullptr;}
 CBlend* LL_PlayCycle(u16 partition,MotionID,bool,float,float,float,bool noloop,PlayCallback cb,void* actor,u8){
  if(!has_blend)return nullptr;last_partition=partition;last_noloop=noloop;callback=cb;
  assert(plays<32);CBlend& blend=blends[plays++];blend.CallbackParam=actor;return &blend;
 }
};
template<class T,class U>T smart_cast(U* object){return dynamic_cast<T>(object);}
struct CActor{
 bool alive=true,seated=false,m_bAnimTorsoPlayed=false;int m_rp_index=-1;u32 m_netcoop_consumption_until=0;
 MotionID m_current_torso;CBlend* m_current_torso_blend=nullptr;VisualBase* fixture_visual=nullptr;
 bool g_Alive(){return alive;}bool netcoop_seated(){return seated;}VisualBase* Visual(){return fixture_visual;}
 // New Way's data (ActorAnimation.cpp outside this region): the fixture's own
 std::string tp_item,attached;unsigned released=0;
 LPCSTR netcoop_tp_motion(LPCSTR item){return item&&!tp_item.empty()&&tp_item==item?"nw_tp_hud_bread":nullptr;}
 void netcoop_tp_item_attach(LPCSTR item){attached=item?item:"";}void netcoop_tp_item_release(){++released;}
 static void netcoop_consumption_end(CBlend*);void netcoop_play_consumption(u8,LPCSTR);void netcoop_expire_consumption();
};
void netcoop_tp_note(LPCSTR,LPCSTR){}
namespace netcoop{bool client=true;bool pure_client(){return client;}}
struct Runtime{CActor* own=nullptr;CActor* CurrentControlEntity(){return own;}} runtime;
Runtime& Level(){return runtime;}struct {u32 dwTimeGlobal=100;}Device;
'''+text[start:stop]+r'''
int main(){
 using namespace netcoop_consumption;
 assert(kind("bandage_israeli","i_medical")==1&&kind("antirad","i_medical")==2);
 assert(kind("medkit_army","i_medical")==0&&kind("stimpack","i_medical")==0);
 assert(kind("vodka_quality","i_drink")==5&&kind("beer","i_drink")==5&&kind("water_drink","i_drink")==3);
 assert(kind("bread","i_food")==4&&kind("meat_dog","i_mutant_raw")==4&&kind("meat_dog_baked","i_mutant_cooked")==4);
 assert(kind("bolts_pack","i_tool")==255&&kind(nullptr,"i_food")==255&&motion(255)==nullptr);
 unsigned actor=0,action=0;const char* name=nullptr;const char* section=nullptr;
 auto parsed=[&](std::string text){std::string copy=text;return parse(&copy[0],actor,action,name,section)?std::string(name)+"/"+section:std::string("!");};
 assert(parsed("42|1|actor_name|bread")=="actor_name/bread"&&actor==42&&action==1);
 assert(parsed("42|255|actor_name|cigarettes")=="actor_name/cigarettes"&&action==255);
 for(const char* bad:{"","-1|0|a|b","65535|1|a|b","42|256|a|b","42|1||b","42949672960|0|a|b","42|1|a\nb|c","42x|1|a|b","42|+1|a|b",
  "42|1|a","42|1|a|b c","42|1|a|b|c"})
  assert(parsed(bad)=="!");
 std::string long_name="42|1|"+std::string(256,'a')+"|b";assert(parsed(long_name)=="!");
 std::string long_section="42|1|a|"+std::string(128,'b');assert(parsed(long_section)=="!");
 IKinematicsAnimated model;CActor remote,own;remote.fixture_visual=&model;runtime.own=&own;
 remote.netcoop_play_consumption(0,"medkit");
 assert(model.plays==1&&model.last_partition==1&&model.last_noloop);
 assert(model.last_motion=="banka_anim_use_medkit"&&remote.attached=="medkit");
 assert(remote.m_bAnimTorsoPlayed&&remote.m_current_torso.valid());
 const u32 until=remote.m_netcoop_consumption_until;
 Device.dwTimeGlobal=until-1;remote.netcoop_expire_consumption();assert(remote.m_bAnimTorsoPlayed);
 Device.dwTimeGlobal=until;remote.netcoop_expire_consumption();assert(!remote.m_bAnimTorsoPlayed&&!remote.m_current_torso.valid());
 for(u8 index=0;index<6;++index){
  remote.netcoop_play_consumption(index,"");assert(remote.m_bAnimTorsoPlayed);
  model.callback(remote.m_current_torso_blend);assert(!remote.m_bAnimTorsoPlayed&&remote.m_netcoop_consumption_until==0);
 }
 remote.netcoop_play_consumption(0,"");CBlend* previous=remote.m_current_torso_blend;
 remote.netcoop_play_consumption(1,"");model.callback(previous);assert(remote.m_bAnimTorsoPlayed);
 remote.alive=false;remote.netcoop_expire_consumption();assert(!remote.m_bAnimTorsoPlayed);remote.alive=true;
 const auto before=model.plays;
 runtime.own=&remote;remote.netcoop_play_consumption(0,"");assert(model.plays==before);runtime.own=&own;
 netcoop::client=false;remote.netcoop_play_consumption(0,"");netcoop::client=true;
 remote.seated=true;remote.netcoop_play_consumption(0,"");remote.seated=false;
 remote.m_rp_index=1;remote.netcoop_play_consumption(0,"");remote.m_rp_index=-1;
 remote.netcoop_play_consumption(255,"");assert(model.plays==before);
 // an item with New Way's data: their motion, whatever the kind, and the item in the hand
 remote.tp_item="bread";remote.netcoop_play_consumption(255,"bread");
 assert(model.plays==before+1&&model.last_motion=="nw_tp_hud_bread"&&remote.attached=="bread");
 model.callback(remote.m_current_torso_blend);assert(remote.m_netcoop_consumption_until==0&&remote.released>0);
 const auto after_tp=model.plays;
 model.has_motion=false;remote.netcoop_play_consumption(0,"");model.has_motion=true;
 model.has_torso=false;remote.netcoop_play_consumption(0,"");model.has_torso=true;
 model.has_def=false;remote.netcoop_play_consumption(0,"");model.has_def=true;
 model.def.speed=std::numeric_limits<float>::quiet_NaN();remote.netcoop_play_consumption(0,"");model.def.speed=2;
 model.has_blend=false;remote.netcoop_play_consumption(0,"");model.has_blend=true;
 assert(model.plays==after_tp);
 Device.dwTimeGlobal=0xffffff00;remote.netcoop_play_consumption(0,"");
 Device.dwTimeGlobal=remote.m_netcoop_consumption_until;remote.netcoop_expire_consumption();assert(!remote.m_bAnimTorsoPlayed);
 std::puts("PASS actual observer consumption: real clips, New Way's motion and item when the item has them, torso-only one-shot, owner/server exclusions, callbacks/deadline, missing assets and bounded authenticated vocabulary");
}
'''
inventory = (ROOT/'src/xrGame/Inventory.cpp').read_text(encoding='utf-8')
eat = inventory[inventory.index('bool CInventory::Eat('):inventory.index('bool CInventory::ClientEat(')]
assert eat.index('if (!pItemToEat->UseBy(entity_alive))') < eat.index('netcoop::server_item_used(') < eat.index('if (pItemToEat->Empty())')
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native compilation is permitted only in GitHub Actions')
with TemporaryDirectory(prefix='consumption-animation-') as temporary:
    folder = Path(temporary)
    cpp, exe = folder/'consume.cpp', folder/('consume.exe' if os.name == 'nt' else 'consume')
    cpp.write_text(source, encoding='utf-8')
    includes=str(ROOT/'src/xrGame')
    command = (['cl','/nologo','/std:c++17','/EHsc','/W4','/WX','/I'+includes,str(cpp),'/Fe:'+str(exe)] if os.name == 'nt' else
               ['g++','-std=c++17','-Wall','-Wextra','-Werror','-I'+includes,str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=10)
