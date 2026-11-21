"""CI-only actual warm-hibernation save/retry/wake logic; no game or sleep."""
import os,subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks run only in Windows GitHub Actions')
root=Path(__file__).resolve().parents[1]
text=(root/'src/xrGame/netcoop_cluster.inc').read_text(encoding='utf-8')
def block(needle):
 start=text.index(needle);opening=text.index('{',start);depth=0
 for i in range(opening,len(text)):
  if text[i]=='{':depth+=1
  if text[i]=='}':
   depth-=1
   if depth==0:return text[start:i+1]
 raise AssertionError(needle)
code=r'''
#define NOMINMAX
#include <windows.h>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <vector>
using u32=unsigned;using LPCSTR=const char*;
unsigned saves=0,trims=0,sleeps=0;bool saving=false,admission=true,s_cluster_quitting=false;
bool s_cluster_hibernating=false;u32 s_cluster_empty_since=0,s_cluster_trimmed=0;
struct{LPCSTR Params="-netcoop_hibernate=1";}Core;
size_t xr_strlen(LPCSTR s){return strlen(s);}void Msg(LPCSTR,...){}
bool world_store_admission_open(){return admission;}bool world_store_save_now(LPCSTR){++saves;return saving;}
void fixture_sleep(DWORD value){assert(value==100);++sleeps;}
BOOL fixture_trim(HANDLE process,SIZE_T low,SIZE_T high){assert(process==GetCurrentProcess() && low==SIZE_T(-1) && high==SIZE_T(-1));++trims;return TRUE;}
#define Sleep fixture_sleep
#define SetProcessWorkingSetSize fixture_trim
struct IClient{struct{bool bLocal=false;}flags;};
struct xrServer{std::vector<IClient*>clients;template<class F>void ForEachClientDo(F f){for(auto* c:clients)f(c);}};
'''+block('struct ClusterCountConnected')+';\n'+block('static void cluster_hibernate(')+r'''
int main(){
 xrServer server;IClient local,joining;local.flags.bLocal=true;server.clients={&local,&joining};
 cluster_hibernate(&server,0);server.clients={&local};cluster_hibernate(&server,1000);
 cluster_hibernate(&server,2000);assert(saves==1 && !trims && !sleeps && !s_cluster_hibernating);
 for(u32 now=2001;now<62000;++now)cluster_hibernate(&server,now);
 assert(saves==1);cluster_hibernate(&server,62000);assert(saves==2 && !s_cluster_hibernating);
 server.clients={&local,&joining};cluster_hibernate(&server,0xfffffa00u);
 server.clients={&local};cluster_hibernate(&server,0xfffffff0u);assert(saves==3);
 cluster_hibernate(&server,10);assert(saves==3);cluster_hibernate(&server,59984);assert(saves==4);
 server.clients={&local,&joining};cluster_hibernate(&server,70000);server.clients={&local};saving=true;
 cluster_hibernate(&server,71000);assert(saves==5 && trims==1 && sleeps==1 && s_cluster_hibernating);
 cluster_hibernate(&server,72000);assert(saves==5 && trims==1 && sleeps==2);
 server.clients={&local,&joining};cluster_hibernate(&server,72001);assert(!s_cluster_hibernating && sleeps==2);
 server.clients={&local};admission=false;cluster_hibernate(&server,80000);assert(saves==5);
 admission=true;cluster_hibernate(&server,80999);assert(saves==5);cluster_hibernate(&server,81000);assert(saves==6 && s_cluster_hibernating);
 std::puts("PASS actual hibernation: one-second delay, failed save retried after60s across timer wrap, successful save before trim/sleep, joining-client wake, admission protection; no game/process trim/sleep executed");
}
'''
with TemporaryDirectory(prefix='lz-hibernate-retry-') as temporary:
 folder=Path(temporary);cpp=folder/'check.cpp';cpp.write_text(code,encoding='utf-8');exe=folder/'check.exe'
 subprocess.run(['cl','/nologo','/EHsc','/std:c++17','/W4','/WX',str(cpp),'/Fe:'+str(exe),'/Fo:'+str(folder/'check.obj')],cwd=folder,check=True)
 subprocess.run([str(exe)],cwd=folder,check=True,timeout=30)
