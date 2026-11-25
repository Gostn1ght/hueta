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
 void sub(Fvector a,Fvector b){x=a.x-b.x;y=a.y-b.y;z=a.z-b.z;}
 float dotproduct(Fvector v)const{return x*v.x+y*v.y+z*v.z;}
 float magnitude()const{return std::sqrt(x*x+y*y+z*z);}void normalize_safe(){float m=magnitude();if(m){x/=m;y/=m;z/=m;}}};
bool _valid(Fvector v){return _valid(v.x)&&_valid(v.y)&&_valid(v.z);}
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
 CPhysicsShell*PPhysicsShell(){return &shell;}::Visual*Visual(){return &visual;}Fmatrix XFORM(){return matrix;}
 Fvector Position(){return matrix.c;}void u_EventSend(NET_Packet p){hits.push_back(p);}};
constexpr u16 vehicle_seat_free=65535;
struct VehicleRuntime{u32 run_over_check=0;std::vector<u16>seats;bool run_over_sampled=false;Fvector run_over_position;};
struct Objects{std::vector<CObject*>all;u32 o_count(){return (u32)all.size();}CObject*o_get_by_iterator(u32 i){return all[i];}
 CObject*net_Find(u16 id){for(auto p:all)if(p->ID()==id)return p;return nullptr;}};
struct World{::Objects Objects;}world;World&Level(){return world;}void Msg(const char*,...){}
''' + native[native.index('static const float RUN_OVER_SPEED'):native.index('static bool vehicle_swept_hit')] + method('static bool vehicle_swept_hit(') + method('static void vehicle_run_over(') + r'''
int main(){
 CCar car;car.id=5;CActor player;player.id=7;world.Objects.all={&player};VehicleRuntime v;
 auto tick=[&](u32 now,float z,float offset=0.f){
    car.matrix.c.z=z;player.pos={0,0,z+offset};vehicle_run_over(&car,v,now);
 };
 car.shell.v={0,0,10};
 tick(1000,0);assert(car.hits.empty()); // no segment yet
 tick(1100,0,2.5f);assert(car.hits.empty()); // near front, shell spike without motion
 tick(1200,0,-2.5f);assert(car.hits.empty()); // near rear, still parked
 tick(1300,.1f);assert(car.hits.empty()); // small contact displacement, below threshold
 tick(1400,1);assert(car.hits.size()==1);
 auto hit=car.hits.back();assert(hit.target==7&&hit.who==5&&hit.weapon==5&&hit.power>.4f&&hit.impulse>530&&hit.impulse<550);
 tick(1500,2);assert(car.hits.size()==1); // repeat cooldown
 tick(2200,9);assert(car.hits.size()==1); // stale sample gap
 tick(2300,10);assert(car.hits.size()==2);
 CActor driver;driver.id=8;driver.m_netcoop_seat_car=5;world.Objects.all.push_back(&driver);v.seats={8};
 tick(3100,20);assert(car.hits.size()==2);
 tick(3200,21);assert(car.hits.size()==3&&car.hits.back().who==8);
 tick(4000,30);player.m_netcoop_seat_car=5;
 tick(4100,31);assert(car.hits.size()==3);
 player.m_netcoop_seat_car=65535;player.m_netcoop_platform_car=5;player.m_netcoop_platform_time=4200;
 tick(4200,32);assert(car.hits.size()==3);
 player.m_netcoop_platform_car=65535;player.alive=false;tick(4300,33);assert(car.hits.size()==3);
 player.alive=true;player.removed=true;tick(4400,34);assert(car.hits.size()==3);player.removed=false;
 tick(4500,130,-4);assert(car.hits.size()==3); // rejected coordinate jump
 tick(4750,132.5f,-4);assert(car.hits.size()==4); // player behind final box, in observed sweep
 car.shell.active=false;tick(4800,132.5f);car.shell.active=true;
 tick(4850,133);assert(car.hits.size()==4); // reactivation starts a fresh sample
 car.shell.v={0,0,-10};tick(5750,125);tick(5850,124,3.4f);assert(car.hits.size()==5);
 // Unsigned elapsed time remains valid across the 32-bit clock wrap.
 v.run_over_sampled=false;s_run_over_last.clear();car.shell.v={0,0,10};
 tick(0xffffffc0u,0);tick(36u,1);assert(car.hits.size()==6);
 puts("PASS actual vehicle impact uses observed movement: parked shell spikes, cooldown, empty/driver/reverse sweep, teleport and stale samples, rider exclusion and timer wrap");
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
