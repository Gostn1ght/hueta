"""CI-only execution of the actual helicopter physics step, including two independent shells."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def body(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


car = (ROOT / 'src/xrGame/Car.cpp').read_text(encoding='utf-8') + (ROOT / 'src/xrGame/CarHelicopter.cpp').read_text(encoding='utf-8')
header = (ROOT / 'src/xrGame/Car.h').read_text(encoding='utf-8')
flight = body(car, 'void CCar::netcoop_heli_step(')
safe_cycle = body(car, 'static CBlend* car_play_cycle_safe(')
gear_code='\n'.join(body(car,signature) for signature in ('void CCar::netcoop_heli_gear_step(', 'void CCar::netcoop_heli_toggle_gear(', 'void CCar::netcoop_heli_gear_replica('))
gravity = '\n'.join(body(car, signature) for signature in (
    'void CCar::PhTune(', 'float CCar::EffectiveGravity(', 'float CCar::AntiGravityAccel('))
heli = header[header.index('struct NetcoopHeli'):header.index('} m_netcoop_heli;') + len('} m_netcoop_heli;')]
source = r'''
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <algorithm>
#include <string>
#ifdef _MSC_VER
// The unchanged legacy PhTune signature does not consume its timestep.
#pragma warning(disable:4100)
#endif
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;
using LPCSTR=const char*;
constexpr bool FALSE=false;
constexpr u16 BI_NONE=u16(-1);
constexpr float EPS=1e-6f,EPS_L=1e-5f;
template<class T>T _min(T a,T b){return std::min(a,b);}
template<class T>T _max(T a,T b){return std::max(a,b);}
float _abs(float x){return std::fabs(x);}
bool _valid(float x){return std::isfinite(x);}
void Msg(const char*,...){}
struct Fvector {
 float x=0,y=0,z=0;
 void set(float a,float b,float c){x=a;y=b;z=c;}
 void mad(const Fvector& v,float f){x+=v.x*f;y+=v.y*f;z+=v.z*f;}
 void sub(const Fvector& a,const Fvector& b){set(a.x-b.x,a.y-b.y,a.z-b.z);}
 float dotproduct(const Fvector& v)const{return x*v.x+y*v.y+z*v.z;}
 float magnitude()const{return std::sqrt(dotproduct(*this));}
};
bool _valid(const Fvector& v){return _valid(v.x)&&_valid(v.y)&&_valid(v.z);}
struct Fmatrix{Fvector i{1,0,0},j{0,1,0},k{0,0,1},c{0,5,0};};
struct CODEGeom {Fmatrix form;unsigned moved=0;void set_local_form_bt(const Fmatrix& f){form=f;++moved;}void clear_cashed_tries(){}void clear_motion_history(bool){}};
struct CBlend{float speed=0;};
struct MotionID{int id=-1;bool valid()const{return id>=0;}};
struct IKinematicsAnimated{
 bool have_idle=true;CBlend blend;unsigned played=0;MotionID last;
 MotionID ID_Cycle_Safe(LPCSTR name){return MotionID{have_idle&&std::string(name)=="idle"?1:-1};}
 CBlend* PlayCycle(MotionID motion,bool){assert(motion.valid());last=motion;++played;return &blend;}
};
struct IKinematics{void CalculateBones_Invalidate(){}};
namespace netcoop{bool active=false;bool enabled(){return active;}bool pure_client(){return false;}}
template<class T>T smart_cast(IKinematics* k){return static_cast<T>(k);}
struct CPhysicsElement {
 Fmatrix form;Fvector force,torque;unsigned force_calls=0;
 bool isActive(){return true;}bool isEnabled(){return true;}float getMass(){return 2500;}
 void GetGlobalTransformDynamic(Fmatrix* f){*f=form;}
 void applyForce(float x,float y,float z){force.mad(Fvector{x,y,z},1);++force_calls;}
 void applyTorque(float x,float y,float z){torque.mad(Fvector{x,y,z},1);}
};
struct CPhysicsShell {
 CPhysicsElement element;Fvector velocity,angular;float mass=2500;u16 count=1;unsigned lookups=0;
 u16 get_ElementsNumber(){return count;}
 CPhysicsElement* get_ElementByStoreOrder(u16 n){assert(n<count);++lookups;return &element;}
 void Enable(){}
 float getMass(){return mass;}
 void get_LinearVel(Fvector& v){v=velocity;}
 void get_AngularVel(Fvector& v){v=angular;}
};
struct FakeWorld{float Gravity(){return 9.81f;}};
FakeWorld* physics_world(){static FakeWorld world;return &world;}
namespace collide{enum{rqtStatic};struct rq_result{float range=0;};}
struct FakeSpace {
 bool RayPick(const Fvector& start,const Fvector&,float range,int,collide::rq_result& hit,void*){
  hit.range=start.y;return start.y>=0&&start.y<range;
 }
};
struct FakeLevel{FakeSpace ObjectSpace;};
FakeLevel& Level(){static FakeLevel level;return level;}
struct{u32 dwTimeGlobal=1;}Device;
struct CPHUpdateObject{static bool IsActive(){return true;}};
struct CCar {
 enum:u8{netcoop_key_forward=1,netcoop_key_back=2,netcoop_key_left=4,netcoop_key_right=8,
  netcoop_key_handbrake=16,netcoop_key_down=32,netcoop_key_yaw_left=64,netcoop_key_yaw_right=128};
 CPhysicsShell* test_shell=nullptr;IKinematics visual;bool has_visual=true,b_engine_on=true;
 u8 m_netcoop_keys=0;float m_fuel=100,m_current_rpm=0,m_min_rpm=100,m_max_rpm=1000,m_fuel_consumption=0;
 unsigned crashes=0;float health=1;void netcoop_heli_crash(){++crashes;}
 void ChangeCondition(float delta){health+=delta;}void StopEngine(){b_engine_on=false;}unsigned ID(){return 42;}void netcoop_heli_gear_step(float);void netcoop_heli_toggle_gear();void netcoop_heli_gear_replica(bool,float);
 CPhysicsShell* PPhysicsShell(){return test_shell;}
 IKinematics* Visual(){return has_visual?&visual:nullptr;}
 void netcoop_heli_weather() {}
 void netcoop_heli_step(float dt);
 void PhTune(float);float EffectiveGravity();float AntiGravityAccel();
''' + heli + '\n};\n' + gravity + '\n' + flight + '\n' + gear_code + '\n' + safe_cycle + r'''
void step(CCar& car,unsigned ticks){
 auto& s=*car.test_shell;
 for(unsigned t=0;t<ticks;++t){
  Device.dwTimeGlobal+=10;s.element.force.set(0,0,0);s.element.torque.set(0,0,0);
  car.PhTune(.01f);
  car.netcoop_heli_step(.01f);
  s.velocity.y+=(s.element.force.y/s.mass-9.81f)*.01f;
  s.element.form.c.y+=s.velocity.y*.01f;
  if(s.element.form.c.y<.1f){s.element.form.c.y=.1f;if(s.velocity.y<0)s.velocity.y=0;}
  assert(_valid(s.velocity)&&_valid(s.element.force)&&_valid(s.element.torque));
 }
}
int main(){
 IKinematicsAnimated animated;
 assert(car_play_cycle_safe(&animated,"$editor")==&animated.blend&&animated.played==1&&animated.last.id==1);
 assert(car_play_cycle_safe(&animated,"idle")==&animated.blend&&animated.played==2);
 animated.have_idle=false;
 assert(car_play_cycle_safe(&animated,"missing")==nullptr&&animated.played==2);
 assert(car_play_cycle_safe(nullptr,"idle")==nullptr);
 CPhysicsShell one,two;CCar a,b;a.test_shell=&one;b.test_shell=&two;
 a.m_netcoop_heli.on=b.m_netcoop_heli.on=true;
 a.m_netcoop_heli.pilot=b.m_netcoop_heli.pilot=true;
 assert(std::fabs(a.EffectiveGravity()-9.81f)<1e-6f&&a.AntiGravityAccel()==0);
 a.PhTune(.01f);assert(one.element.force_calls==0);
 CPhysicsShell road;CCar car;car.test_shell=&road;
 assert(std::fabs(car.EffectiveGravity()-4.905f)<1e-6f);
 car.PhTune(.01f);assert(std::fabs(road.element.force.y-2500*4.905f)<.01f);
 netcoop::active=true;road.element.force.set(0,0,0);car.PhTune(.01f);
 assert(std::fabs(car.EffectiveGravity()-9.81f)<1e-6f && road.element.force.y==0);
 netcoop::active=false;
 a.m_netcoop_heli.rotor=b.m_netcoop_heli.rotor=1;
 a.m_netcoop_heli.collective=b.m_netcoop_heli.collective=.7f;
 // A second vehicle may have been constructed last. No shared bone map is
 // supplied: actual flight must get the body from its own shell every time.
 a.netcoop_heli_step(.01f);
 assert(one.lookups==1&&one.element.force_calls>0&&two.lookups==0&&two.element.force_calls==0);
 const unsigned a_calls=one.element.force_calls;
 b.netcoop_heli_step(.01f);
 assert(one.element.force_calls==a_calls&&two.lookups==1&&two.element.force_calls>0);
 one.count=0;a.netcoop_heli_step(.01f);assert(one.lookups==1);one.count=1;
 a.netcoop_heli_step(0);a.netcoop_heli_step(-1);a.netcoop_heli_step(std::numeric_limits<float>::quiet_NaN());
 assert(one.lookups==1);
 a.has_visual=false;a.netcoop_heli_step(.01f);assert(one.lookups==1);a.has_visual=true;
 a.test_shell=nullptr;a.netcoop_heli_step(.01f);a.test_shell=&one;
 // Real regulator/force equations with an isolated vertical integrator.
 // This does not simulate engine ODE collision or multiplayer acceptance.
 step(a,2000);assert(std::fabs(one.velocity.y)<.2f&&one.element.form.c.y>3);
 a.m_netcoop_keys=CCar::netcoop_key_handbrake;step(a,2000);assert(one.velocity.y>4&&one.velocity.y<9);
 a.m_netcoop_keys=0;step(a,1500);assert(std::fabs(one.velocity.y)<.2f);
 one.element.form.c.y=5;one.velocity.y=0;a.m_netcoop_keys=CCar::netcoop_key_down;
 step(a,1000);assert(one.element.form.c.y<.5f&&std::fabs(one.velocity.y)<1);
 a.m_netcoop_keys=0;a.b_engine_on=false;one.element.form.c.y=50;step(a,1200);
 assert(a.m_netcoop_heli.rotor<.01f&&one.element.form.c.y<.5f);
 // The pilot jumps out at 40 m with the rotor turning: no collective, it
 // falls and the impact destroys it once (owner 2026-10-17).
 a.m_netcoop_heli.crashed=false;a.m_netcoop_heli.recent_speed=0;a.crashes=0;
 a.b_engine_on=true;a.m_netcoop_heli.rotor=1;a.m_netcoop_heli.pilot=false;
 one.element.form.c.y=40;one.velocity.y=0;step(a,800);
 assert(one.element.form.c.y<.5f&&a.crashes==1&&a.m_netcoop_heli.collective<.01f);
 // A gentle landing with the pilot aboard never counts as a crash.
 a.m_netcoop_heli.crashed=false;a.m_netcoop_heli.recent_speed=0;a.crashes=0;a.m_netcoop_heli.pilot=true;
 one.element.form.c.y=6;one.velocity.y=0;a.m_netcoop_keys=CCar::netcoop_key_down;step(a,1200);
 assert(one.element.form.c.y<.5f&&a.crashes==0);a.m_netcoop_keys=0;
 // Actual gear code moves the physical shape and enforces weight/power locks.
 CODEGeom shape;auto& gh=b.m_netcoop_heli;gh.gear_supported=true;gh.gear_down=true;gh.gear_position=1;
 gh.gears[0].geom=&shape;gh.gears[0].rest.c.set(0,0,0);gh.gears[0].travel.set(.65f,1.35f,0);
 gh.ground_height=.1f;b.netcoop_heli_toggle_gear();assert(gh.gear_down);
 gh.ground_height=10;gh.rotor=.5f;b.netcoop_heli_toggle_gear();assert(gh.gear_down);
 gh.rotor=1;b.netcoop_heli_toggle_gear();assert(!gh.gear_down);
 for(int i=0;i<500;++i)b.netcoop_heli_gear_step(.01f);
 assert(gh.gear_position==0 && std::fabs(shape.form.c.y-1.35f)<1e-6f && shape.moved>0);
 b.b_engine_on=false;b.netcoop_heli_toggle_gear();assert(gh.gear_down); // emergency extension
 for(int i=0;i<500;++i)b.netcoop_heli_gear_step(.01f);
 assert(gh.gear_position==1 && shape.form.c.y==0);
 b.netcoop_heli_gear_replica(false,.5f);assert(!gh.gear_down && std::fabs(shape.form.c.y-.675f)<1e-6f);
 b.netcoop_heli_gear_replica(true,2);assert(gh.gear_position==.5f);
 // Manual Mi-24 controls retain collective on release, not a height hold.
 CPhysicsShell manual_shell;CCar manual;manual.test_shell=&manual_shell;
 auto& mh=manual.m_netcoop_heli;mh.on=true;mh.pilot=true;mh.auto_collective=false;mh.auto_level=false;
 mh.collective_rate=.08f;mh.spool_up=.035f;mh.rotor=1;mh.collective=mh.manual_collective=.5f;
 manual_shell.element.form.c.y=50;manual.netcoop_heli_step(.01f);
 assert(std::fabs(mh.manual_collective-.5f)<1e-6f && manual_shell.element.force.y<manual_shell.mass*9.81f);
 manual.m_netcoop_keys=CCar::netcoop_key_handbrake;manual.netcoop_heli_step(10.f);
 assert(mh.manual_collective>.5f && mh.manual_collective<=.50401f); // long-frame bound
 manual.m_netcoop_keys=0;const auto held=mh.manual_collective;manual.netcoop_heli_step(.01f);assert(mh.manual_collective==held);
 // Supported ground weight supplies friction at the actual wheel plane.
 mh.auto_collective=true;mh.collective=0;mh.rotor=.4f;mh.ground_clearance=1.8f;mh.ground_probe=0;
 manual_shell.element.form.c.y=1.9f;manual_shell.velocity.set(2,0,0);manual_shell.element.force.set(0,0,0);
 manual.netcoop_heli_step(.01f);assert(mh.ground_height<.2f && manual_shell.element.force.x<0 && mh.collective==0);
 // Wind changes air-relative drag; rain adds bounded deterministic gusts.
 mh.ground_probe=0;manual_shell.element.form.c.y=50;manual_shell.velocity.set(0,0,0);mh.wind.set(20,0,0);mh.rain=1;
 manual_shell.element.force.set(0,0,0);manual.netcoop_heli_step(.01f);
 assert(manual_shell.element.force.x>0 && _valid(manual_shell.element.force) && std::fabs(manual_shell.element.force.x)<manual_shell.mass*2);
 std::puts("PASS actual helicopter step and PhTune gravity: independent bodies, legacy car gravity retained, no extra heli lift, invalid/empty guards, hover/climb/release/descent, engine-off spool, pilotless fall and impact crash, gentle landing, missing startup cycle fallback; ODE and clients still require live testing");
}
'''
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native compilation is permitted only in GitHub Actions')
with TemporaryDirectory(prefix='heli-native-') as temporary:
    folder = Path(temporary)
    cpp, exe = folder / 'heli.cpp', folder / 'heli.exe'
    cpp.write_text(source, encoding='utf-8')
    subprocess.run(['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)], cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True, timeout=20)
