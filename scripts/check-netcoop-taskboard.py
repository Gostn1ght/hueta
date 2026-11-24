"""PDA task board, players' jobs (actual netcoop_taskboard with the actual
netcoop_transit serializer, Lua 5.1, owner 2026-10-18): posting takes the
reward from the poster at once; nobody takes his own job; one taker; the
poster confirms and the taker is paid through pda_pay (his location pays
it out); cancel returns the reward; a taker may drop it; per-player limit;
jobs expire after 7 days with a refund; never paid twice. The client's
board decodes the server's offers and jobs."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
lua.execute(r'''
store = {}
function netcoop_store_read(b, k)
    local value = (store[b] or {})[k] or ""
    if read_hook then read_hook(b, k, value) end
    return value
end
function netcoop_store_swap(b, k, old, new)
    store[b] = store[b] or {}
    if (store[b][k] or "") ~= old then return false end
    store[b][k] = new ~= "" and new or nil
    return true
end
clock = 1000000
os.time = function() return clock end
logs = {}
function printf(fmt, ...) logs[#logs + 1] = string.format(fmt, ...) end
players = {}
function netcoop_actor_character(id) return players[id] and players[id].char or "" end
level = {name = function() return "l01_escape" end}
function actor_of(id)
    local p = players[id]
    return {id = function() return id end, character_name = function() return p.name end,
            money = function() return p.money end, give_money = function(_, n) p.money = p.money + n end}
end
inbox = {}
function netcoop_send_to_actor(id, ch, data)
    assert(ch == "taskboard")
    inbox[id] = inbox[id] or {}
    table.insert(inbox[id], data)
end
''')
g.netcoop_transit = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            g.netcoop_transit, (root / "server/netcoop_transit.script").read_text(encoding="utf-8"))
board = lua.table()
lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()",
            board, (root / "server/netcoop_taskboard.script").read_text(encoding="utf-8"))
lua.execute('players[1] = {char = "a_1", name = "Bashka", money = 5000}; players[2] = {char = "b_1", name = "Yura", money = 100}')


def cmd(pid, text):
    g.db = lua.eval("{}")
    g.db.actor = g.actor_of(pid)
    g.inbox[pid] = lua.table()
    board.command(pid, text)
    return list(g.inbox[pid].values())


def jobs(pid):
    msgs = cmd(pid, "list")
    body = [m for m in msgs if m.startswith("jobs|")][-1][5:]
    return list(g.netcoop_transit.deserialize(body).values())


def money(pid):
    return g.players[pid].money


assert "job|posted" in cmd(1, "post 3000|Kill the dog|Near the farm")
assert money(1) == 2000, "the reward leaves the poster at once"
assert "jobfail|money" in cmd(1, "post 9000|Too much|x"), "no job beyond his money"
assert "jobfail|bad" in cmd(1, "post 10|| empty title")
j = jobs(2)
assert len(j) == 1 and j[0].title == "Kill the dog" and j[0].by_name == "Bashka" and not j[0].mine and not j[0].taken
jid = j[0].id
assert jobs(1)[0].mine
assert "jobfail|own" in cmd(1, f"take {jid}"), "nobody takes his own job"
assert "jobfail|own" in cmd(2, f"done {jid}"), "only the poster confirms"
assert "jobfail|notaken" in cmd(1, f"done {jid}"), "nothing to confirm before someone took it"
assert "job|take" in cmd(2, f"take {jid}")
assert jobs(1)[0].taken and jobs(1)[0].taker_name == "Yura" and jobs(2)[0].by_me
lua.execute('players[3] = {char = "c_1", name = "Docent", money = 0}')
assert "jobfail|taken" in cmd(3, f"take {jid}"), "one taker"
assert "job|done" in cmd(1, f"done {jid}")
pay = g.netcoop_transit.deserialize(g.store.pda_pay.b_1)
assert pay.sum == 3000 and money(2) == 100, "the taker is paid through pda_pay, not twice in place"
assert "jobfail|gone" in cmd(1, f"done {jid}") and g.netcoop_transit.deserialize(g.store.pda_pay.b_1).sum == 3000, "never paid twice"
assert len(jobs(1)) == 0

# Cancel returns the reward; a taker may drop.
cmd(1, "post 500|Bring vodka|")
jid = jobs(2)[0].id
assert "job|take" in cmd(2, f"take {jid}") and "job|drop" in cmd(2, f"drop {jid}") and not jobs(1)[0].taken
assert money(1) == 1500 and "job|cancel" in cmd(1, f"cancel {jid}") and money(1) == 2000, "cancel refunds"

# Per-player limit; expiry after 7 days refunds through pda_pay.
for n in range(5):
    assert "job|posted" in cmd(1, f"post 10|Job {n}|")
assert "jobfail|limit" in cmd(1, "post 10|Job 6|")
lua.execute("clock = clock + 8 * 86400")
assert len(jobs(2)) == 0
assert g.netcoop_transit.deserialize(g.store.pda_pay.a_1).sum == 50, "expired jobs refund the poster"

# The client's board decodes the server's offers (pdanet decoder).
client = lua.table()
lua.execute("""local env = ...
env.game = {translate_string = function(s) return s end}
env.class = function(name) return function() env[name] = {} end end
env.netcoop_pdanet_client = {decode = function(t) return netcoop_transit.deserialize(t) end}
setfenv(assert(loadstring(select(2, ...))), setmetatable(env,{__index=_G}))()""",
            client, (root / "client/netcoop_taskboard_client.script").read_text(encoding="utf-8"))
offers = lua.eval('{{c="fetch", n=7, t="esc_task_1", d="Bring 3 meat", tt="Meat", td="for Wolf", ti="", b=false}}')
client.receive("1/1|" + g.netcoop_transit.serialize(offers))
cmd(2, "post 0|x|y")  # a job for the client list
client.receive("jobs|" + g.netcoop_transit.serialize(g.netcoop_transit.deserialize(
    [m for m in cmd(2, "list") if m.startswith("jobs|")][-1][5:])))
rows = client.get_rows()
assert rows.fetch[1].task_id == "esc_task_1" and rows.fetch[1].details.task_title == "Meat" and rows.fetch[1].npc_id == 7
assert client.get_jobs()[1].title == "x"
print("PASS task board: players' jobs escrow, one taker, poster confirms, pda_pay reward once, cancel/drop/limit/expiry; client decodes offers")

# Two location servers can interleave between authorization and removal.
# Drop the taker immediately after the author reads the accepted job image.
lua.execute('store={};players[1].money=1000;players[2].money=100')
assert 'job|posted' in cmd(1, 'post 100|Race|test')
race_id = jobs(1)[0].id
assert 'job|take' in cmd(2, f'take {race_id}')
lua.execute('''
local target = ...
read_hook=function(bucket,key,text)
 if bucket=='jobs' and key==target then
  read_hook=nil
  local changed=netcoop_transit.deserialize(text)
  changed.taker=nil;changed.taker_name=nil
  store.jobs[key]=netcoop_transit.serialize(changed)
 end
end
''', race_id)
assert 'jobfail|busy' in cmd(1, f'done {race_id}')
assert len(jobs(1)) == 1 and not jobs(1)[0].taken
assert not g.store.pda_pay and money(1) == 900 and money(2) == 100
# A later fresh confirmation succeeds once after a new acceptance.
assert 'job|take' in cmd(2, f'take {race_id}')
assert 'job|done' in cmd(1, f'done {race_id}')
assert g.netcoop_transit.deserialize(g.store.pda_pay.b_1).sum == 100
assert 'jobfail|gone' in cmd(1, f'done {race_id}')

# A replacement record under the same key cannot inherit old authorization.
assert 'job|posted' in cmd(1, 'post 30|Old owner|test')
replacement_id = jobs(1)[0].id
before_cancel = money(1)
lua.execute('''
local target=...
read_hook=function(bucket,key,text)
 if bucket=='jobs' and key==target then
  read_hook=nil
  local changed=netcoop_transit.deserialize(text);changed.by='other'
  store.jobs[key]=netcoop_transit.serialize(changed)
 end
end
''', replacement_id)
assert 'jobfail|busy' in cmd(1, f'cancel {replacement_id}')
assert money(1) == before_cancel
assert g.netcoop_transit.deserialize(g.store.jobs[replacement_id]).by == 'other'

# Five own jobs sorted behind sixty other jobs must still prevent a sixth.
lua.execute('''
store={jobs={}};local ids={}
for i=1,65 do
 local id='j'..tostring(10000000+i)
 ids[id]=true
 store.jobs[id]=netcoop_transit.serialize({id=id,by=i<=60 and 'other' or 'a_1',
  by_name='Poster',title='Fixture',text='',reward=0,at=clock,level='l01_escape'})
end
store.jobs.index=netcoop_transit.serialize({ids=ids})
''')
assert len(jobs(1)) == 60 and not any(j.mine for j in jobs(1))
assert 'jobfail|limit' in cmd(1, 'post 0|Sixth|hidden own records')
assert sum(1 for _ in g.netcoop_transit.deserialize(g.store.jobs.index).ids.items()) == 65
lua.execute('clock=clock+8*86400')
assert 'job|posted' in cmd(1, 'post 0|After expiry|allowed')
print('PASS task board: exact authorized CAS image survives concurrent drop; per-player limit includes jobs beyond the display cap')

# Expiry must remove the expired image, not a newer replacement at that key.
lua.execute('''
store={jobs={}};local id='j12345678'
store.jobs[id]=netcoop_transit.serialize({id=id,by='a_1',reward=75,
 title='Old',text='',at=clock-8*86400})
store.jobs.index=netcoop_transit.serialize({ids={[id]=true}})
read_hook=function(bucket,key,text)
 if bucket=='jobs' and key==id then
  read_hook=nil
  local fresh=netcoop_transit.deserialize(text)
  fresh.by='b_1';fresh.at=clock;fresh.reward=125;fresh.title='Fresh'
  store.jobs[key]=netcoop_transit.serialize(fresh)
 end
end
''')
jobs(1)
fresh = g.netcoop_transit.deserialize(g.store.jobs.j12345678)
assert fresh.by == 'b_1' and fresh.reward == 125 and fresh.title == 'Fresh'
assert g.netcoop_transit.deserialize(g.store.jobs.index).ids.j12345678
assert not g.store.pda_pay
assert len(jobs(1)) == 1 and jobs(1)[0].title == 'Fresh'
lua.execute('clock=clock+8*86400')
assert len(jobs(1)) == 0
assert g.netcoop_transit.deserialize(g.store.pda_pay.b_1).sum == 125
assert len(jobs(1)) == 0 and g.netcoop_transit.deserialize(g.store.pda_pay.b_1).sum == 125
print('PASS expiry uses the evaluated image: concurrent replacement survives, fresh expiry refunds once')
