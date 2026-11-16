#include "stdafx.h"
#pragma hdrstop
#include "../xrCore/xr_cpu_jobs.h"
#include <algorithm>

extern xrSkin1W* skin1W_func;
extern xrSkin2W* skin2W_func;
extern xrSkin3W* skin3W_func;
extern xrSkin4W* skin4W_func;

namespace
{
template<class Vertex> struct SkinWork
{
    using Kernel=void (__stdcall*)(vertRender*,Vertex*,u32,CBoneInstance*);
    vertRender* output;Vertex* input;CBoneInstance* bones;Kernel kernel;std::size_t count;
    static void run(void* opaque,std::size_t begin,std::size_t end) noexcept
    {
        auto& w=*static_cast<SkinWork*>(opaque);
        begin*=512;end=std::min(w.count,end*512);
        w.kernel(w.output+begin,w.input+begin,u32(end-begin),w.bones);
    }
};
template<class Vertex,class Kernel>
void skin(vertRender* output,Vertex* input,u32 count,CBoneInstance* bones,Kernel kernel)
{
    if(!count)return;
    if(count<1024){kernel(output,input,count,bones);return;}
    SkinWork<Vertex> work{output,input,bones,kernel,count};
    // The caller locks the vertex buffer and freezes bone transforms. This
    // synchronous fence finishes all CPU writes before its unlock/draw.
    // Partition block numbers so WC vertex-buffer boundaries remain aligned.
    xr_cpu::parallel_for((std::size_t(count)+511)/512,1,SkinWork<Vertex>::run,&work);
}
}
void __stdcall xrSkin1W_thread(vertRender* d,vertBoned1W* s,u32 n,CBoneInstance* b){skin(d,s,n,b,skin1W_func);}
void __stdcall xrSkin2W_thread(vertRender* d,vertBoned2W* s,u32 n,CBoneInstance* b){skin(d,s,n,b,skin2W_func);}
void __stdcall xrSkin3W_thread(vertRender* d,vertBoned3W* s,u32 n,CBoneInstance* b){skin(d,s,n,b,skin3W_func);}
void __stdcall xrSkin4W_thread(vertRender* d,vertBoned4W* s,u32 n,CBoneInstance* b){skin(d,s,n,b,skin4W_func);}
