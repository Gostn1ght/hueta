"""PDA network (actual netcoop_pdanet with the actual netcoop_transit serializer,
Lua 5.1): two location servers share one store. UIDs are unique and stable;
strangers are UID-only; a contact shows name/avatar, and online status only
when both added each other; the general channel and chats keep history;
a message to a player on another server (or offline) arrives by polling;
unread counts; groups only from contacts, deleted for all; anonymous general
messages; points validated; a non-member cannot post. Money transfer in a
private chat: taken from the sender at once, paid out by the receiver's own
server (also after he logs in), never twice, not more than the sender has,
no fake "transfer" messages. Group members list, group icons only from the
emblem set, notes kept with the character."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
lua.execute(r'''
store = {}
function netcoop_store_read(b, k) assert(b:match("^[%w_%-]+$") and k:match("^[%w_%-]+$") and #k<=96);return (store[b] or {})[k] or "" end
function netcoop_store_swap(b, k, old, new)
    assert(b:match("^[%w_%-]+$") and k:match("^[%w_%-]+$") and #k<=96 and #new<=65536, "actual native shared-store bounds")
    store[b] = store[b] or {}
    if (store[b][k] or "") ~= old then return false end
    store[b][k] = new ~= "" and new or nil
    return true
end
clock, tg = 1000000, 0
os.time = function() return clock end
function time_global() return tg end
game = {CTime = function() return {set = function() end} end,
        get_game_time = function() return {diffSec = function() return 600000 end} end}
function command_line() return "" end
logs = {}
function printf(fmt, ...) logs[#logs + 1] = string.format(fmt, ...) end
-- players: id -> {char, name, server}
players = {}
function netcoop_actor_character(id) return players[id] and players[id].char or "" end
level = {object_by_id = function(id)
    local p = players[id]
    if not p then return nil end
    p.money = p.money or 1000
    return {character_name = function() return p.name end, character_icon = function() return "icon_" .. p.char end,
            money = function() return p.money end, give_money = function(_, n) p.money = p.money + n end,
            id = function() return id end, alive = function() return p.alive ~= false end,
            iterate_inventory = function(_, fn) for _, item in pairs(items) do if item.owner == id then fn(nil, item.obj) end end end,
            item_in_slot = function(_, slot) return slot == 8 and p.pda and items[p.pda] and items[p.pda].obj or nil end}
end}
-- PDAs (Devices): items[id] = { section, uid, owner = Actor id carrying it }
items = {}
function make_item(id, section, uid)
    local it = {section = section, uid = uid}
    it.obj = {id = function() return id end, section = function() return section end,
              parent = function() return it.owner and level.object_by_id(it.owner) or nil end}
    items[id] = it
    return it
end
local actor_by_id = level.object_by_id
level.object_by_id = function(id) if items[id] then return items[id].obj end return actor_by_id(id) end
function netcoop_item_uid(id) return items[id] and items[id].uid or "" end
se_vars = {}
function se_load_var(id, name, key) return se_vars[id] and se_vars[id][key] end
function se_save_var(id, name, key, v) se_vars[id] = se_vars[id] or {}; se_vars[id][key] = v end
function alife_object(id) return stashes[id] end
stashes = {}
function alife() return {level_name = function() return "l01_escape" end,
    object = function(_, name) for _, s in pairs(stashes) do if s:name() == name then return s end end end} end
function game_graph() return {vertex = function() return {level_id = function() return 1 end} end} end
level.name = function() return "l01_escape" end
treasure_manager = {caches = {}, filled = 0}
function treasure_manager.set_random_stash(no_spot, hint, bonus, id)
    assert(no_spot == true); treasure_manager.filled = treasure_manager.filled + 1; treasure_manager.caches[id] = "wpn_pm"
end
current_server = 1
function netcoop_players()
    local t = {}
    for id, p in pairs(players) do if p.server == current_server then t[#t + 1] = id end end
    table.sort(t)
    return table.concat(t, ",")
end
inbox = {}
function netcoop_send_to_actor(id, ch, data)
    assert(ch == "pdanet")
    inbox[id] = inbox[id] or {}
    table.insert(inbox[id], data)
end
''')
g.netcoop_transit = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_transit, (root / "server/netcoop_transit.script").read_text(encoding="utf-8"))
src = (root / "server/netcoop_pdanet.script").read_text(encoding="utf-8")
servers = []
for i in range(2):
    t = lua.table()
    lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()", t, src)
    servers.append(t)
    assert t.held_device is not None, 'physical-device API must be exported to the marks/map modules'
lua.execute(r'''
function take(id)  -- reassemble chunked messages -> list of {verb, value}
    local out, buf = {}, {}
    for _, d in ipairs(inbox[id] or {}) do
        local n, total, rest = string.match(d, "^(%d+)/(%d+)|(.*)$")
        buf[#buf + 1] = rest
        if n == total then
            local all = table.concat(buf); buf = {}
            all=all:gsub("^%d+@[%w_]+|", "")
            local verb, ser = string.match(all, "^(%a+)|(.*)$")
            local ok, v = pcall(netcoop_transit.deserialize, ser)
            out[#out + 1] = {verb, ok and v or ser}
        end
    end
    inbox[id] = {}
    return out
end
''')
g.netcoop_pdanet=servers[0]
g.netcoop_pda_storage=lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()", g.netcoop_pda_storage, (root/'server/netcoop_pda_storage.script').read_text(encoding='utf-8'))
take = g.take
def cmd(server, pid, text):
    g.current_server = server + 1
    assert text.startswith("pdanet ")
    g.tg += 1500  # a player types at most one post per 1.5 s here (flood limit)
    servers[server].command(pid, text[7:])  # netanomaly_server passes the arguments
    return [tuple(x.values()) for x in take(pid).values()]
def poll(server):
    g.current_server = server + 1
    g.tg += 2500
    servers[server].update_world()
def last(msgs, verb):
    got = [v for k, v in msgs if k == verb]
    assert got, (verb, msgs)
    return got[-1]

lua.execute('players[1] = {char = "a_1", name = "Bashka", server = 1}; players[2] = {char = "b_1", name = "Yura", server = 2}; players[3] = {char = "c_1", name = "Docent", server = 1}')
lua.execute('make_item(500, "device_pda_2", "u500"); players[1].pda=500; items[500].owner=1; make_item(502,"device_pda_1","u502"); players[2].pda=502; items[502].owner=2; make_item(503,"device_pda_1","u503"); players[3].pda=503; items[503].owner=3; make_item(700,"lz_pda_hack_usb","hack700"); items[700].owner=3; make_item(701,"lz_pda_hack_usb","hack701"); items[701].owner=9')
sa = last(cmd(0, 1, "pdanet hello"), "state")
sb = last(cmd(1, 2, "pdanet hello"), "state")
sc = last(cmd(0, 3, "pdanet hello"), "state")
ua, ub, uc = sa.uid, sb.uid, sc.uid
assert len({ua, ub, uc}) == 3 and all(len(u) == 6 and u.isdigit() for u in (ua, ub, uc))
assert last(cmd(0, 1, "pdanet hello"), "state").uid == ua  # stable

poll(0); poll(1)  # servers running: the first poll takes the current point
take(1); take(2); take(3)
# General channel: stranger shows as UID only; anonymous has no UID.
cmd(1, 2, "pdanet say 0 Hello stalkers")
poll(0)
gen = last([tuple(x.values()) for x in take(1).values()], "general")
m = gen[len(gen)]
assert m.x == "Hello stalkers" and m.f == ub and m.n is None
cmd(0, 3, "pdanet say 1 nobody knows me")
poll(1)
m = last([tuple(x.values()) for x in take(2).values()], "general")
assert m[len(m)].f == "" and m[len(m)].x == "nobody knows me"

# Contacts: a adds b -> name for a; online status only when mutual.
assert last(cmd(0, 1, "pdanet add 000000"), "err") in ("invalid UID", "no such UID")
st = last(cmd(0, 1, f"pdanet add {ub}"), "state")
c = st.contacts[1]
assert c.uid == ub and c.name == "Yura" and c.online is None
# Friend request (owner 2026-10-18): b on the other server is told, by name.
take(2); poll(1)
req = last([tuple(x.values()) for x in take(2).values()], "state").requests
assert req and req[1].uid == ua and req[1].name == "Bashka", 'b sees a friend request from a'
# c's request is declined: gone, c keeps b as a one-sided contact.
cmd(0, 3, f"pdanet add {ub}")
st = last(cmd(1, 2, f"pdanet deny {uc}"), "state")
assert len(st.requests) == 1 and st.requests[1].uid == ua, 'declined request removed'
st = last(cmd(1, 2, f"pdanet add {ua}"), "state")
assert len(st.requests) == 0, 'adding back accepts the request'
assert st.contacts[1].online is True
assert st.contacts[1].friend is True and st.contacts[1].actor_id is None, 'mutual friend on another location has no local map object'
g.players[2].server = 1
local_friend = last(cmd(0, 1, 'pdanet hello'), 'state').contacts[1]
assert local_friend.actor_id == 2 and local_friend.actor_name == 'Yura'
g.players[2].server = 2
st = last(cmd(0, 1, "pdanet hello"), "state")
assert st.contacts[1].online is True
g.clock += 200   # b silent for 200 s (no heartbeat): offline
st = last(cmd(0, 1, "pdanet hello"), "state")
assert st.contacts[1].online is False

# DM across servers, while b is "offline": stored, delivered on poll, unread counted.
r = cmd(0, 1, f"pdanet dm {ub}")
chat = last(r, "chat")
cid = chat.id
assert cid.startswith("d_")
cmd(0, 1, f"pdanet msg {cid} text Let's go hunting")
cmd(0, 1, f"pdanet msg {cid} point Hunting spot\tk00_marsh 10.5 0 -20")
assert last(cmd(0, 1, f"pdanet msg {cid} point Bad\tnope"), "err") == "bad point"
poll(1)  # b's server: first look after login takes the list as known
st = last(cmd(1, 2, "pdanet hello"), "state")
s = [x for x in st.chats.values() if x.id == cid][0]
assert s.unread == 2 and s.last.x.startswith("Hunting") and s.peer.name == "Bashka"
cmd(0, 1, f"pdanet msg {cid} text are you there?")
poll(1)
news = [v for k, v in [tuple(x.values()) for x in take(2).values()] if k == "new" and v.id == cid]
assert news and news[-1].msgs[1].x == "are you there?" and news[-1].msgs[1].n == "Bashka"
o = last(cmd(1, 2, f"pdanet open {cid}"), "chat")
assert [x.x for x in o.msgs.values()] == ["Let's go hunting", "Hunting spot", "are you there?"]
assert o.msgs[2].k == "point" and o.msgs[2].d == "k00_marsh 10.5 0 -20"
st = last(cmd(1, 2, "pdanet hello"), "state")
assert [x for x in st.chats.values() if x.id == cid][0].unread == 0

# A stranger cannot post into that chat.
assert last(cmd(0, 3, f"pdanet msg {cid} text intruder"), "err") == "no such chat"

# Groups: only contacts become members; deleting removes it for everybody.
cmd(0, 1, f"pdanet add {uc}")
st = last(cmd(0, 1, f"pdanet group Scientists|icon_sci|{ub},{uc},123456"), "state")
grp = [x for x in st.chats.values() if x.kind == "g"][0]
assert grp.name == "Scientists" and grp.members == 3
gid = grp.id
cmd(1, 2, f"pdanet msg {gid} text Reasonable!")
poll(0)
news = [v for k, v in [tuple(x.values()) for x in take(1).values()] if k == "new" and v.id == gid]
assert news and news[-1].msgs[1].x == "Reasonable!"  # (his own DM line may come too, in any order)
st = last(cmd(0, 3, "pdanet hello"), "state")
assert any(x.id == gid for x in st.chats.values())
cmd(0, 3, f"pdanet delete {gid}")
for pid, srv in ((1, 0), (2, 1), (3, 0)):
    st = last(cmd(srv, pid, "pdanet hello"), "state")
    assert not any(x.id == gid for x in st.chats.values()), pid
# Deleting a private chat removes it from my list only.
cmd(1, 2, f"pdanet delete {cid}")
assert not any(x.id == cid for x in last(cmd(1, 2, "pdanet hello"), "state").chats.values())
assert any(x.id == cid for x in last(cmd(0, 1, "pdanet hello"), "state").chats.values())

# Money: a pays b 300 in their private chat; b is on the other server.
assert last(cmd(0, 1, f"pdanet pay {cid} 5000"), "err") == "not enough money"
assert last(cmd(0, 1, f"pdanet pay {gid if False else cid} 0"), "err") == "bad amount"
assert last(cmd(0, 1, f"pdanet msg {cid} transfer fake	999999"), "err") == "bad message"
r = cmd(0, 1, f"pdanet pay {cid} 300")
assert last(r, "paid").amount == -300 and lua.eval("players[1].money") == 700
assert lua.eval("players[2].money or 1000") == 1000
poll(0)  # a's server does not pay b
assert lua.eval("players[2].money or 1000") == 1000
poll(1); poll(1)
assert lua.eval("players[2].money") == 1300  # once, by b's server
o = last(cmd(1, 2, f"pdanet open {cid}"), "chat")
t = o.msgs[len(o.msgs)]
assert t.k == "transfer" and t.d == "300" and t.own is False
# offline receiver: money waits in the store until his server sees him
lua.execute("players[2].server = 3")
cmd(0, 1, f"pdanet pay {cid} 100")
poll(1)
assert lua.eval("players[2].money") == 1300
lua.execute("players[2].server = 2")
poll(1)
assert lua.eval("players[2].money") == 1400 and lua.eval("players[1].money") == 600
# a group is not a private chat: no transfer there
assert last(cmd(0, 1, f"pdanet group Hunters|ui_mm_faction_dolg|{ub}"), "state")
hg = [x for x in last(cmd(0, 1, "pdanet hello"), "state").chats.values() if x.kind == "g"][0]
assert hg.icon == "ui_mm_faction_dolg"
assert last(cmd(0, 1, f"pdanet pay {hg.id} 10"), "err") == "no such chat"
mem = last(cmd(0, 1, f"pdanet members {hg.id}"), "members")
assert sorted(x.uid for x in mem.list.values()) == sorted([ua, ub]) and any(x.own for x in mem.list.values())
assert last(cmd(0, 3, f"pdanet members {hg.id}"), "err") == "no such chat"
st = last(cmd(0, 1, f"pdanet group Odd|bad/icon|{ub}"), "state")
assert all(x.icon in ("", "ui_mm_faction_dolg") for x in st.chats.values() if x.kind == "g")
# Notes
assert last(cmd(0, 1, "pdanet note new||"), "err") == "empty note"
n = last(cmd(0, 1, "pdanet note new|Hunt|Meet at the farm at 6"), "notes")
assert n[1].title == "Hunt" and n[1].text == "Meet at the farm at 6"
n = last(cmd(0, 1, "pdanet note new|Second|x"), "notes")
assert n[1].title == "Second" and n[2].title == "Hunt"
n = last(cmd(0, 1, f"pdanet note {n[2].id}|Hunt|Moved to 7"), "notes")
assert [x.text for x in n.values()] == ["x", "Moved to 7"]
n = last(cmd(0, 1, f"pdanet note_del {n[1].id}"), "notes")
assert [x.title for x in n.values()] == ["Hunt"]
assert len(last(cmd(0, 3, "pdanet notes"), "notes")) == 0  # someone else's: empty

# History survives a "restart": a fresh module instance reads the same store.
fresh = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()", fresh, src)
g.current_server = 1
fresh.command(1, f"open {cid}")
o = last([tuple(x.values()) for x in take(1).values()], "chat")
assert len(o.msgs) == 5  # 3 + two transfers

# Client: the server's real chunks through netcoop_pdanet_client.
client = lua.table()
lua.execute(r"""
db={actor=level.object_by_id(1)}
listeners_fired = 0
function netcoop_pure_client() return true end
function RegisterScriptCallback() end
game.translate_string = function(id) return "<" .. id .. ">" end
""")
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            client, (root / "client/netcoop_pdanet_client.script").read_text(encoding="utf-8"))
g.netcoop_pdanet_client = client
lua.execute("netcoop_pdanet_client.on_change(function() listeners_fired = listeners_fired + 1 end)")
g.current_server = 1
servers[0].command(1, "hello")
servers[0].command(1, f"open {cid}")
for chunk in list(g.inbox[1].values()):
    client.receive(chunk)
g.inbox[1] = lua.table()
assert client.me.uid == ua and client.me.name == "Bashka"
assert client.contacts[1] is not None and len(client.general) >= 2
assert client.opened.id == cid and len(client.opened.msgs) == 5
m = client.opened.msgs[1]
assert m.own is True and client.sender_name(m) == "Bashka"
anon = [x for x in client.general.values() if x.f == ""][0]
assert client.sender_name(anon) == "<st_pdanet_anonymous>"
assert client.when(lua.eval("{g = 60 * 24 * 31 + 75}")) == "01:15, 01.02.2012"
assert client.when_long(lua.eval("{g = 60 * 24 * 31 + 75}")) == "01:15, <st_pdanet_month_2> 1, 2012"
assert client.when_short(lua.eval("{g = 60 * 24 * 31 + 75}")) == "01.02  01:15"
assert client.dm_id(ub) == cid and client.contact_unread(ub) == 0
assert g.listeners_fired >= 2
# a chunked message (> 7000 bytes) is reassembled
big = "x" * 9000
lua.execute(f"netcoop_send_to_actor = netcoop_send_to_actor")
sent = []
data = "err|" + big
for n in range(2):
    client.receive(f"{n+1}/2|" + data[n*7000:(n+1)*7000])
assert client.last_error == big

# UI and configs: the tab script compiles; the strip and the strings exist.
ui = (root / "client/netcoop_pdanet_ui.script").read_text(encoding="utf-8")
assert lua.eval("function(s) return loadstring(s) ~= nil end")(ui)
import re, xml.etree.ElementTree as ET
pda = (root / "client/configs/ui/pda_16.xml").read_bytes().decode("cp1251")
ET.fromstring(pda.split("?>", 1)[1] if pda.startswith("<?xml") else pda)
ids = re.findall(r'<button [^>]*id="(\w+)"', pda)
assert ids == ["eptTasks", "eptTaskboard", "eptRanking", "eptRelations", "eptContacts", "eptEncyclopedia", "eptLogs"], ids
assert all('width="137"' in b for b in re.findall(r"<button [^>]*>", pda))
pdxml = (root / "client/configs/ui/ui_netcoop_pdanet.xml").read_bytes().decode("cp1251")
ET.fromstring(pdxml.split("?>", 1)[1])
for tpl in set(re.findall(r'xml:Init(?:Static|EditBox|3tButton)\("(\w+)"', ui)) | set(re.findall(r'static\(self, "(\w+)"', ui)) | {"row", "button"}:
    assert f"<{tpl} " in pdxml, tpl
used = set(re.findall(r'"(st_pdanet_[a-z_]+)"', ui + (root / "client/netcoop_pdanet_client.script").read_text(encoding="utf-8")))
used.discard("st_pdanet_month_")
used |= {f"st_pdanet_month_{i}" for i in range(1, 13)}
used |= {t + "_soon" for t in used if t.startswith("st_pdanet_tab_") and t not in ("st_pdanet_tab_general", "st_pdanet_tab_chats", "st_pdanet_tab_contacts", "st_pdanet_tab_map")}
used.add("st_pdanet_tab_map")
for lang in ("rus", "eng"):
    table = (root / f"client/configs/text/{lang}/st_netcoop.xml").read_bytes().decode("cp1251")
    missing = [k for k in used if f'id="{k}"' not in table]
    assert not missing, (lang, missing)
# Flood limit: six posts at once, then one per 1.5 s; reads are free.
g.tg += 60000
seq0 = lua.eval("netcoop_transit.deserialize(netcoop_store_read('pda_chat', 'general'))").seq
for i in range(10):
    servers[0].command(1, f"say 0 spam {i}")
seq1 = lua.eval("netcoop_transit.deserialize(netcoop_store_read('pda_chat', 'general'))").seq
assert seq1 - seq0 == 6, seq1 - seq0
servers[0].command(1, "hello")                      # not limited
g.tg += 1500
servers[0].command(1, "say 0 again")
assert lua.eval("netcoop_transit.deserialize(netcoop_store_read('pda_chat', 'general'))").seq == seq1 + 1
assert "too many messages" in (root / "server/netcoop_pdanet.script").read_text(encoding="utf-8")
# PDA password (owner 2026-10-18): set, locked state hides the network,
# wrong tries hold it, the right one opens it, the old one is needed to change.
g.tg += 60000
st = last(cmd(0, 1, "pdanet lockset |secret1"), "state")
assert st.has_lock and not st.locked
g.players[1].server = 0
lua.execute("players[1].server = 1")
srv = servers[0]
lua.execute("""for k in pairs(package.loaded) do end""")
# a new session (relog): the entity id is new, the PDA is locked again
lua.execute('players[9] = {char = "a_1", name = "Bashka", server = 1, pda = 500}; players[1].pda=nil; items[500].owner=9')
st = last(cmd(0, 9, "pdanet hello"), "state")
assert st.locked and len(st.contacts) == 0 and len(st.chats) == 0, "a locked PDA shows nothing"
assert last(cmd(0, 9, "pdanet notes"), "err") == "locked"
for _ in range(3):
    assert last(cmd(0, 9, "pdanet unlock nope"), "err") == "wrong password"
assert last(cmd(0, 9, "pdanet unlock secret1"), "err") == "pda held", "three wrong tries hold the PDA"
g.tg += 31000
st = last(cmd(0, 9, "pdanet unlock secret1"), "state")
assert not st.locked and len(st.contacts) > 0
assert last(cmd(0, 9, "pdanet lockset wrong|x123"), "err") == "wrong password"
st = last(cmd(0, 9, "pdanet lockset secret1|"), "state")
assert not st.has_lock, "removed with the old password"
assert "secret1" not in (lua.eval("netcoop_store_read('pda_lock', 'u500')") or ""), "never stored in clear"
# Devices (owner 2026-10-23): every PDA its own serial; someone else's PDA
# shows nothing of its holder's network, is hacked in time, shows what its
# owner had until it left him, and can be reset. An NPC's PDA keeps GAMMA's
# messages; hacking opens an encrypted one; its stash is filled here and
# marked for the reader until it is opened.
def drain(pid):
    return [tuple(x.values()) for x in take(pid).values()]
def poll_for(seconds, pids):
    out = {pid: [] for pid in pids}
    for _ in range(int(seconds / 2.5) + 1):
        poll(0)
        for pid in pids: out[pid] += drain(pid)
    return out
lua.execute('make_item(500, "device_pda_2", "u500"); players[9].pda = 500; items[500].owner = 9')
r = cmd(0, 9, "pdanet hello")
held = servers[0].held_device(9, "a_1")
assert held.uid == 'u500' and held.item == 500 and held.own
dev = last(r, "device")
assert dev.own and len(dev.serial) == 9 and dev.serial[4] == "-", dev.serial
serial = dev.serial
assert lua.eval("netcoop_store_read('pda_serial', '%s')" % serial) == "u500"
assert last(r, "state").uid == ua
# The PDA is taken from Bashka (his body): Docent carries it.
g.clock += 100
lua.execute('players[9].pda = nil; players[3].pda = 500; items[500].owner = 3')
r = cmd(0, 3, "pdanet hello")
st, dev = last(r, "state"), last(r, "device")
assert st.foreign and st.uid == "" and len(st.contacts) == 0, "someone else's PDA shows nothing of the holder"
assert not dev.own and not dev.hacked and dev.owner is None and dev.serial == serial and dev.level == 2
assert not any(k == "general" for k, _ in r), "nor the general channel"
assert last(cmd(0, 3, "pdanet notes"), "err") == "foreign device"
# Written to Bashka after his PDA left him: not on that device.
g.clock += 100
cmd(1, 2, f"pdanet msg {cid} text after the PDA was gone")
dev = last(cmd(0, 3, "pdanet hack"), "device")
assert dev.hack_total == 40000 and dev.hack_left == 40000
assert last(cmd(0, 3, "pdanet dump"), "err") == "not hacked"
got = poll_for(45, [3])[3]
assert any(k == "device" and v.hacked and v.owner == "Bashka" for k, v in got), got
d = last(cmd(0, 3, "pdanet dump"), "dump")
assert d.serial == serial and d.owner.name == "Bashka" and d.owner.uid == ua
texts = [m.x for c in d.chats.values() for m in c.msgs.values()]
assert "Let's go hunting" in texts and "after the PDA was gone" in texts, texts
assert any(c.uid == ub for c in d.contacts.values())
# Reset: the PDA serves Docent; his own network is back.
r = cmd(0, 3, "pdanet wipe")
assert last(r, "device").own and last(r, "state").uid not in (ua, uc), "factory reset gets a fresh network ID, not the holders other PDA"
# Taken away during a hack: the hack stops.
lua.execute('players[3].pda = nil; players[9].pda = 500; items[500].owner = 9')
poll(0); drain(9)
assert last(cmd(0, 9, "pdanet hack"), "device").hack_total == 40000
lua.execute('players[9].pda = nil')
got = poll_for(3, [9])[9]
assert ("err", "hack interrupted") in got, got
# Bashka's lock (he had a password): a PDA leaving him is slower to hack.
lua.execute('make_item(501, "device_pda_1", "u501"); players[9].pda = 501; items[501].owner = 9')
cmd(0, 9, "pdanet lockset |secret2")
poll(0)
lua.execute('players[9].pda = nil; players[3].pda = 501; items[501].owner = 3')
poll(0); drain(3)
assert last(cmd(0, 3, "pdanet hack"), "device").hack_total == (20 + 30) * 1000
cmd(0, 3, "pdanet hack_stop"); lua.execute('players[3].pda = 503')

# An NPC's encrypted PDA with a stash message.
lua.execute(r"""
stashes[77] = {id = 77, m_game_vertex_id = 1, name = function() return "esc_box_1" end}
treasure_manager.caches[77] = false
make_item(600, "itm_pda_rare", "u600"); items[600].owner = 3
se_vars[600] = {info = {state = "encrypted", contact = {name = "Dead Guy", comm = "stalker"},
    msg = {{stash = 77, stash_read = false, topic_title = "st_stash"}}}}
""")
n = last(cmd(0, 3, "pdanet npc_open 600"), "npc")
assert n.id == 600 and n.info.state == "encrypted" and n.level == 3
assert last(cmd(0, 3, "pdanet npc_open 500"), "err") == "no device", "only an NPC's PDA the player carries"
n = last(cmd(0, 3, "pdanet hack 600"), "npc")
assert n.hack_total == 60000
assert last(cmd(0, 3, "pdanet npc_stash 600 77 hint"), "err") == "no device", "encrypted: nothing to read"
got = poll_for(62, [3])[3]
assert any(k == "npc" and v.info.state == "default" for k, v in got), "hacked open"
assert lua.eval("se_vars[600].info.state") == "default", "GAMMA's storage on this server too"
info = lua.eval("netcoop_transit.deserialize(netcoop_store_read('pda_npc', 'u600'))")
assert info.state == "default" and info.msg[1].stash_name == "esc_box_1", "travels to other servers"
r = cmd(0, 3, "pdanet npc_stash 600 77 Stash of Dead Guy")
spot = last(r, "spot")
assert spot.id == 77 and spot.add and spot.h == "Stash of Dead Guy"
assert lua.eval("treasure_manager.filled") == 1 and lua.eval("treasure_manager.caches[77]") == "wpn_pm"
assert lua.eval("se_vars[600].info.msg[1].stash_read") is True
cmd(0, 3, "pdanet npc_stash 600 77 again")
assert lua.eval("treasure_manager.filled") == 1, "filled once"
lua.execute("treasure_manager.caches[77] = true")  # someone opened it
got = poll_for(12, [3])[3]
assert any(k == "spot" and v.id == 77 and not v.add for k, v in got), "the mark goes once it is opened"
assert lua.eval("netcoop_store_read('pda_stash', 'u503')") in ("", lua.eval("netcoop_transit.serialize({})"))
print("netcoop pdanet devices: serial, foreign PDA, hack, owner's data until it left him, reset, interrupted hack, NPC PDA, stash")
print("netcoop pdanet: OK")
