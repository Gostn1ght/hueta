"""The weather editor's live changes reach everyone (owner 2026-10-23): the
actual blocks of netcoop_server_compat (weather_edit, its world tick) on two
location servers sharing one store, and of netcoop_client_compat (applying
the shared state). Values validated; an edit reaches both maps; a player
who comes later gets the state; unpausing gives everyone the server's sky."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
server_text = (root / "server/netcoop_server_compat.script").read_text(encoding="utf-8")
a = server_text.index("-- The weather editor's live changes")
b = server_text.index("local function server_world_tick()", a)
server_block = server_text[a:b] + "\nreturn weather_edit, weather_edit_tick\n"
client_text = (root / "client/netcoop_client_compat.script").read_bytes().decode("utf-8")
a = client_text.index("local edit_seq = nil")
b = client_text.index("-- A server dialogue action opened an NPC window", a)
client_block = client_text[a:b] + "\nreturn use_weather_edit\n"

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
sent = {}
function netcoop_broadcast(channel, data) sent[#sent + 1] = {server = current, channel = channel, data = data} end
''')
g.netcoop_transit = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_transit, (root / "server/netcoop_transit.script").read_text(encoding="utf-8"))
servers = []
for i in range(2):
    env = lua.eval("{}")
    lua.execute("local env = ...; local f = assert(loadstring(select(2, ...))); setfenv(f, setmetatable(env,{__index=_G})); _G.last_block = {f()}",
                env, server_block)
    servers.append(lua.eval("last_block"))
edit = [s[1] for s in servers]
tick = [s[2] for s in servers]

def run(server, now):
    g.current = server
    tick[server](now)

assert edit[0]("pause 1").startswith("*")
assert edit[0]("num fog_density 0.8").startswith("*")
assert edit[0]("vec sky_color 0.1 0.2 0.3").startswith("*")
assert edit[0]("vec hemisphere_color 1 1 1 0.5").startswith("*")
assert edit[0](r"str sky_texture sky\sky_9_cube").startswith("!")
assert edit[0]("sun 18 30").startswith("*")
for bad in ("num fog_density nan", "num fog_density 1e400", "vec sky_color 1 2", "str sky_texture a b", "num bad;name 1",
            "sun 25 0", "pause 2", "spawn x", "num fog_density 1.1", "num rain_density -1", "num far_plane 0", "vec sky_color -1 1 1", "num unknown 1"):
    assert edit[0](bad).startswith("!"), bad
run(0, 10000); run(1, 10000)
got = [x for x in lua.eval("sent").values() if x.channel == "weather_edit"]
assert {x.server for x in got} == {0, 1}, "both maps send the editor's state"
state = lua.eval("netcoop_transit.deserialize(netcoop_store_read('weather_edit', 'zone'))")
assert state.paused and state['values'].fog_density[1] == 0.8 and state['values'].sky_color.k == "v" and state.sun.h == 18
assert state['values'].hemisphere_color[4] == 0.5 and state['values'].sky_texture is None

# A client applies it once per change.
calls = lua.eval("{}")
g.calls = calls
lua.execute(r'''
applied = {}
engine_weather = {
    pause = function(on) applied[#applied + 1] = "pause " .. tostring(on) end,
    sun_time = function(h, m) applied[#applied + 1] = "sun " .. h .. ":" .. m end,
    set_value_numric = function(p, v) applied[#applied + 1] = "num " .. p .. " " .. v end,
    set_value_vector = function(p, x, y, z, w) applied[#applied + 1] = "vec " .. p .. " " .. tostring(w) end,
    set_value_string = function(p, v) applied[#applied + 1] = "str " .. p .. " " .. v end}
server_weather = "w_clear1"
skies = {}
engine_set_weather = function(name, now) skies[#skies + 1] = name .. tostring(now) end
netcoop_pdanet_client = {decode = function(text) return netcoop_transit.deserialize(text) end}
''')
lua.execute("local f = assert(loadstring(...)); setfenv(f, _G); _G.use_edit = f()", client_block)
use = g.use_edit
text = lua.eval("netcoop_store_read('weather_edit', 'zone')")
use(text)
applied = list(lua.eval("applied").values())
assert applied[0] == "pause true" and "sun 18:30" in applied and "num fog_density 0.8" in applied
assert "vec hemisphere_color 0.5" in applied and "vec sky_color nil" in applied and not any(x.startswith("str ") for x in applied)
use(text)
assert len(lua.eval("applied")) == len(applied), "the same state is applied once"
assert lua.eval("applying_server_weather") is False

# A later player gets the state from the periodic send; unpausing clears it.
lua.execute("sent = {}")
run(1, 16000)
assert any(x.channel == "weather_edit" for x in lua.eval("sent").values()), "resent for players who came later"
assert edit[1]("pause 0").startswith("*")
state = lua.eval("netcoop_transit.deserialize(netcoop_store_read('weather_edit', 'zone'))")
assert not state.paused and next(iter(state['values'].keys()), None) is None and state.sun is None
use(lua.eval("netcoop_store_read('weather_edit', 'zone')"))
assert list(lua.eval("applied").values())[-1] == "pause false" and list(lua.eval("skies").values()) == ["w_clear1true"]
print("PASS weather editor: validated values, shared store, both maps, late players, applied once, unpause restores the sky")
