"""Execute actual bootstrap clock/calendar helpers with inert worlds, in CI only."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
clock = (root/'src/xrGame/xr_time.cpp').read_text(encoding='utf-8')
clock = clock[clock.index('ALife::_TIME_ID __game_time()'):clock.index('LPCSTR xrTime::dateToString')]
calendar = (root/'src/xrGame/date_time.cpp').read_text(encoding='utf-8')
calendar = calendar[calendar.index('static u64 generate_time_impl('):calendar.index('static void split_time_impl(')]
level = (root/'src/xrGame/level_script.cpp').read_text(encoding='latin-1')
helpers = level[level.index('u32 get_time_days()'):level.index('void change_game_time(')]
debug = (root/'src/xrCore/xrDebugNew.cpp').read_text(encoding='utf-8')
silent = debug[debug.index('static bool unattended_errors()'):debug.index('#ifdef __BORLANDC__')]
source = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
using u32=std::uint32_t;using u64=std::uint64_t;using LPCSTR=const char*;
namespace ALife {using _TIME_ID=u64;}
''' + calendar + r'''
u64 generate_time(u32 y,u32 mo,u32 d,u32 h,u32 mi,u32 s){return generate_time_impl(y,mo,d,h,mi,s,0);}
struct xrTime {u64 value;explicit xrTime(u64 v):value(v){}};
struct Settings {std::map<std::string,std::string> values;
 bool line_exist(LPCSTR,LPCSTR key){return values.count(key)!=0;}
 LPCSTR r_string(LPCSTR,LPCSTR key){return values.at(key).c_str();}} settings;
Settings* pSettings=&settings;LPCSTR alife_section="alife";unsigned messages=0;
void Msg(LPCSTR){++messages;}
struct Clock {u64 value=999;u64 game_time(){return value;}};
struct Simulator {bool ready=false;Clock* manager=nullptr;
 bool initialized(){return ready;}Clock& time(){assert(ready && manager);return *manager;}} simulator;
struct AI {Simulator* current=nullptr;Simulator* get_alife(){return current;}
 Simulator& alife(){assert(current);return *current;}} ai_state;
AI& ai(){return ai_state;}
struct LevelStub {void* game=nullptr;u64 value=123;
 u64 GetGameTime(){assert(game);return value;}} level;
LevelStub* g_pGameLevel=nullptr;LevelStub& Level(){assert(g_pGameLevel);return *g_pGameLevel;}
void split_time(u64 t,u32& y,u32& mo,u32& d,u32& h,u32& mi,u32& s,u32& ms){
 (void)y;(void)mo;(void)ms;d=u32(t/86400000%31+1);h=u32(t/3600000%24);mi=u32(t/60000%60);s=u32(t/1000%60);}
''' + clock + helpers + r'''
LPCSTR command="";LPCSTR GetCommandLineA(){return command;}
''' + silent + r'''
int main(){
 const auto default_time=generate_time(2018,1,1,12,0,0);
 assert(__game_time()==default_time); // no world, no ALife
 ai_state.current=&simulator; // exact crash: published ALife, null time manager
 assert(__game_time()==default_time);
 g_pGameLevel=&level; // level exists but game state does not
 assert(__game_time()==default_time);
 assert(get_time_struct().value==default_time && get_time()==u32(default_time));
 (void)get_time_days();(void)get_time_hours();(void)get_time_minutes();
 settings.values={{"start_date","29.02.2024"},{"start_time","23:58:59"}};
 const auto configured=generate_time(2024,2,29,23,58,59);
 assert(__game_time()==configured && get_time_hours()==23 && get_time_minutes()==58);
 settings.values["start_date"]="29.02.2023";settings.values["start_time"]="25:00:00";
 assert(__game_time()==default_time); // invalid/leap calendar cannot underflow
 settings.values["start_date"]="1.0.0";assert(__game_time()==default_time);
 pSettings=nullptr;assert(__game_time()==default_time);
 level.game=&level;level.value=generate_time(2020,3,4,5,6,7);
 assert(__game_time()==level.value && get_time_hours()==5);
 Clock committed;committed.value=generate_time(2026,10,31,22,33,44);
 simulator.ready=true;simulator.manager=&committed;
 assert(__game_time()==committed.value && committed.value!=level.value);
 level.game=nullptr;assert(get_time_struct().value==committed.value);
 assert(get_time_hours()==22 && get_time_minutes()==33 && messages==1);
 // Teardown must be just as safe as bootstrap, without resetting the clock.
 simulator.ready=false;simulator.manager=nullptr;assert(__game_time()==default_time);
 command="LostZoneClientDX11.exe";assert(!unattended_errors());
 command="server -netcoop_background";assert(unattended_errors());
 command="server -silent_error_mode";assert(unattended_errors());
 std::puts("PASS actual script clock: null/partial ALife and level, configured/leap calendar, saved authority priority, teardown and unattended error policy; no game started");
}
'''
with TemporaryDirectory() as temporary:
    cpp=Path(temporary)/'bootstrap_clock.cpp'
    exe=Path(temporary)/('bootstrap_clock.exe' if os.name=='nt' else 'bootstrap_clock')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX','/D_CRT_SECURE_NO_WARNINGS',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else
        ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=temporary,check=True)
    subprocess.run([str(exe)],cwd=temporary,check=True)
