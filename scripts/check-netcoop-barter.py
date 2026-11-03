"""Barter between players on the server (actual netcoop_barter, Lua 5.1):
invitation only within reach and only to a player, acceptance only by the
invited one and only while fresh (60 s; a lapsed request tells both sides),
each side sees the other's backpack as in a trader's window, offers only of own backpack items (no quest,
foreign items) and own money, any change clears both "ready" marks, the
deal needs both marks on the same version, everything is checked again and
moves at once or nothing does, parting/leaving ends it."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
lua.execute(r'''
function printf() end
now = 0
function time_global() return now end
sent = {}
function netcoop_send_to_actor(id, channel, text) assert(channel == "barter"); sent[#sent + 1] = id .. ">" .. text end
players = "1 2 3"
function netcoop_players() return players end
ini_sys = {r_bool_ex = function(_, sec, key, def) if key == "quest_item" then return sec == "quest_doc" end return def end}
objects = {}
local V = {}
V.__index = V
function V:distance_to(o) return math.sqrt((self.x - o.x) ^ 2 + (self.z - o.z) ^ 2) end
function pos(x) return setmetatable({x = x, z = 0}, V) end
function make_actor(id, x, money, name)
  local a = {_id = id, _pos = pos(x), _money = money, _name = name, _alive = true, belt = {}, slots = {}}
  function a:id() return self._id end
  function a:alive() return self._alive end
  function a:position() return self._pos end
  function a:money() return self._money end
  function a:give_money(n) self._money = self._money + n end
  function a:character_name() return self._name end
  function a:is_on_belt(item) return self.belt[item:id()] == true end
  function a:item_in_slot(slot) return self.slots[slot] end
  function a:iterate_inventory(f, obj)
    local ids = {}
    for oid, o in pairs(objects) do if o._parent == self._id then ids[#ids + 1] = oid end end
    table.sort(ids)
    for _, oid in ipairs(ids) do f(self, objects[oid]) end
  end
  function a:transfer_item(item, to) assert(item._parent == self._id, "moves only own items"); item._parent = to:id() end
  objects[id] = a
  return a
end
function make_item(id, owner, section)
  local it = {_id = id, _parent = owner, _section = section}
  function it:id() return self._id end
  function it:parent() return self._parent and objects[self._parent] end
  function it:section() return self._section end
  function it:condition() return 0.75 end
  objects[id] = it
  return it
end
level = {object_by_id = function(id) return objects[id] end}
''')
barter = lua.table()
lua.execute("local env=...; setfenv(assert(loadstring(select(2,...))), setmetatable(env,{__index=_G}))()",
            barter, (root / "server/netcoop_barter.script").read_text(encoding="utf-8"))
A = g.make_actor(1, 0, 1000, "Alpha")
B = g.make_actor(2, 2, 500, "Bravo")
C = g.make_actor(3, 50, 0, "Charlie")
NPC = g.make_actor(9, 1, 0, "Npc")  # not a player
for i, (owner, sec) in enumerate([(1, "wpn_ak74"), (1, "medkit"), (1, "quest_doc"), (1, "helm"), (1, "art"),
                                  (2, "bread"), (2, "ammo_9x18"), (3, "vodka")], start=100):
    g.make_item(i, owner, sec)
A.belt[104] = True
A.slots[3] = g.objects[103]

def msgs():
    out = [g.sent[i + 1] for i in range(len(g.sent))]
    lua.execute("sent = {}")
    return out

def cmd(id, text):
    barter.command(id, text)
    return msgs()

# Invitations: in reach, to a player, not to oneself.
assert cmd(1, "invite 3") == []            # 50 m away
assert cmd(1, "invite 9") == []            # an NPC
assert cmd(1, "invite 1") == []
assert cmd(1, "invite 2") == ["2>invited|1|Alpha", "1>sent|2|Bravo"]
# Only the invited player accepts, only the inviter's invitation, only while fresh.
assert cmd(3, "accept 1") == [] and cmd(2, "accept 3") == []
g.now = 61000
assert cmd(2, "accept 1") == []
g.now = 70000
cmd(1, "invite 2")
out = cmd(2, "accept 1")
assert out[:2] == ["1>open|2|Bravo", "2>open|1|Alpha"], out
BAG_A, BAG_B = "100,wpn_ak74,0.75;101,medkit,0.75;103,helm,0.75;104,art,0.75", "105,bread,0.75;106,ammo_9x18,0.75"
assert out[2] == "1>state|1|0|0|0|0|||" + BAG_B and out[3] == "2>state|1|0|0|0|0|||" + BAG_A, out
# A busy player cannot be invited by someone else.
C._pos = g.pos(1)
assert cmd(3, "invite 2") == ["3>declined|Bravo"]
# Offers: own backpack items only.
s = barter.session_of(1)
for bad in (105, 102, 999):       # theirs, quest, worn, belt, missing
    assert cmd(1, "add %d" % bad) == [], bad
out = cmd(1, "add 100")
assert out[0] == "1>state|2|0|0|0|0|100,wpn_ak74,0.75||" + BAG_B, out
assert out[1] == "2>state|2|0|0|0|0||100,wpn_ak74,0.75|101,medkit,0.75;103,helm,0.75;104,art,0.75", out  # an offered item leaves the backpack list
cmd(2, "add 106")
cmd(1, "money 300")
cmd(2, "money 9999")                         # clamped to Bravo's 500
assert s["money"][1] == 300 and s["money"][2] == 500 and s.version == 5
# Ready marks: only for the current version; any change clears both.
out = cmd(1, "ready 4")
assert out[0].startswith("1>state|5|") and s["ready"][1] is False
cmd(1, "ready 5")
assert s["ready"][1] is True and s["ready"][2] is False
cmd(2, "money 400")
assert s["ready"][1] is False and s.version == 6
# Both ready on the same version: everything moves at once.
cmd(1, "ready 6")
out = cmd(2, "ready 6")
assert out == ["1>done", "2>done"], out
assert g.objects[100]._parent == 2 and g.objects[106]._parent == 1
assert A._money == 1000 - 300 + 400 and B._money == 500 - 400 + 300
assert barter.session_of(1) is None and barter.session_of(2) is None
# A deal whose item left the owner meanwhile moves nothing.
g.now = 140000
cmd(1, "invite 2"); cmd(2, "accept 1")
cmd(1, "add 101"); cmd(2, "add 105")
lua.execute("objects[101]._parent = 3")    # given away meanwhile
cmd(1, "ready %d" % barter.session_of(1).version)
out = cmd(2, "ready %d" % barter.session_of(2).version)
assert out == ["1>closed|items", "2>closed|items"], out
assert g.objects[105]._parent == 2 and A._money == 1100 and B._money == 400
# Parting ends it; so does leaving the server; cancel ends it for both.
cmd(1, "invite 2"); cmd(2, "accept 1"); msgs()
B._pos = g.pos(5)
barter.update()
assert msgs() == ["1>closed|far", "2>closed|far"]
B._pos = g.pos(2)
cmd(1, "invite 2"); cmd(2, "accept 1"); msgs()
g.players = "1 3"
barter.update()
assert msgs() == ["1>closed|left", "2>closed|left"]
g.players = "1 2 3"
cmd(1, "invite 2"); cmd(2, "accept 1"); msgs()
assert cmd(2, "cancel") == ["1>closed|cancel", "2>closed|cancel"]
# Money entered with Ready is one version-checked change. It clears the
# partner's old consent but keeps the sender ready for the resulting version.
cmd(1, "invite 2"); cmd(2, "accept 1")
s = barter.session_of(1)
cmd(2, "ready 1")
cmd(1, "ready 1 250")
assert s.version == 2 and s["money"][1] == 250
assert s["ready"][1] is True and s["ready"][2] is False
cmd(2, "ready 1 0")
assert s["ready"][2] is False and s["money"][1] == 250
cmd(1, "add 103")  # worn, still owned; no unequip before confirming
assert s["items"][1][103] and g.objects[103]._parent == 1
cmd(1, "add 104")  # belt
assert s["items"][1][104]
cmd(1, "ready %d 999999" % s.version)
assert s["money"][1] == A._money
version = s.version
cmd(2, "ready %d 0" % version)
assert barter.session_of(1) is None
assert g.objects[103]._parent == 2 and g.objects[104]._parent == 2
assert A._money == 0 and B._money == 1500
# Declining tells the inviter; a stale invitation disappears.
cmd(1, "invite 2"); msgs()
assert cmd(2, "decline 1") == ["1>declined|Bravo"]
cmd(1, "invite 2"); msgs()
g.now = g.now + 61000
barter.update()
assert msgs() == ["1>declined|Bravo", "2>expired|1"], "a lapsed request tells both"
assert cmd(2, "accept 1") == []
print("PASS barter: invite in reach, accept fresh (60 s, lapse told to both), partner's backpack shown, own backpack offers, ready per version, all-or-nothing deal, parting/leaving/cancel/decline")
