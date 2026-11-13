"""CI-only: execute actual use/effect paths for exhausted and unlimited items."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

root = Path(__file__).resolve().parents[1]


def function(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


item = (root / 'src/xrGame/eatable_item.cpp').read_text(encoding='utf-8')
use = function(item, 'bool CEatableItem::UseBy(CEntityAlive* entity_alive)')
effects = function(item, 'void CEatableItem::ApplyEffectsOnly(CEntityAlive* entity_alive)')
inventory = (root / 'src/xrGame/Inventory.cpp').read_text(encoding='utf-8')
eat = function(inventory, 'bool CInventory::Eat(PIItem pIItem)')
assert eat.index('pItemToEat->Empty()') < eat.index('if (netcoop::pure_client())')
assert eat.index('pItemToEat->Empty()') < eat.index('actor->callback(GameObject::eUseObject)')
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')

source = r'''
#include <cassert>
#include <cstdint>
#include <string>
#include <cstdio>
using u8=std::uint8_t;
#define R_ASSERT(value) assert(value)
struct CInventory {};
struct CInventoryOwner { CInventory* m_inventory=nullptr; };
struct SMedicineInfluenceValues { void Load(const std::string&) {} };
enum EBoostParams { first_booster, second_booster, eBoostMaxCount };
const char* ef_boosters_section_names[] = {"first", "second"};
struct SBooster { void Load(const std::string&, EBoostParams) {} };
struct Settings { bool line_exist(const std::string&, const char*) { return true; } } settings;
Settings* pSettings=&settings;
struct Conditions {
 int influences=0,boosters=0;
 void ApplyInfluence(const SMedicineInfluenceValues&,const std::string&) { ++influences; }
 void ApplyBooster(const SBooster&,const std::string&) { ++boosters; }
};
struct CEntityAlive : CInventoryOwner {
 Conditions state;
 Conditions& conditions() { return state; }
 int ID() const { return 7; }
};
template<class T> T smart_cast(CEntityAlive* object) { return static_cast<T>(object); }
struct CPhysicItem {
 CEntityAlive* parent=nullptr;
 std::string cNameSect() const { return "medicine"; }
 CEntityAlive* H_Parent() { return parent; }
};
struct CEatableItem {
 CInventory* m_pInventory=nullptr;
 CPhysicItem physical;
 CPhysicItem* m_physic_item=&physical;
 u8 m_iRemainingUses=1,m_iMaxUses=1;
 bool use_condition=false;
 int condition_updates=0;
 bool Empty() const { return m_iRemainingUses==0; }
 bool IsUsingCondition() const { return use_condition; }
 void SetCondition(int) { ++condition_updates; }
 CPhysicItem& object() { return physical; }
 bool UseBy(CEntityAlive*);
 void ApplyEffectsOnly(CEntityAlive*);
};
''' + use + '\n' + effects + r'''
int main() {
 CInventory inventory;CEntityAlive actor;actor.m_inventory=&inventory;
 CEatableItem item;item.m_pInventory=&inventory;item.physical.parent=&actor;
 item.use_condition=true;
 assert(item.UseBy(&actor));assert(item.Empty());
 assert(actor.state.influences==1 && actor.state.boosters==2 && item.condition_updates==1);
 // A second packet before detach must not apply another dose or boosters.
 assert(!item.UseBy(&actor));item.ApplyEffectsOnly(&actor);
 assert(actor.state.influences==1 && actor.state.boosters==2 && item.condition_updates==1);
 assert(!item.UseBy(nullptr));item.ApplyEffectsOnly(nullptr);
 item.m_iRemainingUses=3;item.m_iMaxUses=3;
 for(int remaining=2;remaining>=0;--remaining) {
  assert(item.UseBy(&actor));assert(item.m_iRemainingUses==remaining);
 }
 assert(!item.UseBy(&actor));assert(actor.state.influences==4);
 item.m_iRemainingUses=u8(-1);item.m_iMaxUses=u8(-1);
 for(int i=0;i<300;++i) { assert(item.UseBy(&actor));assert(item.m_iRemainingUses==u8(-1)); }
 assert(actor.state.influences==304 && actor.state.boosters==608);
 // Prediction applies effects without consuming the server's remaining uses.
 item.m_iRemainingUses=2;item.ApplyEffectsOnly(&actor);
 assert(item.m_iRemainingUses==2 && actor.state.influences==305 && actor.state.boosters==610);
 std::puts("PASS actual eatable uses: empty replay rejected, one dose per finite use, 255 unlimited, prediction non-consuming, null safe");
}
'''
with TemporaryDirectory(prefix='eatable-uses-') as temporary:
    folder = Path(temporary)
    cpp = folder / 'check.cpp'
    exe = folder / ('check.exe' if os.name == 'nt' else 'check')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)]
               if os.name == 'nt' else
               ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
