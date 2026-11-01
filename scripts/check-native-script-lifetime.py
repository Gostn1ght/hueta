"""CI-only actual Lua object lifetime gates used by the reported dialogue crash."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
def method(file,signature):
    text=(root/'src/xrGame'/file).read_text(encoding='utf-8-sig')
    start=text.index(signature);begin=text.index('{',start);end=begin+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]
source=r'''
#include <cassert>
#include <set>
template<class T>using xr_set=std::set<T>;
template<class T,class U>T smart_cast(U* p){return dynamic_cast<T>(p);}
#define R_ASSERT2(value,message) assert(value)
constexpr int eLuaMessageTypeError=1;
struct Script {void script_log(int,const char*,...) {}};
struct AI {Script s;Script& script_engine(){return s;}};
AI& ai(){static AI a;return a;}
struct CScriptGameObject;
struct CGameObject {CScriptGameObject* wrapper=nullptr;virtual ~CGameObject()=default;CScriptGameObject* lua_game_object(){return wrapper;}};
struct CInventoryOwner:CGameObject {bool IsTalking(){return true;}};
struct CScriptGameObject {
 CGameObject* m_game_object;void* m_door;
 explicit CScriptGameObject(CGameObject*);~CScriptGameObject();
 bool is_valid()const;CGameObject& object()const;bool IsTalking();
 void unregister_door(){m_door=nullptr;}
};
static xr_set<const CScriptGameObject*> s_live_script_objects;
'''
for signature in ('bool CScriptGameObject::is_valid()', 'CScriptGameObject::CScriptGameObject(', 'CScriptGameObject::~CScriptGameObject('):
    source+='\n'+method('script_game_object_use.cpp',signature)
source+='\n'+method('script_game_object.cpp','CGameObject& CScriptGameObject::object()')
source+='\n'+method('script_game_object_inventory_owner.cpp','bool CScriptGameObject::IsTalking()')
source+=r'''
int main(){
 CInventoryOwner npc;auto* wrapper=new CScriptGameObject(&npc);npc.wrapper=wrapper;
 assert(wrapper->is_valid() && wrapper->IsTalking() && &wrapper->object()==&npc);
 npc.wrapper=nullptr;assert(!wrapper->is_valid() && !wrapper->IsTalking());
 bool caught=false;try{wrapper->object();}catch(const char*){caught=true;}assert(caught);
 npc.wrapper=wrapper;assert(wrapper->is_valid());delete wrapper;
 // Late Lua callback: membership is checked without reading freed fields.
 assert(s_live_script_objects.empty());assert(!wrapper->is_valid() && !wrapper->IsTalking());
 caught=false;try{wrapper->object();}catch(const char*){caught=true;}assert(caught);
}
'''
with TemporaryDirectory(prefix='script-lifetime-') as tmp:
    folder=Path(tmp);cpp=folder/'check.cpp';exe=folder/'check.exe';cpp.write_text(source,encoding='utf8')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4',str(cpp),'/Fe:'+str(exe),'/Fo:'+str(folder/'check.obj')],cwd=tmp,check=True)
    subprocess.run([str(exe)],cwd=tmp,check=True,timeout=30)
print('PASS actual script object: live dialogue, detached wrapper, destroyed wrapper and controlled Lua exception')
