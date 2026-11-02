"""Actual complete server physics loop: sleeping props, fragments, corpse limbs."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
text=netcoop_cpp(root, encoding='utf-8')
loop=text[text.index('struct PhysicsSent {'):text.index('} // namespace netcoop',text.index('struct PhysicsSent {'))]
# Vehicles (doc 100) live in their own include; this loop only selects and replicates cars.
for part in ('netcoop_vehicles.inc','netcoop_vehicle_server.inc','netcoop_vehicle_client.inc','netcoop_vehicle_seat.inc'):
    loop=loop.replace(f'#include "{part}"','')
source=r'''
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <iterator>
#include <map>
#include <string>
#include <vector>
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;
constexpr bool TRUE=true,FALSE=false;constexpr float EPS_S=0.00001f;
template<class A,class B>using xr_map=std::map<A,B>;
template<class T>using xr_vector=std::vector<T>;
template<class T>T _min(T a,T b){return a<b?a:b;}
template<class T>T _max(T a,T b){return a>b?a:b;}
template<class... T>void Msg(const char*,T...){}
struct Fvector{
 float x=0,y=0,z=0;
 void set(float a,float b,float c){x=a;y=b;z=c;}
 void sub(const Fvector& a,const Fvector& b){set(a.x-b.x,a.y-b.y,a.z-b.z);}
 void sub(const Fvector& b){x-=b.x;y-=b.y;z-=b.z;}
 void add(const Fvector& b){x+=b.x;y+=b.y;z+=b.z;}
 void mul(float s){x*=s;y*=s;z*=s;}
 float square_magnitude()const{return x*x+y*y+z*z;}
 float magnitude()const{return std::sqrt(square_magnitude());}
 void normalize(){mul(1.f/magnitude());}
 float dotproduct(const Fvector& b)const{return x*b.x+y*b.y+z*b.z;}
 float distance_to(const Fvector& b)const{Fvector gap;gap.sub(*this,b);return gap.magnitude();}
};
struct Fmatrix{Fvector i,k;void rotateY(float angle){i.set(std::cos(angle),0,-std::sin(angle));k.set(std::sin(angle),0,std::cos(angle));}};
struct SPHNetState{Fvector position,linear_vel;struct{float x=0,y=0,z=0,w=1;}quaternion;bool enabled=false;};
struct CPhysicsElement{
 SPHNetState state;float mass=8;unsigned impulses=0;float last_impulse=0;
 void get_State(SPHNetState& out){out=state;}
 float getMass(){return mass;}
 void applyImpulse(const Fvector& d,float impulse){++impulses;last_impulse=impulse;Fvector v=d;v.mul(impulse/mass);state.linear_vel.add(v);}
 void set_LinearVel(const Fvector& v){state.linear_vel=v;}
};
struct Shell{
 bool enabled=false;unsigned wakes=0;xr_vector<CPhysicsElement> elements{CPhysicsElement()};
 bool isEnabled(){return enabled;}
 float getMass(){float result=0;for(const auto& e:elements)result+=e.mass;return result;}
 void Enable(){enabled=true;++wakes;}
 CPhysicsElement* get_ElementByStoreOrder(u16 i){return &elements.at(i);}
};
struct CObject{
 virtual ~CObject()=default;u16 id=1;bool destroyed=false;Fvector position;
 u16 ID()const{return id;}bool getDestroy()const{return destroyed;}
 Fvector& Position(){return position;}
 std::string cName()const{return "retained prop";}
};
struct CPhysicsShellHolder:CObject{
 Shell shell;bool attached=false,has_shell=true;
 CObject* H_Parent(){return attached?this:nullptr;}
 Shell* PPhysicsShell(){return has_shell?&shell:nullptr;}
 u16 PHGetSyncItemsNumber(){return u16(shell.elements.size());}
 CPhysicsElement* PHGetSyncItem(u16 i){return shell.get_ElementByStoreOrder(i);}
};
struct CEntityAlive:CPhysicsShellHolder{bool alive=true;bool g_Alive(){return alive;}};
struct CInventoryItem:CPhysicsShellHolder{};
struct CMissile:CInventoryItem{};
struct CGrenade:CMissile{};
struct CBolt:CMissile{};
struct CCustomRocket:CInventoryItem{};
struct CPhysicObject:CPhysicsShellHolder{};
struct CPhysicsSkeletonObject:CPhysicsShellHolder{};
struct CCar:CPhysicsShellHolder{};
constexpr u32 mcFwd=1,mcBack=2,mcLStrafe=4,mcRStrafe=8,mcJump=16,mcClimb=32;
struct CActor:CEntityAlive{u32 move=mcFwd;u32 MovingState(){return move;}float netcoop_model_yaw(){return 0;}};
template<class T>T smart_cast(CObject* o){return dynamic_cast<T>(o);}
struct NET_Packet{void w_begin(int){}void w_u16(u16){}void w_u32(u32){}void w_u8(u8){}void w_vec3(const Fvector&){}void w_float(float){}};
constexpr int M_NETCOOP_PHYSICS=4;int net_flags(bool,bool){return 0;}
struct IClient{virtual ~IClient()=default;};
struct Owner{Fvector o_Position;};
struct xrClientData:IClient{struct{bool bConnected=true;}flags;bool gamma_snapshot_ready=true;Owner* owner=nullptr;u32 ID=1;};
struct xrServer{
 xrClientData host,remote;Owner remote_owner;unsigned sends=0;bool room=true;
 xrServer(){remote.owner=&remote_owner;}
 xrClientData* GetServerClient(){return &host;}
 bool HasSendQueueRoom(xrClientData*,int){return room;}
 void SendTo(u32,NET_Packet&,int){++sends;}
 template<class T>void ForEachClientDo(T& f){f(&host);f(&remote);}
};
u32 fixture_now=100;u32 real_time_ms(){return fixture_now;}
int level_present=1;int* g_pGameLevel=&level_present;
struct Objects{
 xr_vector<CObject*> values;u32 o_count(){return u32(values.size());}
 CObject* o_get_by_iterator(u32 i){return values.at(i);}
 CObject* net_Find(u16 id){for(auto* o:values)if(o->ID()==id)return o;return nullptr;}
};
struct World{::Objects Objects;u32 timeServer(){return fixture_now;}} world;
World& Level(){return world;}
namespace netcoop{bool fixture_client=false;bool pure_client(){return fixture_client;}
void server_corpse_drag_update(xrServer*){}
bool server_corpse_dragging(CObject*){return false;}
'''+loop+r'''
void vehicle_server_update(xrServer*){}
}
void tick(xrServer& server){fixture_now+=50;netcoop::server_physics_update(&server);}
template<class T>void place(T& o,u16 id,float y=0.2f,float z=0.3f){o.id=id;o.position.set(0,y,z);o.shell.elements[0].state.position=o.position;}
int main(){
 xrServer server;CActor actor;actor.id=9;
 CPhysicObject untouched;place(untouched,10,0.2f,5.f);
 world.Objects.values={&actor,&untouched};netcoop::server_physics_update(&server);fixture_now+=31000;
 tick(server);assert(!untouched.shell.enabled&&server.sends==0);
 assert(netcoop::s_physics_sent.empty());
 CPhysicObject barrel;place(barrel,11);barrel.shell.elements[0].mass=80;
 CPhysicsSkeletonObject fragment;place(fragment,12);
 CInventoryItem dropped;place(dropped,13);
 CEntityAlive corpse;place(corpse,14);corpse.alive=false;corpse.shell.elements.resize(2);
 corpse.shell.elements[1].state.position.set(0,0.2f,0.4f);
 world.Objects.values={&actor,&barrel,&fragment,&dropped,&corpse,&untouched};
 tick(server);
 assert(barrel.shell.enabled&&fragment.shell.enabled&&dropped.shell.enabled&&corpse.shell.enabled);
 assert(barrel.shell.elements[0].mass==80&&barrel.shell.elements[0].last_impulse==15);
 assert(std::fabs(barrel.shell.elements[0].state.linear_vel.z-0.1875f)<1e-6f);
 assert(fragment.shell.elements[0].last_impulse==4&&dropped.shell.elements[0].last_impulse==6);
 assert(std::fabs(corpse.shell.elements[0].state.linear_vel.z-0.65f)<1e-6f&&corpse.shell.elements[1].impulses==1);
 assert(std::fabs(corpse.shell.elements[1].state.linear_vel.z-0.65f)<1e-6f);
 assert(corpse.shell.elements[0].state.linear_vel.y==0&&corpse.shell.elements[1].state.linear_vel.y==0);
 // This exceeds a 50-ms Coulomb friction impulse for a resting 0.8-mu
 // ragdoll; the old single-limb impulse was below that threshold.
 const float momentum=corpse.shell.elements[0].last_impulse+corpse.shell.elements[1].last_impulse;
 assert(momentum>corpse.shell.getMass()*9.81f*.8f*.05f);
 assert(!untouched.shell.enabled&&netcoop::s_physics_sent.count(10)==0&&server.sends==4);
 for(unsigned i=0;i<64;++i)tick(server);
 assert(fragment.shell.elements[0].state.linear_vel.z<=0.5f&&barrel.shell.elements[0].state.linear_vel.z<=0.5f);
 assert(barrel.shell.elements[0].mass==80);
 CPhysicObject excluded;place(excluded,15);world.Objects.values={&actor,&excluded};
 for(u32 move:{0u,mcJump|mcFwd,mcClimb|mcFwd,mcFwd|mcBack}){actor.move=move;tick(server);assert(excluded.shell.wakes==0);}
 actor.move=mcFwd;actor.alive=false;tick(server);assert(excluded.shell.wakes==0);actor.alive=true;
 actor.id=0;tick(server);assert(excluded.shell.wakes==0);actor.id=9;
 excluded.attached=true;tick(server);assert(excluded.shell.wakes==0);excluded.attached=false;
 excluded.destroyed=true;tick(server);assert(excluded.shell.wakes==0);excluded.destroyed=false;
 excluded.has_shell=false;tick(server);assert(excluded.shell.wakes==0);excluded.has_shell=true;
 netcoop::fixture_client=true;tick(server);assert(excluded.shell.wakes==0);netcoop::fixture_client=false;
 excluded.shell.elements[0].state.position.set(0,0.2f,-0.3f);tick(server);assert(excluded.shell.wakes==0);
 excluded.shell.elements[0].state.position.set(0,1.f,0.3f);tick(server);assert(excluded.shell.wakes==0);
 excluded.shell.elements[0].state.position.set(0,0.2f,0.7f);tick(server);assert(excluded.shell.wakes==0);
 excluded.shell.elements[0].state.position.set(0,0.2f,0.3f);server.room=false;unsigned sent=server.sends;
 tick(server);assert(excluded.shell.enabled&&server.sends==sent);
 excluded.shell.enabled=false;tick(server);assert(server.sends==sent+1); // the final pose of a sleeping body ignores backpressure (no hovering)
 actor.move=0;CInventoryItem loose;CGrenade grenade;CBolt bolt;CCustomRocket rocket;
 place(loose,16,0.2f,5.f);place(grenade,17,0.2f,5.f);place(bolt,18,0.2f,5.f);
 place(rocket,19,0.2f,0.3f);
 for(CPhysicsShellHolder* body:{static_cast<CPhysicsShellHolder*>(&loose),static_cast<CPhysicsShellHolder*>(&grenade),static_cast<CPhysicsShellHolder*>(&bolt),static_cast<CPhysicsShellHolder*>(&rocket)}){
  body->shell.enabled=true;body->shell.elements[0].state.linear_vel.set(24,0,0);
 }
 actor.move=mcFwd;world.Objects.values={&actor,&loose,&grenade,&bolt,&rocket};tick(server);
 assert(loose.shell.elements[0].state.linear_vel.x==12);
 assert(grenade.shell.elements[0].state.linear_vel.x==24&&bolt.shell.elements[0].state.linear_vel.x==24);
 assert(rocket.shell.elements[0].state.linear_vel.x==24&&rocket.shell.elements[0].impulses==0);
 std::puts("PASS actual server physics: authority pushes, real masses, corpse limbs, final sleeping pose, loose-item velocity limit and grenade/bolt/rocket ballistics retained without foot nudges.");
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'push.cpp';exe=Path(tmp)/('push.exe' if os.name=='nt' else 'push')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
             ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=tmp,check=True)
    subprocess.run([str(exe)],cwd=tmp,check=True)
