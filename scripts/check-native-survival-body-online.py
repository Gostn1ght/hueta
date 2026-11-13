"""CI-only: actual ALife switching keeps a restoring character's corpse online."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
root=Path(__file__).resolve().parents[1]
def function(text, signature):
    start=text.index(signature);end=text.index('{',start)+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]
characters=(root/'src/xrGame/netcoop_characters.inc').read_text(encoding='utf-8')
alife=(root/'src/xrGame/alife_dynamic_object.cpp').read_text(encoding='utf-8')
query=function(characters,'bool server_character_needs_survival_body(u16 body_id)')
online=function(alife,'void CSE_ALifeDynamicObject::try_switch_online()')
offline=function(alife,'void CSE_ALifeDynamicObject::try_switch_offline()')
assert 'body_for_character' in query
if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks must run in GitHub Actions')
source=r"""
#include <cassert>
#include <cstdint>
#include <map>
#include <string>
#include <stdexcept>
#include <cstdio>
using u16=std::uint16_t;
bool feature=true,client=false,has_level=true,callback=true,throws=false;
int lookups=0,calls=0;
bool enabled(){return feature;}bool pure_client(){return client;}
bool g_pGameLevel=true;
struct Runtime{void* Server=this;}runtime;
Runtime& Level(){return runtime;}
std::map<u16,int>s_character_restore;
std::map<u16,std::string>s_actor_character;
std::map<std::string,u16> reserved;
namespace luabind{template<class T>struct functor{T operator()(u16 id,const char* character)const{
 ++calls;if(throws)throw std::runtime_error("fixture");auto it=reserved.find(character);
 return it!=reserved.end()&&it->second==id;}};}
struct Scripts{bool functor(const char*,luabind::functor<bool>&){++lookups;return callback;}}scripts;
struct AI{Scripts& script_engine(){return scripts;}}space;AI& ai(){return space;}
"""+query+r"""
namespace netcoop{bool server_character_needs_survival_body(u16 id){return ::server_character_needs_survival_body(id);}}
struct CSE_ALifeDynamicObject;
struct Scheduler{bool object(u16,bool){return true;}void remove(void*){}void add(void*){}};
struct Simulator{Scheduler registry;int online=0,offline=0;
 Scheduler& scheduled(){return registry;}
 float online_distance(){return 100;}float offline_distance(){return 150;}
 void switch_online(CSE_ALifeDynamicObject*){++online;}
 void switch_offline(CSE_ALifeDynamicObject*){++offline;}}simulator;
struct CSE_ALifeSchedulable{bool need_update(void*){return true;}};
template<class To,class From>To smart_cast(From*){return nullptr;}
float distance_to_player=1000;
float netcoop_nearest_actor_distance(float){return distance_to_player;}
bool netcoop_combat_pinned(u16){return false;}
struct CSE_ALifeDynamicObject{u16 ID=7;float o_Position=0;bool may_online=true,may_offline=true;int failed=0;
 bool can_switch_online(){return may_online;}bool can_switch_offline(){return may_offline;}
 Simulator& alife(){return simulator;}void on_failed_switch_online(){++failed;}
 void try_switch_online();void try_switch_offline();};
"""+online+'\n'+offline+r"""
int main(){
 CSE_ALifeDynamicObject body;
 body.try_switch_online();assert(simulator.online==0&&body.failed==1&&lookups==0);
 reserved["user:1"]=7;s_actor_character[8]="user:1";
 body.try_switch_online();assert(simulator.online==0);
 s_character_restore[8]=0;
 body.try_switch_online();assert(simulator.online==1);
 body.try_switch_offline();assert(simulator.offline==0);
 // No permanent flag mutation: ordinary distance switching resumes at ready.
 s_character_restore.clear();body.try_switch_offline();assert(simulator.offline==1&&body.may_online&&body.may_offline);
 s_character_restore[8]=0;s_actor_character[8]="other:1";
 body.try_switch_online();assert(simulator.online==1);
 s_actor_character[8]="user:1";body.ID=9;body.try_switch_online();assert(simulator.online==1);body.ID=7;
 // Same pending gate also protects originals during rejected-restore rollback.
 s_character_restore[8]=1;assert(server_character_needs_survival_body(7));
 callback=false;assert(!server_character_needs_survival_body(7));callback=true;
 throws=true;assert(!server_character_needs_survival_body(7));throws=false;
 feature=false;assert(!server_character_needs_survival_body(7));feature=true;
 client=true;assert(!server_character_needs_survival_body(7));client=false;
 g_pGameLevel=false;assert(!server_character_needs_survival_body(7));g_pGameLevel=true;
 runtime.Server=nullptr;assert(!server_character_needs_survival_body(7));runtime.Server=&runtime;
 s_actor_character.clear();assert(!server_character_needs_survival_body(7));s_actor_character[8]="user:1";
 // Configuration's online prohibition remains authoritative.
 body.may_online=false;body.try_switch_online();assert(simulator.online==1);body.may_online=true;
 s_character_restore.clear();distance_to_player=10;body.try_switch_online();assert(simulator.online==2);
 body.try_switch_offline();assert(simulator.offline==1);
 std::puts("PASS actual ALife survival body: distant restore/rollback wake and hold, ready release, unrelated body and offline/client unchanged");
}
"""
with TemporaryDirectory(prefix='survival-body-online-') as temporary:
    folder=Path(temporary);cpp=folder/'check.cpp';exe=folder/('check.exe' if os.name=='nt' else 'check')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt'
             else ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True)
