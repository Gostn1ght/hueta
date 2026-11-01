"""CI-only actual account/character selection: fresh life, death and rollback."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
code = (root/'src/xrGame/netcoop_characters.inc').read_text(encoding='utf8')
names = code[code.index('static bool character_name_valid('):code.index('bool script_character(')]
selection = code[code.index('static bool character_select('):code.index('static CloudJson s_drafts')]
death=code[code.index('static void character_record_death('):code.index('static bool character_save(Character&')]
source = r'''
#include <cassert>
#include <cstring>
#include <string>
#include <map>
#include <cstdio>
#include <utility>
using LPCSTR=const char*;using u8=unsigned char;using u32=unsigned;
using xr_string=std::string;using string_path=char[1024];
unsigned xr_strlen(LPCSTR s){return unsigned(strlen(s));}
void Msg(const char*,...){}
constexpr unsigned INVALID_FILE_ATTRIBUTES=~0u;
bool damaged=false,save_ok=true,kit_ok=true;int loads=0,saves=0;
unsigned GetFileAttributesA(LPCSTR){return damaged ? 0:INVALID_FILE_ATTRIBUTES;}
struct Character {
 xr_string account,name,faction,loadout,description,history,progress,items,safe;
 u8 slot=1,economy=1,lives_remaining=5;bool initialized=false,respawn=false;u32 storage_revision=1;
 struct Packet {struct Buffer {unsigned count=0;}B;}actor;
};
struct xrClientData {xr_string netcoop_login="owner",netcoop_character_name;u8 netcoop_character_slot=0;int netcoop_role=1;};
std::map<xr_string,Character>s_characters;
xr_string character_key(LPCSTR,u8){return "owner:1";}
Character* character_load(LPCSTR,u8){++loads;auto i=s_characters.find("owner:1");return i==s_characters.end()?nullptr:&i->second;}
void character_path(LPCSTR,u8,string_path& path){path[0]=0;}
bool character_starter_loadout(xr_string& kit,LPCSTR requested){kit=requested[0] ? requested:"server-starter";return kit_ok && kit!="forged-kit";}
bool character_save(Character&){++saves;return save_ok;}
''' + death + names + selection + r'''
int main(){
 const char* nick="\xc1\xee\xf0\xe8\xf1";
 for(LPCSTR bad:{"","Loner","123","A|B","-","\xc1 "," \xc1\xee","\xc1--\xee","\xc1_\xee"})assert(!character_call_sign_valid(bad));
 assert(character_call_sign_valid(nick));assert(character_call_sign_valid("\xa8\xe6-\xc1\xe5\xeb\xfb\xe9"));
 Character counter;
 for(u8 expected=4;;--expected) {
  character_record_death(counter);assert(counter.respawn && counter.lives_remaining==expected);
  character_record_death(counter);assert(counter.lives_remaining==expected);
  if(!expected)break;counter.respawn=false;
 }
 xrClientData client;
 assert(!character_select(nullptr,1,nick,"dolg",3,"forged-kit"));
 for(int role:{1,2}) {client.netcoop_role=role;for(u8 slot:{u8(0),u8(2),u8(10),u8(255)}) {
  const int before=loads;assert(!character_select(&client,slot,nick,"dolg",3,"forged-kit"));assert(loads==before);
 }}
 damaged=true;assert(!character_select(&client,1,nick,"dolg",3,"forged-kit") && s_characters.empty());damaged=false;
 save_ok=false;assert(!character_select(&client,1,nick,"dolg",3,"forged-kit") && s_characters.empty());save_ok=true;
 kit_ok=false;assert(!character_select(&client,1,nick,"dolg",3,"forged-kit") && s_characters.empty());kit_ok=true;
 assert(!character_select(&client,1,"Latin","dolg",3,"forged-kit"));
 assert(character_select(&client,1,nick,"dolg",3,"selected-kit"));
 auto& life=s_characters.at("owner:1");
 assert(life.name==nick && life.faction=="stalker" && life.economy==1 && life.loadout=="selected-kit");
 life.initialized=true;life.storage_revision=19;life.items="gun";life.safe="stash";life.progress="quests";
 life.description="old biography";life.actor.B.count=123;
 const auto before=saves;assert(character_select(&client,1,"ignored","freedom",3,"forged-kit"));
 assert(saves==before && life.items=="gun" && life.progress=="quests" && life.storage_revision==19);
 for(u8 lives:{u8(4),u8(3),u8(2),u8(1)}) {
  life.respawn=true;life.lives_remaining=lives;
  assert(character_select(&client,1,"ignored","freedom",3,"forged-kit"));
  assert(life.name==nick && life.lives_remaining==lives && life.items=="gun" && life.progress=="quests");
 }
 life.respawn=true;life.lives_remaining=0;
 assert(!character_select(&client,1,nick,"stalker",1,"") && life.respawn && life.items=="gun");
 save_ok=false;assert(!character_select(&client,1,"\xc4\xe5\xed\xe8\xf1","stalker",1,"") && life.respawn && life.items=="gun");save_ok=true;
 assert(character_select(&client,1,"\xc4\xe5\xed\xe8\xf1","dolg",3,"selected-kit"));
 const auto& fresh=s_characters.at("owner:1");
 assert(fresh.lives_remaining==5 && fresh.storage_revision==20 && !fresh.initialized && !fresh.respawn && fresh.faction=="stalker");
 assert(fresh.items.empty() && fresh.safe.empty() && fresh.progress.empty() && fresh.description.empty() && fresh.actor.B.count==0);
 assert(client.netcoop_login=="owner" && client.netcoop_role==2 && client.netcoop_character_slot==1);
 puts("PASS actual selection: one account/character, Russian call sign, server starter, live state preserved, dead life reset, monotonic revision, save failure rollback and credentials retained");
}
'''
with TemporaryDirectory(prefix='character-life-') as tmp:
    path=Path(tmp);cpp=path/'check.cpp';exe=path/'check.exe'
    cpp.write_text(source,encoding='utf8')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe),'/Fo:'+str(path/'check.obj')],cwd=tmp,check=True)
    subprocess.run([str(exe)],cwd=tmp,check=True,timeout=30)
