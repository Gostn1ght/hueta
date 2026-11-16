"""CI-only actual particle action bodies, noise and bounded mutable CPU jobs."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os, re, shutil, subprocess

if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native particle checks run only on Windows GitHub Actions')
root = Path(__file__).resolve().parents[1]
folder_src = root / 'src/xrParticles'
actions = (folder_src / 'particle_actions_collection.cpp').read_text(encoding='utf-8-sig')
reference = (root / 'scripts/fixtures/particle-actions-serial.cpp').read_text(encoding='utf-8-sig')
header = (folder_src / 'particle_actions_collection.h').read_text(encoding='utf-8-sig')
psystem = (folder_src / 'psystem.h').read_text(encoding='utf-8-sig')

def braced(text, start):
    opening = text.index('{', start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == '{': depth += 1
        if text[index] == '}':
            depth -= 1
            if depth == 0: return text[start:index+1]
    raise AssertionError('Unclosed source block')

names = re.findall(r'void (PA\w+)::Execute', reference)
assert len(names) == 16
classes = []
bodies = []
for name in names:
    declaration = braced(header, header.index('struct PARTICLES_API ' + name + ' :'))
    declaration = declaration.replace(' : public ParticleAction', '')
    declaration = declaration.replace('_METHODS;', 'void Execute(ParticleEffect*,const float,float&);')
    classes.append(declaration + ';')
    bodies.append(braced(actions, actions.index('void ' + name + '::Execute(')))
# Keep the exact engine pVector operators and Particle fields. Core vector/color
# and the owning effect are boundary doubles; the full engine build checks ABI.
particle_types = psystem[psystem.index('class pVector'):psystem.index('typedef void (* OnBirthParticleCB')]
noise = (folder_src / 'noise.cpp').read_text(encoding='utf-8-sig')
noise = noise[noise.index('#include <xmmintrin.h>'):]
simd = actions[actions.index('__forceinline __m128 _mm_load_fvector'):actions.index('struct TES_PARAMS')]
preamble = r'''
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <set>
#include <mutex>
#include <thread>
#include <vector>
#include <xmmintrin.h>
using u32=unsigned;using u16=unsigned short;
#define IC inline
#define PARTICLES_API
#define P_MAXFLOAT 1.0e16f
#define ONEOVERSQRT2PI (1.f/2.506628274631000502415765284811045253006f)
#define STEP_DEFAULT 0.033F
#define EPS .000010f
#define _sqrt std::sqrt
#define _sqr(x) ((x)*(x))
#define _abs std::abs
#define _sin std::sin
#define _cos std::cos
struct Flags16{u16 value;};
struct Fvector {
 float x,y,z;
 float operator[](unsigned i)const{return (&x)[i];}
 float& operator[](unsigned i){return (&x)[i];}
 void set(float a,float b,float c){x=a;y=b;z=c;}
 void mad(const Fvector& a,const Fvector& b,float t){x=a.x+b.x*t;y=a.y+b.y*t;z=a.z+b.z*t;}
};
struct Fcolor {
 float r,g,b,a;
 void set(float rr,float gg,float bb,float aa){r=rr;g=gg;b=bb;a=aa;}
 void set(u32 v){float f=1.f/255.f;r=f*((v>>16)&255);g=f*((v>>8)&255);b=f*(v&255);a=f*((v>>24)&255);}
 u32 get()const{auto q=[](float x){return unsigned(std::clamp(int(std::floor(x*255.f)),0,255));};return (q(a)<<24)|(q(r)<<16)|(q(g)<<8)|q(b);}
 void lerp(const Fcolor& x,const Fcolor& y,float t){r=x.r*(1-t)+y.r*t;g=x.g*(1-t)+y.g*t;b=x.b*(1-t)+y.b*t;a=x.a*(1-t)+y.a*t;}
};
struct CoreDouble{const char* Params="";} Core;
#include "particle_cpu.h"
float ps_particle_update_coeff=1.f;
static int noise_start=1;
'''
types = 'namespace PAPI {\n' + particle_types + '\nstruct ParticleEffect{u32 p_count;Particle* particles;};\n}\nusing namespace PAPI;\n'
source = preamble + types + noise + simd
source += '\nnamespace serial_ref {\n' + '\n'.join(classes) + '\n' + reference + '\n}\n'
source += '\nnamespace PAPI {\n' + '\n'.join(classes) + '\n' + '\n'.join(bodies) + '\n}\n'
source += r'''
std::vector<Particle> initial(unsigned n){
 std::vector<Particle> result(n+2);std::memset(result.data(),0,result.size()*sizeof(Particle));
 for(unsigned i=0;i<result.size();++i){auto& p=result[i];float f=float(i%97)*.01f;
  p.pos={1+f,2-f,3+f};p.posB={2+f,3+f,4-f};p.vel={.1f+f,.2f-f,.3f+f};p.size={1,2,3};
  p.rot.x=(i%2 ? -1.f:1.f)*f;p.age=f;p.colorR=.1f;p.colorG=.3f;p.colorB=.7f;p.colorA=.8f;
 }
 return result;
}
template<class Old,class Current,class Setup>
void check(Setup setup){
 for(unsigned n:{0u,1u,511u,512u,1023u,1024u,4095u,4096u,16383u,16384u,32769u}){
  auto baseline=initial(n),serial=baseline,parallel=baseline;
  Old old{};Current single{},multi{};setup(old);setup(single);setup(multi);
  ParticleEffect a{n,baseline.data()+1},b{n,serial.data()+1},c{n,parallel.data()+1};
  float ta=2,tb=2,tc=2;
  for(unsigned tick=0;tick<4;++tick){
   old.Execute(&a,.033f,ta);
   Core.Params="-cpu_serial";single.Execute(&b,.033f,tb);
   Core.Params="";xr_cpu::test_fail_after_blocks(tick==1?0:-1);multi.Execute(&c,.033f,tc);
   xr_cpu::test_fail_after_blocks(-1);
   assert(ta==tb && ta==tc && a.p_count==n && b.p_count==n && c.p_count==n);
   assert(!std::memcmp(baseline.data(),serial.data(),baseline.size()*sizeof(Particle)));
   assert(!std::memcmp(baseline.data(),parallel.data(),baseline.size()*sizeof(Particle)));
  }
 }
}
int main(){
 noise3Init();noise_start=0;
#define CHECK(Name,...) check<serial_ref::Name,PAPI::Name>([&](auto& a){__VA_ARGS__;})
 CHECK(PACopyVertexB,a.copy_pos=1);
 CHECK(PACopyVertexB,a.copy_pos=0);
 CHECK(PADamping,a.damping={.7f,.8f,.9f};a.vlowSqr=.01f;a.vhighSqr=1.f);
 CHECK(PAExplosion,a.center={0,0,0};a.velocity=2;a.magnitude=.01f;a.stdev=1;a.age=.1f;a.epsilon=.01f);
 CHECK(PAGravity,a.direction={0,-9,0});
 for(float radius:{1.f,100.f,1.e10f}){
  CHECK(PAScatter,a.center={0,0,0};a.magnitude=.1f;a.epsilon=.01f;a.max_radius=radius);
  CHECK(PAOrbitLine,a.p={0,0,0};a.axis={0,1,0};a.magnitude=.1f;a.epsilon=.01f;a.max_radius=radius);
  CHECK(PAOrbitPoint,a.center={0,0,0};a.magnitude=.1f;a.epsilon=.01f;a.max_radius=radius);
  CHECK(PAVortex,a.center={0,0,0};a.axis={0,1,0};a.magnitude=.1f;a.epsilon=.01f;a.max_radius=radius);
 }
 CHECK(PAMove,(void)a);
 CHECK(PARestore,a.time_left=1);
 CHECK(PARestore,a.time_left=0);
 CHECK(PASpeedLimit,a.min_speed=.2f;a.max_speed=1.1f);
 CHECK(PATargetColor,a.color={.8f,.4f,.2f};a.alpha=1;a.scale=.1f;a.timeFrom=.1f;a.timeTo=.3f);
 CHECK(PATargetSize,a.size={.8f,.4f,.2f};a.scale={.1f,.2f,.3f});
 CHECK(PATargetRotate,a.rot={.8f,0,0};a.scale=.1f);
 CHECK(PATargetVelocity,a.velocity={.8f,.4f,.2f};a.scale=.1f);
 CHECK(PATurbulence,a.frequency=.5f;a.octaves=3;a.magnitude=.001f;a.epsilon=.01f;a.offset={1,2,3};a.age=.1f);
 // Explicitly prove worker execution and exact-once chunks through this helper.
 std::vector<unsigned> visited(32769);std::set<std::thread::id> threads;std::mutex lock;
 auto stats=particle_ranges(unsigned(visited.size()),1024,[&](unsigned first,unsigned last)noexcept{
  {std::lock_guard<std::mutex> guard(lock);threads.insert(std::this_thread::get_id());}
  for(unsigned i=first;i<last;++i){++visited[i];volatile unsigned spin=i;for(unsigned k=0;k<4096;++k)spin=spin*1664525+1013904223;}
 });
 assert(stats.slots>1 && threads.size()>1 && std::all_of(visited.begin(),visited.end(),[](unsigned n){return n==1;}));
 auto particles=initial(32768);ParticleEffect effect{32768,particles.data()};
 for(const char* mode:{"-cpu_serial",""}){
  Core.Params=mode;std::vector<double> times;
  for(unsigned tick=0;tick<61;++tick){PATurbulence action{};action.frequency=.5f;action.octaves=3;action.magnitude=.001f;action.epsilon=.01f;action.offset={1,2,3};
   float max=1;auto start=std::chrono::steady_clock::now();action.Execute(&effect,.033f,max);
   times.push_back(std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count());}
  std::sort(times.begin(),times.end());std::printf("METRIC particle turbulence count=32768 mode=%s p50_us=%.3f p95_us=%.3f\n",*mode?"serial":"parallel",times[30],times[57]);
 }
 std::printf("PASS 16 actual particle actions versus frozen serial math, threshold/chunk boundaries, canaries, unchanged counts, partial scheduler failure, slots=%u threads=%zu\n",stats.slots,threads.size());
}
'''
with TemporaryDirectory(prefix='lz-particle-cpu-') as directory:
    work = Path(directory)
    cpp = work / 'particles.cpp'
    cpp.write_text(source,encoding='utf-8')
    shutil.copy2(root/'sdk/binaries/tbb.dll',work/'tbb.dll')
    exe = work/'particles.exe'
    subprocess.run(['cl','/nologo','/O2','/MD','/EHsc','/std:c++17','/W3','/DLZ_CPU_JOB_TESTS',
        '/D_CRT_SECURE_NO_WARNINGS','/I'+str(folder_src),'/I'+str(root/'src/3rd party'),
        str(cpp),str(root/'src/xrCore/xr_cpu_jobs.cpp'),'/Fe:'+str(exe),'/link',str(root/'sdk/libraries/x64/tbb.lib')],cwd=work,check=True)
    subprocess.run([str(exe)],cwd=work,check=True,timeout=180)
