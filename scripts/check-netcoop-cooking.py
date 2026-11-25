"""Exercise the cooking action and menu adapters in Lua 5.1 with a stub world."""
from pathlib import Path
import re

from lupa.lua51 import LuaRuntime


root = Path(__file__).resolve().parent / "netcoop-overlay"
lua = LuaRuntime(unpack_returned_tuples=True)
load = lua.eval(
    "function(source) local env = setmetatable({}, {__index = _G}); "
    "setfenv(assert(loadstring(source)), env)(); return env end"
)
g = lua.globals()
g.netcoop_workshop_recipe = load((root / "server/netcoop_workshop_recipe.script").read_text())
g.netcoop_cooking = load((root / "server/netcoop_cooking.script").read_text())
server = (root / "server/netcoop_server_compat.script").read_text(encoding="utf-8")
g.netcoop_server_compat = load(re.search(r"^function item_action\(.*?^end", server, re.M | re.S)[0])

lua.execute(r'''
local rows = {
    {"x_meat_boar_b", "1, false, mutant_part_boar_chop,1,flask,2"},
    {"x_meat_chimera", "2, false, mutant_part_chimera_meat,1"},
    {"x_meat_dog_a", "2, encyclopedia__notes_recipe_cooking_1, mutant_part_dog_meat,1,vodka,1"},
}
local tiers = {charcoal=1, kerosene=2, explo_balon_gas=2}
local kits = {
    cooking={cooking_tool=true, cooking_limited=true, fuel={charcoal=true}},
    army_bowler={cooking_tool=true, cooking_limited=true, cooking_campfire=true, fuel={charcoal=true}},
    fieldcooker={cooking_tool=true, fuel={kerosene=true, explo_balon_gas=true}},
}
local sections = {
    meat_boar_b=true, meat_chimera=true, meat_dog_a=true,
    mutant_part_boar_chop=true, mutant_part_chimera_meat=true, mutant_part_dog_meat=true,
    flask=true, vodka=true,
}
ini_sys = {
    section_exist=function(_, sec) return sections[sec] end,
    r_bool_ex=function(_, sec, key) return kits[sec] and kits[sec][key] or false end,
}
function ini_file(path)
    assert(path == "items\\settings\\cook.ltx")
    return {
        line_count=function(_, group) assert(group == "meal_list"); return #rows end,
        r_line_ex=function(_, group, i) assert(group == "meal_list"); return true, unpack(rows[i+1]) end,
        r_float_ex=function(_, group, key)
            if group == "fuel" then return tiers[key] end
            assert(group == "settings" and key == "campfire_cook_tier")
            return 1
        end,
    }
end
function parse_list(ini, sec, key, convert)
    assert(ini == ini_sys and key == "cooking_fuel" and convert)
    return kits[sec].fuel
end
function str_explode(line, delimiter)
    assert(delimiter == ",")
    local out = {}
    for value in line:gmatch("[^,]+") do out[#out+1] = value:match("^%s*(.-)%s*$") end
    return out
end
function printf(...) logs[#logs+1] = string.format(...) end
local function check_state(object, owner, uses)
    assert(entities[object:id()] and entities[object:id()].parent_id == owner)
    assert(object:get_remaining_uses() == uses)
end
function make(id, sec, parent, uses, x)
    local item = {uses=uses, x=x or 0}
    function item:id() return id end
    function item:section() return sec end
    function item:get_remaining_uses() return self.uses end
    function item:set_remaining_uses(value)
        if setter_refused == id and value < self.uses then return end
        self.uses = value
    end
    function item:position()
        return {x=self.x, distance_to=function(a,b) return math.abs(a.x-b.x) end}
    end
    function item:alive() return not self.dead end
    function item:iterate_inventory(fn)
        for key, entity in pairs(entities) do
            if entity.parent_id == id then fn(nil, objects[key]) end
        end
    end
    function item:transfer_item(object, target)
        local entity = entities[object:id()]
        assert(entity.parent_id == id)
        if refused ~= object:id() then entity.parent_id = target:id() end
    end
    entities[id] = {id=id, parent_id=parent, section_name=function() return sec end}
    objects[id] = item
    return item
end
function IsItem(category, sec, object)
    if category == "cook" then return kits[sec] ~= nil end
    assert(category == "multiuse")
    return object:get_remaining_uses() ~= nil
end
function alife_object(id) return entities[id] end
function alife_release_id(id)
    -- The online destroy event is queued by the engine.
    assert(entities[id])
    releases[#releases+1] = id
    return true
end
function alife_create_item(sec, owner)
    assert(owner == db.actor)
    if spawn_refused then return nil end
    births = births + 1
    local id = 100 + births
    make(id, sec, bad_parent and 0 or owner:id())
    return entities[id]
end
level = {object_by_id=function(id) return objects[id] end}
bind_campfire = {get_nearby_campfire=function(distance, result)
    assert(distance == 1.5 and result)
    return {is_on=function() return lit end}
end}
netcoop_workshop = {known_recipes=function(id)
    assert(id == db.actor:id())
    return known
end}
netcoop_server_compat.can_access = function(id, login)
    assert(id == 30 and login == "player")
    return access
end
function netcoop_send_to_actor(id, channel, data)
    assert(channel == "cooking_result")
    replies[#replies+1] = {id, data}
end
function reset()
    entities, objects, replies, releases, known, logs = {}, {}, {}, {}, {}, {}
    refused, setter_refused, spawn_refused, bad_parent, access, lit = nil, nil, false, false, false, false
    births = 0
    make(0, "anchor", 65535)
    db = {actor=make(42, "actor", 65535), storage={[42]={}}}
end
local recipe = netcoop_workshop_recipe
boar_key = recipe.key({sec="meat_boar_b", tool=1, rsp="", {"mutant_part_boar_chop",1}, {"flask",2}})
local chimera = recipe.key({sec="meat_chimera", tool=2, rsp="", {"mutant_part_chimera_meat",1}})
local dog = recipe.key({sec="meat_dog_a", tool=2, rsp="", {"mutant_part_dog_meat",1}, {"vodka",1}})
function action(serial, key, kind, item, actor)
    return netcoop_server_compat.item_action(actor or 42, kind or 1, item or 10, 65535,
        "cook " .. serial .. " " .. (key or boar_key), "player")
end
local function kit_inventory(tool, tool_uses, fuel_uses)
    local kit = make(10, tool, 42, tool_uses)
    local meat = make(11, "mutant_part_boar_chop", 42)
    local water = make(12, "flask", 42, 4)
    local fuel = fuel_uses and make(13, "charcoal", 42, fuel_uses) or nil
    return kit, meat, water, fuel
end
reset()
local kit, meat, water, fuel = kit_inventory("cooking", 3, 3)
local other = make(19, "charcoal", 43, 7)
assert(action(1) == "")
assert(births == 1 and entities[101].parent_id == 42 and entities[101]:section_name() == "meat_boar_b")
check_state(meat, 0)
check_state(water, 42, 2)
check_state(fuel, 42, 2)
check_state(kit, 42, 2)
check_state(other, 43, 7)
assert(#releases == 1 and releases[1] == meat:id())
assert(action(1) == "" and births == 1 and #releases == 1)
assert(replies[1][1] == 42 and replies[1][2] == "1|ok" and replies[2][2] == "1|ok")
assert(action(1, chimera) == "cooking request changed")
assert(action(2) == "missing cooking ingredients")
assert(action("002") == "bad cooking request")
assert(action(3, "0000000000000000") == "unknown cooking recipe")

reset()
kit, meat, water, fuel = kit_inventory("cooking", 1, 3)
spawn_refused = true
assert(action(1) == "cooking failed" and births == 0 and #releases == 0)
check_state(kit, 42, 1)
check_state(meat, 42)
check_state(water, 42, 4)
check_state(fuel, 42, 3)
spawn_refused, bad_parent = false, true
assert(action(1) == "cooking failed" and births == 0)
assert(action(2) == "cooking failed" and births == 1 and releases[1] == 101)
check_state(kit, 42, 1)
check_state(meat, 42)
check_state(water, 42, 4)
check_state(fuel, 42, 3)
bad_parent, refused = false, 10
assert(action(3) == "cooking failed" and births == 1)
check_state(kit, 42, 1)
check_state(meat, 42)
check_state(water, 42, 4)
check_state(fuel, 42, 3)
refused, setter_refused = nil, 13
assert(action(4) == "cooking failed" and births == 1)
check_state(meat, 42)
check_state(water, 42, 4)
check_state(fuel, 42, 3)
setter_refused = nil
assert(action(5) == "" and births == 2 and #releases == 3)
check_state(kit, 0, 1)

reset()
kit, meat, water = kit_inventory("army_bowler", 2)
assert(action(1) == "no compatible cooking fuel in inventory")
check_state(meat, 42)
lit = true
assert(action(2) == "" and births == 1)
check_state(kit, 42, 1)
check_state(water, 42, 2)
entities[10].parent_id = 43
assert(action(3) == "this is not an available cooking kit")
assert(action(4, nil, 1, 10, 43) == "cooking is not available")

reset()
make(10, "fieldcooker", 42)
make(11, "mutant_part_chimera_meat", 42)
local charcoal = make(13, "charcoal", 42, 3)
assert(action(1, chimera) == "no compatible cooking fuel in inventory")
local gas = make(20, "kerosene", 42, 255)
assert(action(2, chimera) == "")
check_state(gas, 42, 255)
check_state(charcoal, 42, 3)
make(21, "mutant_part_dog_meat", 42)
make(22, "vodka", 42, 2)
local stove = make(30, "placeable_stove1", 65535, nil, 8)
assert(action(3, dog, 2, 30) == "cooking stove is not accessible")
access = true
assert(action(4, dog, 2, 30) == "cooking stove is not accessible")
stove.x = 4
assert(action(5, dog, 2, 30) == "cooking recipe is not learned")
known.recipe_cooking_1 = true
assert(action(6, dog, 2, 30) == "" and births == 2)
assert(entities[102].parent_id == 42 and entities[102]:section_name() == "meat_dog_a")
check_state(objects[22], 42, 1)
assert(#logs == 0)
''')
print("PASS server cooking validates exact recipe, owner, stove, campfire and fuel, consumes once and rolls back originals")

g.netcoop_workshop_recipe = load((root / "client/netcoop_workshop_recipe.script").read_text())
g.netcoop_workshop_view = load((root / "client/netcoop_workshop_view.script").read_text())
lua.execute(r'''
reset()
local kit = make(10, "cooking", 42, 2)
local meat = make(11, "mutant_part_boar_chop", 42)
make(12, "flask", 42, 2)
local fuel = make(13, "charcoal", 42, 3)
make(14, "charcoal", 440, 15)
local clock, sends = 1000, {}
function time_global() return clock end
function netcoop_pure_client() return true end
function netcoop_item_action(kind, item, target, data)
    sends[#sends+1] = {kind, item, target, data}
    return true
end
function alife_create_item() error("client created item") end
function alife_release_id() error("client removed item") end
local install
function RegisterScriptCallback(name, fn)
    if name == "actor_on_first_update" then install = fn end
end
local class = {
    OnCook=function() error("base client cooking used") end,
    On_CC_Mouse1=function(self) self.selected = (self.selected or 0) + 1 end,
    Update=function(self) self.updated = (self.updated or 0) + 1 end,
    Close=function(self) self.closed = true end,
    IsShown=function(self) return not self.closed end,
    GetSelectedMeal=function(self) return self.meals[1] end,
    CheckAvail_main=function(self)
        return self.objs.charcoal and self.objs.charcoal[13] and self.objs.mutant_part_boar_chop ~= nil
    end,
}
item_cooking = {UICook=class, start=function(item, section)
    assert(item == kit and section == "cooking")
    opened_kit = true
end}
function CInventory__eat(item)
    assert(item == meat)
    return true
end
netcoop_workshop_view.on_game_start()
install()
assert(CInventory__eat(kit) == false and opened_kit and kit.uses == 2)
assert(CInventory__eat(meat))
local meal = {
    sec="meat_boar_b", fuel_tier=1,
    {sec="mutant_part_boar_chop", amt=1}, {sec="flask", amt=2},
}
local menu = setmetatable({
    obj=kit, cooking_limited=true, meals={meal}, fuel={charcoal=1}, objs={},
    last_cont={}, last_idx=1, btn_cook={Enable=function(self, value) self.enabled=value end},
}, {__index=class})
menu:On_CC_Mouse1()
assert(menu.btn_cook.enabled and menu.objs.charcoal[13] == 3 and not menu.objs.charcoal[14])
menu:OnCook()
menu:OnCook()
assert(#sends == 1 and not menu.btn_cook.enabled)
assert(sends[1][1] == 1 and sends[1][2] == 10 and sends[1][3] == 65535 and sends[1][4] == "cook 1001 " .. boar_key)
assert(kit.uses == 2 and fuel.uses == 3 and objects[11] == meat and not menu.hasCraftedItem)
netcoop_workshop_view.on_cooking_result("1002|ok")
netcoop_workshop_view.on_cooking_result("1001|bad")
assert(not menu.hasCraftedItem)
netcoop_workshop_view.on_cooking_result("1001|failed")
clock = 1299
menu:Update()
assert(not menu.btn_cook.enabled)
clock = 1300
menu:Update()
assert(menu.btn_cook.enabled and not menu.hasCraftedItem)
kit.uses = 1
menu:OnCook()
clock = 4300
menu:Update()
assert(menu.btn_cook.enabled and not menu.closed)
menu:OnCook()
assert(#sends == 3)
netcoop_workshop_view.on_cooking_result("1003|ok")
assert(menu.hasCraftedItem and not menu.closed)
clock = 4600
menu:Update()
assert(menu.closed and menu.updated == 3)
''')
client = (root / "client/netcoop_client_compat.script").read_text(encoding="cp1251")
assert 'elseif channel == "cooking_result" then' in client
assert "netcoop_workshop_view.on_cooking_result(data)" in client
print("PASS client sends exact kit and recipe once, waits for matching acknowledgement and refreshes live preview")
