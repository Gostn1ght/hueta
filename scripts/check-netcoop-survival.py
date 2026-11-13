"""Actual five-life equipment reservation: no replacement items or rerolls."""
from pathlib import Path
from lupa.lua51 import LuaRuntime
lua=LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
state={};actors={};items={};logs={}
alife_storage_manager={get_state=function() return state end}
function printf(...) end
function netcoop_actor_character(id) return id==9 and "" or "user_1" end
level={object_by_id=function(id) return actors[id] or items[id] end}
function alife() return {object=function() return nil end} end
local function actor(id)
 local a={_id=id,_name="Nickname"};actors[id]=a
 function a:id() return self._id end
 function a:character_name() return self._name end
 function a:item_in_slot(slot) return slot==8 and items[100] and items[100].owner==self and items[100] or nil end
 function a:iterate_inventory(fn) for _,v in pairs(items) do if v.owner==self then fn(self,v) end end end
 function a:transfer_item(item,to) assert(item.owner==self);item.owner=to end
 return a
end
body=actor(7);fresh=actor(8)
for id=100,110 do
 local v={_id=id,owner=body};items[id]=v
 function v:id() return self._id end
 function v:parent() return self.owner end
end
''')
code=(Path(__file__).parent/"netcoop-overlay/server/netcoop_survival.script").read_text(encoding="utf-8-sig")
lua.execute(code)
lua.execute(r'''
assert(prepare(body,4))
local r=state.netcoop_survival.user_1
assert(#r.items==6 and r.items[1]==100 and r.remaining==4)
local first=table.concat(r.items,",")
assert(prepare(body,4) and table.concat(r.items,",")==first,"same death must never reroll")
assert(protected_body(7) and reserved("user:1","Nickname"))
local retained={};for _,id in ipairs(r.items) do retained[id]=true end
for id=100,110 do
 assert(item_reserved(7,id)==(retained[id]==true),"reserve only the selected original items, not the whole corpse")
 assert(not item_reserved(999,id),"unrelated corpse remains lootable")
end
assert(can_transfer(7,8) and not can_transfer(7,9),"NPC cannot take equipment reserved for respawn")
local absent=r.items[2];local saved=items[absent];items[absent]=nil
assert(claim(fresh)=="pending" and items[100].owner==body,"no partial transfer on missing item")
items[absent]=saved
assert(claim(fresh)==first)
for _,id in ipairs(r.items) do assert(items[id].owner==fresh) end
assert(claim(fresh)==first,"repeated claim does not duplicate an item")
-- Disconnect after a partial/asynchronous restore: preserve originals and
-- leave the draw reserved for the next connection rather than deleting them.
local original_transfer=fresh.transfer_item
local returns={}
function fresh:transfer_item(item,to) returns[#returns+1]={item,to} end
-- Missing original or foreign ownership must prevent partial rollback.
local missing=r.items[2];local original=items[missing];items[missing]=nil
assert(not rollback(fresh) and #returns==0)
items[missing]=original
local previous=original.owner;original.owner=actors[9] or {_id=9,id=function(self)return self._id end}
assert(not rollback(fresh) and #returns==0);original.owner=previous
-- An offline corpse must be brought online before any item can be returned.
local corpse=actors[7];actors[7]=nil;local wakeups=0
function alife() return {object=function(_,id) return id==7 and {} or nil end,
 set_switch_online=function(_,id,value) assert(id==7 and value);wakeups=wakeups+1 end} end
assert(not rollback(fresh) and wakeups==1 and #returns==0)
actors[7]=corpse
assert(not rollback(fresh) and protected_body(7))
for _,event in ipairs(returns) do event[1].owner=event[2] end
assert(rollback(fresh) and rollback(fresh))
for _,id in ipairs(r.items) do assert(items[id].owner==body) end
fresh.transfer_item=original_transfer
assert(claim(fresh)==first)
complete(fresh);assert(not protected_body(7) and not state.netcoop_survival.user_1)
local kept,left=0,0
for _,v in pairs(items) do if v.owner==fresh then kept=kept+1 else left=left+1 end end
assert(kept==6 and left==5 and items[100].owner==fresh)
-- Real ownership events are asynchronous; admission must wait for them.
actors[10]={_id=10,_name="Nickname"};local nextbody=actors[10]
for key,value in pairs(fresh) do if type(value)=="function" then nextbody[key]=value end end
local queued={}
function fresh:transfer_item(item,to) queued[#queued+1]={item,to} end
assert(prepare(fresh,3))
assert(claim(nextbody)=="pending" and items[100].owner==fresh)
for _,event in ipairs(queued) do event[1].owner=event[2] end
assert(claim(nextbody)~="pending" and items[100].owner==nextbody)
complete(nextbody);assert(not protected_body(8))
-- The fifth/final death retains no reservation, including the PDA.
assert(prepare(nextbody,0) and not protected_body(10) and items[100].owner==nextbody)
-- Repeated deaths/reconnect attempts across many random draws keep the
-- same physical objects and exactly the configured surviving half.
local prototype=body
for seed=1,64 do
 math.randomseed(seed);state={};actors={};items={}
 local function make(id)
  local a={_id=id,_name="Nickname"}
  for key,value in pairs(prototype) do if type(value)=="function" then a[key]=value end end
  actors[id]=a;return a
 end
 local current=make(1000)
 for id=100,120 do
  local item={_id=id,owner=current}
  function item:id() return self._id end
  function item:parent() return self.owner end
  items[id]=item
 end
 local count=21
 for remaining=4,1,-1 do
  assert(prepare(current,remaining))
  local reservation=state.netcoop_survival.user_1
  local original_draw=table.concat(reservation.items,",")
  assert(prepare(current,remaining) and table.concat(reservation.items,",")==original_draw)
  local replacement=make(current:id()+1)
  local claimed=claim(replacement);assert(claimed~="pending" and claimed~="legacy")
  count=1+math.ceil((count-1)/2)
  local actual=0
  for _,item in pairs(items) do if item.owner==replacement then actual=actual+1 end end
  assert(actual==count and items[100].owner==replacement)
  assert(claim(replacement)==claimed)
  complete(replacement);assert(not protected_body(current:id()))
  current=replacement
 end
 assert(prepare(current,0) and next(state.netcoop_survival)==nil)
end
''')
print("PASS actual survival: half of gear, guaranteed same PDA until final death, stable draw, pending missing item, no partial mutation, physical transfer, repeat safe, corpse unlock, 64 complete five-life sequences")
