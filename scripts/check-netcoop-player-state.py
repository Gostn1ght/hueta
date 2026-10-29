"""Actual Lua player-state handoff: early delivery, injured limbs, respawn and forced flush."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
source = (root / 'scripts/netcoop-overlay/client/netcoop_client_compat.script').read_text(encoding='cp1251')
code = source[source.index('local PLAYER_STATE_MODULES ='):source.index('-- Sleep deprivation is cut')]
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute('''
local player_state_ready, next_player_state, pending_player_state = false, 0, nil
db={storage={}};now=100;messages={};loads=0
function time_global() return now end
function printf(...) end
function netcoop_command(text) messages[#messages+1]=text end
actor_status_thirst={save_state=function(t) t.thirst=.6 end,load_state=function(t) assert(t.thirst==.6);loads=loads+1 end}
zzz_player_injuries={health={},timedhp={},maxhp={head=11,torso=11,leftarm=5,rightarm=5,leftleg=5,rightleg=5}}
for part,max in pairs(zzz_player_injuries.maxhp) do zzz_player_injuries.health[part]=max;zzz_player_injuries.timedhp[part]=0 end
''' + code + '''
function fixture_report() report_player_state() end
function fixture_collect() return collect_player_state() end
function fixture_pending() return pending_player_state end
function fixture_ready() return player_state_ready end
''')
lua.execute('''
actor={satiety=.7,power=.4,id=function() return 7 end}
flush_player_state();assert(#messages==0,'no default state before restore')
local saved='satiety=0.7;power=0.4;injuries={health={head=3;torso=7;leftarm=2;rightarm=4;leftleg=1;rightleg=5;};timedhp={head=1;leftleg=0.5;};};modules={actor_status_thirst={thirst=0.6;};};'
use_player_state(saved);assert(not fixture_ready() and fixture_pending()==saved,'state received before actor spawn must wait')
db.actor=actor;use_player_state(fixture_pending());assert(fixture_ready() and fixture_pending()==nil)
assert(loads==1 and actor.satiety==.7 and actor.power==.4)
local b=zzz_player_injuries
assert(b.health.head==3 and b.health.leftleg==1 and b.timedhp.head==1 and b.timedhp.leftleg==.5)
assert(db.storage[7].pstor['health.head']==3 and db.storage[7].pstor['timedhp.head']==1)
local captured=fixture_collect();assert(captured:find('injuries=',1,true))
fixture_report();assert(#messages==0)
flush_player_state();assert(#messages==1 and messages[1]=='player_state '..captured)
now=5099;fixture_report();assert(#messages==1)
now=5100;fixture_report();assert(#messages==2)
use_player_state('-');assert(b.health.head==11 and b.health.leftleg==5 and b.timedhp.head==0,'new body does not inherit the old damaged HUD')
use_player_state(captured);assert(b.health.head==3 and b.timedhp.head==1,'living handoff retains damage')
use_player_state('injuries={health={head=-5;torso=999;};timedhp={head=99;torso=99;};};')
assert(b.health.head==0 and b.health.torso==11 and b.timedhp.head==0 and b.timedhp.torso==11)
local before=fixture_collect();use_player_state('invalid state');assert(fixture_collect()==before)
actor.power=0/0;assert(not fixture_collect():find('nan',1,true))
actor.power=math.huge;assert(not fixture_collect():find('inf',1,true))
use_player_state('modules=1;injuries={health=2;timedhp=true;};satiety=99;power=-4;')
assert(actor.satiety==1 and actor.power==0 and b.health.head==11)
''')
spawn = source[source.index('function on_actor_spawned('):source.index('-- A dead local actor')]
assert 'player_state_ready = false' in spawn
assert 'player_state_ready, next_player_state, pending_player_state = false, 0, nil' in spawn
native = (root / 'src/xrGame/UIGameSP.cpp').read_text(encoding='utf-8')
confirmation = native[native.index('void CChangeLevelWnd::OnOk()'):native.index('void CChangeLevelWnd::OnCancel()')]
assert confirmation.index('client_flush_player_state()') < confirmation.index('Level().Send(')
assert 'net_flags(TRUE, TRUE)' in confirmation
print('PASS actual player-state Lua: early delivery retained, limb damage/healing and thirst preserved, fresh-body reset, bounded values, no NaN/Inf, ordered forced flush before passage')
