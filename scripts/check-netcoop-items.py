"""Execute the actual server-run item action Lua (stage 3) in Lua 5.1."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
client = (root/'scripts/netcoop-overlay/client/netcoop_client_compat.script').read_text(encoding='cp1251')
server = (root/'scripts/netcoop-overlay/server/netcoop_server_compat.script').read_text(encoding='cp1251')
lua = LuaRuntime(unpack_returned_tuples=True)

# Both whole files must compile.
for name, source in (('client', client), ('server', server)):
    ok, err = lua.eval('function(s) local f, e = loadstring(s); return f ~= nil, e end')(source)
    assert ok, f'{name} compat does not compile: {err}'

lua.execute(r'''
function printf() end
game={translate_string=function(s) return s end}
created={}; released={}
function alife_create_item(sec, parent, t) created[#created+1]={sec=sec, parent=parent, cond=t and t.cond} end
function alife_release(obj) released[#released+1]=obj:id() end
local function item(id, sec, cond)
  local o={_id=id,_sec=sec,_cond=cond}
  function o:id() return self._id end
  function o:section() return self._sec end
  function o:condition() return self._cond end
  function o:set_condition(c) self._cond=c end
  return o
end
objects={}
level={object_by_id=function(id) return objects[id] end}
db={actor={id=function() return 91 end}}
item_device={device_battery='batteries_dead', dev_consumption={device_pda_1={}}, dev_critical={device_pda_1=0.1}}
functors={device_pda_1={use2_action_functor='item_device.func_battery'}}
ini_sys={r_string_ex=function(_, sec, key) return functors[sec] and functors[sec][key] end}
unpacked=nil
item_device.func_battery=function(obj) unpacked=obj:id() end
make_item=item
''')
start = server.index('local SERVER_MENU_ACTIONS')
lua.execute(server[start:])
lua.execute(r'''
local battery=make_item(5,'batteries_dead',0.8); objects[5]=battery
local pda=make_item(6,'device_pda_1',0.12); objects[6]=pda
assert(item_action(91,1,5,6,'battery_swap')=='')
assert(pda:condition()==0.8,'device takes the battery charge')
assert(#released==1 and released[1]==5,'the battery is used up')
assert(#created==1 and created[1].cond==0.12 and created[1].parent==db.actor,'the old charge comes back as a battery')
local weak=make_item(7,'batteries_dead',0.3); objects[7]=weak
assert(item_action(91,1,7,6,'battery_swap')=='ui_st_battery_more_power','a weaker battery is refused')
assert(#released==1)
local flat=make_item(8,'device_pda_1',0.05); objects[8]=flat
local full=make_item(9,'batteries_dead',1.0); objects[9]=full
assert(item_action(91,1,9,8,'battery_swap')=='' and #created==1,'a flat device returns no battery')
assert(item_action(91,0,6,65535,'item_device.func_battery')=='' and unpacked==6,'whitelisted menu action runs')
assert(item_action(91,0,6,65535,'item_device.other')~='','unlisted functor is refused')
functors.device_pda_1.use2_action_functor=nil
assert(item_action(91,0,6,65535,'item_device.func_battery')~='','functor must belong to the item section')
assert(item_action(91,1,5,404,'battery_swap')~='','missing target')
''')

# Server repair: GAMMA's formula, kit range, parts, kit use.
lua.execute(r'''
function clamp(v,a,b) if v<a then return a elseif v>b then return b end return v end
items_of={repair_kit={'repair'}, wpn_ak74={'weapon'}, wpn_part={'part'}}
function IsItem(typ, sec, obj) sec=sec or obj:section(); for _,t in ipairs(items_of[sec] or {}) do if t==typ then return true end end; return false end
kits={repair_kit={repair_only='wpn_ak74', repair_min_condition=0.2, repair_max_condition=0.9, repair_add_condition=0.25,
  repair_use_parts=true, repair_parts_sections='wpn_part', repair_parts_multi=1}}
function parse_list(_, sec, key) local v=kits[sec] and kits[sec][key]; if not v then return nil end; return {[v]=true} end
ini_sys.r_float_ex=function(_, sec, key) return kits[sec] and kits[sec][key] or (sec=='wpn_part' and key=='repair_part_bonus' and 0.1) or nil end
ini_sys.r_bool_ex=function(_, sec, key, d) local v=kits[sec] and kits[sec][key]; if v==nil then return d end; return v end
discharged={}; degraded={}
utils_item={get_cond_static=function(c) return c end, discharge=function(o) discharged[#discharged+1]=o:id() end,
  degrade=function(o,n) degraded[#degraded+1]={o:id(),n} end}
''')
lua.execute(r'''
local kit=make_item(40,'repair_kit',1); objects[40]=kit
local ak=make_item(41,'wpn_ak74',0.43); objects[41]=ak
local part=make_item(42,'wpn_part',1); objects[42]=part
part.parent=function() return {id=function() return 91 end} end
assert(item_action(91,1,40,41,'repair 65535')=='')
assert(math.abs(ak:condition()-0.68)<1e-6,'43% + 25% without a part: '..ak:condition())
assert(#degraded==1 and degraded[1][1]==40,'single-use kit degrades')
ak:set_condition(0.43)
assert(item_action(91,1,40,41,'repair 42')=='')
assert(math.abs(ak:condition()-0.78)<1e-6,'part adds its 10% bonus: '..ak:condition())
assert(#discharged==1 and discharged[1]==42,'the part is used')
ak:set_condition(0.95)
assert(item_action(91,1,40,41,'repair 65535')~='','above the kit range refused')
local other=make_item(43,'wpn_ak74',0.5); objects[43]=other
other.parent=function() return {id=function() return 7 end} end
ak:set_condition(0.43)
assert(item_action(91,1,40,41,'repair 43')~='','a part of another player refused')
assert(item_action(91,1,41,40,'repair 65535')~='','a non-kit refused')
''')

# Client: menu routing and the battery drop replacement.
lua.execute(r'''
sent={}
function netcoop_item_action(kind,item,target,action) sent[#sent+1]={kind,item,target,action}; return true end
function netcoop_pure_client() return true end
callbacks={}
function RegisterScriptCallback(name,fn) callbacks[name]=callbacks[name] or {}; callbacks[name][fn]=true end
function UnregisterScriptCallback(name,fn) if callbacks[name] then callbacks[name][fn]=nil end end
EDDListType={iActorBag=1,iActorSlot=2}
actor_menu={set_msg=function() msg=true end}
actor_effects={play_item_fx=function() end}; utils_obj={play_sound=function() end}
original_called=0
ui_inventory={UIInventory={Action_Custom=function() original_called=original_called+1 end}}
functors.device_pda_1.use2_action_functor='item_device.func_battery'
functors.food={use1_action_functor='itms_manager.eat'}
local function on_item_drag_dropped() local_drop_called=true end
local_drop=on_item_drag_dropped
item_device.on_game_start=function() RegisterScriptCallback("ActorMenu_on_item_drag_drop", on_item_drag_dropped) end
item_device.on_game_start()
''')
start = client.index('local SERVER_ITEM_ACTIONS')
end = client.index('\nfunction on_game_start()', start)
lua.execute(client[start:end] + '\ninstall_items = install_server_item_actions\ninstall_server_item_actions()')
lua.execute(r'''
local ui=ui_inventory.UIInventory
local wnd=setmetatable({CheckItem=function(_,o) return o end,On_Item_Update=function() end},{__index=ui})
wnd:Action_Custom(objects[6],nil,nil,2)
assert(#sent==1 and sent[1][1]==0 and sent[1][2]==6 and sent[1][4]=='item_device.func_battery' and original_called==0)
wnd:Action_Custom(make_item(20,'food',1),nil,nil,1)
assert(#sent==1 and original_called==1,'other actions still run on the client')
local drops=callbacks.ActorMenu_on_item_drag_drop
local replacement=nil
for fn in pairs(drops) do replacement=fn end
assert(replacement and not drops[local_drop],'local battery handler replaced')
replacement(make_item(30,'batteries_dead',0.9),objects[6],1,2)
assert(#sent==2 and sent[2][1]==1 and sent[2][2]==30 and sent[2][3]==6 and sent[2][4]=='battery_swap')
replacement(make_item(31,'batteries_dead',0.1),objects[6],1,2)
assert(#sent==2 and msg,'weaker battery refused locally with the GAMMA message')
replacement(make_item(32,'batteries_dead',0.9),objects[6],3,2)
assert(#sent==2,'only from the backpack')
''')
lua.execute(r'''
item_repair={UIRepair={OnRepair=function() local_repair=true end}}
install_items()
local sel={GetCell_Selected=function() return objects[41] end}
local none={GetCell_Selected=function() return nil end}
local w={CC={sel,none},obj=objects[40],con_val={[4]=68},OnCancel=function() closed=true end}
item_repair.UIRepair.OnRepair(w)
assert(not local_repair and sent[#sent][1]==1 and sent[#sent][2]==40 and sent[#sent][3]==41 and sent[#sent][4]=='repair 65535' and closed)
assert(objects[41]:condition()==0.43,'the client does not repair by itself')
''')
# Stage 5 / plan section 7: NPC inventory at spawn, every wearing item conditioned, nothing regenerated at death.
lua.execute(r'''
vars={}
function se_load_var(id,name,key) return vars[id..key] end
function se_save_var(id,name,key,v) vars[id..key]=v end
function character_community() return "stalker" end
ranks={get_obj_rank_name=function() return "veteran" end}
local mcm={["dph_loot_cond/weapon/veteran_min"]=55,["dph_loot_cond/weapon/veteran_max"]=90,
  ["dph_loot_cond/outfit/veteran_min"]=40,["dph_loot_cond/outfit/veteran_max"]=70}
ui_mcm={get=function(k) return mcm[k] end}
function IsWeapon(o) return o._sec=='wpn_ak74' end
function IsAmmo(o) return o._sec=='ammo_545' end
function IsOutfit(o) return o._sec=='outfit_sun' end
function IsHeadgear(o) return o._sec=='helm_sun' end
function IsStalker() return true end
now_ms=0
function time_global() return now_ms end
function any_player() return nil end
function bind_actor() end
function get_object_story_id(id) return id==99 and 'trader' or nil end
item_device.dev_consumption={device_torch={}}
db.storage={}
function RegisterScriptCallback(name,fn) callbacks[name]=callbacks[name] or {}; callbacks[name][fn]=true end
npcs={}
function npc(id)
  local inv={make_item(id*10+1,'wpn_ak74',1), make_item(id*10+2,'outfit_sun',1), make_item(id*10+3,'device_torch',1), make_item(id*10+4,'bread',1)}
  local n={_inv=inv,id=function() return id end,name=function() return 'npc'..id end,alive=function() return true end,
    spawn_ini=function() return nil end,
    iterate_inventory=function(self,fn,o) for _,i in ipairs(inv) do fn(o,i) end end}
  npcs[id]=n; objects[id]=n
  return n
end
generated=0; made_loot=0
death_manager={get_items_by_npc=function() return nil end,
  try_spawn_ammo=function(n) local a=make_item(n:id()*10+5,'ammo_545',1); a._count=120
    a.ammo_get_count=function(self) return self._count end; a.ammo_set_count=function(self,c) self._count=c end
    table.insert(n._inv, a) generated=generated+1 end,
  try_spawn_powders=function() end, try_spawn_bullets=function() end, try_spawn_casings=function() end,
  try_spawn_sin_artefacts=function() end,
  create_item_list=function(n) table.insert(n._inv, make_item(n:id()*10+6+generated,'medkit',1)) generated=generated+1 end,
  set_weapon_drop_condition=function(n,i) i:set_condition(0.99) end}
death_manager.create_release_item=function(n) made_loot=made_loot+1; vars[n:id()..'death_dropped']=true
  death_manager.try_spawn_ammo(n); death_manager.create_item_list(n)
  n:iterate_inventory(function(_,i) if IsWeapon(i) then death_manager.set_weapon_drop_condition(n,i) end end, n) end
level.object_by_id=function(id) return objects[id] end
''')
start = server.index('local WORLD_SEED')
end = server.index('\nfunction on_game_start()', start)
lua.execute(server[start:end] + '\nspawned, process, death_loot, cond_items = on_npc_net_spawn, process_pending_inventory, on_npc_death_loot, condition_npc_items\ninstall_npc_loot()')
lua.execute(r'''
local a=npc(3)
spawned(a); now_ms=2000; process()
assert(#a._inv==7 and generated==3,'inventory made at spawn: ammo + community + private items, got '..#a._inv)
now_ms=4000; process()
local w,o,d,b=a._inv[1]:condition(),a._inv[2]:condition(),a._inv[3]:condition(),a._inv[4]:condition()
assert(w>=0.55 and w<=0.90,'weapon by rank: '..w)
assert(o>=0.40 and o<=0.70,'armour by rank: '..o)
assert(d>=0.15 and d<=0.90,'device battery: '..d)
assert(b==1,'food keeps GAMMA condition')
-- the same NPC id in another world gets the same items and conditions
local saved_w=w; vars={}; objects[3]=nil; local a2=npc(3); generated=0
spawned(a2); now_ms=6000; process(); now_ms=8000; process()
assert(a2._inv[1]:condition()==saved_w,'seeded per NPC')
-- it lives: the weapon wears, a medkit is used
a2._inv[1]:set_condition(0.31); table.remove(a2._inv)
local before=#a2._inv
death_loot(a2)
assert(made_loot==1 and #a2._inv==before,'nothing generated at death')
local ammo; for _,i in ipairs(a2._inv) do if i._sec=='ammo_545' then ammo=i end end
assert(ammo and ammo._count>=6 and ammo._count<=30,'corpse keeps at most one box of ammo: '..(ammo and ammo._count or -1))
assert(a2._inv[1]:condition()==0.31,'weapon keeps its real condition')
death_loot(a2); assert(made_loot==1,'death routine only once')
-- story NPC (trader): no spawn inventory, GAMMA loot at death
local t=npc(99); spawned(t); now_ms=10000; process(); now_ms=12000; process()
assert(#t._inv==4,'story NPC keeps its own inventory')
death_loot(t); assert(#t._inv==6,'story NPC: GAMMA loot at death')
''')

# Player-owned furniture and stashes: place rules, owner-only access, pickup, stash pack-up.
lua.execute(r'''
state={}
alife_storage_manager={get_state=function() return state end}
function vector() local v={x=0,y=0,z=0}
  function v:set(x,y,z) self.x,self.y,self.z=x,y,z; return self end
  function v:distance_to(o) return math.sqrt((self.x-o.x)^2+(self.y-o.y)^2+(self.z-o.z)^2) end
  return v end
roof=true
rq_target={rqtStatic=1}
function ray_pick() local r={} function r:set_position() end function r:set_direction() end function r:set_range() end
  function r:set_flags() end function r:query() return roof end return r end
safe_zone={inside=function(_,p) return p.x>100 end}
db.zone_by_name={bar_sr_no_assault=safe_zone, some_restrictor={inside=function() return true end}}
function get_story_object() return nil end
sent={}; function netcoop_send_to_actor(a,c,d) sent[#sent+1]={a,c,d} end
function SendScriptCallback() end
created={}; next_id=500
function alife_create(sec,pos) next_id=next_id+1; created[#created+1]=sec; return {id=next_id} end
function alife_create_item(sec,parent) created[#created+1]=sec end
function alife_object(id) return {id=id} end
function alife_release(o) released[#released+1]= type(o.id)=='function' and o:id() or o.id end
function strformat(f,...) return string.format(f,...) end
game.translate_string=function(s) return s=='st_itm_stash_of_character' and '%s stash' or s end
function clamp(v,a,b) return math.max(a,math.min(b,v)) end
local function actor() local a=make_item(91,'actor',1)
  function a:position() return vector():set(0,0,0) end
  function a:level_vertex_id() return 1 end; function a:game_vertex_id() return 1 end
  function a:character_name() return 'Ivan' end; return a end
player=actor(); objects[91]=player
placed=nil
placeable_furniture={create_object=function(sec,pos) placed={sec=sec,pos=pos}; next_id=next_id+1; return next_id end,
  transfer_item_data=function() end}
functors.chair_item={}
ini_sys.r_string_ex=function(_,sec,key) if sec=='chair_item' and key=='placeable_section' then return 'chair_phy' end
  return functors[sec] and functors[sec][key] end
picked=false
bind_hf_base={get_wrapper=function(id) return {is_pickupable=function() return true end, pickup=function() picked=true end} end}
clsid={inventory_box=7}
ini_sys.section_exist=function() return true end
''')
start = server.index('-- Player-owned objects: furniture and backpack stashes')
start = server.rfind('------', 0, start)
end = server.index('\nfunction item_action(', start)
lua.execute(server[start:end] + '\nf_place, f_pick, s_create, box_changed, access, owned_t = furniture_place, furniture_pickup, stash_create, on_box_changed, can_access, owned')
lua.execute(r'''
local chair=make_item(60,'chair_item',1); objects[60]=chair
assert(f_place(player, chair, "1.00 0.00 2.00 0.000 0.000 0.000", "ivan")=='', 'indoor placement works')
assert(placed and placed.sec=='chair_phy')
local id=next_id
assert(owned_t()[id].owner=='ivan' and access(id,'ivan') and not access(id,'petr'),'owner only')
assert(access(12345,'petr'),'unowned objects stay open')
roof=false
assert(f_place(player, chair, "1.00 0.00 2.00 0.000 0.000 0.000", "ivan")=='furniture can be placed only indoors')
roof=true
assert(string.find(f_place(player, chair, "150.00 0.00 2.00 0 0 0", "ivan"), 'too far'),'reach')
player.position=function() return vector():set(149,0,2) end
assert(string.find(f_place(player, chair, "150.00 0.00 2.00 0 0 0", "ivan"), 'safe zone'),'safe zone refused')
player.position=function() return vector():set(0,0,0) end
local obj=make_item(id,'chair_phy',1); obj.clsid=function() return 0 end
assert(f_pick(player, obj, "petr")~='','only the placer picks it up')
assert(f_pick(player, obj, "ivan")=='' and picked and owned_t()[id]==nil)
-- Legacy saved stashes without an embedded physical bag still pack once.
local stash=next_id+1
owned_t()[stash]={kind='stash',section='itm_stash_pack',owner='ivan'}
local box=make_item(stash,'inv_backpack',1); box.is_inv_box_empty=function() return true end; objects[stash]=box
netcoop_backpack_stash={changed=function() return false end}
box_changed(stash, 91)
assert(owned_t()[stash]==nil and created[#created]=='itm_stash_pack' and sent[#sent][2]=='stash_spot_remove')
''')

# Player state: encoding, restore on the client, reports only after restore, sleep need off.
lua.execute(r'''
cmds={}; function netcoop_command(t) cmds[#cmds+1]=t end
now_ms=0
actor_obj={satiety=0.2, power=0.9,id=function() return 91 end}
zzz_player_injuries={maxhp={},health={},timedhp={}}
for _,limb in ipairs({'head','torso','leftarm','rightarm','leftleg','rightleg'}) do zzz_player_injuries.maxhp[limb]=100 end
db.actor=actor_obj
loaded=nil
actor_status_thirst={save_state=function(m) m.drink={last_drink=42, chk_drink={Y=2012,M=5,D=1}} end,
  load_state=function(m) loaded=m.drink end}
toggled={}
actor_status_sleep={toggle_feature=function(v) toggled[#toggled+1]=v end}
''')
start = client.index('local PLAYER_STATE_MODULES')
end = client.index('local function install_server_item_actions()', start)
lua.execute('player_state_spawn_ready=true;next_player_state=0;\n'+client[start:end] + '\nps_report = report_player_state')
lua.execute(r'''
ps_report(); assert(#cmds==1 and cmds[1]=='player_state get','only restore request before saved state');cmds={}
use_player_state("satiety=0.75;power=0.5;modules={actor_status_thirst={drink={last_drink=1200;chk_drink={Y=2012;};};};};")
assert(actor_obj.satiety==0.75 and actor_obj.power==0.5 and loaded and loaded.last_drink==1200 and loaded.chk_drink.Y==2012)
now_ms=40000; ps_report()
local reports={};for _,c in ipairs(cmds) do if c~='player_state ack' and c~='player_state get' then reports[#reports+1]=c end end;assert(#reports==1 and string.find(reports[1],"^player_state ") and string.find(reports[1],"last_drink=42",1,true))
use_player_state("-"); use_player_state("broken{{")
disable_sleep_need(); disable_sleep_need()
actor_status_sleep.toggle_feature(true)
assert(toggled[1]==false and toggled[2]==false and #toggled==2,'sleep need stays off')
''')

# Companions follow the player who recruited them, wait while that player is offline.
lua.execute(r'''
online="91 "
logins={[91]="ivan",[92]="petr",[95]="ivan"}
function netcoop_players() return online end
function netcoop_actor_login(id) return logins[id] or "" end
squads={}
function get_object_squad(npc) return npc.squad end
axr_companions={companion_squads={},
  add_to_actor_squad=function(npc) axr_companions.companion_squads[npc.squad.id]=npc.squad end,
  add_special_squad=function(squad) axr_companions.companion_squads[squad.id]=squad end,
  remove_from_actor_squad=function(npc) axr_companions.companion_squads[npc.squad.id]=nil end}
sim_squad_scripted={sim_squad_scripted={get_script_target=function(self) if axr_companions.companion_squads[self.id] then return 0 end return 77 end}}
''')
start = server.index('-- Companions belong to the player who recruited them')
start = server.rfind('------', 0, start)
end = server.index('\nfunction on_game_start()', start)
lua.execute(server[start:end] + '\ninstall_companions()')
lua.execute(r'''
local cls=sim_squad_scripted.sim_squad_scripted
local squad={id=300}; local npc={squad=squad}
db.actor={id=function() return 91 end}
axr_companions.add_to_actor_squad(npc)
assert(cls.get_script_target(squad)==91,'goes to its recruiter, not AC_ID 0')
assert(cls.get_script_target({id=301})==77,'other squads unchanged')
online="92 "
assert(cls.get_script_target(squad)==300,'owner offline: the squad waits')
online="92 95 "
assert(cls.get_script_target(squad)==95,'owner back with a new Actor')
axr_companions.remove_from_actor_squad(npc)
assert(companion_owner(300)==nil and cls.get_script_target(squad)==77)
''')

print('Item actions Lua: battery swap/unpack and repair on the server, whitelist, client routing, NPC inventory at spawn, item condition and death loot, furniture and stashes, player state, sleep off, companions PASS')

# World stash visits: rare, real moves, never weapons/armour/artefacts, never watched or protected.
lua.execute(r'''
moves={}
function make_box(id, items)
  local b=make_item(id,'inv_box',1); b._items=items
  b.position=function() return vector():set(0,0,0) end
  b.iterate_inventory_box=function(self,fn,o) for _,i in ipairs(self._items) do fn(o,i) end end
  b.transfer_item=function(self,item,to) moves[#moves+1]={from=self:id(),to=to:id(),item=item:id()} end
  return b
end
local npc=make_item(400,'stalker',1); npc._inv={}
npc.alive=function() return true end
npc.position=function() return vector():set(1,0,0) end
npc.best_enemy=function() return nil end
npc.wounded=function() return false end
npc.critically_wounded=function() return false end
npc.name=function() return 'npc400' end
npc.is_on_belt=function() return false end
npc.iterate_inventory=function(self,fn,o) for _,i in ipairs(self._inv) do fn(o,i) end end
npc.transfer_item=function(self,item,to) moves[#moves+1]={from=self:id(),to=to:id(),item=item:id()} end
objects[400]=npc
db.OnlineStalkers={400}
online=""
IsArtefact=function(o) return o._sec=='af_medusa' end
functors.bread={kind='i_food'}; functors.af_medusa={kind='i_arty'}
local old_r=ini_sys.r_string_ex
ini_sys.r_string_ex=function(i,sec,key) if key=='kind' then return functors[sec] and functors[sec].kind end return old_r(i,sec,key) end
ini_sys.r_bool_ex=function() return false end
hour=10
game.CTime=function() return {} end
game.get_game_time=function() return {diffSec=function() return hour * 3600 end} end
-- defined above the extracted part in the server script
hours_since_2012=function() return game.get_game_time():diffSec(game.CTime()) / 3600 end
local function always() return 0 end
local box=make_box(700,{make_item(701,'bread',1)})
local failed_box=make_box(730,{make_item(731,'bread',1)})
assert(stash_visit(failed_box, function() return 0.99 end)=="no visit",'rare: 8%')
local rolls=0
assert(stash_visit(failed_box, function() rolls=rolls+1; return 0 end)=="too soon" and rolls==0,
    'a failed opportunity is not rerolled on the next scan')
local saved_visits=alife_storage_manager.get_state().netcoop_stash_visits_v2
alife_storage_manager.get_state().netcoop_stash_visits_v2={[730]=saved_visits[730]}
assert(stash_visit(failed_box, always)=="too soon",'restored failed attempt still has cooldown')
npc._inv={make_item(402,'wpn_ak74',1), make_item(403,'af_medusa',1), make_item(404,'outfit_sun',1)}
assert(stash_visit(box, always)=="take" and moves[1].from==700 and moves[1].to==400,'nothing allowed to deposit: the NPC takes')
assert(stash_visit(box, always)=="too soon",'6 game hours between visits')
hour=17
npc._inv={make_item(405,'bread',1), make_item(406,'wpn_ak74',1)}
local n=#moves
assert(stash_visit(box, always)=="deposit" and moves[n+1].item==405 and moves[n+1].to==700,'only allowed items deposited')
hour=30; online="91 "; player.position=function() return vector():set(5,0,0) end
assert(stash_visit(box, always)=="watched",'never in front of a player')
owned_t()[700]={owner='ivan',kind='stash'}
assert(stash_visit(box, always)=="protected",'player stashes untouched')
owned_t()[700]=nil; online=""; hour=40
npc.position=function() return vector():set(60,0,0) end
assert(stash_visit(box, always)=="nobody near",'no remote transfer from 60m')
npc.position=function() return vector():set(1,0,0) end
npc.best_enemy=function() return player end
assert(stash_visit(box, always)=="nobody near",'busy in combat')
npc.best_enemy=function() return nil end
npc.wounded=function() return true end
assert(stash_visit(box, always)=="nobody near",'wounded NPC stays with current behaviour')
npc.wounded=function() return false end
local state=alife_storage_manager.get_state()
state.netcoop_stash_visits={[700]=((2012*12+5)*31+1)*24+10}
state.netcoop_stash_visits_v2[700]=nil
assert(stash_visit(box, always)=="too soon",'legacy visits migrate with a cooldown')
hour=45.9; assert(stash_visit(box, always)=="too soon")
hour=46; assert(stash_visit(box, always)=="deposit")
hour=45; assert(stash_visit(box, always)=="too soon",'clock rollback never opens a visit')
-- FactionAccessible: a box at a faction's base is visited by its own NPCs only
local gv={level_id=function() return 1 end}
game_graph=function() return {vertex=function() return gv end} end
SIMBOARD={smarts={[1]={smrt={props={base=1},faction='dolg',m_game_vertex_id=5,position=vector():set(10,0,0)}}}}
local base_box=make_box(710,{make_item(711,'bread',1)})
base_box.game_vertex_id=function() return 5 end
community='stalker'; character_community=function() return community end
hour=60
assert(stash_visit(base_box, always)=="faction stash",'another faction never touches a base box')
community='dolg'
local r1=stash_visit(base_box, always); assert(r1=="take" or r1=="deposit",'its own faction may: '..tostring(r1))
local far_box=make_box(720,{make_item(721,'bread',1)})
far_box.game_vertex_id=function() return 5 end
far_box.position=function() return vector():set(200,0,0) end
npc.position=function() return vector():set(201,0,0) end
community='stalker'
local r2=stash_visit(far_box, always); assert(r2=="take" or r2=="deposit",'away from bases anyone may: '..tostring(r2))
''')
print("Stash visits: rare, real item moves, no weapons/armour/artefacts deposited, not watched, protected stashes untouched PASS")
