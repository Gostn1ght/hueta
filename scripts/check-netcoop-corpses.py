"""Corpses (owner 2026-10-06): the actual netcoop_corpses script. Removed with
their loot on a server restart and after 40 minutes without a player near."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
clock = 1000000
os = {time = function() return clock end}
tick = 0
function time_global() return tick end
function printf() end
state = {}
alife_storage_manager = {get_state = function() return state end}
objects, players, story = {}, {}, {}
reserved = {}
netcoop_survival = {protected_body = function(id) return reserved[id] == true end}
db = {storage = {}}
function pos(x) return {x = x, distance_to_sqr = function(self, o) return (self.x - o.x)^2 end} end
function corpse(id, x) objects[id] = {id = id, position = pos(x), online = true, alive = function() return false end,
    clsid = function() return 1 end, m_game_vertex_id = 1, switch_offline = function(self) self.online = false end} end
function item(id, parent) objects[id] = {id = id, parent_id = parent, clsid = function() return 2 end} end
sim = {object = function(_, id) return objects[id] end, level_name = function() return "k00_marsh" end,
    set_switch_online = function() end, set_switch_offline = function() end,
    release = function(_, se) objects[se.id] = nil end}
function alife() return sim end
function game_graph() return {vertex = function() return {level_id = function() return 1 end} end} end
level = {name = function() return "k00_marsh" end, object_by_id = function(id)
    if players[id] then return {position = function() return players[id] end} end end}
function netcoop_players() local t = {} for id in pairs(players) do t[#t + 1] = id end return table.concat(t, " ") end
function IsStalker(_, cls) return cls == 1 end
clsid = {actor = 100, script_actor = 101}
function IsMonster() return false end
function get_object_story_id(id) return story[id] end
''')
g = lua.globals()
g.netcoop_corpses = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_corpses, (root / "scripts/netcoop-overlay/server/netcoop_corpses.script").read_text(encoding="ascii"))
lua.execute(r'''
local c = netcoop_corpses
local function frames(n) for _ = 1, n do c.update() end end
-- A server start removes the saved world's corpses (with their loot), not story ones.
corpse(10, 0); item(11, 10); item(12, 10); corpse(20, 50); story[20] = "story_guy"; item(30, 65535)
frames(3)
assert(not objects[10] and not objects[11] and not objects[12], "restart: corpse and its loot removed")
assert(objects[20], "restart: story corpse stays")
assert(objects[30], "items lying in the world stay")
-- While running: 40 minutes without a player near.
corpse(40, 0); item(41, 40); state.netcoop_corpses[40] = clock
players[1] = pos(30)                              -- a player 30 m away
clock = clock + 39 * 60; tick = tick + 31000; frames(2)
assert(objects[40], "kept before 40 minutes")
clock = clock + 2 * 60; tick = tick + 31000; frames(2)
assert(objects[40], "a player near restarts the count")
players[1] = nil
clock = clock + 39 * 60; tick = tick + 31000; frames(2)
assert(objects[40], "39 minutes after the player left: kept")
clock = clock + 2 * 60; tick = tick + 31000; frames(3)
assert(not objects[40] and not objects[41], "40 minutes alone: removed with its loot")
-- A reservation acquired after enqueue must be checked again at deletion.
corpse(50,0); item(51,50); state.netcoop_corpses[50] = clock - c.corpse_time - 1
tick=tick+31000;frames(1) -- selected for cleanup, not deleted yet
assert(objects[50] and objects[51])
reserved[50]=true;frames(2)
assert(objects[50] and objects[51], "late survival reservation preserves corpse and original items")
reserved[50]=nil;tick=tick+31000;frames(3)
assert(not objects[50] and not objects[51], "after reservation ends normal cleanup resumes")
corpse(60,0);item(61,60);state.netcoop_corpses[60]=clock-c.corpse_time-1
tick=tick+31000;frames(1);story[60]="late_story";frames(2)
assert(objects[60] and objects[61], "late story protection also cancels queued deletion")
''')
print("Corpses: removed with their loot on a server restart and after 40 min without a player within 100 m (a visit restarts the count); story corpses and world items stay; late survival/story protection cancels queued deletion PASS")
