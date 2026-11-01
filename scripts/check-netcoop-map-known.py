"""Places a player has found on the PDA map (owner 2026-10-24): the actual
netcoop_map_known (server) and the client handler of netcoop_client_compat.
A changer, a named place and an anomaly field open only near the player,
belong to the character (shared store: a relog or another server gets them,
nothing depends on the PDA), are sent once per session, and the client puts
them on the map with a name in its own language."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
lua.execute(r'''
store = {}
function netcoop_store_read(b, k) return (store[b] or {})[k] or "" end
function netcoop_store_swap(b, k, old, new)
    store[b] = store[b] or {}
    if (store[b][k] or "") ~= old then return false end
    store[b][k] = new ~= "" and new or nil
    return true
end
tg = 0
function time_global() return tg end
function printf() end
local V = {}
V.__index = V
function vector() return setmetatable({x = 0, y = 0, z = 0}, V) end
function V:set(x, y, z) self.x, self.y, self.z = x, y, z return self end
function V:add(o) self.x, self.y, self.z = self.x + o.x, self.y + o.y, self.z + o.z return self end
function V:div(n) self.x, self.y, self.z = self.x / n, self.y / n, self.z / n return self end
function V:distance_to(o) return math.sqrt((self.x - o.x)^2 + (self.y - o.y)^2 + (self.z - o.z)^2) end
local function at(x, z) return vector():set(x, 0, z) end
clsid = {level_changer_s = 1, level_changer = 2, smart_terrain = 3}
objects = {
    [10] = {cls = 1, name = "esc_changer_to_garbage", position = at(500, 0), level = "l01_escape", dest = "l02_garbage"},
    [11] = {cls = 1, name = "esc_changer_to_marsh", position = at(-500, 0), level = "l01_escape", dest = "k00_marsh"},
    [12] = {cls = 1, name = "gar_changer", position = at(0, 0), level = "l02_garbage", dest = "l01_escape"},
}
for id, o in pairs(objects) do
    o.id = id
    o.clsid = function() return o.cls end
    o.name = (function(n) return function() return n end end)(o.name)
    o.m_game_vertex_id = o.level
end
function alife() return {object = function(_, id) return objects[id] end, level_name = function(_, l) return l end} end
function game_graph() return {vertex = function(_, v) return {level_id = function() return v end} end} end
utils_stpk = {get_level_changer_data = function(se) return {dest_level_name = se.dest} end}
local village = {id = 20, position = at(0, 300), m_game_vertex_id = "l01_escape", name = function() return "esc_smart_terrain_village" end}
local hidden = {id = 21, position = at(0, -300), m_game_vertex_id = "l01_escape", name = function() return "esc_unnamed" end}
SIMBOARD = {smarts = {[20] = {smrt = village}, [21] = {smrt = hidden}}}
function ini_file() return {
    section_exist = function(_, s) return s == "l01_escape" end,
    line_count = function() return 1 end,
    r_line = function() return true, "esc_smart_terrain_village", "st_esc_village_name" end} end
db = {anomaly_by_name = {esc_zone_field_acidic_1 = {object = {id = function() return 30 end, position = function() return at(200, 200) end}}}}
level = {name = function() return "l01_escape" end, object_by_id = function(id) return players[id] and players[id].actor end}
players = {}
function netcoop_players() local t = {} for id in pairs(players) do t[#t + 1] = id end table.sort(t) return table.concat(t, ",") end
function netcoop_actor_character(id) return players[id] and players[id].char or "" end
netcoop_pdanet={held_device=function(id,char) return {uid=players[id].uid or char.."-pda",own=true} end}
inbox = {}
function netcoop_send_to_actor(id, ch, data) assert(ch == "map_known"); inbox[id] = (inbox[id] or "") .. data .. "\n" end
function join(id, char, x, z)
    local p = {char = char, pos = at(x, z)}
    p.actor = {position = function() return p.pos end}
    players[id] = p
end
function step() tg = tg + 3000; netcoop_map_known.update_world() end
''')
g.netcoop_transit = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_transit, (root / "server/netcoop_transit.script").read_text(encoding="utf-8"))
g.netcoop_map_known = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_map_known, (root / "server/netcoop_map_known.script").read_text(encoding="utf-8"))

def inbox(pid):
    text = lua.eval("inbox[%d] or ''" % pid)
    lua.execute("inbox[%d] = nil" % pid)
    return [l for l in text.split("\n") if l]

lua.execute('join(1, "a_1", 0, 0)')
lua.eval("step()")
assert sorted(row.split()[0] for row in inbox(1)) == ["10", "11"], "both level transitions visible immediately"
lua.execute('players[1].pos = vector():set(480, 0, 10)')  # at the Garbage changer
lua.eval("step()")
got = inbox(1)
assert got == [], "transitions already sent at spawn"
lua.eval("step()")
assert inbox(1) == [], "sent once per session"
lua.execute('players[1].pos = vector():set(10, 0, 290)')  # the named village
lua.eval("step()")
assert inbox(1) == ["20 0.0 0.0 300.0 blue_location p|st_esc_village_name"]
lua.execute('players[1].pos = vector():set(0, 0, -290)')  # a smart with no name: not a place
lua.eval("step()")
assert inbox(1) == []
lua.execute('players[1].pos = vector():set(190, 0, 190)')  # the acid field
lua.execute("tg = tg + 15000"); lua.eval("step()")
assert "30 200.0 0.0 200.0 circle_empty a|chemical" in inbox(1)
# A relog (another session, any PDA): everything known comes back at once.
lua.execute('players[1] = nil'); lua.eval("step()")
lua.execute('join(7, "a_1", -100, -100)'); lua.eval("step()")
assert sorted(l.split()[0] for l in inbox(7)) == ["10", "11", "20", "30"]
# Another character knows nothing.
lua.execute('join(8, "b_1", -100, -100)'); lua.eval("step()")
assert sorted(row.split()[0] for row in inbox(8)) == ["10", "11"]
known = lua.eval("netcoop_transit.deserialize(store.map_known['a_1-pda'])")
assert sorted(known["l01_escape"].keys()) == ["a:esc_zone_field_acidic_1", "p:esc_smart_terrain_village"]

# The client: position for the id, a spot with a name in its own language.
client = (root / "client/netcoop_client_compat.script").read_bytes().decode("utf-8")
a = client.index("local MAP_KINDS"); b = client.index("-- A server dialogue action opened an NPC window", a)
lua.execute(r'''
positions, spots = {}, {}
function netcoop_map_position_set(id, x, y, z, l) positions[id] = {x, y, z, l} end
level.map_has_object_spot = function(id, spot) return spots[id .. spot] and 1 or 0 end
level.map_remove_object_spot=function(id,spot) spots[id..spot]=nil end
level.map_add_object_spot_ser = function(id, spot, hint) spots[id .. spot] = hint end
game = {translate_string = function(s)
    local t = {st_lz_map_changer = "Переход: %s", l02_garbage = "Свалка", st_lz_map_anomaly = "Аномальное поле: %s",
               st_lz_anomaly_chemical = "химическое", st_esc_village_name = "Деревня новичков"}
    return t[s] or s end}
''')
lua.execute("local f = assert(loadstring(...)); setfenv(f, _G); _G.use_map_known = f()", client[a:b] + "\nreturn use_map_known\n")
g.use_map_known("10 480.0 0.0 0.0 level_changer_right c|l02_garbage\n20 0.0 0.0 300.0 blue_location p|st_esc_village_name\n"
                "30 200.0 0.0 200.0 circle_empty a|chemical\nbad line\n99999 1 2 3 x c|y")
assert lua.eval("spots['10level_changer_right']") == "Переход: Свалка"
assert lua.eval("spots['20blue_location']") == "Деревня новичков"
assert lua.eval("spots['30circle_empty']") == "Аномальное поле: химическое"
assert lua.eval("positions[30][4]") == "l01_escape" and lua.eval("positions[99999]") is None
print("PASS map places: found only near, per character in the shared store, once per session, relog restores, client spots named")

# Switching to an empty physical PDA removes discoveries; no player-owned fallback.
lua.execute('players[7].uid="replacement";inbox[7]=nil;step()')
assert "clear" in inbox(7)
print("PASS transitions always visible, map discoveries owned by PDA UID and periodically resent")
