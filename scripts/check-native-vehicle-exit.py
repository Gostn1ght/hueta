"""CI-only actual car/player contact and standing-volume exit selection."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def method(path, signature):
    text = (ROOT/path).read_text(encoding='utf-8')
    start = text.index(signature)
    brace = text.index('{', start)
    depth, end = 1, brace+1
    while depth:
        depth += (text[end] == '{')-(text[end] == '}')
        end += 1
    return text[start:end]


source = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>
template<class T>using xr_vector=std::vector<T>;
template<class T>T _min(T a,T b){return std::min(a,b);}
template<class T>T _max(T a,T b){return std::max(a,b);}
struct Fvector {float x=0,y=0,z=0;void set(float a,float b,float c){x=a;y=b;z=c;}};
struct Fmatrix {
 Fvector c;
 void invert(const Fmatrix& m){c.set(-m.c.x,-m.c.y,-m.c.z);}
 void transform_tiny(Fvector& out,const Fvector& in)const{out.set(in.x+c.x,in.y+c.y,in.z+c.z);}
};
struct Fbox {
 Fvector min,max;
 void set(float a,float b,float c,float d,float e,float f){min.set(a,b,c);max.set(d,e,f);}
 void xform(const Fbox& box,const Fmatrix& m){m.transform_tiny(min,box.min);m.transform_tiny(max,box.max);}
 bool intersect(const Fbox& b)const{return min.x<=b.max.x&&max.x>=b.min.x&&min.y<=b.max.y&&max.y>=b.min.y&&min.z<=b.max.z&&max.z>=b.min.z;}
};
struct VisualData {Fbox box;};
struct Model {VisualData data;VisualData& getVisData(){return data;}};
struct CObject {
 Model model;Fmatrix pose;bool destroyed=false;
 bool getDestroy(){return destroyed;}Model* Visual(){return &model;}
 Fmatrix& XFORM(){return pose;}Fvector& Position(){return pose.c;}
};
struct Flags {int flags=0;bool test(int f){return (flags&f)!=0;}};
struct SGameMtl {enum{flActorObstacle=1};::Flags Flags;};
struct Holder {bool actor=false,live=true;bool IsActor(){return actor;}};
struct dxGeomUserData {Holder* ph_ref_object=nullptr;};
dxGeomUserData* retrieveGeomUserData(void* p){return static_cast<dxGeomUserData*>(p);}
bool PHIsShellHolderLive(Holder* h){return h&&h->live;}
constexpr int dContactSoftERP=1,dContactSoftCFM=2;
struct dContact {
 struct{void* g1=nullptr;void* g2=nullptr;float depth=.8f;}geom;
 struct{int mode=0;float soft_erp=.2f,soft_cfm=.00001f,mu=1.f,bounce=.5f;}surface;
};
namespace netcoop{bool active=true;bool enabled(){return active;}}
struct CCar:CObject {static void ActorObstacleCallback(bool&,bool,dContact&,SGameMtl*,SGameMtl*);};
namespace collide {struct rq_result{float range=0;};enum{rqtStatic=1};}
struct Space {
 bool all_blocked=false,preferred_blocked=false,ground=true;
 xr_vector<CObject*> nearby;
 bool BoxQuery(const Fvector& center,const Fvector&,const Fvector&,const Fvector& size,void*){
  assert(size.x>=.8f&&size.y>=1.7f);
  return all_blocked||(preferred_blocked&&center.x<0);
 }
 void GetNearest(xr_vector<CObject*>& out,const Fvector&,float,CObject* ignore){for(auto* o:nearby)if(o!=ignore)out.push_back(o);}
 bool RayPick(const Fvector& start,const Fvector&,float,int,collide::rq_result& hit,CCar*){hit.range=start.y;return ground;}
};
struct World {Space ObjectSpace;}fixture_world;
World& Level(){return fixture_world;}
struct VehicleSeatPose {Fmatrix local;};
struct VehicleSeats {float center_x=0,half_width=1;};
'''
source += '\n'+method('src/xrGame/Car.cpp', 'void CCar::ActorObstacleCallback(')
source += '\n'+method('src/xrGame/netcoop_vehicles.inc', 'static bool vehicle_exit_clear(')
source += '\n'+method('src/xrGame/netcoop_vehicles.inc', 'static Fvector vehicle_exit_position(')
source += r'''
int main(){
 Holder player;player.actor=true;Holder prop;
 dxGeomUserData a{&prop},b{&player};bool collide=true;
 dContact c;c.geom.g1=&a;c.geom.g2=&b;
 CCar::ActorObstacleCallback(collide,true,c,nullptr,nullptr);
 assert(collide&&c.geom.depth==.02f&&c.surface.soft_erp==.08f&&c.surface.soft_cfm==.002f&&c.surface.mu==.4f&&c.surface.bounce==0);
 assert(c.surface.mode==(dContactSoftERP|dContactSoftCFM));
 dContact reverse;reverse.geom.g1=&b;reverse.geom.g2=&a;
 CCar::ActorObstacleCallback(collide,false,reverse,nullptr,nullptr);assert(reverse.geom.depth==.02f);
 for(int variant=0;variant<4;++variant){
  dContact excluded;excluded.geom.g2=&b;
  netcoop::active=variant!=0;player.live=variant!=1;player.actor=variant!=2;collide=variant!=3;
  CCar::ActorObstacleCallback(collide,true,excluded,nullptr,nullptr);assert(excluded.geom.depth==.8f);
 }
 netcoop::active=true;player.live=player.actor=true;collide=false;
 SGameMtl obstacle;obstacle.Flags.flags=SGameMtl::flActorObstacle;
 CCar::ActorObstacleCallback(collide,true,c,&obstacle,nullptr);assert(collide);
 CCar car;VehicleSeats seats;VehicleSeatPose seat;seat.local.c.x=-.4f;
 bool clear=false;Fvector exit=vehicle_exit_position(&car,seats,seat,&clear);
 assert(clear&&exit.x<0&&std::abs(exit.y-.08f)<1e-5f);
 fixture_world.ObjectSpace.preferred_blocked=true;
 exit=vehicle_exit_position(&car,seats,seat,&clear);assert(clear&&exit.x>0);
 fixture_world.ObjectSpace.all_blocked=true;
 vehicle_exit_position(&car,seats,seat,&clear);assert(!clear);
 fixture_world.ObjectSpace.all_blocked=fixture_world.ObjectSpace.preferred_blocked=false;
 CObject parked;parked.model.data.box.set(-.5f,0,-.5f,.5f,2,.5f);parked.pose.c.set(-1.9f,0,0);
 fixture_world.ObjectSpace.nearby={&parked,&car};
 exit=vehicle_exit_position(&car,seats,seat,&clear);assert(clear&&exit.x>0);
 parked.destroyed=true;exit=vehicle_exit_position(&car,seats,seat,&clear);assert(clear&&exit.x<0);
 fixture_world.ObjectSpace.ground=false;seat.local.c.y=20;
 exit=vehicle_exit_position(&car,seats,seat,&clear);assert(clear&&exit.y==20.5f);
 std::puts("PASS actual vehicle exit/contact: standing volume, alternate side, occupied exits, no-ground dismount, bounded player penetration; no gameplay physics claim");
}
'''
server = (ROOT/'src/xrGame/netcoop_vehicle_server.inc').read_text(encoding='utf-8')
assert 'vehicle_transition(current,it->second,*config,i,actor,true)' in server
assert 'vehicle_unseat_server(car,v,i,false)' in server
seat = (ROOT/'src/xrGame/netcoop_vehicle_seat.inc').read_text(encoding='utf-8')
leave = seat[seat.index('void CActor::netcoop_seat_leave('):seat.index('void CActor::netcoop_seat_place(')]
assert leave.index('movement->SetPosition(exit)') < leave.index('movement->CreateCharacter()')
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native compilation is permitted only in GitHub Actions')
with TemporaryDirectory(prefix='vehicle-exit-') as tmp:
    folder = Path(tmp)
    cpp, exe = folder/'exit.cpp', folder/('exit.exe' if os.name=='nt' else 'exit')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
               ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=10)
