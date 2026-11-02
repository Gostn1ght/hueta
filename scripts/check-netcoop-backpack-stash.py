"""Actual physical backpack stash Lua with delayed ownership and restart replay."""
from pathlib import Path
from lupa.lua51 import LuaRuntime
root=Path(__file__).resolve().parents[1]
overlay=root/'scripts/netcoop-overlay'
lua=LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
now=100;objects={};ses={};state={};online={};queue={};released={};sent={};next_id=500;refuse=false
function printf() end
function time_global() return now end
function vector() return {set=function(self,x,y,z) self.x,self.y,self.z=x,y,z;return self end,
 distance_to=function(self,p) return math.sqrt((self.x-p.x)^2+(self.y-p.y)^2+(self.z-p.z)^2) end} end
function netcoop_item_uid(id) return objects[id] and objects[id]._uid or '' end
function netcoop_actor_login(id) return objects[id] and objects[id].login or '' end
function netcoop_players() local out={};for id in pairs(online) do out[#out+1]=tostring(id) end;return table.concat(out,' ') end
function netcoop_send_to_actor(id,cmd,data) sent[#sent+1]={id,cmd,data} end
function alife_object(id) return ses[id] end
alife_storage_manager={get_state=function() return state end}
level={object_by_id=function(id) return objects[id] end}
function alife() return {set_switch_online=function() end} end
function SendScriptCallback() end
function ini_file() return nil end
function IsAmmo(item) return item.ammo or false end
ini_sys={r_string_ex=function(_,sec,key) return sec=='medkit' and key=='kind' and 'i_medical' or nil end,
 r_bool_ex=function(_,sec,key,default) return sec=='quest' and key=='quest_item' or default end,
 section_exist=function() return true end}
function strformat(...) return string.format(...) end
game={translate_string=function() return '%s stash' end}
function make(id,sec,parent,key)
 local o={_id=id,_section=sec,_parent=parent,_uid=key or tostring(id),_condition=.73,pos=vector():set(0,0,0),live=true}
 function o:id() return self._id end
 function o:name() return self._section..'_'..self._id end
 function o:section() return self._section end
 function o:parent() return self._parent end
 function o:condition() return self._condition end
 function o:position() return self.pos end
 function o:alive() return self.live end
 function o:level_vertex_id() return 1 end
 function o:game_vertex_id() return 1 end
 function o:character_name() return 'Ivan' end
 function o:is_on_belt(it) return it.belt or false end
 function o:item_in_slot(slot) return slot==13 and self.backpack or nil end
 function o:iterate_inventory(fn,context)
  local list={};for _,item in pairs(objects) do if item._parent==self then list[#list+1]=item end end
  table.sort(list,function(a,b)return a:id()<b:id()end)
  for _,item in ipairs(list) do fn(context,item) end
 end
 o.iterate_inventory_box=o.iterate_inventory
 function o:is_inv_box_empty() for _,item in pairs(objects) do if item._parent==self then return false end end;return true end
 function o:transfer_item(item,to)
  assert(item and item._parent==self,'transfer must target the current source')
  queue[#queue+1]={self,item,to}
 end
 objects[id]=o;ses[id]={id=id,name=function() return o:name() end}
 return o
end
function alife_create(sec,pos)
 next_id=next_id+1;local o=make(next_id,sec);o.pos=pos;return ses[next_id]
end
function alife_release(se)
 local box=objects[se.id];assert(not box or box:is_inv_box_empty(),'never release a nonempty stash')
 released[#released+1]=se.id;objects[se.id]=nil;ses[se.id]=nil
end
function alife_create_item() error('a physical backpack must never be recreated') end
function flush()
 local events=queue;queue={}
 for _,event in ipairs(events) do
  local source,item,to=unpack(event)
  if item._parent==source and not refuse then
   if early_callback and source:section()=='inv_backpack' then on_box_changed(source:id(),to:id()) end
   item._parent=to
   if not early_callback and source:section()=='inv_backpack' then on_box_changed(source:id(),to:id()) end
  end
 end
end
item_backpack={is_in_slot=function(item) return item.slot or false end,is_ammo_for_wpn=function(sec)return sec=='ammo_keep'end}
player=make(91,'actor');player.login='ivan';online[91]=true
''')
source=(overlay/'server/netcoop_backpack_stash.script').read_text()
loader=lua.eval('function(s) local env={};setmetatable(env,{__index=_G});setfenv(assert(loadstring(s)),env)();return env end')
lua.globals().netcoop_backpack_stash=loader(source)
server=(overlay/'server/netcoop_server_compat.script').read_text(encoding='cp1251')
a=server.index('-- Player-owned objects: furniture and backpack stashes')
b=server.index('\nfunction item_action(',a)
lua.execute(server[a:b]+r'''
s_create=stash_create;s_deploy=backpack_deploy;owned_t=owned
netcoop_server_compat={on_box_changed=on_box_changed}
function tick(ms) now=now+(ms or 1100);netcoop_backpack_stash.update() end
function deploy(bag,contents)
 player.backpack=bag
 assert((contents and s_deploy(player,'ivan') or s_create(player,bag,'My|stash\n','ivan'))=='')
 local id=next_id;tick();assert(bag:parent()==player,'ownership is asynchronous');flush();tick()
 return id,objects[id]
end
''')
lua.execute(r'''
-- Actual compat entry point keeps UID/condition and puts the same bag in the box.
local bag=make(70,'pack',player,'bag-A');local id,box=deploy(bag,false)
assert(bag:parent()==box and bag:condition()==.73 and netcoop_item_uid(70)=='bag-A')
assert(owned_t()[id].name=='Mystash' and owned_t()[id].bag_phase=='idle')
assert(s_create(player,bag,'again','ivan')~='','cannot deploy an already stored bag')
-- Bag pickup packs ALL loot despite arbitrarily low carrying capacity.
local loot=make(71,'heavy_loot',box);player.capacity=1;loot.weight=500
box:transfer_item(bag,player);flush();assert(objects[id] and loot:parent()==box)
player.pos=vector():set(50,0,0) -- walking away must not strand the authorized pickup
tick();flush();tick()
assert(not objects[id] and not owned_t()[id] and bag:parent()==player and loot:parent()==player)
player.pos=vector():set(0,0,0)
assert(bag:condition()==.73 and #released==1 and sent[#sent][2]=='stash_spot_remove')
-- Take-all has already queued its own requests: wait for them, never duplicate.
local id2,box2=deploy(bag,false);local extra=make(72,'loot',box2)
box2:transfer_item(bag,player);box2:transfer_item(extra,player);flush();tick()
assert(not objects[id2] and extra:parent()==player and #queue==0)
-- A refused take retains loot and the stash. It can be retried after reconnect.
local id3,box3=deploy(bag,false);local saved=make(73,'loot',box3)
box3:transfer_item(bag,player);flush();refuse=true;tick();flush();tick()
assert(objects[id3] and saved:parent()==box3 and owned_t()[id3])
online[91]=nil;refuse=false;tick();assert(#queue==1,'the preceding pending retry remains queued')
queue={};player.live=false;tick();assert(objects[id3] and saved:parent()==box3)
-- Reconnect changes both actor ID and held bag object ID, with the same UID.
player=make(92,'actor');player.login='ivan';online[92]=true
objects[70]=nil;ses[70]=nil;bag=make(170,'pack',player,'bag-A')
make(70,'unrelated_reused_id',player,'WRONG-UID')
tick();flush();tick()
assert(not objects[id3] and saved:parent()==player and objects[70]:parent()==player)
-- Worn deployment snapshots first, excludes equipped/medical/quest/ammo, and
-- leaves an unrelated future item with the character.
local medical=make(180,'medkit',player);local quest=make(181,'quest',player)
local ammo=make(182,'ammo_keep',player);ammo.ammo=true
local worn=make(183,'outfit',player);worn.slot=true
local belt=make(184,'artifact',player);belt.belt=true
local id4,box4=deploy(bag,true);local future=make(185,'future',player)
tick();flush();tick()
assert(bag:parent()==box4 and future:parent()==player)
assert(medical:parent()==player and quest:parent()==player and ammo:parent()==player and worn:parent()==player and belt:parent()==player)
assert(owned_t()[id4].bag_phase=='idle')
-- Putting the bag back before packing completes cancels the pending pack.
box4:transfer_item(bag,player);flush();player:transfer_item(bag,box4);flush();tick()
assert(objects[id4] and owned_t()[id4].bag_phase=='idle')
-- Repeated native/stock callbacks are idempotent. A restarted module resumes.
box4:transfer_item(bag,player);flush();on_box_changed(id4,player:id());tick();flush()
restart_id=id4
''')
lua.globals().netcoop_backpack_stash=loader(source)
lua.execute(r'''
tick();flush();tick();assert(not objects[restart_id]);assert(#released==4)
-- Native confirmation precedes the live object's queued H_Parent update.
local bag=make(190,'pack',player,'bag-EARLY');local id,box=deploy(bag,false)
local loot=make(191,'loot',box);early_callback=true
box:transfer_item(bag,player);flush();assert(owned_t()[id].bag_phase=='idle')
tick();assert(owned_t()[id].bag_phase=='pack_wait')
tick();flush();tick();assert(not objects[id] and loot:parent()==player)
early_callback=false
-- Failed bag deployment rolls back its empty proxy, never destroys the bag.
local bag2=make(192,'pack',player,'bag-REFUSED');refuse=true
assert(s_create(player,bag2,'refused','ivan')=='');local id2=next_id
tick();flush();tick(12000)
assert(not objects[id2] and bag2:parent()==player and bag2:condition()==.73)
refuse=false
''')
print('PASS actual backpack stash: real UID/condition, async deployment, all loot despite weight, take-all, refused transfer/reconnect, reused IDs, retained equipment, return cancellation, restart and no bag recreation')
