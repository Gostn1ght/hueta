"""CI-only: actual condition clock rebases on master catch-up and preserves ordinary updates."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
text = (root / 'src/xrGame/EntityCondition.cpp').read_text(encoding='utf-8')
body = text[text.index('void CEntityCondition::UpdateConditionTime()'):text.index('void CEntityCondition::UpdateCondition()')]
items = (root / 'src/xrGame/netcoop_items.inc').read_text(encoding='utf-8')
reset = items[items.index('void client_items_reset()'):items.index('void client_item_forget(')]
source = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <map>
#include <cstdio>
using u32=unsigned;using u64=std::uint64_t;
constexpr int eGameIDSingle=1;int game=eGameIDSingle;int GameID(){return game;}
bool coop=true;namespace netcoop{bool enabled(){return coop;}}
template<class T>T _max(T a,T b){return std::max(a,b);}
struct World{u64 now=0;float factor=10;u64 GetGameTime(){return now;}u64 timeServer(){return now;}float GetGameTimeFactor(){return factor;}}world;
World& Level(){return world;}
struct CEntityCondition{
 bool m_bTimeValid=false;u64 m_iLastTimeCalled=0;
 float m_fDeltaHealth=3,m_fDeltaPower=3,m_fDeltaRadiation=3,m_fDeltaCircumspection=3,m_fDeltaEntityMorale=3,delta=0;
 void SetConditionDeltaTime(float x){delta=x;}void UpdateConditionTime();
};
''' + body + r'''
std::map<int,int>s_client_items,s_client_item_pending,s_client_item_reports;
u32 s_client_item_stale=9,s_client_item_applied=10;
''' + reset + r'''
int main(){
 CEntityCondition condition;world.now=1500000000000ULL;condition.UpdateConditionTime();assert(condition.delta==0&&condition.m_fDeltaHealth==0);
 world.now+=1000;condition.UpdateConditionTime();assert(condition.delta==1);
 world.now+=553484000ULL;condition.UpdateConditionTime();assert(condition.delta==0);
 world.now+=1500;condition.UpdateConditionTime();assert(condition.delta==1.5f);
 world.now-=5000;condition.UpdateConditionTime();assert(condition.delta==0);
 world.factor=60;world.now+=300000;condition.UpdateConditionTime();assert(condition.delta==300);
 world.now+=86400000;condition.UpdateConditionTime();assert(condition.delta==0);
 coop=false;world.now+=86400000;condition.UpdateConditionTime();assert(condition.delta==86400);
 game=2;world.now+=10;condition.UpdateConditionTime();assert(condition.delta==.01f);
 s_client_items[1]=7;s_client_item_pending[2]=8;s_client_item_reports[3]=9;
 client_items_reset();assert(s_client_items.empty()&&s_client_item_pending.empty()&&s_client_item_reports.empty());
 assert(s_client_item_stale==0&&s_client_item_applied==0);client_items_reset();
 std::puts("PASS actual condition clock: first update, normal accelerated schedule, master catch-up, backward jump, SP unchanged; actual cross-location item cache reset");
}
'''
with TemporaryDirectory(prefix='condition-clock-') as temporary:
    folder = Path(temporary)
    cpp, exe = folder / 'clock.cpp', folder / ('clock.exe' if os.name == 'nt' else 'clock')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)]
               if os.name == 'nt' else ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
