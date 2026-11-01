"""CI-only actual cold-stop guards and status withdrawal; no game process."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
text=(root/'src/xrGame/netcoop_cluster.inc').read_text(encoding='utf8')
def block(signature):
    start=text.index(signature);begin=text.index('{',start);end=begin+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]
counter=block('struct ClusterCountOnline')+';'
remove=block('static bool cluster_status_remove(')
idle=block('static void cluster_idle_exit(')
update=text[text.index('static void cluster_update('):]
after=update.split('cluster_idle_exit(server, now);',1)[1].split('cluster_hibernate(',1)[0]
assert 'if (s_cluster_quitting) return;' in after
source=r'''
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>
#include <fstream>
#include <vector>
using u32=unsigned;using LPCSTR=const char*;using string64=char[64];using string_path=char[1024];
template<size_t N,class... T>void xr_sprintf(char(&out)[N],LPCSTR f,T...args){std::snprintf(out,N,f,args...);}
size_t xr_strlen(LPCSTR s){return strlen(s);}void Msg(LPCSTR,...){}void FlushLog(){}
struct {LPCSTR Params="";}Core;
static u32 s_cluster_idle_since=0;static bool s_cluster_quitting=false;
bool admission=true,save_ok=true;unsigned saves=0,quits=0;
bool world_store_admission_open(){return admission;}
bool world_store_save_now(LPCSTR){++saves;return save_ok;}
u32 cluster_port(){return 1267;}
void cluster_file(LPCSTR prefix,LPCSTR key,int slot,string_path& path){assert(slot==-1);xr_sprintf(path,"%s_%s.txt",prefix,key);}
struct IClient{virtual ~IClient()=default;};
struct xrClientData:IClient{struct {bool bLocal=false;}flags;};
struct xrServer{std::vector<IClient*> clients;template<class F>void ForEachClientDo(F f){for(auto* c:clients)f(c);}};
struct ConsoleStub{void Execute(LPCSTR command){assert(std::string(command)=="quit");++quits;}}console;
ConsoleStub* Console=&console;
'''+counter+remove+idle+r'''
int main(){
 xrServer server;xrClientData local,connecting;local.flags.bLocal=true;server.clients={&local,&connecting};
 cluster_idle_exit(&server,1000);assert(!quits && !saves);
 Core.Params="-netcoop_idle_exit=180";
 cluster_idle_exit(&server,1000);cluster_idle_exit(&server,200000);assert(!quits && !saves);
 server.clients={&local};admission=false;cluster_idle_exit(&server,400000);assert(!saves);
 admission=true;cluster_idle_exit(&server,579999);assert(!saves);
 {std::ofstream out("status_1267.txt");out<<"active";}
 save_ok=false;cluster_idle_exit(&server,580000);assert(saves==1 && !quits && !s_cluster_quitting);
 assert(GetFileAttributesA("idle_exit_1267.txt")==INVALID_FILE_ATTRIBUTES);
 save_ok=true;cluster_idle_exit(&server,639999);assert(saves==1);
 HANDLE held=CreateFileA("status_1267.txt",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);assert(held!=INVALID_HANDLE_VALUE);
 cluster_idle_exit(&server,640000);assert(saves==2 && !quits && !s_cluster_quitting);CloseHandle(held);
 cluster_idle_exit(&server,640001);assert(saves==3 && quits==1 && s_cluster_quitting);
 assert(GetFileAttributesA("status_1267.txt")==INVALID_FILE_ATTRIBUTES);
 std::ifstream in("idle_exit_1267.txt");std::string pid;in>>pid;assert(pid==std::to_string(GetCurrentProcessId()));
 cluster_idle_exit(&server,999999);assert(saves==3 && quits==1);
}
'''
with TemporaryDirectory(prefix='cold-idle-') as tmp:
    folder=Path(tmp);cpp=folder/'check.cpp';exe=folder/'check.exe';cpp.write_text(source,encoding='utf8')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe),'/Fo:'+str(folder/'check.obj')],cwd=tmp,check=True)
    subprocess.run([str(exe)],cwd=tmp,check=True,timeout=30)
print('PASS actual idle stop: connecting clients, admission, failed world save/retry, locked status/retry, PID receipt and no dead-port advertisement')
