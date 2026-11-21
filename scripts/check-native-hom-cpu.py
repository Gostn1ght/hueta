"""CI-only actual HOM clipping/projection and software rasterizer. No game/GPU."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os, subprocess, shutil
if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native HOM checks run only on Windows GitHub Actions')
root=Path(__file__).resolve().parents[1]
render=root/'src/Layers/xrRender'
def block(text,needle):
    start=text.index(needle);opening=text.index('{',start);depth=0
    for index in range(opening,len(text)):
        if text[index]=='{':depth+=1
        if text[index]=='}':
            depth-=1
            if depth==0:return text[start:index+1]
    raise AssertionError(needle)
clip=block((root/'src/xrCDB/Frustum.cpp').read_text(encoding='utf-8-sig'),'sPoly* CFrustum::ClipPoly(')
matrix=block((root/'src/xrCore/_matrix.h').read_text(encoding='utf-8-sig'),'IC void transform(Tvector& dest, const Tvector& v) const')
matrix=matrix.replace('Tvector','Fvector').replace('T iw','float iw')
core=(render/'occRasterizer_core.cpp').read_text(encoding='utf-8-sig');core=core[core.index('static occTri* currentTri'):]
base=(render/'occRasterizer.cpp').read_text(encoding='utf-8-sig')
functions='\n'.join(block(base,needle) for needle in ['IC void propagade_depth(', 'occRasterizer::occRasterizer()', 'occRasterizer::~occRasterizer()', 'void occRasterizer::clear()', 'void occRasterizer::propagade()'])
code=r'''
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <numeric>
#include <random>
#include <vector>
#undef assert
#define assert(x) do{if(!(x)){std::fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);ExitProcess(2);}}while(false)
#define IC inline
#define _abs std::abs
using u32=unsigned;using s32=int;using s16=short;
constexpr float EPS_S=.0000001f;
int iFloor(float x){return int(std::floor(x));}int iCeil(float x){return int(std::ceil(x));}
template<class T>void clamp(T& value,T low,T high){value=std::clamp(value,low,high);}
bool negative(float f){return f<0;}bool positive(float f){return f>=0;}
struct Fvector{
 float x=0,y=0,z=0;
 bool similar(const Fvector& b,float e)const{return std::abs(x-b.x)<e && std::abs(y-b.y)<e && std::abs(z-b.z)<e;}
 void sub(const Fvector& a,const Fvector& b){x=a.x-b.x;y=a.y-b.y;z=a.z-b.z;}
 void mad(const Fvector& a,const Fvector& b,float t){x=a.x+b.x*t;y=a.y+b.y*t;z=a.z+b.z*t;}
 float dotproduct(const Fvector& b)const{return x*b.x+y*b.y+z*b.z;}
};
struct Fplane{Fvector n;float d=0;float classify(const Fvector& p)const{return n.dotproduct(p)+d;}};
#define FRUSTUM_SAFE 48
struct sPoly{
 std::array<Fvector,FRUSTUM_SAFE> points{};u32 length=0;
 void clear(){length=0;}u32 size()const{return length;}
 void push_back(const Fvector& v){assert(length<points.size());points[length++]=v;}
 Fvector& last(){assert(length<points.size());return points[length];}void inc(){++length;}
 Fvector& operator[](u32 i){return points[i];}const Fvector& operator[](u32 i)const{return points[i];}
};
struct CFrustum{using fplane=Fplane;Fplane planes[12]{};int p_count=1;sPoly* ClipPoly(sPoly&,sPoly&)const;};
struct Fmatrix{
 float _11=20,_12=0,_13=0,_14=0,_21=0,_22=20,_23=0,_24=0,_31=0,_32=0,_33=1,_34=0,_41=32,_42=32,_43=0,_44=1;
'''+matrix+r'''
};
namespace CDB{struct TRI{u32 verts[3];};struct RESULT{u32 id;};}
struct MemoryDouble{void mem_fill32(void* p,u32 value,std::size_t size){std::fill_n(static_cast<u32*>(p),size,value);}}Memory;
#include "occRasterizer.h"
occRasterizer Raster;
'''+clip+'\n'+core+'\n'+functions+r'''
#include "hom_cpu.h"
struct State{std::vector<float> depths;std::vector<occTri*> frame;std::vector<occD> hierarchy;std::vector<u32> skips;u32 random;};
u32 rng(u32& value){value=value*1664525u+1013904223u;return 3+value%7;}
State draw(xr_hom::Input& input,std::size_t count,bool prepared,unsigned limit,unsigned tick,unsigned& slots){
 std::vector<xr_hom::Prepared> output(count);input.output=output.data();
 if(prepared){
  // Preparation may change only its output, never shared triangles or raster.
  const auto* bytes=reinterpret_cast<const unsigned char*>(input.occluders);
  std::vector<unsigned char> before(bytes,bytes+count*sizeof(occTri));
  const auto stats=xr_hom::prepare(input,count,limit);slots=std::max(slots,stats.slots);
  assert(!std::memcmp(before.data(),bytes,before.size()));
 }
 Raster.clear();u32 random=1234567u+tick;
 for(std::size_t index=0;index<count;++index){auto& tri=const_cast<occTri&>(input.occluders[input.order[index].id]);
  const u32 next=tick+rng(random);u32 pixels=0;
  if(prepared){auto& p=output[index];assert(p.count<=4);if(!p.count){tri.skip=next;continue;}
   for(unsigned j=1;j+1<p.count;++j){tri.raster[0]=p.points[0];tri.raster[1]=p.points[j];tri.raster[2]=p.points[j+1];pixels+=Raster.rasterize(&tri);}
  }else{
   if(!(tri.flags || tri.plane.classify(input.camera)>0)){tri.skip=next;continue;}
   const auto& face=input.triangles[input.order[index].id];sPoly source,destination;
   for(unsigned j=0;j<3;++j)source.push_back(input.vertices[face.verts[j]]);
   auto* p=input.frustum.ClipPoly(source,destination);if(!p){tri.skip=next;continue;}
   for(unsigned j=1;j+1<p->size();++j){input.transform.transform(tri.raster[0],(*p)[0]);input.transform.transform(tri.raster[1],(*p)[j]);input.transform.transform(tri.raster[2],(*p)[j+1]);pixels+=Raster.rasterize(&tri);}
  }
  if(!pixels)tri.skip=next;
 }
 Raster.propagade();State result;
 result.depths.assign(Raster.get_depth(),Raster.get_depth()+occ_dim*occ_dim);
 result.frame.assign(Raster.get_frame(),Raster.get_frame()+occ_dim*occ_dim);
 for(int level=0,dim=64;level<4;++level,dim/=2)result.hierarchy.insert(result.hierarchy.end(),Raster.get_depth_level(level),Raster.get_depth_level(level)+dim*dim);
 for(std::size_t i=0;i<count;++i)result.skips.push_back(input.occluders[i].skip);
 result.random=random;return result;
}
void equal(const State& a,const State& b){assert(a.random==b.random && a.frame==b.frame && a.skips==b.skips && a.hierarchy==b.hierarchy);assert(!std::memcmp(a.depths.data(),b.depths.data(),a.depths.size()*sizeof(float)));}
int main(){
 std::setvbuf(stdout,nullptr,_IONBF,0);unsigned slots=0;
 for(unsigned count:{0u,1u,127u,128u,1023u,1024u,4097u,8192u}){
  std::vector<occTri> triangles(count);std::vector<Fvector> vertices(count*3);std::vector<CDB::TRI> faces(count);std::vector<CDB::RESULT> order(count);
  for(unsigned i=0;i<count;++i){const float x=float(int(i%41)-20)*.08f,y=float(int(i%37)-18)*.08f;
   vertices[i*3]={x,y,i%7==0?-.1f:.2f};vertices[i*3+1]={x+.2f,y,i%7==1?-.1f:.3f};vertices[i*3+2]={x,y+.2f,i%7==2?-.1f:.4f};
   if(i%17==0)vertices[i*3+1]=vertices[i*3];
   if(i%19==0)vertices[i*3].z=0.f;
   faces[i]={{i*3,i*3+1,i*3+2}};order[i]={i};triangles[i].flags=i%3==0;triangles[i].plane.n={0,0,1};triangles[i].plane.d=i%5==0?-3.f:0.f;
   triangles[i].adjacent[0]=i?&triangles[i-1]:reinterpret_cast<occTri*>(-1);triangles[i].adjacent[1]=triangles[i].adjacent[2]=reinterpret_cast<occTri*>(-1);
  }
  std::mt19937 shuffle(111);std::shuffle(order.begin(),order.end(),shuffle);const auto original=triangles;
  xr_hom::Input input{order.data(),faces.data(),vertices.data(),triangles.data(),{0,0,2},{},{},nullptr};input.frustum.planes[0].n={0,0,-1};
  for(bool perspective:{false,true}){input.transform._14=perspective?.03f:0.f;input.transform._24=perspective?-.02f:0.f;input.transform._34=perspective?1.f:0.f;
  for(unsigned tick=0;tick<8;++tick){triangles=original;input.occluders=triangles.data();const auto baseline=draw(input,count,false,1,tick,slots);
   for(unsigned limit:{1u,4u}){triangles=original;input.occluders=triangles.data();if(limit==4 && count>=1024)xr_cpu::test_fail_after_blocks(0);
    const auto result=draw(input,count,true,limit,tick,slots);xr_cpu::test_fail_after_blocks(-1);equal(baseline,result);}
  }
  }
  if(count==8192){std::vector<xr_hom::Prepared> output(count);input.output=output.data();
   for(unsigned limit:{1u,4u}){std::vector<double> times;for(unsigned i=0;i<61;++i){auto start=std::chrono::steady_clock::now();xr_hom::prepare(input,count,limit);times.push_back(std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count());}
    std::sort(times.begin(),times.end());std::printf("METRIC hom prepare count=8192 limit=%u p50_us=%.3f p95_us=%.3f\n",limit,times[30],times[57]);}
  }
 }
 assert(slots>1);std::printf("PASS actual ClipPoly/matrix/rasterizer: exact depth/frame/mip/skip/RNG equality, zero/degenerate/near-plane/fan/boundary cases, scheduler recovery, immutable inputs, slots=%u\n",slots);
}
'''
with TemporaryDirectory(prefix='lz-hom-cpu-') as temporary:
    folder=Path(temporary);cpp=folder/'hom.cpp';cpp.write_text(code,encoding='utf-8')
    shutil.copy2(root/'sdk/binaries/tbb.dll',folder/'tbb.dll');exe=folder/'hom.exe'
    subprocess.run(['cl','/nologo','/O2','/MD','/EHsc','/std:c++17','/W3','/DLZ_CPU_JOB_TESTS','/I'+str(render),'/I'+str(root/'src/3rd party'),str(cpp),str(root/'src/xrCore/xr_cpu_jobs.cpp'),'/Fe:'+str(exe),'/link',str(root/'sdk/libraries/x64/tbb.lib')],cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=180)
