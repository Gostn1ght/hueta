"""CI-only real early snapshot gates: stale health/equipment never mutate replicas."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]


def method(path, signature):
    source = (root / path).read_text(encoding='utf-8-sig')
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


gate = method('src/xrGame/netcoop_net_sync.inc', 'bool snapshot_packet_stale(')
source = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
using u32=std::uint32_t;
struct NET_Packet {
 unsigned char bytes[32]{};u32 pos=0,count=8;
 void set(u32 stamp,float health){std::memcpy(bytes,&health,4);std::memcpy(bytes+4,&stamp,4);pos=0;count=8;}
 u32 r_elapsed(){return count-pos;}u32 r_tell(){return pos;}void r_seek(u32 to){pos=to;}
 float r_float(){assert(r_elapsed()>=4);float value;std::memcpy(&value,bytes+pos,4);pos+=4;return value;}
 u32 r_u32(){assert(r_elapsed()>=4);u32 value;std::memcpy(&value,bytes+pos,4);pos+=4;return value;}
};
namespace netcoop {bool pure=true;bool pure_client(){return pure;}
''' + gate + r'''
}
struct Snapshot {u32 dwTimeStamp;};
struct Replica {
 std::deque<Snapshot> NET;bool remote=true;float health=1;unsigned mutations=0;
 bool Remote(){return remote;}
 void actor(NET_Packet&);void stalker(NET_Packet&);void monster(NET_Packet&);void custom(NET_Packet&);
};
'''
paths = (
    ('actor', 'src/xrGame/Actor_Network.cpp', 'void CActor::net_Import(NET_Packet& P)', 'net_Import_Base(P);'),
    ('stalker', 'src/xrGame/ai/stalker/ai_stalker.cpp', 'void CAI_Stalker::net_Import(NET_Packet& P)', 'SetfHealth(health);'),
    ('monster', 'src/xrGame/ai/monsters/basemonster/base_monster_net.cpp', 'void CBaseMonster::net_Import(NET_Packet& P)', 'SetfHealth(health);'),
    ('custom', 'src/xrGame/CustomMonster.cpp', 'void CCustomMonster::net_Import(NET_Packet& P)', 'SetfHealth(health);'),
)
for name, path, signature, mutation in paths:
    body = method(path, signature)
    start = body.index('if (netcoop::pure_client() && Remote() && !NET.empty() &&')
    end = body.index('return;', start) + len('return;')
    assert end < body.index(mutation), f'{name}: rejection must precede every state mutation'
    source += '\nvoid Replica::' + name + '(NET_Packet& P){\n' + body[start:end] + r'''
 health=P.r_float();const u32 stamp=P.r_u32();++mutations;
 if(NET.empty()||stamp>NET.back().dwTimeStamp)NET.push_back({stamp});
}
'''
actor = method('src/xrGame/Actor_Network.cpp', 'void CActor::net_Import_Base(')
assert 'NET.clear()' not in actor, 'a reordered datagram must not restart the timeline'
export = method('src/xrGame/Actor_Network.cpp', 'void CActor::net_Export(')
assert 'P.w_u32(m_netcoop_owner_received);' in export
object_list = method('src/xrEngine/xr_object_list.cpp', 'void CObjectList::net_Import(')
assert 'P->net_Import(own);' in object_list and 'Packet->r_seek(rsize + size);' in object_list
source += r'''
int main(){
 NET_Packet packet;packet.set(900,0.2f);packet.pos=0;
 assert(netcoop::snapshot_packet_stale(packet,1000)&&packet.pos==0);
 packet.set(1000,0.3f);assert(!netcoop::snapshot_packet_stale(packet,1000)&&packet.pos==0);
 packet.pos=8;assert(netcoop::snapshot_packet_stale(packet,1000)&&packet.pos==8);
 for(auto import:{&Replica::actor,&Replica::stalker,&Replica::monster,&Replica::custom}){
  Replica replica;packet.set(1000,1);(replica.*import)(packet);
  packet.set(1500,0);(replica.*import)(packet);
  assert(replica.health==0&&replica.mutations==2&&replica.NET.size()==2);
  // Old living snapshots arrive after the death, including >300 ms late.
  for(u32 stamp:{1499u,1100u,100u}){
   packet.set(stamp,1);(replica.*import)(packet);
   assert(replica.health==0&&replica.mutations==2&&replica.NET.size()==2&&packet.pos==0);
  }
  packet.set(1501,0.4f);(replica.*import)(packet);
  assert(replica.health==0.4f&&replica.mutations==3&&replica.NET.back().dwTimeStamp==1501);
  // Equal timestamps still carry current equipment/health, as before.
  packet.set(1501,0.5f);(replica.*import)(packet);assert(replica.health==0.5f&&replica.NET.size()==3);
  packet.set(1502,1);packet.count=7;(replica.*import)(packet);assert(replica.health==0.5f&&packet.pos==0);
  // Fresh replica after a location switch has a new independent timeline.
  Replica next_map;packet.set(10,0.6f);(next_map.*import)(packet);assert(next_map.health==0.6f&&next_map.mutations==1);
  // The gate applies only to remote pure-client replicas.
  replica.remote=false;packet.set(1,0.7f);(replica.*import)(packet);assert(replica.health==0.7f);
  replica.remote=true;netcoop::pure=false;packet.set(2,0.8f);(replica.*import)(packet);assert(replica.health==0.8f);
  netcoop::pure=true;
 }
 puts("PASS actual stale snapshot gates: actor/NPC/mutant/custom, no health/equipment rollback or timeline reset, equal/new stamps, packet cursor, short header, fresh location and server/local guards");
}
'''
with TemporaryDirectory() as temporary:
    cpp = Path(temporary) / 'snapshot-order.cpp'
    exe = Path(temporary) / ('snapshot-order.exe' if os.name == 'nt' else 'snapshot-order')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)] if os.name == 'nt' else
               ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=temporary, check=True)
    subprocess.run([str(exe)], cwd=temporary, check=True, timeout=15)
