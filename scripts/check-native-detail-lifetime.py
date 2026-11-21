"""CI-only actual detail cancellation/unload, actual delegates, Windows barrier."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess
if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks run only in Windows GitHub Actions')
root=Path(__file__).resolve().parents[1]
s=(root/'src/Layers/xrRender/DetailManager.cpp').read_text(encoding='utf-8-sig')
def block(needle):
 start=s.index(needle);opening=s.index('{',start);depth=0
 for i in range(opening,len(s)):
  if s[i]=='{':depth+=1
  if s[i]=='}':
   depth-=1
   if depth==0:return s[start:i+1]
 raise AssertionError(needle)
code=r'''
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>
#include "fastdelegate.h"
struct xrCriticalSection{CRITICAL_SECTION cs;xrCriticalSection(){InitializeCriticalSection(&cs);}~xrCriticalSection(){DeleteCriticalSection(&cs);}void Enter(){EnterCriticalSection(&cs);}void Leave(){LeaveCriticalSection(&cs);}};
struct xrCriticalSectionGuard{xrCriticalSection& cs;xrCriticalSectionGuard(xrCriticalSection& c):cs(c){cs.Enter();}~xrCriticalSectionGuard(){cs.Leave();}};
struct{std::vector<fastdelegate::FastDelegate0<>>seqParallel;}Device;
std::atomic<bool>active{false};std::atomic<unsigned>unloads{0};
template<class T>void xr_delete(T*& p){delete p;p=nullptr;}
template<class T>void xr_free(T*& p){free(p);p=nullptr;}
struct Object{void Unload(){assert(!active);}};
struct{void r_close(void*& p){assert(!active);p=nullptr;}}FS;
struct CDetailManager{
 xrCriticalSection MT;std::vector<Object*>objects;using DetailIt=std::vector<Object*>::iterator;
 std::vector<int>m_visibles[3];void*dtFS=reinterpret_cast<void*>(1);unsigned*dtSlots=nullptr;
 bool UseVS(){return false;}void hw_Unload(){assert(false);}void soft_Unload(){assert(!active);++unloads;}
 void MT_CALC(){}void CancelPendingTasks();void Unload();
};
void unrelated(){}
'''+block('void CDetailManager::CancelPendingTasks()')+'\n'+block('void CDetailManager::Unload()')+r'''
int main(){
 CDetailManager first,other;first.dtSlots=static_cast<unsigned*>(malloc(sizeof(unsigned)));first.objects.push_back(new Object);
 auto stale=fastdelegate::FastDelegate0<>(&first,&CDetailManager::MT_CALC),live=fastdelegate::FastDelegate0<>(&other,&CDetailManager::MT_CALC);
 auto plain=fastdelegate::FastDelegate0<>(&unrelated);Device.seqParallel={stale,plain,live,stale};
 first.CancelPendingTasks();assert(Device.seqParallel.size()==2 && Device.seqParallel[0]==plain && Device.seqParallel[1]==live);
 Device.seqParallel.push_back(stale);
 HANDLE entered=CreateEventW(nullptr,TRUE,FALSE,nullptr),release=CreateEventW(nullptr,TRUE,FALSE,nullptr);assert(entered && release);
 std::thread calculation([&]{xrCriticalSectionGuard guard(first.MT);active=true;SetEvent(entered);assert(WaitForSingleObject(release,10000)==WAIT_OBJECT_0);active=false;});
 assert(WaitForSingleObject(entered,10000)==WAIT_OBJECT_0);
 std::atomic<bool>started{false},done{false};std::thread owner([&]{started=true;first.Unload();done=true;});
 while(!started.load())SwitchToThread();Sleep(20);assert(!done && !unloads);
 SetEvent(release);calculation.join();owner.join();CloseHandle(entered);CloseHandle(release);
 assert(done && unloads==1 && first.objects.empty() && !first.dtFS && !first.dtSlots);
 assert(Device.seqParallel.size()==2 && Device.seqParallel[0]==plain && Device.seqParallel[1]==live);
 std::puts("PASS actual detail task cancellation/unload: stale duplicates removed, other callbacks retained, active calculation joined before data release, real delegate equality and Windows lock; no GPU/game");
}
'''
with TemporaryDirectory(prefix='lz-detail-life-') as temporary:
 folder=Path(temporary);cpp=folder/'check.cpp';cpp.write_text(code,encoding='utf-8');exe=folder/'check.exe'
 subprocess.run(['cl','/nologo','/EHsc','/std:c++17','/W3','/I'+str(root/'src/3rd party/fastdelegate'),str(cpp),'/Fe:'+str(exe),'/Fo:'+str(folder/'check.obj')],cwd=folder,check=True)
 subprocess.run([str(exe)],cwd=folder,check=True,timeout=30)
