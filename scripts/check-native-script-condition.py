"""CI-only execution of actual Lua condition setter and inventory clamping."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]

def method(path,name):
    text=(root/path).read_text(encoding='utf8')
    start=text.index(name);end=text.index('{',start)+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

source=r'''
#include <cassert>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <vector>
using u16=unsigned short;
template<class T>void clamp(T&v,T a,T b){v=std::clamp(v,a,b);}
template<class T,class U>T smart_cast(U*p){return dynamic_cast<T>(p);}
struct Object{virtual ~Object()=default;u16 id=0;u16 ID(){return id;}};
struct CInventoryItem:Object{float m_fCondition=.3f;float GetCondition(){return m_fCondition;}void ChangeCondition(float);};
struct CScriptGameObject{Object*item;Object&object(){return *item;}void SetCondition(float);};
namespace ScriptStorage{enum{eLuaMessageTypeError};}
unsigned errors=0;
struct Engine{void script_log(int,const char*){++errors;}}engine;
struct AI{Engine&script_engine(){return engine;}}ai_space;
AI&ai(){return ai_space;}
namespace netcoop{
bool active=true,client=false;std::vector<u16>touched;
bool enabled(){return active;}bool pure_client(){return client;}
void server_item_touch(u16 id){touched.push_back(id);}
}
'''
source+=method('src/xrGame/inventory_item.cpp','void CInventoryItem::ChangeCondition(')
source+=method('src/xrGame/script_game_object.cpp','void CScriptGameObject::SetCondition(')
source+=r'''
int main(){
 CInventoryItem repaired,other;repaired.id=41;other.id=42;
 CScriptGameObject object{&repaired};object.SetCondition(.99999f);
 assert(std::abs(repaired.GetCondition()-.99999f)<.00001f);
 assert(other.GetCondition()==.3f&&netcoop::touched==std::vector<u16>{41});
 object.SetCondition(2);assert(repaired.GetCondition()==1&&netcoop::touched.size()==2);
 object.SetCondition(-1);assert(repaired.GetCondition()==0&&netcoop::touched.size()==3);
 // Client prediction and SP never produce server-forced snapshots.
 netcoop::client=true;object.SetCondition(.5f);assert(repaired.GetCondition()==.5f&&netcoop::touched.size()==3);
 netcoop::client=false;netcoop::active=false;object.SetCondition(.7f);assert(netcoop::touched.size()==3);
 // Noninventory Lua wrappers keep the original diagnostic, without touching another item.
 Object npc;CScriptGameObject invalid{&npc};invalid.SetCondition(1);assert(errors==1&&netcoop::touched.size()==3);
 puts("PASS actual scripted condition setter: repair value, exact item snapshot, clamping, client/SP isolation and invalid-object guard");
}
'''
with TemporaryDirectory() as tmp:
    folder=Path(tmp);cpp=folder/'condition.cpp';exe=folder/('condition.exe' if os.name=='nt' else 'condition')
    cpp.write_text(source,encoding='utf8')
    command=(['cl','/nologo','/std:c++17','/EHsc',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
             ['g++','-std=c++17','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=15)
