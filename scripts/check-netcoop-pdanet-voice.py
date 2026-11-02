"""PDA voice messages and dictaphone (actual netcoop_pdanet server and the
actual netcoop_pdanet_voice / netcoop_pdanet_client on the client, Lua 5.1;
the engine recorder is stubbed). A recording goes to the server in parts of
at most 3800 characters (one netcoop command is at most 4000), the server
joins and stores them in the cluster store in records under 64 KB, posts a
"voice" message to the chat; chat members fetch the record, others cannot;
the client plays a fetched record and keeps it cached; a second upload
waits for the first; uploads only to a chat the sender is in; dictaphone
records are kept in a file per UID and survive a reload; the 10-minute
limit ends a dictaphone recording and keeps it. Engine wiring as text."""
from pathlib import Path
import base64, os, re, tempfile
from lupa.lua51 import LuaRuntime
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp

root = Path(__file__).resolve().parent / "netcoop-overlay"
src_dir = Path(__file__).resolve().parents[1] / "src"
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
level = {object_by_id = function(id)
    local p = players[id]
    if not p then return nil end
    return {character_name = function() return p.name end, character_icon = function() return "" end,
            money = function() return 1000 end, give_money = function() end}
end}
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
-- engine recorder / player
rec = {on = false, secs = 0, data = "", limit = 0}
function netcoop_record_start(limit) rec.on = true; rec.limit = limit; return true end
function netcoop_record_active() return rec.on and rec.secs < rec.limit end
function netcoop_record_seconds() return rec.secs end
function netcoop_record_stop() rec.on = false; return rec.data end
played = {}
function netcoop_play_start(data, from) played[#played + 1] = data; return 7 end
function netcoop_play_pos() return -1 end
function netcoop_play_paused() return false end
function netcoop_play_pause() end
function netcoop_play_stop() end
function netcoop_play_seek() end
tips = {}
actor_menu = {set_msg = function(_, m) tips[#tips + 1] = m end}
commands = {}
function netcoop_command(c) commands[#commands + 1] = c end
function class(name) return function(base) local c = {}; c.__index = c; _G[name] = c end end
CUIScriptWnd = {}
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
client = load("netcoop_pdanet_client", root / "client/netcoop_pdanet_client.script")
voice = load("netcoop_pdanet_voice", root / "client/netcoop_pdanet_voice.script")
voice.on_game_start()
update = g.callbacks.actor_on_update

def run(pid, command):
    """A netcoop command from player pid; returns what pid received."""
    assert command.startswith("pdanet ") and len(command) <= 4000, len(command)
    server.command(pid, command[7:])
    out = list(g.inbox[pid].values()) if g.inbox[pid] else []
    g.inbox[pid] = lua.table()
    return out

def to_client(chunks):
    for c in chunks:
        client.receive(c)

# a, b, c with UIDs; a and b in a private chat
to_client(run(1, "pdanet hello"))
run(2, "pdanet hello"); run(3, "pdanet hello")
ua, ub = client.me.uid, None
ub = lua.eval("netcoop_transit.deserialize(netcoop_store_read('pda_prof', 'fixture902'))").uid
run(1, f"pdanet add {ub}")
to_client(run(1, f"pdanet dm {ub}"))
cid = client.opened.id
assert cid.startswith("d_")

def flush_commands(pid):
    """Send the client's queued commands (from Lua) to the server as pid."""
    got = []
    while len(g.commands):
        c = g.commands[1]
        lua.execute("table.remove(commands, 1)")
        got += run(pid, c)
    return got

# A voice message: ~12 kB of record -> 4 parts.
blob = base64.b64encode(os.urandom(9000)).decode()
g.rec.data, g.rec.secs = blob, 6.2
voice.set_chat(cid)
voice.start_message()
assert voice.recording_kind() == "msg" and g.rec.on
voice.stop_and_send(cid)
assert not voice.recording() and not g.rec.on
assert g.commands[1].startswith(f"pdanet abeg ") and g.commands[1].endswith(f" {cid} 7 4")
flush_commands(1)
assert voice.uploading() == 0
# a second upload waits for the first
assert voice.upload(cid, "QUJD", 1) is False
replies = []
for _ in range(10):
    g.tg += 60
    update()
    replies += flush_commands(1)
assert all(len(c) <= 4000 for c in replies)
to_client(replies)
assert voice.uploading() is None and "<st_pdanet_rec_sent>" in list(g.tips.values())
meta = lua.eval("netcoop_transit.deserialize(netcoop_store_read('pda_audio', next(store.pda_audio, nil) and (function() for k in pairs(store.pda_audio) do if not k:find('_') then return k end end end)()))")
assert meta.cid == cid and meta.secs == 7 and meta.parts == 1
# the message in the chat; b fetches it; c (not a member) cannot
to_client(run(1, f"pdanet open {cid}"))
m = client.opened.msgs[len(client.opened.msgs)]
assert m.k == "voice" and re.fullmatch(r"[0-9a-f]{16} 7", m.d), m.d
aid = m.d.split()[0]
got = run(2, f"pdanet aget {aid}")
assert any(c.endswith(blob) or blob[-100:] in c for c in got)
assert any("no such record" in c for c in run(3, f"pdanet aget {aid}"))
# a plays it: asked once, then cached
voice.play_message(m)
assert g.commands[1] == f"pdanet aget {aid}"
to_client(flush_commands(1))
assert g.played[1] == blob
voice.play_message(m)
assert len(g.commands) == 0 and g.played[2] == blob
# uploads only into own chats
assert any("no such chat" in c for c in run(3, f"pdanet abeg {'1' * 16} {cid} 3 1"))
assert any("bad record" in c for c in run(1, f"pdanet abeg xyz {cid} 3 1"))
# parts without "abeg" are ignored
run(3, f"pdanet aup {'2' * 16} 1 QUJD")

# Dictaphone: kept in a file per UID; the 10-minute limit keeps the record.
g.rec.data, g.rec.secs = "RElDVA==", 0
voice.dict_start()
assert voice.recording_kind() == "dict" and g.rec.limit == 600
g.rec.secs = 600          # limit reached: the engine stops
update()
assert not voice.recording() and len(voice.records) == 1 and voice.records[1].secs == 600
assert os.path.exists(f"{tmp}/netcoop_dictaphone_fixture901.txt")
voice2 = load("netcoop_pdanet_voice", root / "client/netcoop_pdanet_voice.script")
voice2.dict_play(1)
assert len(voice2.records) == 1 and g.played[len(g.played)] == "RElDVA=="
voice2.dict_delete(1)
assert len(voice2.records) == 0
# sending a record needs an open chat
lua.execute("netcoop_pdanet_client.opened = nil")
voice2.dict_start(); g.rec.secs = 3; voice2.dict_stop()
voice2.dict_send(1)
assert "<st_pdanet_rec_open_chat>" in list(g.tips.values())

# Strings and templates.
ui = (root / "client/netcoop_pdanet_voice.script").read_text(encoding="utf-8")
used = set(re.findall(r'"(st_pdanet_[a-z_]+)"', ui))
for lang in ("rus", "eng"):
    table = (root / f"client/configs/text/{lang}/st_netcoop.xml").read_bytes().decode("cp1251")
    missing = [k for k in used if f'id="{k}"' not in table]
    assert not missing, (lang, missing)
pdxml = (root / "client/configs/ui/ui_netcoop_pdanet.xml").read_bytes().decode("cp1251")
for tpl in set(re.findall(r'u\.static\(self, "(\w+)"', ui)) | {"seek", "row", "hint_left"}:
    assert f"<{tpl} " in pdxml, tpl

# Engine: the recorder hears the microphone, players and radio, world sounds.
inc = (src_dir / "xrGame/netcoop_voice_record.inc").read_text(encoding="utf-8")
voice_inc = (src_dir / "xrGame/netcoop_voice.inc").read_text(encoding="utf-8")
assert "voice_record_heard(speaker, mode" in voice_inc and "voice_record_update();" in voice_inc
assert "SetRecord(&s_rec)" in inc and "SetSoundTap(&s_rec)" in inc
assert '#include "netcoop_voice_record.inc"' in netcoop_cpp(src_dir.parent, encoding="utf-8", errors="replace")
script = (src_dir / "xrGame/level_script.cpp").read_text(encoding="utf-8", errors="replace")
for name in ("record_start", "record_active", "record_seconds", "record_stop", "play_start", "play_seek",
             "play_pause", "play_stop", "play_pos", "play_paused", "keyboard_layout"):
    assert f'def("netcoop_{name}", &netcoop::script_{name})' in script, name
core = (src_dir / "xrSound/SoundRender_Core_Processor.cpp").read_text(encoding="utf-8", errors="replace")
assert "i_tap(P, D, N);" in core and "s_tap_pending.push_back(E)" in core
print("netcoop pdanet voice: OK")
