"""Actual target character progress/inventory admission and gameplay gate."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import re
import subprocess
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks must run in GitHub Actions")
root = Path(__file__).resolve().parents[1]
engine = netcoop_cpp(root, encoding="utf-8")
characters = (root / "src/xrGame/netcoop_characters.inc").read_text(encoding="utf-8")
items = (root / "src/xrGame/netcoop_items.inc").read_text(encoding="utf-8")
start = items.index("static bool item_state_ready_for_save(u16 id)\n{")
item_ready = items[start:items.index("static void item_state_for_save(", start)]
start = engine.index("static bool character_restore_progress(Character& character, CActor* actor)\n{")
progress = engine[start:engine.index("// ---------------------------------------------------------------------------\n// task list replication",start)]
start = characters.index("struct CharacterRestore\n{")
declarations = characters[start:characters.index("static bool character_capture_progress(",start)]
start = characters.index("bool server_character_accepts(")
gate = characters[start:characters.index("static xr_string character_key(",start)]
start = characters.index("static bool character_spawn_saved_items(")
spawn = characters[start:characters.index("void server_character_spawn_items(",start)]
start = characters.index("static void characters_restore_update()\n{")
update = characters[start:characters.index("static void characters_update(",start)]
spawn_caller = characters[characters.index("void server_character_spawn_items("):characters.index("// Refuse the whole checkpoint")]
assert spawn_caller.index("s_actor_character.find(CL->owner->ID)") < spawn_caller.index("character_load(")
assert spawn_caller.index("s_character_restore[CL->owner->ID]") < spawn_caller.index("character_load(")
assert spawn_caller.index("if (!character_spawn_saved_items(") < spawn_caller.index("restore.inventory_complete = true")
assert spawn_caller.count("if (!spawned) return;") == 2
save = characters[characters.index("static bool character_save_actor("):characters.index("void server_character_save_actor(")]
start = characters.index("static Character* character_tracked_for_save(")
tracked = characters[start:characters.index("// Captures the Actor",start)]
assert "s_character_restore.find(actor_id)" in tracked
assert "s_characters[" not in save and "s_characters[" not in tracked
assert save.index("character_tracked_for_save(actor_id)") < save.index("if (!tracked") < save.index("Character& character = *tracked") < save.index("character_capture_progress(")
server = (root / "src/xrGame/xrServer.cpp").read_text(encoding="utf-8")
assert server.index("GetCurrentThreadId() != m_netcoop_main_thread") < server.index("server_character_accepts(CL, type)") < server.index("case M_CL_INPUT:")
assert "type != M_CL_INPUT && !netcoop::server_character_accepts(CL, type)" in server
start = server.index("case M_CL_INPUT:")
input_case = server[start:server.index("case M_UPDATE:", start)]
assert input_case.index("m_last_received_sequence = cmd.sequence") < input_case.index("server_character_accepts(CL, M_CL_INPUT)") < input_case.index("m_last_input_receive_time =") < input_case.index("m_pending_inputs.push_back")
messages = (root / "src/xrServerEntities/xrMessages.h").read_text(encoding="utf-8")
input_types = messages[messages.index("struct ActorInputCommand"):messages.index("enum\n")]
input_case = input_case.replace("netcoop::server_character_accepts", "server_character_accepts")
packet_names = sorted(set(re.findall(r"\bM_[A-Z_]+\b",gate)))
enums = "enum PacketType {" + ",".join(packet_names+["M_CLIENTREADY","M_CLIENT_REQUEST_CONNECTION_DATA","M_CHANGE_LEVEL","M_CHAT_MESSAGE"]) + "};\n"
source = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <memory>
#include <iostream>
#include <algorithm>
#include <cmath>
#include <deque>
#include <limits>
using u8=unsigned char;using u16=unsigned short;using u32=unsigned int;
constexpr bool TRUE=true;
using shared_str=std::string;using xr_string=std::string;
template<class T>using xr_vector=std::vector<T>;
template<class K,class V>using xr_map=std::map<K,V>;
template<class T,class P>T smart_cast(P* value){return dynamic_cast<T>(value);}
void Msg(const char*,...){}
''' + input_types + r'''
namespace ACTOR_DEFS {constexpr u16 mcJump=16,kM1InputIntentFlags=31;}
constexpr float PI_MUL_2=6.283185307f,PI_DIV_2=1.570796327f;
bool _valid(float value){return std::isfinite(value);}
float _abs(float value){return std::abs(value);}
float angle_normalize_signed(float value){return std::remainder(value,PI_MUL_2);}
void clamp(float& value,float low,float high){value=std::max(low,std::min(high,value));}
struct DeviceStub {u32 dwTimeGlobal=123;};DeviceStub Device;
struct IReader {
 const u8* data;size_t length,position=0;
 IReader(const void* bytes,size_t size):data(static_cast<const u8*>(bytes)),length(size){}
 size_t elapsed()const{return length-position;}
 const void* pointer()const{return data+position;}
 u32 r_u32(){assert(elapsed()>=4);u32 value=0;for(u32 i=0;i<4;++i)value|=u32(data[position++])<<(i*8);return value;}
 void advance(size_t count){assert(count<=elapsed());position+=count;}
 void r_stringZ(shared_str& value){auto start=static_cast<const char*>(pointer());assert(memchr(start,0,elapsed()));value=start;advance(value.size()+1);}
};
struct GameTask {shared_str m_netcoop_origin;};
struct SGameTaskKey {
 shared_str task_id;GameTask* game_task=nullptr;
 void load(IReader& reader){reader.r_stringZ(task_id);reader.r_u32();game_task=new GameTask;}
};
using vGameTasks=std::vector<SGameTaskKey>;
struct CGameTaskManager {vGameTasks entries;int changed=0;vGameTasks& GetGameTasks(){return entries;}void MarkChanged(){++changed;}};
CGameTaskManager fixture_manager;
CGameTaskManager* server_task_manager(u16){return &fixture_manager;}
void clear_tasks(CGameTaskManager* manager){for(auto& key:manager->entries)delete key.game_task;manager->entries.clear();manager->MarkChanged();}
struct Info {u32 value=0;Info& registry(){return *this;}u32& objects(){return value;}};
void load_data(u32& value,IReader& reader){value=reader.r_u32();}
struct NET_Packet {
 bool readable=true;struct Buffer {u32 count=16;u8 data[32]={};}B;u32 position=2;
 u32 r_tell()const{return position;}
 template<class T>void read(T& value){assert(position+sizeof(T)<=B.count);std::memcpy(&value,B.data+position,sizeof(T));position+=u32(sizeof(T));}
 void r_u32(u32& value){read(value);}void r_u16(u16& value){read(value);}void r_float(float& value){read(value);}
 void w_u16(u16){}void w_u8(u8){}
};
std::vector<int>fixture_events;
struct CGameObject {
 virtual ~CGameObject()=default;u16 id=7;CGameObject* parent=nullptr;
 u16 ID()const{return id;}CGameObject* H_Parent()const{return parent;}
 static void u_EventGen(NET_Packet&,int kind,u16){fixture_events.push_back(kind);}
 static void u_EventSend(NET_Packet&){}
};
struct CActor:CGameObject {Info info;Info* m_known_info_registry=&info;int* lua_game_object(){return nullptr;}};
int fixture_scope_depth=0;
struct ServerVictimScope {explicit ServerVictimScope(CActor*){++fixture_scope_depth;}~ServerVictimScope(){--fixture_scope_depth;}};
bool fixture_stopping=false;bool server_stopping(){return fixture_stopping;}
bool fixture_available=true,fixture_throw=false,fixture_respawn=false;int fixture_restore_calls=0;std::string fixture_restored;
namespace luabind {using internal_string=std::string;
 template<class T>struct functor {void operator()(int*,const internal_string& state,bool respawn){fixture_respawn=respawn;++fixture_restore_calls;if(fixture_throw)throw 1;fixture_restored=state;}};
}
struct ScriptEngine {bool functor(const char*,luabind::functor<void>&){return fixture_available;}};
struct AI {ScriptEngine scripts;ScriptEngine& script_engine(){return scripts;}};
AI fixture_ai;AI& ai(){return fixture_ai;}
struct Flags {void assign(int){}};
struct CSE_Abstract {
 virtual ~CSE_Abstract()=default;
 u16 ID=7,ID_Phantom=0xffff,ID_Parent=0xffff;Flags s_flags;
 bool Spawn_Read(NET_Packet& packet){return packet.readable;}
};
struct CSE_ALifeCreatureActor:CSE_Abstract {};
struct xrClientData {
 CSE_Abstract* owner;int ID=1;bool net_Ready=false;
 u32 m_last_received_sequence=0,m_last_input_receive_time=0;bool m_pending_jump_edge=false;
 std::deque<ActorInputCommand> m_pending_inputs;
 explicit xrClientData(CSE_Abstract* entity,int client_id=1):owner(entity),ID(client_id){}
};
struct Character {bool respawn=false;std::vector<u8>progress;
 struct Item {std::string section="item";u16 parent=0,place=0;NET_Packet spawn;std::vector<u8>state;};
 std::vector<Item>items;
};
std::map<u16,std::vector<u8>>fixture_item_states;
void item_state_restore(u16 id,const std::vector<u8>& bytes){fixture_item_states[id]=bytes;}
void F_entity_Destroy(CSE_Abstract* entity){delete entity;}
struct Game {
 std::vector<std::unique_ptr<CSE_Abstract>>created;int begun=0,ended=0,fail_begin=0,fail_end=0;
 CSE_Abstract* spawn_begin(const char*){++begun;if(fail_begin==begun)return nullptr;return new CSE_Abstract;}
 CSE_Abstract* spawn_end(CSE_Abstract* entity,int){++ended;if(fail_end==ended){delete entity;return nullptr;}entity->ID=u16(100+ended);created.emplace_back(entity);return entity;}
};
struct xrServer {Game* game;};
struct StubObjects {std::map<u16,CGameObject*> entries;CGameObject* net_Find(u16 id){auto it=entries.find(id);return it==entries.end()?nullptr:it->second;}};
struct Runtime {StubObjects Objects;};
Runtime fixture_runtime;Runtime& Level(){return fixture_runtime;}
namespace item_state {struct State {std::uint64_t uid=0;};}
struct ItemRecord {item_state::State sent;};
xr_map<u16,ItemRecord> s_item_records;
xr_map<u16,item_state::State> s_item_restore;
u32 fixture_clock=0;u32 real_time_ms(){return fixture_clock;}
enum {M_SPAWN_OBJECT_LOCAL=1,eItemPlaceSlot=1,eItemPlaceBelt=2,GEG_PLAYER_ITEM2RUCK=10,GEG_PLAYER_ITEM2SLOT=11,GEG_PLAYER_ITEM2BELT=12};
struct SInvItemPlace {u16 value=0,type=eItemPlaceSlot,slot_id=1;};
''' + enums + r'''
xr_map<xr_string,Character>s_characters;
xr_map<u16,xr_string>s_actor_character;
int fixture_timeouts=0;void character_restore_timeout(u16){++fixture_timeouts;}
''' + declarations + item_ready + '\nstatic const u32 task_origin_marker=0x524f434e;\n' + progress + gate + spawn + update + tracked + '\nvoid receive_input(NET_Packet& P,xrClientData* CL){switch(M_CL_INPUT){\n' + input_case + '\ndefault:break;}}\n' + r'''
NET_Packet input_packet(u32 sequence,u16 flags=ACTOR_DEFS::mcJump,float yaw=0,float pitch=0){
 NET_Packet packet;u32 position=2;
 auto write=[&](const auto& value){std::memcpy(packet.B.data+position,&value,sizeof(value));position+=u32(sizeof(value));};
 write(sequence);write(flags);write(yaw);write(pitch);return packet;
}
void input_cases(){
 CSE_ALifeCreatureActor owner;xrClientData client(&owner);s_character_restore[owner.ID]={};
 for(u32 sequence=1;sequence<=12000;++sequence){auto packet=input_packet(sequence);receive_input(packet,&client);}
 assert(client.m_last_received_sequence==12000 && client.m_pending_inputs.empty());
 assert(client.m_last_input_receive_time==0 && !client.m_pending_jump_edge);
 auto reject=[&](NET_Packet packet){receive_input(packet,&client);assert(client.m_last_received_sequence==12000 && client.m_pending_inputs.empty());};
 reject(input_packet(12000));reject(input_packet(11999));reject(input_packet(22001));
 reject(input_packet(12001,0x8000));reject(input_packet(12001,0,std::numeric_limits<float>::quiet_NaN()));
 reject(input_packet(12001,0,100));reject(input_packet(12001,0,0,std::numeric_limits<float>::infinity()));
 auto short_packet=input_packet(12001);--short_packet.B.count;reject(short_packet);
 auto extra_packet=input_packet(12001);++extra_packet.B.count;reject(extra_packet);
 s_character_restore.clear();auto ready=input_packet(12001);receive_input(ready,&client);
 assert(client.m_last_received_sequence==12001 && client.m_pending_inputs.size()==1);
 assert(client.m_last_input_receive_time==Device.dwTimeGlobal && client.m_pending_jump_edge);
 client.m_pending_inputs.clear();client.m_pending_jump_edge=false;client.m_last_input_receive_time=0;
 client.m_last_received_sequence=0xfffffff0u;s_character_restore[owner.ID]={};
 for(u32 i=1;i<=32;++i){auto packet=input_packet(0xfffffff0u+i);receive_input(packet,&client);}
 assert(client.m_last_received_sequence==16 && client.m_pending_inputs.empty() && !client.m_pending_jump_edge);
 s_character_restore.clear();auto wrapped=input_packet(17);receive_input(wrapped,&client);
 assert(client.m_pending_inputs.size()==1 && client.m_last_received_sequence==17);
}
void number(std::vector<u8>& data,u32 value){for(u32 i=0;i<4;++i)data.push_back(u8(value>>(i*8)));}
void text(std::vector<u8>& data,const std::string& value){data.insert(data.end(),value.begin(),value.end());data.push_back(0);}
std::vector<u8> saved(u32 count=1,bool footer=true){
 std::vector<u8> data;number(data,count);
 for(u32 i=0;i<count;++i){text(data,"quest"+std::to_string(i));number(data,1);}
 number(data,123);number(data,6);data.insert(data.end(),{'s','c','r','i','p','t'});
 if(footer){number(data,task_origin_marker);number(data,count);for(u32 i=0;i<count;++i){text(data,"quest"+std::to_string(i));text(data,"source-map");}}
 return data;
}
void reset(CActor& actor){clear_tasks(&fixture_manager);fixture_manager.changed=0;fixture_available=true;fixture_throw=false;fixture_restore_calls=0;fixture_restored.clear();fixture_clock=0;fixture_events.clear();fixture_item_states.clear();s_item_records.clear();s_item_restore.clear();s_characters.clear();s_actor_character.clear();s_character_restore.clear();fixture_runtime.Objects.entries.clear();fixture_runtime.Objects.entries[actor.ID()]=&actor;assert(fixture_scope_depth==0);}
void save_cache_cases(CActor& actor){
 reset(actor);assert(!character_tracked_for_save(actor.ID()) && s_characters.empty());
 s_actor_character[actor.ID()]="tester:1";
 assert(!character_tracked_for_save(actor.ID()) && s_characters.empty());
 auto& cached=s_characters["tester:1"];cached.progress={9,8,7};
 s_character_restore[actor.ID()]={};
 assert(!character_tracked_for_save(actor.ID()) && cached.progress==std::vector<u8>({9,8,7}));
 s_character_restore.clear();assert(character_tracked_for_save(actor.ID())==&cached);
 s_actor_character[actor.ID()]="missing:2";
 assert(!character_tracked_for_save(actor.ID()) && s_characters.size()==1);
}
void progress_cases(CActor& actor){
 Character character;character.progress=saved();const auto prior=character.progress;
 fixture_available=false;assert(!character_restore_progress(character,&actor));assert(fixture_manager.changed==0 && fixture_restore_calls==0);
 fixture_available=true;fixture_throw=true;assert(!character_restore_progress(character,&actor));assert(character.progress==prior);
 fixture_throw=false;character.respawn=true;assert(character_restore_progress(character,&actor));assert(fixture_respawn);assert(fixture_restored=="script" && actor.info.value==123);
 assert(fixture_manager.entries.size()==1 && fixture_manager.entries[0].game_task->m_netcoop_origin=="source-map");
 character.progress=saved(0,false);assert(character_restore_progress(character,&actor));
 character.progress=saved(512);assert(character_restore_progress(character,&actor));assert(fixture_manager.entries.size()==512);
 character.progress=saved(513);assert(!character_restore_progress(character,&actor));
 character.progress={1,2,3};assert(!character_restore_progress(character,&actor));
 character.progress={0,0,0,0};assert(!character_restore_progress(character,&actor));
 character.progress.assign(1048577,0);assert(!character_restore_progress(character,&actor));
 character.progress=saved();character.progress.pop_back();assert(!character_restore_progress(character,&actor));
 character.progress=saved();character.progress.push_back(9);assert(!character_restore_progress(character,&actor));
 character.progress=saved(0,false);number(character.progress,task_origin_marker);number(character.progress,1);assert(!character_restore_progress(character,&actor));
 character.progress=saved(0,false);character.progress.push_back(1);assert(!character_restore_progress(character,&actor));
 character.progress.clear();assert(character_restore_progress(character,&actor));assert(fixture_scope_depth==0);
}
void admission_cases(CActor& actor,xrClientData& client){
 reset(actor);s_actor_character[actor.ID()]="tester:1";s_characters["tester:1"].progress=saved();
 auto& pending=s_character_restore[actor.ID()];
 characters_restore_update();assert(s_character_restore.size()==1 && fixture_restore_calls==0);
 pending.inventory_complete=true;CGameObject root_item,child;root_item.id=100;root_item.parent=&actor;child.id=101;child.parent=&root_item;
 pending.entities={{u16(100),actor.ID()},{u16(101),u16(100)}};pending.places={{u16(100),u16(1)}};
 fixture_runtime.Objects.entries[100]=&root_item;
 characters_restore_update();assert(s_character_restore.size()==1 && fixture_restore_calls==0);
 fixture_runtime.Objects.entries[101]=&child;child.parent=&actor;
 characters_restore_update();assert(s_character_restore.size()==1 && fixture_restore_calls==0);
 child.parent=&root_item;
 // Parents/runtime objects alone must not unlock saving or gameplay.
 characters_restore_update();assert(s_character_restore.size()==1 && fixture_restore_calls==0);
 assert(!character_tracked_for_save(actor.ID()) && !server_character_accepts(&client,M_CL_INPUT));
 s_item_records[100].sent.uid=41;s_item_records[101].sent.uid=0;
 characters_restore_update();assert(s_character_restore.size()==1 && fixture_restore_calls==0);
 s_item_records[101].sent.uid=42;s_item_restore[101].uid=42;
 characters_restore_update();assert(s_character_restore.size()==1 && fixture_restore_calls==0);
 s_item_restore.erase(101);fixture_throw=true;
 characters_restore_update();assert(s_character_restore.size()==1 && fixture_restore_calls==1 && fixture_events.empty());
 assert(!server_character_accepts(&client,M_CL_INPUT) && !server_character_accepts(&client,M_CL_UPDATE) && client.net_Ready);
 assert(!server_character_accepts(&client,M_EVENT_PACK) && !server_character_accepts(&client,M_NETCOOP_ITEM_REPORT));
 assert(server_character_accepts(&client,M_CLIENTREADY) && server_character_accepts(&client,M_CLIENT_REQUEST_CONNECTION_DATA));
 assert(server_character_accepts(&client,M_CHANGE_LEVEL) && server_character_accepts(&client,M_CHAT_MESSAGE));
 fixture_throw=false;fixture_clock=999;characters_restore_update();assert(fixture_restore_calls==1 && s_character_restore.size()==1);
 fixture_clock=1000;characters_restore_update();assert(fixture_restore_calls==2 && s_character_restore.empty() && fixture_events.size()==2);
 assert(server_character_accepts(&client,M_CL_INPUT) && server_character_accepts(nullptr,M_EVENT));
 fixture_stopping=true;assert(!server_character_accepts(&client,M_CL_INPUT)&&!server_character_accepts(&client,M_EVENT));
 assert(server_character_accepts(&client,M_CLIENTREADY));fixture_stopping=false;
 reset(actor);s_character_restore[actor.ID()].inventory_complete=true;characters_restore_update();assert(s_character_restore.size()==1);
 reset(actor);s_actor_character[actor.ID()]="tester:1";s_characters["tester:1"].progress=saved();s_character_restore[actor.ID()].inventory_complete=true;
 fixture_clock=0xfffffff0u;fixture_available=false;characters_restore_update();assert(s_character_restore.size()==1);
 fixture_available=true;fixture_clock+=999u;characters_restore_update();assert(s_character_restore.size()==1);
 fixture_clock+=1u;characters_restore_update();assert(s_character_restore.empty());
}
void timeout_cases(CActor& actor){
 reset(actor);fixture_timeouts=0;s_actor_character[actor.ID()]="tester:1";s_characters["tester:1"].progress=saved();
 s_character_restore[actor.ID()]={};characters_restore_update();fixture_clock=59999;characters_restore_update();assert(fixture_timeouts==0);
 fixture_clock=60000;characters_restore_update();assert(fixture_timeouts==1 && s_character_restore[actor.ID()].rejected);
 fixture_clock=90000;characters_restore_update();assert(fixture_timeouts==1 && fixture_restore_calls==0 && fixture_events.empty());
 reset(actor);fixture_timeouts=0;s_character_restore[actor.ID()]={};fixture_clock=0xfffffff0u;characters_restore_update();fixture_clock+=60000;
 characters_restore_update();assert(fixture_timeouts==1);
}
void inventory_cases(xrClientData& client){
 Character character;Character::Item first,second;first.place=1;first.state={1,2};second.parent=1;second.state={3,4};character.items={first,second};
 {Game game;xrServer server{&game};CharacterRestore restore;assert(character_spawn_saved_items(&server,&client,character,restore));
  assert(restore.entities.size()==2 && restore.places.size()==1);assert(game.created[0]->ID_Parent==client.owner->ID && game.created[1]->ID_Parent==game.created[0]->ID);
  assert(fixture_item_states[game.created[1]->ID]==second.state);}
 {Game game;game.fail_end=2;xrServer server{&game};CharacterRestore restore;assert(!character_spawn_saved_items(&server,&client,character,restore));assert(restore.entities.size()==1 && !restore.inventory_complete);}
 {Game game;game.fail_begin=1;xrServer server{&game};CharacterRestore restore;assert(!character_spawn_saved_items(&server,&client,character,restore));assert(restore.entities.empty());}
 {Game game;xrServer server{&game};CharacterRestore restore;character.items[0].spawn.readable=false;assert(!character_spawn_saved_items(&server,&client,character,restore));assert(restore.entities.empty());character.items[0].spawn.readable=true;}
 {Game game;xrServer server{&game};CharacterRestore restore;character.items[1].parent=3;assert(!character_spawn_saved_items(&server,&client,character,restore));assert(game.begun==0);}
 {Game game;xrServer server{&game};CharacterRestore restore;character.items.resize(513);assert(!character_spawn_saved_items(&server,&client,character,restore));assert(game.begun==0);}
}
int main(){input_cases();CActor actor;CSE_Abstract owner;xrClientData client{&owner,1};save_cache_cases(actor);reset(actor);progress_cases(actor);admission_cases(actor,client);inventory_cases(client);timeout_cases(actor);clear_tasks(&fixture_manager);
 std::cout<<"PASS actual target restore: inventory creation/parent/state completeness, pending gameplay refusal, progress hook failure/retry, task/origin bounds and wrap-safe admission\n";
}
'''
with TemporaryDirectory(prefix="character-restore-") as tmp:
    cpp = Path(tmp) / "check.cpp"
    exe = Path(tmp) / ("check.exe" if os.name == "nt" else "check")
    cpp.write_text(source,encoding="utf-8")
    if os.name == "nt":
        command = ["cl","/nologo","/std:c++17","/EHsc","/W4","/WX","/O2",str(cpp),"/Fe:"+str(exe),"/Fo:"+str(Path(tmp)/"check.obj")]
    else:
        command = ["g++","-std=c++17","-Wall","-Wextra","-Werror","-O2",str(cpp),"-o",str(exe)]
    subprocess.run(command,check=True,cwd=tmp)
    subprocess.run([str(exe)],check=True,cwd=tmp,timeout=30)
