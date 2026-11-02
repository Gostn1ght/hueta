"""Actual native PDA input gate and window routing; compile/run only in CI."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os, subprocess
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run on GitHub Actions')
root=Path(__file__).resolve().parents[1]
level=(root/'src/xrGame/Level_input.cpp').read_text(encoding='utf-8-sig')
helper=level[level.index('static bool netcoop_pda_key('):level.index('void CLevel::IR_OnKeyboardPress(')]
pda=(root/'src/xrGame/ui/UIPdaWnd.cpp').read_text(encoding='utf-8-sig')
body=pda[pda.index('bool CUIPdaWnd::OnKeyboardAction('):]
# Keep the actual function, independently of any later additions to the file.
start=body.index('{'); depth=1; end=start+1
while depth:
    depth+=(body[end]=='{')-(body[end]=='}');end+=1
body=body[:end]
for method,event in [('Press','PRESSED'),('Release','RELEASED'),('Hold','HOLD')]:
    start=level.index('void CLevel::IR_OnKeyboard'+method+'(')
    function=level[start:level.index('\n}',start)]
    assert function.index('netcoop_pda_key(key, WINDOW_KEY_'+event+')') < function.index('level_input.on_key'), method
stop=pda[pda.index('bool CUIPdaWnd::StopAnyMove()'):pda.index('bool CUIPdaWnd::OnKeyboardAction(')]
source=r'''
#include <cassert>
#include <cstdio>
#include <initializer_list>
enum EUIMessages {WINDOW_KEY_PRESSED,WINDOW_KEY_RELEASED,WINDOW_KEY_HOLD};
enum EGameActions {kQUIT,kINVENTORY,kACTIVE_JOBS,kRELOAD,kJUMP,kUSE};
constexpr int DIK_ESCAPE=1,MOUSE_1=337,MOUSE_8=344,CMD_START=1,CMD_STOP=0,AF_3D_PDA=1;
bool pure=true,g_bDisableAllInput=false,ui_present=true,accept=false;
unsigned raw=0,item=0,press=0,release=0,hold=0,closed=0,cleanup=0;
bool jump_latched=false,pickup_latched=false;
namespace netcoop {bool pure_client(){return pure;}}
EGameActions get_binded_action(int key){return key==DIK_ESCAPE?kQUIT:key==57?kJUMP:key==33?kUSE:kRELOAD;}
struct CPda {bool Action(EGameActions,int){++item;return accept;}} test_item;
struct Inv {CPda* ActiveItem(){return &test_item;}};
struct ActorType {Inv inventory(){return {};}void IR_OnKeyboardRelease(EGameActions command){
 ++cleanup;if(command==kJUMP)jump_latched=false;if(command==kUSE)pickup_latched=false;
}} actor;
ActorType* Actor(){return &actor;}
template<class T> T smart_cast(CPda* p){return static_cast<T>(p);}
struct Flags {bool test(int){return true;}} psActorFlags;
struct Base {bool OnKeyboardAction(int,EUIMessages){++raw;return accept;}};
struct CUIPdaWnd:Base {
 using inherited=Base;bool shown=true,enabled=true,captured=false;
 bool StopAnyMove();bool m_pKeyboardCapturer=false;bool IsShown(){return shown;}bool IsEnabled(){return enabled;}
 void HideDialog(){++closed;}bool OnKeyboardAction(int,EUIMessages);
} window,other;
CUIPdaWnd* test_top=&window;
struct UI {
 CUIPdaWnd& GetPdaMenu(){return window;}CUIPdaWnd* TopInputReceiver(){return test_top;}
 void IR_UIOnKeyboardPress(int key){++press;if(test_top)test_top->OnKeyboardAction(key,WINDOW_KEY_PRESSED);}
 void IR_UIOnKeyboardRelease(int key){++release;if(test_top)test_top->OnKeyboardAction(key,WINDOW_KEY_RELEASED);}
 void IR_UIOnKeyboardHold(int key){++hold;if(test_top)test_top->OnKeyboardAction(key,WINDOW_KEY_HOLD);}
} test_ui;
UI* CurrentGameUI(){return ui_present?&test_ui:nullptr;}
'''+stop+body+helper+r'''
int main(){
 unsigned cases=0;
 for(bool p:{false,true})for(bool shown:{false,true})for(bool present:{false,true})
 for(bool enabled:{false,true})for(bool disabled:{false,true})for(bool capture:{false,true})
 for(bool handled:{false,true})for(int receiver:{0,1,2})for(int key:{1,18,28,44,15,29,47,57,33,MOUSE_1})
 for(auto event:{WINDOW_KEY_PRESSED,WINDOW_KEY_RELEASED,WINDOW_KEY_HOLD}){
  pure=p;assert(window.StopAnyMove()==p);window.shown=shown;ui_present=present;window.enabled=enabled;g_bDisableAllInput=disabled;
  window.m_pKeyboardCapturer=capture;other.m_pKeyboardCapturer=capture;accept=handled;
  test_top=receiver==0?nullptr:receiver==1?&window:&other;
  raw=item=press=release=hold=closed=cleanup=0;
  jump_latched=pickup_latched=true;
  const bool blocked=netcoop_pda_key(key,event);
  assert(blocked==(p&&shown&&present));
  const bool stop=blocked&&event==WINDOW_KEY_RELEASED&&(key==57||key==33);
  assert(cleanup==unsigned(stop));
  assert(jump_latched==!(stop&&key==57));assert(pickup_latched==!(stop&&key==33));
  if(blocked&&!disabled){
   if(key!=DIK_ESCAPE&&key<MOUSE_1){assert(raw==1);assert(item==0);}
   if(key==DIK_ESCAPE){assert(raw==0);assert(item==unsigned(event==WINDOW_KEY_PRESSED));}
  }else assert(raw==0&&item==0&&press==0&&release==0&&hold==0);
  ++cases;
 }
 std::printf("PASS actual PDA window and level gate: %u input cases, raw editing survives declined UI, gameplay isolated, Escape closes\n",cases);
}
'''
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'pda-input.cpp';exe=Path(tmp)/('pda-input.exe' if os.name=='nt' else 'pda-input')
    cpp.write_text(source,encoding='utf-8')
    cmd=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(cmd,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
