"""CI: actual headless precache, PDA key routing and multiplayer aim bodies."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

root=Path(__file__).resolve().parents[1]
def method(path,signature):
    s=(root/path).read_text(encoding='utf-8-sig');a=s.index(signature);b=s.index('{',a);n=1;e=b+1
    while n:n+=(s[e]=='{')-(s[e]=='}');e+=1
    return s[a:e]

precache=r'''
#include <cassert>
#include <vector>
using u32=unsigned;
bool g_dedicated_server=false,g_pGameLevel=true;int vCameraPosition=0;
std::vector<int> g_loading_events;
struct Light {bool active=false;void set_shadow(bool){}void set_position(int){}void set_color(int,int,int){}
 void set_range(float){}void set_active(bool v){active=v;}} light;
struct LightRef {Light* p=nullptr;explicit operator bool()const{return p!=nullptr;}Light* operator->(){return p;}} precache_light;
struct Renderer {bool force=false;int queried=0;bool GetForceGPU_REF(){++queried;return force;}
 LightRef light_create(){return LightRef{&light};}} renderer;
Renderer* Render=&renderer;
struct Screen {bool b_registered=false,wait=false;void start(bool v){b_registered=true;wait=v;}} load_screen_renderer;
struct CRenderDevice {Renderer* m_pRender=&renderer;u32 dwPrecacheFrame=0,dwPrecacheTotal=0;void PreCache(u32,bool,bool);};
''' + method('src/xrEngine/device.cpp','void CRenderDevice::PreCache(') + r'''
int main(){
 CRenderDevice d;g_dedicated_server=true;d.m_pRender=nullptr;d.PreCache(60,true,true);
 assert(d.dwPrecacheFrame==0 && d.dwPrecacheTotal==0 && renderer.queried==0 && !precache_light && !load_screen_renderer.b_registered);
#ifndef DEDICATED_SERVER
 g_dedicated_server=false;d.m_pRender=&renderer;d.PreCache(60,true,true);
 assert(d.dwPrecacheFrame==60 && d.dwPrecacheTotal==60 && light.active && load_screen_renderer.wait);
 renderer.force=true;d.PreCache(60,false,false);assert(d.dwPrecacheFrame==0);
#endif
}
'''
pda=r'''
#include <cassert>
#include <vector>
using u16=unsigned short;
enum EUIMessages{WINDOW_KEY_PRESSED,WINDOW_KEY_RELEASED,WINDOW_KEY_OTHER};
enum EGameActions{kQUIT=1,kINVENTORY=2,kACTIVE_JOBS=3,kOTHER=4};
constexpr int AF_3D_PDA=1,CMD_START=1,CMD_STOP=2,DIK_ESCAPE=1,MOUSE_1=337,MOUSE_8=344;
namespace netcoop {bool pure_client(){return false;}}
struct Flags{bool three=true;bool test(int){return three;}}psActorFlags;
EGameActions get_binded_action(int key){return key==1?kQUIT:key==2?kINVENTORY:key==3?kACTIVE_JOBS:kOTHER;}
struct CUIWindow{virtual ~CUIWindow()=default;int calls=0;CUIWindow* m_pKeyboardCapturer=nullptr;
 virtual bool OnKeyboardAction(int key,EUIMessages e){++calls;if(m_pKeyboardCapturer)return m_pKeyboardCapturer->OnKeyboardAction(key,e);return false;}};
struct Edit:CUIWindow {std::vector<int> keys;bool OnKeyboardAction(int key,EUIMessages e)override{keys.push_back(key);return e!=WINDOW_KEY_OTHER;}};
struct CPda{int actions=0;bool Action(EGameActions,int){++actions;return true;}} item;
CPda* active=&item;
struct Inventory{CPda* ActiveItem(){return active;}} inventory;
struct ActorType{Inventory& inventory(){return ::inventory;}} actor;
ActorType* Actor(){return &actor;}
template<class T,class V>T smart_cast(V* p){return static_cast<T>(p);}
struct CUIPdaWnd:CUIWindow{using inherited=CUIWindow;bool shown=true;bool IsShown(){return shown;}void HideDialog(){shown=false;}
 bool OnKeyboardAction(int,EUIMessages)override;};
''' + method('src/xrGame/ui/UIPdaWnd.cpp','bool CUIPdaWnd::OnKeyboardAction(') + r'''
int main(){
 CUIPdaWnd p;Edit edit;p.m_pKeyboardCapturer=&edit;
 // Raw letters (including game hotkeys), Ctrl+V, backspace and releases:
 for(int key:{19,30,3,29,47,14})for(EUIMessages e:{WINDOW_KEY_PRESSED,WINDOW_KEY_RELEASED})assert(p.OnKeyboardAction(key,e));
 assert(edit.keys.size()==12 && item.actions==0 && p.shown);
 p.shown=false;assert(!p.OnKeyboardAction(30,WINDOW_KEY_PRESSED)&&edit.keys.size()==12);
 p.shown=true;p.m_pKeyboardCapturer=nullptr;assert(p.OnKeyboardAction(3,WINDOW_KEY_PRESSED)&&item.actions==1);
 active=nullptr;assert(!p.OnKeyboardAction(30,WINDOW_KEY_RELEASED));
 psActorFlags.three=false;assert(p.OnKeyboardAction(1,WINDOW_KEY_PRESSED)&&!p.shown);
 p.shown=true;assert(!p.OnKeyboardAction(2,WINDOW_KEY_PRESSED)&&!p.shown);
}
'''
aim=r'''
#include <cassert>
#include <string>
struct Fvector{float x=0,y=0,z=0;Fvector& set(float a,float b,float c){x=a;y=b;z=c;return *this;}};
struct Matrix{void transform_tiny(Fvector& o,const Fvector& v)const{o=v;}};
struct CGameObject{virtual ~CGameObject()=default;Fvector pos;bool center=false;
 bool use_center_to_aim()const{return center;}void Center(Fvector& p)const{p=pos;p.y+=.8f;}
 const Fvector& Position()const{return pos;}Matrix XFORM()const{return Matrix();}};
struct CActor:CGameObject{bool alive=true;bool g_Alive()const{return alive;}};
struct CAI_Stalker:CGameObject{bool alive=true;std::string bone;bool g_Alive()const{return alive;}
 const std::string& aim_bone_id()const{return bone;}void aim_target(Fvector& p,const CGameObject* o){p=o->pos;p.y+=2;}};
template<class T,class V>T smart_cast(V* p){return dynamic_cast<T>(p);}
CActor* g_actor=nullptr;
void aim_target(const char* bone,Fvector& p,const CGameObject* o){assert(std::string(bone)=="bip01_head");p=o->pos;p.y+=1.65f;}
struct CSightManager{CAI_Stalker* m_object;bool aim_target(Fvector&,Fvector&,const CGameObject*)const;};
''' + method('src/xrGame/sight_manager_target.cpp','bool CSightManager::aim_target(') + r'''
int main(){
 CActor anchor,player;g_actor=&anchor;player.pos.y=5;
 CAI_Stalker shooter,npc;CSightManager s{&shooter};Fvector source,target;
 assert(s.aim_target(source,target,&player)&&target.y==6.65f);
 assert(s.aim_target(source,target,&anchor)&&target.y==1.65f);
 assert(s.aim_target(source,target,&npc)&&target.y==1.65f);
 player.alive=false;assert(!s.aim_target(source,target,&player));
 CGameObject prop;assert(!s.aim_target(source,target,&prop));assert(!s.aim_target(source,target,nullptr));
 shooter.bone="custom";assert(s.aim_target(source,target,&player)&&target.y==7);
}
'''

if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native compilation is permitted only in GitHub Actions')
with TemporaryDirectory(prefix='play32-input-ai-') as tmp:
    folder=Path(tmp)
    for name,code in [('precache',precache),('dedicated_precache','#define DEDICATED_SERVER\n'+precache),('pda',pda),('aim',aim)]:
        cpp=folder/(name+'.cpp');exe=folder/(name+'.exe');cpp.write_text(code,encoding='utf-8')
        subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)],cwd=folder,check=True)
        subprocess.run([str(exe)],cwd=folder,check=True,timeout=10)
print('PASS actual runtime/compiled dedicated precache, captured 3D PDA raw keys, living multiplayer aim and legacy fallbacks')
