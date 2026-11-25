"""Mutant butchering online (actual netcoop_mutant_loot server module and
netcoop_mutant_loot_view client adapter, Lua 5.1): the server rolls GAMMA's
parts once per body and keeps them; a decayed, already looted, living or
non-mutant body gives nothing; taking checks the counts against the server's
list, creates the parts for the player with GAMMA's condition rule, wears the
knife, marks the body looted when empty; the client window shows the server's
list and sends the chosen counts in the server's order."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
lua.execute(r'''
store = {}
function se_save_var(id, name, var, val) store[id] = store[id] or {}; store[id][var] = val end
function se_load_var(id, name, var) return store[id] and store[id][var] end
now = 1000
local time_mt = {}
time_mt.__index = time_mt
function time_mt:diffSec(o) return self.v - o.v end
game = {get_game_time = function() return setmetatable({v = now}, time_mt) end}
function ini_file() return {r_float_ex = function() return 7200 end} end
db = {storage = {}}
rolls = 0
ui_mutant_loot = {loot_mutant = function(sec, cls, loot, npc, dont_create, victim)
    rolls = rolls + 1
    loot.mutant_part_dog_tail = {count = 1}
    loot.meat_dog = {count = 2}
end}
knife = 0
item_knife = {degradate = function() knife = knife + 1 end}
made = {}
function alife_create_item(sec, actor, props)
    assert(props.cond_ct == "part")
    if fail_after and #made >= fail_after then return nil end
    made[#made + 1] = sec
    return {id = 100+#made}
end
sent = {}
function netcoop_send_to_actor(id, ch, data) sent[#sent + 1] = {id, ch, data} end
valuable = {}
xr_corpse_detection = {set_valuable_loot = function(id, v) valuable[id] = v end}
clsid = {crow = 99}
function body(id, alive, monster)
    local o = {}
    function o:id() return id end
    function o:name() return "body" .. id end
    function o:section() return "dog_weak" end
    function o:clsid() return 1 end
    function o:alive() return alive end
    function o:is_monster() return monster end
    return o
end
held = {section=function() return 'wpn_knife3' end, condition=function() return 1 end,
 set_condition=function() knife=knife+1 end}
player = {id = function() return 7 end,active_item=function() return held end}
db.actor=player
game.translate_string=function(s) return s end
''')
g.netcoop_butchering = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_butchering, (root / "server/netcoop_butchering.script").read_text(encoding="utf-8"))
assert (root/'server/netcoop_butchering.script').read_bytes() == (root/'client/netcoop_butchering.script').read_bytes()
g.netcoop_mutant_loot = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_mutant_loot, (root / "server/netcoop_mutant_loot.script").read_text(encoding="utf-8"))
act = g.netcoop_mutant_loot.action
last = lambda: lua.eval("sent[#sent][3]")

lua.execute('''
local real_knife=held
local corpse=body(60,false,true)
local function denied(reason)
 local before=rolls;assert(netcoop_mutant_loot.action(player,corpse,'mloot_open')==reason and rolls==before)
end
held=nil;denied('st_body_knife_needed')
held={section=function() return 'wpn_axe' end};denied('st_body_knife_needed')
held={section=function() return 'wpn_knife2' end,condition=function() return .14 end};denied('st_body_knife_bad')
held.condition=function() return 1 end
corpse.section=function() return 'chimera_strong' end;denied('st_body_knife_weak')
corpse.section=function() return 'gigant_normal' end;denied('st_body_knife_weak')
held=real_knife
''')

lua.execute("dog = body(10, false, true); db.storage[10] = {death_time = setmetatable({v = 900}, getmetatable(game.get_game_time()))}")
assert act(g.player, g.dog, "mloot_open") == "" and last() == "10|ok|meat_dog*2;mutant_part_dog_tail*1"
assert act(g.player, g.dog, "mloot_open") == "" and g.rolls == 1  # rolled once, kept with the body
# Take: counts in the server's order (meat_dog, tail).
assert act(g.player, g.dog, "mloot_take 3,0") == "the list changed"
assert act(g.player, g.dog, "mloot_take 1") == "the list changed"
assert act(g.player, g.dog, "mloot_take 0,0") == "nothing selected"
assert act(g.player, g.dog, "mloot_take 1,1") == ""
assert list(g.made.values()) == ["meat_dog", "mutant_part_dog_tail"] or sorted(g.made.values()) == ["meat_dog", "mutant_part_dog_tail"]
assert g.knife == 2 and last() == "10|ok|meat_dog*1" and g.valuable[10] is True
assert lua.eval("store[10].looted") is False
assert act(g.player, g.dog, "mloot_take all") == "" and last() == "10|empty|"
assert lua.eval("store[10].looted") is True and g.valuable[10] is False
assert act(g.player, g.dog, "mloot_open") == "" and last() == "10|empty|"
# Decayed, looted by an NPC, alive, not a mutant.
lua.execute("old = body(11, false, true); db.storage[11] = {death_time = setmetatable({v = -9000}, getmetatable(game.get_game_time()))}")
assert act(g.player, g.old, "mloot_open") == "" and last() == "11|decayed|"
lua.execute("npc_looted = body(12, false, true); store[12] = {looted = true}")
assert act(g.player, g.npc_looted, "mloot_open") == "" and last() == "12|empty|"
assert act(g.player, lua.eval("body(13, true, true)"), "mloot_open") == "this is not a mutant body"
assert act(g.player, lua.eval("body(14, false, false)"), "mloot_open") == "this is not a mutant body"
assert g.rolls == 1

# Real creation failures preserve uncreated parts and wear only successful cuts.
lua.execute('fresh = body(15, false, true)')
assert act(g.player, g.fresh, "mloot_open") == ""
lua.execute("saved_knife=held;held=nil")
assert act(g.player, g.fresh, "mloot_take all") == "st_body_knife_needed"
lua.execute("held=saved_knife")
before, knife_before = len(g.made), g.knife
g.fail_after = before
assert act(g.player, g.fresh, "mloot_take all") == "item creation failed; parts remain on the body"
assert len(g.made) == before and g.knife == knife_before
assert lua.eval('store[15].netcoop_mutant_loot.meat_dog.count') == 2
g.fail_after = before+1
assert act(g.player, g.fresh, "mloot_take all") == "item creation failed; remaining parts stay on the body"
assert len(g.made) == before+1 and g.knife == knife_before+1
assert lua.eval('store[15].netcoop_mutant_loot.meat_dog.count') == 1
assert lua.eval('store[15].looted') is False
g.fail_after = None
assert act(g.player, g.fresh, "mloot_take all") == ""
assert len(g.made) == before+3 and g.knife == knife_before+3
assert lua.eval('store[15].looted') is True

lua.execute('''
-- Every GAMMA knife class, both heavy mutants, and the exact wear boundary.
local original=held
for i=1,9 do
 local name=i==1 and 'wpn_knife' or 'wpn_knife'..i
 held={section=function() return name end,condition=function() return .15 end}
 assert(netcoop_butchering.check(player,'dog_weak')==nil)
 for _,mutant in ipairs({'chimera_strong','gigant_normal'}) do
  assert(netcoop_butchering.check(player,mutant)==(i<=2 and 'st_body_knife_weak' or nil))
 end
end
local condition=.15
held={section=function() return 'wpn_knife3' end,condition=function() return condition end,
 set_condition=function(_,v) condition=v end}
local fresh=body(70,false,true)
assert(netcoop_mutant_loot.action(player,fresh,'mloot_open')=='')
local before=#made
assert(netcoop_mutant_loot.action(player,fresh,'mloot_take all')=='st_body_knife_bad')
assert(#made==before+1 and math.abs(condition-.14)<.000001)
assert(store[70].netcoop_mutant_loot.meat_dog.count==1)
assert(store[70].netcoop_mutant_loot.mutant_part_dog_tail.count==1 and not store[70].looted)
held=original
assert(netcoop_mutant_loot.action(player,fresh,'mloot_take all')=='' and #made==before+3)
assert(store[70].looted)
''')

lua.execute(r'''
local npc = {id=function() return 69 end, alive=function() return true end, get_total_weight=function() return 29 end}
local original_roll, original_spawn = ui_mutant_loot.loot_mutant, alife_create_item
local roll_count, spawned = 0, 0
function printf() end
ini_sys = {r_float_ex=function(_, _, key) assert(key == "inv_weight"); return 0.6 end}
ui_mutant_loot.loot_mutant = function(sec, cls, loot, who, dont_create)
    assert(who == npc and db.actor == npc and dont_create)
    roll_count = roll_count + 1
    loot.meat_dog = {count = 3}
end
local spawn_fails = true
function alife_create_item(sec, who, props)
    assert(sec == "meat_dog" and who == npc and props.cond_ct == "part")
    if spawn_fails then return nil end
    spawned = spawned + 1
    return {id=110+spawned}
end
local fresh = body(73, false, true)
netcoop_mutant_loot.npc_take(npc, fresh)
assert(db.actor == player and roll_count == 1 and spawned == 0 and valuable[73] == true)
assert(store[73].netcoop_mutant_loot.meat_dog.count == 3)
spawn_fails = false
netcoop_mutant_loot.npc_take(npc, fresh)
assert(db.actor == player and roll_count == 1 and spawned == 1)
assert(store[73].netcoop_mutant_loot.meat_dog.count == 2 and valuable[73] == true)
assert(netcoop_mutant_loot.action(player, fresh, "mloot_open") == "")
assert(sent[#sent][3] == "73|ok|meat_dog*2")
npc.get_total_weight=function() return 26 end
netcoop_mutant_loot.npc_take(npc, fresh)
assert(roll_count == 1 and spawned == 3 and store[73].looted and not valuable[73])
netcoop_mutant_loot.npc_take(npc, fresh)
assert(spawned == 3)
ui_mutant_loot.loot_mutant = function() error("roll failed") end
netcoop_mutant_loot.npc_take(npc, body(71, false, true))
assert(db.actor == player and not store[71])
ui_mutant_loot.loot_mutant, alife_create_item = original_roll, original_spawn
''')
print("PASS NPC and player share one mutant loot roll, failed spawn preserves parts, NPC respects carry limit")

# Client window.
lua.execute(r'''
requests = {}
function netcoop_item_action(kind, id, target, action) requests[#requests + 1] = {kind, id, target, action} end
msgs = {}
actor_menu = {set_msg = function(_, m) msgs[#msgs + 1] = m end}
game.translate_string = function(s) return s end
UI = {}
UI.__index = UI
function UI.new() return setmetatable({shown = false}, UI) end
function UI:IsShown() return self.shown end
function UI:ShowDialog() self.shown = true end
function UI:Reset(obj) self.id = obj:id(); return self:FillList() end
reinit = nil
-- GAMMA's window class: instances read methods from UI, the adapter writes them there.
ui_mutant_loot = {}
ui_mutant_loot.UIMutantLoot = setmetatable({}, {__call = function() local u = UI.new(); u.CC = {cell = {}, Reinit = function(_, inv) reinit = inv end}; return u end, __index = UI, __newindex = UI})
registered = 0
function Register_UI() registered = registered + 1 end
level = {object_by_id = function(id) return body(id, false, true) end}
''')
g.netcoop_mutant_loot_view = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_mutant_loot_view, (root / "client/netcoop_mutant_loot_view.script").read_text(encoding="utf-8"))
lua.execute(r'''
netcoop_mutant_loot_view.install()
ui_mutant_loot.start(body(20, false, true))
assert(requests[1][1] == 2 and requests[1][2] == 20 and requests[1][4] == "mloot_open")
netcoop_mutant_loot_view.receive("21|ok|meat_dog*2")     -- not asked: ignored
assert(registered == 0)
netcoop_mutant_loot_view.receive("20|ok|meat_dog*2;mutant_part_dog_tail*1")
assert(registered == 1 and #reinit == 3 and reinit[1] == "meat_dog" and reinit[3] == "mutant_part_dog_tail")
local req = netcoop_mutant_loot_view.take_request({meat_dog = {count = 2}, mutant_part_dog_tail = {count = 1}}, {mutant_part_dog_tail = 1}, false)
assert(req == "0,1")
assert(netcoop_mutant_loot_view.take_request({}, {}, true) == "all")
assert(netcoop_mutant_loot_view.take_request({meat_dog = {count = 1}}, {}, false) == nil)
ui_mutant_loot.start(body(22, false, true)); netcoop_mutant_loot_view.receive("22|decayed|")
assert(msgs[#msgs] == "st_body_decayed")
''')
lua.execute(r'''
assert(netcoop_mutant_loot_view.use(nil)==false)
assert(netcoop_mutant_loot_view.use(body(50,true,true))==false)
assert(netcoop_mutant_loot_view.use(body(51,false,false))==false)
local before=#requests
assert(netcoop_mutant_loot_view.use(body(52,false,true))==true)
assert(#requests==before+1 and requests[#requests][2]==52 and requests[#requests][4]=="mloot_open")
ui_mutant_loot.start(53)
assert(requests[#requests][2]==53, "numeric ID callers resolve the current object")
''')
actor_input=(root.parents[1]/"src/xrGame/ActorInput.cpp").read_text(encoding="utf-8")
assert actor_input.index('functor("netcoop_mutant_loot_view.use"') < actor_input.index("m_pUsableObject->use(this)")

print("netcoop mutant loot: direct F route, numeric callers and server-backed window OK")
