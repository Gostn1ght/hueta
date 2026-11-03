"""Barter between players on the client (actual netcoop_barter_client, Lua 5.1,
UI classes stubbed): the prompt appears only for another living player in
reach, says "offer" and no name (spec 6.6); the use key sends the invitation;
an invitation opens a request with Accept / Decline that lapses after 60 s
(spec 9); the window opens only on the server's "open", shows the server's
state (own offer as real items, the partner's offer and backpack as
sections, money, ready marks), clicks and drag-and-drop add/remove, Ready
sends the money and the version, closing messages close it."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
lua.execute(r'''
function printf() end
now = 0
function time_global() return now end
commands, news_log = {}, {}
function netcoop_command(text) commands[#commands + 1] = text end
function netcoop_pure_client() return true end
game = {translate_string = function(id) return id end}
key_bindings = {kUSE = 7}
function dik_to_bind(dik) return dik == 33 and 7 or 0 end
function bind_to_dik() return 33 end
function dik_to_keyname() return "f" end
clsid = {actor = 1, stalker = 2}
local V = {}
V.__index = V
function V:distance_to(o) return math.abs(self.x - o.x) end
function pos(x) return setmetatable({x = x}, V) end
objects = {}
function make(id, cls, x, name)
  local o = {_id = id, _cls = cls, _pos = pos(x), _name = name, _alive = true}
  function o:id() return self._id end
  -- A player's class on a client is script_actor; only the engine's test counts.
  function o:is_actor() return self._cls == 1 end
  function o:clsid() return self._cls == 1 and 99 or self._cls end
  function o:position() return self._pos end
  function o:alive() return self._alive end
  function o:character_name() return self._name end
  function o:section() return self._sec end
  objects[id] = o
  return o
end
looking = nil
db = {actor = make(0, 1, 0, "Me")}
db.actor.get_actor_object_looking_at = function() return looking end
function db.actor:give_game_news(title, text) news_log[#news_log + 1] = text end
function db.actor:item_in_slot(slot) return slot == 2 and objects[50] or nil end
function db.actor:is_on_belt(item) return item:id() == 51 end
function db.actor:iterate_ruck(f, o) for _, id in ipairs({50, 51, 52, 53}) do f(o, objects[id]) end end
level = {object_by_id = function(id) return objects[id] end, get_target_obj = function() return nil end}
-- UI stubs
local function widget()
  local w = {}
  function w:SetText(t) self.text = t end
  function w:GetText() return self.text end
  function w:SetWndRect() end function w:SetFont() end function w:SetTextAlignment() end
  function w:SetTextColor() end function w:SetAutoDelete() end
  return w
end
hud_shown = {}
function get_hud() return {AddDialogToRender = function(_, w) hud_shown[w] = true end,
                           RemoveDialogToRender = function(_, w) hud_shown[w] = nil end} end
function CUITextWnd() return widget() end
function CUIStatic() local w = widget(); function w:InitTexture() end; function w:SetStretchTexture() end; return w end
ini_sys = {section_exist = function(_, s) return s ~= "ghost" end}
function Frect() return {set = function(self) return self end} end
function GetFontLetterica18Russian() end
function GetARGB() end
CUIScriptWnd = {Update = function() end, OnKeyboard = function() return false end}
function class(name)
  local env = getfenv(2)
  return function(base)
    local cls = {}
    cls.__index = cls
    setmetatable(cls, {__index = base, __call = function(c, ...)
      local o = setmetatable({}, c)
      o.shown = false
      function o:AttachChild() end function o:SetWndRect() end function o:SetAutoDelete() end
      function o:Register() end function o:AddCallback() end
      function o:ShowDialog() self._shown = true end
      function o:HideDialog() self._shown = false end
      function o:IsShown() return self._shown == true end
      c.__init(o, ...)
      return o
    end})
    env[name] = cls
  end
end
function super() end
function CScriptXmlInit()
  local x = {}
  function x:ParseFile() end
  function x:InitStatic() return widget() end
  function x:InitTextWnd() return widget() end
  function x:InitEditBox() return widget() end
  function x:Init3tButton() return widget() end
  return x
end
ui_events = {BUTTON_CLICKED = 1, EDIT_TEXT_COMMIT = 2, WINDOW_KEY_PRESSED = 3}
DIK_keys = {DIK_ESCAPE = 1}
reinit = {}
utils_ui = {
  UICellContainer = function(id, owner) return {id = id, cell = {}, Reinit = function(self, t) reinit[id] = t end,
                                                  Update = function() return false end,
                                                  prof = {over = false, IsCursorOverWindow = function(self) return self.over end}} end,
  UIInfoItem = function() return {Update = function() end} end,
}
callbacks = {}
function RegisterScriptCallback(name, f) callbacks[name] = f end
''')
client = lua.table()
lua.execute("local env=...; setfenv(assert(loadstring(select(2,...))), setmetatable(env,{__index=_G}))()",
            client, (root / "client/netcoop_barter_client.script").read_text(encoding="utf-8"))
g.UIBarterPrompt = client.UIBarterPrompt
client.on_game_start()
update, key = g.callbacks.actor_on_update, g.callbacks.on_key_press
make = g.make
other = make(10, 1, 2, "Bravo")
npc = make(11, 2, 1, "Npc")
far = make(12, 1, 9, "Far")
for i, sec in ((50, "wpn_ak74"), (51, "art"), (52, "bread"), (53, "medkit")):
    o = make(i, 3, 0, sec); o._sec = sec

def shown_prompt():
    g.now += 200
    update()
    for w in g.hud_shown:
        return w.text.text
    return None

def cmds():
    out = [g.commands[i + 1] for i in range(len(g.commands))]
    lua.execute("commands = {}")
    return out

# The prompt: only another living player in reach.
for target in (None, npc, far, g.db.actor):
    g.looking = target
    assert shown_prompt() is None, target
g.looking = other
assert shown_prompt() == "st_netcoop_barter_offer"    # no name, faction or hostility
key(33); assert cmds() == ["barter invite 10"]
key(34); assert cmds() == []                       # another key
other._alive = False
assert shown_prompt() is None
other._alive = True
# Invited: a request with Accept / Decline; no prompt, no key behind it.
client.receive("invited|10|Bravo")
req = client.current_request()
assert req and req.IsShown(req) and shown_prompt() is None
key(33); assert cmds() == []
req.OnAccept(req); assert cmds() == ["barter accept 10"] and client.current_request() is None
# Not answered in 60 s: declined by itself.
client.receive("invited|10|Bravo"); req = client.current_request()
g.now += 61000; req.Update(req)
assert cmds() == ["barter decline 10"] and client.current_request() is None
client.receive("invited|10|Bravo"); req = client.current_request()
req.OnDecline(req); assert cmds() == ["barter decline 10"]
# The server says it lapsed: the request closes.
client.receive("invited|10|Bravo")
client.receive("expired|10")
assert client.current_request() is None and g.news_log[len(g.news_log)] == "st_netcoop_barter_expired"
# The window opens only on the server's "open", follows its state.
client.receive("invited|10|Bravo")
client.receive("open|10|Bravo")
assert client.current_request() is None             # accepted on the other side: the request goes
assert shown_prompt() is None                      # no prompt while the window is open
client.receive("state|3|150|200|1|0|53,medkit,0.80|77,ammo_9x18,1.00;78,bread,0.50|60,vodka,1.00;61,ghost,1.00")
bag = [g.reinit.bag[i + 1]._id for i in range(len(g.reinit.bag))]
assert bag == [51, 52], bag                            # not worn (50), not on belt (51), not offered (53)
assert [g.reinit.give[i + 1]._id for i in range(len(g.reinit.give))] == [53]
assert [g.reinit.get[i + 1] for i in range(len(g.reinit.get))] == ["ammo_9x18", "bread"]
assert [g.reinit.their_bag[i + 1] for i in range(len(g.reinit.their_bag))] == ["vodka"]  # unknown sections skipped
key(33); assert cmds() == []                       # the use key does nothing behind the window
# Another invitation while trading is declined at once.
client.receive("invited|3|Charlie"); assert cmds() == ["barter decline 3"] and client.current_request() is None
win = client.current_window()
win.bag.cell[1] = lua.eval("{ID = 52}")
win.give.cell[1] = lua.eval("{ID = 53}")
win.On_CC_Mouse1(win, "bag", 1); assert cmds() == ["barter add 52"]
win.On_CC_Mouse1(win, "give", 1); assert cmds() == ["barter remove 53"]
win.On_CC_Mouse1(win, "get", 1); assert cmds() == []          # the partner's items are not ours to move
# Drag and drop: onto the offer adds, back onto the backpack removes; elsewhere nothing.
win.On_CC_DragDrop(win, "bag", 1); assert cmds() == []
win.give.prof.over = True
win.On_CC_DragDrop(win, "bag", 1); assert cmds() == ["barter add 52"]
win.give.prof.over = False; win.bag.prof.over = True
win.On_CC_DragDrop(win, "give", 1); assert cmds() == ["barter remove 53"]
win.On_CC_DragDrop(win, "their_bag", 1); assert cmds() == []
win.money.text = "250"
win.OnReady(win); assert cmds() == ["barter ready 3 250"]
win.money.text = "-5"
win.OnMoney(win); assert cmds() == ["barter money 0"]
# Exercise the real base UICellContainer event methods, not direct callback calls.
lua.execute((Path(__file__).parent / "tests/fixtures/barter_container_input.lua").read_text(encoding="utf-8"))
lua.execute(r'''
K_M1, K_M2, K_SHFT, E_PRESS, E_RELEASE = 100, 101, 102, 3, 4
function get_time() return now end
function wire(cc, owner, id, item)
  setmetatable(cc, {__index = UICellContainer})
  cc.ID, cc.owner, cc.disable_callback = id, owner, {}
  cc.hover, cc.db = {idx = 1}, {tg = -1000}
  cc.hold = {ico = {Show = function() end}}
  cc.cell[1] = {ID = item, IsShown = function() return true end}
  cc.scroll = {GetCurrentScrollPos = function() return 0 end}
  cc.IsShown = function() return true end
  cc.On_Select = function() end
  cc.Print = function() end
end
''')
for name, item in (("bag", 52), ("give", 53), ("equipment", 50), ("get", 77), ("their_bag", 60)):
    g.wire(win[name], win, name, item)
    win[name].hover.idx = False
win.bag.hover.idx = 1
win.OnKeyboard(win, g.K_M1, g.E_PRESS)
win.OnKeyboard(win, g.K_M1, g.E_RELEASE)
assert cmds() == ["barter add 52"], "owner must forward real mouse input"
win.bag.hover.idx = False
win.equipment.hover.idx = 1
g.now += 500
win.OnKeyboard(win, g.K_M1, g.E_PRESS)
win.OnKeyboard(win, g.K_M1, g.E_RELEASE)
assert cmds() == ["barter add 50"], "equipped items are offerable"
win.equipment.hover.idx = False
win.bag.hover.idx = 1
g.now += 500
win.OnKeyboard(win, g.K_M1, g.E_PRESS)
win.bag.hover.idx = False
win.give.hover.idx = 1
win.give.prof.over = True
win.OnKeyboard(win, g.K_M1, g.E_RELEASE)
assert cmds() == ["barter add 52"], "drop must not click an item in the target as well"
# Remote state refresh preserves an unfinished money edit and refreshes equipment.
win.money.text = "123"
client.receive("state|4|150|210|0|0|50,wpn_ak74,1.00||")
assert win.money.text == "123" and len(g.reinit.equipment) == 0
win.OnReady(win)
assert cmds() == ["barter ready 4 123"]
client.receive("state|5|123|210|1|0|50,wpn_ak74,1.00||")
assert win.money.text == "123"
client.receive("done")
assert client.current_window() is None and g.news_log[len(g.news_log)] == "st_netcoop_barter_done"
client.receive("open|10|Bravo"); client.receive("closed|far")
assert client.current_window() is None and g.news_log[len(g.news_log)] == "st_netcoop_barter_closed_far"
client.receive("open|10|Bravo"); win = client.current_window()
win.OnCancel(win); assert cmds() == ["barter cancel"] and client.current_window() is None
print("PASS barter client: prompt only for players in reach and without their name, request with accept/decline lapsing in 60 s, actual container mouse/drag input, equipped offers, money edit preservation, atomic cash-ready, partner inventory")
