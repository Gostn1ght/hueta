"""CI-only execution of actual server Lua ownership transaction and rollback."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os, subprocess
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
text = (root/'src/xrGame/netcoop_transfer.inc').read_text(encoding='utf-8')
method = text[text.index('bool server_script_transfer('):text.index('\nvoid server_on_transfer(')]
binding = (root/'src/xrGame/script_game_object_inventory_owner.cpp').read_text(encoding='utf-8-sig')
start = binding.index('void CScriptGameObject::TransferItem(')
body = binding[start:binding.index('\nvoid CScriptGameObject::TakeItem(',start)]
assert body.index('server_script_transfer(') < body.index('u_EventGen(P, GE_TRADE_SELL')
source = r'''
#include <cassert>
#include <cstdio>
#include <map>
using u16=unsigned short;using LPCSTR=const char*;
struct CObject{virtual~CObject()=default;};struct CInventoryItem:CObject{};
struct CSE_Abstract{u16 ID_Parent=65535;};
struct Game{std::map<u16,CSE_Abstract> entities;
 CSE_Abstract*get_entity_from_eid(u16 id){auto i=entities.find(id);return i==entities.end()?nullptr:&i->second;}};
struct xrServer{Game*game=nullptr;bool client=true;int value=1;int*GetServerClient(){return client?&value:nullptr;}};
struct Objects{std::map<u16,CObject*>values;CObject*net_Find(u16 id){auto i=values.find(id);return i==values.end()?nullptr:i->second;}};
struct World{xrServer*Server=nullptr;::Objects Objects;}world;World&Level(){return world;}
template<class T>T smart_cast(CObject*object){return dynamic_cast<T>(object);}
bool active=true,client=false,full=false,reject_take=false,reject_sell=false;
int level=1;int*g_pGameLevel=&level;
bool enabled(){return active;}bool pure_client(){return client;}
template<class...T>void Msg(LPCSTR,T...){}
LPCSTR server_inventory_take_failure(xrServer*,u16,u16){return full?"save safety limit":nullptr;}
constexpr u16 GE_TRADE_SELL=1,GE_TRADE_BUY=2;
unsigned steps=0;
void transfer_step(xrServer*server,u16 type,u16 holder,u16 item){
 ++steps;auto&entry=server->game->entities.at(item);
 if(type==GE_TRADE_SELL){if(!reject_sell&&entry.ID_Parent==holder)entry.ID_Parent=65535;}
 else if(entry.ID_Parent==65535&&!(reject_take&&holder==2))entry.ID_Parent=holder;
}
'''+method+r'''
int main(){
 Game game;xrServer server;server.game=&game;world.Server=&server;
 game.entities[1]={};game.entities[2]={};game.entities[3]={1};CInventoryItem item;world.Objects.values[3]=&item;
 assert(!server_script_transfer(1,1,3)&&steps==0);
 assert(!server_script_transfer(1,3,3)&&steps==0);
 assert(!server_script_transfer(9,2,3)&&steps==0);
 assert(!server_script_transfer(1,9,3)&&steps==0);
 full=true;assert(!server_script_transfer(1,2,3)&&game.entities[3].ID_Parent==1&&steps==0);full=false;
 reject_take=true;assert(!server_script_transfer(1,2,3)&&game.entities[3].ID_Parent==1&&steps==3);reject_take=false;
 reject_sell=true;assert(!server_script_transfer(1,2,3)&&game.entities[3].ID_Parent==1&&steps==5);reject_sell=false;
 assert(server_script_transfer(1,2,3)&&game.entities[3].ID_Parent==2&&steps==7);
 assert(!server_script_transfer(1,2,3)&&steps==7); // delayed duplicate, no second reject
 client=true;assert(!server_script_transfer(2,1,3)&&steps==7);client=false;
 world.Objects.values.clear();assert(!server_script_transfer(2,1,3)&&steps==7);
 std::puts("PASS actual Lua transfer: ownership and save checks, one transfer, refused take rollback, refused reject retained, stale replay and client execution rejected");
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'transfer.cpp';exe=Path(tmp)/('transfer.exe' if os.name=='nt' else 'transfer')
    cpp.write_text(source,encoding='utf-8')
    cmd=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
         ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(cmd,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
