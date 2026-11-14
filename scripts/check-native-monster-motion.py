"""CI-only actual mutant motion playback rejects missing indexes and nonfinite timing."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
native = (root / 'src/xrGame/ai/monsters/basemonster/base_monster_net.cpp').read_text(encoding='utf-8')


def method(signature):
    start = native.index(signature)
    end = native.index('{', start) + 1
    depth = 1
    while depth:
        depth += (native[end] == '{') - (native[end] == '}')
        end += 1
    return native[start:end]


source = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <utility>
#include <vector>
using u16=std::uint16_t;using u32=std::uint32_t;
constexpr float EPS=0.00001f,SAMPLE_SPF=1.f/30.f;
constexpr bool TRUE=true;
template<class T>T _min(T a,T b){return std::min(a,b);}
template<class T>T _max(T a,T b){return std::max(a,b);}
bool _valid(float value){return std::isfinite(value);}
// Match the engine MotionID union; MSVC enables its anonymous-field extension.
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable:4201)
#endif
struct MotionID {
 union {struct{u16 idx,slot;};u32 val;};
 MotionID():val(u32(-1)){}bool valid()const{return val!=u32(-1);}
};
#ifdef _MSC_VER
#pragma warning(pop)
#endif
struct CMotionDef{u16 bone_or_part=0;};
struct shared_motions {
 std::vector<CMotionDef>* definitions;
 std::vector<CMotionDef>* motion_defs(){return definitions;}
};
struct CBlend {
 enum{eFalloff=1};MotionID motionID;float timeTotal=1,timeCurrent=0,speed=1;
 bool stop_at_end=false,playing=true;int state=0;int blend_state(){return state;}
};
struct IterateBlendsCallback{virtual ~IterateBlendsCallback()=default;virtual void operator()(CBlend&)=0;};
struct IKinematicsAnimated {
 std::vector<std::vector<CMotionDef>> slots{{CMotionDef{}}};CBlend blend;
 unsigned definitions_read=0,plays=0,updates=0,iterations=0;
 shared_motions current;
 u16 LL_MotionsSlotCount(){return u16(slots.size());}
 const shared_motions& LL_MotionsSlot(u16 slot){assert(slot<slots.size());current.definitions=&slots.at(slot);return current;}
 CMotionDef* LL_GetMotionDef(MotionID motion){++definitions_read;return &slots.at(motion.slot).at(motion.idx);}
 u16 LL_PartID(const char*){return 0;}
 CBlend* LL_PlayCycle(u16,MotionID motion,bool,int,int){++plays;blend.motionID=motion;blend.timeCurrent=0;return &blend;}
 void LL_IterateBlends(IterateBlendsCallback& callback){++iterations;callback(blend);}
 void UpdateTracks(){++updates;}
};
template<class T>T smart_cast(IKinematicsAnimated* model){return static_cast<T>(model);}
struct CBaseMonster {
 IKinematicsAnimated* visual=nullptr;u32 m_netcoop_motion=u32(-1),m_netcoop_motion_played=u32(-1);
 float m_netcoop_motion_speed=1,m_netcoop_phase=0,m_netcoop_phase_played=0;
 IKinematicsAnimated* Visual(){return visual;}void netcoop_play_motion();
};
''' + method('static bool netcoop_monster_motion_valid(') + '\n' + method('void CBaseMonster::netcoop_play_motion()') + r'''
int main(){
 CBaseMonster monster;monster.netcoop_play_motion();
 IKinematicsAnimated model;monster.visual=&model;monster.netcoop_play_motion();assert(!model.updates);
 MotionID valid;valid.slot=0;valid.idx=0;monster.m_netcoop_motion=valid.val;
 monster.m_netcoop_phase=.4f;monster.m_netcoop_motion_speed=1.2f;
 monster.netcoop_play_motion();assert(model.plays==1&&model.definitions_read==1&&model.updates==1);
 assert(model.blend.timeCurrent==.4f&&model.blend.speed==1.2f);
 monster.netcoop_play_motion();assert(model.plays==1&&model.iterations==1&&model.updates==2);
 const unsigned reads=model.definitions_read,updates=model.updates;
 // A foreign library slot or absent cycle must never reach the renderer.
 for(auto pair:{std::pair<u16,u16>{u16(1),u16(0)},{u16(0),u16(1)},{u16(65534),u16(65534)}}){
  MotionID bad;bad.slot=pair.first;bad.idx=pair.second;monster.m_netcoop_motion=bad.val;
  monster.netcoop_play_motion();assert(model.definitions_read==reads&&model.updates==updates&&model.plays==1);
 }
 monster.m_netcoop_motion=valid.val;
 for(float bad:{std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity(),-std::numeric_limits<float>::infinity()}){
  monster.m_netcoop_phase=bad;monster.netcoop_play_motion();assert(model.updates==updates);
  monster.m_netcoop_phase=.4f;monster.m_netcoop_motion_speed=bad;monster.netcoop_play_motion();assert(model.updates==updates);
  monster.m_netcoop_motion_speed=1.2f;
 }
 // Validate against the current model each time, including same pointer reuse.
 model.slots.clear();monster.netcoop_play_motion();assert(model.updates==updates);
 model.slots.resize(1);monster.netcoop_play_motion();assert(model.updates==updates);
 model.slots[0].push_back({});monster.netcoop_play_motion();assert(model.updates==updates+1&&model.plays==1);
 puts("PASS actual mutant motion playback: slot/index bounds before renderer access, finite phase/speed, current visual replacement, valid playback and smooth existing blend retained");
}
'''
with TemporaryDirectory() as temporary:
    cpp = Path(temporary) / 'monster-motion.cpp'
    exe = Path(temporary) / ('monster-motion.exe' if os.name == 'nt' else 'monster-motion')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)] if os.name == 'nt' else
               ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=temporary, check=True)
    subprocess.run([str(exe)], cwd=temporary, check=True, timeout=15)
