"""Actual bounded background save admission and Windows commit I/O faults."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks must run in GitHub Actions")
root = Path(__file__).resolve().parents[1]
characters = (root/"src/xrGame/netcoop_characters.inc").read_text(encoding="utf-8")
a=characters.index('struct CharacterCommit {')
b=characters.index('static bool character_sync_commit(',a)
queue=characters[a:b]
# The world master mirror (doc 135) is declared here; this fixture saves locally only.
queue='\n'.join(line for line in queue.split('\n') if 'admission_capture' not in line)
a=b;b=characters.index('static void character_commit_worker(',a)
commit_file=characters[a:b]
worker=characters[b:characters.index('// A synchronous save',b)]
assert 'character_commit_take(commit)' in worker and 'character_commit_finish()' in worker
save=characters[characters.index('static bool character_save(Character&'):characters.index('static bool character_decode(')]
assert save.index('character_path(') < save.index('character_commits_flush(path)') < save.index('character_temp_path(') < save.index('character_snapshot(')
assert save.index('character_snapshot(') < save.index('character_commit_enqueue(std::move(commit))') < save.index('character.last_save = real_time_ms()')
for operation in ('fopen(', 'fwrite(', 'fflush(', 'DeleteFileA(', '_commit('):
    assert operation not in save
assert 'DeleteFileA(' not in queue
assert save.index('character_commit_file(commit)') < save.rindex('character.last_save = real_time_ms()')

source=r'''
#define _CRT_SECURE_NO_WARNINGS
#define NOMINMAX
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <deque>
#include <string>
#include <vector>
#include <mutex>
#include <thread>
#include <atomic>
#include <iostream>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <chrono>
#ifdef _WIN32
#include <windows.h>
#include <io.h>
#else
using LONG=int32_t;
#endif
using u8=unsigned char;using u32=unsigned int;using u64=uint64_t;using LPCSTR=const char*;
using xr_string=std::string;using string_path=char[260];
// Match the engine allocator boundary: construct(const T&) copies even
// when push_back receives an rvalue. The real queue must transfer buffers.
template<class T>struct CopyOnlyAllocator:std::allocator<T>{
 using value_type=T;
 template<class U>struct rebind{using other=CopyOnlyAllocator<U>;};
 CopyOnlyAllocator()=default;
 template<class U>CopyOnlyAllocator(const CopyOnlyAllocator<U>&){}
 void construct(T* where,const T& value){::new(static_cast<void*>(where))T(value);}
};
template<class T,class U>bool operator==(const CopyOnlyAllocator<T>&,const CopyOnlyAllocator<U>&){return true;}
template<class T,class U>bool operator!=(const CopyOnlyAllocator<T>&,const CopyOnlyAllocator<U>&){return false;}
template<class T>using xr_deque=std::deque<T,CopyOnlyAllocator<T>>;
template<class T>using xr_vector=std::vector<T>;
struct xrCriticalSection{std::mutex lock;void Enter(){lock.lock();}void Leave(){lock.unlock();}};
std::vector<std::string>deleted;
void record_delete(LPCSTR path){deleted.push_back(path);
#ifdef _WIN32
 ::DeleteFileA(path);
#endif
}
u32 fixture_pid=123;
u32 process_id(){return fixture_pid;}
#ifdef _WIN32
bool fail_flush=false,fail_rename=false,fail_write=false,fail_open=false;
FILE* checked_open(LPCSTR path,LPCSTR mode){return fail_open?nullptr:fopen(path,mode);}
size_t checked_write(const void* data,size_t size,size_t count,FILE* file){return fail_write?0:fwrite(data,size,count,file);}
#define fopen checked_open
#define fwrite checked_write
int checked_commit(int fd){return fail_flush?-1:_commit(fd);}
BOOL checked_move(LPCSTR from,LPCSTR to,DWORD flags){return fail_rename?FALSE:MoveFileExA(from,to,flags);}
#define _commit checked_commit
#define MoveFileExA checked_move
#else
LONG InterlockedExchange(volatile LONG* target,LONG value){const auto old=*target;*target=value;return old;}
void Sleep(unsigned ms){std::this_thread::sleep_for(std::chrono::milliseconds(ms));}
#endif
#define DeleteFileA record_delete
#define GetCurrentProcessId process_id
std::vector<std::string> fixture_paths;
void character_path(LPCSTR account,u8 slot,string_path& path){
 std::snprintf(path,sizeof(path),"%s_%u.bin",account,unsigned(slot));fixture_paths.emplace_back(path);
}
'''+queue+(commit_file if os.name=="nt" else "")+characters[characters.index('static void character_commits_flush('):characters.index('static bool character_save(Character&')]+r'''
CharacterCommit entry(const std::string& path,const std::string& temp,u64 bytes){CharacterCommit result;result.path=path;result.temp=temp;result.bytes=bytes;result.snapshot.resize(size_t(bytes),42);return result;}
void reset(){assert(!s_commit_busy);s_commits.clear();s_commit_bytes=s_commit_active_bytes=0;deleted.clear();}
void drain(){CharacterCommit work;while(character_commit_take(work))character_commit_finish();}
#ifdef _WIN32
std::string read_file(){std::ifstream file("character.bin",std::ios::binary);std::ostringstream out;out<<file.rdbuf();return out.str();}
void io_faults(){
 std::ofstream("character.bin")<<"previous durable snapshot";
 auto candidate_commit=entry("character.bin","candidate.tmp",21);
 const std::string text="new complete snapshot";candidate_commit.snapshot.assign(text.begin(),text.end());
 fail_open=true;assert(!character_commit_file(candidate_commit));fail_open=false;
 assert(read_file()=="previous durable snapshot");
 fail_write=true;assert(!character_commit_file(candidate_commit));fail_write=false;
 assert(read_file()=="previous durable snapshot" && GetFileAttributesA("candidate.tmp")==INVALID_FILE_ATTRIBUTES);
 fail_flush=true;assert(!character_commit_file(candidate_commit));fail_flush=false;
 assert(read_file()=="previous durable snapshot");
 fail_rename=true;assert(!character_commit_file(candidate_commit));fail_rename=false;
 assert(read_file()=="previous durable snapshot");
 assert(character_commit_file(candidate_commit));assert(read_file()=="new complete snapshot");
 // Execute the actual synchronous completion path, including failed temporary
 // file cleanup, while the prior durable snapshot stays intact.
 auto candidate=[](){FILE* file=fopen("sync.tmp","wb");assert(file);assert(fwrite("next",1,4,file)==4);return file;};
 fail_flush=true;assert(!character_sync_commit(candidate(),"sync.tmp","character.bin"));fail_flush=false;
 assert(read_file()=="new complete snapshot" && GetFileAttributesA("sync.tmp")==INVALID_FILE_ATTRIBUTES);
 fail_rename=true;assert(!character_sync_commit(candidate(),"sync.tmp","character.bin"));fail_rename=false;
 assert(read_file()=="new complete snapshot" && GetFileAttributesA("sync.tmp")==INVALID_FILE_ATTRIBUTES);
 assert(character_sync_commit(candidate(),"sync.tmp","character.bin"));
 assert(read_file()=="next" && GetFileAttributesA("sync.tmp")==INVALID_FILE_ATTRIBUTES);
 // A write error must close and remove the failed candidate too.
 std::ofstream("readonly.tmp")<<"read only candidate";FILE* readonly=fopen("readonly.tmp","rb");assert(readonly);
 assert(fwrite("bad",1,3,readonly)!=3 && ferror(readonly));
 assert(!character_sync_commit(readonly,"readonly.tmp","character.bin"));
 assert(read_file()=="next" && GetFileAttributesA("readonly.tmp")==INVALID_FILE_ATTRIBUTES);
}
#endif
int main(){
 (void)s_commit_worker;
 reset();auto owned=entry("owned","memory",1024);const auto* address=owned.snapshot.data();
 assert(character_commit_enqueue(std::move(owned)));assert(s_commits.front().snapshot.data()==address);
 owned.snapshot.assign(4,99);assert(s_commits.front().snapshot.size()==1024&&s_commits.front().snapshot[0]==42);
 CharacterCommit taken;assert(character_commit_take(taken)&&taken.snapshot.data()==address);character_commit_finish();
 reset();assert(character_commit_enqueue(entry("a","a1",100)));
 assert(character_commit_enqueue(entry("a","a2",200)));
 assert(s_commits.size()==1 && s_commit_bytes==200 && deleted.empty());
 assert(!character_commit_enqueue(entry("a","a2",100)));assert(s_commit_bytes==200);
 CharacterCommit active,second;
 assert(character_commit_take(active));assert(active.temp=="a2" && s_commit_bytes==200 && s_commit_busy);
 assert(!character_commit_take(second));
 assert(character_commit_enqueue(entry("a","a3",300)));
 assert(s_commits.size()==1 && s_commit_bytes==500 && deleted.empty());
 character_commit_finish();assert(s_commit_bytes==300);
 assert(character_commit_take(second));assert(second.temp=="a3");character_commit_finish();
 character_commit_finish();assert(s_commit_bytes==0 && s_commits.empty() && !s_commit_busy);
 // A held unrelated disk write must not hold this player's sync checkpoint.
 reset();assert(character_commit_enqueue(entry("b","b1",20)));
 assert(character_commit_take(active));assert(s_commit_active_path=="b");
 character_commits_flush("a");assert(s_commit_busy && s_commit_bytes==20);
 character_commits_flush_account("alice");
 assert(fixture_paths.size()==10 && fixture_paths.front()=="alice_1.bin" && fixture_paths.back()=="alice_10.bin");
 assert(s_commit_busy && s_commit_bytes==20); // account flush also ignores B
 assert(character_commit_enqueue(entry("b","b2",30)));
 assert(character_commit_enqueue(entry("c","c1",40)));
 assert(character_commit_enqueue(entry("a","a1",10)));
 assert(character_commit_pending("a") && s_commits.front().path=="a");
 assert(!character_commit_pending("missing") && character_commit_pending(nullptr));
 character_commit_finish();assert(character_commit_take(active) && active.path=="a");
 assert(character_commit_pending("a") && s_commit_active_path=="a");
 character_commit_finish();character_commits_flush("a");
 assert(!character_commit_pending("a") && s_commit_bytes==70 && character_commit_pending(nullptr));
 drain();character_commits_flush();assert(s_commit_active_path.empty());
 reset();assert(character_commit_enqueue(entry("a","a1",character_commit_byte_limit)));
 assert(!character_commit_enqueue(entry("b","b1",1)));
 assert(character_commit_take(active));assert(!character_commit_enqueue(entry("b","b1",1)));
 character_commit_finish();assert(character_commit_enqueue(entry("b","b1",1)));drain();
 reset();assert(character_commit_enqueue(entry("a","a1",character_commit_byte_limit-1)));
 assert(character_commit_enqueue(entry("b","b1",1)));
 assert(!character_commit_enqueue(entry("b","b2",2)));assert(s_commit_bytes==character_commit_byte_limit && deleted.empty());
 assert(character_commit_enqueue(entry("a","a2",1)));assert(s_commit_bytes==2);drain();
 assert(!character_commit_enqueue(entry("bad","oversize",character_commit_byte_limit+1)));
 assert(!character_commit_enqueue(entry("bad","empty",0)));
 auto mismatch=entry("bad","mismatch",2);mismatch.snapshot.pop_back();assert(!character_commit_enqueue(std::move(mismatch)));
 reset();for(u32 i=0;i<character_commit_count_limit;++i)assert(character_commit_enqueue(entry(std::to_string(i),"old"+std::to_string(i),1)));
 assert(!character_commit_enqueue(entry("overflow","new",1)));
 assert(character_commit_enqueue(entry("0","replacement",2)));assert(s_commits.size()==character_commit_count_limit);
 drain();assert(s_commit_bytes==0);
 string_path first_path,second_path,sync_path,foreign_path;
 assert(character_temp_path("character.bin",true,first_path));assert(character_temp_path("character.bin",true,second_path));
 assert(character_temp_path("character.bin",false,sync_path));fixture_pid=124;
 assert(character_temp_path("character.bin",true,foreign_path));
 assert(std::strcmp(first_path,second_path) && std::strcmp(first_path,sync_path) && std::strcmp(first_path,foreign_path));
 assert(std::string(first_path).find(".123.")!=std::string::npos && std::string(foreign_path).find(".124.")!=std::string::npos);
 assert(!character_temp_path(std::string(260,'x').c_str(),true,first_path));
 // One real producer and consumer exercise replacement/take/finish under
 // contention. Each path must finish with its latest complete snapshot.
 reset();std::atomic<bool> done{false};std::map<std::string,u32> latest;
 std::thread producer([&](){for(u32 i=1;i<=4000;++i)assert(character_commit_enqueue(entry(std::to_string(i%4),std::to_string(i),100)));done=true;});
 std::thread consumer([&](){for(;;){
  CharacterCommit work;
  if(!character_commit_take(work)){
   if(!done){std::this_thread::yield();continue;}
   if(!character_commit_take(work))break; // Recheck after producer's release barrier.
  }
  latest[work.path]=u32(std::stoul(work.temp));character_commit_finish();
 }});
 producer.join();consumer.join();assert(latest.size()==4 && s_commit_bytes==0 && !s_commit_busy);
 for(u32 i=0;i<4;++i)assert(latest[std::to_string(i)]==4000-((4-i)%4));
#ifdef _WIN32
 io_faults();
#endif
 std::cout<<"PASS actual background commits: bounded bytes/count, complete pending replacement, in-flight accounting, no stale takeover, owned immutable memory, no producer filesystem calls, process-unique names, threaded latest snapshots and Windows open/write/flush/rename faults\n";
}
'''
with TemporaryDirectory(prefix="character-commits-") as tmp:
    cpp=Path(tmp)/"check.cpp";exe=Path(tmp)/("check.exe" if os.name=="nt" else "check")
    cpp.write_text(source,encoding="utf-8")
    if os.name=="nt":
        command=["cl","/nologo","/std:c++17","/EHsc","/W4","/WX","/O2",str(cpp),"/Fe:"+str(exe),"/Fo:"+str(Path(tmp)/"check.obj")]
    else:
        command=["g++","-std=c++17","-Wall","-Wextra","-Werror","-O2","-pthread",str(cpp),"-o",str(exe)]
    subprocess.run(command,check=True,cwd=tmp)
    subprocess.run([str(exe)],check=True,cwd=tmp,timeout=30)
