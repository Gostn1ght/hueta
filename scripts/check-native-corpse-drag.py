"""CI-only actual native corpse capture bridge; stock ODE joint remains native."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess

if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
native=(root/'src/xrGame/netcoop_corpse_drag.inc').read_text(encoding='utf-8')
native=native.replace('#include "../xrPhysics/IPHCapture.h"','')
actor=(root/'src/xrGame/ActorInput.cpp').read_text(encoding='latin-1')
actor=actor[actor.index('void CActor::ActorUse()'):]
assert actor.index('netcoop::corpse_drag_use(')<actor.index('netcoop_mutant_loot_view.use')
server=(root/'src/xrGame/xrServer.cpp').read_text(encoding='latin-1')
command=server[server.index('case M_NETANOMALY_CMD:'):]
assert command.index('server_corpse_drag_command(this, CL, na_text)')<command.index('netanomaly_server.on_client_command')
source=r'''
#define _CRT_SECURE_NO_WARNINGS
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>
using u16=unsigned short;using LPCSTR=const char*;using string128=char[128];
template<class A,class B>using xr_map=std::map<A,B>;
template<class...T>void Msg(const char*,T...){}
template<size_t N,class...T>void xr_sprintf(char(&p)[N],const char* f,T...v){std::snprintf(p,N,f,v...);}
struct Fvector{float x=0,y=0,z=0;void sub(const Fvector&a,const Fvector&b){x=a.x-b.x;y=a.y-b.y;z=a.z-b.z;}
 float magnitude()const{return std::sqrt(x*x+y*y+z*z);}void mul(float f){x*=f;y*=f;z*=f;}
 float distance_to(const Fvector&b)const{Fvector d;d.sub(*this,b);return d.magnitude();}};
bool _valid(float f){return std::isfinite(f);}bool _valid(const Fvector&v){return _valid(v.x)&&_valid(v.y)&&_valid(v.z);}
struct SPHNetState{Fvector position={0,0.2f,1};};
struct CPhysicsElement{u16 bone=1;SPHNetState state;u16 BoneID(){return bone;}void get_State(SPHNetState&s){s=state;}};
struct CPhysicsShell{float mass=70;bool active=true;unsigned wakes=0;CPhysicsElement element;
 float getMass(){return mass;}bool isActive(){return active;}void Enable(){++wakes;}
 CPhysicsElement*get_ElementByStoreOrder(u16){return &element;}};
struct CObject{virtual~CObject()=default;u16 id=1;bool destroyed=false;Fvector position;
 u16 ID(){return id;}bool getDestroy(){return destroyed;}Fvector&Position(){return position;}};
struct CEntityAlive:CObject{bool alive=false,parent=false,has_shell=true;CPhysicsShell shell;
 bool g_Alive(){return alive;}CObject*H_Parent(){return parent?this:nullptr;}
 CPhysicsShell*PPhysicsShell(){return has_shell?&shell:nullptr;}u16 PHGetSyncItemsNumber(){return 1;}
 CPhysicsElement*PHGetSyncItem(u16){return &shell.element;}};
struct IPHCapture{bool failed=false;bool Failed(){return failed;}};
struct CPHMovementControl{bool exists=true,fail_start=false;IPHCapture capture;bool holding=false;unsigned starts=0,releases=0;
 bool CharacterExist(){return exists;}IPHCapture*PHCapture(){return holding?&capture:nullptr;}
 void PHCaptureObject(CEntityAlive*,u16){++starts;holding=true;capture.failed=fail_start;}
 void PHReleaseObject(){++releases;holding=false;}};
struct Physics{CPHMovementControl move;CPHMovementControl*movement(){return &move;}};
struct CActor:CEntityAlive{bool seated=false,m_netcoop_noclip=false,hidden=false;Physics physics;
 Physics*character_physics_support(){return &physics;}bool netcoop_seated(){return seated;}void HideAllWeapons(bool v){hidden=v;}};
template<class T>T smart_cast(CObject*o){return dynamic_cast<T>(o);}
struct Owner{u16 ID=9;};
struct xrClientData{Owner*owner=nullptr;struct{bool bConnected=true;}flags;bool accepts=true;};
struct FindActorOwner{u16 actor_id=0;};
struct xrServer{xrClientData*client=nullptr;xrClientData*FindClient(const FindActorOwner&f){return client&&client->owner&&client->owner->ID==f.actor_id?client:nullptr;}};
namespace collide{struct rq_result{};constexpr int rqtStatic=1;}
struct Objects{std::map<u16,CObject*>objects;CObject*net_Find(u16 id){auto i=objects.find(id);return i==objects.end()?nullptr:i->second;}};
struct Space{bool blocked=false;bool RayPick(const Fvector&,const Fvector&,float,int,collide::rq_result&,CObject*){return blocked;}};
struct World{::Objects Objects;Space ObjectSpace;CActor*current=nullptr;CActor*CurrentControlEntity(){return current;}}world;
World&Level(){return world;}int present=1;int*g_pGameLevel=&present;constexpr u16 M_NETANOMALY_CMD=1;
namespace netcoop{
bool remote=false;bool pure_client(){return remote;}
bool server_character_accepts(xrClientData*c,u16){return c&&c->accepts;}
std::vector<std::string> states,commands;
bool script_send_to_actor(u16,LPCSTR,LPCSTR v){states.push_back(v);return true;}
void script_command(LPCSTR v){commands.push_back(v);}
}
'''+native+r'''
int main(){
 using namespace netcoop;
 CActor actor;actor.id=9;actor.alive=true;CEntityAlive body;body.id=10;
 world.Objects.objects={{u16(9),&actor},{u16(10),&body}};world.current=&actor;
 Owner owner;xrClientData client;client.owner=&owner;xrServer server;server.client=&client;
 auto use=[&](const char*s){return server_corpse_drag_command(&server,&client,s);};
 assert(!use("other")&&!use("corpse_drag_bad"));
 for(const char*s:{"corpse_drag","corpse_drag x 1","corpse_drag 10 65536","corpse_drag 10 2","corpse_drag 10 1 extra","corpse_drag 999 1"}){
  assert(use(s));assert(actor.physics.move.starts==0);
 }
 body.alive=true;use("corpse_drag 10 1");assert(actor.physics.move.starts==0);body.alive=false;
 body.shell.element.state.position.z=10;use("corpse_drag 10 1");assert(actor.physics.move.starts==0);body.shell.element.state.position.z=1;
 world.ObjectSpace.blocked=true;use("corpse_drag 10 1");assert(actor.physics.move.starts==0);world.ObjectSpace.blocked=false;
 client.accepts=false;use("corpse_drag 10 1");assert(actor.physics.move.starts==0);client.accepts=true;
 actor.seated=true;use("corpse_drag 10 1");assert(actor.physics.move.starts==0);actor.seated=false;
 actor.physics.move.exists=false;use("corpse_drag 10 1");assert(actor.physics.move.starts==0);actor.physics.move.exists=true;
 use("corpse_drag 10 1");assert(actor.physics.move.starts==1&&states.back()=="1"&&s_corpse_drags.size()==1);
 assert(server_corpse_dragging(&body));
 server_corpse_drag_update(&server);assert(s_corpse_drags.size()==1);
 use("corpse_drag 65535 65535");assert(s_corpse_drags.empty()&&actor.physics.move.releases==1&&states.back()=="0");
 assert(!server_corpse_dragging(&body));
 use("corpse_drag 10 1");client.flags.bConnected=false;server_corpse_drag_update(&server);
 assert(s_corpse_drags.empty()&&actor.physics.move.releases==2);client.flags.bConnected=true;
 use("corpse_drag 10 1");actor.alive=false;server_corpse_drag_update(&server);assert(s_corpse_drags.empty());actor.alive=true;
 use("corpse_drag 10 1");actor.physics.move.capture.failed=true;server_corpse_drag_update(&server);assert(s_corpse_drags.empty());
 use("corpse_drag 10 1");CEntityAlive replacement;replacement.id=10;world.Objects.objects[10]=&replacement;
 server_corpse_drag_update(&server);assert(s_corpse_drags.empty());world.Objects.objects[10]=&body;
 remote=true;assert(!corpse_drag_use(&actor,&body,1,false));
 assert(corpse_drag_use(&actor,&body,1,true)&&commands.back()=="corpse_drag 10 1");
 corpse_drag_client_state(true);assert(actor.hidden);assert(corpse_drag_use(&actor,nullptr,65535,false));
 assert(commands.back()=="corpse_drag 65535 65535");corpse_drag_client_state(false);assert(!actor.hidden);
 std::puts("PASS actual stock corpse drag bridge: authenticated ownership, physical bone, distance/wall, toggle, failed capture, death/disconnect, ID reuse, client key and weapon state");
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'drag.cpp';exe=Path(tmp)/('drag.exe' if os.name=='nt' else 'drag')
    cpp.write_text(source,encoding='utf-8')
    cmd=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
         ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(cmd,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
