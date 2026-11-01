"""Actual demo request, server teleport and MoveActor prediction clearing; GHA only."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp
if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
native=netcoop_cpp(root, encoding='latin-1')
owner=native[native.index('struct FindActorOwner\n'):native.index('void server_forward_news(',native.index('struct FindActorOwner\n'))]
teleport=native[native.index('bool script_admin_teleport('):native.index('bool script_admin_noclip(',native.index('bool script_admin_teleport('))]
events=(root/'src/xrGame/Actor_Events.cpp').read_text(encoding='latin-1')
move=events[events.index('void CActor::MoveActor('):]
assert move.rstrip().endswith('}') and 'ResetPredictionState' not in move
persistent=(root/'src/xrGame/GamePersistent.cpp').read_text(encoding='latin-1')
request=persistent[persistent.index('bool CGamePersistent::RequestDemoTeleport('):]
assert request.rstrip().endswith('}')
render=(root/'src/xrEngine/FDemoRecord.cpp').read_text(encoding='latin-1')
assert '#include "IGame_Persistent.h"' in render
assert 'if (!g_pGamePersistent || !g_pGamePersistent->RequestDemoTeleport(m_Camera))' in render
source=r'''
#include <cassert>
#include <cmath>
#include <cstdio>
#include <map>
#include <limits>
#include <string>
#include <vector>
using u16=unsigned short;constexpr bool TRUE=true;
constexpr int GE_MOVE_ACTOR=1,M_NETANOMALY_CMD=2;
struct Fvector{float x=0,y=0,z=0;void set(float a,float b,float c){x=a;y=b;z=c;}void set(const Fvector& v){*this=v;}};
bool same(const Fvector& a,const Fvector& b){return a.x==b.x&&a.y==b.y&&a.z==b.z;}
bool _valid(const Fvector& v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
struct Fmatrix{Fvector c;void translate(const Fvector& v){c=v;}};
struct CObject{virtual ~CObject()=default;};
struct Camera{void Set(float,float,float){}};
struct CActor:CObject{
 u16 id=0;bool alive=true;unsigned moves=0,next_sequence=501,last_ack=490;
 Fmatrix matrix;Camera camera;float r_model_yaw=0,r_torso_tgt_roll=0,m_prediction_error=4;
 struct Torso{float yaw=0,pitch=0,roll=0;}r_torso,unaffected_r_torso;
 std::vector<int> m_client_pending_inputs={1,2},m_client_prediction_history={1,2};bool m_bInInterpolation=true;
 u16 ID()const{return id;}bool g_Alive()const{return alive;}
 Fmatrix XFORM()const{return matrix;}Camera* cam_Active(){return &camera;}
 const Fvector& Position()const{return matrix.c;}
 void ForceTransform(const Fmatrix& m){matrix=m;++moves;}
 void MoveActor(Fvector NewPos,Fvector NewDir);
};
struct Owner{u16 ID=0;Fvector o_Position;};
struct IClient{virtual ~IClient()=default;};
struct xrClientData:IClient{
 struct{bool bLocal=false;}flags;Owner* owner=nullptr;int netcoop_role=0;unsigned ID=77;
 bool admitted=true,m_pending_jump_edge=true;unsigned received=500,processed=490;
 std::vector<int> m_pending_inputs={1,2};struct{float pitch=.2f,yaw=.3f;int mstate=3;}m_current_intent;
};
template<class T>T smart_cast(CObject* o){return dynamic_cast<T>(o);}
'''+owner+r'''
struct NET_Packet{int event=0;u16 actor=0;std::vector<Fvector> vectors;void w_vec3(const Fvector& v){vectors.push_back(v);}};
struct CGameObject{static void u_EventGen(NET_Packet& p,int kind,u16 id){p.event=kind;p.actor=id;}};
unsigned net_flags(bool reliable,bool immediate){return (reliable?1u:0u)|(immediate?2u:0u);}
struct Server{
 std::vector<IClient*> clients;unsigned sends=0,last_client=0,last_flags=0;NET_Packet last;
 template<class F>IClient* FindClient(F f){for(auto* c:clients)if(f(c))return c;return nullptr;}
 void SendTo(unsigned cid,NET_Packet& p,unsigned flags){++sends;last=p;last_client=cid;last_flags=flags;}
};
struct Objects{std::map<u16,CObject*> values;CObject* net_Find(u16 id){auto i=values.find(id);return i==values.end()?nullptr:i->second;}};
struct Box{bool contains(const Fvector& p)const{return std::abs(p.x)<=100&&std::abs(p.y)<=100&&std::abs(p.z)<=100;}};
struct Space{Box box;const Box& GetBoundingVolume(){return box;}};
struct World{::Server* Server=nullptr;::Objects Objects;Space ObjectSpace;CObject* control=nullptr;CObject* CurrentControlEntity(){return control;}}world;
World& Level(){return world;}bool g_pGameLevel=true,enabled_flag=true,pure_flag=false,admin_flag=true;
namespace netcoop{
 constexpr int role_admin=2;std::vector<std::string> commands;
 bool enabled(){return enabled_flag;}bool pure_client(){return pure_flag;}
 bool client_admin_authorized(){return admin_flag;}
 bool server_character_accepts(xrClientData* c,int kind){assert(kind==M_NETANOMALY_CMD);return c->admitted;}
 void client_send_command(const char* s){commands.emplace_back(s);}
'''+teleport+r'''
}
'''+move+r'''
using string256=char[256];
template<class... T>void xr_sprintf(string256& out,const char* fmt,T... args){std::snprintf(out,sizeof(out),fmt,args...);}
void Msg(const char*){}
struct CGamePersistent{bool RequestDemoTeleport(const Fmatrix& camera);};
'''+request+r'''
int main(){
 Server server;world.Server=&server;CActor actor,other;actor.id=7;other.id=8;
 Owner a,b;a.ID=7;b.ID=8;xrClientData admin,player;
 admin.owner=&a;admin.netcoop_role=2;player.owner=&b;player.netcoop_role=1;
 server.clients={&admin,&player};world.Objects.values={{u16(7),&actor},{u16(8),&other}};
 const Fvector dest={3,4,5};
 assert(!netcoop::script_admin_teleport(8,dest)&&other.moves==0&&server.sends==0);
 assert(!netcoop::script_admin_teleport(65535,dest));
 for(const Fvector bad:{Fvector{101,0,0},Fvector{0,101,0},Fvector{0,0,101},Fvector{std::numeric_limits<float>::quiet_NaN(),0,0}})
  assert(!netcoop::script_admin_teleport(7,bad)&&actor.moves==0&&server.sends==0);
 actor.alive=false;assert(!netcoop::script_admin_teleport(7,dest));actor.alive=true;
 admin.admitted=false;assert(!netcoop::script_admin_teleport(7,dest));admin.admitted=true;
 admin.flags.bLocal=true;assert(!netcoop::script_admin_teleport(7,dest));admin.flags.bLocal=false;
 enabled_flag=false;assert(!netcoop::script_admin_teleport(7,dest));enabled_flag=true;
 pure_flag=true;assert(!netcoop::script_admin_teleport(7,dest));pure_flag=false;
 g_pGameLevel=false;assert(!netcoop::script_admin_teleport(7,dest));g_pGameLevel=true;
 world.Server=nullptr;assert(!netcoop::script_admin_teleport(7,dest));world.Server=&server;
 assert(netcoop::script_admin_teleport(7,dest));
 assert(actor.moves==1&&same(actor.Position(),dest)&&same(a.o_Position,dest));
 assert(admin.m_pending_inputs.empty()&&!admin.m_pending_jump_edge&&admin.m_current_intent.mstate==0);
 assert(admin.received==500&&admin.processed==490);
 assert(server.sends==1&&server.last_client==77&&server.last_flags==3);
 assert(server.last.actor==7&&server.last.event==GE_MOVE_ACTOR&&server.last.vectors.size()==2);
 assert(same(server.last.vectors[0],dest));
 assert(server.last.vectors[1].x==-.2f&&server.last.vectors[1].y==.3f);
 // Deliver the actual MoveActor path to the controlled client, without sequence reset.
 pure_flag=true;world.control=&actor;actor.MoveActor(server.last.vectors[0],server.last.vectors[1]);
 assert(actor.m_client_pending_inputs.empty()&&actor.m_client_prediction_history.empty());
 assert(actor.next_sequence==501&&actor.last_ack==490&&actor.m_prediction_error==0&&!actor.m_bInInterpolation);
 other.MoveActor(dest,{});assert(!other.m_client_prediction_history.empty());
 CGamePersistent persistent;Fmatrix camera;camera.c=dest;
 const auto before=netcoop::commands.size();
 admin_flag=false;assert(persistent.RequestDemoTeleport(camera)&&netcoop::commands.size()==before);
 admin_flag=true;camera.c.x=std::numeric_limits<float>::quiet_NaN();
 assert(persistent.RequestDemoTeleport(camera)&&netcoop::commands.size()==before);
 camera.c=dest;assert(persistent.RequestDemoTeleport(camera)&&netcoop::commands.back()=="admin_teleport 3 4 5");
 pure_flag=false;assert(!persistent.RequestDemoTeleport(camera));
 std::puts("PASS actual demo request/server teleport/MoveActor: owner-role-liveness-admission-finite-map guards; reliable owner move; old paths cleared, sequences retained; ordinary/local behavior isolated");
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'teleport.cpp';exe=Path(tmp)/('teleport.exe' if os.name=='nt' else 'teleport')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
        ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
