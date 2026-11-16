"""Actual vendored ODE + island coordinator, CI only. No game/window/GPU."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,shutil,subprocess,xml.etree.ElementTree as ET

if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native physics checks run only on Windows GitHub Actions')
root=Path(__file__).resolve().parents[1]
project=root/'src/3rd party/ode/contrib/msvc7/ode_default/default.vcxproj'
sources=[(project.parent/item.attrib['Include']).resolve() for item in ET.parse(project).iter()
         if item.tag.endswith('ClCompile') and item.get('Include')]
assert len(sources)>25 and all(p.is_file() for p in sources)
code=r'''
#define NOMINMAX
#include <windows.h>
#include <ode/ode.h>
#include "objects.h"
#include "PHIslandBatch.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <exception>
#include <cstdlib>
#include <cstdarg>
#include <thread>
#include <vector>
#undef assert
#define assert(condition) do { if(!(condition)){std::fprintf(stderr,"FAIL %s:%d: %s\n",__FILE__,__LINE__,#condition);std::fflush(stderr);ExitProcess(2);} } while(false)
std::atomic<DWORD> owner_thread{0};
std::atomic<bool> geometry_on_worker{false};
struct dxGeom;
void lz_ode_test_geom_moved(dxGeom*) {
 if(GetCurrentThreadId()!=owner_thread.load())geometry_on_worker=true;
}
void no_contact(void*,dGeomID,dGeomID){}
struct Scene {
 dSpaceID space=dSimpleSpaceCreate(nullptr);
 dGeomID floor=dCreatePlane(space,0,1,0,0);
 std::vector<dJointID> contacts;
 std::vector<dWorldID> worlds;
 std::vector<dBodyID> bodies;
 std::vector<dGeomID> geoms;
 std::vector<xr_physics::IslandJob> jobs;
 std::vector<dJointFeedback> feedback;
 unsigned contacts_used=0;
 Scene(unsigned count,bool extremes=false) {
  feedback.resize(count*128);
  for(unsigned island=0;island<count;++island){
   auto world=dWorldCreate();worlds.push_back(world);
   dWorldSetGravity(world,0,-9.81f,0);dWorldSetCFM(world,1.e-5f);
   dWorldSetQuickStepNumIterations(world,24);
   bool exact=island%2==0;
   unsigned n=exact?4:12;
   if(extremes && island==0)n=65;
   jobs.push_back({world,exact,0});
   dBodyID previous=nullptr;
   for(unsigned index=0;index<n;++index){
    auto body=dBodyCreate(world);bodies.push_back(body);
    dMass mass;dMassSetBoxTotal(&mass,1,.4f,.4f,.4f);dBodySetMass(body,&mass);
    dBodySetPosition(body,dReal(island)*20,dReal(index)*.45f+.21f,0);
    dBodySetLinearVel(body,.01f*float(index+1),0,.02f);
    auto geom=dCreateBox(space,.4f,.4f,.4f);dGeomSetBody(geom,body);geoms.push_back(geom);
    if(previous){auto joint=dJointCreateBall(world,nullptr);dJointAttach(joint,previous,body);
     dJointSetBallAnchor(joint,dReal(island)*20,dReal(index)*.45f,0);}
    previous=body;
   }
  }
 }
 ~Scene(){clear_contacts();for(auto world:worlds)dWorldDestroy(world);dSpaceDestroy(space);}
 void clear_contacts(){for(auto joint:contacts)dJointDestroy(joint);contacts.clear();}
 void prepare(unsigned tick){
  // This engine's group empty deliberately does NOT unlink world roots:
  // CPHWorld reinitializes island lists before emptying its contact group.
  // Our persistent standalone worlds instead destroy ungrouped contacts so
  // subsequent frames do not traverse freed joints from a stale root list.
  clear_contacts();contacts_used=0;std::fill(feedback.begin(),feedback.end(),dJointFeedback{});
  // Clean shared parent-space lists, so stale/worker geometry notifications
  // cannot be hidden by every geom already being dirty.
  dSpaceCollide(space,nullptr,no_contact);
  for(auto geom:geoms){
   dContact contact[4]{};
   const int count=dCollide(geom,floor,4,&contact[0].geom,sizeof(dContact));
   for(int i=0;i<count;++i){
    contact[i].surface.mode=dContactBounce|dContactSoftCFM;
    contact[i].surface.mu=.6f;contact[i].surface.bounce=.05f;contact[i].surface.soft_cfm=1.e-5f;
    auto body=dGeomGetBody(geom);auto joint=dJointCreateContact(body->world,nullptr,&contact[i]);contacts.push_back(joint);
    dJointAttach(joint,body,nullptr);assert(contacts_used<feedback.size());
    dJointSetFeedback(joint,&feedback[contacts_used++]);
   }
  }
  for(unsigned i=0;i<jobs.size();++i)jobs[i].seed=tick^((i+1u)*0x9e3779b9u);
 }
 void direct(){
  for(auto& job:jobs){if(job.exact)dWorldStep(job.world,.01f);
   else dWorldQuickStepSeeded(job.world,.01f,job.seed);}
 }
 void check_bounds(){
  for(auto geom:geoms){dReal bounds[6];dGeomGetAABB(geom,bounds);
   const auto p=dBodyGetPosition(dGeomGetBody(geom));
   for(unsigned axis=0;axis<3;++axis){assert(std::isfinite(p[axis]));
    assert(std::abs((bounds[axis*2]+bounds[axis*2+1])*.5f-p[axis])<.001f*std::max(1.f,std::abs(p[axis])));}
  }
 }
};
void compare(const Scene& a,const Scene& b){
 assert(a.bodies.size()==b.bodies.size() && a.contacts_used==b.contacts_used);
 for(std::size_t i=0;i<a.bodies.size();++i){
  const auto x=a.bodies[i],y=b.bodies[i];
  assert(!std::memcmp(dBodyGetPosition(x),dBodyGetPosition(y),3*sizeof(dReal)));
  assert(!std::memcmp(dBodyGetQuaternion(x),dBodyGetQuaternion(y),4*sizeof(dReal)));
  assert(!std::memcmp(dBodyGetLinearVel(x),dBodyGetLinearVel(y),3*sizeof(dReal)));
  assert(!std::memcmp(dBodyGetAngularVel(x),dBodyGetAngularVel(y),3*sizeof(dReal)));
 }
 for(unsigned i=0;i<a.contacts_used;++i)
  assert(!std::memcmp(&a.feedback[i],&b.feedback[i],sizeof(dJointFeedback)));
}
void ode_error(int number,const char* format,va_list arguments){
 std::fprintf(stderr,"ODE failure %d: ",number);std::vfprintf(stderr,format,arguments);std::fflush(stderr);ExitProcess(5);
}
DWORD WINAPI small_stack(void*){
 owner_thread=GetCurrentThreadId();
 Scene scene(8);
 // Worst six-row joints at the worker exact bound, not only three-row balls.
 for(unsigned i=0;i<scene.worlds.size();++i){
  const auto world=scene.worlds[i];
  const bool exact=i%2==0;scene.jobs[i].exact=exact;
  // All rows at the24/128 joint boundary have six constraints.
  while(world->firstjoint)dJointDestroy(world->firstjoint);
  unsigned add=exact?24:128;
  auto body=scene.bodies[exact ? (i/2)*16:(i/2)*16+4];
  for(unsigned j=0;j<add;++j){auto joint=dJointCreateFixed(world,nullptr);dJointAttach(joint,body,nullptr);dJointSetFixed(joint);}
 }
 auto s=xr_physics::step_islands(scene.jobs.data(),scene.jobs.size(),.01f,1);
 assert(s.accepted && s.eligible==8);scene.check_bounds();
 return 0;
}
int main(){
 std::setvbuf(stdout,nullptr,_IONBF,0);
 std::set_terminate([]{try{auto exception=std::current_exception();if(exception)std::rethrow_exception(exception);}
  catch(const std::exception& error){std::fprintf(stderr,"TERMINATE %s\n",error.what());}
  catch(...){std::fprintf(stderr,"TERMINATE unknown exception\n");}std::fflush(stderr);ExitProcess(6);});
 dSetErrorHandler(ode_error);dSetDebugHandler(ode_error);
 owner_thread=GetCurrentThreadId();
 assert(xr_physics::step_islands(nullptr,0,.01f).accepted);
 assert(!xr_physics::step_islands(nullptr,4,.01f).accepted);
 std::puts("CHECK constructing actual ODE scenes");
 Scene baseline(32,true),serial(32,true),parallel(32,true);
 unsigned max_slots=0;
 std::vector<double> timings[2];
 for(unsigned tick=0;tick<120;++tick){
  if(tick%10==0)std::printf("CHECK frame=%u\n",tick);
  baseline.prepare(tick);serial.prepare(tick);parallel.prepare(tick);
  if(tick==0)std::puts("CHECK first direct step");
  baseline.direct();
  for(unsigned mode=0;mode<2;++mode){
   auto& scene=mode?parallel:serial;
   if(mode && tick%17==0)xr_cpu::test_fail_after_blocks(0);
   const auto begin=std::chrono::steady_clock::now();
   if(tick==0)std::printf("CHECK first batch mode=%u\n",mode);
   const auto stats=xr_physics::step_islands(scene.jobs.data(),scene.jobs.size(),.01f,mode?4:1);
   xr_cpu::test_fail_after_blocks(-1);assert(stats.accepted);
   max_slots=std::max(max_slots,stats.cpu.slots);
   timings[mode].push_back(std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-begin).count());
   scene.check_bounds();
  }
  compare(baseline,serial);compare(baseline,parallel);
  assert(dThreadSetGeomNotificationsDeferred(0)==0);
 }
 std::puts("CHECK frame equality complete");
 // Duplicate/invalid roots reject before touching any world.
 auto invalid=parallel.jobs;invalid[1]=invalid[0];
 const auto body=parallel.bodies.front();std::array<dReal,3> before;
 std::copy_n(dBodyGetPosition(body),3,before.begin());
 assert(!xr_physics::step_islands(invalid.data(),invalid.size(),.01f).accepted);
 assert(!xr_physics::step_islands(parallel.jobs.data(),65537,.01f).accepted);
 assert(!xr_physics::step_islands(parallel.jobs.data(),parallel.jobs.size(),std::numeric_limits<dReal>::quiet_NaN()).accepted);
 assert(!std::memcmp(before.data(),dBodyGetPosition(body),3*sizeof(dReal)));
 // Prove bounded worker scratch on a deliberately small reserved stack.
 std::puts("CHECK bounded stack");
 HANDLE thread=CreateThread(nullptr,512*1024,small_stack,nullptr,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);
 assert(thread && WaitForSingleObject(thread,30000)==WAIT_OBJECT_0);
 DWORD code=1;assert(GetExitCodeThread(thread,&code) && code==0);CloseHandle(thread);owner_thread=GetCurrentThreadId();
 assert(!geometry_on_worker.load());
 for(unsigned mode=0;mode<2;++mode){auto& t=timings[mode];std::sort(t.begin(),t.end());
  std::printf("METRIC physics roots=32 frames=120 limit=%u p50_us=%.3f p95_us=%.3f max_slots=%u\n",mode?4:1,t[60],t[114],max_slots);}
 std::puts("PASS actual ODE exact/quick/contacts/feedback: direct/serial/parallel bit equality, once-only partial-failure recovery, large owner fallback, shared-space AABB refresh on owner, bounded512KiB stack, invalid roots rejected");
}
'''
with TemporaryDirectory(prefix='lz-physics-islands-') as directory:
    folder=Path(directory);objects=folder/'ode';objects.mkdir()
    includes=['/I'+str(root/'src/3rd party/ode/include'),'/I'+str(root/'src/3rd party/ode/ode/src')]
    subprocess.run(['cl','/nologo','/c','/O2','/MD','/EHsc','/std:c++17','/DWIN32','/DMSVC','/DdSINGLE',
        '/DdNODEBUG','/DNDEBUG','/DLZ_ODE_TESTS','/D_CRT_SECURE_NO_WARNINGS',*includes,
        '/Fo'+str(objects)+'\\',*map(str,sources)],cwd=folder,check=True)
    library=folder/'ode-test.lib'
    subprocess.run(['lib','/nologo','/OUT:'+str(library),*map(str,objects.glob('*.obj'))],cwd=folder,check=True)
    cpp=folder/'islands.cpp';cpp.write_text(code,encoding='utf-8')
    shutil.copy2(root/'sdk/binaries/tbb.dll',folder/'tbb.dll')
    executable=folder/'islands.exe'
    subprocess.run(['cl','/nologo','/O2','/MD','/EHsc','/std:c++17','/W4','/WX','/DWIN32','/DMSVC','/DdSINGLE',
        '/DdNODEBUG','/DLZ_CPU_JOB_TESTS','/D_CRT_SECURE_NO_WARNINGS','/external:I'+str(root/'src/3rd party'),'/external:W0',
        *includes,'/I'+str(root/'src/xrPhysics'),'/I'+str(root/'src/xrCore'),str(cpp),
        str(root/'src/xrPhysics/PHIslandBatch.cpp'),str(root/'src/xrCore/xr_cpu_jobs.cpp'),
        '/Fe:'+str(executable),'/link','/STACK:8388608',str(library),str(root/'sdk/libraries/x64/tbb.lib'),'user32.lib'],
        cwd=folder,check=True)
    subprocess.run([str(executable)],cwd=folder,check=True,timeout=120)
