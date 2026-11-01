"""Actual host stop saves characters/world before exit; no game launch."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
text = (root / 'src/xrGame/netcoop_cluster.inc').read_text(encoding='utf-8')
code = text[text.index('struct ClusterSaveForHostStop'):text.index('static void cluster_hibernate(')]
characters=(root/'src/xrGame/netcoop_characters.inc').read_text(encoding='utf-8')
body_reset=characters[characters.index('static void character_clear_dead_body_state('):characters.index('bool server_character_load_actor(')]
loader=characters[characters.index('bool server_character_load_actor('):characters.index('static bool character_spawn_saved_items(')]
assert loader.index('actor->Spawn_Read(packet)') < loader.index('character_clear_dead_body_state(actor, character->respawn)')
source = r'''
#include <cassert>
#include <cstddef>
#include <map>
#include <string>
#include <vector>
#include <cstdio>
#include <cstdint>
using u32=std::uint32_t;using xr_string=std::string;using string64=char[64];using string_path=char[512];
template<size_t N,class... Args>void xr_sprintf(char(&out)[N],const char* format,Args... args){std::snprintf(out,N,format,args...);}
struct IClient{virtual ~IClient()=default;};
struct ClientID{u32 id;u32 value()const{return id;}};
struct Entity{u32 ID;};
struct xrClientData:IClient{struct{bool bLocal=false;}flags;ClientID ID{1};Entity* owner=nullptr;};
struct xrServer{std::vector<IClient*>clients;template<class T>void ForEachClientDo(T& op){for(auto* c:clients)op(c);}};
std::map<u32,int>s_cluster_leaving;bool s_cluster_quitting=false;
bool fixture_admitted=true,fixture_save=true,fixture_world=true,fixture_request_present=false,fixture_accounts=true,fixture_status=true;
xr_string fixture_request,fixture_events;unsigned fixture_saves=0;
u32 cluster_port(){return 1361;}u32 GetCurrentProcessId(){return 999;}
void cluster_file(const char*,const char*,int,string_path& path){xr_sprintf(path,"%s","request");}
bool cluster_read_line(const char*,xr_string& out){out=fixture_request;return fixture_request_present;}
bool world_store_admission_open(){return fixture_admitted;}
bool character_save_actor(u32,const void*,bool){++fixture_saves;fixture_events+='C';return fixture_save;}
void store_money(xrClientData*){fixture_events+='M';}
bool accounts_save(){fixture_events+='A';return fixture_accounts;}
void character_commits_flush(){fixture_events+='F';}
bool world_store_save_now(const char*){fixture_events+='W';return fixture_world;}
bool cluster_status_remove(){fixture_events+='X';return fixture_status;}
void DeleteFileA(const char*){fixture_request_present=false;fixture_events+='D';}
void Msg(const char*){}void FlushLog(){fixture_events+='L';}
struct ConsoleStub{void Execute(const char* command){assert(xr_string(command)=="quit");fixture_events+='Q';}}fixture_console;
ConsoleStub* Console=&fixture_console;
''' + code + r'''
struct CSE_Abstract{virtual ~CSE_Abstract()=default;std::vector<unsigned char>client_data{1,2,3};};
namespace ALife{using _OBJECT_ID=unsigned short;}
struct CSE_ALifeCreatureActor:CSE_Abstract{float fixture_health=0;unsigned fixture_money=900;ALife::_OBJECT_ID fixture_killer=42;unsigned long long m_game_death_time=77;void set_health(float v){fixture_health=v;}void set_killer_id(ALife::_OBJECT_ID v){fixture_killer=v;}};
template<class T>T smart_cast(CSE_Abstract* obj){return dynamic_cast<T>(obj);}
''' + body_reset + r'''
int main(){
 CSE_ALifeCreatureActor body;character_clear_dead_body_state(&body,false);
 assert(body.fixture_health==0&&body.client_data.size()==3&&body.fixture_money==900&&body.fixture_killer==42&&body.m_game_death_time==77);
 character_clear_dead_body_state(&body,true);
 assert(body.fixture_health==1&&body.client_data.empty()&&body.fixture_money==900&&body.fixture_killer==0xffff&&body.m_game_death_time==0);
 xrServer server;Entity entity{7};xrClientData player,local,joining;
 player.owner=&entity;local.flags.bLocal=true;local.ID.id=2;joining.ID.id=3;
 server.clients={&player,&local};
 cluster_host_stop(&server,1000);assert(fixture_events.empty());
 fixture_request_present=true;fixture_request="stop|998";
 cluster_host_stop(&server,2000);assert(fixture_events.empty());
 fixture_request="stop|999";fixture_admitted=false;
 cluster_host_stop(&server,3000);assert(fixture_events.empty());
 fixture_admitted=true;fixture_save=false;cluster_host_stop(&server,4000);
 assert(fixture_events=="MC"&&!s_cluster_quitting&&fixture_request_present);
 fixture_events.clear();fixture_save=true;server.clients.push_back(&joining);
 cluster_host_stop(&server,5000);assert(fixture_events=="MC"&&!s_cluster_quitting);
 server.clients.pop_back();fixture_events.clear();fixture_world=false;
 cluster_host_stop(&server,6000);assert(fixture_events=="MCFAW"&&!s_cluster_quitting);
 fixture_events.clear();fixture_world=true;s_cluster_leaving[1]=1;
 fixture_status=false;cluster_host_stop(&server,7000);assert(fixture_events=="FAWX"&&!s_cluster_quitting&&fixture_request_present);
 fixture_events.clear();fixture_status=true;cluster_host_stop(&server,8000);assert(fixture_events=="FAWXDLQ"&&s_cluster_quitting&&!fixture_request_present);
 auto previous=fixture_events;cluster_host_stop(&server,9000);assert(fixture_events==previous);
 assert(fixture_saves==3);
 std::puts("PASS actual host stop: exact process, admission/restore/save failures hold exit, handoff checkpoint protected, world saved before quit");
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'stop.cpp';exe=Path(tmp)/('stop.exe' if os.name=='nt' else 'stop')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
             ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
