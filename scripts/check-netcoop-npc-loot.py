"""NPCs searching corpses on the server (actual netcoop_npc_loot, Lua 5.1).
GAMMA takes every lootable item at once (callback npc_on_get_all_from_corpse
before each transfer); right after the search the NPC gives back the least
valuable of those items until it is within GAMMA's 30 kg; an NPC with room
keeps all; items it had before stay; GAMMA's "not near the actor" counts
living players, not the server's own Actor."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
lua.execute(r'''
function printf() end
function netcoop_enabled() return true end
function netcoop_pure_client() return false end
callbacks = {}
function RegisterScriptCallback(n, f) callbacks[n] = f end
queue = {}
function CreateTimeEvent(ev, act, t, f, ...) local k = ev .. act; if not queue[k] then queue[k] = {f = f, p = {...}} end end
function run_events() for k, e in pairs(queue) do if e.f(unpack(e.p)) then queue[k] = nil end end end
objects = {}
local function distance_squared(a, b) return (a.x - b.x) ^ 2 + (a.z - b.z) ^ 2 end
function vec(x, z)
  return {x=x, z=z, distance_to_sqr=distance_squared, distance_to=function(a,b) return math.sqrt(distance_squared(a,b)) end}
end
function make(id, extra)
  local o = {_id = id, _alive = false, _pos = vec(0, 0)}
  for k, v in pairs(extra or {}) do o[k] = v end
  function o:id() return self._id end
  function o:name() return "obj" .. self._id end
  function o:alive() return self._alive end
  function o:position() return self._pos end
  function o:parent() return self._parent and objects[self._parent] end
  function o:cost() return self._cost or 0 end
  function o:condition() return self._cond or 1 end
  function o:weight() return self._w or 0 end
  function o:get_total_weight()
    local w = 0
    for _, it in pairs(objects) do if it._parent == self._id then w = w + it._w end end
    return w
  end
  function o:transfer_item(it, to) if to:id() ~= it._refused then it._parent = to:id() end end
  function o:section() return self._section or "item" end
  function o:clsid() return self._class or 1 end
  function o:is_monster() return self._monster == true end
  function o:iterate_inventory(fn, context)
    for _, it in pairs(objects) do if it._parent == id then fn(context, it) end end
  end
  objects[id] = o
  return o
end
level = {object_by_id = function(id) return objects[id] end}
function alife_object(id) return objects[id] and {parent_id=objects[id]._parent} end
''')
mod = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            mod, (root / "server/netcoop_npc_loot.script").read_text(encoding="utf-8"))
lua.execute(r'''
clsid = {actor=2, script_actor=3}
function IsStalker(obj) return not obj:is_monster() end
db = {storage={}}
local original = function() error("stock handler needs player") end
local function captured() return {into={[0]={"animation", {f=original}}}} end
state_mgr_animation_list = {animations={search_corpse=captured(), field_dress=captured()}}
valuable, vars, stats = {}, {}, {}
xr_corpse_detection = {
    get_all_from_corpse=original,
    lootable_table={item=true},
    set_valuable_loot=function(id,v) valuable[id]=v end,
}
xr_gather_items = {}
function SendScriptCallback(name, ...) callbacks[name](...) end
function load_var(npc,key) return vars[npc:id()] end
function save_var(npc,key,v) assert(key == "s_loot_count"); vars[npc:id()]=v end
game_statistics = {increment_npc_statistic=function(npc,key)
    assert(key=="corpse_looted"); stats[npc:id()]=(stats[npc:id()] or 0)+1
end}
''')
mod.on_game_start()
on_get = g.callbacks.npc_on_get_all_from_corpse
make = lua.eval("make")

def item(i, parent, w, cost, cond=1):
    return make(i, lua.table_from({"_parent": parent, "_w": w, "_cost": cost, "_cond": cond}))

def gamma_search(npc, corpse):
    """GAMMA's get_all_from_corpse: callback, then transfer, for each lootable item."""
    for it in sorted([o for o in g.objects.values() if o._parent == corpse._id], key=lambda o: o._id):
        on_get(npc, corpse, it, True)
        corpse.transfer_item(corpse, it, npc)

npc = make(1, lua.table_from({"_alive": True}))
corpse = make(2)
item(10, 1, 20, 1000)            # what the NPC carried before (20 kg)
item(20, 2, 4, 3000)             # rifle: valuable
item(21, 2, 4, 50)               # junk
item(22, 2, 3, 900, 0.5)         # value 450
item(23, 2, 2, 400)              # value 400
item(24, 2, 5, 100)              # value 100
gamma_search(npc, corpse)
assert npc.get_total_weight(npc) == 38
g.run_events()
# within 30 kg; the cheapest went back first (junk 50, then 100), the rest kept
kept = sorted(o._id for o in g.objects.values() if o._parent == 1)
back = sorted(o._id for o in g.objects.values() if o._parent == 2)
assert kept == [10, 20, 22, 23] and back == [21, 24], (kept, back)
assert npc.get_total_weight(npc) <= 30
# an NPC with room keeps everything
npc2 = make(3, lua.table_from({"_alive": True}))
corpse2 = make(4)
item(30, 4, 2, 10); item(31, 4, 3, 20)
gamma_search(npc2, corpse2)
g.run_events()
assert all(g.objects[i]._parent == 3 for i in (30, 31))
# not lootable: not counted
on_get(npc2, corpse2, g.objects[30], False)
assert len(list(g.queue.keys())) == 0

# "not near the actor" = any living player within the option's distance
lua.execute("""
ui_options = {get = function() return '10' end}
local p = make(100, {_alive = true, _pos = vec(5, 0)})
function netcoop_players() return '100' end
""")
near = make(200, lua.table_from({"_pos": g.vec(9, 0)}))
far = make(201, lua.table_from({"_pos": g.vec(40, 0)}))
assert g.xr_corpse_detection.near_actor(near) is True and g.xr_gather_items.near_actor(far) is False
lua.execute("objects[100]._alive = false")
assert mod.near_player(near) is False
lua.execute("ui_options = {get = function() return '0' end}; objects[100]._alive = true")
assert mod.near_player(near) is False
print("NPC corpse search: 30 kg like GAMMA, least valuable left first, players count as the actor: PASS")

lua.execute(r'''
local animation = state_mgr_animation_list.animations
local search = animation.search_corpse.into[0][2].f
local dress = animation.field_dress.into[0][2].f
assert(search == xr_corpse_detection.get_all_from_corpse and dress == search)
local npc = make(60, {_alive=true, _pos=vec(4, 0)})
local corpse = make(61, {_pos=vec(5, 0)})
make(59, {_parent=60, _w=27})
local ordinary = make(62, {_parent=61, _w=3, _cost=1000})
local quest = make(63, {_parent=61, _w=1, _section="quest"})
local rejected = make(64, {_parent=61, _w=1, _refused=60})
local excess = make(68, {_parent=61, _w=2, _cost=1})
local function select_body(id)
    db.storage[id] = {object=objects[id], corpse_already_selected=60}
    local state = {selected_corpse_id=id, __stimer=100, nearest_id=id}
    db.storage[60] = {corpse_detection=state}
    return state
end
local state = select_body(61)
assert(db.actor == nil)
search(npc)
assert(not state.selected_corpse_id and not state.__stimer and not db.storage[61].corpse_already_selected)
assert(ordinary._parent == 60 and quest._parent == 61 and rejected._parent == 61)
assert(excess._parent == 60 and npc:get_total_weight() == 32)
run_events()
assert(excess._parent == 61 and ordinary._parent == 60 and npc:get_total_weight() == 30)
assert(valuable[61] == false and vars[60] == 1 and stats[60] == 1)
search(npc)
assert(stats[60] == 1)
local mutant = make(65, {_pos=vec(5, 0), _monster=true})
local calls = 0
netcoop_mutant_loot = {npc_take=function(who,body)
    assert(who == npc and body == mutant and not db.actor)
    calls = calls+1
end}
select_body(65)
dress(npc)
assert(calls == 1)
mutant._pos = vec(9, 0)
select_body(65)
search(npc)
assert(calls == 1)
mutant._pos = vec(5, 0)
ui_options = {get=function() return '10' end}
select_body(65)
search(npc)
assert(calls == 1)
ui_options = {get=function() return '0' end}
local player_body = make(66, {_class=clsid.script_actor, _pos=vec(5, 0)})
local saved = make(67, {_parent=66, _w=2})
select_body(66)
search(npc)
assert(saved._parent == 66 and stats[60] == 1)
''')
print("PASS dedicated corpse completion and both animation callbacks work without a player context")
