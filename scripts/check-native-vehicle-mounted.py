"""CI-only execution of real optional vehicle-turret dependency validation."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
text=(root/'src/xrGame/Car.cpp').read_text(encoding='utf-8')
start=text.index('static bool car_mounted_weapon_available(')
end=text.index('CCar::CCar(',start)
code=text[start:end]
assert 'car_mounted_weapon_available(*PKinematics(Visual()), *pUserData)' in text
source=r'''
#include <cassert>
#include <map>
#include <string>
#include <stdexcept>
using LPCSTR=const char*;constexpr unsigned BI_NONE=65535;
struct CInifile{
 std::map<std::string,std::map<std::string,std::string>> data;
 bool section_exist(LPCSTR s){return data.count(s)!=0;}
 bool line_exist(LPCSTR s,LPCSTR k){return section_exist(s)&&data.at(s).count(k);}
 LPCSTR r_string(LPCSTR s,LPCSTR k){return data.at(s).at(k).c_str();}
};
struct IKinematics{unsigned LL_BoneID(LPCSTR s){return std::string(s)=="missing"?BI_NONE:1;}};
CInifile settings;CInifile*pSettings=&settings;
template<class...T>void Msg(LPCSTR,T...){}
'''+code+r'''
int main(){
 IKinematics model;CInifile donor;
 assert(!car_mounted_weapon_available(model,donor));
 donor.data["mounted_weapon_definition"]={{"wpn_section","btr82_mgun"},{"rotate_x_bone","x"},{"rotate_y_bone","y"},{"fire_bone","fire"}};
 assert(!car_mounted_weapon_available(model,donor)); // exact reported fatal
 settings.data["btr82_mgun"]={};assert(!car_mounted_weapon_available(model,donor));
 settings.data["btr82_mgun"]["ammo_class"]="missing_ammo";
 assert(!car_mounted_weapon_available(model,donor));
 settings.data["missing_ammo"]={};assert(car_mounted_weapon_available(model,donor));
 donor.data["mounted_weapon_definition"]["fire_bone"]="missing";
 assert(!car_mounted_weapon_available(model,donor));
 donor.data["mounted_weapon_definition"].erase("fire_bone");
 assert(!car_mounted_weapon_available(model,donor));
}
'''
with TemporaryDirectory() as directory:
    cpp=Path(directory)/'mounted.cpp';exe=Path(directory)/('mounted.exe' if os.name=='nt' else 'mounted')
    cpp.write_text(source)
    command=['cl','/nologo','/std:c++17','/EHsc',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else ['g++','-std=c++17',str(cpp),'-o',str(exe)]
    subprocess.run(command,cwd=directory,check=True)
    subprocess.run([str(exe)],cwd=directory,check=True,timeout=15)
print('PASS actual mounted-weapon dependency guard: missing gun/ammo/bones cannot crash vehicle spawning')
