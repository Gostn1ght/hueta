"""Compare actual indexed candidates + native cadence against a full scan in CI."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import hashlib
import subprocess

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks must run in GitHub Actions")

root = Path(__file__).resolve().parents[1]
game = root / "src/xrGame"
server = (game / "xrServer.cpp").read_text(encoding="utf-8")
start = server.index("\t\t\t\tconst float d =")
end = server.index("\t\t\t\tif ((server->m_aoi_tick + c.id) % every)", start)
cadence = server[start:end].replace("close_by =", "const bool close_by =", 1)
reference_path = root / "scripts/fixtures/full-rate-cadence/cadence.cpp"
reference = reference_path.read_text(encoding="utf-8")
assert hashlib.sha256(reference.encode("utf-8")).hexdigest() == "cbef7e47e7982084081bb30a8e6eb39a0a6db763cf979febf3af642fdee67537"
source = r'''
#include "netcoop_replication_index.h"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <vector>
using u16=std::uint16_t;using u32=std::uint32_t;
using namespace netcoop_world;
std::uint64_t distance_calls=0;
struct Fvector {
 float x,y,z;
 float distance_to(const Fvector& p)const{++distance_calls;return std::sqrt((x-p.x)*(x-p.x)+(y-p.y)*(y-p.y)+(z-p.z)*(z-p.z));}
};
struct Chunk {u16 id;bool full_rate;Fvector position;};
bool eligible(const ReplicationRecord& record,u16 owner,const Fvector& eye,u32 tick,u32 far_scale=1) {
 struct Owner {u16 ID;} object{owner};
 struct Client {Owner* owner;} client{&object};auto CL=&client;
 struct Server {u32 m_aoi_tick;} instance{tick};auto server=&instance;
 Chunk c{record.id,record.full_rate,{record.x,record.y,record.z}};
''' + cadence + r'''
 if(record.full_rate){assert(every==1&&close_by);}
 return (server->m_aoi_tick+c.id)%every==0;
}
std::size_t compare(ReplicationIndex& index,const std::vector<ReplicationRecord>& records,u16 owner,Fvector eye,u32 tick,u32 far_scale=1) {
 const auto selected=index.select(owner,eye.x,eye.y,eye.z,tick);assert(selected.valid);
 std::vector<u32> actual,expected;
 for(std::size_t i=0;i<selected.count;++i) {
  const auto offset=selected.indices[i];assert(offset<records.size());
  if(i)assert(selected.indices[i-1]<offset);
  if(eligible(records[offset],owner,eye,tick,far_scale))actual.push_back(offset);
 }
 for(std::size_t i=0;i<records.size();++i)
  if(legacy_eligible(records[i],owner,eye,tick,far_scale))expected.push_back(u32(i));
 assert(actual==expected);return selected.count;
}
int main() {
 ReplicationIndex index;assert(!index.select(0,0,0,0,1).valid);
 assert(index.prepare(nullptr,0));assert(index.select(0,0,0,0,1).valid);
 assert(!index.prepare(nullptr,1));assert(!index.select(0,0,0,0,1).valid);
 assert(!index.prepare(nullptr,65537));
 std::vector<ReplicationRecord> records{
  {0,true,10000,0,0},{1,false,49.999f,0,0},{2,false,50,0,0},
  {3,false,149.999f,0,0},{4,false,150,0,0},{5,false,299.99997f,0,0},
  {6,false,300,0,0},{7,false,300.00003f,0,0},{8,false,0,299.99997f,0},
  {9,true,-10000,0,0},{65535,false,9999,0,0},{10,false,-300,0,0}
 };
 assert(index.prepare(records.data(),records.size()));
 distance_calls=0;assert(eligible(records[0],0,{100,0,0},1));assert(distance_calls==0);
 assert(legacy_eligible(records[0],1,{100,0,0},1));assert(distance_calls==1);
 distance_calls=0;(void)eligible(records[1],0,{100,0,0},1);assert(distance_calls==1);
 for(u32 tick=0;tick<64;++tick)compare(index,records,0,{0,0,0},tick);
 // Characters at every distance, including beyond the spatial sphere, must
 // remain candidates every tick under all overload scales. No byte budget deferral.
 auto protected_records=records;for(auto& record:protected_records)record.full_rate=true;
 assert(index.prepare(protected_records.data(),protected_records.size()));
 for(u32 overload:{1u,2u,4u})for(u32 tick=0;tick<64;++tick){
  compare(index,protected_records,0,{0,0,0},tick,overload);
  auto selected=index.select(0,0,0,0,tick);assert(selected.count==protected_records.size() && selected.spatial_candidates==0);
 }
 assert(index.prepare(records.data(),records.size()));
 for(u32 tick:{0xffffffffu,0xfffffffeu,0xfffffff0u})compare(index,records,65535,{0,0,0},tick);
 assert(!index.select(0,std::numeric_limits<float>::quiet_NaN(),0,0,1).valid);
 auto bad=records;bad[1].id=bad[0].id;
 assert(!index.prepare(bad.data(),bad.size()) && !index.select(0,0,0,0,1).valid);
 bad=records;bad[2].x=std::numeric_limits<float>::infinity();
 assert(!index.prepare(bad.data(),bad.size()) && !index.select(0,0,0,0,1).valid);
 assert(index.prepare(records.data(),records.size()));
 // Remove/reorder/reuse runtime handles: offsets always belong to this frame.
 records.erase(records.begin()+1);std::reverse(records.begin(),records.end());
 records.push_back({1,false,0,0,0});records[1].x=-450;
 assert(index.prepare(records.data(),records.size()));
 for(u32 tick=0;tick<32;++tick)compare(index,records,65535,{-450,0,0},tick);
 std::mt19937 rng(7251);std::uniform_real_distribution<float> coord(-5000,5000);
 records.clear();
 for(u32 i=0;i<12000;++i)records.push_back({u16(i),i<512,coord(rng),coord(rng)/30,coord(rng)});
 std::uint64_t candidates=0,full_scan=0;
 for(u32 frame=0;frame<32;++frame) {
  std::shuffle(records.begin(),records.end(),rng);
  for(std::size_t i=0;i<records.size();i+=17) {records[i].x=coord(rng);records[i].z=coord(rng);}
  assert(index.prepare(records.data(),records.size()));
  for(u16 player=0;player<64;++player) {
   // Includes distant observers, negative cells, height and high-speed jumps.
   candidates+=compare(index,records,player,{coord(rng),coord(rng)/30,coord(rng)},frame);
   full_scan+=records.size();
  }
 }
 assert(candidates<full_scan/4);
 std::cout<<"PASS: real grid candidates + native world cadence match full scan; characters/equipment always full rate, including overload, order, owner, float boundaries, tick overflow, moves/removals/reuse and fallback; pinned pre-optimization predicate matches; protected distance calls and spatial candidates zero\n"
          <<"Synthetic candidate count "<<candidates<<" versus "<<full_scan<<" full checks; not a gameplay capacity/load test\n";
}
'''
legacy_begin = source.index("bool eligible(")
legacy_end = source.index("std::size_t compare(", legacy_begin)
legacy = source[legacy_begin:legacy_end].replace("bool eligible(", "bool legacy_eligible(", 1)
assert cadence in legacy
legacy = legacy.replace(cadence, reference, 1)
source = source[:legacy_end] + legacy + source[legacy_end:]

with TemporaryDirectory(prefix="replication-index-") as tmp:
    cpp = Path(tmp) / "check.cpp"
    exe = Path(tmp) / ("check.exe" if os.name == "nt" else "check")
    cpp.write_text(source, encoding="utf-8")
    implementation = str(game / "netcoop_replication_index.cpp")
    if os.name == "nt":
        command = ["cl", "/nologo", "/std:c++17", "/EHsc", "/W4", "/WX", "/O2", "/I" + str(game),
                   str(cpp), implementation, "/Fe:" + str(exe), "/Fo:" + tmp + os.sep]
    else:
        command = ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2", "-I", str(game),
                   str(cpp), implementation, "-o", str(exe)]
    subprocess.run(command, check=True, cwd=tmp)
    subprocess.run([str(exe)], check=True)
