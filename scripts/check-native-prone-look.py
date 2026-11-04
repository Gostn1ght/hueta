"""CI-only execution of actual prone look gates/callbacks; no game process."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
text = (root / 'src/xrGame/ActorAnimation.cpp').read_text(encoding='utf-8-sig')


def method(signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


constants = text[text.index('static const float y_spin0_factor'):text.index('CBlend* PlayMotionByParts')]
source = r'''
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include <initializer_list>
#define VERIFY(x) assert(x)
float deg2rad(float v){return v*3.14159265358979323846f/180.f;}
bool _valid(float v){return std::isfinite(v);}
template<class T>void clamp(T&v,T lo,T hi){if(v<lo)v=lo;if(v>hi)v=hi;}
float angle_normalize_signed(float v){return std::remainder(v,deg2rad(360.f));}
struct Fvector{float x=0,y=0,z=0;};
// Capture the real callback's transform calls. Full engine math/build is
// verified separately; this harness checks gates, angles and pivot retention.
struct Fmatrix{
 Fvector c;float pitch=0,yaw=0,roll=0;unsigned writes=0;
 void setXYZ(float p,float y,float r){pitch=p;yaw=y;roll=r;}
 void setHPB(float y,float p,float r){setXYZ(p,y,r);}
 void mulA_43(const Fmatrix& s){pitch+=s.pitch;yaw+=s.yaw;roll+=s.roll;++writes;c={99,99,99};}
};
struct CBoneInstance{Fmatrix mTransform;void* actor=nullptr;void* callback_param(){return actor;}};
enum {eflDisabled=0};
struct CActor{
 bool prone=false,seated=false,alive=true,m_bAnimTorsoPlayed=false;
 float r_model_yaw=0,r_model_yaw_delta=0;struct {float yaw=0,pitch=0,roll=0;} r_torso;
 int cam_freelook=eflDisabled;struct Camera{float yaw=0;} camera;
 Camera* cam_FirstEye(){return &camera;}
 bool netcoop_authored_pose(){return prone||seated;}bool netcoop_seated(){return seated;}bool g_Alive(){return alive;}
 static void Spin0Callback(CBoneInstance*);static void Spin1Callback(CBoneInstance*);
 static void ShoulderCallback(CBoneInstance*);static void HeadCallback(CBoneInstance*);static void VehicleHeadCallback(CBoneInstance*);
};
''' + constants + method('static void netcoop_prone_look(') + '\n'.join(method('void CActor::' + n + '(') for n in (
    'Spin0Callback', 'Spin1Callback', 'ShoulderCallback', 'HeadCallback', 'VehicleHeadCallback')) + r'''
bool near(float a,float b){return std::abs(a-b)<.00001f;}
void pivot(CBoneInstance&b){assert(b.mTransform.c.x==1&&b.mTransform.c.y==2&&b.mTransform.c.z==3);}
CBoneInstance bone(CActor&a){CBoneInstance b;b.actor=&a;b.mTransform.c={1,2,3};return b;}
int main(){
 CActor a;a.prone=true;a.r_torso.pitch=deg2rad(20);a.r_torso.yaw=deg2rad(12);
 // r_torso is {yaw,pitch,roll} in the engine, not a position vector.
 auto shoulder=bone(a),head=bone(a),hip=bone(a),spine=bone(a);
 CActor::ShoulderCallback(&shoulder);CActor::HeadCallback(&head);
 assert(shoulder.mTransform.writes==1&&head.mTransform.writes==0);
 assert(near(shoulder.mTransform.yaw,deg2rad(12)));
 assert(near(shoulder.mTransform.pitch,-deg2rad(20)));
 assert(near(head.mTransform.yaw+shoulder.mTransform.yaw,deg2rad(12)));
 assert(near(head.mTransform.pitch+shoulder.mTransform.pitch,-deg2rad(20)));
 pivot(shoulder);pivot(head);
 CActor::Spin0Callback(&hip);CActor::Spin1Callback(&spine);
 assert(!hip.mTransform.writes&&!spine.mTransform.writes);pivot(hip);pivot(spine);
 for(float sign:{-1.f,1.f}){
  a.r_torso.yaw=sign*deg2rad(150);a.r_torso.pitch=sign*deg2rad(80);
  auto b=bone(a);CActor::ShoulderCallback(&b);pivot(b);
  assert(near(b.mTransform.yaw,sign*deg2rad(45)));
  assert(near(b.mTransform.pitch,-sign*deg2rad(30)));
 }
 for(int gate=0;gate<3;++gate){
  a.seated=gate==0;a.alive=gate!=1;a.m_bAnimTorsoPlayed=gate==2;
  auto s=bone(a),h=bone(a);CActor::ShoulderCallback(&s);CActor::HeadCallback(&h);
  assert(!s.mTransform.writes&&!h.mTransform.writes);pivot(s);pivot(h);
 }
 a.seated=false;a.alive=true;a.m_bAnimTorsoPlayed=false;
 for(float bad:{std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity()}){
  auto b=bone(a);netcoop_prone_look(&b,bad,0,.85f);netcoop_prone_look(&b,0,bad,.85f);
  assert(!b.mTransform.writes);pivot(b);
 }
 a.prone=false;a.r_torso.yaw=.2f;a.r_torso.pitch=.1f;a.r_torso.roll=0;
 auto standing=bone(a);CActor::ShoulderCallback(&standing);
 assert(near(standing.mTransform.yaw,.2f*y_shoulder_factor));
 assert(near(standing.mTransform.pitch,-.1f*p_shoulder_factor));pivot(standing);
 puts("PASS actual prone look callbacks: hips fixed, bounded chest/head aim, seated/dead/action exclusions, finite inputs and standing path");
}
'''
with TemporaryDirectory() as temporary:
    cpp = Path(temporary) / 'prone.cpp'
    exe = Path(temporary) / ('prone.exe' if os.name == 'nt' else 'prone')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', str(cpp), '/Fe:' + str(exe)] if os.name == 'nt' else
               ['g++', '-std=c++17', '-fsanitize=address,undefined', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=temporary, check=True)
    subprocess.run([str(exe)], cwd=temporary, check=True, timeout=15)
