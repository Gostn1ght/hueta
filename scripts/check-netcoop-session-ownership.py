"""Actual local account ownership code with real Windows process/file races."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp

if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
    raise SystemExit("Windows native checks must run in GitHub Actions")
root = Path(__file__).resolve().parents[1]
cluster = (root/"src/xrGame/netcoop_cluster.inc").read_text(encoding="utf-8")
engine = netcoop_cpp(root, encoding="utf-8")
a = cluster.index('static void cluster_file(')
b = cluster.index('static bool cluster_config_path(',a)
files = cluster[a:b]
a = cluster.index('// ---- session lease:')
b = cluster.index('// ---- transfer ticket',a)
ownership = cluster[a:b]
storage = engine[engine.index('if (pending->storage.active)'):engine.index('characters_refresh_for_list(a->login.c_str());')]
assert storage.index('cluster_on_login(') < storage.index('storage_execute(') < storage.index('cluster_lease_release(')
# The menu's slot list is read from the files, never inside a storage transaction.
listing = engine[engine.index('static void characters_refresh_for_list('):engine.index('static void auth_worker(')]
assert 'character_commits_flush_account(account)' in listing and 's_pending_admission' in listing and 's_actor_character' in listing
selection = engine[engine.index('if (!admission_active() && !character_select(CL, pending->slot'):engine.index('if (!admission_active()) if (Character* character = character_load(CL->netcoop_login')]
assert selection.index('cluster_lease_release(') < selection.index('CL->netcoop_login = NULL')

source = r'''
#define _CRT_SECURE_NO_WARNINGS
#define NOMINMAX
#include <windows.h>
#include <io.h>
#include <cstdio>
#include <cstdarg>
#include <cassert>
#include <cstdint>
#include <map>
#include <string>
#include <iostream>
#include <algorithm>
#include <cctype>
#include <cstring>
using u32=unsigned int;using u64=uint64_t;using LPCSTR=const char*;
using xr_string=std::string;using string_path=char[260];using string64=char[64];using string256=char[256];
template<class A,class B>using xr_map=std::map<A,B>;
template<size_t N>void xr_sprintf(char(&out)[N],const char* format,...){va_list args;va_start(args,format);vsnprintf(out,N,format,args);va_end(args);}
void to_lower(xr_string& value){std::transform(value.begin(),value.end(),value.begin(),[](unsigned char c){return char(std::tolower(c));});}
void cluster_dir(string_path& path){std::snprintf(path,sizeof(path),"cluster\\");CreateDirectoryA(path,nullptr);}
u32 current_port=1267,fixture_now=100;bool fail_open=false,fail_flush=false,fail_rename=false;
u32 cluster_port(){return current_port;}u32 cluster_now(){return fixture_now;}
static const u32 cluster_lease_ttl_s=30;
int flushes=0;
void character_commits_flush_account(LPCSTR){
 ++flushes;
 HANDLE probe=CreateFileA("cluster\\ownership_user.txt",GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
 assert(probe==INVALID_HANDLE_VALUE); // Ownership is retained through the drain.
}
HANDLE checked_open(LPCSTR path,DWORD access,DWORD share,LPSECURITY_ATTRIBUTES security,DWORD creation,DWORD flags,HANDLE template_file){
 return fail_open?INVALID_HANDLE_VALUE:CreateFileA(path,access,share,security,creation,flags,template_file);
}
int checked_commit(int fd){return fail_flush?-1:_commit(fd);}
BOOL checked_move(LPCSTR from,LPCSTR to,DWORD flags){return fail_rename?FALSE:MoveFileExA(from,to,flags);}
#define CreateFileA checked_open
#define _commit checked_commit
#define MoveFileExA checked_move
'''+files+ownership+r'''
struct Child{HANDLE process=nullptr;HANDLE thread=nullptr;};
Child spawn(const std::string& mode,u32 port,const std::string& event=""){
 char executable[MAX_PATH]={};assert(GetModuleFileNameA(nullptr,executable,MAX_PATH));
 std::string command=std::string("\"")+executable+"\" child "+std::to_string(port)+" "+mode+" "+event;
 STARTUPINFOA startup={};startup.cb=DWORD(sizeof(startup));PROCESS_INFORMATION info={};
 assert(CreateProcessA(nullptr,&command[0],nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,nullptr,&startup,&info));
 return {info.hProcess,info.hThread};
}
void completed(Child& child){
 assert(WaitForSingleObject(child.process,10000)==WAIT_OBJECT_0);
 DWORD result=99;assert(GetExitCodeProcess(child.process,&result));assert(result==0);
 CloseHandle(child.thread);CloseHandle(child.process);child={};
}
int main(int argc,char** argv){
 xr_string error;
 if(argc>=4 && std::string(argv[1])=="child"){
  current_port=u32(std::stoul(argv[2]));const std::string mode=argv[3];
  if(mode=="race"){
   const std::string base=argv[4];
   HANDLE start=OpenEventA(SYNCHRONIZE,FALSE,(base+"_start").c_str());assert(start);
   assert(WaitForSingleObject(start,10000)==WAIT_OBJECT_0);CloseHandle(start);
   if(!cluster_claim_session("USER",error))return 0;
   HANDLE won=OpenEventA(EVENT_MODIFY_STATE,FALSE,(base+"_won").c_str());assert(won);
   assert(SetEvent(won));CloseHandle(won);Sleep(INFINITE);return 2;
  }
  if(mode=="probe"){
   assert(!cluster_claim_session("USER",error));assert(s_cluster_ownership.empty());return 0;
  }
  if(mode=="other"){
   assert(cluster_claim_session("other",error));return 0; // Process exit closes it.
  }
  assert(cluster_claim_session("USER",error));
  if(mode=="hold"){
   HANDLE event=OpenEventA(EVENT_MODIFY_STATE,FALSE,argv[4]);assert(event);assert(SetEvent(event));CloseHandle(event);
   Sleep(INFINITE);return 2;
  }
  cluster_lease_release("USER");assert(s_cluster_ownership.empty());return 0;
 }
 // The parent and another process cannot claim the same account. A different
 // account remains independent, and a second local login is rejected too.
 assert(cluster_claim_session("User",error));assert(s_cluster_ownership.size()==1);
 assert(!cluster_claim_session("USER",error));
 Child probe=spawn("probe",1277);completed(probe);
 Child other=spawn("other",1277);completed(other);
 // Stalling past the TTL still does not permit another live writer.
 fixture_now=10000;probe=spawn("probe",1277);completed(probe);
 cluster_lease_release("USER");assert(s_cluster_ownership.empty() && flushes==1);
 assert(!cluster_lease_write("USER"));
 Child claim=spawn("claim",1277);completed(claim);
 // A non-owner's repeated release cannot unlink the new owner's lease.
 const std::string event_name="Local\\LostZoneOwnershipTest"+std::to_string(GetCurrentProcessId());
 HANDLE event=CreateEventA(nullptr,TRUE,FALSE,event_name.c_str());assert(event);
 Child held=spawn("hold",1277,event_name);
 assert(WaitForSingleObject(event,10000)==WAIT_OBJECT_0);
 cluster_lease_release("USER");
 u32 port=0,stamp=0;assert(cluster_lease_holder("user",port,stamp) && port==1277);
 assert(!cluster_claim_session("user",error));
 // Real process termination releases the OS lock; after the compatibility
 // timestamp lease expires, a new owner can commit the same account.
 assert(TerminateProcess(held.process,0));completed(held);CloseHandle(event);
 fixture_now=131;assert(cluster_claim_session("user",error));cluster_lease_release("user");
 // Failed create, fsync or rename must never report a successful claim or
 // leak the exclusive handle; retry in another process remains possible.
 for(int fault=0;fault<3;++fault){
  fail_open=fault==0;fail_flush=fault==1;fail_rename=fault==2;
  assert(!cluster_claim_session("user",error));assert(s_cluster_ownership.empty());
  fail_open=fail_flush=fail_rename=false;
  claim=spawn("claim",1277);completed(claim);
 }
 // Old timestamp-only owners are held conservatively until expiry.
 string_path path;cluster_file("online","user",-1,path);assert(cluster_write_line(path,"1277 100"));
 fixture_now=100;assert(!cluster_claim_session("user",error));assert(s_cluster_ownership.empty());
 fixture_now=130;assert(cluster_claim_session("user",error));cluster_lease_release("user");
 // Start two real claimers against an absent lease at the same barrier.
 HANDLE start=CreateEventA(nullptr,TRUE,FALSE,(event_name+"_start").c_str());
 HANDLE won=CreateEventA(nullptr,TRUE,FALSE,(event_name+"_won").c_str());assert(start && won);
 Child first=spawn("race",1267,event_name),second=spawn("race",1277,event_name);
 assert(SetEvent(start));assert(WaitForSingleObject(won,10000)==WAIT_OBJECT_0);
 HANDLE claimers[2]={first.process,second.process};
 const DWORD loser=WaitForMultipleObjects(2,claimers,FALSE,10000)-WAIT_OBJECT_0;assert(loser<2);
 Child& losing=loser==0?first:second;Child& winning=loser==0?second:first;
 completed(losing);assert(WaitForSingleObject(winning.process,0)==WAIT_TIMEOUT);
 assert(TerminateProcess(winning.process,0));completed(winning);CloseHandle(start);CloseHandle(won);
 fixture_now=131;assert(cluster_claim_session("user",error));cluster_lease_release("user");
 std::cout<<"PASS actual session ownership: cross-process/local duplicate refusal, stalled owner, independent accounts, crash release, drain ordering, stale release, create/fsync/rename failure and legacy lease expiry\n";
}
'''
with TemporaryDirectory(prefix="session-ownership-") as tmp:
    cpp,exe=Path(tmp)/"check.cpp",Path(tmp)/"check.exe"
    cpp.write_text(source,encoding="utf-8")
    subprocess.run(["cl","/nologo","/std:c++17","/EHsc","/W4","/WX","/O2",str(cpp),
                    "/Fe:"+str(exe),"/Fo:"+str(Path(tmp)/"check.obj")],check=True,cwd=tmp)
    subprocess.run([str(exe)],check=True,cwd=tmp,timeout=60)
