"""Actual GAMMA quest/reward news and netcoop completion callback."""
from pathlib import Path
from lupa.lua51 import LuaRuntime
root=Path(__file__).resolve().parents[1]
lua=LuaRuntime(unpack_returned_tuples=True)
lua.execute(r"""
AC_ID=1;function printf()end
function actor(id)
 local obj={id=id,chat={},pda={},talking=true}
 function obj:is_talking()return self.talking end
 function obj:get_task(task_id,in_progress_only)assert(task_id=='job'and not in_progress_only);return task_object end
 function obj:give_talk_message2(caption,text,icon,template)
  assert(template=='iconed_answer_item');self.chat[#self.chat+1]={caption=caption,text=text,icon=icon}
 end
 function obj:give_game_news(caption,text,icon,delay,duration)
  assert(delay==0 and duration>0);self.pda[#self.pda+1]={caption=caption,text=text,icon=icon}
 end
 return obj
end
first=actor(1);second=actor(2);db={actor=first}
game={translate_string=function(key)return key end}
xr_sound={set_sound_play=function()end}
ui_item={get_sec_name=function(section)return 'name:'..section end}
ini_sys={section_exist=function(_,section)return section=='bandage'end}
function printe()error('unexpected invalid item')end
task_object={get_title=function()return 'job_title'end,get_icon_name=function()return 'quest_icon'end}
""")
lua.execute('news_manager={};setmetatable(news_manager,{__index=_G});local fn=assert(loadstring(...));setfenv(fn,news_manager);fn()',
 (root/'scripts/fixtures/quest-news/news_manager.lua').read_text(encoding='utf-8'))
client=(root/'scripts/netcoop-overlay/client/netcoop_client_compat.script').read_text(encoding='cp1251')
a=client.index('function on_task(task_id, kind)');b=client.index('-- The base-game debug menu',a)
lua.execute(client[a:b])
a=client.index('function on_script_message(channel, data)')
b=client.index('-- Engine (netcoop.cpp) when the task list',a)
lua.execute(client[a:b])
lua.execute(r"""
news_manager.send_task(first,'new',task_object)
assert(#first.chat==1 and first.chat[1].text=='job_title.' and first.chat[1].icon=='quest_icon')
on_task('job','new');assert(#first.chat==1,'acceptance must not duplicate the authoritative GAMMA news')
on_task('job','complete');assert(#first.chat==2 and first.chat[2].text=='job_title.')
news_manager.relocate_money(first,'in',5000)
assert(first.chat[3].text=='5000'and first.chat[3].icon=='ui_inGame2_Dengi_polucheni')
news_manager.relocate_item(first,'in','bandage',2)
assert(first.chat[4].text=='name:bandage x2')
news_manager.send_task(first,'fail',task_object);local before=#first.chat
on_task('job','fail');assert(#first.chat==before)
db.actor=second;AC_ID=2;news_manager.relocate_money(second,'in',7000)
assert(#second.chat==1 and second.chat[1].text=='7000'and #first.chat==before)
second.talking=false;news_manager.send_task(second,'new',task_object);assert(#second.pda==1)
local sounds={}
second.id=function()return 2 end
xr_sound.set_sound_play=function(id,name)sounds[#sounds+1]={id,name}end
on_script_message('task_arrival_sound','')
assert(#sounds==1 and sounds[1][1]==2 and sounds[1][2]=='pda_task')
db.actor=nil;on_task('job','complete')
on_script_message('task_arrival_sound','');assert(#sounds==1)
""")
print('PASS actual GAMMA task/reward news: acceptance, completion, money, item amount, failure, actor separation, normal PDA path and no duplicate acceptance/failure')
