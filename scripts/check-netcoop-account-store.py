"""Actual account save/lock code with Windows lock and flush failure injection."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp
if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
    raise SystemExit("Windows native checks must run in GitHub Actions")
root=Path(__file__).resolve().parents[1]
engine=netcoop_cpp(root, encoding="utf-8")
a=engine.index('struct ClusterFileLock\n{');b=engine.index('\nstatic void accounts_read(',a)
lock=engine[a:b]
a=engine.index('static bool accounts_save()\n{');b=engine.index('\nstatic Account* account_find(',a)
save=engine[a:b]
source=r'''
#define _CRT_SECURE_NO_WARNINGS
#define NOMINMAX
#include <windows.h>
#include <io.h>
#include <cstdio>
#include <cstdarg>
#include <cassert>
#include <fstream>
#include <sstream>
#include <map>
#include <string>
#include <iostream>
#include <set>
#include <vector>
using u8=unsigned char;using u32=unsigned int;using LPCSTR=const char*;using string_path=char[260];
template<size_t N>void xr_sprintf(char(&out)[N],const char* format,...) {va_list args;va_start(args,format);vsnprintf(out,N,format,args);va_end(args);}
void Msg(const char*,...){}
bool timeout_lock=false,fail_mutex=false,fail_flush=false,fail_rename=false;int releases=0,refreshes=0;
// The cluster lock is a lock file; timeout/creation failure = it cannot be opened.
HANDLE checked_lock_file(LPCSTR path,DWORD access,DWORD share,LPSECURITY_ATTRIBUTES sa,DWORD disposition,DWORD flags,HANDLE t){
 if(timeout_lock||fail_mutex){SetLastError(ERROR_SHARING_VIOLATION);return INVALID_HANDLE_VALUE;}
 return CreateFileA(path,access,share,sa,disposition,flags,t);}
BOOL checked_close(HANDLE handle){++releases;return CloseHandle(handle);}
struct{void update_path(char* out,const char*,const char* file){std::snprintf(out,260,"%s",file);}}FS;
void Sleep_checked(DWORD){}
int checked_commit(int fd){return fail_flush?-1:_commit(fd);}
BOOL checked_move(LPCSTR from,LPCSTR to,DWORD flags){return fail_rename?FALSE:MoveFileExA(from,to,flags);}
#define CreateFileA checked_lock_file
#define CloseHandle checked_close
#define Sleep Sleep_checked
#define _commit checked_commit
#define MoveFileExA checked_move
struct Account{
 std::string login="player",salt="salt",hash="hash",device="device",firebase_uid="uid";
 bool has_money=true,touched=true;u32 money=123;u8 role=1,approval=1;
};
using Accounts=std::map<std::string,Account>;
Accounts s_accounts;bool s_accounts_dirty=true;FILETIME s_accounts_stamp={};
void accounts_path(char* out){std::snprintf(out,260,"accounts.txt");}
void accounts_refresh(){++refreshes;}
void accounts_file_stamp(FILETIME& stamp){stamp.dwLowDateTime=1;}
const char* role_name(u8){return "player";}
// The world master keeps the accounts (doc 154): touched records go to it, the file stays.
namespace netcoop_world{struct AccountRecord{std::string login;};}
bool in_master=false,s_accounts_master=false,put_ok=true;int master_puts=0;std::set<std::string> s_accounts_master_keys;
bool accounts_in_master(){return in_master;}
netcoop_world::AccountRecord account_record(const Account& a){return {a.login};}
bool admission_accounts_put(const std::vector<netcoop_world::AccountRecord>& records,bool only_new){assert(!only_new && records.size()==1 && records[0].login=="player");++master_puts;return put_ok;}
'''+lock+save+r'''
std::string read_file(){std::ifstream file("accounts.txt",std::ios::binary);std::ostringstream out;out<<file.rdbuf();return out.str();}
void reset(){s_accounts_dirty=true;s_accounts["player"].touched=true;std::ofstream("accounts.txt")<<"old committed";}
int main(){
 s_accounts["player"]=Account{};
 reset();timeout_lock=true;accounts_save();timeout_lock=false;
 assert(s_accounts_dirty && read_file()=="old committed" && releases==0 && refreshes==0);
 reset();fail_mutex=true;accounts_save();fail_mutex=false;
 assert(s_accounts_dirty && read_file()=="old committed" && releases==0 && refreshes==0);
 reset();fail_flush=true;accounts_save();fail_flush=false;
 assert(s_accounts_dirty && s_accounts["player"].touched && read_file()=="old committed" && releases==1);
 reset();fail_rename=true;accounts_save();fail_rename=false;
 assert(s_accounts_dirty && s_accounts["player"].touched && read_file()=="old committed" && releases==2);
 accounts_save();
 assert(!s_accounts_dirty && !s_accounts["player"].touched && read_file().find("player|player|salt|hash|123|device|approved|uid")!=std::string::npos);
 const auto saved=read_file();const auto refreshed=refreshes;accounts_save();assert(read_file()==saved && refreshes==refreshed);
 in_master=true;reset();accounts_save();assert(s_accounts_dirty && master_puts==0 && read_file()=="old committed"); // not loaded yet: held
 s_accounts_master=true;put_ok=false;accounts_save();assert(s_accounts_dirty && s_accounts["player"].touched && master_puts==1);
 put_ok=true;accounts_save();assert(!s_accounts_dirty && !s_accounts["player"].touched && master_puts==2 && s_accounts_master_keys.count("player") && read_file()=="old committed");
 std::cout<<"PASS actual account persistence: lock timeout/mutex failure do not write/release unowned lock; fsync/rename failure preserve committed file and dirty state; retry commits\n";
}
'''
with TemporaryDirectory(prefix="account-store-") as tmp:
    cpp=Path(tmp)/"check.cpp";exe=Path(tmp)/"check.exe"
    cpp.write_text(source,encoding="utf-8")
    subprocess.run(["cl","/nologo","/std:c++17","/EHsc","/W4","/WX","/O2",str(cpp),"/Fe:"+str(exe),"/Fo:"+str(Path(tmp)/"check.obj")],check=True,cwd=tmp)
    subprocess.run([str(exe)],check=True,cwd=tmp)
