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
receipt=block('static bool cluster_idle_receipt(')
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
enum class Fault{none,open,write,short_write,flush,close,publish};
Fault fault=Fault::none;unsigned open_handles=0;
HANDLE receipt_create(LPCSTR name,DWORD access,DWORD share,LPSECURITY_ATTRIBUTES security,DWORD mode,DWORD attrs,HANDLE base){
 if(fault==Fault::open)return INVALID_HANDLE_VALUE;
 HANDLE h=CreateFileA(name,access,share,security,mode,attrs,base);if(h!=INVALID_HANDLE_VALUE)++open_handles;return h;
}
BOOL receipt_write(HANDLE h,LPCVOID data,DWORD size,LPDWORD written,LPOVERLAPPED overlapped){
 if(fault==Fault::write){*written=0;return FALSE;}
 if(fault==Fault::short_write)return WriteFile(h,data,size-1,written,overlapped);
 return WriteFile(h,data,size,written,overlapped);
}
BOOL receipt_flush(HANDLE h){return fault==Fault::flush ? FALSE:FlushFileBuffers(h);}
BOOL receipt_close(HANDLE h){const BOOL result=CloseHandle(h);assert(open_handles);--open_handles;return fault==Fault::close ? FALSE:result;}
BOOL receipt_publish(LPCSTR from,LPCSTR to,DWORD flags){
 std::ifstream in(from);std::string pid;in>>pid;in.close();assert(pid==std::to_string(GetCurrentProcessId()));
 if(fault==Fault::publish)return FALSE;
 return MoveFileExA(from,to,flags);
}
#define CreateFileA receipt_create
#define WriteFile receipt_write
#define FlushFileBuffers receipt_flush
#define CloseHandle receipt_close
#define MoveFileExA receipt_publish
'''+receipt+r'''
#undef CreateFileA
#undef WriteFile
#undef FlushFileBuffers
#undef CloseHandle
#undef MoveFileExA
'''+counter+remove+idle+r'''
void receipt_failures(){
 const char* path="receipt.txt";string_path temporary;xr_sprintf(temporary,"%s.tmp.%u",path,GetCurrentProcessId());
 for(auto failure:{Fault::open,Fault::write,Fault::short_write,Fault::flush,Fault::close,Fault::publish}){
  for(bool previous:{false,true}){
   DeleteFileA(path);if(previous){std::ofstream out(path);out<<"previous";}
   fault=failure;assert(!cluster_idle_receipt(path));assert(!open_handles);
   assert(GetFileAttributesA(temporary)==INVALID_FILE_ATTRIBUTES);
   if(previous){std::ifstream in(path);std::string value;in>>value;assert(value=="previous");}
   else assert(GetFileAttributesA(path)==INVALID_FILE_ATTRIBUTES);
  }
 }
 fault=Fault::none;
 assert(cluster_idle_receipt(path));assert(!open_handles);
 std::ifstream in(path);std::string value;in>>value;in.close();assert(value==std::to_string(GetCurrentProcessId()));
 assert(GetFileAttributesA(temporary)==INVALID_FILE_ATTRIBUTES);DeleteFileA(path);
 {std::ofstream out(path);out<<"previous";}
 HANDLE held=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);assert(held!=INVALID_HANDLE_VALUE);
 assert(!cluster_idle_receipt(path));assert(!open_handles);assert(GetFileAttributesA(temporary)==INVALID_FILE_ATTRIBUTES);
 CloseHandle(held);DeleteFileA(path);
}
int main(){
 receipt_failures();
 xrServer server;xrClientData local,connecting;local.flags.bLocal=true;server.clients={&local,&connecting};
 Core.Params="-netcoop_idle_exit=1";cluster_idle_exit(&server,0);server.clients={&local};
 cluster_idle_exit(&server,1000);save_ok=false;cluster_idle_exit(&server,2000);assert(saves==1);
 for(u32 now=2001;now<62000;++now)cluster_idle_exit(&server,now);
 assert(saves==1 && !quits);cluster_idle_exit(&server,62000);assert(saves==2 && !quits);
 server.clients={&local,&connecting};cluster_idle_exit(&server,0xfffffa00u);
 server.clients={&local};cluster_idle_exit(&server,0xfffffff0u);assert(saves==3);
 cluster_idle_exit(&server,10);assert(saves==3);cluster_idle_exit(&server,59984);assert(saves==4);
 server.clients={&local,&connecting};Core.Params="-netcoop_idle_exit=180";
 cluster_idle_exit(&server,0);saves=quits=0;save_ok=true;Core.Params="";

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
 cluster_idle_exit(&server,640000);assert(saves==2 && !quits && !s_cluster_quitting);
 assert(GetFileAttributesA("idle_exit_1267.txt")==INVALID_FILE_ATTRIBUTES);CloseHandle(held);
 cluster_idle_exit(&server,640001);assert(saves==2 && !quits);
 fault=Fault::flush;cluster_idle_exit(&server,700000);assert(saves==3 && !quits && !s_cluster_quitting);
 assert(GetFileAttributesA("idle_exit_1267.txt")==INVALID_FILE_ATTRIBUTES);
 assert(GetFileAttributesA("status_1267.txt")!=INVALID_FILE_ATTRIBUTES);
 fault=Fault::none;cluster_idle_exit(&server,759999);assert(saves==3 && !quits);
 cluster_idle_exit(&server,760000);assert(saves==4 && quits==1 && s_cluster_quitting);
 assert(GetFileAttributesA("status_1267.txt")==INVALID_FILE_ATTRIBUTES);
 std::ifstream in("idle_exit_1267.txt");std::string pid;in>>pid;assert(pid==std::to_string(GetCurrentProcessId()));
 cluster_idle_exit(&server,999999);assert(saves==4 && quits==1);
}
'''
with TemporaryDirectory(prefix='cold-idle-') as tmp:
    folder=Path(tmp);cpp=folder/'check.cpp';exe=folder/'check.exe';cpp.write_text(source,encoding='utf8')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe),'/Fo:'+str(folder/'check.obj')],cwd=tmp,check=True)
    subprocess.run([str(exe)],cwd=tmp,check=True,timeout=30)
print('PASS actual idle stop: atomic PID receipt, open/write/short/flush/close/publish failures, locked target, no handle leaks; save/admission/status/retry guards and no dead-port advertisement')
