"""CI-only: unfinished character bodies reject hits without granting lasting god mode."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

root = Path(__file__).resolve().parents[1]


def function(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


characters = (root / 'src/xrGame/netcoop_characters.inc').read_text(encoding='utf-8')
actor = (root / 'src/xrGame/Actor.cpp').read_text(encoding='utf-8')
condition = (root / 'src/xrGame/ActorCondition.cpp').read_text(encoding='utf-8')
clock = (root / 'src/xrGame/EntityCondition.cpp').read_text(encoding='utf-8')
pending = function(characters, 'bool server_character_restoring(u16 actor_id)')
condition_hit = function(condition, 'CWound* CActorCondition::ConditionHit(SHit* pHDS)')
clock_update = function(clock, 'void CEntityCondition::UpdateConditionTime()')
# Execute the actual early exits before the expensive existing simulation.
# The remainder is instrumented to prove it is reached again when ready.
update_prefix = condition[condition.index('void CActorCondition::UpdateCondition()'):
                          condition.index('\tfloat v_alcohol =', condition.index('void CActorCondition::UpdateCondition()'))]
hit_prefix = actor[actor.index('void CActor::Hit(SHit* pHDS)'):
                   actor.index('\tnetcoop::ServerVictimScope netcoop_victim(this);', actor.index('void CActor::Hit(SHit* pHDS)'))]
assert 'server_character_restoring' in update_prefix and 'server_character_restoring' in hit_prefix
scheduled = (root / 'src/xrGame/entity_alive.cpp').read_text(encoding='utf-8')
schedule = function(scheduled, 'void CEntityAlive::shedule_Update(u32 dt)')
assert schedule.index('conditions().UpdateConditionTime();') < schedule.index('conditions().UpdateCondition();')
assert 'it=s_character_restore.erase(it)' in characters  # ready completion revokes shield
assert 'if (s_character_restore.find(actor_id) != s_character_restore.end()) return nullptr;' in characters

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')

source = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <map>
#include <cstdio>
using u16=std::uint16_t; using u64=std::uint64_t;
constexpr int eGameIDSingle=1; int GameID(){return eGameIDSingle;}
template<class T>T _max(T a,T b){return std::max(a,b);}
struct World{void* Server=this;u64 now=100000;u64 GetGameTime(){return now;}
 u64 timeServer(){return now;}float GetGameTimeFactor(){return 10;}}world;
World& Level(){return world;}void* g_pGameLevel=&world;
namespace netcoop{
 bool active=true,client=false;bool enabled(){return active;}bool pure_client(){return client;}
 struct Restore{bool rejected=false;};std::map<u16,Restore>s_character_restore;
''' + pending + r'''
}
struct SHit{float power=2;};struct CWound{};
struct CActor{u16 id=42;int hit_effects=0;u16 ID()const{return id;}void Hit(SHit*);};
bool god=false;bool GodMode(const CActor*){return god;}
struct BaseCondition{
 float health=1;int hits=0;
 CWound* ConditionHit(SHit* hit){++hits;health-=hit->power;return nullptr;}
};
struct CActorCondition:BaseCondition{
 using inherited=BaseCondition;CActor* m_object;int updates=0;
 explicit CActorCondition(CActor* actor):m_object(actor){}
 CWound* ConditionHit(SHit*);void UpdateCondition();
};
''' + condition_hit + update_prefix + '++updates;\n}\n' + hit_prefix + r'''
 (void)pHDS;++hit_effects;
}
struct CEntityCondition{
 bool m_bTimeValid=false;u64 m_iLastTimeCalled=0;
 float m_fDeltaHealth=0,m_fDeltaPower=0,m_fDeltaRadiation=0,m_fDeltaCircumspection=0,m_fDeltaEntityMorale=0,delta=0;
 void SetConditionDeltaTime(float value){delta=value;}void UpdateConditionTime();
};
''' + clock_update + r'''
int main(){
 CActor actor;CActorCondition condition(&actor);SHit hit;
 using namespace netcoop;
 assert(!server_character_restoring(actor.ID()));
 s_character_restore[actor.ID()]={};
 assert(server_character_restoring(actor.ID()));
 CEntityCondition clock;clock.UpdateConditionTime();
 for(int second=0;second<59;++second){
  world.now+=1000;clock.UpdateConditionTime();condition.UpdateCondition();
  condition.ConditionHit(&hit);actor.Hit(&hit);
 }
 assert(condition.health==1&&condition.hits==0&&condition.updates==0&&actor.hit_effects==0);
 // Timeout rejection retains protection while asynchronous rollback removes the body.
 s_character_restore[actor.ID()].rejected=true;
 assert(server_character_restoring(actor.ID()));
 // Other players and offline/client simulation do not acquire a global shield.
 assert(!server_character_restoring(43));
 client=true;assert(!server_character_restoring(actor.ID()));client=false;
 active=false;assert(!server_character_restoring(actor.ID()));active=true;
 g_pGameLevel=nullptr;assert(!server_character_restoring(actor.ID()));g_pGameLevel=&world;
 world.Server=nullptr;assert(!server_character_restoring(actor.ID()));world.Server=&world;
 // Successful completion (or cleanup) erases the transaction, no persistent god flag.
 s_character_restore.erase(actor.ID());assert(!server_character_restoring(actor.ID())&&!god);
 world.now+=1000;clock.UpdateConditionTime();assert(clock.delta==1);
 condition.UpdateCondition();condition.ConditionHit(&hit);actor.Hit(&hit);
 assert(condition.updates==1&&condition.hits==1&&condition.health<0&&actor.hit_effects==1);
 // Preserve existing explicit god mode outside restoration.
 god=true;condition.ConditionHit(&hit);assert(condition.hits==1);
 std::puts("PASS actual restore gate/query/condition-hit and hit/update entry guards: lethal hit held, other bodies unaffected, ready revokes protection, scheduler clock stays current");
}
'''
with TemporaryDirectory(prefix='character-restore-damage-') as temporary:
    folder = Path(temporary)
    cpp, exe = folder / 'restore.cpp', folder / ('restore.exe' if os.name == 'nt' else 'restore')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)]
               if os.name == 'nt' else ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
