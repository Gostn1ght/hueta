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
text = (root/'src/xrGame/netcoop_client.inc').read_text(encoding='utf-8')
a = text.index('static LPCSTR master_entry_query(')
code = text[a:text.index('int script_account_state()', a)]
class Handler(http.server.BaseHTTPRequestHandler):
    calls = 0
    def do_GET(self):
        Handler.calls += 1
        time.sleep(.2)
        if 'TesterTwo' in self.path:
            status, result = 200, dict(schema=1,host='',location='l08_yantar',port=1319)
        elif 'Disabled' in self.path:
            status, result = 503, dict(schema=1,state='disabled',location='l08_yantar',retry_seconds=0)
        else:
            status, result = 503, dict(schema=1,state='loading',location='l08_yantar',retry_seconds=3)
        body = json.dumps(result).encode()
        self.send_response(status);self.send_header('Content-Length', str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self, *_): pass
server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
prefix = r'''
#define NOMINMAX
#include <windows.h>
#include <winhttp.h>
#include <thread>
#include <mutex>
#include <string>
#include <cstring>
#include <cstdio>
#include <cassert>
#include <algorithm>
#include "''' + (root/'src/3rd party/nlohmann/json.hpp').as_posix() + r'''"
using u64=unsigned long long;using u32=unsigned;using u8=unsigned char;using xr_string=std::string;using string256=char[256];
#define xr_strlen std::strlen
#define _max std::max
#define _min std::min
template<size_t N> void xr_strcpy(char(&to)[N],const char* from){assert(std::strlen(from)<N);strcpy_s(to,from);}
template<size_t N,class... A> void xr_sprintf(char(&to)[N],const char* format,A...args){assert(std::snprintf(to,N,format,args...)>=0);}
bool login_valid(const char* name){return name && std::strlen(name)>=3 && std::strlen(name)<=20;}
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
 assert(wait_result(argv[1],"Disabled")=="error|disabled|l08_yantar|1");
 client_entry_stop();assert(std::string(script_master_entry(argv[1],"Tester",1))=="wait|contacting||1");client_entry_stop();
 puts("PASS actual entry worker: nonblocking UI, real WinHTTP 503 loading/disabled states, successful route, account-key isolation, bounded joined shutdown");
}
'''
try:
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary);cpp=folder/'entry.cpp';exe=folder/'entry.exe'
        cpp.write_text(prefix+code+suffix,encoding='utf-8')
        subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX','/utf-8','/D_CRT_SECURE_NO_WARNINGS',str(cpp),'/Fe:'+str(exe),'/link','winhttp.lib'],cwd=folder,check=True)
        subprocess.run([str(exe),'127.0.0.1:'+str(server.server_port)],cwd=folder,check=True,timeout=30)
finally:
    server.shutdown();server.server_close();thread.join()
