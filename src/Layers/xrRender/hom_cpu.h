#pragma once
#include "../../xrCore/xr_cpu_jobs.h"

namespace xr_hom
{
// A triangle clipped against HOM's single near plane has at most4 vertices.
// Shared raster buffers and occTri::raster/skip are never touched by workers.
struct Prepared {unsigned count=0;Fvector points[4];};
struct Input
{
    const CDB::RESULT* order;
    const CDB::TRI* triangles;
    const Fvector* vertices;
    const occTri* occluders;
    Fvector camera;
    Fmatrix transform;
    CFrustum frustum;
    Prepared* output;
};
inline void prepare_range(void* opaque,std::size_t begin,std::size_t end) noexcept
{
    auto& work=*static_cast<Input*>(opaque);
    for(auto index=begin;index<end;++index)
    {
        auto& result=work.output[index];result.count=0;
        const auto id=work.order[index].id;
        const auto& occluder=work.occluders[id];
        if(!(occluder.flags || occluder.plane.classify(work.camera)>0))continue;
        const auto& triangle=work.triangles[id];
        sPoly source,destination;source.clear();destination.clear();
        for(unsigned vertex=0;vertex<3;++vertex)source.push_back(work.vertices[triangle.verts[vertex]]);
        const auto* polygon=work.frustum.ClipPoly(source,destination);
        if(!polygon)continue;
        if(polygon->size()>4){result.count=5;continue;} // reject before owner mutation
        result.count=unsigned(polygon->size());
        for(unsigned vertex=0;vertex<result.count;++vertex)
            work.transform.transform(result.points[vertex],(*polygon)[vertex]);
    }
}
inline xr_cpu::BatchStats prepare(Input& input,std::size_t count,unsigned limit=0) noexcept
{
    return xr_cpu::parallel_for(count,128,prepare_range,&input,limit);
}
}
