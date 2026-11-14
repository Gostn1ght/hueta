"""Real GAMMA task callback/rewards/save-load with dedicated runtime hooks."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root=Path(__file__).resolve().parents[1]
fixtures=root/'scripts/fixtures/task-runtime'
lua=LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
function printf() end
active=true;client=false
function netcoop_enabled() return active end
function netcoop_pure_client() return client end
task={completed=2,fail=0}
CGeneralTask={};CGeneralTask.__index=CGeneralTask
setmetatable(CGeneralTask,{__call=function(cls,id)
 local obj=setmetatable({},cls);obj:__init(id);return obj
end})
CRandomTask={};CRandomTask.__index=CRandomTask
manager=setmetatable({task_info={}},CRandomTask)
function get_task_manager()return manager end
task_manager={CRandomTask=CRandomTask,get_task_manager=get_task_manager}
task_objects={CGeneralTask=CGeneralTask}
configs={paid={reward_money="5000",on_complete="rep"},items={reward_money="0",reward_item="medkit,medkit"}}
task_manager.task_ini={r_string_to_condlist=function(_,id,key)return configs[id] and configs[id][key] end}
events={};function GetEvent(key)return events[key]end
function SetEvent(key,value)events[key]=value end
local context={}
netcoop_server_compat={talk_speaker=function(id)
 if id==65535 then events.used_npc_id=context[#context].id;table.remove(context)
 else context[#context+1]={id=events.used_npc_id};events.used_npc_id=id end
end}
objects={[27]={id=function()return 27 end}};level={object_by_id=function(id)return objects[id]end}
function get_speaker()return objects[events.used_npc_id]end
function actor(id)return {_id=id,money=0,rep=0,items={},vars={},get_task=function()return nil end}end
a=actor(1);b=actor(2);db={actor=a}
function device()return {precache_frame=0}end
function printe()end
clock={diffSec=function()return 0 end};game={get_game_time=function()return clock end}
game_statistics={increment_statistic=function()end};news_manager={send_task=function()end}
function load_var(who,key)return who.vars[key]end
function save_var(who,key,value)who.vars[key]=value end
function parse_names(text)local list={} for value in text:gmatch("[^,]+")do list[#list+1]=value end return list end
xr_logic={pick_section_from_condlist=function(_,_,value)
 if value=="rep" then assert(get_speaker() and get_speaker():id()==27);db.actor.rep=db.actor.rep+100;return end
 if value=="throw" then error("injected callback failure") end
 return value
end}
dialogs={relocate_money=function(npc,money,dir)
 assert(npc:id()==27 and dir=="in");db.actor.money=db.actor.money+money
end,relocate_item_section=function(npc,section,dir,count)
 assert(npc:id()==27 and dir=="in" and section=="medkit","money text must never become an item section")
 db.actor.items[section]=(db.actor.items[section]or 0)+count
end}
good_checks=0
function CGeneralTask:check_task()
 if self.broken then error("bad optional title/target functor")end
 good_checks=good_checks+1
end
''')
for name in ('reward_constructor','give_reward','task_complete','update','save_load','object_save_load'):
    lua.execute((fixtures/(name+'.lua')).read_text(encoding='utf-8'))
lua.execute((fixtures/'task_callback.lua').read_text(encoding='utf-8'))
lua.execute('task_manager.task_callback=task_callback')
lua.execute(r'''
-- Reproduce the old payout: the native tick no longer has a speaker.
local old=CGeneralTask("paid");old.reward_item=nil;old:give_reward();assert(a.money==0)
local typo=CGeneralTask("paid");assert(typo.reward_item=="5000")
''')
lua.execute((root/'scripts/netcoop-overlay/server/netcoop_task_runtime.script').read_text(encoding='utf-8'))
lua.execute(r'''
install();local check=CGeneralTask.check_task;local callback=task_manager.task_callback
install();assert(check==CGeneralTask.check_task and callback==task_manager.task_callback)
local paid=CGeneralTask("paid");assert(paid.reward_money=="5000" and paid.reward_item==nil)
paid.task_giver_id=27;paid.repeat_timeout=10;paid.on_complete="rep";paid.status="selected"
manager.task_info.paid=paid
local tsk={get_id=function()return "paid"end}
events.used_npc_id=99;task_manager.task_callback(tsk,task.completed)
assert(a.money==5000 and a.rep==100 and b.money==0 and events.used_npc_id==99)
task_manager.task_callback(tsk,task.completed);assert(a.money==5000 and a.rep==100,"repeat callback must not pay twice")
db.actor=b;local second=CGeneralTask("paid");second.task_giver_id=27;second.on_complete="rep";second.repeat_timeout=10
manager=setmetatable({task_info={paid=second}},CRandomTask)
task_manager.task_callback(tsk,task.completed);assert(b.money==5000 and b.rep==100 and a.money==5000)
local items=CGeneralTask("items");items.task_giver_id=27;manager.task_info.items=items
task_manager.task_callback({get_id=function()return "items"end},task.completed)
assert(b.items.medkit==2)
local throwing=CGeneralTask("paid");throwing.task_giver_id=27;throwing.on_complete="throw"
manager.task_info.paid=throwing;local ok=pcall(task_manager.task_callback,tsk,task.completed)
assert(not ok and events.used_npc_id==99,"callback errors must unwind the speaker context")
-- A single invalid quest no longer prevents another quest from updating.
manager.task_info={setmetatable({id="broken",broken=true},CGeneralTask),setmetatable({id="good"},CGeneralTask)}
manager:update();assert(good_checks==1)
-- Complete only after the trader is available on the return map.
local returning=CGeneralTask("paid");returning.task_giver_id=27;returning.forced_status="complete"
manager.task_info={paid=returning};objects[27]=nil
assert(not manager:task_complete("paid") and returning.forced_status=="complete")
objects[27]={id=function()return 27 end};assert(manager:task_complete("paid"))
''')
lua.execute(r'''
-- The real GAMMA save/load path carries the same stage, target and giver
-- through A -> B (objective) -> A (hand-in), without another player's state.
function empty_table(value)for key in pairs(value)do value[key]=nil end return value end
local function clone(value)
 if type(value)~="table" then return value end
 local copy={} for k,v in pairs(value)do copy[k]=clone(v)end return copy
end
local source=setmetatable({task_info={}},CRandomTask);manager=source;db.actor=a;a.money=0;a.rep=0
local job=CGeneralTask("paid");job.status="selected";job.stage=4;job.current_target=501
job.task_giver_id=27;job.t={};source.task_info.paid=job
local checkpoint={};save_state(checkpoint)
manager=setmetatable({task_info={}},CRandomTask);load_state(clone(checkpoint))
assert(manager.task_info.paid.stage==4 and manager.task_info.paid.current_target==501 and manager.task_info.paid.task_giver_id==27)
assert(source.task_info.paid==job and checkpoint.task_objects.paid.stage==4)
local remote=manager.task_info.paid;remote.t={};remote.stage=5;remote.current_target=27
local return_checkpoint={};save_state(return_checkpoint)
manager=setmetatable({task_info={}},CRandomTask);load_state(clone(return_checkpoint))
local returned=manager.task_info.paid;assert(returned.stage==5 and returned.current_target==27 and returned.task_giver_id==27)
returned.repeat_timeout=10;returned.forced_status="complete"
assert(manager:task_complete("paid"));local tsk={get_id=function()return "paid"end}
task_manager.task_callback(tsk,task.completed);task_manager.task_callback(tsk,task.completed)
assert(a.money==5000 and a.rep==100 and b.money==5000)
''')
compat=(root/'scripts/netcoop-overlay/server/netcoop_server_compat.script').read_text(encoding='utf-8')
assert 'cancel_task_on_other_map' not in compat
assert 'if netcoop_task_runtime then netcoop_task_runtime.install() end' in compat
update=compat[compat.index('function update_player_tasks()'):compat.index('-- axr_main calls on_game_start')]
assert 'pcall(server_world_tick)' in update and 'pcall(netcoop_emission.update_player, a)' in update
lua.execute(r'''
-- Native actions are authoritative: a stale "completed" phrase cannot
-- finish a live objective, use another giver or hand in missing items.
function CRandomTask:set_task_completed(id)if self.task_info[id]then self.task_info[id].forced_status="complete"end end
task_manager.task_ini.r_float_ex=function(_,_,key)if key=="stage_complete"then return 1 end end
task_manager.task_ini.r_string_ex=function(_,id,key)
 if key=="on_complete"and id=="fetch"then return "%=fetch_reward_and_remove(fetch_fetch:1.25)%"end
end
configs.fetch={on_complete="rep_fetch"}
-- Simulate the world methods at their native boundary, including ownership
-- events whose Lua parent pointer has not caught up with the server yet.
server_items={};all_items={};fail_transfer=nil
function alife()return {object=function(_,id)return server_items[id]end}end
function alife_object(id)return server_items[id]end
function IsItem(kind,section)if kind=="multiuse"and section=="medicine"then return 5 end end
function IsArtefact()return false end
ini_sys={r_float_ex=function()return 100 end}
function alife_release_id(id)server_items[id]=nil;all_items[id].removed=true end
function make_item(id,section,uses,condition)
 local item={_id=id,_section=section,uses=uses or 1,quality=condition or 1,owner=a}
 function item:id()return self._id end
 function item:section()return self._section end
 function item:parent()return self.owner end
 function item:condition()return self.quality end
 function item:get_remaining_uses()return self.uses end
 function item:set_remaining_uses(value)self.uses=value end
 function item:get_weapon_type()return 255 end
 all_items[id]=item;server_items[id]={parent_id=a:id()};return item
end
function a:id()return self._id end
function a:iterate_inventory(fn)
 for _,item in pairs(all_items)do if item.owner==self and not item.removed then fn(self,item)end end
end
function a:iterate_belt(fn)for _,item in pairs(all_items)do if item.belt then fn(self,item)end end end
function transfer(self,item,to)
 if item:id()==fail_transfer then return end
 assert(server_items[item:id()].parent_id==self:id())
 server_items[item:id()].parent_id=to:id()
end
a.transfer_item=transfer;objects[27].transfer_item=transfer
server_items[27]={group_id=65535}
function a:set_task_state(state,id)
 self.completions=(self.completions or 0)+1
 task_manager.task_callback({get_id=function()return id end},state)
end
function a:get_task(id)return manager.task_info[id]end
news_manager.relocate_item=function()end
xr_effects={fetch_reward_and_remove=function()error("old delayed fetch must not run")end,
 reward_random_money=function(_,_,range)
  assert(server_items[101]==nil and server_items[102]==nil,"pay only after exact instances are handed in")
  db.actor.money=db.actor.money+math.floor(range[1])
 end}
local previous_pick=xr_logic.pick_section_from_condlist
xr_logic.pick_section_from_condlist=function(x,y,value)
 if value=="rep_fetch"then
  assert(server_items[101]==nil and server_items[102]==nil,"reputation also follows confirmed consumption")
  db.actor.rep=db.actor.rep+50
  xr_effects.fetch_reward_and_remove(x,y,{"fetch_fetch","1.25"});return
 end
 return previous_pick(x,y,value)
end
''')
handin=(root/'scripts/netcoop-overlay/server/netcoop_task_handin.script').read_text(encoding='utf-8')
lua.execute('local chunk=assert(loadstring(...));netcoop_task_handin={};setmetatable(netcoop_task_handin,{__index=_G});setfenv(chunk,netcoop_task_handin);chunk()',handin)
lua.execute(r'''
install();db.actor=a;events.used_npc_id=27;a.money=0;a.rep=0;a.completions=0
manager=setmetatable({task_info={}},CRandomTask)
local fetch=CGeneralTask("fetch");fetch.task_giver_id=27;fetch.stage=1
manager.task_info.fetch=fetch
a.vars.fetch_fetch="bandage";a.vars.fetch_fetch_count=2
make_item(101,"bandage");fetch.check_time=999999
assert(not manager:set_task_completed("fetch"),"a cached finished stage cannot replace the second item")
assert(server_items[101].parent_id==a:id()and a.money==0 and a.rep==0 and a.completions==0)
make_item(102,"bandage");fail_transfer=102
assert(not manager:set_task_completed("fetch"),"failed second transfer rolls back the first before any reward")
assert(server_items[101].parent_id==a:id()and server_items[102].parent_id==a:id()and a.money==0 and a.rep==0)
fail_transfer=nil;events.used_npc_id=99;assert(not manager:set_task_completed("fetch"),"wrong NPC cannot accept hand-in")
events.used_npc_id=27;fetch.stage=0;assert(not manager:set_task_completed("fetch"),"unmet objective cannot be forced complete")
fetch.stage=1;assert(manager:set_task_completed("fetch"))
assert(server_items[101]==nil and server_items[102]==nil and a.money>0 and a.rep==50 and a.completions==1)
local paid=a.money;assert(not manager:set_task_completed("fetch"));assert(a.money==paid and a.rep==50)
-- Partial medicine use keeps the same physical item and its remainder.
all_items={};server_items={[27]={group_id=65535}};local medicine=make_item(201,"medicine",5)
a.vars.fetch_fetch="medicine";a.vars.fetch_fetch_count=3
local ok,receipt=netcoop_task_handin.prepare("fetch",{},a);assert(ok)
assert(netcoop_task_handin.commit(receipt,a,objects[27])and medicine.uses==2 and server_items[201].parent_id==a:id())
-- Belt artefacts and insufficient condition cannot satisfy a fetch.
all_items={};server_items={[27]={group_id=65535}};make_item(202,"bandage").belt=true
a.vars.fetch_fetch="bandage";a.vars.fetch_fetch_count=1
assert(not netcoop_task_handin.prepare("fetch",{},a))
''')
lua.execute(r'''
-- Multi-fetch recipes reserve distinct physical instances. Optional rewards
-- require the full optional set and cannot reuse a required item.
local original_ini=task_manager.task_ini.r_string_ex
task_manager.task_ini.r_string_ex=function(self,id,key)
 if id=="multi"and key=="on_complete"then return "%=multifetch_remove(multi:true)%"end
 if id=="quality"and key=="on_complete"then return "%=remove_fetch_item(fetch_fetch)%"end
 return original_ini(self,id,key)
end
local recipe={required_items={{sec="bandage",num=1,cost=100,cond=.5}},optional_items={{sec="bandage",num=1,cost=100}}}
tasks_multifetch={save_state=function(state)state.multifetch_data={multi=recipe}end,has_optional_items=function()return false end}
xr_effects.multifetch_remove=function()error("legacy multi-fetch removal must not run")end
news_manager.relocate_money=function()end
function a:give_money(value)self.money=self.money+value end
netcoop_task_handin.install();all_items={};server_items={[27]={group_id=65535}}
local required=make_item(301,"bandage",1,.5)
assert(not netcoop_task_handin.prepare("multi",{},a),"condition threshold is strict as configured")
required.quality=1
local ok,one=netcoop_task_handin.prepare("multi",{},a)
assert(ok and #one.items==1 and not one.optional_delivered,"one object must not fulfill both requirements")
make_item(302,"bandage",1,1)
local ok,both=netcoop_task_handin.prepare("multi",{},a);assert(ok and #both.items==2 and both.optional_delivered)
assert(netcoop_task_handin.commit(both,a,objects[27]))
local prior=netcoop_task_handin.enter({_netcoop_fetch_receipt=both});local before=a.money
xr_effects.multifetch_remove(a,objects[27],{"multi","true"})
assert(a.money==before+240 and tasks_multifetch.has_optional_items("multi"))
xr_effects.multifetch_remove(a,objects[27],{"multi","true"});assert(a.money==before+240)
netcoop_task_handin.enter(prior)
-- Low-condition weapons cannot be substituted at hand-in.
all_items={};server_items={[27]={group_id=65535}};a.vars.fetch_fetch="rifle";a.vars.fetch_fetch_count=1
local rifle=make_item(303,"rifle",1,.59)
assert(not netcoop_task_handin.prepare("quality",{status_functor="actor_has_fetch_weapon_warfare"},a))
rifle.quality=.6;assert(netcoop_task_handin.prepare("quality",{status_functor="actor_has_fetch_weapon_warfare"},a))
''')
print('PASS actual GAMMA tasks: cross-map save/load and stage, fresh objective/NPC/inventory checks, whole-batch rollback, exact instance consumption before money/reputation, partial uses retained, no repeat payout and isolated actors/quest errors')

# Use GAMMA's real public cache save/load methods, then switch two characters
# and deserialize one on another location process. No cache is shared by ID.
context_source=(root/'scripts/netcoop-overlay/server/netcoop_task_context.script').read_text(encoding='utf-8')
lua.execute('local chunk=assert(loadstring(...));netcoop_task_context={};setmetatable(netcoop_task_context,{__index=_G});setfenv(chunk,netcoop_task_context);chunk()',context_source)
lua.execute(r"""
local _M={}
tasks_multifetch={save_state=function(m_data)m_data.multifetch_data=_M end,
 load_state=function(m_data)_M=m_data.multifetch_data or {} end}
axr_task_manager={bounties_by_id={}}
db.storage={[1]={pstor={}},[2]={pstor={}}}
function b:id()return self._id end
local function read()local state={};tasks_multifetch.save_state(state);return state.multifetch_data end
local function clone(value)if type(value)~='table'then return value end local out={}for k,v in pairs(value)do out[k]=clone(v)end return out end
netcoop_task_context.bind_actor(a)
read().order={required_items={{sec='bandage',num=2}}};axr_task_manager.bounties_by_id.hunt=501
netcoop_task_context.bind_actor(b)
assert(not read().order and not axr_task_manager.bounties_by_id.hunt)
read().order={required_items={{sec='vodka',num=7}}};axr_task_manager.bounties_by_id.hunt=900
netcoop_task_context.bind_actor(a)
assert(read().order.required_items[1].sec=='bandage'and axr_task_manager.bounties_by_id.hunt==501)
netcoop_task_context.capture(a)
local checkpoint=clone(db.storage[1].pstor)
netcoop_task_context.bind_actor(nil);assert(not read().order and not axr_task_manager.bounties_by_id.hunt)
-- Another server restores pstor before creating task objects.
db.storage[1].pstor=checkpoint;netcoop_task_context.bind_actor(a)
assert(read().order.required_items[1].num==2 and axr_task_manager.bounties_by_id.hunt==501)
-- Replacing pstor for the same actor ID must not reuse its previous globals.
db.storage[1].pstor={};netcoop_task_context.bind_actor(a)
assert(not read().order and not axr_task_manager.bounties_by_id.hunt)
netcoop_task_context.bind_actor(b)
assert(read().order.required_items[1].sec=='vodka'and axr_task_manager.bounties_by_id.hunt==900)
""")
assert compat.index('netcoop_task_context.bind_actor(actor)',compat.index('function restore_character_state')) < compat.index('task_manager.load_state(state)',compat.index('function restore_character_state'))
print('PASS per-character GAMMA recipes/bounty targets: A/B isolation, A->B->A location checkpoint, unbind and fresh life/same-ID restore')

# Execute actual GAMMA bounty and assault status functions under server-local
# objective proof. Missing/foreign/reused IDs never become a kill certificate.
lua.execute(r"""
task_status_functor={};local fixture_clock=0
function time_global()fixture_clock=fixture_clock+10000;return fixture_clock end
axr_task_manager.is_task_giver_valid=function()return true end
function IsStalker(_,kind)return kind=='stalker'end
map_name='cordon';level.name=function()return map_name end
local vertex_maps={[50]='radar',[60]='cordon'}
function game_graph()return {vertex=function(_,id)return {level_id=function()return id end}end}end
local sim=alife();function alife()return sim end
sim.level_name=function(_,id)return vertex_maps[id]end
function objective(id,name,vertex,kind)
 local se={id=id,m_game_vertex_id=vertex,label=name,kind=kind,live=true}
 function se:name()return self.label end
 function se:section_name()return self.kind end
 function se:clsid()return self.kind end
 function se:alive()return self.live end
 server_items[id]=se;return se
end
victim=objective(501,'named_bounty',50,'stalker')
smart=objective(601,'named_smart',50,'smart')
xr_effects.setup_bounty_task=function(_,_,params)axr_task_manager.bounties_by_id[params[1]]=501 end
xr_effects.setup_assault_task=function(_,_,params)save_var(db.actor,params[1],{smart_id=601,squad_id=701,is_enemy=true})end
SIMBOARD={smarts={[601]={smrt=smart}},squads={}}
simulation_objects={available_by_id={[601]=true}};is_squad_monster={monster=true}
function parse_list()return {'monster'}end
function evaluate_squads_smarts(_,_,squad)return squad.live end
function character_community()return 'actor_stalker'end
""")
lua.execute((fixtures/'bounty_status.lua').read_text(encoding='utf-8'))
lua.execute('local cache_assault_func={};local factions_list={};'+(fixtures/'assault_status.lua').read_text(encoding='utf-8'))
objectives_source=(root/'scripts/netcoop-overlay/server/netcoop_task_objectives.script').read_text(encoding='utf-8')
lua.execute('local chunk=assert(loadstring(...));netcoop_task_objectives={};setmetatable(netcoop_task_objectives,{__index=_G});setfenv(chunk,netcoop_task_objectives);chunk()',objectives_source)
lua.execute(r"""
netcoop_task_objectives.install();local saved=task_status_functor.bounty_task
netcoop_task_objectives.install();assert(saved==task_status_functor.bounty_task)
db.actor=a;netcoop_task_context.bind_actor(a)
xr_effects.setup_bounty_task(a,objects[27],{'hunt'})
local bounty={stage=0,status_functor='bounty_task'}
assert(task_status_functor.bounty_task(bounty,'hunt')==nil and bounty.stage==0)
-- A dead clone on the giver map is not the actual target on Radar.
victim.live=false;task_status_functor.bounty_task(bounty,'hunt');assert(bounty.stage==0)
map_name='radar';victim.live=true;task_status_functor.bounty_task(bounty,'hunt');assert(bounty.stage==0)
server_items[501]=nil;assert(task_status_functor.bounty_task(bounty,'hunt')==nil and bounty.stage==0)
server_items[501]=victim;victim.label='reused_id';victim.live=false
task_status_functor.bounty_task(bounty,'hunt');assert(bounty.stage==0)
victim.label='named_bounty';task_status_functor.bounty_task(bounty,'hunt');assert(bounty.stage==1)
assert(netcoop_task_objectives.verified(bounty,'hunt'))
-- Completion is evidence carried back with this character, not re-tested
-- against a respawned clone on the giver's server.
map_name='cordon';victim.live=true;task_status_functor.bounty_task(bounty,'hunt');assert(bounty.stage==1)
netcoop_task_context.bind_actor(b);db.actor=b
assert(not netcoop_task_objectives.verified(bounty,'hunt'))
netcoop_task_context.bind_actor(a);db.actor=a
assert(netcoop_task_objectives.verified(bounty,'hunt'))
xr_effects.setup_bounty_task(a,objects[27],{'hunt'})
assert(not netcoop_task_objectives.verified(bounty,'hunt'),'a repeated task must not reuse the old kill')
-- The actual assault functor must see living/absent enemy squads only on
-- the target server. Its preserved completion can then return to giver.
xr_effects.setup_assault_task(a,objects[27],{'raid'})
local raid={stage=0,status_functor='assault_task_status_functor'}
server_items[701]={live=true};SIMBOARD.squads[701]=true
map_name='cordon';task_status_functor.assault_task_status_functor(raid,'raid');assert(raid.stage==0)
map_name='radar';task_status_functor.assault_task_status_functor(raid,'raid');assert(raid.stage==0)
server_items[701].live=false;task_status_functor.assault_task_status_functor(raid,'raid');assert(raid.stage==1)
map_name='cordon';server_items[701].live=true
task_status_functor.assault_task_status_functor(raid,'raid');assert(raid.stage==1 and netcoop_task_objectives.verified(raid,'raid'))
""")
print('PASS actual GAMMA bounty/assault: foreign/missing/reused target rejected, live target stays pending, local kill/clear proof survives return, actor and repeat-job isolation')

lua.execute(r"""
-- Fetching wrapped artefacts returns their empty container, with no timer
-- depending on whichever db.actor happens to be bound a second later.
local original_ini=task_manager.task_ini.r_string_ex
task_manager.task_ini.r_string_ex=function(self,id,key)
 if id=='contained'and key=='on_complete'then return '%=remove_artefact_item(contained_fetch)%'end
 return original_ini(self,id,key)
end
all_items={};server_items={[27]={group_id=65535}};db.actor=a
local combo=make_item(801,'af_medusa_lead_box');a.vars.contained_fetch='af_medusa'
local created={};local refuse=false
function alife_create_item(section,owner)
 if refuse then return end
 assert(owner==a and section=='lead_box')
 local obj=make_item(901,section);created[#created+1]=obj
 return {id=obj:id(),parent_id=a:id()}
end
local ok,plan=netcoop_task_handin.prepare('contained',{},a)
assert(ok and plan.items[1].return_container=='lead_box')
refuse=true;assert(not netcoop_task_handin.commit(plan,a,objects[27]))
assert(server_items[801].parent_id==a:id()and not combo.removed and #created==0)
refuse=false;assert(netcoop_task_handin.commit(plan,a,objects[27]))
assert(combo.removed and #created==1 and server_items[901].parent_id==a:id()and not created[1].removed)
assert(not netcoop_task_handin.commit(plan,a,objects[27]),'same combination cannot hand in again')
""")
print('PASS wrapped artefact delivery: original combination consumed, empty container returned once, spawn failure rolls back original and gives no reward')

lua.execute(r"""
-- Bring quests can demand several different sections or original quest IDs.
-- The entire set is preflighted even if reward effects precede remove_item.
local original_ini=task_manager.task_ini.r_string_ex
task_manager.task_ini.r_string_ex=function(self,id,key)
 if id=='bundle'and key=='on_complete'then return '%=reward_money(1000) =remove_item(bandage:2) =remove_item(vodka)%'end
 if id=='original'and key=='on_complete'then return '%=remove_quest_item(parcel)%'end
 if id=='delivery'and key=='on_complete'then return '%=remove_delivery_item(parcel)%'end
 if id=='branch'and key=='on_complete'then return '{+choose_a} %=remove_item(bandage)%, %=remove_item(vodka)%'end
 return original_ini(self,id,key)
end
local legacy_removes=0
xr_effects.remove_item=function()legacy_removes=legacy_removes+1 end
xr_effects.remove_quest_item=function()error('legacy original removal must not run')end
xr_effects.remove_delivery_item=function()error('legacy delivery must not run')end
netcoop_task_handin.install();all_items={};server_items={[27]={group_id=65535}};db.actor=a
make_item(1001,'bandage');make_item(1002,'vodka')
assert(not netcoop_task_handin.prepare('bundle',{},a),'no partial hand-in with missing bandage')
assert(server_items[1001].parent_id==a:id()and server_items[1002].parent_id==a:id())
make_item(1003,'bandage');local ok,receipt=netcoop_task_handin.prepare('bundle',{},a)
assert(ok and #receipt.items==3);assert(netcoop_task_handin.commit(receipt,a,objects[27]))
assert(not server_items[1001]and not server_items[1002]and not server_items[1003])
local previous=netcoop_task_handin.enter({_netcoop_fetch_receipt=receipt})
xr_effects.remove_item(a,objects[27],{'bandage','2'});xr_effects.remove_item(a,objects[27],{'vodka'})
assert(legacy_removes==0);netcoop_task_handin.enter(previous)
xr_effects.remove_item(a,objects[27],{'unrelated'});assert(legacy_removes==1,'non-quest script removal retains upstream behavior')
all_items={};server_items={[27]={group_id=65535}}
local copy=make_item(1100,'parcel');local original=make_item(1101,'parcel');objects[1101]=original
a.vars.parcel={item_1_id=1101,item_1_sec='parcel'}
server_items[1101].parent_id=2
assert(not netcoop_task_handin.prepare('original',{},a),'same section cannot replace another character original')
server_items[1101].parent_id=a:id()
local ok,receipt=netcoop_task_handin.prepare('original',{},a);assert(ok and #receipt.items==1 and receipt.items[1].id==1101)
assert(netcoop_task_handin.commit(receipt,a,objects[27])and server_items[1100]and not server_items[1101])
assert(not netcoop_task_handin.prepare('delivery',{},a),'a saved original delivery ID cannot be silently replaced')
assert(not netcoop_task_handin.prepare('branch',{},a),'never consume both conditional branches')
""")
print('PASS multi-section bring/delivery quests: whole set before reward, exact quest IDs, no foreign substitution, original removal outside quest retained, conditional branch refusal')

# Delivery quests finish at their destination, not at the original giver;
# stage 2 is the result of delivery, not a substitute for the original parcel.

lua.execute((fixtures/'delivery_status.lua').read_text(encoding='utf-8'))
delivery_source=(root/'scripts/netcoop-overlay/server/netcoop_task_delivery.script').read_text(encoding='utf-8')
lua.execute('local chunk=assert(loadstring(...));netcoop_task_delivery={};setmetatable(netcoop_task_delivery,{__index=_G});setfenv(chunk,netcoop_task_delivery);chunk()',delivery_source)
lua.execute(r"""
function has_alife_info()return true end
utils_item={has_item_by_id=function(_,id,section)
 local item=all_items[id];local se=server_items[id]
 return item and not item.removed and item:section()==section and se and se.parent_id==db.actor:id()
end}
function printdbg()end
objects[28]={id=function()return 28 end,transfer_item=transfer}
server_items[28]={id=28,group_id=65535}
sim_offline_combat={task_squads={[701]=true}}
for _,name in ipairs({'check_delivery_task_npc','actor_has_package','complete_simulation_task','st_simulation_task_stext_0','st_simulation_task_stext_1'})do
 dialogs[name]=function()error('process-global delivery_task_id must not be used')end
end
local previous_ini=task_manager.task_ini.r_float_ex
task_manager.task_ini.r_float_ex=function(self,id,key)if id=='delivery'and key=='stage_complete'then return 2 end return previous_ini(self,id,key)end
configs.delivery={on_complete='rep_delivery'}
local previous_pick=xr_logic.pick_section_from_condlist
xr_logic.pick_section_from_condlist=function(x,y,value)
 if value=='rep_delivery'then
  assert(not server_items[1201]and server_items[1200],'only the original parcel is consumed before any reward')
  xr_effects.remove_delivery_item(x,y,{'parcel'});db.actor.money=db.actor.money+700;db.actor.rep=db.actor.rep+50;return
 end
 return previous_pick(x,y,value)
end
netcoop_task_runtime=nil -- global fixture install() is the runtime entry point
install();db.actor=a;manager=setmetatable({task_info={}},CRandomTask)
all_items={};server_items={[27]={group_id=65535},[28]={id=28,group_id=65535}}
local job=CGeneralTask('delivery');job.task_giver_id=27;job.status_functor='delivery_task';job.stage=1;job.repeat_timeout=10
function job:check_task()task_status_functor.delivery_task(self,self.id)end
manager.task_info.delivery=job
-- The generic removal argument is parcel, while task ID is delivery.
a.vars.delivery={item_1_id=1201,item_1_sec='parcel',target_id=28,target_squad_id=701}
a.vars.parcel=a.vars.delivery
make_item(1200,'parcel');events.used_npc_id=27
assert(not dialogs.check_delivery_task_npc()and not manager:set_task_completed('delivery'))
events.used_npc_id=28;assert(dialogs.check_delivery_task_npc()and not dialogs.actor_has_package())
assert(not dialogs.complete_simulation_task()and sim_offline_combat.task_squads[701])
objects[1201]=make_item(1201,'parcel');local old_money,old_rep=a.money,a.rep
assert(dialogs.actor_has_package()and dialogs.complete_simulation_task())
assert(a.money==old_money+700 and a.rep==old_rep+50 and not sim_offline_combat.task_squads[701])
assert(not dialogs.complete_simulation_task()and a.money==old_money+700)
db.actor=b;assert(not dialogs.check_delivery_task_npc(),'another actor cannot inherit the old recipient dialogue')
db.actor=a
""")
print('PASS actual GAMMA delivery status: destination NPC instead of issuer, original parcel before stage 2/money/reputation, stale global dialogue removed, cleanup only after success')

# Execute the real dedicated per-player update with unrelated modules throwing.
aux=LuaRuntime(unpack_returned_tuples=True)
aux.execute(r"""
local actor={id=function()return 1 end};db={actor=actor};player_tasks={};updates=0;notices=0
function printf()notices=notices+1 end
function server_game_load()end
function install_hide_hud()end
function server_debug_file()end
function server_world_tick()error('unrelated world script')end
zz_netcoop_sandbox={update=function()error('sandbox')end}
netcoop_emission={update_player=function()error('emission')end}
netcoop_psi_storm={update_player=function()error('psi')end}
netcoop_task_runtime={install=function()end}
level={object_by_id=function()return nil end}
task_manager={get_task_manager=function()return {update=function()updates=updates+1 end}end}
""")
aux.execute(compat[compat.index('local task_aux_errors = 0'):compat.index('-- axr_main calls on_game_start')])
aux.execute('update_player_tasks();assert(updates==1 and notices==4);db.actor=nil;update_player_tasks();assert(updates==1)')
print('PASS actual dedicated task update continues after independent sandbox/world/emission/psi failures and skips absent actor')

# Private fetch offer cache: capture the public GAMMA callback boundary,
# never copy/splice private upvalues. Two players can preview the same trader.
lua.execute(r"""
tasks_fetch={}
local chunk=assert(loadstring([[
 local DIALOG_ID={}
 function save_state(data)data.tasks_fetch_ids=DIALOG_ID end
 function load_state(data)DIALOG_ID=data.tasks_fetch_ids or {} end
 function offer(npc,section,count)DIALOG_ID[npc]={section=section,count=count}end
 function read(npc)return DIALOG_ID[npc]end
]]));setfenv(chunk,tasks_fetch);chunk()
netcoop_task_context.register_callback('save_state',tasks_fetch.save_state)
netcoop_task_context.register_callback('load_state',tasks_fetch.load_state)
netcoop_task_context.bind_actor(nil);netcoop_task_context.bind_actor(a)
tasks_fetch.offer(27,'bandage',2)
netcoop_task_context.bind_actor(b);assert(not tasks_fetch.read(27))
tasks_fetch.offer(27,'vodka',5)
netcoop_task_context.bind_actor(a);assert(tasks_fetch.read(27).section=='bandage'and tasks_fetch.read(27).count==2)
netcoop_task_context.capture(a)
local checkpoint=db.storage[1].pstor.netcoop_quest_context.fetch
assert(checkpoint[27].section=='bandage')
netcoop_task_context.bind_actor(b);assert(tasks_fetch.read(27).section=='vodka')
netcoop_task_context.bind_actor(nil);assert(not tasks_fetch.read(27))
""")
assert 'netcoop_task_context.register_callback(name, handler)' in compat
print('PASS private GAMMA fetch offer cache uses original callback boundary and stays with the correct character/trader')

# Native inventory restoration assigns new network IDs. Preserve the UID and
# migrate legacy quest IDs only through the server's saved->restored mapping.
identity_source=(root/'scripts/netcoop-overlay/server/netcoop_task_identity.script').read_text(encoding='utf-8')
lua.execute('local chunk=assert(loadstring(...));netcoop_task_identity={};setmetatable(netcoop_task_identity,{__index=_G});setfenv(chunk,netcoop_task_identity);chunk()',identity_source)
lua.execute(r"""
item_uids={}
function netcoop_item_uid(id)return item_uids[id]or''end
all_items={};server_items={};db.actor=a
a.vars.delivery={item_1_id=1301,item_1_sec='parcel'};a.vars.parcel=a.vars.delivery
objects[1301]=make_item(1301,'parcel');item_uids[1301]='9007199254740993'
assert(netcoop_task_identity.refresh('delivery',a))
assert(a.vars.delivery.item_1_uid=='9007199254740993','UID is text, not an imprecise Lua double')
-- Arrival at another server: old ID reused by a same-section copy, while
-- the original UID was restored under another ID.
all_items={};server_items={};objects[1301]=make_item(1301,'parcel');item_uids[1301]='unrelated'
objects[1309]=make_item(1309,'parcel');item_uids[1309]='9007199254740993'
assert(netcoop_task_identity.refresh('delivery',a)and a.vars.delivery.item_1_id==1309)
local ok,plan=netcoop_task_handin.prepare('delivery',{},a)
assert(ok and plan.items[1].id==1309,'same section at the old network ID is never a substitute')
a.vars.delivery.item_1_id=1301;assert(not netcoop_task_handin.prepare('delivery',{},a),'UID check also protects a stale dialogue ID')
-- Migrate a pre-fix saved quest with no UID by exact native restored mapping.
a.vars.delivery={item_1_id=1301,item_1_sec='parcel'};a.vars.parcel=a.vars.delivery
netcoop_task_identity.restore(a,{task_objects={delivery={}}},'1301:1309;')
assert(a.vars.delivery.item_1_id==1309 and a.vars.delivery.item_1_uid=='9007199254740993')
-- A different section, ambiguous mapping or foreign-owned restored object
-- does not manufacture an identity for unprovable legacy progress.
a.vars.delivery={item_1_id=1301,item_1_sec='parcel'};a.vars.parcel=a.vars.delivery
netcoop_task_identity.restore(a,{task_objects={delivery={}}},'1301:1309;1301:1309;')
assert(a.vars.delivery.item_1_uid_required and not netcoop_task_identity.refresh('delivery',a))
a.vars.delivery={item_1_id=1301,item_1_sec='parcel'};a.vars.parcel=a.vars.delivery
server_items[1309].parent_id=2
netcoop_task_identity.restore(a,{task_objects={delivery={}}},'1301:1309;')
assert(a.vars.delivery.item_1_uid_required and not a.vars.delivery.item_1_uid)
server_items[1309].parent_id=a:id()
-- A parcel known by UID but left on a different server stays pending; it
-- never turns into a success/failure because this server recycled its ID.
a.vars.delivery={item_1_id=1301,item_1_sec='parcel',item_1_uid='left_behind'};a.vars.parcel=a.vars.delivery
assert(not netcoop_task_identity.refresh('delivery',a))
""")
assert compat.index('netcoop_task_identity.restore(actor, state, item_ids)') < compat.index('task_manager.load_state(state)')
characters=(root/'src/xrGame/netcoop_characters.inc').read_text(encoding='utf-8')
assert characters.index('const u16 original_id = item->ID;') < characters.index('item->ID = item->ID_Phantom = 0xffff;')
assert 'restore.original_items.push_back(std::make_pair(original_id, spawned->ID))'in characters
print('PASS quest parcel identity across network ID changes: text UID, exact native legacy migration, same-section copy/foreign/ambiguous rejection and pending unresolved original')

lua.execute(r"""
-- Runtime hooks target ordinary giver quests, preserving non-quest effects
-- and scripted tasks without a merchant delivery transaction.
local calls=0;xr_effects.fetch_reward_and_remove=function()calls=calls+1 end
netcoop_task_handin.install();local prior=netcoop_task_handin.enter(nil)
xr_effects.fetch_reward_and_remove(a,objects[27],{'scripted'})
netcoop_task_handin.enter({id='scripted_without_giver'})
xr_effects.fetch_reward_and_remove(a,objects[27],{'scripted'})
assert(calls==2);netcoop_task_handin.enter(prior)
""")
print('PASS non-quest and giver-less scripted item effects retain original behavior')

lua.execute(r"""
-- Rejected authoritative hand-ins inform only the initiating player.
local notices={}
function netcoop_send_to_actor(id,channel,data)notices[#notices+1]={id,channel,data}end
db.actor=a;events.used_npc_id=27;all_items={};server_items={[27]={group_id=65535},[28]={group_id=65535}}
manager=setmetatable({task_info={}},CRandomTask)
local job=CGeneralTask('fetch');job.task_giver_id=27;job.stage=0
manager.task_info.fetch=job;a.vars.fetch_fetch='bandage';a.vars.fetch_fetch_count=2
assert(not manager:set_task_completed('fetch')and notices[#notices][3]=='objective')
job.stage=1;assert(not manager:set_task_completed('fetch')and notices[#notices][3]=='items')
events.used_npc_id=28;assert(not manager:set_task_completed('fetch')and notices[#notices][3]=='giver')
events.used_npc_id=27;make_item(1401,'bandage');make_item(1402,'bandage');fail_transfer=1402
assert(not manager:set_task_completed('fetch')and notices[#notices][3]=='changed')
assert(server_items[1401].parent_id==a:id()and server_items[1402].parent_id==a:id())
for _,row in ipairs(notices)do assert(row[1]==1 and row[2]=='task_handin_refused')end
""")
client=(root/'scripts/netcoop-overlay/client/netcoop_client_compat.script').read_text(encoding='cp1251')
branch=client[client.index('\telseif channel == "task_handin_refused"'):client.index('\telseif channel == "registration"')]
ui=LuaRuntime(unpack_returned_tuples=True)
ui.execute('shown={};function show_text(value)shown[#shown+1]=value end;game={translate_string=function(key)return key end}')
ui.execute('function receive(channel,data)\n'+branch.replace('elseif','if',1)+'\nend\nend')
ui.execute("receive('task_handin_refused','items');assert(#shown==1 and shown[1]=='st_lz_task_handin_items');receive('task_handin_refused','unknown');assert(#shown==1)")
import xml.etree.ElementTree as ET
for side,name in [('client','st_netcoop.xml'),('server','st_netcoop_server.xml')]:
 for language in ('rus','eng'):
  text_file=root/'scripts/netcoop-overlay'/side/'configs/text'/language/name
  entries=ET.fromstring(text_file.read_bytes()).findall('string')
  keys={entry.attrib['id']:entry.findtext('text')for entry in entries}
  assert len(keys)==len(entries),'duplicate translation ID'
  for key in ('objective','items','giver','changed'):
   assert keys['st_lz_task_handin_'+key]
print('PASS hand-in refusal: owner-only reason, actual client message branch and valid CP1251 Russian/English strings without duplicate IDs')
