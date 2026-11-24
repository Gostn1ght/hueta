"""CI-only actual UpdateTasks keeps character jobs active across maps."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
native = (root/'src/xrGame/GametaskManager.cpp').read_text(encoding='utf-8')
start = native.index('void CGameTaskManager::UpdateTasks()')
end = native.index('void CGameTaskManager::UpdateActiveTask()', start)
update = native[start:end]
assert 'server_task_here' not in update and 'server_task_check_target' not in update
cluster = (root/'src/xrGame/netcoop_cluster.inc').read_text(encoding='utf-8')
assert 's_cancelled_foreign_tasks' not in cluster
task_source=(root/'src/xrGame/GameTask.cpp').read_text(encoding='utf-8')
callback=task_source[task_source.index('void CGameTask::ChangeStateCallback()'):task_source.index('ETaskState CGameTask::UpdateState()')]
source = r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include <string>
using u32=unsigned;
enum ETaskState{eTaskStateInProgress=1,eTaskStateFail=0,eTaskStateCompleted=2};
struct CMapLocation{bool enabled=false;bool PointerEnabled(){return enabled;}void EnablePointer(){enabled=true;}};
struct CGameTask{
 std::string m_ID="job";void ChangeStateCallback();
 const char* origin="cordon";ETaskState state=eTaskStateInProgress,next=eTaskStateInProgress;
 unsigned checks=0;CMapLocation spot;
 ETaskState GetTaskState(){return state;}ETaskState UpdateState(){++checks;return next;}
 CMapLocation* LinkedMapLocation(){return &spot;}
};
struct SGameTaskKey{CGameTask* game_task;};
using TaskVector=std::vector<SGameTaskKey>;
struct vGameTasks:TaskVector{using TaskVector::TaskVector;using TaskVector::operator=;u32 size()const{return u32(TaskVector::size());}};
template<class T>struct buffer_vector:std::vector<T>{
 template<class I>buffer_vector(void*,u32,I begin,I end):std::vector<T>(begin,end){}
};
#define _alloca(size) nullptr
struct {bool paused=false;bool Paused(){return paused;}}Device;
struct Map{unsigned disables=0;void DisableAllPointers(){++disables;}};
struct World{Map map;Map& MapManager(){return map;}}world;
World& Level(){return world;}
int fallback_calls=0,scope_depth=0,arrival_notices=0;bool callback_available=true,callback_throws=false;
namespace GameObject{enum{eTaskStateChange=1};}
struct LegacyCallback{bool valid=false;int calls=0;explicit operator bool()const{return valid;}
 void operator()(CGameTask*,ETaskState){if(valid)++calls;}};
struct CActor{bool server=true;LegacyCallback legacy;unsigned ID(){return 7;}LegacyCallback& callback(int){return legacy;}};
CActor* current_actor=nullptr;CActor* Actor(){return current_actor;}
namespace netcoop{bool client=false;bool pure_client(){return client;}
 bool server_player_copy(CActor* value){return value&&value->server&&!client;}
 void server_task_arrived(CActor&,CGameTask& task){assert(scope_depth==1&&task.state==eTaskStateInProgress);++arrival_notices;}
 struct ServerVictimScope{explicit ServerVictimScope(CActor*){++scope_depth;}~ServerVictimScope(){--scope_depth;}};
}
namespace luabind{template<class T>struct functor{void operator()(CGameTask*,ETaskState){assert(scope_depth==1);++fallback_calls;if(callback_throws)throw 1;}};}
struct ScriptEngine{bool functor(const char*,luabind::functor<void>&){return callback_available;}};
struct AI{ScriptEngine engine;ScriptEngine& script_engine(){return engine;}}fixture_ai;
AI& ai(){return fixture_ai;}
template<class...T>void Msg(const char*,T...){}

struct CGameTaskManager{
 vGameTasks fixture_store;struct Flags{bool changed=true;bool test(int){return changed;}}m_flags;
 enum{eChanged=1};unsigned changed=0,completions=0,failures=0;
 vGameTasks& GetGameTasks(){return fixture_store;}
 CGameTask* ActiveTask(){return fixture_store.empty()?nullptr:fixture_store.front().game_task;}
 void SetTaskState(CGameTask* entry,ETaskState state){entry->state=state;entry->ChangeStateCallback();if(state==eTaskStateCompleted)++completions;else ++failures;}
 void UpdateActiveTask(){++changed;}void UpdateTasks();
};
''' + callback + '\n' + update + r'''
int main(){
 CGameTask local,foreign,finished;foreign.origin="radar";finished.state=eTaskStateCompleted;
 CGameTaskManager manager;manager.fixture_store={{&local},{&foreign},{nullptr},{&finished}};
 manager.UpdateTasks();assert(local.checks==1&&foreign.checks==1&&!finished.checks);
 assert(local.spot.enabled&&manager.changed==1);
 // A foreign issuing map does not prevent completion on this map.
 foreign.next=eTaskStateCompleted;local.next=eTaskStateFail;manager.UpdateTasks();
 assert(manager.completions==1&&manager.failures==1&&foreign.checks==2);
 manager.UpdateTasks();assert(manager.completions==1&&manager.failures==1&&foreign.checks==2);
 CGameTask returning;returning.origin="another-location";manager.fixture_store={{&returning}};
 manager.UpdateTasks();assert(returning.checks==1);
 netcoop::client=true;manager.UpdateTasks();assert(returning.checks==1);
 netcoop::client=false;Device.paused=true;manager.UpdateTasks();assert(returning.checks==1);
 Device.paused=false;manager.fixture_store.clear();manager.UpdateTasks();
 CActor actor;current_actor=&actor;local.ChangeStateCallback();assert(fallback_calls==1&&scope_depth==0&&actor.legacy.calls==0);
 actor.legacy.valid=true;local.ChangeStateCallback();assert(fallback_calls==1&&actor.legacy.calls==1);
 actor.legacy.valid=false;callback_throws=true;local.ChangeStateCallback();assert(fallback_calls==2&&scope_depth==0);
 callback_throws=false;callback_available=false;local.ChangeStateCallback();assert(fallback_calls==2&&scope_depth==0);
 callback_available=true;actor.server=false;actor.legacy.valid=true;local.ChangeStateCallback();assert(actor.legacy.calls==2&&fallback_calls==2);
 actor.server=true;netcoop::client=true;local.ChangeStateCallback();assert(actor.legacy.calls==3&&fallback_calls==2);
 current_actor=nullptr;local.ChangeStateCallback();assert(fallback_calls==2);
 assert(arrival_notices==0);
 current_actor=&actor;actor.legacy.valid=false;netcoop::client=false;
 returning.ChangeStateCallback();assert(arrival_notices==1&&fallback_calls==3);
 actor.legacy.valid=true;returning.ChangeStateCallback();assert(arrival_notices==1&&fallback_calls==3);
 puts("PASS actual task state callback: missing dedicated binder fallback, existing callback once, correct actor scope, error/missing handler, offline/client/null actor");
 puts("PASS actual task manager: local and cross-location jobs update/complete, null entries safe, no repeat rewards, client/paused guards retained");
}
'''
with TemporaryDirectory() as temporary:
    cpp=Path(temporary)/'task-locations.cpp'
    exe=Path(temporary)/('task-locations.exe' if os.name=='nt' else 'task-locations')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
             ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=temporary,check=True)
    subprocess.run([str(exe)],cwd=temporary,check=True,timeout=15)
