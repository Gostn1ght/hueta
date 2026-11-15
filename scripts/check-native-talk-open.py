"""CI-only actual scripted conversation opener without a dedicated game UI."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
text=(root/'src/xrGame/actor_communication.cpp').read_text(encoding='utf8')
start=text.index('void CActor::RunTalkDialog(')
end=text.index('\nvoid CActor::StartTalk(',start)
source=r'''
#include <cassert>
#include <cstdio>
#include <string>
using u16=unsigned short;
struct CActor;
struct CInventoryOwner{virtual ~CInventoryOwner()=default;bool allow=true,bDisableBreakDialog=false;
 bool OfferTalk(CActor*){return allow;}};
struct CGameObject:CInventoryOwner{u16 id=0;u16 ID(){return id;}};
struct CEntityAlive:CGameObject{bool alive=true;bool g_Alive(){return alive;}};
struct CActor:CEntityAlive{bool remote=false;unsigned started=0;void StartTalk(CInventoryOwner*){++started;}
 void RunTalkDialog(CInventoryOwner*,bool);};
template<class T,class U>T smart_cast(U*p){return dynamic_cast<T>(p);}
namespace netcoop{
 unsigned sent=0;u16 recipient=0,partner=0;std::string kind;
 bool server_player_copy(CActor*a){return a->remote;}
 bool server_open_ui(u16 a,const char*k,u16 p){++sent;recipient=a;partner=p;kind=k;return true;}
}
struct AI{bool alife=true;bool get_alife(){return alife;}}ai_space;AI&ai(){return ai_space;}
struct World{bool Server=true;}world;World&Level(){return world;}
struct Window{unsigned hidden=0;void HideDialog(){++hidden;}}window;
struct BaseUI{virtual ~BaseUI()=default;Window*TopInputReceiver(){return &window;}};
struct CUIGameSP:BaseUI{unsigned opened=0;void StartTalk(bool){++opened;}}ui;
BaseUI* current=&ui;unsigned ui_reads=0;BaseUI* CurrentGameUI(){++ui_reads;return current;}
'''+text[start:end]+r'''
int main(){
 CActor owner,other;owner.id=91;owner.remote=true;other.id=92;other.remote=true;
 CEntityAlive npc;npc.id=60001;
 current=nullptr;owner.RunTalkDialog(&npc,false);
 assert(netcoop::sent==1&&netcoop::recipient==91&&netcoop::partner==60001&&netcoop::kind=="talk");
 assert(!ui_reads&&!owner.started); // no absent UI and no orphaned server-side conversation
 other.RunTalkDialog(&npc,true);assert(netcoop::sent==2&&netcoop::recipient==92&&!ui_reads);
 owner.RunTalkDialog(&other,false);owner.RunTalkDialog(nullptr,false);assert(netcoop::sent==2&&!ui_reads);
 // A local remote-client request retains the existing validated talk transport/UI path.
 owner.remote=false;world.Server=false;ai_space.alife=false;current=&ui;
 owner.RunTalkDialog(&npc,false);assert(owner.started==1&&ui.opened==1&&window.hidden==1);
 npc.alive=false;owner.RunTalkDialog(&npc,false);assert(owner.started==1&&ui.opened==1);npc.alive=true;
 current=nullptr;owner.RunTalkDialog(&npc,false);assert(owner.started==1);
 // Ordinary SP, refusal and an unbound headless actor remain safe.
 ai_space.alife=true;world.Server=true;current=&ui;npc.allow=false;
 owner.RunTalkDialog(&npc,false);assert(owner.started==1&&ui.opened==1);
 npc.allow=true;owner.RunTalkDialog(&npc,false);assert(owner.started==2&&ui.opened==2);
 current=nullptr;owner.RunTalkDialog(&npc,false);assert(owner.started==2);
 puts("PASS actual scripted talk opener: dedicated owner-only routing without UI, separate recruiters, client/SP behavior and missing UI safety");
}
'''
with TemporaryDirectory() as tmp:
    folder=Path(tmp);cpp=folder/'talk.cpp';exe=folder/('talk.exe' if os.name=='nt' else 'talk')
    cpp.write_text(source,encoding='utf8')
    command=(['cl','/nologo','/std:c++17','/EHsc',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
             ['g++','-std=c++17','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=15)
