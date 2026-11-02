"""CI: serialize the ACTUAL actor owner writer through the ACTUAL host validator."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os, subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
text=(root/'src/xrGame/Actor_Network.cpp').read_text(encoding='utf-8')
writer=text[text.index('void CActor::net_Export(NET_Packet& P)'):text.index('static void w_vec_q8(')]
actor=(root/'src/xrGame/Actor.cpp').read_text(encoding='utf-8')
assert 'm_netcoop_owner_sequence:CL->m_last_processed_sequence' in actor
assert 'netcoop::enabled() && !m_netcoop_owner_sequence_valid' in actor
source=r'''
#include "GammaNetPolicy.h"
#include <cassert>
#include <vector>
#include <deque>
#include <cstdio>
#include <cstring>
#include <limits>
using u8=unsigned char;using u16=unsigned short;using u32=unsigned;
constexpr u32 mcJump=1,kM1InputIntentFlags=65535;
constexpr u16 OUTFIT_SLOT=1,HELMET_SLOT=2;
float angle_normalize(float x){return x;}
struct Fvector {float x=0,y=0,z=0;void set(float a,float b,float c){x=a;y=b;z=c;}};
struct Fmatrix {void invert(const Fmatrix&){}void transform_tiny(Fvector& out,const Fvector& in){out=in;}};
struct NET_Packet {
 std::vector<u8> bytes;
 void w_u8(u8 v){bytes.push_back(v);}void w_u16(u16 v){w_u8(u8(v));w_u8(u8(v>>8));}
 void w_u32(u32 v){for(unsigned i=0;i<4;++i)w_u8(u8(v>>(i*8)));}
 void w_float(float v){u32 x;std::memcpy(&x,&v,4);w_u32(x);}
 void w_vec3(Fvector v){w_float(v.x);w_float(v.y);w_float(v.z);}
 void w_sdir(Fvector v){w_u16(0);w_float(v.x);}
 void w_stringZ(const char* s){while(*s)w_u8(u8(*s++));w_u8(0);}
};
struct ActorInputCommand{u32 sequence,mstate;float yaw,pitch;};
struct CActor;
namespace netcoop{bool enabled(){return true;}bool pure_client(){return true;}bool server_player_copy(CActor*){return false;}u32 real_time_ms(){return 1000;}}
struct Movement{Fvector GetVelocity(){return {};}};
struct Physics{Movement m;Movement*movement(){return &m;}};
struct Item{u16 object_id(){return 5;}};using PIItem=Item*;
struct Inventory{u8 GetActiveSlot(){return 0;}PIItem ActiveItem(){return nullptr;}PIItem ItemFromSlot(u16){return nullptr;}};
struct Object{Fmatrix pose;Fmatrix&XFORM(){return pose;}};
struct Objects{Object* expected=nullptr;Object*net_Find(u16){return expected;}};
struct World{::Objects Objects;u32 timeServer(){return 1000;}void Send(NET_Packet&,int){}}world;
World&Level(){return world;}int net_flags(bool,bool){return 0;}
constexpr bool TRUE=true;
struct CActor{
 u32 m_next_input_sequence=1,mstate_real=0,m_netcoop_owner_received=0;
 u16 m_netcoop_owner_slot=65535,m_netcoop_owner_item=65535,m_netcoop_platform_car=65535;
 bool m_jump_input_pending=false;struct{float yaw=0,pitch=0,roll=0;}unaffected_r_torso;
 float r_model_yaw=0;Fvector position{12,3,4},NET_SavedAccel;
 std::deque<ActorInputCommand> m_client_pending_inputs;Object* m_netcoop_platform_object=nullptr;
 Physics physics;Inventory inv;
 bool Local(){return true;}bool OnServer(){return false;}
 float GetfHealth(){return 1;}float g_Radiation(){return 0;}
 u8 g_Team(){return 0;}u8 g_Squad(){return 0;}u8 g_Group(){return 0;}
 Fvector&Position(){return position;}Physics*character_physics_support(){return &physics;}Inventory&inventory(){return inv;}
 const char*cNameVisual(){return "actors\\stalker.ogf";}
 void net_ExportInput(NET_Packet&,const ActorInputCommand&){}
 void netcoop_export_weapon_slots(NET_Packet&){} // server-only optional tail
 void net_Export(NET_Packet&);
};
'''+writer+r'''
int main(){
 CActor actor;Object car;world.Objects.expected=&car;
 for(bool riding:{false,true}) {
  actor.m_netcoop_platform_car=riding?7:65535;actor.m_netcoop_platform_object=riding?&car:nullptr;
  NET_Packet p;actor.net_Export(p);
  assert(gamma_net::valid_coop_actor(p.bytes.data(),p.bytes.size()));
  const auto at=65+std::strlen(actor.cNameVisual())+1;
  assert(p.bytes[at]==0x4c&&p.bytes[at+1]==0x50&&p.bytes[at+16]==0x4e&&p.bytes[at+17]==0x53);
  u32 sequence;std::memcpy(&sequence,p.bytes.data()+at+18,4);
  assert(sequence==actor.m_next_input_sequence-1&&sequence==actor.m_client_pending_inputs.back().sequence);
  for(std::size_t n=0;n<p.bytes.size();++n)assert(!gamma_net::valid_coop_actor(p.bytes.data(),n));
 }
 puts("PASS actual owner writer -> host validator: ordinary/riding positions, matching sample sequence, every truncation");
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'wire.cpp';exe=Path(tmp)/('wire.exe' if os.name=='nt' else 'wire')
    cpp.write_text(source,encoding='utf-8')
    include=str(root/'src/xrNetServer')
    command=(['cl','/nologo','/std:c++17','/EHsc','/I'+include,str(cpp),'/Fe:'+str(exe)] if os.name=='nt'
             else ['g++','-std=c++17','-I',include,str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=tmp,check=True)
    subprocess.run([str(exe)],cwd=tmp,check=True,timeout=10)
