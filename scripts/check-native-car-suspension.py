"""CI-only DCP profile adapter reaches the actual ODE joint coefficients."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def method(path, signature):
    text=(ROOT/path).read_text(encoding='utf-8')
    start=text.index(signature)
    brace=text.index('{',start)
    depth,end=1,brace+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}')
        end+=1
    return text[start:end]


source=r'''
#include <cassert>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <map>
#include <string>
#include <limits>
#include <initializer_list>
using u32=uint32_t;using LPCSTR=const char*;
bool _valid(float x){return std::isfinite(x);}
float fixed_step=.01f;const float hinge2_spring=20000,hinge2_damping=1000;
const float world_spring=10000,world_damping=100;
float CFM(float k,float d){return 1.f/(fixed_step*k+d);}
float ERP(float k,float d){return fixed_step*k/(fixed_step*k+d);}
enum JointType{hinge2,ball,hinge,full_control,slider};
struct CPhysicsJoint{virtual ~CPhysicsJoint()=default;virtual bool IsWheelJoint()=0;virtual void SetJointSDfactors(float,float)=0;};
struct CPHJoint:CPhysicsJoint{
 JointType eType=hinge2;bool bActive=true;float m_cfm=0,m_erp=0;unsigned writes=0;
 bool IsWheelJoint()override{return eType==hinge2;}
 void SetJointSDfactorsActive(){++writes;}
 void SetJointSDfactors(float,float)override;
};
struct CInifile{
 std::map<std::pair<std::string,std::string>,float> values;
 bool line_exist(LPCSTR s,LPCSTR k){return values.count({s,k})!=0;}
 float r_float(LPCSTR s,LPCSTR k){return values.at({s,k});}
 void set(LPCSTR section,LPCSTR key,float value){values[{section,key}]=value;}
};
'''+method('src/xrPhysics/PHJoint.cpp','void CPHJoint::SetJointSDfactors(')+'\n'+method(
    'src/xrGame/CarWheels.cpp','static bool car_apply_suspension_profile(')+r'''
int main(){
 CInifile ini;CPHJoint joint;
 assert(!car_apply_suspension_profile(&ini,&joint,"wheel")&&joint.writes==0);
 ini.set("wheels_params","spring_factor",2);ini.set("wheels_params","damping_factor",3);
 assert(!car_apply_suspension_profile(&ini,&joint,"wheel")&&joint.writes==0);
 ini.set("wheels_params","suspension_spring_factor",1);
 ini.set("wheels_params","suspension_damping_factor",5);
 // Representative validated DCP factors; physical-step ERP/CFM, not a
 // rendering/contact friction multiplier or position/velocity override.
 for(float step:{.01f,1.f/60.f,1.f/120.f}){
  fixed_step=step;assert(car_apply_suspension_profile(&ini,&joint,"wheel"));
  assert(std::fabs(joint.m_cfm-1.f/(step*20000.f+5000.f))<1e-9f);
  assert(std::fabs(joint.m_erp-(step*20000.f)/(step*20000.f+5000.f))<1e-6f);
 }
 ini.set("wheels_params","suspension_distance",.25f);
 for(float mass:{600.f,1500.f,3500.f,12000.f}){
  assert(car_apply_suspension_profile(&ini,&joint,"wheel",mass,4));
  const float k=joint.m_erp/(joint.m_cfm*fixed_step);
  assert((mass/4)*9.81f/k<=.0751f);
 }
 ini.values.erase({"wheels_params","suspension_distance"});
 ini.set("wheel","suspension_spring_factor",2);
 assert(car_apply_suspension_profile(&ini,&joint,"wheel"));
 assert(std::fabs(joint.m_erp-ERP(hinge2_spring*2,hinge2_damping*5))<1e-6f);
 const unsigned writes=joint.writes;
 for(float bad:{0.f,-1.f,101.f,std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity()}){
  ini.set("wheel","suspension_damping_factor",bad);
  assert(!car_apply_suspension_profile(&ini,&joint,"wheel")&&joint.writes==writes);
 }
 joint.eType=hinge;assert(!car_apply_suspension_profile(&ini,&joint,"wheel"));
 assert(!car_apply_suspension_profile(nullptr,&joint,"wheel"));
 assert(!car_apply_suspension_profile(&ini,nullptr,"wheel"));
 std::puts("PASS actual DCP suspension adapter and ODE ERP/CFM: optional legacy, per-wheel override, fixed-step scaling, invalid profile rejection; no driving claim");
}
'''
wheel=(ROOT/'src/xrGame/CarWheels.cpp').read_text(encoding='utf-8')
assert 'car->PPhysicsShell()->getMass(),u32(car->m_wheels_map.size())' in wheel
if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native compilation is permitted only in GitHub Actions')
with TemporaryDirectory(prefix='car-suspension-') as temporary:
    folder=Path(temporary)
    cpp,exe=folder/'suspension.cpp',folder/('suspension.exe' if os.name=='nt' else 'suspension')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
             ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=10)
