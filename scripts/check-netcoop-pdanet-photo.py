"""PDA photos, tasks and points to contacts, unread tab marks (doc 89 P4 and
the rest of its checklist). Actual netcoop_pdanet server and the actual
client modules (netcoop_pdanet_client / _photo / _ui / _voice, netcoop_pda,
pda_dynamic_tabs) under Lua 5.1; the engine's photo functions, the UI
classes and the HUD are stubbed. Photo mode: the PDA closes, the weapon is
put away, RMB zooms 1x/2x/4x, LMB hides the camera frame for two frames,
takes the shot, adds it to the gallery (an index file per UID, kept over a
reload); E leaves and restores. A gallery photo goes to a chat in parts of
at most 3800 characters ("pbeg" + "aup"), the server stores it in records
under 64 KB and posts a "photo" message; chat members fetch it ("pget"),
others cannot; a fetched photo is written into the PDA cache and shown; a
photo cannot be posted by "msg"; voice and photo uploads do not overlap.
Tasks go to a contact with title and target; points can be a map pin.
Chats/Contacts tab captions carry unread counts. Engine wiring as text."""
from pathlib import Path
import base64, os, re, tempfile
from lupa.lua51 import LuaRuntime
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp

root = Path(__file__).resolve().parent / "netcoop-overlay"
repo = Path(__file__).resolve().parents[1]
src_dir = repo / "src"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
tmp = tempfile.mkdtemp().replace("\\", "/")
lua.execute(r'''
store = {}
function netcoop_store_read(b, k) assert(b:match("^[%w_%-]+$") and k:match("^[%w_%-]+$") and #k<=96);return (store[b] or {})[k] or "" end
function netcoop_store_swap(b, k, old, new)
    assert(b:match("^[%w_%-]+$") and k:match("^[%w_%-]+$") and #k<=96 and #new<=65536, "actual native shared-store bounds")
    store[b] = store[b] or {}
    if (store[b][k] or "") ~= old then return false end
    assert(#new < 65536, "record over 64 KB")
    store[b][k] = new ~= "" and new or nil
    return true
end
clock, tg = 1000000, 0
os.time = function() return clock end
function time_global() return tg end
game = {CTime = function() return {set = function() end} end,
        get_game_time = function() return {diffSec = function() return 600000 end} end,
        translate_string = function(id) return "<" .. id .. ">" end}
function printf() end
players = {[1] = {char = "a_1", name = "Bashka"}, [2] = {char = "b_1", name = "Yura"}, [3] = {char = "c_1", name = "Docent"}}
function netcoop_actor_character(id) return players[id] and players[id].char or "" end
targets = {}
level = {
    object_by_id = function(id)
        if targets[id] then return {position = function() return targets[id] end} end
        local p = players[id]
        if not p then return nil end
        return {character_name = function() return p.name end, character_icon = function() return "" end,
                money = function() return 1000 end, give_money = function() end}
    end,
    name = function() return "k00_marsh" end,
    present = function() return true end,
    hidden = 0,
    hide_indicators_safe = function() level.hidden = level.hidden + 1 end,
    show_indicators = function() level.hidden = level.hidden - 1 end,
    get_time_hours = function() return 12 end, get_time_minutes = function() return 5 end,
}
function vector() return {set = function(self, x, y, z) self.x, self.y, self.z = x, y, z; return self end} end
-- Persistent physical PDAs; the network cannot silently fall back to account identity.
local actor_by_id = level.object_by_id
pda_items = {}
for id=1,3 do
 local actor = actor_by_id(id)
 local item_id = 900+id
 local item = {id=function() return item_id end, section=function() return "device_pda_1" end, parent=function() return actor end}
 pda_items[item_id]=item
 players[id].pda_item=item
end
level.object_by_id = function(id)
 if pda_items[id] then return pda_items[id] end
 local actor=actor_by_id(id)
 if actor then actor.item_in_slot=function(_,slot) return slot==8 and players[id].pda_item or nil end; actor.id=function() return id end; actor.alive=function() return true end end
 return actor
end
db={actor={item_in_slot=function() return players[1].pda_item end}}
function netcoop_item_uid(id) return pda_items[id] and ("fixture"..id) or "" end
function netcoop_players() return "1,2,3" end
inbox = {}
function netcoop_send_to_actor(id, ch, data) inbox[id] = inbox[id] or {}; table.insert(inbox[id], data) end
function netcoop_pure_client() return true end
callbacks = {}
function RegisterScriptCallback(n, f) callbacks[n] = f end
tips = {}
actor_menu = {set_msg = function(_, m) tips[#tips + 1] = m end}
commands = {}
function netcoop_command(c) commands[#commands + 1] = c end
DIK_keys = {MOUSE_1 = 337, MOUSE_2 = 338, DIK_E = 18, DIK_ESCAPE = 1, DIK_RETURN = 28}
ui_events = {BUTTON_CLICKED = 17, WINDOW_KEY_PRESSED = 1}

-- engine photo functions: a fake $game_saves$\netcoop_photos
files, pending, zoom_now = {}, nil, 1
function netcoop_photo_take(name) pending = name; return true end
function frame_end() -- the renderer saves the frame before Present
    if pending then files[pending] = "RERTIA" .. string.rep("QUJD", 600); pending = nil end
end
function netcoop_photo_exists(name) return files[name] ~= nil end
function netcoop_photo_size(name) return files[name] and math.floor(#files[name] * 3 / 4) or 0 end
function netcoop_photo_read(name) return files[name] or "" end
function netcoop_photo_write(name, data)
    assert(name:match("^[%w_]+$"), name)
    if data:sub(1, 4) ~= "RERT" then return false end
    files[name] = data; return true
end
function netcoop_photo_delete(name) files[name] = nil; return true end
function netcoop_photo_zoom(z) zoom_now = z end

-- UI stubs
function new_widget()
    local w = {shown = true, text = "", enabled = true}
    local tc = {SetText = function(_, t) w.text = t end, GetText = function() return w.text end}
    function w:TextControl() return tc end
    function w:Show(v) self.shown = v end
    function w:IsShown() return self.shown end
    function w:InitTexture(t) self.texture = t end
    function w:Enable(v) self.enabled = v end
    function w:SetWndPos() end
    function w:SetWndSize() end
    function w:GetWndPos() return {x=0,y=0} end
    function w:SetCheck(value) self.checked=value end
    function w:GetText() return self.text end
    function w:SetText(t) self.text = t end
    return w
end
function CScriptXmlInit()
    local x = {}
    function x:ParseFile() end
    function x:InitStatic() return new_widget() end
    function x:InitFrame() return new_widget() end
    function x:InitCheck() return new_widget() end
    function x:Init3tButton() return new_widget() end
    function x:InitEditBox() return new_widget() end
    return x
end
function Frect() return {set = function(self) return self end} end
function vector2() return {set = function(self) return self end} end
CUIScriptWnd = {}
function CUIScriptWnd.SetWndRect() end
function CUIScriptWnd.SetAutoDelete() end
function CUIScriptWnd.Register(self, w, id) self._ids = self._ids or {}; self._ids[w] = id end
function CUIScriptWnd.AddCallback(self, id, ev, fn) self._cb = self._cb or {}; self._cb[id] = fn end
function CUIScriptWnd.IsShown() return true end
function CUIScriptWnd.Update() end
function CUIScriptWnd.OnKeyboard() return true end
function super() end
function class(name)
    return function(base)
        local c = {}
        c.__index = c
        setmetatable(c, {__index = base, __call = function(cls, ...)
            local o = setmetatable({}, cls)
            if cls.__init then cls.__init(o, ...) end
            return o
        end})
        _G[name] = c
    end
end
function click(win, w) return win._cb[win._ids[w]]() end
hud = {shown = {}}
function hud:AddDialogToRender(d) self.shown[d] = true end
function hud:RemoveDialogToRender(d) self.shown[d] = nil end
function get_hud() return hud end
pda_open = true
ActorMenu = {get_pda_menu = function() return {
    IsShown = function() return pda_open end, HideDialog = function() pda_open = false end,
    GetTabControl = function() return {GetButtonById = function(_, id) tab_buttons[id] = tab_buttons[id] or new_widget(); return tab_buttons[id] end} end,
    RebuildTabs = function() end} end}
tab_buttons = {}
pda = {set_active_subdialog = function() end}
sound_played = {}
sound_object = setmetatable({s2d = 1}, {__call = function(_, name)
    return {play = function() sound_played[#sound_played + 1] = name end} end})
weapon_hidden = false
tasks = {}
db = {actor = {
    id = function() return 1 end, alive = function() return true end,
    position = function() return {x = 10, y = 0.5, z = -20} end,
    hide_weapon = function() weapon_hidden = true end, restore_weapon = function() weapon_hidden = false end,
    active_slot = function() return 0 end, activate_slot = function() end,
    money = function() return 1000 end, character_name = function() return "Bashka" end,
    character_community = function() return "stalker" end, character_icon = function() return "" end,
    get_task = function(_, id) return tasks[id] end,
}}
''')
g.getFS = lua.eval("function() return {update_path = function(_, root, name) return '%s/' .. name end} end" % tmp)

def load(table_name, path):
    t = lua.table()
    lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
                t, path.read_text(encoding="utf-8"))
    g[table_name] = t
    return t

load("netcoop_transit", root / "server/netcoop_transit.script")
server = load("netcoop_pdanet", root / "server/netcoop_pdanet.script")
compat = lua.eval("{ on_task = function(id, kind) end }")
g.netcoop_client_compat = compat
client = load("netcoop_pdanet_client", root / "client/netcoop_pdanet_client.script")
voice = load("netcoop_pdanet_voice", root / "client/netcoop_pdanet_voice.script")
photo = load("netcoop_pdanet_photo", root / "client/netcoop_pdanet_photo.script")
tabs = load("pda_dynamic_tabs", repo / "gamedata/scripts/pda_dynamic_tabs.script")
mpda = load("netcoop_pda", root / "client/netcoop_pda.script")
lua.execute('''
equipped_pda=901
db.actor.item_in_slot=function(_,slot) return slot==8 and {id=function() return equipped_pda end} end
tasks_placeable_waypoints={pins={}}
function tasks_placeable_waypoints.load_state(data) tasks_placeable_waypoints.pins=data.pawsys.pins end
netcoop_pda.receive("fixture901|901|1/1|")
''')
device_uid = 'fixture901'
ui = load("netcoop_pdanet_ui", root / "client/netcoop_pdanet_ui.script")
client.on_game_start()
photo.on_game_start()
on_update = g.callbacks.actor_on_update
on_key = g.callbacks.on_key_press

def run(pid, command):
    """A netcoop command from player pid; returns what pid received."""
    assert command.startswith("pdanet ") and len(command) <= 4000, len(command)
    if not command.startswith("pdanet aup "):
        g.tg += 1500  # one post per 1.5 s (flood limit)
    server.command(pid, command[7:])
    out = list(g.inbox[pid].values()) if g.inbox[pid] else []
    g.inbox[pid] = lua.table()
    return out

def to_client(chunks):
    for c in chunks:
        client.receive(c)

def flush_commands(pid):
    got = []
    while len(g.commands):
        c = g.commands[1]
        lua.execute("table.remove(commands, 1)")
        got += run(pid, c)
    return got

def frame():
    """One game frame: Lua update, then the renderer's end of frame."""
    g.tg += 33
    on_update()
    lua.execute("frame_end()")

# a, b, c with UIDs; a and b in a private chat
to_client(run(1, "pdanet hello"))
run(2, "pdanet hello"); run(3, "pdanet hello")
ua = client.me.uid
ub = lua.eval("netcoop_transit.deserialize(netcoop_store_read('pda_prof', 'fixture902'))").uid
run(1, f"pdanet add {ub}")
run(2, f"pdanet add {ua}")
to_client(run(1, "pdanet hello"))
to_client(run(1, f"pdanet dm {ub}"))
cid = client.opened.id
assert cid.startswith("d_")

# ---------------------------------------------------------------- photo mode
photo.enter()
assert photo.active() and g.weapon_hidden and g.level.hidden == 1 and not g.pda_open
assert g.zoom_now == 1 and len(list(g.hud.shown.keys())) == 1
on_key(338); assert g.zoom_now == 2
on_key(338); assert g.zoom_now == 4
on_key(338); assert g.zoom_now == 1
on_key(338)                       # 2x for the shot
on_key(337)                       # LMB: the camera frame leaves the screen first
assert len(list(g.hud.shown.keys())) == 0 and g.pending is None
frame()                           # frame 1 without the frame: not yet
assert g.pending is None
frame()                           # frame 2: the shot is asked, saved at the frame's end
frame()                           # the file is there: into the gallery
assert len(photo.photos) == 1, len(photo.photos)
p1 = photo.photos[1]
assert re.fullmatch(r"[0-9a-f]{16}", p1.id) and p1.level == "k00_marsh" and p1.bytes > 0
name1 = photo.file_name(p1)
assert name1 == f"g{device_uid}_{p1.id}" and g.files[name1]
assert "pda_camera_shutter" in str(list(g.sound_played.values()))
assert len(list(g.hud.shown.keys())) == 1          # the camera frame is back
on_key(337); frame(); frame(); frame()             # a second shot
assert len(photo.photos) == 2
on_key(18)                                         # E
assert not photo.active() and not g.weapon_hidden and g.level.hidden == 0 and g.zoom_now == 1
assert len(list(g.hud.shown.keys())) == 0
# a failed capture leaves photo mode usable
photo.enter()
lua.execute("netcoop_photo_take = function() return false end")
on_key(337); frame(); frame()
assert "<st_pdanet_photo_failed>" in list(g.tips.values()) and len(photo.photos) == 2
lua.execute("netcoop_photo_take = function(name) pending = name; return true end")
on_key(1)                                          # ESC
assert not photo.active()

# the gallery index survives a reload (a file per UID)
assert os.path.exists(f"{tmp}/netcoop_gallery_{device_uid}.txt")
assert not os.path.exists(f"{tmp}/netcoop_gallery_{ua}.txt"), 'character gallery must never receive physical-device photos'
photo2 = load("netcoop_pdanet_photo", root / "client/netcoop_pdanet_photo.script")
photo2.load()
assert len(photo2.photos) == 2 and photo2.photos[2].id == p1.id
# a shot whose file was deleted by hand leaves the list
lua.execute(f"files['{name1}'] = nil")
photo3 = load("netcoop_pdanet_photo", root / "client/netcoop_pdanet_photo.script")
photo3.load()
assert len(photo3.photos) == 1
photo = load("netcoop_pdanet_photo", root / "client/netcoop_pdanet_photo.script")
photo.on_game_start()
on_update = g.callbacks.actor_on_update
photo.load()
assert len(photo.photos) == 1

# ---------------------------------------------------------------- a photo to the chat
g.commands = lua.table()
assert photo.send(1, cid) is True
first = g.commands[1]
m = re.fullmatch(r"pdanet pbeg ([0-9a-f]{16}) (\S+) (\d+) k00_marsh", first)
assert m and m.group(2) == cid, first
pid, parts = m.group(1), int(m.group(3))
assert g.files["c_" + pid]                         # own message shows without a fetch
flush_commands(1)
# no voice message while a photo goes up
assert voice.upload(cid, "QUJD", 1) is False and "<st_pdanet_rec_busy>" in list(g.tips.values())
replies = []
for _ in range(parts + 5):
    g.tg += 60
    on_update()
    replies += flush_commands(1)
to_client(replies)
assert photo.uploading() is None and "<st_pdanet_photo_sent>" in list(g.tips.values())
meta = lua.eval(f"netcoop_transit.deserialize(netcoop_store_read('pda_photo', '{pid}'))")
assert meta.cid == cid and meta.place == "k00_marsh" and meta.parts == 1
to_client(run(1, f"pdanet open {cid}"))
msg = client.opened.msgs[len(client.opened.msgs)]
assert msg.k == "photo" and re.fullmatch(pid + r" k00_marsh \d+", msg.d), msg.d
def shown_photo(m):
    r = photo.message_photo(m)
    return r[0] if isinstance(r, tuple) else r
assert shown_photo(msg) == f"netcoop_photos\\c_{pid}"
# b fetches it; c (not a member) cannot
got = run(2, f"pdanet pget {pid}")
assert any(c.endswith(g.files["c_" + pid][-200:]) for c in got)
assert any("no such photo" in c for c in run(3, f"pdanet pget {pid}"))
# the client asks for a photo it does not have, once, and shows it after
lua.execute(f"files['c_{pid}'] = nil")
g.commands = lua.table()
assert shown_photo(msg) is None and g.commands[1] == f"pdanet pget {pid}"
photo.message_photo(msg)
assert len(g.commands) == 1
to_client(flush_commands(1))
assert shown_photo(msg) == f"netcoop_photos\\c_{pid}"
# and keeps it in the gallery
assert photo.keep(pid, "k00_marsh") and len(photo.photos) == 2
# rejected uploads
assert any("bad message" in c for c in run(1, f"pdanet msg {cid} photo x"))
assert any("no such chat" in c for c in run(3, f"pdanet pbeg {'1' * 16} {cid} 3 l01_escape"))
assert any("bad photo" in c for c in run(1, f"pdanet pbeg xyz {cid} 3 l01_escape"))
assert any("bad photo" in c for c in run(1, f"pdanet pbeg {'2' * 16} {cid} 500 l01_escape"))
run(1, f"pdanet pbeg {'3' * 16} {cid} 1 l01_escape")
assert any("bad photo" in c for c in run(1, f"pdanet aup {'3' * 16} 1 QUJDRA=="))  # not a DDS

# ---------------------------------------------------------------- a task and a pin point
lua.execute("""
targets[777] = {x = 1, y = 2, z = 3}
tasks['t1'] = {get_title = function() return 'st_task_find' end, get_map_object_id = function() return 777 end}
tasks['t2'] = {get_title = function() return 'st_task_talk' end, get_map_object_id = function() return 65535 end}
""")
compat.on_task("t1", "new"); compat.on_task("t2", "new"); compat.on_task("t3", "new")
lst = client.active_tasks()
assert [t.title for t in lst.values()] == ["<st_task_find>", "<st_task_talk>"], [t.title for t in lst.values()]
compat.on_task("t2", "complete")
lst = client.active_tasks()
assert len(lst) == 1 and lst[1].at.x == 1
g.commands = lua.table()
client.send_task_to(ub, lst[1])
flush_commands(1)
to_client(run(1, f"pdanet open {cid}"))
tm = client.opened.msgs[len(client.opened.msgs)]
assert tm.k == "task" and tm.x == "<st_task_find>" and tm.d == "k00_marsh 1.0 2.0 3.0", (tm.k, tm.x, tm.d)
assert any("bad task" in c for c in run(1, f"pdanet msg {cid} task "))
assert any("bad task" in c for c in run(1, f"pdanet msg {cid} task Title\tnowhere"))
# a point at a pin, not where the player stands
client.post_point(cid, "Stash", lua.eval("{level = 'l01_escape', x = 5, y = 6, z = 7}"))
flush_commands(1)
to_client(run(1, f"pdanet open {cid}"))
pm = client.opened.msgs[len(client.opened.msgs)]
assert pm.k == "point" and pm.d == "l01_escape 5.0 6.0 7.0", pm.d

# ---------------------------------------------------------------- the PDA tab windows (stub UI)
ui.on_game_start()
gallery = photo.gallery_window()
gallery.Pick(gallery, 1)
assert gallery.selected == 1 and gallery.prev.texture.startswith("netcoop_photos\\g")
gallery.Pick(gallery, 1)                           # second click: full view
assert gallery.viewing and gallery.view.img.shown and not gallery.send_btn.shown
g.click(gallery, gallery.view.close)
assert not gallery.viewing and gallery.send_btn.shown
tab = photo.photo_window()
assert tab.last.texture.startswith("netcoop_photos\\g") and tab.count.text == "<st_pdanet_photo_count>"
chats = ui.pdanet_chats()
chats.chat = cid
chats.Dialog(chats, "point")
assert chats.dlg.rows[1].text.endswith("<st_pdanet_point_here>")
chats.Toggle(chats, 1)
g.commands = lua.table()
chats.DialogOk(chats)
assert g.commands[1].startswith(f"pdanet msg {cid} point ") and "k00_marsh 10.0 0.5 -20.0" in g.commands[1]
chats.Dialog(chats, "photo")
assert "k00_marsh" in chats.dlg.rows[1].text or "<k00_marsh>" in chats.dlg.rows[1].text
chats.Toggle(chats, 1)
g.commands = lua.table()
chats.DialogOk(chats)
assert g.commands[1].startswith("pdanet pbeg "), g.commands[1]
lua.execute("netcoop_pdanet_photo.on_sent()")
chats.Fill(chats)
contacts = ui.pdanet_contacts()
contacts.selected = 1
contacts.Tasks(contacts, True)
assert contacts.tdlg.rows[1].text == "<st_task_find>"
contacts.task_pick = 1
g.commands = lua.table()
contacts.SendTask(contacts)
assert any(" task <st_task_find>" in c for c in g.commands.values())

# unread marks on the tab captions
g.tab_buttons = lua.table()
lua.execute("netcoop_pdanet_client.chats = {{id = 'x', unread = 3}, {id = 'd_" + min(ua, ub) + "_" + max(ua, ub) + "', unread = 2}}")
ui.unread_captions()
caps = sorted(w.text for w in g.tab_buttons.values())
assert caps == ["<st_pdanet_tab_chats> (5)", "<st_pdanet_tab_contacts> (2)"], caps
lua.execute("netcoop_pdanet_client.chats = {}")
ui.unread_captions()
assert sorted(w.text for w in g.tab_buttons.values()) == ["<st_pdanet_tab_chats>", "<st_pdanet_tab_contacts>"]

# ---------------------------------------------------------------- strings, templates, sounds
used = set()
for f in ("netcoop_pdanet_photo.script", "netcoop_pdanet_ui.script", "netcoop_pdanet_voice.script"):
    used |= set(re.findall(r'"(st_pdanet_[a-z_]+)"', (root / "client" / f).read_text(encoding="utf-8")))
for lang in ("rus", "eng"):
    table = (root / f"client/configs/text/{lang}/st_netcoop.xml").read_bytes().decode("cp1251")
    missing = [k for k in used if f'id="{k}"' not in table and not k.endswith("_")]
    assert not missing, (lang, missing)
pdxml = (root / "client/configs/ui/ui_netcoop_pdanet.xml").read_bytes().decode("cp1251")
code = (root / "client/netcoop_pdanet_photo.script").read_text(encoding="utf-8")
for tpl in set(re.findall(r'(?:u\.static\(self|InitStatic)\(?"(\w+)"', code)) | {"photo", "cam_bar", "cam_title", "cam_info", "cam_hint", "cam_saved"}:
    assert f"<{tpl} " in pdxml, tpl
for s in ("shutter", "zoom_in", "zoom_out"):
    assert (root / f"client/sounds/device/pda/pda_camera_{s}.ogg").stat().st_size > 1000

# ---------------------------------------------------------------- engine wiring
shot = (src_dir / "Layers/xrRender/r__screenshot.cpp").read_text(encoding="utf-8", errors="replace")
dev = (src_dir / "Layers/xrRender/dxRenderDeviceRender.cpp").read_text(encoding="utf-8", errors="replace")
assert "bool CRender::NetcoopPhotoRequest" in shot and shot.count("void NetcoopPhotoFlush()") == 2
assert "DXGI_FORMAT_BC1_UNORM" in shot and "0xff000000u" in shot and re.search(r"\bsmall\b", shot.split("NetcoopPhotoFlush")[1]) is None
i_flush = dev.index("NetcoopPhotoFlush(); //")
assert 0 < dev.index("HW.m_pSwapChain->Present", i_flush) - i_flush < 200  # right before the window's Present
for h in ("Layers/xrRenderPC_R4/r4.h",):
    assert "NetcoopPhotoRequest" in (src_dir / h).read_text(encoding="utf-8", errors="replace")
assert "virtual bool NetcoopPhotoRequest" in (src_dir / "xrEngine/Render.h").read_text(encoding="utf-8", errors="replace")
script = (src_dir / "xrGame/level_script.cpp").read_text(encoding="utf-8", errors="replace")
for name in ("take", "exists", "size", "read", "write", "delete", "zoom"):
    assert f'def("netcoop_photo_{name}", &netcoop::script_photo_{name})' in script, name
assert '#include "netcoop_photo.inc"' in netcoop_cpp(src_dir.parent, encoding="utf-8", errors="replace")
assert "g_netcoop_photo_zoom > 1.f" in (src_dir / "xrGame/Actor.cpp").read_text(encoding="utf-8", errors="replace")
inc = (src_dir / "xrGame/netcoop_photo.inc").read_text(encoding="utf-8")
assert "photo_dds_ok" in inc and "photo_name_ok" in inc and "$game_saves$" in inc
# Physical-device switch, including completion of an asynchronous capture.
on_key=g.callbacks.on_key_press
old_count=len(photo.photos)
lua.execute('netcoop_pda.reset();equipped_pda=82;netcoop_pda.receive("physical_B|82|1/1|")')
photo.load();assert len(photo.photos)==0
photo.enter();on_key(337);frame();frame();frame()
assert len(photo.photos)==1 and photo.file_name(photo.photos[1]).startswith('gphysical_B_')
on_key(18)
photo.enter();on_key(337);frame();frame()
lua.execute('netcoop_pda.reset();equipped_pda=901;netcoop_pda.receive("fixture901|901|1/1|")')
frame();photo.load()
assert not photo.active() and len(photo.photos)==old_count, 'late shot cannot enter replacement gallery'
lua.execute('netcoop_pda.reset();netcoop_pdanet_client.slot_device=nil')
photo.load();assert len(photo.photos)==0 and not photo.keep(pid,'k00_marsh')
photo.enter();assert not photo.active(), 'unknown device cannot create an account-global photo'
print("PDA photos, tasks, pin points, unread tab captions and physical-device isolation/capture switch: PASS")
