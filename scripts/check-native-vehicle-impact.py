"""CI-only actual authoritative run-over: stationary contacts versus moving cars."""
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
native = (root / 'src/xrGame/netcoop_vehicle_server.inc').read_text(encoding='utf-8')


def method(name):
    start = native.index(name)
    end = native.index('{', start) + 1
    depth = 1
    while depth:
        depth += (native[end] == '{') - (native[end] == '}')
        end += 1
    return native[start:end]


# Exercise the actual collision emitter below, and ensure the scheduler calls
# it for empty cars as well as occupied ones.
update = method('void vehicle_server_update(')
assert '\n\t\tvehicle_run_over(car, v, now);' in update
source = r'''
#include <cassert>
#include <cmath>
#include <algorithm>
#include <map>
#include <string>
#include <vector>
#include <cstdio>
using u32=unsigned;using u16=unsigned short;
template<class K,class V>using xr_map=std::map<K,V>;
template<class T>T _min(T a,T b){return std::min(a,b);}
template<class T>T _max(T a,T b){return std::max(a,b);}
float _abs(float a){return std::abs(a);}bool _valid(float a){return std::isfinite(a);}
struct Fvector{float x=0,y=0,z=0;float&operator[](unsigned i){return (&x)[i];}float operator[](unsigned i)const{return (&x)[i];}
 Fvector&set(float a,float b,float c){x=a;y=b;z=c;return *this;}void mul(Fvector v,float k){x=v.x*k;y=v.y*k;z=v.z*k;}
 float magnitude()const{return std::sqrt(x*x+y*y+z*z);}void normalize_safe(){float m=magnitude();if(m){x/=m;y/=m;z/=m;}}};
struct Fbox{Fvector min{-1,-1,-2},max{1,1,2};void grow(float k){for(unsigned i=0;i<3;++i){min[i]-=k;max[i]+=k;}}};
struct Fmatrix{Fvector c;void invert(Fmatrix b){c={-b.c.x,-b.c.y,-b.c.z};}
 void transform_tiny(Fvector&o,Fvector p){o={p.x+c.x,p.y+c.y,p.z+c.z};}void transform_dir(Fvector&o,Fvector p){o=p;}};
struct CObject{u16 id;bool removed=false;std::string name="test";virtual~CObject()=default;u16 ID(){return id;}bool getDestroy(){return removed;}std::string cName(){return name;}};
struct CActor:CObject{bool alive=true;u16 m_netcoop_seat_car=65535,m_netcoop_platform_car=65535;u32 m_netcoop_platform_time=0;Fvector pos;
 bool g_Alive(){return alive;}Fvector Position(){return pos;}};
template<class T>T smart_cast(CObject*p){return dynamic_cast<T>(p);}
struct NET_Packet{float power=0,impulse=0;u16 target=0,who=0,weapon=0;};
namespace ALife{constexpr int eHitTypeStrike=1;}constexpr int GE_HIT=1;
struct SHit{NET_Packet p;u16 whoID=0,weaponID=0;
 SHit(float power,Fvector,CObject*,int,Fvector,float impulse,int,float,bool){p.power=power;p.impulse=impulse;}
 void GenHeader(int,u16 id){p.target=id;}void Write_Packet(NET_Packet&out){p.who=whoID;p.weapon=weaponID;out=p;}};
struct CPhysicsShell{Fvector v;bool active=true;bool isActive(){return active;}void get_LinearVel(Fvector&o){o=v;}};
struct VisualData{Fbox box;};struct Visual{VisualData data;VisualData&getVisData(){return data;}};
struct CCar:CObject{CPhysicsShell shell;::Visual visual;Fmatrix matrix;std::vector<NET_Packet>hits;
 CPhysicsShell*PPhysicsShell(){return &shell;}::Visual*Visual(){return &visual;}Fmatrix XFORM(){return matrix;}void u_EventSend(NET_Packet p){hits.push_back(p);}};
constexpr u16 vehicle_seat_free=65535;
struct VehicleRuntime{u32 run_over_check=0;std::vector<u16>seats;};
struct Objects{std::vector<CObject*>all;u32 o_count(){return (u32)all.size();}CObject*o_get_by_iterator(u32 i){return all[i];}
 CObject*net_Find(u16 id){for(auto p:all)if(p->ID()==id)return p;return nullptr;}};
struct World{::Objects Objects;}world;World&Level(){return world;}void Msg(const char*,...){}
''' + native[native.index('static const float RUN_OVER_SPEED'):native.index('static bool vehicle_swept_hit')] + method('static bool vehicle_swept_hit(') + method('static void vehicle_run_over(') + r'''
int main(){
 CCar car;car.id=5;CActor player;player.id=7;world.Objects.all={&player};VehicleRuntime v;
 vehicle_run_over(&car,v,1000);assert(car.hits.empty()); // overlapping a parked wheel/body
 car.shell.v={0,0,2.99f};vehicle_run_over(&car,v,1100);assert(car.hits.empty());
 car.shell.v={0,0,10};vehicle_run_over(&car,v,1200);assert(car.hits.size()==1);
 auto hit=car.hits.back();assert(hit.target==7&&hit.who==5&&hit.weapon==5&&hit.power>.5f&&hit.impulse==600);
 vehicle_run_over(&car,v,1300);assert(car.hits.size()==1); // one impact, not frame-rate damage
 vehicle_run_over(&car,v,2000);assert(car.hits.size()==2);
 CActor driver;driver.id=8;driver.m_netcoop_seat_car=5;world.Objects.all.push_back(&driver);v.seats={8};
 vehicle_run_over(&car,v,2800);assert(car.hits.size()==3&&car.hits.back().who==8);
 player.m_netcoop_seat_car=5;vehicle_run_over(&car,v,3600);assert(car.hits.size()==3);
 player.m_netcoop_seat_car=65535;player.m_netcoop_platform_car=5;player.m_netcoop_platform_time=4000;
 vehicle_run_over(&car,v,4000);assert(car.hits.size()==3);
 player.m_netcoop_platform_car=65535;player.alive=false;vehicle_run_over(&car,v,5000);assert(car.hits.size()==3);
 player.alive=true;player.removed=true;vehicle_run_over(&car,v,5100);assert(car.hits.size()==3);player.removed=false;
 player.pos={10,0,0};vehicle_run_over(&car,v,5200);assert(car.hits.size()==3);
 // A player crossed between two snapshots is still hit behind the final box.
 player.pos={0,0,-4};vehicle_run_over(&car,v,5450);assert(car.hits.size()==4);
 car.shell.v={0,0,0};player.pos={0,0,0};vehicle_run_over(&car,v,6300);assert(car.hits.size()==4);
 puts("PASS actual run-over: parked/slow contacts harmless, moving empty car hits, swept path, driver credit, rate limit, rider exclusions");
}
'''
with TemporaryDirectory() as tmp:
    cpp = Path(tmp) / 'impact.cpp'
    exe = Path(tmp) / ('impact.exe' if os.name == 'nt' else 'impact')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', str(cpp), '/Fe:'+str(exe)] if os.name == 'nt' else
               ['g++', '-std=c++17', '-fsanitize=address,undefined', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=tmp, check=True)
    subprocess.run([str(exe)], cwd=tmp, check=True, timeout=15)
