"""Exercise actual do_exit logging and normal/silent termination ordering."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
for filename in ['xrDebug.cpp','xrDebugNew.cpp']:
    text=(root/'src/xrCore'/filename).read_text(encoding='latin-1')
    start=text.index('void xrDebug::do_exit(const std::string& message)')
    method=text[start:text.index('\n}',start)+2]
    policy=''
    if 'unattended_errors()' in method:
        begin=text.index('static bool unattended_errors()')
        policy=text[begin:text.index('\n}',begin)+2]
    source=r'''
#include <cassert>
#include <string>
#include <vector>
#include <iostream>
#include <cstring>
struct xrDebug {void do_exit(const std::string&);};
std::vector<std::string> events;
std::string reason;
std::string command_line;
const char* GetCommandLine(){return command_line.c_str();}
const char* GetCommandLineA(){return command_line.c_str();}
constexpr int MB_OK=1,MB_ICONERROR=2,MB_SYSTEMMODAL=4;
struct Terminated {};
void Msg(const char* format,const char* value){
 assert(std::string(format)=="! [X-Ray][exit] %s");
 assert(std::string(value)==reason);events.push_back("log");
}
void FlushLog(){events.push_back("flush");}
void MessageBox(void* window,const char* message,const char* title,int flags){
 assert(!window && std::string(message)==reason && std::string(title)=="Error");
 assert(flags==(MB_OK|MB_ICONERROR|MB_SYSTEMMODAL));events.push_back("dialog");
}
void* GetCurrentProcess(){return &events;}
void TerminateProcess(void* process,int code){
 assert(process==&events && code==1);events.push_back("terminate");throw Terminated{};
}
''' + policy + method + r'''
int main(){
 for(int mode:{0,1,2})for(const std::string value:{"", "world is locked or lock file is inaccessible", "missing archive %s %n", "invalid path\nsecond line"}){
  const bool silent=mode==1 || (mode==2 && std::string("FILE_NAME")=="xrDebugNew.cpp");
  command_line=mode==1?"LostZoneServer.exe -dedicated -silent_error_mode":mode==2?"LostZoneServer.exe -netcoop_background":"LostZoneClient.exe -netcoop";
  events.clear();reason=value;xrDebug debug;bool stopped=false;
  try{debug.do_exit(reason);}catch(const Terminated&){stopped=true;}
  assert(stopped);
  const std::vector<std::string> expected=silent?
   std::vector<std::string>{"log","flush","terminate"}:
   std::vector<std::string>{"log","flush","dialog","terminate"};
  assert(events==expected);
 }
 std::cout<<"PASS actual do_exit: logged/flushed reason then terminate; ordinary dialog retained, explicit silent mode skips only dialog\n";
}
'''
    with TemporaryDirectory() as tmp:
        cpp=Path(tmp)/'exit.cpp';exe=Path(tmp)/('exit.exe' if os.name=='nt' else 'exit')
        cpp.write_text(source.replace('FILE_NAME',filename),encoding='utf-8')
        if os.name=='nt':
            command=['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)]
        else:
            command=['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(exe)]
        subprocess.run(command,cwd=tmp,check=True)
        subprocess.run([str(exe)],cwd=tmp,check=True)
