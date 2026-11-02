"""CI: actual trader callback without a camera, torch guard, stable ODE drag."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os, subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]

def method(file, name):
    text = (root / file).read_text(encoding='utf-8')
    start = text.index(name); at = text.index('{', start); end = at + 1; depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}'); end += 1
    return text[start:end]

torch = method('src/xrGame/Torch.cpp', 'void CTorch::Switch(bool light_on)')
guard = torch[:torch.index('// Netcoop:')] + 'observed = light_on; }'
source = r'''
#include "stable_angular_drag.h"
#include <cassert>
#include <cstdio>
#include <limits>
struct Fvector { float x=0,y=0,z=0; void sub(const Fvector&a,const Fvector&b){x=a.x-b.x;y=a.y-b.y;z=a.z-b.z;} void getHP(float&h,float&p){h=0;p=0;} };
struct Fmatrix { unsigned changes=0; void getHPB(float&h,float&p,float&b){h=p=b=0;} void setHPB(float,float,float){} void mulB_43(const Fmatrix&){++changes;} };
float _abs(float x){return std::abs(x);} float angle_normalize_signed(float x){return x;}
struct CBoneInstance{Fmatrix mTransform;};
struct CObject { virtual ~CObject()=default; bool destroyed=false; Fvector position; unsigned reads=0; bool getDestroy(){return destroyed;} Fvector&Position(){++reads;return position;} };
struct CActor:CObject{bool seated=false;bool netcoop_seated(){return seated;}};
template<class T>T smart_cast(CObject*p){return dynamic_cast<T>(p);}
struct World{CObject* entity=nullptr;CObject*CurrentEntity(){return entity;}}world;World&Level(){return world;}
struct CAI_Trader:CObject{Fmatrix matrix;Fmatrix&XFORM(){return matrix;}void LookAtActor(CBoneInstance*);};
struct CTorch{CObject*parent=nullptr;bool observed=false;CObject*H_Parent(){return parent;}void Switch(bool light_on);};
''' + method('src/xrGame/ai/trader/ai_trader.cpp', 'void CAI_Trader::LookAtActor(') + guard + r'''
int main(){
 CAI_Trader trader;CBoneInstance head;trader.LookAtActor(&head);assert(head.mTransform.changes==0);
 CObject camera;world.entity=&camera;camera.destroyed=true;trader.LookAtActor(&head);assert(head.mTransform.changes==0&&camera.reads==0);
 camera.destroyed=false;trader.LookAtActor(&head);assert(head.mTransform.changes==1&&camera.reads==1);
 CTorch torch;torch.Switch(true);assert(torch.observed);CActor actor;torch.parent=&actor;actor.seated=true;
 torch.Switch(true);assert(!torch.observed);torch.Switch(false);assert(!torch.observed);actor.seated=false;torch.Switch(true);assert(torch.observed);
 // ODE inertia layout: a bandage's damping formerly changed +1 into -8999 rad/s.
 double tiny[12]={1e-5,0,0,0,0,2e-5,0,0,0,0,3e-5,0};
 assert(1.-.02*4.5/tiny[0] < -1000.);
 for(double request:{0.,.001,1.5,4.5,12.,1e10}) for(double dt:{.001,.02,.1}) {
  const double drag=stable_angular_drag(request,tiny,dt);assert(drag>=0&&drag<=request);
  for(int axis:{0,5,10}) {double w=20;for(int i=0;i<1000;++i){const double next=w*(1.-dt*drag/tiny[axis]);assert(next>=-1e-10&&next<=w+1e-10);w=next;}}
 }
 // Rotated 2x2 tensor: eigenvalues .00001, .001, .002; lower bound may
 // require determinant/trace rather than diagonal dominance.
 double rotated[12]={.000505,.000495,0,0,.000495,.000505,0,0,0,0,.002,0};
 auto drag=stable_angular_drag(4.5,rotated,.02);assert(drag>0&&.02*drag<=.00001);
 double bad[12]={};assert(stable_angular_drag(1.,bad,.02)==0);
 assert(stable_angular_drag(-1.,tiny,.02)==0&&stable_angular_drag(1.,tiny,0.)==0);
 assert(stable_angular_drag(std::numeric_limits<double>::infinity(),tiny,.02)==0);
 puts("PASS actual trader null/destroyed/live entity, seated torch guard, bounded drag for light and rotated ODE tensors");
}
'''
element=(root/'src/xrPhysics/PHElement.cpp').read_text(encoding='utf-8')
assert 'stable_angular_drag(k_w, mass.I, dReal(fixed_step))' in element
assert '-angular_velocity[0] * angular_drag' in element
seat=(root/'src/xrGame/netcoop_vehicle_seat.inc').read_text(encoding='utf-8')
assert 'torch->Switch(false)' in seat and 'local.c.add(m_netcoop_driver_fit)' not in seat
with TemporaryDirectory() as temporary:
    cpp=Path(temporary)/'regressions.cpp'; exe=Path(temporary)/('regressions.exe' if os.name=='nt' else 'regressions')
    cpp.write_text(source,encoding='utf-8');inc=str(root/'src/xrPhysics')
    command=(['cl','/nologo','/std:c++17','/EHsc','/I'+inc,str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
             ['g++','-std=c++17','-I',inc,str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=temporary,check=True);subprocess.run([str(exe)],cwd=temporary,check=True,timeout=15)
