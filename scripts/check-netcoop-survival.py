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
assert(can_transfer(7,8) and not can_transfer(7,9),"NPC cannot take equipment reserved for respawn")
local absent=r.items[2];local saved=items[absent];items[absent]=nil
assert(claim(fresh)=="pending" and items[100].owner==body,"no partial transfer on missing item")
items[absent]=saved
assert(claim(fresh)==first)
for _,id in ipairs(r.items) do assert(items[id].owner==fresh) end
assert(claim(fresh)==first,"repeated claim does not duplicate an item")
complete(fresh);assert(not protected_body(7) and not state.netcoop_survival.user_1)
local kept,left=0,0
for _,v in pairs(items) do if v.owner==fresh then kept=kept+1 else left=left+1 end end
assert(kept==6 and left==5 and items[100].owner==fresh)
-- The fifth/final death retains no reservation, including the PDA.
assert(prepare(fresh,0) and not protected_body(8) and items[100].owner==fresh)
''')
print("PASS actual survival: half of gear, guaranteed same PDA until final death, stable draw, pending missing item, no partial mutation, physical transfer, repeat safe, corpse unlock")
