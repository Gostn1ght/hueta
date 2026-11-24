"""Actual spawn visual resolver: map boxes without an override use their section."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks must run in GitHub Actions")
root = Path(__file__).resolve().parents[1]
text = (root / "src/xrGame/GameObject.cpp").read_text(encoding="latin-1")
start = text.index("LPCSTR CGameObject::visual_name(CSE_Abstract* server_entity)")
method = text[start:text.index("\nbool CGameObject::animation_movement_controlled", start)]
actor = (root / "src/xrGame/Actor_Network.cpp").read_text(encoding="latin-1")
spawn = actor[actor.index("BOOL CActor::net_Spawn("):]
name_start = spawn.index("if (netcoop::enabled() && E->ID != 0 && E->name_replace()[0]")
name_end = spawn.index("\n\tset_money(", name_start)
assert spawn.index("if (!inherited::net_Spawn(DC)) return FALSE;") < name_start
assert spawn.index("if (!CInventoryOwner::net_Spawn(DC)) return FALSE;") < name_start
name_restore = spawn[name_start:name_end]
characters = (root / "src/xrGame/netcoop_characters.inc").read_text(encoding="utf-8")
load_start = characters.index("bool server_character_load_actor(")
load_end = characters.index("CSE_ALifeCreatureActor* creature", characters.index("trader->m_character_name_str = character->name;", load_start))
load = characters[load_start:load_end]
assert load.index("trader->set_character_profile(") < load.index("trader->specific_character();") < load.index("trader->m_character_name_str = character->name;")
source = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
using LPCSTR=const char*;
struct CSE_Abstract { virtual ~CSE_Abstract()=default; };
struct CSE_Visual:CSE_Abstract { LPCSTR name=nullptr; LPCSTR get_visual() const{return name;} };
template<class T>T smart_cast(CSE_Abstract* obj){return dynamic_cast<T>(obj);}
#define VERIFY assert
struct Settings {
 bool has=true; unsigned reads=0;
 bool line_exist(LPCSTR section,LPCSTR field) {assert(!std::strcmp(section,"inventory_box")); assert(!std::strcmp(field,"visual")); return has;}
 LPCSTR r_string(LPCSTR,LPCSTR) {++reads; return "equipment_box_01_case.ogf";}
}settings;
Settings* pSettings=&settings;
struct CGameObject {LPCSTR cNameSect(){return "inventory_box";} LPCSTR visual_name(CSE_Abstract*);};
namespace netcoop {bool active=true;bool enabled(){return active;}}
struct ActorEnvelope{unsigned ID=17;const char* name="Selected Call Sign";LPCSTR name_replace()const{return name;}};
struct Trader{std::string m_character_name_str;};
static void restore_name(ActorEnvelope* E, Trader* pTA, std::string& m_game_name_str, std::string& m_game_name)
{
''' + name_restore + r'''
}
''' + method + r'''
int main(){
 CGameObject object; CSE_Visual spawn;
 assert(!std::strcmp(object.visual_name(&spawn),"equipment_box_01_case.ogf"));
 spawn.name=""; assert(!std::strcmp(object.visual_name(&spawn),"equipment_box_01_case.ogf"));
 assert(settings.reads==2);
 spawn.name="explicit.ogf"; assert(object.visual_name(&spawn)==spawn.name);
 spawn.name="missing.ogf"; assert(object.visual_name(&spawn)==spawn.name);
 assert(settings.reads==2);
 settings.has=false; spawn.name=""; assert(object.visual_name(&spawn)==spawn.name);
 spawn.name=nullptr; assert(object.visual_name(&spawn)==nullptr);
 ActorEnvelope entity;Trader trader{entity.name};std::string raw="Old checkpoint",display="Random name";
 restore_name(&entity,&trader,raw,display);
 assert(raw==entity.name&&display==entity.name);
 raw=display="Existing";
 trader.m_character_name_str="Another name";restore_name(&entity,&trader,raw,display);assert(display=="Existing");
 trader.m_character_name_str=entity.name;entity.ID=0;restore_name(&entity,&trader,raw,display);assert(display=="Existing");
 entity.ID=17;netcoop::active=false;restore_name(&entity,&trader,raw,display);assert(display=="Existing");
 netcoop::active=true;entity.name="";trader.m_character_name_str="";restore_name(&entity,&trader,raw,display);assert(display=="Existing");
 std::puts("PASS actual network actor name restore after old client_data, observer-compatible spawn, absent/anchor/offline guards");
 std::puts("PASS actual spawn visual resolver: empty map overrides use defaults; explicit visuals and absent defaults preserved");
}
'''
with TemporaryDirectory() as tmp:
    cpp = Path(tmp) / "visual.cpp"
    exe = Path(tmp) / ("visual.exe" if os.name == "nt" else "visual")
    cpp.write_text(source, encoding="utf-8")
    command = (["cl", "/nologo", "/std:c++17", "/EHsc", "/W4", "/WX", str(cpp), "/Fe:" + str(exe)]
               if os.name == "nt" else ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", str(cpp), "-o", str(exe)])
    subprocess.run(command, cwd=tmp, check=True)
    subprocess.run([str(exe)], cwd=tmp, check=True)
