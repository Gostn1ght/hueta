"""Actual Lua player-state handoff: early delivery, injured limbs, respawn and forced flush."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
source = (root / 'scripts/netcoop-overlay/client/netcoop_client_compat.script').read_text(encoding='cp1251')
code = source[source.index('local PLAYER_STATE_MODULES ='):source.index('-- Sleep deprivation is cut')]
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute('''
local player_state_ready, next_player_state, pending_player_state = false, 0, nil
local player_state_spawn_ready=true
db={storage={}};now=100;messages={};loads=0
function time_global() return now end
function printf(...) end
function netcoop_command(text) if text~='player_state ack' then messages[#messages+1]=text end end
actor_status_thirst={save_state=function(t) t.thirst=.6 end,load_state=function(t) assert(t.thirst==.6);loads=loads+1 end}
zzz_player_injuries={health={},timedhp={},maxhp={head=11,torso=11,leftarm=5,rightarm=5,leftleg=5,rightleg=5}}
for part,max in pairs(zzz_player_injuries.maxhp) do zzz_player_injuries.health[part]=max;zzz_player_injuries.timedhp[part]=0 end
''' + code + '''
function fixture_report() report_player_state() end
function fixture_collect() return collect_player_state() end
function fixture_pending() return pending_player_state end
function fixture_ready() return player_state_ready end
function fixture_begin_body() player_state_ready=false;pending_player_state=nil;next_player_state=0 end
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
local old_head=b.health.head
use_player_state('@6|-');assert(b.health.head==old_head,'previous actor snapshot must not reset current body')
fixture_begin_body();use_player_state('@7|-');assert(b.health.head==11,'targeted fresh-body snapshot is applied')
use_player_state('@7|'..captured);assert(b.health.head==11,'duplicate initial snapshot must not overwrite current health');fixture_begin_body();use_player_state('@7|'..captured);assert(b.health.head==3,'targeted living handoff retains damage')
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

lua.execute("local b=zzz_player_injuries;local old=b.maxhp;b.maxhp={};fixture_begin_body();use_player_state('@7|-');assert(fixture_pending()=='@7|-');b.maxhp=old;use_player_state(fixture_pending());assert(fixture_pending()==nil)")

# First binder update must run before snapshot acknowledgement, even if BHS
# tables already exist from the preceding body in this Lua VM.
fresh=LuaRuntime(unpack_returned_tuples=True)
fresh.execute(r'''
db={storage={[7]={pstor={}}}};now=100;acks=0;input_resets=0
level={enable_input=function()input_resets=input_resets+1 end}
function time_global()return now end
function printf()end
function netcoop_command(text)if text=='player_state ack' then acks=acks+1 end end
function quiet_busy_hands()end
function CreateTimeEvent()end
zzz_player_injuries={health={},timedhp={},maxhp={head=11,torso=11,leftarm=5,rightarm=5,leftleg=5,rightleg=5}}
actor={id=function()return 7 end}
bind_stalker={actor_binder={net_destroy=function()end,update=function(self)
 assert(zzz_player_injuries.health.head==11 and db.storage[7].pstor['health.head']==11,'old lethal state neutralized before first update')
 zzz_player_injuries.health.head=0;db.storage[7].pstor['health.head']=0;return 123
end}}
''')
declarations=source[source.index('local controlled_actor = nil'):source.index('-- The locally controlled Actor:')]
spawn=source[source.index('function on_actor_spawned('):source.index('-- A dead local actor')]
lifecycle=source[source.index('install_actor_lifecycle = function()'):source.index('function is_pure_client()')]
fresh.execute(declarations+'\nuse_own_actor_id=function()end\n'+code+spawn+lifecycle+r'''
on_actor_spawned(actor)
assert(input_resets==1,'new body releases input lock held by an interrupted old-body animation')
use_player_state('@7|-');assert(acks==0 and pending_player_state=='@7|-')
assert(bind_stalker.actor_binder.update({object=actor,st=db.storage[7]})==123)
assert(acks==1 and player_state_ready and pending_player_state==nil)
assert(zzz_player_injuries.health.head==11 and db.storage[7].pstor['health.head']==11)
''')
print('PASS actual binder/state ordering: initialization before ACK; early snapshot survives first-update overwrite')

# An optional HUD/PDA reset failure must not abort control/binder setup.
fresh.execute(r'''
local logs=0
function printf(text,...) if text:find('[diag][actor-reset]',1,true) then logs=logs+1 end end
local resets=0
netcoop_pda={reset=function() error('stale PDA widget') end}
zzz_player_injuries.netcoop_reset_actor=function() error('stale BHS widget') end
ui_hud_dotmarks={netcoop_reset_actor=function() resets=resets+1 end}
on_actor_spawned(actor)
assert(input_resets==2 and resets==1 and logs==2,'optional resets are isolated; essential input restoration runs')
use_player_state('@7|-')
assert(bind_stalker.actor_binder.update({object=actor,st=db.storage[7]})==123)
assert(acks==2 and zzz_player_injuries.health.head==11,'restore and input must survive an optional HUD failure')
''')
# Execute the actual disabled-DotMarks reset path (dependency failure => cfg=nil).
dotmarks=(root/'scripts/netcoop-overlay/client/ui_hud_dotmarks.script').read_text(encoding='utf-8')
reset=dotmarks[dotmarks.index('function netcoop_reset_actor()'):]
LuaRuntime().execute('cfg=nil\n'+reset+'\nnetcoop_reset_actor()')
print('PASS actor bootstrap: stale optional PDA/BHS widgets cannot abort input/binder/state restore; disabled DotMarks is safe')

# A previous map may retire a binder after the next map has reused its ID.
fresh.execute(r"""
local replacement={id=function()return 7 end}
local old={object=actor,st=db.storage[7]}
local deletes=0
function db.del_obj()deletes=deletes+1 end
function db.delete_enemy()deletes=deletes+1 end
object_binder={net_destroy=function()return 'retired' end}
db.storage[7]={pstor={}} -- actual new actor_binder.reinit creates a new table
on_actor_spawned(replacement)
local storage=db.storage[7];storage.pstor={['health.head']=3}
on_actor_destroyed(actor,old.st)
assert(db.actor==replacement and db.storage[7]==storage)
assert(bind_stalker.actor_binder.update(old)==nil)
assert(bind_stalker.actor_binder.net_destroy(old)=='retired')
assert(deletes==0 and db.actor==replacement and db.storage[7]==storage)
db.del_actor(actor);assert(deletes==0 and db.actor==replacement)
""")
print('PASS retired actor with reused ID cannot update/reset/delete replacement body or limb storage')

# Faithful pointer-wrapper aliases: equal native ID and storage but distinct
# Lua wrappers, as luabind's pointer_converter constructs with lua_newuserdata.
alias=LuaRuntime()
alias.execute(r"""
db={storage={[7]={pstor={}}},actor_proxy={net_destroy=function()end}}
level={enable_input=function()end};now=100;updates=0;destroyed=0
function time_global()return now end
function printf()end
function quiet_busy_hands()end
function CreateTimeEvent()end
actor={id=function()return 7 end}
binder_alias={id=function()return 7 end};assert(actor~=binder_alias)
function db.del_obj(obj)db.storage[obj:id()]=nil end
bind_stalker={actor_binder={update=function(self)updates=updates+1 end,
 net_destroy=function(self)destroyed=destroyed+1;db.del_actor(self.object) end}}
"""+declarations+'\nuse_own_actor_id=function()end\n'+spawn+lifecycle+r"""
on_actor_spawned(actor)
local body={object=binder_alias,st=db.storage[7]}
bind_stalker.actor_binder.update(body)
assert(updates==1,'a new Lua wrapper for the same native body MUST update')
bind_stalker.actor_binder.net_destroy(body)
assert(destroyed==1 and db.actor==nil and db.storage[7]==nil)
""")
print('PASS real wrapper-alias regression: same body updates and retires despite unequal Lua userdata wrappers')
