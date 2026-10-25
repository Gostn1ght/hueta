"""CI-only: execute the actual car headlight loader and bone lookup."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

root = Path(__file__).resolve().parents[1]
text = (root / "src/xrGame/CarLights.cpp").read_text(encoding="utf-8-sig")


def method(signature):
    start = text.index(signature)
    begin = text.index("{", start)
    depth = 1
    end = begin + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


source = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
using LPCSTR=const char*;
using u16=unsigned short;
constexpr bool FALSE=false,TRUE=true;
static float deg2rad(float value){return value*0.017453292519943295f;}
#define READ_IF_EXISTS(ltx, method, section, name, default_value) (((ltx)->line_exist(section, name)) ? ((ltx)->method(section, name)) : (default_value))
struct Fcolor{void set(const Fcolor&) {}};
struct Fvector{float x=0,y=0,z=0;Fvector& set(float a,float b,float c){x=a;y=b;z=c;return *this;}};
struct CInifile {
 std::map<std::string,float> angles;
 std::set<std::string> strings; // spot_texture, glow_texture, type, position present
 int type=2;
 bool line_exist(LPCSTR section,LPCSTR key){assert(std::string(section)=="f1");return angles.count(key)!=0||strings.count(key)!=0;}
 int r_s32(LPCSTR,LPCSTR key){assert(std::string(key)=="type");return type;}
 Fvector r_fvector3(LPCSTR,LPCSTR key){assert(std::string(key)=="position");return Fvector().set(0.f,0.f,.05f);}
 float r_float(LPCSTR section,LPCSTR key){
  assert(std::string(section)=="f1");
  if(std::string(key)=="range")return 30.f;
  if(std::string(key)=="glow_radius")return .5f;
  return angles.at(key);
 }
 Fcolor r_fcolor(LPCSTR,LPCSTR){return {};}
 LPCSTR r_string(LPCSTR,LPCSTR key){return key;}
} test_ini;
struct IKinematics {
 bool visible=true;
 CInifile* LL_UserData(){return &test_ini;}
 u16 LL_BoneID(LPCSTR name){assert(std::string(name)=="bone");return 4;}
 void LL_SetBoneVisible(u16 id,bool value,bool recursive){assert(id==4 && recursive);visible=value;}
} kinematics;
template<class T> static T smart_cast(IKinematics* object){return static_cast<T>(object);}
struct CCar{IKinematics* Visual(){return &kinematics;}} car;
struct Light {
 float cone=0.f;bool active=true,shadow=false;int type=-1;
 void set_type(int value){type=value;} void set_shadow(bool value){shadow=value;} void set_range(float){}
 void set_color(Fcolor){} void set_cone(float value){cone=value;}
 void set_texture(LPCSTR){} void set_radius(float){} void set_active(bool value){active=value;}
} test_light,test_glow;
namespace IRender_Light {constexpr int POINT=1,SPOT=2,OMNIPART=3;}
struct Ref {
 Light* value=nullptr;
 Ref& operator=(Light* object){value=object;return *this;}
 Light* operator->(){assert(value);return value;}
 explicit operator bool()const{return value!=nullptr;}
};
struct Renderer{Light* light_create(){return &test_light;}Light* glow_create(){return &test_glow;}} renderer;
static Renderer* Render=&renderer;
class CCarLights;
struct SCarLight {
 Ref light_render,glow_render;u16 bone_id=65535;Fvector offset;CCarLights* m_holder=nullptr;
 void ParseDefinitions(LPCSTR);
};
using LIGHTS_I=std::vector<SCarLight*>::iterator;
class CCarLights {
public:
 std::vector<SCarLight*> m_lights;
 CCar* PCar(){return &car;}
 bool findLight(u16,SCarLight*&);
 struct SFindLightPredicate{
  const SCarLight* target;
  explicit SFindLightPredicate(const SCarLight* object):target(object){}
  bool operator()(const SCarLight* object)const{return object->bone_id==target->bone_id;}
 };
};
''' + method("void SCarLight::ParseDefinitions(LPCSTR section)") + "\n" + method("bool CCarLights::findLight(") + r'''
int main(){
 CCarLights holder;SCarLight headlight;headlight.m_holder=&holder;
 // The owner's Moskvich f1 section contains spot_angle=70, no cone_angle.
 test_ini.strings={"spot_texture","glow_texture"};
 test_ini.angles={{"spot_angle",70.f}};headlight.ParseDefinitions("f1");
 assert(std::fabs(test_light.cone-deg2rad(70.f))<.00001f);
 assert(headlight.bone_id==4 && !test_light.active && !test_glow.active && !kinematics.visible);
 assert(test_light.type==IRender_Light::SPOT && test_light.shadow && headlight.glow_render);
 test_ini.angles={{"cone_angle",55.f}};headlight.ParseDefinitions("f1");
 assert(std::fabs(test_light.cone-deg2rad(55.f))<.00001f);
 test_ini.angles={{"cone_angle",60.f},{"spot_angle",70.f}};headlight.ParseDefinitions("f1");
 assert(std::fabs(test_light.cone-deg2rad(60.f))<.00001f);
 test_ini.angles.clear();bool rejected=false;
 try{headlight.ParseDefinitions("f1");}catch(const std::out_of_range&){rejected=true;}
 assert(rejected); // malformed definitions still fail; no invented beam angle.
 // Definitive Car Pack [f1o]: type = 1, a point light without angle, textures or glow.
 SCarLight marker;marker.m_holder=&holder;test_ini.strings={"type","position"};test_ini.type=1;test_light.cone=-1.f;
 marker.ParseDefinitions("f1");
 assert(test_light.type==IRender_Light::POINT && !test_light.shadow && test_light.cone==-1.f && !marker.glow_render);
 assert(std::fabs(marker.offset.z-.05f)<.00001f && marker.bone_id==4);
 test_ini.type=3;marker.ParseDefinitions("f1");assert(test_light.type==IRender_Light::OMNIPART);
 SCarLight* found=&headlight;
 assert(!holder.findLight(4,found) && found==nullptr);
 holder.m_lights.push_back(&headlight);
 assert(holder.findLight(4,found) && found==&headlight);
 assert(!holder.findLight(9,found) && found==nullptr);
}
'''

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native fixture compiles only in GitHub Actions; no local compiler invocation.")
with TemporaryDirectory(prefix="car-lights-") as temporary:
    folder = Path(temporary)
    cpp = folder / "car_lights.cpp"
    exe = folder / ("car_lights.exe" if os.name == "nt" else "car_lights")
    cpp.write_text(source, encoding="utf-8")
    args = (["cl", "/nologo", "/std:c++17", "/EHsc", "/W4", "/WX", str(cpp), "/Fe:"+str(exe)]
            if os.name == "nt" else
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)])
    subprocess.run(args, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
print("PASS actual headlights: Moskvich spot_angle, legacy cone_angle, precedence, DCP point lights, safe missing-bone lookup")
