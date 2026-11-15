"""CI: compile actual asynchronous entry code; exercise real loopback WinHTTP."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

if os.environ.get('GITHUB_ACTIONS') != 'true' or os.name != 'nt':
    raise SystemExit('Native checks must run on Windows GitHub Actions')
root = Path(__file__).resolve().parents[1]
project = (root/'src/xrGame/xrGame.vcxproj').read_text(encoding='utf-8-sig')
import xml.etree.ElementTree as ET
ns={'m':'http://schemas.microsoft.com/developer/msbuild/2003'}
unit=next(e for e in ET.fromstring(project).findall('.//m:ClCompile',ns) if e.get('Include')=='netcoop_entry_worker.cpp')
assert unit.find('m:ExceptionHandling',ns).text=='Sync'
assert unit.find('m:PrecompiledHeader',ns).text=='NotUsing'
wrapper=(root/'src/xrGame/netcoop_client.inc').read_text(encoding='utf-8')
assert 'netcoop_world::poll_entry_route(' in wrapper and 'struct ClientEntryWorker' not in wrapper
class Handler(http.server.BaseHTTPRequestHandler):
    calls = 0
    followed = 0
    def do_GET(self):
        Handler.calls += 1
        time.sleep(.2)
        if self.path == '/followed':
            Handler.followed += 1
            self.send_response(500);self.end_headers();return
        if 'Redirect' in self.path:
            self.send_response(302);self.send_header('Location','/followed');self.send_header('Content-Length','0');self.end_headers();return
        if 'Malformed' in self.path:
            status, result = 200, None
        elif 'BoundaryHost' in self.path:
            status, result = 200, dict(schema=1,host='a'*200,location='l08_yantar',port=1319)
        elif 'Truncated' in self.path:
            status, result = 200, dict(schema=1,host='',location='l08_yantar',port=1319)
        elif 'LongHost' in self.path:
            status, result = 200, dict(schema=1,host='a'*253,location='l08_yantar',port=1319)
        elif 'HugePort' in self.path:
            status, result = 200, dict(schema=1,host='',location='l08_yantar',port=4294968615)
        elif 'NulHost' in self.path:
            status, result = 200, dict(schema=1,host='127.0.0.1\0other',location='l08_yantar',port=1319)
        elif 'DeepBody' in self.path:
            status, result = 200, None
        elif 'HugeBody' in self.path:
            status, result = 200, None
        elif 'WrongSchema' in self.path:
            status, result = 503, dict(schema=2,state='loading',location='l08_yantar',retry_seconds=3)
        elif 'TesterTwo' in self.path:
            status, result = 200, dict(schema=1,host='',location='l08_yantar',port=1319)
        elif 'Disabled' in self.path:
            status, result = 503, dict(schema=1,state='disabled',location='l08_yantar',retry_seconds=0)
        else:
            status, result = 503, dict(schema=1,state='loading',location='l08_yantar',retry_seconds=3)
        body = json.dumps(result).encode()
        if 'Malformed' in self.path: body=b'{invalid json'
        if 'DeepBody' in self.path: body=b'['*1000+b'0'+b']'*1000
        if 'HugeBody' in self.path: body=b' '*5000

        self.send_response(status);self.send_header('Content-Length', str(len(body)+(10 if 'Truncated' in self.path else 0)));self.end_headers();self.wfile.write(body)
    def log_message(self, *_): pass
server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
prefix = r'''
#define NOMINMAX
#include <windows.h>
#include <cassert>
#include <cstdio>
#include <string>
#include <map>
#include <winternl.h>
#include "netcoop_entry_worker.h"
using namespace netcoop_world;
std::string script_master_entry(const char* address,const char* account,int slot){
 char answer[256];poll_entry_route(address,account,slot,answer,sizeof(answer));return answer;
}
void client_entry_stop(){stop_entry_route();}
void handle_types(const char* stage){
 std::map<std::wstring,unsigned> types;
 for(ULONG_PTR value=4;value<65536;value+=4){
  const auto handle=reinterpret_cast<HANDLE>(value);DWORD flags=0;
  if(!GetHandleInformation(handle,&flags))continue;
  alignas(void*) char info[2048]{};ULONG size=0;
  if(NtQueryObject(handle,ObjectTypeInformation,info,sizeof(info),&size)<0)continue;
  const auto type=reinterpret_cast<const UNICODE_STRING*>(info);
  if(type->Buffer && type->Length<512)++types[std::wstring(type->Buffer,type->Length/sizeof(wchar_t))];
 }
 for(const auto& type:types)std::fprintf(stderr,"handles %s %ls=%u\n",stage,type.first.c_str(),type.second);
}
'''
suffix = r'''
std::string wait_result(const char* address,const char* account){
 const auto deadline=GetTickCount64()+5000;
 for(;;){const std::string value=script_master_entry(address,account,1);if(value!="wait|contacting||1") return value;assert(GetTickCount64()<deadline);Sleep(10);}
}
int main(int argc,char**argv){
 assert(argc==2);const auto start=GetTickCount64();assert(std::string(script_master_entry(argv[1],"Tester",1))=="wait|contacting||1");
 assert(GetTickCount64()-start<100);assert(wait_result(argv[1],"Tester")=="wait|loading|l08_yantar|3");
 assert(wait_result(argv[1],"TesterTwo")=="127.0.0.1:1319");
 assert(wait_result(argv[1],"BoundaryHost")==std::string(200,'a')+":1319");
 assert(wait_result(argv[1],"Disabled")=="error|disabled|l08_yantar|1");
 for(const char* bad:{"Malformed","Truncated","LongHost","HugePort","NulHost","DeepBody","HugeBody","WrongSchema","Redirect"}) {
  const auto reply=wait_result(argv[1],bad);
  if(reply!="wait|master_unavailable||3")std::fprintf(stderr,"entry bad case %s reply=%s\n",bad,reply.c_str());
  assert(reply=="wait|master_unavailable||3");
  assert(wait_result(argv[1],"TesterTwo")=="127.0.0.1:1319"); // failure cannot poison lock/thread/cache
 }
 // WinHTTP closes its internal work items asynchronously after CloseHandle.
 // Settle both samples; a transient count at join is not proof of a leak.
 Sleep(1000);
 DWORD handles_before=0,handles_after=0;assert(GetProcessHandleCount(GetCurrentProcess(),&handles_before));
 handle_types("before");
 for(int i=0;i<12;++i){
  assert(std::string(script_master_entry(argv[1],"Malformed",1))=="wait|contacting||1");
  assert(wait_result(argv[1],"Malformed")=="wait|master_unavailable||3");
  assert(wait_result(argv[1],"TesterTwo")=="127.0.0.1:1319");
 }
 client_entry_stop();
 const auto cleanup_deadline=GetTickCount64()+5000;
 do {assert(GetProcessHandleCount(GetCurrentProcess(),&handles_after));if(handles_after<=handles_before+4)break;Sleep(50);}while(GetTickCount64()<cleanup_deadline);
 std::fprintf(stderr,"entry handles: settled_before=%lu after=%lu\n",handles_before,handles_after);
 handle_types("after");
 assert(handles_after<=handles_before+4);
 // Lifecycle stress is distinct from request churn: every real menu teardown
 // joins its worker/session. Reopening must recover even with IO in flight.
 for(int i=0;i<12;++i){
  assert(script_master_entry(argv[1],"Malformed",1)=="wait|contacting||1");
  Sleep(50); // the fixture server delays replies200ms, so stop joins real IO
  const auto stopping=GetTickCount64();client_entry_stop();assert(GetTickCount64()-stopping<5000);
  assert(wait_result(argv[1],"TesterTwo")=="127.0.0.1:1319");
 }
 client_entry_stop();
 char tiny[2]={'x','x'};poll_entry_route(argv[1],"Tester",-1,tiny,sizeof(tiny));assert(tiny[0]==0);
 poll_entry_route(argv[1],"Tester",1,nullptr,0);
 client_entry_stop();assert(std::string(script_master_entry(argv[1],"Tester",1))=="wait|contacting||1");client_entry_stop();
 puts("PASS actual entry worker: nonblocking UI, real WinHTTP 503 loading/disabled states, successful route, account-key isolation, bounded joined shutdown, production EHsc boundary, malformed/deep/oversized responses, oversized/NUL hosts and ports, no HTTP redirect, handle stability and failure recovery");
}
'''
try:
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary);cpp=folder/'entry.cpp';exe=folder/'entry.exe'
        cpp.write_text(prefix+suffix,encoding='utf-8')
        subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX','/utf-8','/D_CRT_SECURE_NO_WARNINGS','/I'+str(root/'src/xrGame'),str(cpp),str(root/'src/xrGame/netcoop_entry_worker.cpp'),'/Fe:'+str(exe),'/link','winhttp.lib','ntdll.lib'],cwd=folder,check=True)
        subprocess.run([str(exe),'127.0.0.1:'+str(server.server_port)],cwd=folder,check=True,timeout=90)
        assert Handler.followed==0
finally:
    server.shutdown();server.server_close();thread.join()
