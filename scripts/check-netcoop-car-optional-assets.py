"""CI-only actual car optional damage/exhaust code, including absent assets."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
car=(root/'src/xrGame/Car.cpp').read_text(encoding='utf8')
damage=car[car.index('\tif (ini->section_exist("damage_items"))'):car.index('\tif (ini->section_exist("immunities"))')]
exhaust=(root/'src/xrGame/CarExhaust.cpp').read_text(encoding='utf8')
exhaust=exhaust[exhaust.index('void CCar::SExhaust::Init()'):]
source=r'''
#include <cassert>
#include <map>
#include <string>
#include <vector>
#include <set>
#include <cstdlib>
#include <cstdio>
using u16=unsigned short;using u32=unsigned;using LPCSTR=const char*;
template<class K,class V>using xr_map=std::map<K,V>;
template<class T,class P>T smart_cast(P* p){return dynamic_cast<T>(p);}
void Msg(const char*,...){}
#define VERIFY(x) assert(x)
constexpr bool FALSE=false;constexpr u16 BI_NONE=0xffff;
bool g_dedicated_server=false;
struct Text {std::string s;Text(LPCSTR v=""):s(v){}LPCSTR operator*()const{return s.c_str();}LPCSTR c_str()const{return s.c_str();}};
struct Fvector {void set(float,float,float){}};
struct Fmatrix {void set(const Fmatrix&){}void mulB_43(const Fmatrix&){} };
struct Element {void InterpolateGlobalTransform(Fmatrix*){}void GetPointVel(Fvector&,Fvector&){} };
struct Transform:Fmatrix {Fvector c;};
// Match the real Fmatrix member used by exhaust Update.
struct Matrix {Fvector c;void set(const Matrix&){}void mulB_43(const Matrix&){} };
struct PhysElement {void InterpolateGlobalTransform(Matrix*){}void GetPointVel(Fvector&,Fvector&){} };
struct Physics {bool Processing()const{return false;}}physics;
Physics* physics_world(){return &physics;}
struct CBoneData {Matrix bind_transform;};
struct IKinematics {virtual ~IKinematics()=default;CBoneData bone;u16 LL_BoneID(LPCSTR name){return std::string(name)=="wheel"?1:std::string(name)=="door"?2:std::string(name)=="back_door"?3:BI_NONE;}CBoneData& LL_GetData(u16){return bone;}}kinematics;
struct CInifile {
 using Item=std::pair<Text,Text>;struct Sect{std::vector<Item>Data;};using SectCIt=std::vector<Item>::const_iterator;
 Sect data;bool section_exist(LPCSTR){return true;}Sect& r_section(LPCSTR){return data;}
};
struct CDamagableHealthItem {float health=0;int kind=0;void Init(float h,int k){health=h;kind=k;}};
struct SWheel:CDamagableHealthItem{};struct SDoor:CDamagableHealthItem{};
std::set<std::string> available;std::vector<std::string> created;
struct CParticlesObject {
 int updates=0,plays=0,stops=0;
 static bool IsAvailable(LPCSTR name){return !g_dedicated_server && name && available.count(name)!=0;}
 static CParticlesObject* Create(LPCSTR name,bool){assert(IsAvailable(name));created.emplace_back(name);return new CParticlesObject;}
 static void Destroy(CParticlesObject*& p){delete p;p=nullptr;}
 void UpdateParent(const Matrix&,const Fvector&){++updates;}void Play(bool){++plays;}void Stop(){++stops;}
};
struct BoneElement{PhysElement* element=nullptr;};std::map<u16,BoneElement>bone_map;
struct CCar {
 Text m_exhaust_particles;std::map<u16,SWheel>m_wheels_map;std::map<u16,SDoor>m_doors;
 IKinematics* Visual(){return &kinematics;}Text cNameSect(){return Text("fixture_car");}Matrix matrix;Matrix& XFORM(){return matrix;}
 void damage(CInifile* ini){auto* pKinematics=&kinematics;
''' + damage + r'''
 }
 struct SExhaust {CCar* pcar=nullptr;u16 bone_id=7;PhysElement* pelement=nullptr;Matrix transform;CParticlesObject* p_pgobject=nullptr;
 void Init();void Update();void Clear();void Play();void Stop();~SExhaust(){Clear();}};
};
''' + exhaust.replace('Fmatrix global_transform;', 'Matrix global_transform;') + r'''
int main(){
 CCar car;car.m_wheels_map[1]={};car.m_doors[2]={};
 CInifile ini;ini.data.Data={{Text("wheel"),Text("35")},{Text("door"),Text("70")},{Text("back_door"),Text("90")},{Text("absent"),Text("100")}};
 car.damage(&ini);assert(car.m_wheels_map.at(1).health==35 && car.m_wheels_map.at(1).kind==2);
 assert(car.m_doors.at(2).health==70 && car.m_doors.at(2).kind==1 && car.m_doors.size()==1);
 PhysElement element;bone_map[7].element=&element;
 car.m_exhaust_particles=Text("vehiclefx\\exhausts\\exhaust_kamaz");
 {CCar::SExhaust e;e.pcar=&car;e.Init();e.Update();e.Play();e.Stop();assert(!e.p_pgobject && created.empty());}
 available.insert("vehiclefx\\exhaust_1");
 {CCar::SExhaust e;e.pcar=&car;e.Init();assert(e.p_pgobject && created.back()=="vehiclefx\\exhaust_1");e.Play();e.Update();e.Stop();assert(e.p_pgobject->plays==1 && e.p_pgobject->stops==1);}
 car.m_exhaust_particles=Text("valid");available.insert("valid");
 {CCar::SExhaust e;e.pcar=&car;e.Init();assert(e.p_pgobject && created.back()=="valid");e.Clear();e.Clear();e.Update();e.Stop();}
 const auto count=created.size();g_dedicated_server=true;
 {CCar::SExhaust e;e.pcar=&car;e.Init();e.Play();e.Stop();assert(!e.p_pgobject && created.size()==count);}
 g_dedicated_server=false;bone_map.clear();
 {CCar::SExhaust e;e.pcar=&car;e.Init();e.Update();e.Play();e.Stop();assert(!e.p_pgobject && created.size()==count);}
 puts("PASS actual car optional assets: absent back_door/bone skipped, wheel/door damage preserved, missing exhaust fallback, no fallback, headless and null-safe lifecycle");
}
'''
with TemporaryDirectory(prefix='car-assets-') as tmp:
    p=Path(tmp);cpp=p/'check.cpp';exe=p/'check.exe';cpp.write_text(source,encoding='utf8')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe),'/Fo:'+str(p/'check.obj')],cwd=tmp,check=True)
    subprocess.run([str(exe)],cwd=tmp,check=True,timeout=30)
