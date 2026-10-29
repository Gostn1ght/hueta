"""CI-only regressions for the owner's four matching October 25/26 dumps."""
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
ROOT=Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT/path).read_text(encoding='utf-8')


missile=read('src/xrGame/Missile.cpp')
missile=missile[missile.index('bool CMissile::render_item_ui_query()'):missile.index('void CMissile::render_item_ui()')]
monster=read('src/xrGame/ai/monsters/basemonster/base_monster.cpp')
monster=monster[monster.index('void CBaseMonster::net_Relcase('):monster.index('void CBaseMonster::create_base_controls()')]
alive=re.search(r'IC BOOL g_Alive\(\) const \{[^}]+\}',read('src/xrGame/Entity.h')).group()
device=read('src/xrGame/CustomDevice.cpp')
visibility=device[device.index('void CCustomDevice::UpdateVisibility()'):device.index('void CCustomDevice::UpdateWork()')]
# Compile the actual entry guard; the counter stands in for the unchanged
# animation code after it. Its dependencies must not be touched during transit.
visibility=visibility[:visibility.index('\tbool bClimb')]
render=read('src/Layers/xrRender/r__dsgraph_build.cpp')
render_guard=render[render.index('void R_dsgraph_structure::r_dsgraph_insert_dynamic('):render.index('\tCRender& RI = RImplementation;')]
source=r'''
#include <cassert>
#include <cstdio>
#define IC
using BOOL=bool;
struct Condition{float health=1;float GetHealth()const{return health;}};
struct CEntity{
 Condition*m_entity_condition=nullptr;
 float GetfHealth()const{assert(m_entity_condition);return m_entity_condition->GetHealth();}
''' + alive + r'''
};
struct CObject{virtual ~CObject()=default;};struct CActor:CObject{};
template<class T>T smart_cast(CObject*p){return dynamic_cast<T>(p);}
struct Inventory{void*active=nullptr;void*ActiveItem(){return active;}};
struct CMissile{
 Inventory*m_pInventory=nullptr;bool destroyed=false,m_throw=false;CObject*parent=nullptr;int state=0;enum{eReady=1};
 bool getDestroy(){return destroyed;}CObject*H_Parent(){return parent;}int GetState(){return state;}
 bool render_item_ui_query();
};
''' + missile + r'''
bool pure=true;namespace netcoop{bool pure_client(){return pure;}}
int link_calls=0;struct Links{void remove_links(CObject*){++link_calls;}void remove_hit_info(CObject*){++link_calls;}void in_NetRelcase(CObject*){++link_calls;}};
struct MonsterBase{void net_Relcase(CObject*){++link_calls;}};
struct CBaseMonster:MonsterBase,CEntity{
 using inherited=MonsterBase;Links links,*StateMan=&links,*m_pPhysics_support=&links;
 Links EnemyMemory,SoundMemory,HitMemory,EnemyMan,CorpseMan,CorpseMemory;int ai_updates=0;
 Links&com_man(){return links;}Links&monster_squad(){return links;}void UpdateMemory(){++ai_updates;}
 void net_Relcase(CObject*);
};
''' + monster + r'''
CActor*current=nullptr;CActor*Actor(){return current;}void*g_player_hud=nullptr;
int visibility_updates=0;
struct CCustomDevice{CObject*parent=nullptr;CObject*H_Parent(){return parent;}void UpdateVisibility();};
''' + visibility + r'''
 ++visibility_updates;
}
struct Fvector{};struct ShaderRef{void*value=nullptr;void*_get(){return value;}};
struct dxRender_Visual{ShaderRef shader;};int render_updates=0;
struct R_dsgraph_structure{void r_dsgraph_insert_dynamic(dxRender_Visual*,Fvector&);};
''' + render_guard + r'''
 (void)Center;++render_updates;
}
int main(){
 CEntity entity;assert(!entity.g_Alive());Condition condition;entity.m_entity_condition=&condition;
 assert(entity.g_Alive());condition.health=0;assert(!entity.g_Alive());condition.health=1;
 CMissile grenade;assert(!grenade.render_item_ui_query());Inventory inventory;grenade.m_pInventory=&inventory;
 inventory.active=&grenade;grenade.state=CMissile::eReady;assert(!grenade.render_item_ui_query());
 CActor actor;grenade.parent=&actor;assert(grenade.render_item_ui_query());
 grenade.destroyed=true;assert(!grenade.render_item_ui_query());grenade.destroyed=false;
 grenade.m_throw=true;assert(!grenade.render_item_ui_query());grenade.m_throw=false;
 inventory.active=nullptr;assert(!grenade.render_item_ui_query());
 CBaseMonster beast;beast.m_entity_condition=&condition;CObject removed;
 beast.net_Relcase(&removed);assert(beast.ai_updates==0&&link_calls==11);
 pure=false;beast.net_Relcase(&removed);assert(beast.ai_updates==1&&link_calls==22);
 CCustomDevice device;device.UpdateVisibility();assert(visibility_updates==0);
 device.parent=&actor;device.UpdateVisibility();assert(visibility_updates==0);
 current=&actor;device.UpdateVisibility();assert(visibility_updates==0);
 g_player_hud=&actor;device.UpdateVisibility();assert(visibility_updates==1);
 CActor other;device.parent=&other;device.UpdateVisibility();assert(visibility_updates==1);
 R_dsgraph_structure graph;Fvector center;graph.r_dsgraph_insert_dynamic(nullptr,center);
 dxRender_Visual visual;graph.r_dsgraph_insert_dynamic(&visual,center);assert(render_updates==0);
 visual.shader.value=&actor;graph.r_dsgraph_insert_dynamic(&visual,center);assert(render_updates==1);
 std::puts("PASS actual detached object paths: grenade inventory/owner, conditionless entity, replica relcase preserves links without AI, device/HUD transit guards and shaderless visual rejection");
}
'''
with TemporaryDirectory(prefix='detached-objects-') as temporary:
    folder=Path(temporary)
    cpp,exe=folder/'detached.cpp',folder/('detached.exe' if os.name=='nt' else 'detached')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc',str(cpp),'/Fe:'+str(exe)] if os.name=='nt'
             else ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True)

assert 'if (!H_Parent() || H_Parent() != Level().CurrentEntity()) return;' in device
assert 'actor->inventory().ActiveItem()' in device
members=read('src/xrGame/ai/ai_monsters_misc.cpp')
assert members.count('Group.members()[k] && !Group.members()[k]->getDestroy() && Group.members()[k]->g_Alive()')==2
