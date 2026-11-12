"""CI-only production snapshot clock reset across servers with different uptime."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
native = (root / 'src/xrGame/netcoop_net_sync.inc').read_text(encoding='utf-8')


def method(name):
    start = native.index(name)
    end = native.index('{', start) + 1
    depth = 1
    while depth:
        depth += (native[end] == '{') - (native[end] == '}')
        end += 1
    return native[start:end]


stop = (root / 'src/xrGame/Level_network.cpp').read_text(encoding='utf-8')
start = stop.index('void CLevel::net_Stop(')
assert stop.index('remove_objects();', start) < stop.index('netcoop::client_sync_reset();', start)
source = r'''
#include <cassert>
#include <cmath>
#include <algorithm>
#include <cstdint>
#include <cstdio>
using u32=std::uint32_t;using s64=std::int64_t;
template<class T>T _min(T a,T b){return std::min(a,b);}
template<class T>T _max(T a,T b){return std::max(a,b);}
double _abs(double a){return std::abs(a);}
struct World{u32 timeServer(){return 17;}} world;
World* g_pGameLevel=&world;World& Level(){return world;}
namespace netcoop {
bool pure=true;bool pure_client(){return pure;}
u32 now=1000;u32 real_time_ms(){return now;}
bool s_snapshot_clock_valid=false,s_clock_prev_valid=false,s_respawn_sent=false,s_own_dead=false;
double s_clock_now_max=0,s_clock_prev_max=0,s_clock_candidate=0,s_clock_applied=0;
u32 s_clock_bucket_time=0,s_clock_candidates=0,s_clock_applied_time=0;
float s_snap_interval=33,s_frame_ema=33,s_snap_jitter=5;
u32 s_frame_last=0,s_death_time=0,s_respawn_sent_time=0;
'''
for signature in ('double snapshot_clock_target(', 'void snapshot_clock_advance(',
                  'void snapshot_sample(', 'u32 snapshot_now(', 'void client_sync_reset('):
    source += method(signature) + '\n'
source += r'''
}
int main(){using namespace netcoop;
 snapshot_sample(1000000);assert(snapshot_now()==1000000);
 s_snap_interval=200;s_snap_jitter=80;s_frame_ema=150;s_frame_last=999;
 s_own_dead=true;s_respawn_sent=true;s_death_time=900;s_respawn_sent_time=950;
 // net_Stop runs after Disconnect: pure_client() can already be false.
 pure=false;client_sync_reset();
 assert(!s_snapshot_clock_valid&&!s_clock_prev_valid&&!s_respawn_sent&&!s_own_dead);
 assert(!s_clock_candidates&&!s_clock_bucket_time&&!s_clock_applied_time);
 assert(s_snap_interval==33&&s_snap_jitter==5&&s_frame_ema==33&&!s_frame_last);
 assert(!s_death_time&&!s_respawn_sent_time);
 pure=true;assert(snapshot_now()==17);now=1100;
 snapshot_sample(5000);assert(snapshot_now()==5000);
 now=1110;assert(snapshot_now()==5010);
 // A new session may also be ahead of the old one: do not wait for five
 // confirmations of a supposed outlier from a different server.
 client_sync_reset();now=1200;snapshot_sample(2000000);
 assert(snapshot_now()==2000000&&s_clock_candidates==0);
 client_sync_reset();client_sync_reset();assert(!s_snapshot_clock_valid);
 puts("PASS actual session reset: low/high uptime, first snapshot, detached transport, death and timing state");
}
'''
with TemporaryDirectory() as folder:
    cpp = Path(folder) / 'session-clock.cpp'
    exe = Path(folder) / ('session-clock.exe' if os.name == 'nt' else 'session-clock')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', str(cpp), '/Fe:'+str(exe)] if os.name == 'nt'
               else ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True, timeout=10)
