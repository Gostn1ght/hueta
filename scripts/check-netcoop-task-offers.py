"""Actual GAMMA task generator and dedicated-server config-cache initialization."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root=Path(__file__).resolve().parents[1]
source=(root/'scripts/netcoop-overlay/server/netcoop_server_compat.script').read_text(encoding='cp1251')
lua=LuaRuntime()
lua.execute('''
function printf() end
available_tasks={};CFG_CACHE={};init_count=0
sections={trader_task_1={job_descr='bring ammunition'},trader_task_2={job_descr='locked'},other_task_1={job_descr='other trader'}}
task_info={};db={storage={[27]={}},actor={}}
task_manager={get_task_manager=function() return {task_info=task_info} end,task_ini={
 r_string_ex=function(_,section,key) return sections[section] and sections[section][key] end,
 r_float_ex=function() return nil end,
 section_for_each=function(_,fn) init_count=init_count+1 for k in pairs(sections) do fn(k) end end}}
function empty_table(t) for k in pairs(t) do t[k]=nil end end
function starts_with(s,p) return s:sub(1,#p)==p end
xr_conditions={has_completed_task_prerequisites=function(_,_,p) return p[1]~='trader_task_2' end}
npc={id=function() return 27 end,section=function() return 'trader' end}
''')
lua.execute((root/'scripts/fixtures/task-offers/generate_cache.lua').read_text(encoding='utf8'))
lua.execute((root/'scripts/fixtures/task-offers/generate_available_tasks.lua').read_text(encoding='utf8'))
lua.execute('axr_task_manager={CFG_CACHE=CFG_CACHE,generate_cache=generate_cache}')
start=source.index('local task_cache_ready = false')
lua.execute(source[start:source.index('\nlocal game_loaded',start)])
lua.execute('''
generate_available_tasks(npc,false);assert(#available_tasks[27]==0,'reproduce empty dedicated cache before SP load_state')
ensure_task_cache();assert(init_count==1)
generate_available_tasks(npc,false)
assert(#available_tasks[27]==1 and available_tasks[27][1]=='trader_task_1','ordinary job offered, locked prerequisites still enforced')
ensure_task_cache();ensure_task_cache();assert(init_count==1,'no cache rebuild per dialogue/frame')
task_info.trader_task_1={status='in_progress'}
generate_available_tasks(npc,false);assert(#available_tasks[27]==0,'already taken task remains unavailable to this player')
task_info={};generate_available_tasks(npc,false);assert(#available_tasks[27]==1,'another player uses their own task history')
''')
# The first dialogue must initialize before any condition/action examines offers.
start=source.index('function talk_speaker(npc_id)')
speaker=source[start:source.index('\n-- Remote dialogue',start)]
assert 'if npc_id ~= 65535 then ensure_task_cache() end' in speaker
assert 'ensure_task_cache()' in source[source.index('local function server_game_load()'):source.index('-- World systems')]
print('PASS actual GAMMA task offers: cold dedicated cache, ordinary offers, prerequisites, taken tasks, separate player history and idempotent startup')

# Run the same real generator in its production module environment, together
# with the actual per-character context. Include a fresh Lua VM restart.
context=(root/'scripts/netcoop-overlay/server/netcoop_task_context.script').read_text(encoding='utf8')
generator=(root/'scripts/fixtures/task-offers/generate_available_tasks.lua').read_text(encoding='utf8')
def boot():
    vm=LuaRuntime()
    vm.execute('''
function starts_with(s,p)return s:sub(1,#p)==p end
function empty_table(t)for k in pairs(t)do t[k]=nil end end
function parse_list()return {stalker=true} end
function character_community()return 'stalker' end
db={storage={[1]={pstor={}},[2]={pstor={}},[27]={dyn_quest_rand='nil'}}}
a={id=function()return 1 end};b={id=function()return 2 end}
npc={id=function()return 27 end,name=function()return 'sim_stalker_stable_name' end,section=function()return 'stalker' end}
history={};task_manager={get_task_manager=function()return {task_info=history}end,
 task_ini={r_string_ex=function(_,id,k)
 if k=='on_complete' then return id=='fetch' and '%=fetch_reward_and_remove(job)%' or '%=spawn_squad(story)%' end end}}
xr_conditions={has_completed_task_prerequisites=function(_,_,p)return p[1]~='simulation_task_locked' end}
axr_task_manager={CFG_CACHE={simulation_task_a={},simulation_task_b={},simulation_task_locked={}},available_tasks={}}
setmetatable(axr_task_manager,{__index=_G})
function load_module(text,env)local f=assert(loadstring(text));setfenv(f,env);f()end
''')
    vm.execute('load_module(...,axr_task_manager)',generator)
    vm.execute('netcoop_task_context={};setmetatable(netcoop_task_context,{__index=_G});load_module(...,netcoop_task_context)',context)
    return vm
vm=boot()
vm.execute('''
local c,t=netcoop_task_context,axr_task_manager
db.actor=a;c.bind_actor(a)
math.random=function(n)return 1 end -- SP's first roll says "no work".
t.generate_available_tasks(npc,true)
assert(#t.available_tasks[27]==1 and t.available_tasks[27][1]=='simulation_task_a')
assert(db.storage[27].dyn_quest_rand=='nil','restore the NPC global after every call')
history.simulation_task_a={status='in_progress'}
t.generate_available_tasks(npc,true)
assert(t.available_tasks[27][1]=='simulation_task_b','active old choice cannot hide eligible next job')
local a_offers=t.available_tasks
db.actor=b;history={};c.bind_actor(b)
assert(not t.available_tasks[27],'no stale A offer in B dialogue')
t.generate_available_tasks(npc,true)
assert(t.available_tasks[27][1]=='simulation_task_a')
db.actor=a;c.bind_actor(a)
assert(t.available_tasks==a_offers and t.available_tasks[27][1]=='simulation_task_b')
assert(c.personal_task('fetch') and not c.personal_task('story'),'only ordinary fetch templates allow independent concurrent jobs')
c.capture(a)
saved_choice=db.storage[1].pstor.netcoop_quest_context.dyn_quests[npc:name()]
-- Even a prerequisite exception restores the speaker NPC's shared state.
local check=xr_conditions.has_completed_task_prerequisites
xr_conditions.has_completed_task_prerequisites=function()error('broken condition')end
assert(not pcall(t.generate_available_tasks,npc,true))
assert(db.storage[27].dyn_quest_rand=='nil')
xr_conditions.has_completed_task_prerequisites=check
''')
choice=vm.globals().saved_choice
start=source.index('local function install_player_tasks()')
end=source.index('\n-- Dialogue actions',start)
vm.execute('''
db.actor=a;give_calls=0
task_manager.CRandomTask={give_task=function()give_calls=give_calls+1 end}
function netcoop_task_taken()return true end
function printf()end
function a:give_game_news()end
game={translate_string=function(id)return id end}
''')
vm.execute('local player_tasks={}\n'+source[start:end]+'''\ninstall_player_tasks()
task_manager.CRandomTask.give_task({},'fetch',27)
assert(give_calls==1,'another player may have the same personal fetch template')
task_manager.CRandomTask.give_task({},'story',27)
assert(give_calls==1,'an exclusive world/story task cannot be duplicated')
''')
restarted=boot()
restarted.globals().saved_choice=choice
restarted.execute('''
-- A restart changed network IDs; persistent NPC name still identifies offers.
db.storage[88]=db.storage[27];db.storage[27]=nil;npc.id=function()return 88 end
db.storage[1].pstor.netcoop_quest_context={dyn_quests={[npc:name()]=saved_choice}}
db.actor=a;netcoop_task_context.bind_actor(a)
math.random=function()error('must not reroll a valid saved offer')end
axr_task_manager.generate_available_tasks(npc,true)
assert(axr_task_manager.available_tasks[88][1]==saved_choice)
''')
print('PASS personal simulation offers: actual generator, shared nil recovery, prerequisite/active-job filtering, A/B isolation, exception unwind, saved choice in a fresh VM with new network IDs')
