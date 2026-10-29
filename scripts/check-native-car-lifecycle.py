"""CI-only: compile the actual shell queries, inactive door state and car restore."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
ROOT = Path(__file__).resolve().parents[1]


def between(path, start, end):
    source = (ROOT / path).read_text(encoding='utf-8')
    return source[source.index(start):source.index(end, source.index(start))]


dynamic = between('src/xrPhysics/PHShell.cpp', 'void CPHShell::GetGlobalTransformDynamic(', 'void CPHShell::InterpolateGlobalPosition(')
interpolate = between('src/xrPhysics/PHShell.cpp', 'void CPHShell::InterpolateGlobalTransform(', 'void CPHShell::GetGlobalTransformDynamic(')
state = between('src/xrPhysics/PHElementNetState.cpp', 'void CPHElement::get_State(', 'void CPHElement::net_Export(')
fix = between('src/xrPhysics/PHElement.cpp', 'void CPHElement::Fix()', 'void CPHElement::SetAnimated(')
restore = between('src/xrGame/Car.cpp', 'void CCar::RestoreNetState(', 'void CCar::SetDefaultNetState(')
car_source = (ROOT / 'src/xrGame/Car.cpp').read_text(encoding='utf-8')
steer_start = car_source.index('m_steer_angle = m_steering_wheels.empty()')
steer = car_source[steer_start:car_source.index(';', steer_start)+1]
source = r'''
#include <cassert>
#include <vector>
#include <map>
#include <string>
#include <cstdio>
#include <cstdint>
using u16=std::uint16_t;using u8=std::uint8_t;
#define VERIFY2(a,b) assert(a)
#define TRUE true
#define FALSE false
struct Fvector {float x=0,y=0,z=0;void set(float a,float b,float c){x=a;y=b;z=c;}};
struct Fmatrix {
 Fvector c;
 void set(const Fmatrix& b){*this=b;}
 void mul_43(const Fmatrix&a,const Fmatrix&b){c.set(a.c.x+b.c.x,a.c.y+b.c.y,a.c.z+b.c.z);}
 void mulB_43(const Fmatrix&b){c.set(c.x+b.c.x,c.y+b.c.y,c.z+b.c.z);}
 void transform_tiny(Fvector&v,const Fvector&p)const{v.set(c.x+p.x,c.y+p.y,c.z+p.z);}
};
bool _valid(const Fmatrix&){return true;}
struct Fquaternion {float w=1;void set(const Fmatrix&){w=1;}};
struct SPHNetState {
 Fvector position,previous_position,linear_vel,angular_vel,force,torque;
 Fquaternion quaternion,previous_quaternion;bool enabled=false;
};
struct Flags{int value=0;bool test(int f)const{return !!(value&f);}void set(int f,bool yes){if(yes)value|=f;else value&=~f;}};
struct IKinematics{Fmatrix pose;const Fmatrix& LL_GetTransform(u16){return pose;}};
struct IPhysicsShellHolder {void ObjectProcessingDeactivate(){}void ObjectSpatialMove(){}};
struct CPHShell;
int odeCalls=0,fixCalls=0;
bool dBodyIsEnabled(void* p){assert(p);++odeCalls;return true;}
void dBodyEnable(void*p){assert(p);++odeCalls;}
void FixBody(void*p){assert(p);++fixCalls;}
struct Interpolation {
 void GetPosition(Fvector&,int){++odeCalls;}void GetRotation(Fquaternion&,int){++odeCalls;}
 void SetPosition(const Fvector&,int){++odeCalls;}void SetRotation(const Fquaternion&,int){++odeCalls;}
};
struct Disabling {void Reinit(){}};using CPHDisablingFull=Disabling;
struct CPHElement:Disabling {
 bool active=true;void*m_body=this;Flags m_flags;enum{flUpdate=1,flFixed=2};
 Fmatrix mXFORM;Fvector m_mass_center;u16 m_SelfID=0;CPHShell*m_shell=nullptr;Interpolation m_body_interpolation;
 int queries=0;bool isActive()const{return active;}
 void GetGlobalTransformDynamic(Fmatrix*m){assert(active&&m_body);++queries;m->c.x=30;}
 void InterpolateGlobalTransform(Fmatrix*m){assert(active&&m_body);++queries;m->c.x=31;}
 IPhysicsShellHolder*PhysicsRefObject(){return nullptr;}
 void GetGlobalPositionDynamic(Fvector*v){assert(active);v->x=10;}
 void getQuaternion(Fquaternion&q){assert(active);q.w=1;}
 void get_LinearVel(Fvector&v){v.x=2;}void get_AngularVel(Fvector&v){v.y=3;}
 void getForce(Fvector&v){v.x=4;}void getTorque(Fvector&v){v.x=5;}
 void SetGlobalPositionDynamic(const Fvector&){assert(active);++odeCalls;}
 void setQuaternion(const Fquaternion&){assert(active);++odeCalls;}
 void set_LinearVel(const Fvector&){assert(active);++odeCalls;}
 void set_AngularVel(const Fvector&){assert(active);++odeCalls;}
 void setForce(const Fvector&){assert(active);++odeCalls;}
 void setTorque(const Fvector&){assert(active);++odeCalls;}
 void Disable(){assert(active);++odeCalls;}
 void get_State(SPHNetState&);void set_State(const SPHNetState&);void Fix();
};
struct CPHShell {
 std::vector<CPHElement*>elements;using ELEMENT_CI=std::vector<CPHElement*>::const_iterator;using ELEMENT_I=std::vector<CPHElement*>::iterator;
 Fmatrix mXFORM,m_object_in_root;int m_active_count=0;IKinematics k;
 IKinematics*PKinematics(){return &k;}CPHElement& root_element(){return *elements.front();}
 void EnableObject(int){}void DisableObject(){}
 void GetGlobalTransformDynamic(Fmatrix*);void InterpolateGlobalTransform(Fmatrix*);
};
''' + dynamic + interpolate + state + fix + r'''
struct CSE_PHSkeleton {virtual ~CSE_PHSkeleton()=default;enum{flSavedData=1};Flags _flags;};
struct CSE_ALifeCar:CSE_PHSkeleton{
 struct SDoorState{int value;};struct SWheelState{int value;};
 std::vector<SDoorState>door_states;std::vector<SWheelState>wheel_states;
};
template<class T>using xr_vector=std::vector<T>;template<class K,class V>using xr_map=std::map<K,V>;
template<class T,class U>T smart_cast(U*p){return dynamic_cast<T>(p);}
int messages=0;void Msg(const char*,const char*){++messages;}
struct CPHSkeleton{int restored=0;void RestoreNetState(CSE_PHSkeleton*p){++restored;p->_flags.set(CSE_PHSkeleton::flSavedData,false);}};
struct CCar:CPHSkeleton{
 struct SDoor{int applied=0;void RestoreNetState(const CSE_ALifeCar::SDoorState&s){applied=s.value;}};
 struct SWheel{int applied=0;void RestoreNetState(const CSE_ALifeCar::SWheelState&s){applied=s.value;}};
 xr_map<u16,SDoor>m_doors;xr_map<u16,SWheel>m_wheels_map;int defaults=0;
 std::string cNameSect(){return "dcp_test";}
 void SetDefaultNetState(CSE_PHSkeleton*p){assert(!p->_flags.test(CSE_PHSkeleton::flSavedData));++defaults;}
 void RestoreNetState(CSE_PHSkeleton*);
};
''' + restore + r'''
struct SteeringWheel{float GetSteerAngle(){return .5f;}};
float steering(std::vector<SteeringWheel> m_steering_wheels,float m_steer_angle){
''' + steer + r'''
 return m_steer_angle;
}
int main(){
 assert(steering({},99.f)==0.f);assert(steering({{}},0.f)==.05f);
 CPHShell shell;CPHElement root,door;root.m_shell=&shell;door.m_shell=&shell;
 door.active=false;door.m_body=nullptr;door.mXFORM.c.x=7;door.m_mass_center.x=2;
 shell.elements={&root,&door};shell.k.pose.c.x=4;shell.m_object_in_root.c.x=1;
 // Actual crash path: Spawn -> default door close -> whole-shell query.
 Fmatrix result;shell.GetGlobalTransformDynamic(&result);
 assert(result.c.x==31&&root.queries==1&&door.queries==0&&door.mXFORM.c.x==7);
 shell.InterpolateGlobalTransform(&result);assert(result.c.x==32&&door.queries==0);
 SPHNetState packet;packet.force.x=99;packet.quaternion.w=99;
 door.get_State(packet);assert(!packet.enabled&&packet.position.x==38&&packet.previous_position.x==38);
 assert(packet.quaternion.w==1&&packet.previous_quaternion.w==1&&packet.force.x==0&&packet.torque.x==0);
 assert(packet.linear_vel.x==0&&packet.angular_vel.y==0&&odeCalls==0);
 door.set_State(packet);assert(odeCalls==0&&door.m_flags.value==0);
 door.Fix();assert(fixCalls==0&&door.m_flags.test(CPHElement::flFixed));
 // Reopening restores an actual body; both the physics and network paths run.
 door.active=true;door.m_body=&door;door.m_flags.value=0;
 shell.GetGlobalTransformDynamic(&result);assert(door.queries==1);
 door.get_State(packet);assert(packet.enabled&&packet.position.x==10&&packet.force.x==4);
 int calls=odeCalls;door.set_State(packet);assert(odeCalls>calls);door.Fix();assert(fixCalls==1);
 CCar car;car.m_doors[0]={};car.m_doors[1]={};car.m_wheels_map[0]={};
 CSE_ALifeCar saved;saved._flags.value=1;saved.door_states={{11}};saved.wheel_states={{12}};
 car.RestoreNetState(&saved);assert(car.defaults==1&&car.m_doors[0].applied==0&&messages==1);
 saved._flags.value=1;saved.door_states={{11},{12},{13}};
 car.RestoreNetState(&saved);assert(car.defaults==2&&messages==2);
 saved._flags.value=1;saved.door_states={{11},{12}};
 car.RestoreNetState(&saved);assert(car.m_doors[0].applied==11&&car.m_doors[1].applied==12&&car.m_wheels_map[0].applied==12);
 car.RestoreNetState(&saved);assert(car.restored==3); // cleared flag: no double restore
 CSE_PHSkeleton noncar;noncar._flags.value=1;car.RestoreNetState(&noncar);
 std::puts("PASS actual car lifecycle: closed door spawn/interpolation, complete finite inactive state, no freed ODE access, reopen, replica fix, shorter/longer/matching saves and repeated restore");
}
'''
with TemporaryDirectory(prefix='car-lifecycle-') as temporary:
    folder=Path(temporary)
    cpp,exe=folder/'car.cpp',folder/('car.exe' if os.name=='nt' else 'car')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc',str(cpp),'/Fe:'+str(exe)] if os.name=='nt'
             else ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True)

# Destruction must skip the already deactivated bodies/joints and release
# queued SDoor pointers before their owning map. No game is launched here.
deactivate=between('src/xrPhysics/PHShellActivate.cpp','void CPHShell::Deactivate()','void CPHShell::ActivatingBonePoses(')
assert 'if ((*i)->isActive()) (*i)->Deactivate();' in deactivate
assert 'if ((*j)->bActive) (*j)->Deactivate();' in deactivate
destroy=between('src/xrGame/Car.cpp','void CCar::net_Destroy()','void CCar::net_Save(')
assert destroy.index('m_doors_update.clear();') < destroy.index('m_doors.clear();')
