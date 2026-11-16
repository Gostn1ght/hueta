"""CI-only actual bounded TBB CPU jobs, server planner and1-4W skin kernels. No GPU/game."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess,shutil

if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native CPU checks run only on Windows GitHub Actions')
root=Path(__file__).resolve().parents[1]
skin=(root/'src/xrCPU_Pipe/xrSkin2W.cpp').read_text(encoding='utf-8-sig')
skin=skin[skin.index('void __stdcall xrSkin1W_x86'):]
wrapper=(root/'src/xrCPU_Pipe/xrSkin2W_thread.cpp').read_text(encoding='utf-8-sig')
wrapper=wrapper[wrapper.index('extern xrSkin1W*'):]
source=r'''
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cfenv>
#include <xmmintrin.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <mutex>
#include <random>
#include <set>
#include <thread>
#include <type_traits>
#include <vector>
#include "xr_cpu_jobs.h"
#include "netcoop_replication_plan.h"
using u32=unsigned;
// Matrix/vector boundary doubles; both serial/parallel run the ACTUAL engine
// kernels below. Full native build verifies the real engine types/ABI.
struct Fvector {
 float x=0,y=0,z=0;
 void mul(float w){x*=w;y*=w;z*=w;}
 void add(const Fvector& p){x+=p.x;y+=p.y;z+=p.z;}
 void lerp(const Fvector& a,const Fvector& b,float w){x=a.x*(1-w)+b.x*w;y=a.y*(1-w)+b.y*w;z=a.z*(1-w)+b.z*w;}
};
struct Fmatrix {
 float a=1,b=2,c=3,t=4;
 void transform_tiny(Fvector& o,const Fvector& p)const{o={p.x*a+t,p.y*b+t,p.z*c+t};}
 void transform_dir(Fvector& o,const Fvector& p)const{o={p.x*a,p.y*b,p.z*c};}
};
struct CBoneInstance{Fmatrix mRenderTransform;};
struct vertRender{Fvector P,N;float u,v;};
struct vertBoned1W{Fvector P,N;float u,v;u32 matrix;};
struct vertBoned2W{Fvector P,N;float u,v,w;u32 matrix0,matrix1;};
struct vertBoned3W{Fvector P,N;float u,v,w[2];u32 m[3];};
struct vertBoned4W{Fvector P,N;float u,v,w[3];u32 m[4];};
using xrSkin1W=void __stdcall(vertRender*,vertBoned1W*,u32,CBoneInstance*);
using xrSkin2W=void __stdcall(vertRender*,vertBoned2W*,u32,CBoneInstance*);
using xrSkin3W=void __stdcall(vertRender*,vertBoned3W*,u32,CBoneInstance*);
using xrSkin4W=void __stdcall(vertRender*,vertBoned4W*,u32,CBoneInstance*);
'''+skin+r'''
xrSkin1W* skin1W_func=xrSkin1W_x86;
xrSkin2W* skin2W_func=xrSkin2W_x86;
xrSkin3W* skin3W_func=xrSkin3W_x86;
xrSkin4W* skin4W_func=xrSkin4W_x86;
'''+wrapper+r'''
struct Probe {
 std::vector<std::uint64_t> output;
 std::mutex lock;std::set<std::thread::id> threads;bool nested=false;
 static void run(void* p,std::size_t begin,std::size_t end)noexcept{
  auto& x=*static_cast<Probe*>(p);
  {std::lock_guard<std::mutex> g(x.lock);x.threads.insert(std::this_thread::get_id());}
  for(auto i=begin;i<end;++i){std::uint64_t v=i+1;for(unsigned k=0;k<4096;++k)v=(v*6364136223846793005ULL)+1;x.output[i]=v;}
 }
 static void nested_task(void* p,std::size_t begin,std::size_t end)noexcept{
  auto& x=*static_cast<Probe*>(p);const auto s=xr_cpu::parallel_for(end-begin,1,run,p,4);assert(s.slots==1);x.nested=true;
 }
};
struct Nested {
 std::vector<unsigned> output;
 static void inner(void* p,std::size_t begin,std::size_t end)noexcept{
  static_cast<std::atomic<unsigned>*>(p)->fetch_add(unsigned(end-begin));
 }
 static void run(void* p,std::size_t begin,std::size_t end)noexcept{
  auto& x=*static_cast<Nested*>(p);
  for(auto i=begin;i<end;++i){std::atomic<unsigned> touched{0};
   auto s=xr_cpu::parallel_for(8,1,inner,&touched,4);assert(s.slots==1 && touched.load()==8);x.output[i]=1;}
 }
};
struct Environment {
 int expected;unsigned expected_sse;std::atomic<bool> valid{true};
 static void run(void* p,std::size_t,std::size_t)noexcept{
  auto& x=*static_cast<Environment*>(p);
  if(std::fegetround()!=x.expected || (_mm_getcsr()&0xffc0u)!=x.expected_sse)x.valid=false;
  std::fesetround(FE_UPWARD); // Scope must restore the worker/caller environment.
  _mm_setcsr(_mm_getcsr()^0x8040u); // Perturb FTZ/DAZ, as initialized by the engine.
 }
};
struct OnceProbe {
 std::array<std::atomic<unsigned>,8192> calls{};
 static void run(void* p,std::size_t index)noexcept{
  static_cast<OnceProbe*>(p)->calls[index].fetch_add(1,std::memory_order_relaxed);
 }
 void reset(){for(auto& item:calls)item.store(0);}
 void verify(){for(auto& item:calls)assert(item.load()==1);}
};
template<class V,class Serial,class Parallel>void skins(Serial serial,Parallel parallel){
 for(u32 n:{0u,1u,7u,8u,511u,512u,513u,1023u,1024u,1025u,4097u,8193u,65536u}){
  std::vector<V> input(n);std::vector<CBoneInstance> bones(16);
  for(unsigned i=0;i<16;++i)bones[i].mRenderTransform={float(i+1),float(i+2),float(i+3),float(i)};
  for(u32 i=0;i<n;++i){auto& v=input[i];v.P={float(i%17),float(i%23),float(i%31)};v.N={.1f,.2f,.3f};v.u=float(i);v.v=-float(i);}
  // Distribute valid bone indices/weights without relying on a common layout.
  for(u32 i=0;i<n;++i){
   if constexpr(std::is_same<V,vertBoned1W>::value)input[i].matrix=i%16;
   else if constexpr(std::is_same<V,vertBoned2W>::value){input[i].matrix0=i%16;input[i].matrix1=(i+1)%16;input[i].w=.4f;}
   else {for(unsigned j=0;j<sizeof(input[i].m)/sizeof(u32);++j)input[i].m[j]=(i+j)%16;for(auto& w:input[i].w)w=.2f;}
  }
  const auto before=input;const auto saved=bones;
  std::vector<vertRender> a(n+2),b(n+2);std::memset(a.data(),0x5a,a.size()*sizeof(vertRender));b=a;
  serial(a.data()+1,input.data(),n,bones.data());parallel(b.data()+1,input.data(),n,bones.data());
  assert(std::memcmp(a.data(),b.data(),a.size()*sizeof(vertRender))==0);
  assert(!n || std::memcmp(input.data(),before.data(),n*sizeof(V))==0);
  assert(std::memcmp(saved.data(),bones.data(),saved.size()*sizeof(CBoneInstance))==0);
 }
}
std::vector<u32> reference(const std::vector<netcoop_world::PlanRecord>& rows,const netcoop_world::PlanObserver& eye,u32 tick,unsigned scale){
 std::vector<u32> out;
 for(std::size_t i=0;i<rows.size();++i){const auto& r=rows[i];if(r.owner_only!=65535&&r.owner_only!=eye.owner)continue;
  const float x=eye.x-r.x,y=eye.y-r.y,z=eye.z-r.z;
  const float d=r.full_rate||r.id==eye.owner?0:std::sqrt(x*x+y*y+z*z);
  const bool close_by=r.full_rate||d<50;
  unsigned every=r.full_rate?1:d<50?1:d<150?2:d<300?4:16;if(!close_by)every*=scale;
  if((tick+r.id)%every==0)out.push_back(u32(i)|(close_by?netcoop_world::plan_close:0));
 }return out;
}
int main(){
 auto z=xr_cpu::parallel_for(0,0,nullptr,nullptr);assert(z.blocks==0);
 // Simultaneous first use of the shared arenas, as client and server batches.
 Probe clients,servers,reference_batch;clients.output.resize(4096);servers.output.resize(4096);reference_batch.output.resize(4096);
 std::atomic<unsigned> start{0};
 auto concurrent=[&](Probe& p,unsigned limit){start.fetch_add(1);while(start.load()!=2)std::this_thread::yield();
  auto s=xr_cpu::parallel_for(p.output.size(),64,Probe::run,&p,limit);assert(s.slots<=xr_cpu::concurrency(limit));};
 std::thread client([&]{concurrent(clients,2);}),server([&]{concurrent(servers,4);});client.join();server.join();
 xr_cpu::parallel_for(reference_batch.output.size(),64,Probe::run,&reference_batch,1);
 assert(clients.output==reference_batch.output && servers.output==reference_batch.output);
 OnceProbe once;once.reset();
 xr_cpu::for_each_once(once.calls.size(),OnceProbe::run,&once,4);once.verify();
 if(xr_cpu::concurrency(4)>1){
  once.reset();xr_cpu::test_fail_after_blocks(0);
  auto failed=xr_cpu::for_each_once(once.calls.size(),OnceProbe::run,&once,4);
  xr_cpu::test_fail_after_blocks(-1);assert(failed.fallback);once.verify();
 }
 once.reset();xr_cpu::for_each_once(once.calls.size(),OnceProbe::run,&once,1);once.verify();
 std::puts("PASS non-idempotent jobs: every index exactly once, including scheduler failure after completed work");
 const auto original_round=std::fegetround();const auto original_sse=_mm_getcsr();
 assert(std::fesetround(FE_DOWNWARD)==0);_mm_setcsr(_mm_getcsr()|0x8040u);
 Environment environment{FE_DOWNWARD,_mm_getcsr()&0xffc0u};xr_cpu::parallel_for(2048,1,Environment::run,&environment,4);
 assert(environment.valid.load() && std::fegetround()==FE_DOWNWARD && (_mm_getcsr()&0xffc0u)==environment.expected_sse);
 assert(std::fesetround(original_round)==0);_mm_setcsr(original_sse);
 std::puts("PASS engine SSE controls: inherited/restored rounding, exception masks, FTZ and DAZ");
 Nested nesting;nesting.output.resize(64);xr_cpu::parallel_for(nesting.output.size(),1,Nested::run,&nesting,4);
 assert(std::all_of(nesting.output.begin(),nesting.output.end(),[](unsigned value){return value==1;}));
 Probe a,b;a.output.resize(16384);b.output.resize(16384);
 auto serial=xr_cpu::parallel_for(a.output.size(),64,Probe::run,&a,1);
 auto parallel=xr_cpu::parallel_for(b.output.size(),64,Probe::run,&b,4);
 assert(a.output==b.output && a.threads.size()==1 && parallel.slots<=xr_cpu::concurrency(4));
 if(xr_cpu::concurrency(4)>1)assert(b.threads.size()>1);
 Probe nested;nested.output.resize(8);xr_cpu::parallel_for(8,8,Probe::nested_task,&nested,4);assert(nested.nested);
 std::printf("METRIC cpu_pool threads=%zu slots=%u blocks=%zu\n",b.threads.size(),parallel.slots,parallel.blocks);
 skins<vertBoned1W>(xrSkin1W_x86,xrSkin1W_thread);skins<vertBoned2W>(xrSkin2W_x86,xrSkin2W_thread);
 skins<vertBoned3W>(xrSkin3W_x86,xrSkin3W_thread);skins<vertBoned4W>(xrSkin4W_x86,xrSkin4W_thread);
 using namespace netcoop_world;
 ReplicationPlan plan;assert(!plan.select(0).valid);
 assert(plan.prepare(nullptr,0,nullptr,0,0,1));assert(!plan.select(0).valid);
 assert(!plan.prepare(nullptr,1,nullptr,0,0,1));assert(!plan.prepare(nullptr,65537,nullptr,0,0,1));
 std::mt19937 random(42);std::uniform_real_distribution<float> position(-1000,1000);
 std::vector<PlanRecord> rows;for(unsigned i=0;i<8192;++i)rows.push_back({std::uint16_t(i),std::uint16_t(i%13==0?7:65535),i%7==0,position(random),position(random),position(random)});
 rows[1]={1,65535,false,50,0,0};rows[2]={2,65535,false,150,0,0};rows[3]={3,65535,false,300,0,0};
 rows[4]={4,65535,false,299.99997f,0,0};rows[5]={5,65535,true,90000,0,0};
 std::vector<PlanObserver> eyes;for(unsigned i=0;i<64;++i)eyes.push_back({i,std::uint16_t(i),float(i)*2,0,0});
 for(unsigned scale:{1u,2u,4u})for(u32 tick:{0u,1u,15u,16u,123u,0xffffffffu}){
  assert(plan.prepare(rows.data(),rows.size(),eyes.data(),eyes.size(),tick,scale));
  for(std::size_t i=0;i<eyes.size();++i){auto out=plan.select(i);auto expected=reference(rows,eyes[i],tick,scale);
   assert(out.valid && out.count==expected.size() && std::equal(expected.begin(),expected.end(),out.entries));}
 }
 auto bad=eyes;bad[0].x=std::numeric_limits<float>::quiet_NaN();assert(!plan.prepare(rows.data(),rows.size(),bad.data(),bad.size(),1,1));assert(!plan.select(0).valid);
 assert(!plan.prepare(rows.data(),rows.size(),eyes.data(),513,0,1));assert(!plan.prepare(rows.data(),rows.size(),eyes.data(),eyes.size(),0,0));
 // Bounded32MiB output, no multiplication overflow or stale successful frame.
 assert(!plan.prepare(rows.data(),65536,eyes.data(),512,0,1));
 std::vector<double> timings[2];
 for(unsigned mode=0;mode<2;++mode)for(unsigned iteration=0;iteration<32;++iteration){
  const auto begin=std::chrono::steady_clock::now();
  assert(plan.prepare(rows.data(),rows.size(),eyes.data(),eyes.size(),iteration,1,mode?4:1));
  timings[mode].push_back(std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-begin).count());
 }
 for(unsigned mode=0;mode<2;++mode){auto& t=timings[mode];std::sort(t.begin(),t.end());std::printf("METRIC replication observers=64 records=8192 limit=%u p50_us=%.3f p95_us=%.3f\n",mode?4:1,t[16],t[30]);}
 puts("PASS actual CPU pool: simultaneous first-use batches, inherited/restored FP environment, bounded slots, multiple OS threads, synchronous/nested fences; actual1-4W kernels exact output/canaries/immutable inputs; replication cadence/private ownership/order/bounds/failure reset match serial");
}
'''
with TemporaryDirectory(prefix='lz-cpu-jobs-') as directory:
    folder=Path(directory);cpp=folder/'cpu.cpp';exe=folder/'cpu.exe';cpp.write_text(source,encoding='utf-8')
    shutil.copy2(root/'sdk/binaries/tbb.dll',folder/'tbb.dll')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/O2','/W4','/WX','/D_CRT_SECURE_NO_WARNINGS','/DLZ_CPU_JOB_TESTS',
        '/external:I'+str(root/'src/3rd party'),'/external:W0',
        '/I'+str(root/'src/xrCore'),'/I'+str(root/'src/xrGame'),str(cpp),str(root/'src/xrCore/xr_cpu_jobs.cpp'),
        str(root/'src/xrGame/netcoop_replication_plan.cpp'),'/Fe:'+str(exe),'/link',str(root/'sdk/libraries/x64/tbb.lib')],cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=90)
