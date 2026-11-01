"""Actual character Lua restore: live condition persistence vs a fresh body."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
source = (root / 'scripts/netcoop-overlay/server/netcoop_server_compat.script').read_text(encoding='cp1251')
code = source[source.index('function capture_character_state('):source.index('local function install_player_tasks()')]
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute('''
db={storage={[7]={pstor={rank=42,netcoop_player_state='satiety=0;power=0.1;'},pstor_ctime={stamp=99}}}}
player_tasks={};restored_players={};first_seen={};state_sent={};sent={};clock=0
function time_global() return clock end
function netcoop_send_to_actor(id,channel,data) sent[#sent+1]={id=id,channel=channel,data=data} end
god,ammo=true,true
function netcoop_admin_god_enabled() return god end
function netcoop_admin_ammo_enabled() return ammo end
function netcoop_admin_god_set(id,v) god=v end
function netcoop_admin_ammo_set(id,v) ammo=v end
marshal={encode=function(s) return s end,decode=function(s) return s end}
task_manager={save_state=function(s) s.task='retained' end,
 load_state=function(s) assert(s.task=='retained') end,CRandomTask=function() return {} end}
actor={radiation=0.9,psy_health=0,id=function() return 7 end,alive=function() return true end}
''')
lua.execute(code)
handoff = source[source.index('send_player_state = function('):source.index('local function send_owner_spots()')]
lua.execute(handoff)
lua.execute('''
local living=capture_character_state(actor)
god,ammo=false,false
restore_character_state(actor,living,false)
assert(god and ammo,'admin toggles must travel in the server-owned character snapshot')
clock=60000;send_player_state(7);assert(#sent==0,'time cannot unlock an incomplete restore')
character_ready(actor,false);assert(restored_players[7] and #sent==2)
assert(sent[1].channel=='netcoop_admin_state' and sent[1].data=='1|1')
assert(sent[2].channel=='player_state' and sent[2].data:sub(1,3)=='@7|')
assert(actor.radiation==0.9 and actor.psy_health==0)
assert(db.storage[7].pstor.netcoop_player_state=='satiety=0;power=0.1;','a living reconnect keeps hunger/stamina/thirst')
-- A legacy death save did not carry the Lua respawn flag.
restore_character_state(actor,living,true)
assert(not god and not ammo,'new life does not inherit admin toggles')
assert(actor.radiation==0 and actor.psy_health==1)
actor.alive=function() return false end;actor.radiation=1;actor.psy_health=0
local dead=capture_character_state(actor)
assert(dead.netcoop_respawn and dead.netcoop_conditions.radiation==0 and dead.netcoop_conditions.psy_health==1)
dead.pstor.netcoop_player_state='satiety=0;power=0.1;';dead.pstor['health.head']=0;dead.pstor['timedhp.head']=9
restore_character_state(actor,dead)
assert(actor.radiation==0 and actor.psy_health==1)
assert(db.storage[7].pstor['health.head']==nil and db.storage[7].pstor['timedhp.head']==nil,'new body drops raw BHS limb state too')
assert(db.storage[7].pstor.netcoop_player_state==nil,'a new body starts fed and rested, not as the old one died')
assert(db.storage[7].pstor.rank==42 and db.storage[7].pstor_ctime.stamp==99)
assert(not restored_players[7] and player_tasks[7])
local previous=#sent;clock=120000;state_sent[7]=nil;send_player_state(7);assert(#sent==previous)
character_ready(actor,false);assert(restored_players[7] and sent[#sent].data=='@7|-')
''')
print('PASS actual respawn state: new/legacy dead bodies reset lethal conditions and the old hunger/stamina/thirst; living saves and progress retained')
