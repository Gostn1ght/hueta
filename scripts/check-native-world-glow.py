"""CI-only execution of the production dropped chemical-light update."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
text=(root/'src/xrGame/Flashlight.cpp').read_text(encoding='utf-8')
start=text.index('bool CFlashlight::UpdateWorldGlow()')
end=text.index('void CFlashlight::UpdateCL()',start)
body=text[start:end]
assert text.index('if (UpdateWorldGlow()) return;',end)<text.index('if (!actor)',end)
for role in ('client','server'):
    config=(root/f'scripts/netcoop-overlay/{role}/configs/mod_system_zzzzzzzz_netcoop_devices.ltx').read_text(encoding='utf-8')
    assert config.count('netcoop_world_glow = true')==4
source=r'''
#include <cassert>
#include <cmath>
#include <cstdio>
#include <algorithm>
using u16=unsigned short;constexpr u16 BI_NONE=65535;
template<class T>T _max(T a,T b){return std::max(a,b);}
struct Vec{float x=0,y=0,z=0;bool operator==(const Vec& v)const{return x==v.x&&y==v.y&&z==v.z;}};
struct Fmatrix{Vec c,k,i;void mul_43(const Fmatrix& a,const Fmatrix& b){c={a.c.x+b.c.x,a.c.y+b.c.y,a.c.z+b.c.z};k=a.k;i=a.i;}};
struct Bone{Fmatrix mTransform;};
struct IKinematics{Bone bone;u16 id=BI_NONE;unsigned calculated=0;u16 LL_BoneID(int){return id;}void CalculateBones(){++calculated;}Bone& LL_GetBoneInstance(u16){return bone;}};
template<class T>T smart_cast(IKinematics* v){return static_cast<T>(v);}
struct Name{bool set=false;unsigned size()const{return set?1:0;}operator int()const{return 0;}};
struct Light{bool hud=true,active=false;Vec pos,dir;void set_hud_mode(bool v){hud=v;}void set_position(Vec v){pos=v;}void set_rotation(Vec k,Vec){dir=k;}void set_direction(Vec v){dir=v;}};
namespace netcoop{bool enabled_value=true,client=true;bool enabled(){return enabled_value;}bool pure_client(){return client;}}
struct{float fTimeDelta=.02f;}Device;
struct CFlashlight{
 bool m_netcoop_world_glow=true,m_bWorking=false,parent=false,destroyed=false;float m_netcoop_world_drain=.001f,condition=.5f;
 Light a,b,g;Light*light_render=&a,*light_omni=&b,*glow_render=&g;Name light_trace_bone;
 IKinematics visual;Fmatrix transform;unsigned moved=0,toggles=0;
 void*H_Parent(){return parent?this:nullptr;}float GetCondition(){return condition;}
 void ChangeCondition(float d){condition=std::max(0.f,std::min(1.f,condition+d));}
 bool getDestroy(){return destroyed;}void TurnDeviceInternal(bool v){++toggles;m_bWorking=v;a.active=b.active=g.active=v;}
 void UpdateXForm(){++moved;}Fmatrix XFORM(){return transform;}IKinematics*Visual(){return &visual;}
 bool UpdateWorldGlow();
};
'''+body+r'''
int main(){CFlashlight stick;stick.transform.c={3,4,5};stick.transform.k={0,0,1};
 assert(stick.UpdateWorldGlow()&&stick.m_bWorking&&stick.a.active&&stick.g.active);
 assert(!stick.a.hud&&!stick.b.hud&&stick.a.pos==stick.transform.c&&stick.g.pos==stick.transform.c);
 const float charge=stick.condition;for(int i=0;i<1000;++i)stick.UpdateWorldGlow();assert(stick.condition==charge);
 assert(stick.toggles==1); // stable replicas never repeatedly toggle their emitters
 netcoop::client=false;for(int i=0;i<1000;++i)stick.UpdateWorldGlow();assert(std::abs(stick.condition-(charge-.02f))<.0001f);
 stick.condition=.01f;assert(stick.UpdateWorldGlow()&&!stick.m_bWorking&&!stick.a.active&&!stick.g.active);
 stick.condition=.8f;stick.destroyed=true;assert(stick.UpdateWorldGlow()&&!stick.m_bWorking);
 stick.destroyed=false;stick.parent=true;unsigned moved=stick.moved;assert(!stick.UpdateWorldGlow()&&stick.moved==moved);
 stick.parent=false;stick.m_netcoop_world_glow=false;assert(!stick.UpdateWorldGlow());
 stick.m_netcoop_world_glow=true;netcoop::enabled_value=false;assert(!stick.UpdateWorldGlow());netcoop::enabled_value=true;
 stick.visual.id=2;stick.light_trace_bone.set=true;stick.visual.bone.mTransform.c={1,2,3};
 assert(stick.UpdateWorldGlow()&&stick.visual.calculated==1&&stick.a.pos==Vec({4,6,8}));
 puts("PASS actual world glow: same object, no client drain, authority drain, expiration, detach/held, ordinary/offline exclusion, world bone transform");}
'''
with TemporaryDirectory() as directory:
    folder=Path(directory);cpp=folder/'glow.cpp';exe=folder/('glow.exe' if os.name=='nt' else 'glow')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True);subprocess.run([str(exe)],cwd=folder,check=True,timeout=10)
