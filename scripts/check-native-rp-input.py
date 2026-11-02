"""Exercise the actual level input prefix; RP UI input cannot escape into gameplay;
the view keys reach the player during RP (owner 2026-10-24)."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os, subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run on GitHub Actions')
root = Path(__file__).resolve().parents[1]
text = (root/'src/xrGame/Level_input.cpp').read_text(encoding='utf-8-sig')
start = text.index('void CLevel::IR_OnKeyboardPress(int key)')
prefix = text[start:text.index('    if (_curr == kEDITOR', start)]
button_text=(root/'src/xrGame/ui/UIButton.cpp').read_text(encoding='utf-8-sig')
button=button_text[button_text.index('bool CUIButton::OnMouseAction('):button_text.index('void CUIButton::DrawTexture()')]
source = r'''
#include <cassert>
#include <cstdio>
enum EGameActions { kOTHER, kQUIT, kCONSOLE, kSCREENSHOT, kCAM_1, kCAM_2, kCAM_3 };
constexpr int DIK_Z=1, MOUSE_1=2, MOUSE_2=3, MOVE=4, USE=5, QUIT=6, CONSOLE=7, SCREENSHOT=8, CAM1=9, CAM2=10, CAM3=11;
bool pure=false,g_bDisableAllInput=false,ui_present=false,top=false,consumed=false,has_actor=false;
unsigned ui_calls=0,fallthrough=0;
unsigned stop_clicks=0;
enum EUIMessages {WINDOW_KEY_PRESSED, WINDOW_LBUTTON_DOWN=10,WINDOW_LBUTTON_DB_CLICK,WINDOW_LBUTTON_UP,WINDOW_MOUSE_MOVE,BUTTON_DOWN,BUTTON_CLICKED};
enum {BUTTON_NORMAL=0,BUTTON_PUSHED,BUTTON_UP};
struct CUIButton;
struct Target {void SendMessage(CUIButton*,int msg,void* =nullptr){if(msg==BUTTON_CLICKED)++stop_clicks;}} target;
struct Base {bool OnMouseAction(float,float,EUIMessages){return false;}};
struct CUIButton:Base {
 using inherited=Base;int m_eButtonState=BUTTON_NORMAL;bool m_bCursorOverWindow=true,m_bIsSwitch=false;
 void SetButtonState(int state){m_eButtonState=state;}Target* GetMessageTarget(){return &target;}
 bool OnMouseAction(float x,float y,EUIMessages mouse_action);void OnClick();
} button;
''' + button + r'''
struct { unsigned dwPrecacheFrame=0; } Device;
struct CActor {int m_rp_index=-1;bool g_Alive(){return true;}} test_actor;
struct UI {bool TopInputReceiver(){return top;}bool IR_UIOnKeyboardPress(int key){++ui_calls;if(key==MOUSE_1)button.OnMouseAction(0,0,WINDOW_LBUTTON_DOWN);return consumed;}} ui;
UI* CurrentGameUI(){return ui_present?&ui:nullptr;}
template<class T> T smart_cast(CActor* value){return static_cast<T>(value);}
namespace netcoop {bool pure_client(){return pure;}bool client_death_key(int){return false;}bool client_voice_key(int,bool){return false;}}
namespace luabind {template<class T> struct functor{bool operator()(int){return false;}};}
struct Engine {bool functor(const char*,luabind::functor<bool>&){return false;}} engine;
struct AI {Engine& script_engine(){return engine;}} ai_object;
AI& ai(){return ai_object;}
EGameActions get_binded_action(int key){return key==QUIT?kQUIT:key==CONSOLE?kCONSOLE:key==SCREENSHOT?kSCREENSHOT:
 key==CAM1?kCAM_1:key==CAM2?kCAM_2:key==CAM3?kCAM_3:kOTHER;}
struct CLevel {CActor* CurrentControlEntity(){return has_actor?&test_actor:nullptr;}void IR_OnKeyboardPress(int key);};
''' + 'static bool netcoop_pda_key(int,EUIMessages){return false;}\n' + prefix + r'''
 ++fallthrough;
}
int main(){
 unsigned cases=0;CLevel level;
 for(bool p:{false,true})for(bool a:{false,true})for(bool active:{false,true})
 for(bool shown:{false,true})for(bool receiver:{false,true})for(bool disabled:{false,true})
 for(bool handled:{false,true})for(int key:{DIK_Z,MOUSE_1,MOUSE_2,MOVE,USE,QUIT,CONSOLE,SCREENSHOT,CAM1,CAM2,CAM3}){
  pure=p;has_actor=a;test_actor.m_rp_index=active?0:-1;ui_present=shown;top=receiver;g_bDisableAllInput=disabled;consumed=handled;
  ui_calls=fallthrough=0;level.IR_OnKeyboardPress(key);
  const bool view=key==CAM1||key==CAM2||key==CAM3;
  const bool locked=p&&a&&active&&key!=DIK_Z&&key!=QUIT&&key!=CONSOLE&&key!=SCREENSHOT&&!view;
  assert(ui_calls==unsigned(locked&&shown&&receiver&&!disabled));
  assert(fallthrough==unsigned(!locked));
  ++cases;
 }
 // The actual native button receives press through the RP level gate, then
 // release through the ordinary UI path and emits BUTTON_CLICKED once.
 pure=true;has_actor=true;test_actor.m_rp_index=0;ui_present=top=true;g_bDisableAllInput=false;
 ui_calls=fallthrough=stop_clicks=0;button.SetButtonState(BUTTON_NORMAL);
 level.IR_OnKeyboardPress(MOUSE_1);assert(ui_calls==1 && fallthrough==0 && button.m_eButtonState==BUTTON_PUSHED);
 button.OnMouseAction(0,0,WINDOW_LBUTTON_UP);assert(stop_clicks==1 && button.m_eButtonState==BUTTON_NORMAL);
 std::printf("PASS actual RP input prefix %u cases and actual UIButton press/release: focused UI click delivered; gameplay remains locked even when UI declines; disabled/no UI/SP/system paths preserved; view keys pass\n",cases);
}
'''
# initializer_list is required by the matrix loops on both toolchains.
source = '#include <initializer_list>\n' + source
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'rp-input.cpp';exe=Path(tmp)/('rp-input.exe' if os.name=='nt' else 'rp-input')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
        ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
