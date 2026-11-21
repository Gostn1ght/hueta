"""Actual deployed-derived option records and Apply/Cancel handlers, Lua5.1. No game/GPU."""
from pathlib import Path
import re
from lupa.lua51 import LuaRuntime
root=Path(__file__).resolve().parents[1]
s=(root/'scripts/netcoop-overlay/client/ui_options.script').read_text(encoding='utf-8-sig')
lua=LuaRuntime(unpack_returned_tuples=True)
assert lua.eval('function(s) return loadstring(s) ~= nil end')(s),'full options syntax'
records={}
for name in ['resolution','detail_density','detail_radius','detail_height','renderer','ssao']:
 line=next(line.strip().rstrip(',') for line in s.splitlines() if re.match(r'\s*\{ id= "'+name+r'"',line))
 records[name]=lua.execute('return '+line)
for name in ['resolution','detail_density','detail_radius','detail_height']:
 assert records[name]['restart'] is False and records[name]['vid'] is True
assert records['renderer']['restart'] is True and records['ssao']['restart'] is True
begin=s.index('function UIOptions:On_Accept()');end=s.index('function UIOptions:On_Discard()',begin)
handlers=s[begin:end]
lua.execute(r'''
UIOptions={};events={};local opt_temp,opt_backup={},{};local opt_section='video'
function reset_pending(t)opt_temp=t;opt_backup={};events={}end
function print_dbg(...)end
function exec_console_cmd(cmd)events[#events+1]=cmd end
function empty_table(t)for k in pairs(t)do t[k]=nil end end
function Unregister_UI(id)events[#events+1]='unregister' end
level={present=function()return true end}
game={translate_string=function(s)return s end}
function SendScriptCallback(name)events[#events+1]=name end
axr_main={config={w_value=function()end,save=function()events[#events+1]='axr_save'end}}
function context(options)
 local owner={ShowDialog=function()end,Show=function()end,SetMsg=function()end,CloseRoomView=function()events[#events+1]='close_room'end}
 local box={InitMessageBox=function()events[#events+1]='restart_warning'end,ShowDialog=function()end}
 local c={owner=owner,message_box=box,Change_Done=false,Need_Restart=false,Need_VidRestart=false,Save_CFG=false,Keybinds_Shown=false,Save_AXR=false}
 c.GetOption=function(self,id)return options[id]end;c.HideDialog=function()events[#events+1]='hide_options'end
 return setmetatable(c,{__index=UIOptions})
end
'''+handlers)
values={'resolution':'1920x1080','detail_density':.2,'detail_radius':90,'detail_height':1.2,'renderer':'renderer_r4','ssao':'high'}
def check(names,warnings):
 options=lua.table_from({n:records[n] for n in names});pending=lua.table_from({n:values[n] for n in names})
 lua.globals().reset_pending(pending);ctx=lua.globals().context(options);ctx.On_Accept(ctx)
 events=list(lua.globals().events.values())
 assert events.count('vid_restart')==1 and events.count('cfg_save')==1
 assert events.count('restart_warning')==warnings and events.count('on_option_change')==1
 assert events.index('cfg_save')<events.index('vid_restart') and events.index('close_room')<events.index('vid_restart')
 assert not any(x=='quit' or x=='disconnect' or x.startswith('start ') for x in events)
 assert ctx.Need_VidRestart is False and ctx.Need_Restart is False
for name in ['resolution','detail_density','detail_radius','detail_height']:check([name],0)
check(['resolution','detail_density','detail_radius','detail_height'],0)
check(['resolution','renderer'],1);check(['detail_height','ssao'],1)
lua.globals().reset_pending(lua.table());ctx=lua.globals().context(lua.table());ctx.On_Cancel(ctx)
assert 'vid_restart' not in list(lua.globals().events.values())
print('PASS actual Lua options:4 live-reset descriptors, Apply/Cancel/save/callback/one vid_restart, no disconnect/quit, unsupported mixed settings retain warning; no game rendering tested')
