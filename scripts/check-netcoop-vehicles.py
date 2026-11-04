"""Vehicles (doc 100): the actual netcoop_vehicle_client prompts and the
server's car trunks (netcoop_vehicles.script) with host stubs."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
client = (root / "scripts/netcoop-overlay/client/netcoop_vehicle_client.script").read_text(encoding="ascii")
server = (root / "scripts/netcoop-overlay/server/netcoop_vehicles.script").read_text(encoding="ascii")

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
game = {translate_string = function(id) return "<" .. id .. ">" end}
key_bindings = {kUSE = 1, kJUMP = 2, kTORCH = 3, kDETECTOR = 4, kACCEL=5, kCROUCH=6, kFWD=7, kBACK=8}
names = {"F", "SPACE", "L", "O", "RSHIFT", "RCTRL", "UP", "DOWN"}
function bind_to_dik(b) return b end
function dik_to_keyname(d) return string.lower(names[d]) end
function class(name) _G[name] = {} return function() end end
CUIScriptWnd = {}
''')
lua.execute(client)
lua.execute(r'''
assert(prompt_text("driver", 0) == "[F]  <st_netcoop_car_drive>")
assert(prompt_text("passenger", 0) == "[F]  <st_netcoop_car_sit>")
assert(prompt_text("trunk", 0) == "[F]  <st_netcoop_car_trunk>")
assert(prompt_text("taken", 0) == "<st_netcoop_seat_taken>", "a taken seat says so, no key")
assert(prompt_text("", 0) == nil)
local hint = prompt_text("seated_driver", 1000)
assert(hint:find("[UP/DOWN]",1,true) and hint:find("[RSHIFT/RCTRL]",1,true),hint)
assert(hint:find("%[SPACE%] <st_netcoop_car_handbrake>") and hint:find("%[L%] <st_netcoop_car_lights>"), hint)
assert(prompt_text("seated_driver", 8999) ~= nil and prompt_text("seated_driver", 9001) == nil, "controls for 8 s")
assert(prompt_text("", 9100) == nil)
assert(prompt_text("seated", 10000) == "[F]  <st_netcoop_car_exit>", "a new seat shows the hint again")
assert(prompt_text("", 19000) == nil)
local pilot = prompt_text("seated_pilot", 20000)
assert(pilot:find("%[SPACE/RCTRL%] <st_netcoop_heli_collective>") and pilot:find("%[UPADOWND%] <st_netcoop_heli_cyclic>")
	and pilot:find("%[Q/E%] <st_netcoop_heli_pedals>") and pilot:find("%[F%] <st_netcoop_car_exit>"), pilot)
assert(prompt_text("seated_pilot", 34999) ~= nil and prompt_text("seated_pilot", 35001) == nil, "pilot controls for 15 s")
''')

# Construct the actual dashboard with the engine's frame API. A nine-slice
# identifier is not a standalone static texture and must not use InitStatic.
lua.execute(r'''
frames,added,removed=0,0,0
function super()end
function Frect()return {set=function(self,...)return self end}end
function GetARGB(a,r,g,b)return {a,r,g,b}end
function get_hud()return {AddDialogToRender=function()added=added+1 end,RemoveDialogToRender=function()removed=removed+1 end}end
function CScriptXmlInit()return {
 ParseFile=function(_,name)assert(name=="ui_netcoop_vehicle_status.xml")end,
 InitFrame=function(_,name,parent)assert(name=="dashboard" and parent);frames=frames+1;return {}end,
 InitTextWnd=function(_,name,parent)assert(parent);return {SetText=function(self,value)self.text=value end,SetTextColor=function(self,value)self.color=value end}end,
}end
local hud=setmetatable({SetWndRect=function()end},{__index=UIVehicleStatus})
hud:__init();assert(frames==1)
hud:Set("64.0|72.0|86.0|2400|3|1")
assert(hud.speed.text=="064  <st_lz_car_kmh>" and hud.details.text:find("2400",1,true))
assert(hud.condition.text:find("72%",1,true) and hud.condition.color[2]==205 and added==1)
hud:Set("0|9|24|0|0|0");assert(hud.condition.color[2]==220 and added==1)
assert(hud.engine.text:find("<st_lz_car_off>",1,true) and hud.details.text:find(" R",1,true))
hud:Set("0|100|100|850|1|33")
assert(hud.parking.text:find("<st_lz_car_on>",1,true) and hud.controls.text:find("RSHIFT/RCTRL",1,true))
hud:Set("0|100|100|850|1|1");assert(hud.parking.text:find("<st_lz_car_off>",1,true))
hud:Set("0|100|100|850|1|97");assert(hud.parking.text=="" and hud.controls.text=="" and hud.details.text:find("<st_lz_heli_gear_down>",1,true))
hud:Set("0|100|100|850|1|65");assert(hud.details.text:find("<st_lz_heli_gear_up>",1,true))
hud:Set("");assert(removed==1 and not hud.shown)
''')

srv = LuaRuntime(unpack_returned_tuples=True)
srv.execute(r'''
state, objects, anchors, released, logs, callbacks = {}, {}, {}, {}, {}, {}
next_id = 500
alife_storage_manager = {get_state = function() return state end}
function vector() local v = {} function v:set(x, y, z) self.x, self.y, self.z = x, y, z return self end return v end
function printf(fmt, ...) logs[#logs + 1] = fmt end
function IsInvbox(_, cls) return cls == "box" end
function alife_object(id) return objects[id] end
function alife_create(section, pos, lv, gv)
    next_id = next_id + 1
    local se = {id = next_id, section = section, pos = pos}
    function se:clsid() return "box" end
    objects[se.id] = se
    return se
end
function alife_release(se) released[#released + 1] = se.id; objects[se.id] = nil end
online = {}
function alife() return {set_switch_online = function(_, id, v) online[id] = v end, set_switch_offline = function() end} end
function netcoop_box_anchor(box, car) anchors[box] = car end
function netcoop_pure_client() return false end
function RegisterScriptCallback(name, fn) callbacks[name] = fn end
car = {position = function() return {x = 10, y = 5, z = 20} end, level_vertex_id = function() return 1 end,
       game_vertex_id = function() return 2 end, section = function() return "veh_niva" end}
level = {object_by_id = function(id) return id == 42 and car or nil end}
''')
srv.execute(server)
srv.execute(r'''
on_game_start()
local box = trunk_box(42)
assert(box == 501 and objects[501].section == "netcoop_car_trunk", "a trunk is made on first use")
assert(objects[501].pos.y == -45, "under the map, below the car")
assert(anchors[501] == 42 and online[501] == true, "anchored to the car, always online")
assert(trunk_box(42) == 501, "the same trunk next time")
assert(trunk_box(7) == 0, "no car, no trunk")
callbacks.server_entity_on_unregister({id = 42})
assert(released[1] == 501 and state.netcoop_car_trunks[42] == nil, "a car that is gone takes its trunk")
assert(trunk_box(42) == 502, "a new trunk for a car seen again")
''')
# V6: a car through a passage keeps its trunk's items and their state.
srv.execute(r"""
records = {}
local function copy(v) if type(v) ~= "table" then return v end local c = {} for k, x in pairs(v) do c[k] = copy(x) end return c end
netcoop_transit = {
    serialize = function(t) records[#records + 1] = copy(t) return "rec" .. #records end,
    deserialize = function(s) return copy(records[tonumber(s:sub(4))]) end,
}
utils_stpk = {
    get_object_data = function(se) return se.data and copy(se.data) end,
    set_object_data = function(d, se) se.data = d end,
}
ini_sys = {section_exist = function(_, s) return s ~= "bogus" end}
level.vertex_id = function(pos) return pos.y > -40 and 77 or 4294967295 end
created = {}
function alife()
    return {
        set_switch_online = function(_, id, v) online[id] = v end, set_switch_offline = function() end,
        create = function(_, section, pos, lv, gv)
            next_id = next_id + 1
            local se = {id = next_id, section = section, pos = pos, gv = gv}
            function se:section_name() return self.section end
            function se:clsid() return "car" end
            objects[se.id] = se; created[#created + 1] = se
            return se
        end,
    }
end
function alife_create_item(section, parent)
    next_id = next_id + 1
    local se = {id = next_id, section = section, parent = parent.id,
        data = {condition = 1, upgrades = "", game_vertex_id = 9, level_vertex_id = 8}}
    objects[se.id] = se
    return se
end
-- The car 42 with a trunk holding a worn rifle (upgraded) and an ammo box.
objects[42] = {id = 42, section_name = function() return "veh_niva" end}
local box = trunk_box(42)
objects[600] = {id = 600, data = {condition = 0.9, upgrades = "up_sect_a", game_vertex_id = 1, level_vertex_id = 2}}
objects[601] = {id = 601, data = {ammo_left = 30, game_vertex_id = 1, level_vertex_id = 2}}
local items = {
    {id = function() return 600 end, section = function() return "wpn_ak74" end, condition = function() return 0.42 end},
    {id = function() return 601 end, section = function() return "ammo_5.45x39_fmj" end, condition = function() return 1 end,
     ammo_get_count = function() return 12 end},
}
local box_obj = {iterate_inventory_box = function(self, fn, owner) for _, it in ipairs(items) do fn(owner, it) end end}
level.object_by_id = function(id) if id == 42 then return car end if id == box then return box_obj end end
local text = capture(42)
assert(text == "rec1", "the car is captured as one record")
local saved = records[1]
assert(saved.section == "veh_niva" and #saved.trunk == 2)
assert(saved.trunk[1].data.condition == 0.42 and saved.trunk[1].data.upgrades == "up_sect_a", "condition from the live item, upgrades kept")
assert(saved.trunk[2].data.ammo_left == 12, "ammo count from the live box")
released = {}
release(42)
assert(objects[42] == nil and objects[box] == nil and objects[600] == nil and objects[601] == nil, "car, trunk and items leave")
assert(state.netcoop_car_trunks[42] == nil)
-- The target map.
local id = restore(text, 100, 3, 200, 55)
local car_se = objects[id]
assert(car_se and car_se.section == "veh_niva" and car_se.gv == 55, "the car arrives at the passage's vertex")
local new_box = state.netcoop_car_trunks[id]
assert(new_box and online[new_box], "with a trunk, always online")
local rifle, ammo
for _, se in pairs(objects) do
    if se.parent == new_box and se.section == "wpn_ak74" then rifle = se end
    if se.parent == new_box and se.section == "ammo_5.45x39_fmj" then ammo = se end
end
assert(rifle and rifle.data.condition == 0.42 and rifle.data.upgrades == "up_sect_a", "the rifle keeps its state")
assert(rifle.data.game_vertex_id == 9 and rifle.data.level_vertex_id == 8, "placed on the new map, not the old")
assert(ammo and ammo.data.ammo_left == 12)
assert(restore(text, 100, -60, 200, 55) == 0, "no ground, no car")
records[2] = {section = "bogus", trunk = {}}
assert(restore("rec2", 1, 1, 1, 1) == 0, "an unknown car is refused")
""")
print("Vehicles: seat/trunk/taken prompts, driver controls hint for 8 s, trunk made once under the car, anchored, always online, released with the car, passage capture/release/restore with item state PASS")
