"""CI-only: actual stable motion table and manager cache under reordered OMF slots."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

root = Path(__file__).resolve().parents[1]
header = root / 'src/xrGame/netcoop_motion_identity.h'
manager = (root / 'src/xrGame/stalker_animation_manager.cpp').read_text(encoding='utf-8')
export = (root / 'src/xrGame/ai/stalker/ai_stalker.cpp').read_text(encoding='utf-8')
puppet = (root / 'src/xrGame/stalker_animation_manager_update.cpp').read_text(encoding='utf-8')


def function(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


ready = function(manager, 'bool CStalkerAnimationManager::netcoop_motions_ready()')
wire = function(manager, 'u32 CStalkerAnimationManager::netcoop_motion_wire(const MotionID& motion)')
for signature in ('void CStalkerAnimationManager::reinit()', 'void CStalkerAnimationManager::reload()'):
    body = function(manager, signature)
    assert 'm_netcoop_motions.reset();' in body and 'm_netcoop_motion_slots.clear();' in body
    assert 'netcoop_motions_ready();' not in body, 'Offline/reload must not eagerly scan all motions'
assert 'anim_mode && netcoop::enabled() ? u8(anim_mode | netcoop::motion_mode_hashed) : anim_mode' in export
assert 'am.netcoop_motion_wire(anims[i])' in export
assert 'resolve_motion_snapshot(m_netcoop_motions' in puppet
assert 'anims[i].val = stalker.m_netcoop_anim[i]' not in puppet
assert 'switch (mode)' in puppet
renderer = (root / 'src/Layers/xrRender/SkeletonAnimated.cpp').read_text(encoding='utf-8')
lookup = function(renderer, 'MotionID CKinematicsAnimated::ID_Cycle_Safe(LPCSTR N)')
assert 'int(m_Motions.size()) - 1' in lookup and '--k' in lookup
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')

source = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <map>
#include <memory>
#include <string>
using u8=std::uint8_t;using u16=std::uint16_t;using u32=std::uint32_t;
''' + '#include "' + header.as_posix() + '"\n' + r'''
namespace netcoop{bool active=true;bool enabled(){return active;}}
template<class T>using xr_vector=std::vector<T>;
struct MotionID{u16 slot=0,idx=u16(-1);u32 val=u16(-1);bool valid()const{return val!=u16(-1);}};
struct Name{
 std::string value;Name(const char* text):value(text){}const char* c_str()const{return value.c_str();}
 bool operator<(const Name& other)const{return value<other.value;}
};
int enumerations=0;
struct SharedValue{std::map<Name,u16>cycles;};
struct shared_motions{
 std::shared_ptr<SharedValue> p;
 std::map<Name,u16>* cycle(){++enumerations;return &p->cycles;}
 bool operator==(const shared_motions& other)const{return p==other.p;}
};
struct IKinematicsAnimated{
 std::vector<shared_motions>slots;
 u16 LL_MotionsSlotCount(){return u16(slots.size());}
 const shared_motions& LL_MotionsSlot(u16 index){return slots.at(index);}
};
template<class To,class From>To smart_cast(From* value){return static_cast<To>(value);}
struct Actor{IKinematicsAnimated* visual=nullptr;IKinematicsAnimated* Visual(){return visual;}};
struct CStalkerAnimationManager{
 Actor owner;IKinematicsAnimated* m_skeleton_animated=nullptr;
 netcoop::MotionIdentityTable m_netcoop_motions;
 xr_vector<shared_motions>m_netcoop_motion_slots;
 Actor& object(){return owner;}
 bool netcoop_motions_ready();u32 netcoop_motion_wire(const MotionID&);
};
''' + ready + wire + r'''
shared_motions slot(const char* name,u16 index){
 shared_motions result;result.p=std::make_shared<SharedValue>();result.p->cycles.emplace(Name(name),index);return result;
}
int main(){
 using namespace netcoop;
 MotionIdentityTable server,client;
 server.build({{"walk",0,0},{"idle",1,0}});
 client.build({{"idle",0,0},{"walk",1,0}});
 u32 key=motion_wire_invalid;
 assert(motion_key(1,0)!=motion_key(0,0)); // raw server idle selects client walk
 assert(client.decode(server.encode(1,0),key)&&key==motion_key(0,0));
 assert(!client.decode(motion_wire_invalid,key)&&!client.decode(motion_name_hash("absent"),key));
 assert(client.encode(99,99)==motion_wire_invalid);
 // Exact-name aliases follow engine's highest-slot lookup, independent of insertion order.
 client.build({{"idle",0,5},{"idle",3,7},{"alias_z",3,7},{"alias_a",3,7}});
 assert(client.decode(motion_name_hash("idle"),key)&&key==motion_key(3,7));
 const u32 alias_hash=client.encode(3,7);
 client.build({{"alias_z",3,7},{"alias_a",3,7},{"idle",3,7},{"idle",0,5}});
 assert(alias_hash==client.encode(3,7)&&alias_hash==motion_name_hash("alias_a"));
 // Three distinct colliding names remain poisoned, exact duplicates alone are not collisions.
 client.build({{"one",0,1},{"two",0,2},{"three",0,3}},[](const char*){return u32(77);});
 assert(!client.decode(77,key));
 for(u16 i=1;i<=3;++i)assert(client.encode(0,i)==motion_wire_invalid&&client.legacy(motion_key(0,i)));
 client.build({{"one",0,1},{"one",2,2}},[](const char*){return u32(77);});
 assert(client.decode(77,key)&&key==motion_key(2,2));
 client.build({{"one",0,1}},[](const char*){return motion_wire_invalid;});
 assert(client.encode(0,1)==motion_wire_invalid&&!client.decode(motion_wire_invalid,key));
 client.build({{"idle",0,0},{"walk",1,0},{"head",2,0}});
 u32 packet[3]={motion_name_hash("head"),motion_name_hash("idle"),motion_name_hash("walk")},keys[3];u8 mode=0;
 assert(resolve_motion_snapshot(client,u8(motion_mode_hashed|3),packet,keys,mode)&&mode==3);
 assert(keys[0]==motion_key(2,0)&&keys[1]==motion_key(0,0)&&keys[2]==motion_key(1,0));
 packet[0]=motion_name_hash("missing_head");
 assert(resolve_motion_snapshot(client,u8(motion_mode_hashed|3),packet,keys,mode)&&keys[0]==motion_wire_invalid);
 packet[1]=motion_name_hash("missing_torso");
 assert(!resolve_motion_snapshot(client,u8(motion_mode_hashed|3),packet,keys,mode));
 packet[0]=motion_name_hash("idle");
 assert(resolve_motion_snapshot(client,u8(motion_mode_hashed|1),packet,keys,mode)&&mode==1);
 assert(resolve_motion_snapshot(client,u8(motion_mode_hashed|2),packet,keys,mode)&&mode==2);
 packet[0]=motion_key(1,0);
 assert(resolve_motion_snapshot(client,2,packet,keys,mode)&&keys[0]==packet[0]);
 packet[0]=motion_key(99,99);assert(!resolve_motion_snapshot(client,2,packet,keys,mode));
 assert(!resolve_motion_snapshot(client,0,packet,keys,mode));
 assert(!resolve_motion_snapshot(client,7,packet,keys,mode));
 client.reset();assert(!client.built()&&!client.legacy(motion_key(0,0)));
 // Actual manager cache: no cycle-name scans during repeated snapshots;
 // replacement of slots even at the same visual address rebuilds safely.
 IKinematicsAnimated visual;visual.slots={slot("idle",4),slot("walk",7)};
 CStalkerAnimationManager manager;manager.owner.visual=&visual;manager.m_skeleton_animated=&visual;
 active=false;assert(!manager.netcoop_motions_ready()&&enumerations==0);
 MotionID motion;motion.slot=0;motion.idx=4;motion.val=motion_key(0,4);
 assert(manager.netcoop_motion_wire(motion)==motion.val&&enumerations==0);
 active=true;assert(manager.netcoop_motions_ready()&&enumerations==2);
 for(int i=0;i<1000;++i)assert(manager.netcoop_motion_wire(motion)==motion_name_hash("idle"));
 assert(enumerations==2);
 std::weak_ptr<SharedValue> old_slot=visual.slots[0].p;
 visual.slots={slot("idle",9),slot("walk",1)};
 assert(!old_slot.expired()); // cache owns the old motion data until invalidation
 assert(manager.netcoop_motions_ready()&&enumerations==4&&old_slot.expired());
 assert(manager.netcoop_motion_wire(motion)==motion_wire_invalid);
 motion.idx=9;motion.val=motion_key(0,9);
 assert(manager.netcoop_motion_wire(motion)==motion_name_hash("idle"));
 manager.m_netcoop_motions.reset();manager.m_netcoop_motion_slots.clear();
 assert(manager.netcoop_motions_ready()&&enumerations==6);
 manager.owner.visual=nullptr;assert(!manager.netcoop_motions_ready());
 std::puts("PASS actual NPC motion identity/cache: reordered slots, collisions/aliases, invalid/missing/legacy modes, reset, same-address visual replacement, 1000 cached snapshots, offline no scan");
}
'''
with TemporaryDirectory(prefix='npc-motion-identity-') as temporary:
    folder = Path(temporary)
    cpp, exe = folder / 'motion.cpp', folder / ('motion.exe' if os.name == 'nt' else 'motion')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)]
               if os.name == 'nt' else ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
