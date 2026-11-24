"""Workshop on the server (actual netcoop_workshop and GAMMA's actual crafting
code: ui_workshop + zz_ui_workshop_keep_crafting_window_open +
zzzzzz_ui_workshop_nearby_stashes + craft_use_low_cond +
zzzzzz_craft_use_low_cond_nearby_stashes, from scripts/fixtures/workshop;
Lua 5.1, the world stubbed). The server rebuilds the recipe and the toolkit
state itself and runs GAMMA's UpdateItem/Craft headless for the player:
components from the inventory and from a stash in range are used up, belt
artefacts are not, the result is created; missing components, a missing
toolkit or an unknown recipe change nothing; a recipe book teaches the
recipe once (kept with the character, sent to the client) and is used up;
only a toolkit, a mechanic's vise or a furniture workshop is a workshop.
Disassembly runs GAMMA's leaf for the item and the tool. The client sends
"craft <type> <index>" from the workshop that opened the window,
"disassemble" for GAMMA's disassembly leaves, "recipe_read" for books, and
unlocks the recipes the server sends."""
from pathlib import Path
import re
from lupa.lua51 import LuaRuntime
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp

here = Path(__file__).resolve().parent
root = here / "netcoop-overlay"
gamma = here / "fixtures/workshop"
lua = LuaRuntime(unpack_returned_tuples=True)
g = lua.globals()
lua.execute(r'''
function printf() end
function printe() end
strformat = string.format
function class(name)
    local env = getfenv(2)
    return function(base)
        local c = {}
        c.__index = c
        setmetatable(c, {__index = base})
        env[name] = c
    end
end
CUIScriptWnd, CUIListBoxItem = {}, {}
function str_explode(s, sep)
    local out = {}
    for part in string.gmatch(s, "([^" .. sep .. "]+)") do out[#out + 1] = (part:gsub("^%s+", ""):gsub("%s+$", "")) end
    return out
end
function GetARGB() return 0 end
utils_xml = {get_color = function() return "" end, set_icon = function() error("UI icon used on the server") end}
utils_obj = {play_sound = function() error("UI sound on the server") end}
ui_item = {get_sec_name = function(s) return s end}
game = {translate_string = function(id) return "<" .. id .. ">" end}
game_achievements = {has_achievement = function() return false end}
stats = {}
game_statistics = {increment_statistic = function(n) stats[n] = (stats[n] or 0) + 1 end}
function CreateTimeEvent() error("time event from the headless window") end
function random_number(a) return a end
function spairs(t, f)
    local keys = {}
    for k in pairs(t) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return f(t, a, b) end)
    local i = 0
    return function() i = i + 1; if keys[i] then return keys[i], t[keys[i]] end end
end
clsid = {inventory_box_s = 7}
-- world
objects, next_id = {}, 100
ACTOR = 0
function make(sec, parent, extra)
    next_id = next_id + 1
    local o = {_id = next_id, _sec = sec, _parent = parent, _cond = 1}
    for k, v in pairs(extra or {}) do o[k] = v end
    function o:id() return self._id end
    function o:section() return self._sec end
    function o:condition() return self._cond end
    function o:name() return self._name or (self._sec .. self._id) end
    function o:clsid() return self._clsid or 1 end
    function o:get_remaining_uses() return 1 end
    function o:position() return self._pos or {x = 0, y = 0, z = 0} end
    function o:parent() if self._parent == 0 then return actor end return objects[self._parent] end
    function o:iterate_inventory_box(fn, arg)
        for _, it in pairs(objects) do if it._parent == self._id then fn(arg, it) end end
    end
    objects[o._id] = o
    return o
end
belt = {}
actor = {_id = ACTOR}
function actor:id() return 0 end
function actor:iterate_inventory(fn, arg)
    local list = {}
    for _, it in pairs(objects) do if it._parent == ACTOR then list[#list + 1] = it end end
    table.sort(list, function(a, b) return a._id < b._id end)
    for _, it in ipairs(list) do fn(arg, it) end
end
function actor:iterate_belt(fn) for _, it in ipairs(belt) do fn(actor, it) end end
infos = {}
function actor:has_info(i) return infos[i] or false end
function actor:position() return {x = 0, y = 0, z = 0} end
db = {actor = actor, storage = {}}
level = {object_by_id = function(id) if id == 0 then return actor end return objects[id] end}
get_object_by_id = level.object_by_id
function distance_between_safe(a, b) local p = b:position(); return math.sqrt(p.x * p.x + p.z * p.z) end
function alife_release_id(id) objects[id] = nil end
function alife_release(obj) objects[obj:id()] = nil end
created = {}
function alife_create_item(sec, owner, t)
    local o = make(sec, owner:id(), {})
    if t and t.cond then o._cond = t.cond end
    if t and t.ammo then o._ammo = t.ammo end
    created[#created + 1] = sec
    return o
end
storage = {}
alife_storage_manager = {get_state = function() return storage end}
SECTIONS = {itm_basickit = "tool", itm_advancedkit = "tool", itm_expertkit = "tool", itm_drugkit = "tool", itm_ammokit = "tool",
    itm_artefactskit = "tool", prt_i_fabrics = "part", prt_i_scrap = "part", bandage = "item", medkit = "item",
    af_medusa = "arty", recipe_basic_1 = "recipe", kolbasa = "item", wpn_pm = "weapon"}
function IsItem(kind, sec, obj)
    sec = sec or (obj and obj:section())
    if kind == "recipe" then return SECTIONS[sec] == "recipe" end
    return false
end
function IsWeapon(o) return SECTIONS[o:section()] == "weapon" end
function IsOutfit() return false end
function IsHeadgear() return false end
function SYS_GetParam(_, sec, key)
    if key == "kind" then return SECTIONS[sec] == "arty" and "i_arty" or "i_part" end
end
utils_item = {is_degradable = function() return false end, discharge = function(o) objects[o:id()] = nil end}
functors = {itm_basickit = "workshop_tool.start_workshop_basic", itm_advancedkit = "workshop_tool.start_workshop_advanced"}
ini_sys = {
    section_exist = function(_, s) return SECTIONS[s] ~= nil end,
    r_string_ex = function(_, s, k) if k == "use1_action_functor" then return functors[s] end end,
    r_float_ex = function() return nil end,
}
-- craft.ltx: [1] title, x_<result> = tool, recipe, comp, n, comp, n
craft_lines = {
    {"title", "st_craft_medical"},
    {"x_bandage", "1,recipe_basic_0,prt_i_fabrics,2,prt_i_scrap,1"},
    {"x_medkit", "1,recipe_basic_1,prt_i_fabrics,1,prt_i_scrap,1"},
    {"x_kolbasa", "2,recipe_basic_0,prt_i_scrap,1,prt_i_fabrics,1"},
}
ini_craft = {
    section_exist = function(_, s) return s == "1" end,
    line_count = function() return #craft_lines end,
    r_line = function(_, s, i) local l = craft_lines[i + 1]; return true, l[1], l[2] end,
}
itms_manager = {ini_craft = ini_craft, ini_manager = {r_string_ex = function() return nil end}}
function parse_list(ini, sec, key) return {"mech_" .. key} end
sent = {}
function netcoop_send_to_actor(id, ch, data) sent[#sent + 1] = ch .. "|" .. data end
ui_mcm = nil
''')

def load(table_name, path):
    t = lua.table()
    lua.execute("local env = ...; setfenv(assert(loadstring(select(2, ...), select(3, ...))), setmetatable(env,{__index=_G}))()",
                t, path.read_text(encoding="utf-8"), "@" + path.name)
    g[table_name] = t
    return t

ws = load("ui_workshop", gamma / "ui_workshop.lua")
load("zz_ui_workshop_keep_crafting_window_open", gamma / "zz_ui_workshop_keep_crafting_window_open.lua")
nearby = load("zzzzzz_ui_workshop_nearby_stashes", gamma / "zzzzzz_ui_workshop_nearby_stashes.lua")
low = load("craft_use_low_cond", gamma / "craft_use_low_cond.lua")
low2 = load("zzzzzz_craft_use_low_cond_nearby_stashes", gamma / "zzzzzz_craft_use_low_cond_nearby_stashes.lua")
lua.execute("function RegisterScriptCallback() end")
for m in (nearby, low, low2):
    m.on_game_start()
server = load("netcoop_workshop", root / "server/netcoop_workshop.script")
recipe_name = "netcoop_workshop_recipe.script"
assert (root / "server" / recipe_name).read_bytes() == (root / "client" / recipe_name).read_bytes()
recipe_keys = load("netcoop_workshop_recipe", root / "server" / recipe_name)

def inv():
    return sorted(o._sec for o in g.objects.values() if o._parent == 0)

def item(sec, parent=0, **kw):
    return lua.eval("make")(sec, parent, lua.table_from(kw))

kit = item("itm_basickit")
item("prt_i_fabrics"); item("prt_i_fabrics"); item("prt_i_fabrics")
item("prt_i_scrap")
arty = item("af_medusa"); g.belt[1] = arty

# 1. a default recipe from a toolkit: components used up, result made
assert server.craft(0, 1, kit, "craft 1 1") == ""
assert inv() == ["af_medusa", "bandage", "itm_basickit", "prt_i_fabrics"], inv()
assert g.stats["items_crafted"] == 1
# 2. not enough components: nothing changes
before = inv()
assert server.craft(0, 1, kit, "craft 1 1") == "<craft_warning_4>"
assert inv() == before
# 3. components in a stash within range are used (the player's own stash)
stash = item("stash_box", 9999, _clsid=7, _pos=lua.table_from({"x": 3, "y": 0, "z": 4}))
lua.execute(f"storage.player_created_stashes = {{[{stash._id}] = true}}")
item("prt_i_fabrics", stash._id); item("prt_i_scrap", stash._id)
assert server.craft(0, 1, kit, "craft 1 1") == ""
assert inv().count("bandage") == 2 and "prt_i_fabrics" not in inv(), inv()
assert not any(o._parent == stash._id for o in g.objects.values())
assert g.objects[arty._id]            # the belt artefact is never an ingredient
# 4. an unknown recipe, then the book teaches it once
item("prt_i_fabrics"); item("prt_i_scrap")
r = server.craft(0, 1, kit, "craft 1 2"); assert r == "<craft_warning_2>", r
book = item("recipe_basic_1")
assert server.read_recipe(0, book) == ""
assert book._id not in g.objects and g.sent[len(g.sent)] == "recipes|recipe_basic_1"
assert g.db.storage[0].pstor.netcoop_recipes == "recipe_basic_1"
book2 = item("recipe_basic_1")
assert server.read_recipe(0, book2) == "<st_recipe_is_known>" and book2._id in g.objects
assert server.craft(0, 1, kit, "craft 1 2") == ""
assert "medkit" in inv()
server.command(0, "get")
assert g.sent[len(g.sent)] == "recipes|recipe_basic_1"
# 5. a recipe for the advanced toolkit with only the basic one: no
item("prt_i_scrap"); item("prt_i_fabrics")
assert server.craft(0, 1, kit, "craft 1 3") == "<craft_warning_3>"
assert "kolbasa" not in inv() and "prt_i_scrap" in inv()
adv = item("itm_advancedkit")
assert server.craft(0, 1, adv, "craft 1 3") == ""
assert "kolbasa" in inv()
# 6. only workshops; bad requests
assert server.craft(0, 1, item("prt_i_scrap"), "craft 1 1") == "this item is not a workshop"
assert server.craft(0, 2, stash, "craft 1 1") == "this is not a workshop"
lua.execute(f"storage.workshop_stashes = {{[1] = {stash._id}}}")
assert server.craft(0, 2, stash, "craft 9 9") == "no such recipe"
assert server.craft(0, 1, kit, "craft x") == "bad recipe"
# a mechanic's vise: access from bind_awr, tiers from the player's infos
vise = item("physic_object", 9999, _name="awr_tiski_bar")
lua.execute("bind_awr = {access = function(o) return o:name() == 'awr_tiski_bar' end}")
assert server.craft(0, 2, vise, "craft 1 9") == "no such recipe"
lua.execute("bind_awr.access = function() return false end")
assert server.craft(0, 2, vise, "craft 1 1") == "the mechanic has not given you access"

# The same displayed recipe can have different row numbers on the two
# Lua states when workshop_autoinject inserts its overrides in hash order.
lua.execute(r'''
local is_item=IsItem
function IsItem(kind,sec,obj)
    if kind=="ammo" and (sec=="ammo_9x18_fmj" or sec=="ammo_9x18_fmj_bad") then return 10 end
    return is_item(kind,sec,obj)
end
functors.itm_ammokit="workshop_tool.start_workshop_ammo"
SECTIONS.ammo_9x18_fmj="ammo";SECTIONS.ammo_9x18_fmj_bad="ammo";SECTIONS.prt_i_ammo="part"
craft_lines[#craft_lines+1]={"x_ammo_9x18_fmj","5,recipe_ammo_0,ammo_9x18_fmj_bad,1,prt_i_ammo,3"}
ammo_recipe={sec="ammo_9x18_fmj",tool=5,rsp="recipe_ammo_0",{"ammo_9x18_fmj_bad",1},{"prt_i_ammo",3}}
''')
ammo_kit = item("itm_ammokit")
bad_box = item("ammo_9x18_fmj_bad")
lua.execute("local o=objects[...];function o:ammo_get_count()return 10 end;function o:ammo_box_size()return 10 end", bad_box._id)
parts = [item("prt_i_ammo") for _ in range(3)]
ammo_key = recipe_keys.key(g.ammo_recipe)
assert server.craft(0, 1, ammo_kit, "craft_recipe 1 0000000000000000") == "no such recipe"
assert bad_box._id in g.objects and all(p._id in g.objects for p in parts)
assert server.craft(0, 1, ammo_kit, f"craft_recipe 1 {ammo_key}") == ""
assert bad_box._id not in g.objects and all(p._id not in g.objects for p in parts)
boxes = [o for o in g.objects.values() if o._sec == "ammo_9x18_fmj"]
assert len(boxes) == 1 and boxes[0]._ammo == 10
assert server.craft(0, 1, ammo_kit, f"craft_recipe 1 {ammo_key}") == "<craft_warning_4>"
print("PASS actual ammo crafting: recipe key independent of row, invalid key changes nothing, one full output box and exact parts consumed")

# 7. disassembly: GAMMA's leaf for the item kind, after the tool check
lua.execute("""
dis = {}
item_parts = {is_suitable_dtool = function(o, t) return t:section() == 'itm_basickit' end,
  disassembly_item = function(o, t) dis[#dis + 1] = 'item ' .. o:section() end,
  disassembly_weapon = function(o, t) dis[#dis + 1] = 'weapon ' .. o:section() end,
  disassembly_outfit = function(o, t) dis[#dis + 1] = 'outfit ' .. o:section() end}
""")
pm = item("wpn_pm")
assert server.disassemble(pm, kit) == "" and g.dis[1] == "weapon wpn_pm"
assert server.disassemble(pm, adv) == "<st_news_dis_items>" and len(g.dis) == 1

# 7b. upgrades: GAMMA's tree evaluated headless, cells clicked in tree order
lua.execute("""
SECTIONS.itm_upgrade_kit = "kit"; SECTIONS.itm_gunsmith_toolkit = "kit"
installed = {}
tree = {[1] = {
  [1] = {section = "up_firsta_pm", tool = "itm_upgrade_kit", effect = {up_seconda_pm = true}},
  [2] = {section = "up_firstb_pm", tool = "itm_upgrade_kit", effect = {up_seconda_pm = true}},
  [3] = {section = "up_seconda_pm", tool = "itm_upgrade_kit", solo = true},
}}
function k2t_table(t) local keys = {}; for k in pairs(t) do keys[#keys + 1] = k end; for k in pairs(keys) do end
  for k in pairs(t) do t[k] = nil end; for i, k in ipairs(keys) do t[i] = k end end
function t2k_table(t) local n = #t; for i = 1, n do t[t[i]] = true; t[i] = nil end end
function is_not_empty(t) return t and next(t) ~= nil end
function random_key_table(t) local keys = {}; for k in pairs(t) do keys[#keys + 1] = k end; table.sort(keys); return keys[1] end
function odd(n) return n % 2 == 1 end
inventory_upgrades = {}
item_weapon = {clear_cache = function() end}
function SendScriptCallback() end
function GetItemList(kind) if kind == "workshop" then return {itm_gunsmith_toolkit = {wpn_pm = true}} end return {} end
local base_isitem = IsItem
function IsItem(kind, sec, obj)
  sec = sec or (obj and obj:section())
  if kind == "upgrade" then return SECTIONS[sec] == "kit" and sec ~= "itm_gunsmith_toolkit" end
  return base_isitem(kind, sec, obj)
end
utils_item.get_item_remaining_uses = function() return 1 end
utils_item.get_upgrades_tree = function(sec) return sec == "wpn_pm" and tree or nil end
utils_item.get_upgrades_installed = function(obj, _, to_key)
  local t = {}; for s in pairs(installed) do t[s] = true end; return t end
""")
pm2 = item("wpn_pm")
lua.execute(f"local o = objects[{pm2._id}]; function o:install_upgrade(s) installed[s] = true; return true end; function o:force_unload_magazine() unloaded = true end")
gun_kit = item("itm_gunsmith_toolkit")
k1 = item("itm_upgrade_kit"); k2 = item("itm_upgrade_kit")
# the second column needs the first: alone it stays disabled
assert server.upgrade(0, pm2, "upgrade 0 1.3") == "<st_upgr_disable>" and not g.installed["up_seconda_pm"]
# first and second column: both installed, two kits used up, magazine unloaded
assert server.upgrade(0, pm2, "upgrade 0 1.3 1.1") == ""
assert g.installed["up_firsta_pm"] and g.installed["up_seconda_pm"] and g.unloaded
assert k1._id not in g.objects and k2._id not in g.objects
# the pair's other upgrade cannot be added any more; no kit, no upgrade
k3 = item("itm_upgrade_kit")
assert server.upgrade(0, pm2, "upgrade 0 1.2") == "<st_upgr_disable>" and not g.installed["up_firstb_pm"]
assert server.upgrade(0, pm2, "upgrade 0 1.1") == "this upgrade is installed"
assert server.upgrade(0, pm2, "upgrade 0 2.1") == "no such upgrade"
assert server.upgrade(0, kit, "upgrade 0 1.1") == "this item has no upgrades"
assert server.upgrade(0, pm2, "upgrade 77 1.2") == "this is not a workshop"
assert server.upgrade(0, pm2, "upgrade 0") == "nothing to install"

# A native-install exception happens after GAMMA sets the shared free-upgrade
# flag and before its normal reset. Preserve the caller's exact nil/false/true
# value, and ensure the existing UI helper restoration also survives.
server_upgrade_leaf = g.ui_workshop.UIWorkshopUpgrade.Upgrade
def failed_workshop(previous=None):
    failed = item("wpn_pm")
    remaining = item("itm_upgrade_kit")
    g.inventory_upgrades.force_upgrade = previous
    lua.execute(f'''
    installed={{}};inst3={{}}
    local o=objects[{failed._id}]
    function o:force_unload_magazine()end
    function o:install_upgrade()error('fixture native install failed')end
    saved_icon=utils_xml.set_icon;saved_sound=utils_obj.play_sound;saved_element=ui_workshop.list_element
    ''')
    current_leaf = g.ui_workshop.UIWorkshopUpgrade.Upgrade
    g.ui_workshop.UIWorkshopUpgrade.Upgrade = server_upgrade_leaf
    try:
        server.upgrade(0, failed, "upgrade 0 1.1")
        raise AssertionError("native install failure was swallowed")
    except __import__('lupa.lua51', fromlist=['LuaError']).LuaError as error:
        assert 'fixture native install failed' in str(error)
    finally:
        g.ui_workshop.UIWorkshopUpgrade.Upgrade = current_leaf
    assert g.inventory_upgrades.force_upgrade is previous
    lua.execute('assert(utils_xml.set_icon==saved_icon and utils_obj.play_sound==saved_sound and ui_workshop.list_element==saved_element)')
    assert remaining._id in g.objects

for previous in (None, False, True):
    failed_workshop(previous)
    # Normal completion restores the same caller context too; exactly one
    # upgrade kit is spent and a replay cannot install or charge again.
    recovered = item("wpn_pm")
    lua.execute(f'''
    installed={{}};native_calls=0
    local o=objects[{recovered._id}]
    function o:force_unload_magazine()end
    function o:install_upgrade(s)native_calls=native_calls+1;installed[s]=true;return true end
    ''')
    g.inventory_upgrades.force_upgrade = previous
    before_kits = inv().count("itm_upgrade_kit")
    assert server.upgrade(0, recovered, "upgrade 0 1.1") == ""
    assert g.inventory_upgrades.force_upgrade is previous
    assert g.native_calls == 1 and inv().count("itm_upgrade_kit") == before_kits - 1
    assert server.upgrade(0, recovered, "upgrade 0 1.1") == "this upgrade is installed"
    assert g.native_calls == 1 and inv().count("itm_upgrade_kit") == before_kits - 1
g.inventory_upgrades.force_upgrade = None
print('PASS workshop forced-install scope: exceptions and success restore nil/false/true; one kit per new upgrade, replay unchanged')

# 7c. a mechanic NPC's repair and upgrades: the mechanic is the speaker
lua.execute("""
events = {}
function SetEvent(k, v) events[k] = v end
function GetEvent(k) return events[k] end
function IsStalker(o) return o._stalker == true end
money = 5000
speakers, paid = {}, {}
inventory_upgrades = {
  precondition_functor_a = function(_, stats)
    speakers[#speakers + 1] = events.used_npc_id
    return (stats == 'cheap' and money >= 100) and 0 or 2 end,
  effect_upgrade_item = function(obj) paid[#paid + 1] = 'lend ' .. obj:section() end,
  can_repair_item = function(sec) return sec == 'wpn_pm' end,
  can_afford_repair_item = function() return money >= 200 end,
  effect_repair_item = function(sec, cond) money = money - 200; paid[#paid + 1] = 'repair ' .. sec .. ' by ' .. tostring(events.used_npc_id) end,
}
tree[1][1].stats = 'cheap'; tree[1][2].stats = 'cheap'; tree[1][3].stats = 'dear'
""")
mech = item("stalker_mechanic", 9999, _stalker=True, _alive=True)
lua.execute(f"local m = objects[{mech._id}]; function m:alive() return true end")
pm3 = item("wpn_pm")
lua.execute(f"""local o = objects[{pm3._id}]; o._cond = 0.4
function o:install_upgrade(s) inst3 = inst3 or {{}}; inst3[s] = true; return true end
function o:force_unload_magazine() end
function o:set_condition(c) self._cond = c end""")
lua.execute(f"installed = {{}}; utils_item.get_upgrades_installed = function(obj) local t = {{}}; for s in pairs(inst3 or {{}}) do t[s] = true end; return t end")
assert server.mechanic(0, mech, f"mupgrade {pm3._id} 1.1") == ""
assert g.inst3["up_firsta_pm"] and list(g.speakers.values())[-1] == mech._id and g.events.used_npc_id is None
assert server.mechanic(0, mech, f"mupgrade {pm3._id} 1.2") == "<st_upgr_disable>"      # the pair
assert server.mechanic(0, mech, f"mupgrade {pm3._id} 1.3") == "<st_upgr_disable>"      # his price/rules
lua.execute("tree[1][3].stats = 'cheap'")
assert server.mechanic(0, mech, f"mupgrade {pm3._id} 1.3") == ""                       # parent installed
assert server.mechanic(0, mech, f"mrepair {pm3._id}") == "" and g.objects[pm3._id]._cond > 0.99
assert g.money == 4800 and f"repair wpn_pm by {mech._id}" in list(g.paid.values())
assert server.mechanic(0, mech, f"mrepair {pm3._id}") == "<st_upgr_cant_do>"            # already repaired
assert server.mechanic(0, kit, f"mrepair {pm3._id}") == "this is not a mechanic"
foreign = item("wpn_pm", 9999)
assert server.mechanic(0, mech, f"mrepair {foreign._id}") == "item is not in your inventory"

# 8. server routing (netcoop_server_compat.item_action) and the command
compat = (root / "server/netcoop_server_compat.script").read_text(encoding="utf-8")
assert 'string.match(action, "^craft_recipe %d+ [0-9a-f]+$")' in compat
assert "netcoop_workshop.disassemble(item, target)" in compat and "netcoop_workshop.read_recipe(actor_id, item)" in compat
assert 'cmd == "recipes"' in (root / "server/netanomaly_server.script").read_text(encoding="utf-8")

# ---------------------------------------------------------------- client
lua.execute(r'''
actions = {}
function netcoop_item_action(kind, id, target, action) actions[#actions + 1] = string.format("%d %d %d %s", kind, id, target, action); return true end
commands = {}
function netcoop_command(c) commands[#commands + 1] = c end
function netcoop_pure_client() return true end
callbacks = {}
function RegisterScriptCallback(n, f) callbacks[n] = f end
unlocked, interactions = {}, {}
ui_pda_encyclopedia_tab = {is_unlocked_note = function(n) return unlocked[n] or false end}
function SendScriptCallback(n, kind, _, sec) interactions[#interactions + 1] = kind .. " " .. sec; unlocked["encyclopedia__notes_" .. sec] = true end
workshop_tool = {start_workshop_basic = function(obj) opened = "basic" end}
ui_furniture_workshop = {OpenWorkshop = function(id) opened = "furniture" end}
viewed = {}
item_recipe = {start = function(sec) viewed[#viewed + 1] = sec end}
actor_menu = {set_msg = function() end}
actor_effects = {play_item_fx = function() end}
function get_hud() return nil end
item_parts = {disassembly_item = function() error("client must not disassemble") end,
  disassembly_weapon = function() error("client must not disassemble") end,
  disassembly_outfit = function() error("client must not disassemble") end}
''')
view = load("netcoop_workshop_view", root / "client/netcoop_workshop_view.script")
view.on_game_start()
g.callbacks.actor_on_first_update()
assert g.commands[1] == "recipes get"
lua.execute(r'''
local configured={charcoal={[42]=1}}
local control={
    Update=function(self)self.updates=(self.updates or 0)+1 end,
    On_CC_Mouse1=function(self)
        self.fuel_ready = self.objs.charcoal and self.objs.charcoal[42]==1
        return "selection handled"
    end,
}
item_cooking={UICook=control}
callbacks.actor_on_first_update()
local update=control.Update
callbacks.actor_on_first_update();assert(control.Update==update)
local panel=setmetatable({
    objs={kerosene={[41]=1}},
    item_info={Update=function(self)self.cleared=(self.cleared or 0)+1 end},
    GetSelectedMeal=function(self)return self.meal end,
    Load_ActorItems=function(self)for k,v in pairs(configured)do self.objs[k]=v end end,
},{__index=control})
assert(panel:On_CC_Mouse1()=="selection handled" and panel.fuel_ready and not panel.objs.kerosene)
configured={};panel:On_CC_Mouse1();assert(not panel.fuel_ready and not panel.objs.charcoal)
panel:Update();assert(panel.item_info.cleared==1 and panel.updates==1)
panel.meal={};panel:Update();assert(panel.item_info.cleared==1 and panel.updates==2)
''')
print("PASS cooking preview refreshes fuel from current inventory before the original checks and clears stale tooltips")
g.workshop_tool.start_workshop_basic(kit)
assert g.opened == "basic" and view.opened_from.kind == 1 and view.opened_from.id == kit._id
win = lua.eval("{craft_allow_r = true, last_type = 1, selected_index = 2, recipes={{false,ammo_recipe}}, btn_craft = {Enable = function() end}}")
g.ui_workshop.UIWorkshopCraft.Craft(win)
assert g.actions[1] == f"1 {kit._id} 65535 craft_recipe 1 {ammo_key}", g.actions[1]
g.ui_furniture_workshop.OpenWorkshop(stash._id)
g.ui_workshop.UIWorkshopCraft.Craft(win)
assert g.actions[2] == f"2 {stash._id} 65535 craft_recipe 1 {ammo_key}"
g.callbacks.physic_object_on_use_callback(vise, g.actor)
g.ui_workshop.UIWorkshopCraft.Craft(win)
assert g.actions[3] == f"2 {vise._id} 65535 craft_recipe 1 {ammo_key}"
g.item_parts.disassembly_weapon(pm, kit)
assert g.actions[4] == f"1 {pm._id} {kit._id} disassemble"
book3 = item("recipe_basic_1")
g.item_recipe.func_recipe(book3)
assert g.actions[5] == f"1 {book3._id} 65535 recipe_read" and g.viewed[1] == "recipe_basic_1"
view.receive_recipes("recipe_basic_1,recipe_basic_1")
assert list(g.interactions.values()) == ["notes recipe_basic_1"]
g.item_recipe.func_recipe(book3)                   # known now: no request
assert len(g.actions) == 5
# the upgrade window sends the newly checked cells
lua.execute("installed = {up_firsta_pm = true}; utils_item.get_upgrades_installed = function() local t = {}; for k in pairs(installed) do t[k] = true end; return t end")
upwin = lua.eval("""function(obj)
  local function cell(on) return {btn = {GetCheck = function() return on end}} end
  return {CC = {GetCell_Selected = function() return obj end}, upgr = tree,
    upgr_xml = {[1] = {[1] = cell(true), [2] = cell(false), [3] = cell(true)}}, closed = false,
    Close = function(self) self.closed = true end}
end""")(pm2)
g.utils_obj = lua.eval("{play_sound = function() end}")
g.ui_workshop.UIWorkshopUpgrade.Upgrade(upwin)
assert g.actions[len(g.actions)] == f"1 {pm2._id} 65535 upgrade 0 1.3" and upwin.closed
# the mechanic's window asks the server
lua.execute("""ui_inventory = {UIInventory = {}}
function CreateTimeEvent() end""")
g.callbacks.actor_on_first_update()                 # install again: now ui_inventory is there
rwin = lua.eval(f"{{npc_id = {mech._id}, upgr = {{id = {pm3._id}}}, upgr_last_row = 1, upgr_last_col = 2, upgr_last_ii = 1,"
                "upx = {[1] = {btn = {SetCheck = function() end}}}, npc_up_repair = {Enable = function() end}}")
g.ui_inventory.UIInventory.RMode_UpgradeYes(rwin)
assert g.actions[len(g.actions)] == f"2 {mech._id} 65535 mupgrade {pm3._id} 1.2", g.actions[len(g.actions)]
g.ui_inventory.UIInventory.RMode_RepairYes(rwin)
assert g.actions[len(g.actions)] == f"2 {mech._id} 65535 mrepair {pm3._id}"
cc = (root / "client/netcoop_client_compat.script").read_text(encoding="utf-8")
assert 'channel == "recipes"' in cc and "netcoop_workshop_view.receive_recipes(data)" in cc
for lang in ("rus", "eng"):
    table = (root / f"client/configs/text/{lang}/st_netcoop.xml").read_bytes().decode("cp1251")
    assert 'id="st_netcoop_workshop_unknown"' in table, lang
    assert 'id="st_netcoop_upgrade_too_many"' in table, lang
# engine: the server installs, clients get the upgrade, a client cannot install
src = here.parent / "src"
msgs = (src / "xrServerEntities/xrMessages.h").read_text(encoding="utf-8", errors="replace")
assert msgs.index("M_NETCOOP_VOICE,") < msgs.index("M_NETCOOP_ITEM_UPGRADE,") < msgs.index("MSG_FORCEDWORD")
nc = netcoop_cpp(src.parent, encoding="utf-8", errors="replace")
assert re.search(r"case GE_INSTALL_UPGRADE:\s*return false;", nc)
assert "netcoop::server_item_upgraded(this, receiver->ID" in (src / "xrGame/xrServer_process_event.cpp").read_text(encoding="utf-8", errors="replace")
items = (src / "xrGame/netcoop_items.inc").read_text(encoding="utf-8", errors="replace")
up = items[items.index("void client_on_item_upgrade"):items.index("void client_on_item_state")]
assert 'r_string(upgrade, "section")' in up and "add_upgrade(upgrade, true)" in up and "pre_install_upgrade" not in up.split("No pre_install")[0]
assert "netcoop::client_on_item_upgrade(*P)" in (src / "xrGame/Level_network_messages.cpp").read_text(encoding="utf-8", errors="replace")
print("Workshop on the server: GAMMA craft/upgrade headless, stashes, toolkits, recipes from books, disassembly: PASS")

# Actual rank-pricing and MP repair overrides used by the deployed GAMMA.
# The old server path crashed at ui_inventory.GUI.upgr.sec before installing.
lua.execute('''
money=2000
function actor:money()return money end
function actor:give_money(v)money=money+v end
function ini_file()return {r_u32=function()return 100 end,section_exist=function()return false end,
 line_exist=function()return true end,r_string_ex=function()return 'true' end}end
ini_sys.r_u32=function()return 1000 end
smooth_prog_mcm={get_tierdisc=function()return 1 end,get_wpndisc=function()return 2 end}
game_difficulties={get_eco_factor=function()return 1 end}
inventory_upgrades.get_price_percent=function()return 1.5 end
inventory_upgrades.get_global_precondition_functor=function()return 0 end
inventory_upgrades.can_upgrade_item=function()
 assert(get_speaker() and ui_inventory.GUI.upgr.sec=='wpn_pm');return true end
inventory_upgrades.effect_upgrade_item=function()end
ui_options={get=function()return false end}
function get_speaker()return level.object_by_id(GetEvent('used_npc_id'))end
ui_inventory.GUI=nil
inst3={};tree[1][1].stats='sect_up_firsta_pm'
utils_item.get_upgrades_installed=function()local t={}for k in pairs(inst3)do t[k]=true end return t end
''')
lua.execute((gamma/'upgrade_rank_pricing.lua').read_text(encoding='utf8'))
lua.execute((gamma/'inventory_upgrades_mp.lua').read_text(encoding='utf8'))
pm4=item('wpn_pm')
lua.execute(f'''
local o=objects[{pm4._id}];o._cond=.4
function o:force_unload_magazine()end
function o:set_condition(v)self._cond=v end
function o:install_upgrade(s)
 assert(ui_inventory.GUI.upgr.id==self:id())
 inventory_upgrades.effect_functor_a(nil,tree[1][1].stats,0)
 inst3[s]=true;return true
end
''')
result=server.mechanic(0,mech,f'mupgrade {pm4._id} 1.1')
assert result == '', result
assert g.money==1700 and g.inst3.up_firsta_pm and g.ui_inventory.GUI is None
assert g.events.used_npc_id is None
assert server.mechanic(0,mech,f'mrepair {pm4._id}') == ''
assert g.money==1100 and pm4._cond>0.99 and g.ui_inventory.GUI is None
lua.execute('money=0;inst3={};ui_inventory.GUI={old=true};events.used_npc_id=777')
# Exercise the actual GAMMA pricing functor after the failed workshop, not
# merely a fake predicate that ignores the leaked shared flag.
failed_workshop()
assert server.mechanic(0,mech,f'mupgrade {pm4._id} 1.1') == '<st_upgr_disable>'
assert g.money==0 and not g.inst3.up_firsta_pm and g.ui_inventory.GUI.old and g.events.used_npc_id==777
lua.execute('money=2000;inventory_upgrades.precondition_functor_a=function()error("mechanic failed")end')
try:
    server.mechanic(0,mech,f'mupgrade {pm4._id} 1.1')
    raise AssertionError('expected mechanic failure')
except __import__('lupa.lua51',fromlist=['LuaError']).LuaError:
    pass
assert g.ui_inventory.GUI.old and g.events.used_npc_id==777 and g.money==2000
print('PASS actual GAMMA rank pricing and repair: headless selected item, native effect payment, real repair charge, insufficient funds, GUI/speaker restoration on success/rejection/exception')

# The authoritative UI-open reply must bind the local mechanic too: the
# remote conversation bypasses the SP NPC binder's used_npc_id callback.
start=cc.index('local function open_ui(data)')
end=cc.index('\n-- Trade profile',start)
lua.execute(cc[start:end]+'''\nopen_remote_ui=open_ui''')
lua.execute(f'''
local npc=objects[{mech._id}]
function npc:start_upgrade(a)assert(a==db.actor and get_speaker()==self);opened_mechanic=true end
function npc:start_trade(a)assert(a==db.actor and get_speaker()==self);opened_trade=true end
function db.actor:run_talk_dialog(other)assert(other==npc and get_speaker()==other);opened_talk=true end
events.used_npc_id=777
open_remote_ui('unknown {mech._id}');assert(events.used_npc_id==777)
open_remote_ui('upgrade 65534');assert(events.used_npc_id==777)
open_remote_ui('upgrade {mech._id}');assert(opened_mechanic)
open_remote_ui('trade {mech._id}');assert(opened_trade)
open_remote_ui('talk {mech._id}');assert(opened_talk)
''')
print('PASS actual client remote mechanic/trade opener selects the correct GAMMA speaker before opening its window')
