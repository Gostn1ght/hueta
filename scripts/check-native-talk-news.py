"""CI-only actual GAMMA talk-message forwarding instead of absent dedicated UI."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
s=(root/'src/xrGame/script_game_object_inventory_owner.cpp').read_text(encoding='utf-8')
a=s.index('void CScriptGameObject::AddIconedTalkMessage(');b=s.index('void _AddIconedTalkMessage(',a)
function=s[a:b]
source=r"""
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
using LPCSTR=const char*;
struct GAME_NEWS_DATA{enum{eTalk=1};int m_type=0,show_time=0;std::string news_caption,news_text,texture_name;};
struct CObject{virtual ~CObject()=default;};
struct CActor:CObject{bool remote=true;std::vector<GAME_NEWS_DATA>news;void AddGameNews(const GAME_NEWS_DATA& value){news.push_back(value);}};
template<class T>T smart_cast(CObject* obj){return dynamic_cast<T>(obj);}
namespace netcoop{bool client=false,enabled=true;bool pure_client(){return client;}bool server_player_copy(CActor* actor){return enabled&&!client&&actor&&actor->remote;}}
struct World{CObject* owner=nullptr;CObject* CurrentControlEntity(){return owner;}}world;World& Level(){return world;}
unsigned legacy=0;void _AddIconedTalkMessage(LPCSTR,LPCSTR,LPCSTR,LPCSTR){++legacy;}
struct CScriptGameObject{CObject& value;explicit CScriptGameObject(CObject& obj):value(obj){}CObject& object(){return value;}
 void AddIconedTalkMessage(LPCSTR,LPCSTR,LPCSTR,LPCSTR);};
"""+function+r"""
int main(){
 CActor first,second;CScriptGameObject a(first),b(second);
 a.AddIconedTalkMessage("task","accepted","icon","template");
 b.AddIconedTalkMessage("reward","5000","money","template");
 assert(first.news.size()==1&&second.news.size()==1&&!legacy);
 assert(first.news[0].m_type==GAME_NEWS_DATA::eTalk&&first.news[0].news_text=="accepted");
 assert(second.news[0].news_text=="5000"&&second.news[0].show_time==7000);
 a.AddIconedTalkMessage(nullptr,nullptr,nullptr,nullptr);assert(!first.news.back().texture_name.empty());
 netcoop::client=true;world.owner=&first;
 a.AddIconedTalkMessage("task","complete","icon",nullptr);assert(first.news.size()==3);
 b.AddIconedTalkMessage("foreign","hidden","icon",nullptr);assert(second.news.size()==1&&!legacy);
 netcoop::client=false;netcoop::enabled=false;a.AddIconedTalkMessage("sp","original","icon",nullptr);assert(legacy==1);
 CObject npc;CScriptGameObject n(npc);n.AddIconedTalkMessage("npc","original","icon",nullptr);assert(legacy==2);
 puts("PASS actual GAMMA talk news: dedicated owner routing, separate actors, local routed dialogue, foreign actor exclusion, safe icon, SP/NPC path retained");
}
"""
with TemporaryDirectory()as temporary:
 cpp=Path(temporary)/'talk-news.cpp';exe=Path(temporary)/('talk-news.exe'if os.name=='nt'else'talk-news')
 cpp.write_text(source,encoding='utf-8')
 command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)]if os.name=='nt'else
 ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
 subprocess.run(command,cwd=temporary,check=True);subprocess.run([str(exe)],cwd=temporary,check=True,timeout=15)
