"""Execute the actual server population guard; no native build needed."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
source = (root / "scripts/netcoop-overlay/server/zz_netcoop_world_rules.script").read_text()
door_lua = LuaRuntime(unpack_returned_tuples=True)
door_lua.execute('''
cooperative = true
function netcoop_enabled() return cooperative end
objects = {}
clsid = {obj_physic=1,script_actor=2}
db = {storage={}}
level = {object_by_id=function(id) return objects[id] end}
''')
door_lua.execute(source)
door_lua.execute('''
assert(not physics_door_binder_ready(7))
objects[7] = {clsid=function() return 1 end}
db.storage[7] = {active_scheme="ph_door",ini={},ph_door={door_action={initialized=true}}}
assert(physics_door_binder_ready(7))
objects[7].clsid = function() return 2 end
assert(not physics_door_binder_ready(7), "Actor must never enter the door binder serializer")
objects[7].clsid = function() return 1 end
db.storage[7].ph_door.door_action.initialized = false
assert(not physics_door_binder_ready(7), "bootstrap must not save uninitialized binders")
db.storage[7].ph_door.door_action.initialized = true
db.storage[7].active_scheme = "ph_idle"
assert(not physics_door_binder_ready(7))
db.storage[7].active_scheme = "ph_door";db.storage[7].ini=nil
assert(not physics_door_binder_ready(7))
db.storage[7].ini={};cooperative=false
assert(not physics_door_binder_ready(7))
''')
print("Actual door binder classifier: initialized ph_door only, no Actor/idle/bootstrap/single-player PASS")
server = (root / "scripts/netcoop-overlay/server/netanomaly_server.script").read_text(encoding="utf-8")
door_lua.execute(server)
door_lua.execute(r'''
clock=1000;calls=0;gestures=0;handled=true
function time_global()return clock end
function alife()return {object=function()end}end
function netcoop_broadcast(channel,data)
    assert(channel=="netcoop_consumption" and data=="8|255|Player|anim_door_open")
    gestures=gestures+1
end
local gap=2
local player={id=function()return 8 end,alive=function()return true end,name=function()return "Player" end,
    position=function()return {distance_to=function()return gap end}end}
objects[8]=player
objects[7]={position=function()return {}end,use=function(_,actor)
    assert(actor==player and db.actor:id()==8)
    calls=calls+1
    return handled
end}
db.level_doors={[7]=true}
local function command(target)on_client_command("cid","Player",8,"door "..target,"player")end
db.actor={id=function()return 0 end}
command("7");assert(calls==0 and gestures==0)
db.actor=player
command("7.0");assert(calls==0)
gap=4;command("7");assert(calls==0)
gap=2;db.level_doors[7]=nil;command("7");assert(calls==0)
db.level_doors[7]=true
handled=false;command("7");assert(calls==1 and gestures==0)
handled=true;clock=1599;command("7");assert(calls==1)
clock=1600;command("7");assert(calls==2 and gestures==1)
''')
print("PASS door use command: requesting actor, real registered target, range, cooldown and gesture only after accepted use")
compat = (root / "scripts/netcoop-overlay/server/netcoop_server_compat.script").read_text(encoding="utf-8")
zone_lua = LuaRuntime(unpack_returned_tuples=True)
start = compat.index("local zone_players_installed")
end = compat.index("local function server_game_load", start)
zone_lua.execute(r'''
AC_ID=0;clsid={script_actor=1,actor=2,script_stalker=3}
function netcoop_actor_character(id)return (id==8 or id==9) and "tracked" or "" end
function entity(i,c,alive)
    return {id=function()return i end,clsid=function()return c end,alive=function()return alive end}
end
local veto,broken=false,false
function set_zone_mode(reject,raise)veto,broken=reject,raise end
function CCustomZone_BeforeActivateCallback(_,obj)
    if broken then error("zone callback failed") end
    if veto then return false end
    return obj:id()==AC_ID -- original pathfinding's player exception
end
''' + compat[start:end])
zone_lua.execute(r'''
local a=entity(8,clsid.script_actor,true)
local b=entity(9,clsid.script_actor,true)
local callback=CCustomZone_BeforeActivateCallback
assert(not callback(nil,a))
install_zone_players()
local wrapped=CCustomZone_BeforeActivateCallback
install_zone_players();assert(wrapped==CCustomZone_BeforeActivateCallback)
assert(wrapped(nil,a) and AC_ID==0)
AC_ID=8
assert(wrapped(nil,b) and AC_ID==8)
assert(not wrapped(nil,entity(10,clsid.script_actor,true)))
assert(not wrapped(nil,entity(11,clsid.actor,true)))
assert(not wrapped(nil,entity(9,clsid.script_actor,false)))
assert(not wrapped(nil,entity(12,clsid.script_stalker,true)))
assert(not wrapped(nil,entity(0,clsid.script_actor,true)))
set_zone_mode(true,false);assert(not wrapped(nil,b) and AC_ID==8)
set_zone_mode(false,true);local ok,err=pcall(wrapped,nil,b)
assert(not ok and err:find("zone callback failed",1,true) and AC_ID==8)
''')
print("PASS anomaly activation: tracked S_ACTOR gets its own AC_ID; NPC, dead, anchor and unrelated vetoes preserved")
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
cooperative = true; spawns = 0; initial = 0; quest = 0; callbacks = {}
function netcoop_enabled() return cooperative end
function printf() end
function RegisterScriptCallback(kind, fn) callbacks[kind] = fn end
state = {}
alife_storage_manager = {get_state = function() return state end}
db = {actor = {}}
xr_logic = {pick_section_from_condlist = function(_, _, value) return value end}
-- GAMMA's respawn: a section spawns while fewer of its squads are alive than its limit.
function gamma_respawn(self)
    for k, p in pairs(self.respawn_params) do
        if self.already_spawned[k].num < tonumber(p.num) then
            self.already_spawned[k].num = self.already_spawned[k].num + 1
            spawns = spawns + 1
            return
        end
    end
end
smart_terrain = {se_smart_terrain = {try_respawn = gamma_respawn}}
SIMBOARD = {create_squad = function() quest = quest + 1 end,
    fill_start_position = function() initial = initial + 1 end}
''')
lua.execute(source)
lua.execute(r'''
on_game_start()
local smart = {id = 7, respawn_params = {mutants = {num = "2"}, stalkers = {num = "1"}},
    already_spawned = {mutants = {num = 0}, stalkers = {num = 0}}}
for i = 1, 10 do smart_terrain.se_smart_terrain.try_respawn(smart) end
assert(spawns == 3, "the freeplay population fills once: " .. spawns)
-- Every squad dies: nothing is replenished.
smart.already_spawned.mutants.num = 0; smart.already_spawned.stalkers.num = 0
for i = 1, 10 do smart_terrain.se_smart_terrain.try_respawn(smart) end
assert(spawns == 3, "dead squads must not be replenished")
assert(smart.already_spawned.mutants.num == 0, "GAMMA's own counters are left as they were")
SIMBOARD.fill_start_position(); SIMBOARD.create_squad()
assert(initial == 1 and quest == 1, "initial and scripted squads retain their separate creation paths")
local wrapped = smart_terrain.se_smart_terrain.try_respawn
for i=1,10 do callbacks.on_game_load() end
assert(wrapped == smart_terrain.se_smart_terrain.try_respawn, "install is idempotent")
smart_terrain.se_smart_terrain.try_respawn = gamma_respawn
callbacks.on_game_load(); smart_terrain.se_smart_terrain.try_respawn(smart)
assert(spawns == 3, "guard survives a mod replacing the method on load")
cooperative = false
smart.already_spawned.mutants.num = 0
smart_terrain.se_smart_terrain.try_respawn(smart); assert(spawns == 4, "single-player retains original population policy")
''')
print("Actual server world rules: each smart section fills to its freeplay limit once, dead squads are not replaced, idempotent reload guard PASS")

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
cooperative = true; purged = 0; consumed = 0; timers = {}; callbacks = {}; artefacts = 0; npc_items = 0
function netcoop_enabled() return cooperative end
function printf() end
function RegisterScriptCallback(kind, fn) callbacks[kind] = fn end
function RemoveTimeEvent(id, name) timers[id .. name] = nil end
function CreateTimeEvent(id, name, fn) timers[id .. name] = fn end
release_item_manager = {clear = function() purged = purged + 1; return false end}
grok_artefact_despawner = {delete_artefacts = function(id) artefacts = artefacts + id; return id end}
release_npc_inventory = {clean_npc_inv = function(id) npc_items = npc_items + id; return id end}
function consume_item() consumed = consumed + 1 end
-- Simulate the base manager's earlier on_game_load callback capturing clear.
CreateTimeEvent(0, "release_item", release_item_manager.clear)
CreateTimeEvent(0, "unrelated_quest", consume_item)
''')
lua.execute(source)
lua.execute(r'''
on_game_start()
assert(not timers["0release_item"], "remove an already-queued original purge callback")
assert(timers["0unrelated_quest"], "leave other timers intact")
local guarded = release_item_manager.clear
for i=1,100 do assert(release_item_manager.clear() == true) end
assert(purged == 0, "dropped items have no age-based deletion")
local artefact_guard = grok_artefact_despawner.delete_artefacts
local inventory_guard = release_npc_inventory.clean_npc_inv
grok_artefact_despawner.delete_artefacts(7); release_npc_inventory.clean_npc_inv(9)
assert(artefacts == 0 and npc_items == 0, "floor artefacts and persistent NPC inventory are not age-purged")
for i=1,10 do install() end
assert(guarded == release_item_manager.clear, "item guard is idempotent")
assert(artefact_guard == grok_artefact_despawner.delete_artefacts and inventory_guard == release_npc_inventory.clean_npc_inv)
-- The base callback can also run after ours; it then captures the guard.
CreateTimeEvent(0, "release_item", release_item_manager.clear)
assert(timers["0release_item"]() == true and purged == 0)
release_item_manager.clear = function() purged = purged + 1; return false end
CreateTimeEvent(0, "release_item", release_item_manager.clear)
callbacks.on_game_load()
assert(not timers["0release_item"] and release_item_manager.clear() == true)
grok_artefact_despawner.delete_artefacts = function(id) artefacts = artefacts + id; return id end
callbacks.on_game_load(); grok_artefact_despawner.delete_artefacts(7); assert(artefacts == 0)
timers["0unrelated_quest"](); assert(consumed == 1)
cooperative = false
assert(release_item_manager.clear() == false and purged == 1,
       "single-player retains its original purge policy")
assert(grok_artefact_despawner.delete_artefacts(7) == 7 and artefacts == 7)
assert(release_npc_inventory.clean_npc_inv(9) == 9 and npc_items == 9)
''')
print("Actual dropped-item guard: old/new queued callbacks, reload replacement, consumption and unrelated timers PASS")

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
cooperative=true; callbacks={}; timers={}; spawn_reads=0; state_runs=0; other_runs=0
db={}
function netcoop_enabled() return cooperative end
function printf() end
function RegisterScriptCallback(kind,fn) callbacks[kind]=fn end
function RemoveTimeEvent(id,name) timers[id .. name]=nil end
function spawn_timer()
    spawn_reads=spawn_reads+1
    return db.actor:character_rank() -- reproduces GAMMA's actor-dependent timer
end
sim_squad_bounty={spawn_timer=spawn_timer,try_spawn=function() error('respawn forbidden') end,
    state_timer=function() state_runs=state_runs+1; return false end}
timers.cyclebounty_squad_spawn=sim_squad_bounty.spawn_timer -- captured before installation
timers.cyclebounty_squad_state=sim_squad_bounty.state_timer
timers.other=function() other_runs=other_runs+1 end
''')
lua.execute(source)
lua.execute(r'''
assert(not pcall(sim_squad_bounty.spawn_timer), 'unpatched nil actor timer reproduces failure')
spawn_reads=0; on_game_start()
assert(not timers.cyclebounty_squad_spawn, 'retire captured original spawn timer')
assert(timers.cyclebounty_squad_state and timers.other)
local guarded=sim_squad_bounty.spawn_timer
for i=1,10 do assert(guarded()==true); callbacks.on_game_load() end
assert(spawn_reads==0 and sim_squad_bounty.spawn_timer==guarded)
timers.cyclebounty_squad_spawn=guarded
assert(timers.cyclebounty_squad_spawn()==true, 'late registration retires itself')
timers.cyclebounty_squad_state(); timers.other(); assert(state_runs==1 and other_runs==1)
sim_squad_bounty.spawn_timer=spawn_timer
timers.cyclebounty_squad_spawn=spawn_timer; callbacks.on_game_load()
assert(not timers.cyclebounty_squad_spawn and sim_squad_bounty.spawn_timer()==true)
cooperative=false; db.actor={character_rank=function() return 777 end}
assert(sim_squad_bounty.spawn_timer()==777 and spawn_reads==1, 'single-player callback remains original')
''')
print('Actual world guard: old/late/replaced bounty spawn timers retired; existing squad state, unrelated timers and single-player callback preserved PASS')

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
function netcoop_enabled() return true end
function printf() end
function RegisterScriptCallback() end
state = {}; writes = {}; short_write = false; save_error = false
marshal = {encode = function(value) return "encoded-complete-snapshot" end}
original_encode = marshal.encode
io = {open = function(path, mode)
    if not writes[path] then return nil end
    return {read = function() return writes[path] end, close = function() return true end}
end}
function getFS() return {update_path = function() return "saves/" end} end
alife_storage_manager = {
    get_state = function() return state end,
    CALifeStorageManager_before_save = function(fname)
        local bytes = marshal.encode(state)
        if save_error then error("injected Lua save exception") end
        writes["saves/" .. fname:sub(0, -6):lower() .. ".scoc"] = short_write and bytes:sub(1, 4) or bytes
    end
}
''')
lua.execute(source)
lua.execute(r'''
on_game_start()
local save = alife_storage_manager.CALifeStorageManager_before_save
install(); assert(save == alife_storage_manager.CALifeStorageManager_before_save)
save("Zone_A.scop")
assert(marshal.encode == original_encode, "encoder restored after success")
assert(script_snapshot_matches("Zone_A"), "exact saved script bytes verified")
assert(not script_snapshot_matches("Zone_A"), "one capture cannot bless another save")
short_write = true; save("Zone_A.scop")
assert(not script_snapshot_matches("Zone_A"), "nonempty truncated script file rejected")
short_write = false; save("Zone_A.scop")
writes["saves/zone_a.scoc"] = "stale-snapshot"
assert(not script_snapshot_matches("Zone_A"), "same-slot stale state rejected")
save_error = true; assert(not pcall(save, "Zone_A.scop"))
assert(marshal.encode == original_encode, "encoder restored even when saver raises")
assert(not script_snapshot_matches("Zone_A"))
''')
print("Actual server script-save guard: full bytes, truncated/stale data, one-use capture, encoder restoration on exception PASS")

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
cooperative = true; spawned = 0; unregistered = {}; callbacks = {}
function netcoop_enabled() return cooperative end
function printf() end
function RegisterScriptCallback(kind, fn) callbacks[kind] = fn end
function UnregisterScriptCallback(kind, fn) unregistered[#unregistered + 1] = {kind, fn} end
local function spawn() spawned = spawned + 1 end
night_mutants = {try_to_spawn = spawn}
guards_spawner = {spawn_guard = spawn}
sim_squad_bounty = {try_spawn = spawn}
tasks_fate = {spawn_target = spawn}
''')
lua.execute(source)
lua.execute(r'''
on_game_start()
night_mutants.try_to_spawn(); guards_spawner.spawn_guard(); sim_squad_bounty.try_spawn()
assert(spawned == 0, "periodic spawners add nobody")
assert(#unregistered == 2 and unregistered[1][1] == "actor_on_update", "registered update callbacks removed")
tasks_fate.spawn_target(); assert(spawned == 1, "quest spawns unchanged")
local off = night_mutants.try_to_spawn
install(); assert(night_mutants.try_to_spawn == off and #unregistered == 2, "idempotent")
''')
print("Actual spawner guard: night mutants, base guards and bounty squads off, quest spawns unchanged PASS")

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
cooperative = true; callbacks = {}
function netcoop_enabled() return cooperative end
function printf() end
function RegisterScriptCallback(kind, fn) callbacks[kind] = fn end
local levels = {[10] = 1, [11] = 1, [20] = 2}
function game_graph() return {vertex = function(_, id) return {level_id = function() return levels[id] end} end} end
smart_terrain = {se_smart_terrain = {target_precondition = function(self, squad) return true end}}
sim_squad_scripted = {sim_squad_scripted = {target_precondition = function(self, squad) return true end}}
''')
lua.execute(source)
lua.execute(r'''
on_game_start()
local smart = smart_terrain.se_smart_terrain
local here, there, squad = {m_game_vertex_id = 11}, {m_game_vertex_id = 20}, {m_game_vertex_id = 10}
assert(smart.target_precondition(here, squad), "a target on the squad's map stays available")
assert(not smart.target_precondition(there, squad), "a target on another map is refused")
assert(not sim_squad_scripted.sim_squad_scripted.target_precondition(there, squad), "squad targets too")
local guarded = smart.target_precondition
install(); assert(smart.target_precondition == guarded, "idempotent")
cooperative = false
assert(smart.target_precondition(there, squad), "single-player keeps cross-map travel")
''')
print("Actual squad map guard: generic targets on other maps refused in coop, single-player unchanged PASS")

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
cooperative = true; callbacks = {}; released = {}; calls = {}; now = 0
function netcoop_enabled() return cooperative end
function printf() end
function time_global() return now end
function RegisterScriptCallback(kind, fn) callbacks[kind] = fn end
function AddUniqueCall(fn) calls[#calls + 1] = fn end
getFS = function() return {update_path = function() return "cluster.ltx" end} end
io = {open = function() return {close = function() end} end}
local names = {[1] = "k00_marsh", [2] = "l01_escape"}
function game_graph() return {vertex = function(_, gv) return {level_id = function() return gv end} end} end
squad_objects = {}
function alife() return {level_name = function(_, id) return names[id] end, object = function(_, id) return squad_objects[id] end} end
level = {name = function() return "k00_marsh" end}
store = {}
alife_storage_manager = {get_state = function() return store end}
story = {[30] = true}
function get_object_story_id(id) return story[id] end
function alife_release_id(id) released[#released + 1] = id end
function alife_release(se) released[#released + 1] = se.id end
function squad(id, gv, members)
    return {id = id, m_game_vertex_id = gv, squad_members = function()
        local i = 0
        return function() i = i + 1; return members[i] and {id = members[i]} end
    end}
end
SIMBOARD = {start_position_filled = false, squads = {}}
''')
lua.execute(source)
lua.execute(r'''
on_game_start()
assert(#released == 0 and #calls == 2, "a new world waits for its population (and online smarts get their updates)")
-- As in GAMMA: SIMBOARD.squads maps id -> true, the objects come from alife.
squad_objects = {[10] = squad(10, 1, {11, 12}), [20] = squad(20, 2, {21, 22}), [30] = squad(30, 2, {31})}
SIMBOARD.squads = {[10] = true, [20] = true, [30] = true}
SIMBOARD.start_position_filled = true
now = 6000
assert(calls[2]() == true)
local set = {}
for _, id in ipairs(released) do set[id] = true end
assert(set[20] and set[21] and set[22], "a generic squad of another map is released")
assert(not set[10] and not set[11] and not set[30] and not set[31], "own map and story squads stay")
local count = #released
install(); assert(#released == count, "once per world")
''')
print("Actual cluster population split: other maps' generic squads released once, own map and story squads kept PASS")
