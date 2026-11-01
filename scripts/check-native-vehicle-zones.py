"""Actual car bone impulses, direct gravitational pull and gravity switching."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]


def method(path, signature):
    text=(ROOT/path).read_text(encoding='utf-8');start=text.index(signature)
    brace=text.index('{',start);depth,end=1,brace+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]


source=r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
using u16=uint16_t;using BOOL=bool;constexpr bool TRUE=true;
template<class T>T _min(T a,T b){return std::min(a,b);}
template<class T>T _max(T a,T b){return std::max(a,b);}
bool _valid(float f){return std::isfinite(f);}bool fis_zero(float f){return std::abs(f)<1e-6f;}
namespace ALife{enum EHitType{eHitTypeStrike,eHitTypeFireWound};}
namespace netcoop{bool active=true;bool enabled(){return active;}}
struct Fvector {
 float x=0,y=0,z=0;
 Fvector& set(const Fvector& v){*this=v;return *this;}
 Fvector& mul(float f){x*=f;y*=f;z*=f;return *this;}
 float magnitude(){return std::sqrt(x*x+y*y+z*z);}
 Fvector& random_point(float){return *this;}Fvector& random_dir(){return *this;}
};
struct CPhysicsElement {
 float mass=10;u16 m_SelfID=1;bool isActive(){return true;}float getMass(){return mass;}
 float getRadius(){return 1;}void applyImpulseTrace(Fvector,Fvector,float,u16){}
};
struct CPhysicsShell {
 bool gravity=true;unsigned writes=0,hits=0;float last=0;CPhysicsElement root,door;
 CPhysicsShell(){root.mass=1000;}
 bool isActive(){return true;}float getMass(){return 2000;}
 void set_ApplyByGravity(bool v){gravity=v;++writes;}bool get_ApplyByGravity(){return gravity;}
 CPhysicsElement* get_Element(u16 id){return id==0?&root:id==1?&door:nullptr;}
 CPhysicsElement* get_ElementByStoreOrder(u16){return &door;}u16 get_ElementsNumber(){return 2;}
 void applyHit(const Fvector&,const Fvector&,float impulse,u16,ALife::EHitType){last=impulse;++hits;}
};
struct Movement {
 enum{peOnGround=0};unsigned writes=0;
 void SetApplyGravity(BOOL){++writes;}void SetForcedPhysicsControl(bool){}
 int Environment(){return peOnGround;}void GroundNormal(Fvector&){}
 float GetMass(){return 80;}void ApplyImpulse(Fvector,float){}
};
using CPHMovementControl=Movement;
struct Support{Movement move;Movement* movement(){return &move;}};
struct CPhysicsShellHolder {
 virtual ~CPhysicsShellHolder()=default;CPhysicsShell shell;bool destroyed=false;
 bool getDestroy(){return destroyed;}CPhysicsShell* PPhysicsShell(){return &shell;}
};
struct CEntityAlive:CPhysicsShellHolder {
 bool alive=true;Support support;bool g_Alive(){return alive;}Support* character_physics_support(){return &support;}
};
struct CActor:CEntityAlive{};
struct CCustomZone:CPhysicsShellHolder{};
template<class T>T smart_cast(CPhysicsShellHolder* p){return dynamic_cast<T>(p);}
struct Bone{u16 parent=0;u16 GetParentID(){return parent;}};
struct IKinematics {
 Bone bones[3];IKinematics(){bones[2].parent=1;}
 u16 LL_BoneCount(){return 3;}Bone& LL_GetData(u16 id){return bones[id];}
};
IKinematics* smart_cast_model(IKinematics* p){return p;}
template<class T>T smart_cast(IKinematics* p){return smart_cast_model(p);}
struct SHit {
 float impulse=10000;u16 boneID=2;CPhysicsShellHolder* who=nullptr;ALife::EHitType hit_type=ALife::eHitTypeFireWound;
 Fvector dir{1,0,0},position;
 u16 bone(){return boneID;}const Fvector& direction(){return dir;}float phys_impulse(){return impulse;}
 const Fvector& bone_space_position(){return position;}ALife::EHitType type(){return hit_type;}
};
struct CPHUpdateObject{static bool IsActive(){return true;}};
struct CCar:CPhysicsShellHolder {
 CPhysicsShell* m_pPhysicsShell=&shell;u16 m_bone_steer=99;IKinematics fixture_model;
 IKinematics* Visual(){return &fixture_model;}float GravityFactorImpulse(){return .5f;}void PHHit(SHit&);
};
struct SZoneObjectInfo{CPhysicsShellHolder* object;bool nonalive_object=true;};
struct CBaseGraviZone {
 unsigned alive_pulls=0,dead_pulls=0;
 void AffectPull(CPhysicsShellHolder*,const Fvector&,float);
 void AffectPullAlife(CEntityAlive*,const Fvector&,float){++alive_pulls;}
 void AffectPullDead(CPhysicsShellHolder*,const Fvector&,float){++dead_pulls;}
};
struct CNoGravityZone{void switchGravity(SZoneObjectInfo&,bool);};
struct RandomType{int randI(int a,int){return a;}}Random;
struct PhysicsWorld{float Gravity(){return 9.81f;}}fixture_physics;
PhysicsWorld* physics_world(){return &fixture_physics;}float fixed_step=.02f;
'''
source+='\n'+method('src/xrGame/Car.cpp','void CCar::PHHit(')
source+='\n'+method('src/xrGame/GraviZone.cpp','void CBaseGraviZone::AffectPull(')
source+='\n'+method('src/xrGame/NoGravityZone.cpp','void CNoGravityZone::switchGravity(')
source+=r'''
int main(){
 CCar car;SHit hit;car.PHHit(hit);assert(hit.impulse==80&&car.shell.last==80);
 hit.impulse=10000;hit.boneID=0;car.PHHit(hit);assert(hit.impulse==8000);
 CActor player;hit.boneID=2;hit.who=&player;hit.hit_type=ALife::eHitTypeStrike;
 hit.impulse=10000;car.PHHit(hit);assert(hit.impulse==1&&car.shell.last==1);
 CCustomZone anomaly;hit.who=&anomaly;hit.impulse=10000;
 unsigned before=car.shell.hits;car.PHHit(hit);assert(hit.impulse==0&&car.shell.hits==before);
 hit.who=nullptr;hit.impulse=std::numeric_limits<float>::quiet_NaN();car.PHHit(hit);assert(hit.impulse==0);
 hit.impulse=-100;car.PHHit(hit);assert(hit.impulse==0);
 netcoop::active=false;hit.impulse=10000;car.PHHit(hit);assert(hit.impulse==10000);netcoop::active=true;
 CBaseGraviZone gravi;Fvector direction{0,1,0};
 gravi.AffectPull(&car,direction,2);assert(gravi.dead_pulls==0&&gravi.alive_pulls==0);
 gravi.AffectPull(&player,direction,2);assert(gravi.alive_pulls==1);
 CPhysicsShellHolder prop;gravi.AffectPull(&prop,direction,2);assert(gravi.dead_pulls==1);
 CNoGravityZone no_gravity;SZoneObjectInfo object{&car};
 car.shell.gravity=false;no_gravity.switchGravity(object,false);assert(car.shell.gravity);
 no_gravity.switchGravity(object,true);assert(car.shell.gravity);
 object.object=&prop;no_gravity.switchGravity(object,false);assert(!prop.shell.gravity);
 no_gravity.switchGravity(object,true);assert(prop.shell.gravity);
 netcoop::active=false;object.object=&car;no_gravity.switchGravity(object,false);assert(!car.shell.gravity);
 gravi.AffectPull(&car,direction,2);assert(gravi.dead_pulls==2);
 std::puts("PASS actual car hit/zone methods: physical bone mass, finite impulses, no anomalous lift/gravity switch for transport, player/prop and freeplay behavior retained");
}
'''
gravi=(ROOT/'src/xrGame/GraviZone.cpp').read_text(encoding='utf-8')
activation=gravi[gravi.index('if (m_dwTeleTime > m_dwTimeToTele + m_dwTelePause)'):gravi.index('bool CBaseGraviZone::CheckAffectField')]
assert '!(netcoop::enabled() && smart_cast<CCar*>(GO))' in activation
assert 'AffectThrow(O, GO, throw_in_dir, dist)' in gravi,'anomaly damage path must remain'
if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native compilation is permitted only in GitHub Actions')
with TemporaryDirectory(prefix='vehicle-zones-') as temporary:
    folder=Path(temporary);cpp=folder/'zones.cpp';exe=folder/('zones.exe' if os.name=='nt' else 'zones')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
             ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=10)
