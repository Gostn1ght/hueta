"""CI-only actual Lua crash-stack entry: no AI construction or cross-thread VM access."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
source=(root/'src/xrServerEntities/script_engine.cpp').read_text(encoding='utf-8')
function=source[source.index('void printLuaStack()'):source.index('int CScriptEngine::lua_pcall_failed(')]
inline=(root/'src/xrGame/ai_space_inline.h').read_text(encoding='utf-8')
accessor=inline[inline.index('IC CScriptEngine* CAI_Space::get_script_engine() const'):inline.index('IC CScriptEngine& CAI_Space::script_engine() const')]
assert 'ai()' not in function
assert 's_lua_stack_thread.store(GetCurrentThreadId(), std::memory_order_release);'in source[source.index('void CScriptEngine::init()'):]
assert 's_lua_stack_thread.store(0, std::memory_order_release);'in source[source.index('CScriptEngine::~CScriptEngine()'):source.index('void CScriptEngine::unload()')]
fixture=r"""
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
using u32=std::uint32_t;
#define IC inline
u32 thread_id=7;u32 GetCurrentThreadId(){return thread_id;}
static std::atomic<u32> s_lua_stack_thread{0};
struct CScriptEngine{bool ready=false;unsigned prints=0;void* lua(){return ready?this:nullptr;}void print_stack(){assert(ready&&thread_id==7);++prints;}};
struct CAI_Space{CScriptEngine* m_script_engine=nullptr;CScriptEngine* get_script_engine()const;};
CAI_Space* g_ai_space=nullptr;
"""+accessor+function+r"""
int main(){
 printLuaStack(); // no engine, must not try ai().init()
 CAI_Space space;g_ai_space=&space;printLuaStack();
 s_lua_stack_thread.store(7);printLuaStack(); // AI allocated but Lua missing
 CScriptEngine engine;space.m_script_engine=&engine;printLuaStack();assert(!engine.prints); // VM not ready
 engine.ready=true;printLuaStack();assert(engine.prints==1);
 thread_id=9;g_ai_space=reinterpret_cast<CAI_Space*>(std::uintptr_t(1));printLuaStack(); // worker does not touch AI at all
 g_ai_space=&space;printLuaStack();assert(engine.prints==1);
 thread_id=7;s_lua_stack_thread.store(0);printLuaStack();assert(engine.prints==1); // teardown
 g_ai_space=nullptr;s_lua_stack_thread.store(7);printLuaStack();
 puts("PASS actual crash Lua stack gate: startup/partial init, absent VM, owner thread, poisoned worker pointer, teardown; native diagnostic cannot construct AI");
}
"""
with TemporaryDirectory()as temporary:
 cpp=Path(temporary)/'crash-lua.cpp';exe=Path(temporary)/('crash-lua.exe'if os.name=='nt'else'crash-lua')
 cpp.write_text(fixture,encoding='utf-8')
 command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)]if os.name=='nt'else
 ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
 subprocess.run(command,cwd=temporary,check=True);subprocess.run([str(exe)],cwd=temporary,check=True,timeout=15)
