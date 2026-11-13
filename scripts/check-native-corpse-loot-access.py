"""CI-only: actual corpse access and per-item reservation, without unlocking retained gear."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

root = Path(__file__).resolve().parents[1]
events = (root / 'src/xrGame/netcoop_events.inc').read_text(encoding='utf-8')


def function(signature):
    start = events.index(signature)
    end = events.index('{', start) + 1
    depth = 1
    while depth:
        depth += (events[end] == '{') - (events[end] == '}')
        end += 1
    return events[start:end]


access = function('static bool accessible_corpse(')
reserved = function('static bool corpse_item_reserved(')
script_access = function('static bool corpse_script_transfer_allowed(')
assert 'protected_body' not in access
assert 'holder != CL->owner && corpse_item_reserved(holder, item_id)' in events
transfer = (root / 'src/xrGame/netcoop_transfer.inc').read_text(encoding='utf-8')
assert 'source == transfer_end_corpse && corpse_item_reserved' in transfer
assert 'item is reserved for the next life' in transfer
assert 'corpse_script_transfer_allowed(server->game->get_entity_from_eid(from), to, item_id)' in transfer
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')

source = r'''
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <set>
#include <stdexcept>
using u16=std::uint16_t;
struct Point{float x=0;float distance_to(const Point& other)const{return std::fabs(x-other.x);}};
struct Object{virtual ~Object()=default;};
struct CEntityAlive:Object{bool alive=false;Point pos;bool g_Alive()const{return alive;}Point& Position(){return pos;}};
struct CInventoryOwner{virtual ~CInventoryOwner()=default;bool closed=false;bool deadbody_closed_status(){return closed;}};
struct Body:CEntityAlive,CInventoryOwner{};
struct CSE_Abstract{virtual ~CSE_Abstract()=default;u16 ID=0;};
struct CSE_ALifeCreatureActor:CSE_Abstract{};
struct xrClientData{CSE_Abstract* owner=nullptr;};
struct ObjectStore{std::map<u16,Object*>data;Object* net_Find(u16 id){auto it=data.find(id);return it==data.end()?nullptr:it->second;}};
struct World{ObjectStore Objects;}world;
World& Level(){return world;}
template<class To,class From>To smart_cast(From* value){return dynamic_cast<To>(value);}
bool callback_available=true,callback_throws=false;
std::set<std::pair<int,int>> retained;
std::set<std::pair<int,int>> claimants;
namespace luabind{template<class T>struct functor{bool claim=false;T operator()(int body,int item)const{
 if(callback_throws)throw std::runtime_error("script error");
 return (claim?claimants:retained).count({body,item})!=0;
}};}
struct Engine{template<class T>bool functor(const char* name,T& fn){fn.claim=std::strcmp(name,"netcoop_survival.can_transfer")==0;return callback_available;}}engine;
struct AI{Engine& script_engine(){return engine;}}ai_state;
AI& ai(){return ai_state;}
''' + access + reserved + script_access + r'''
int main(){
 CSE_ALifeCreatureActor owner,corpse;owner.ID=1;corpse.ID=2;
 xrClientData client;client.owner=&owner;
 CEntityAlive actor;actor.alive=true;Body body;body.pos.x=2;
 world.Objects.data[1]=&actor;world.Objects.data[2]=&body;
 retained.insert({2,100});
 assert(accessible_corpse(&client,&corpse)); // reservation does not reject entire corpse
 assert(corpse_item_reserved(&corpse,100));
 assert(!corpse_item_reserved(&corpse,101)); // dropped half remains accessible
 claimants.insert({2,8});
 assert(corpse_script_transfer_allowed(&corpse,8,100)); // next body of the same character
 assert(!corpse_script_transfer_allowed(&corpse,9,100)); // NPC/other character
 assert(corpse_script_transfer_allowed(&corpse,9,101)); // ordinary dropped loot
 assert(!corpse_item_reserved(nullptr,100));
 CSE_Abstract npc;npc.ID=3;assert(!corpse_item_reserved(&npc,100));
 body.closed=true;assert(!accessible_corpse(&client,&corpse));body.closed=false;
 body.alive=true;assert(!accessible_corpse(&client,&corpse));body.alive=false;
 actor.alive=false;assert(!accessible_corpse(&client,&corpse));actor.alive=true;
 body.pos.x=30;assert(!accessible_corpse(&client,&corpse));body.pos.x=2;
 assert(!accessible_corpse(nullptr,&corpse));
 world.Objects.data.erase(2);assert(!accessible_corpse(&client,&corpse));world.Objects.data[2]=&body;
 callback_available=false;assert(corpse_item_reserved(&corpse,101));callback_available=true;
 callback_throws=true;assert(corpse_item_reserved(&corpse,101));callback_throws=false;
 retained.clear();assert(!corpse_item_reserved(&corpse,100)&&accessible_corpse(&client,&corpse));
 std::puts("PASS actual player corpse access: ordinary loot accessible during respawn reserve, retained originals blocked, living/closed/distant refused, script errors fail closed");
}
'''
with TemporaryDirectory(prefix='corpse-loot-access-') as temporary:
    folder = Path(temporary)
    cpp, exe = folder / 'corpse.cpp', folder / ('corpse.exe' if os.name == 'nt' else 'corpse')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)]
               if os.name == 'nt' else ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
