"""CI-only actual car support probe and history-based platform acceptance."""
import os,subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
s=(root/'src/xrGame/netcoop_actor_platform.inc').read_text()
def method(signature):
 a=s.index(signature);b=s.index('{',a);e=b+1;depth=1
 while depth:depth+=(s[e]=='{')-(s[e]=='}');e+=1
 return s[a:e]
source=r'''#include <cassert>
#include <cmath>
#include <deque>
#include <map>
#include <algorithm>
#include <cstdio>
using u16=unsigned short;using u32=unsigned;
template<class T>using xr_deque=std::deque<T>;template<class K,class V>using xr_map=std::map<K,V>;
template<class T>T _max(T a,T b){return std::max(a,b);}float _abs(float f){return std::abs(f);}
constexpr float EPS_S=.000001f;
struct Fvector{float x=0,y=0,z=0;
 Fvector&set(float a,float b,float c){x=a;y=b;z=c;return *this;}
 Fvector&sub(const Fvector&a,const Fvector&b){return set(a.x-b.x,a.y-b.y,a.z-b.z);}
 Fvector&mul(float v){x*=v;y*=v;z*=v;return *this;}
 Fvector&mad(const Fvector&a,const Fvector&b,float v){return set(a.x+b.x*v,a.y+b.y*v,a.z+b.z*v);}
 float square_magnitude()const{return x*x+y*y+z*z;}float magnitude()const{return std::sqrt(square_magnitude());}
 void normalize(){mul(1/magnitude());}
 float distance_to_sqr(const Fvector&v)const{Fvector d;return d.sub(*this,v).square_magnitude();}
 float distance_to(const Fvector&v)const{return std::sqrt(distance_to_sqr(v));}
 void crossproduct(const Fvector&a,const Fvector&b){set(a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x);}
};
bool _valid(const Fvector&v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
struct Fmatrix{float yaw=0;Fvector c;
 void set(const Fmatrix&v){*this=v;}
 void transform_tiny(Fvector&out,Fvector v)const{out.set(std::cos(yaw)*v.x+std::sin(yaw)*v.z+c.x,v.y+c.y,-std::sin(yaw)*v.x+std::cos(yaw)*v.z+c.z);}
 void invert(const Fmatrix&m){yaw=-m.yaw;Fvector p{-m.c.x,-m.c.y,-m.c.z};c={};transform_tiny(c,p);}
};
struct CObject{virtual~CObject()=default;};struct CActor;
struct CCar:CObject{Fmatrix pose;bool destroyed=false,heli=false;u16 id=7;
 u16 ID(){return id;}bool getDestroy(){return destroyed;}bool netcoop_destroyed(){return destroyed;}bool netcoop_is_heli(){return heli;}Fmatrix&XFORM(){return pose;}};
template<class T>T smart_cast(CObject*p){return dynamic_cast<T>(p);}
namespace collide{enum{rqtObject};struct rq_result{CObject*O=nullptr;float range=0;};}
struct Objects{std::map<u16,CObject*>values;CObject*net_Find(u16 id){auto it=values.find(id);return it==values.end()?nullptr:it->second;}};
CCar*surface_car=nullptr;float slope=0;unsigned rays=0,fail_ray=99;
struct Space{bool RayPick(const Fvector&start,const Fvector&,float range,int,collide::rq_result&hit,CActor*){
 if(rays++==fail_ray||!surface_car)return false;hit.O=surface_car;hit.range=start.y-surface_car->pose.c.y-slope*start.x;return hit.range>=0&&hit.range<=range;}};
struct World{::Objects Objects;Space ObjectSpace;u32 now=1000;u32 timeServer(){return now;}}world;
World&Level(){return world;}
namespace netcoop{''' +s[s.index('struct PlatformFrame'):s.index('void platform_record(')]+r'''}
struct CActor:CObject{Fvector pos;bool seated=false,m_netcoop_noclip=false;u16 m_netcoop_platform_car=65535;
 CCar*m_netcoop_platform_object=nullptr;Fvector m_netcoop_platform_local,m_netcoop_platform_velocity;Fmatrix m_netcoop_platform_pose;
 u32 m_netcoop_platform_time=0,m_netcoop_platform_departure_until=0;
 bool netcoop_seated(){return seated;}Fvector&Position(){return pos;}
 bool netcoop_platform_accept(u16,const Fvector&,Fvector,Fvector&,Fvector&);
};
namespace netcoop{'''+method('static CCar* platform_surface(')+r'''}
'''+method('bool CActor::netcoop_platform_accept(')+r'''
int main(){
 CCar car;surface_car=&car;world.Objects.values[7]=&car;CActor actor;Fvector feet{0,.08f,0};
 assert(netcoop::platform_surface(&actor,feet)==&car&&rays==3);
 rays=0;fail_ray=1;assert(!netcoop::platform_surface(&actor,feet));fail_ray=99;rays=0;
 slope=2;feet={0,0,0};assert(!netcoop::platform_surface(&actor,feet));slope=0;
 car.heli=true;assert(!netcoop::platform_surface(&actor,feet));car.heli=false;
 Fvector target,base;Fvector local{0,0,0};
 assert(!actor.netcoop_platform_accept(7,local,feet,target,base)); // no recorded car pose
 auto& history=netcoop::s_platform_history[7];history.object=&car;
 Fmatrix old;history.frames.push_back({950,old});car.pose.c={1,0,0};history.frames.push_back({1000,car.pose});
 assert(actor.netcoop_platform_accept(7,local,feet,target,base));
 assert(std::abs(target.x-1)<.001f&&std::abs(base.x-1)<.001f&&std::abs(actor.m_netcoop_platform_velocity.x-20)<.001f);
 actor.m_netcoop_platform_local={.2f,0,0};car.pose.yaw=1.5707963f;
 Fvector rejected_position{.1f,0,0},rejected_base{9,9,9};
 fail_ray=rays;assert(!actor.netcoop_platform_accept(7,local,rejected_position,rejected_position,rejected_base));fail_ray=99;
 assert(rejected_position.x==.1f&&rejected_base.x==9); // alias remains intact on a failed surface probe
 Fvector reported{1.3f,0,0};local={.3f,0,0};
 assert(actor.netcoop_platform_accept(7,local,reported,target,base));
 assert(std::abs(target.z+.3f)<.001f&&std::abs(base.z+.2f)<.001f); // walking remains relative to turning deck
 reported={100,0,0};assert(!actor.netcoop_platform_accept(7,local,reported,target,base));
 actor.m_netcoop_platform_car=65535;actor.m_netcoop_platform_object=nullptr;actor.pos={50,0,0};
 reported={1,0,0};local={0,0,0};assert(!actor.netcoop_platform_accept(7,local,reported,target,base)); // cannot board remotely
 actor.pos={};history.object=nullptr;assert(!actor.netcoop_platform_accept(7,local,reported,target,base));
 puts("PASS actual platform support/history: three contacts, slopes, helicopters, missing/reused car, translation, rotation, relative walking and remote-boarding rejection");
}
'''
with TemporaryDirectory() as tmp:
 cpp=Path(tmp)/'platform.cpp';exe=Path(tmp)/('platform.exe' if os.name=='nt' else 'platform');cpp.write_text(source)
 cmd=['cl','/nologo','/std:c++17','/EHsc',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else ['g++','-std=c++17','-fsanitize=address,undefined',str(cpp),'-o',str(exe)]
 subprocess.run(cmd,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
