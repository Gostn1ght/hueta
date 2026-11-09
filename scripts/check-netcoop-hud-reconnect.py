"""Actual persistent Lua HUD/pickup lifecycle, clock rollback and retained health."""
from pathlib import Path
from lupa.lua51 import LuaRuntime
root=Path(__file__).resolve().parents[1]
bhs=(root/'scripts/netcoop-overlay/client/zzz_player_injuries.script').read_text(encoding='cp1251')
lua=LuaRuntime()
lua.execute('''
zzz_player_injuries_mcm={get_config=function()return false end}
dialogs={is_actor_not_healthy=function()return false end}
function time_global()return 10 end
statics={bhs_health_head_bar=true,bhs_health_head_bar_green_1610=true,body_health_system=true,unrelated=true}
hud={GetCustomStatic=function(self,n)return statics[n]end,RemoveCustomStatic=function(self,n)statics[n]=nil end}
function get_hud()return hud end
''')
lua.execute(bhs+'''
health.head=3;timedhp.head=2;preview.health.head=99;preview.bonus.head=99
init=true;scuffed_fix=true;xml={old=true};progress_health_head={old=true}
tg_anm=900000;show_hud_change_time=900000
netcoop_reset_actor()
assert(health.head==3 and timedhp.head==2,'UI reset must not heal or erase authoritative limb state')
assert(not statics.bhs_health_head_bar and not statics.bhs_health_head_bar_green_1610 and not statics.body_health_system)
assert(statics.unrelated,'another addon UI must survive')
assert(not init and not scuffed_fix and not xml and not progress_health_head)
assert(not preview.health.head and not preview.bonus.head and tg_anm==0 and show_hud_change_time==0)
netcoop_reset_actor();assert(health.head==3 and timedhp.head==2)
hud=nil;netcoop_reset_actor();assert(health.head==3)
init=true;xml={};progress_health_head={};get_hud=function()error('old HUD root')end
netcoop_reset_actor();assert(not init and not xml and not progress_health_head and health.head==3)
get_hud=function()return {GetCustomStatic=function()error('old child')end}end
init=true;netcoop_reset_actor();assert(not init and health.head==3)
''')
dot=(root/'scripts/netcoop-overlay/client/ui_hud_dotmarks.script').read_text(encoding='cp1251')
def block(start,end):
    return dot[dot.index(start):dot.index(end,dot.index(start))]
code=block('function actor_on_first_update()','function show_welcome_message()')
code+=block('function start_scanning()','function stop_scanning()')
code+=block('function reset_nearby_item_tables()','function update_actor_move_state()')
code+=dot[dot.index('function netcoop_reset_actor()'):]
lua=LuaRuntime()
lua.execute('''
cfg={scan_start_delay=.1,held_key=1,held_mod=2,holding={},use_release_time=900000,last_tap=900000,
 block_loot_window=900000,heal_cooldown_active=true,reverting_toggle=true,markers={{}},pending_actions={{}}}
scanning=true;callbacks={};timers={dotmark_scan_delay=true};handlers=0
function RegisterScriptCallback(n,f)callbacks[n]=f end
function RemoveTimeEvent(n,id)timers[n]=nil end
function CreateTimeEvent(n,id,delay,f)if not timers[n]then timers[n]=f end end
function time_global()return 10 end
function vl(...)end
function validate_object_tables()end
function check_for_dependencies()return dependencies_failed end
function check_for_main_ui()end
function set_killswitch(v)cfg.killswitch_all=v end
function set_handler_callbacks()handlers=handlers+1 end
function show_welcome_message()end
function update_skill_bonus_range()end
new_ui={};new_marks={}
ActorMenu={get_maingame=function()return new_ui end}
utils_catspaw_hudmarks={get_hud_mark_manager=function()return new_marks end}
'''+code+'''
netcoop_reset_actor()
assert(not scanning and not cfg.held_key and not cfg.held_mod and not cfg.holding)
assert(not cfg.use_release_time and not cfg.last_tap and not cfg.block_loot_window)
assert(not cfg.heal_cooldown_active and not cfg.reverting_toggle and not timers.dotmark_scan_delay)
assert(next(cfg.markers)==nil and next(cfg.pending_actions)==nil and cfg.netcoop_restart)
actor_on_first_update()
assert(maingameui==new_ui and hmm==new_marks and handlers==1 and cfg.game_started)
assert(type(timers.dotmark_scan_delay)=='function','old delayed event must be replaced even after clock rollback')
timers.dotmark_scan_delay();assert(scanning and not cfg.killswitch_all)
cfg.disable_addon=true;netcoop_reset_actor();actor_on_first_update();assert(not scanning and handlers==1)
cfg.disable_addon=false;dependencies_failed=true;netcoop_reset_actor();actor_on_first_update();assert(not scanning and handlers==1)
''')
print('PASS actual HUD/pickup reconnect: owned widgets only, no healing, held/loot locks cleared, fresh HUD and timer, disabled/dependency failure respected')

# Execute the actual nested bar builder with a replaced custom-static root.
# Cached userdata must rebind even when no actor-spawn callback was emitted.
a=bhs.index('local function ParamBar(')
b=bhs.index('--- green bkg lines',a)
bar=bhs[a:b].rstrip()
ui=LuaRuntime()
ui.execute("""
bar_roots={};display={types={}};healthstatus=true;show_hud_type=1
show_hud_change_time=0;scuffed_fix=true;disable_hud_fps_fix_tmr=1000
function time_global()return 1000 end
function netcoop_enabled()return true end
function CreateTimeEvent()end
function get_hud()return hud end
xml={InitProgressBar=function(self,name,root)
 return {owner=root,Show=function()end,SetProgressPos=function(self,v)self.value=v end}
end}
roots={};hud={GetCustomStatic=function(self,n)return roots[n]end,
 AddCustomStatic=function(self,n)local wnd={SetAutoDelete=function()end};roots[n]={wnd=function()return wnd end}end,
 RemoveCustomStatic=function(self,n)roots[n]=nil end}
"""+bar+"""
local first=ParamBar(nil,'head','bodypart',11,11,true)
assert(first and first.value==100,'first frame displays real health, never placeholder 55/red')
roots.head=nil
local second=ParamBar(first,'head','bodypart',3,11,true)
assert(second and second~=first and second.owner~=first.owner and second.value==300/11)
local wnd={};roots.head={wnd=function()return wnd end}
local third=ParamBar(second,'head','bodypart',11,11,true)
assert(third~=second and third.owner==wnd and third.value==100)
""")
print('PASS real limb bar builder: replaced HUD roots rebind, expired throttle cannot block MP startup, first frame uses actual health')
