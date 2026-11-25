"""Actual owner routing and client sidebar with Lua world/UI boundaries."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parent / "netcoop-overlay"
server = (root / "server/netcoop_server_compat.script").read_text(encoding="utf-8")
owners = server.index("local function companion_owners()")
owner_store = server[owners:server.index("local function online_actor_of(", owners)]
start = server.index("local companion_roster_next")
publisher = server[start:server.index("local function install_world_glowsticks(", start)]
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r"""
clock=1000
function time_global()return clock end
local logged_in={ [9]="one", [10]="two", [11]="three" }
function netcoop_players()return "9 10 11"end
function netcoop_actor_login(id)return logged_in[id]end
local owner_state={netcoop_companion_owner={[101]="one",[102]="two",[103]="one"}}
alife_storage_manager={get_state=function()return owner_state end}
clsid={script_stalker=2,script_actor=3}
local function npc(id,exists)
    return {alive=function()return exists end,id=function()return id end,clsid=function()return 2 end}
end
objects={[201]=npc(201,true),[202]=npc(202,true),[203]=npc(203,false),
    [204]=npc(204,true),[205]=npc(205,true)}
level={object_by_id=function(id)return objects[id]end}
local function squad(leader, ...)
    local members={...}
    return {commander_id=function()return leader end,squad_members=function()
        local i=0
        return function()i=i+1;if members[i] then return {id=members[i]}end end
    end}
end
local squads={[101]=squad(202,203,202,201),[102]=squad(204,204),[103]=squad(205,205)}
function alife_object(id)return squads[id]end
axr_companions={companion_squads=squads}
axr_task_manager={hostages_by_id={[205]=true}}
sent={};fail=false
function netcoop_send_to_actor(id,channel,data)
    assert(channel=="companions_roster")
    if fail then return false end
    sent[id]=data
    return true
end
""" + owner_store + publisher + r"""
companion_roster_update()
assert(sent[9]=="9|201.0,202.1" and sent[10]=="10|204.1" and not sent[11])
sent={};clock=2000;companion_roster_update();assert(not next(sent))
clock=6000;companion_roster_update()
assert(sent[9]=="9|201.0,202.1" and sent[10]=="10|204.1")
squads[101]=nil
sent={};fail=true;clock=7000;companion_roster_update();assert(not next(sent))
fail=false;clock=8000;companion_roster_update()
assert(sent[9]=="9|" and not sent[10] and not sent[11])
""")

client = (root / "client/netcoop_client_compat.script").read_text(encoding="cp1251")
start = client.index("function on_script_message(channel, data)")
route = client[start:client.index("-- Engine (netcoop.cpp) when the task list", start)]
lua.execute(r"""
local function actor(id)
    return {id=function()return id end,position=function()return {}end}
end
local function character(id)
    return {id=function()return id end,health=.75,clsid=function()return 2 end,alive=function()return true end,
        character_icon=function()return "icon"..id end,character_community=function()return "stalker" end,
        position=function()return {distance_to=function()return 10 end}end}
end
db={actor=actor(9)}
objects={[201]=character(201),[202]=character(202),[204]=character(204)}
function netcoop_pure_client()return true end
function main_hud_shown()return true end
CUIScriptWnd={Update=function()end}
callbacks={}
function RegisterScriptCallback(event,fn)assert(not callbacks[event]);callbacks[event]=fn end
local function widget()
    return {Show=function(self,v)self.visible=v end,InitTexture=function(self,v)self.image=v end,
        SetText=function(self,v)self.text=v end,SetTextureColor=function(self,v)self.color=v end,
        SetProgressPos=function(self,v)self.progress=v end}
end
local class={Update=function()error("stock ALife path called")end}
panel=setmetatable({_tmr=0,update_rate=2000,companion_info={},clr_list={def=0,stalker=1}},{__index=class})
for i=1,8 do
    panel.companion_info[i]={}
    for _,name in ipairs({"icon","distance","team_role","team_role_shadow","prog_health","base","danger_indicator"}) do
        panel.companion_info[i][name]=widget()
    end
end
axr_companions={UICompanionList=class,update_hud=function()panel:Update(true)end}
""" + route)
load = lua.eval("function(text)local module=setmetatable({}, {__index=_G});setfenv(assert(loadstring(text)),module)();return module end")
lua.globals().netcoop_companion_view = load((root / "client/netcoop_companion_view.script").read_text(encoding="utf-8"))
lua.execute(r"""
local slots=panel.companion_info
on_script_message("companions_roster","9|201.0,202.1")
assert(slots[1].base.visible and slots[1].icon.image=="icon201")
assert(slots[2].base.visible and slots[2].team_role.image=="ui_minimap_squad_leader")
assert(slots[2].prog_health.progress==.75 and not slots[3].base.visible)
on_script_message("companions_roster","10|204.1")
on_script_message("companions_roster","9|204.1,204.1")
assert(slots[2].icon.image=="icon202")
objects[202]=nil;panel:Update(true);assert(not slots[2].base.visible)
on_script_message("companions_roster","9|")
assert(not slots[1].base.visible)
on_script_message("companions_roster","9|201.0")
clock=clock+10000;panel:Update(true);assert(not slots[1].base.visible)
on_script_message("companions_roster","9|201.0")
callbacks.actor_on_net_destroy();panel:Update(true);assert(not slots[1].base.visible)
""")
print("PASS companion roster: owner-only server routing, no hostage/unrelated NPC, refresh/leave and replicated sidebar")
