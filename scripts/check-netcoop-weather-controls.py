"""Actual restored GAMMA editor: live parameter types, pause and presets."""
from pathlib import Path
from lupa.lua51 import LuaRuntime
source=(Path(__file__).parent/'netcoop-overlay/client/ui_debug_weather.script').read_text(encoding='utf-8-sig')
lua=LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
role=1;applied={};paused=false
function netcoop_pure_client()return true end
function netcoop_role()return role end
function GetARGB(...)return 0 end
DIK_keys=setmetatable({},{__index=function(t,k)rawset(t,k,k);return k end})
function class(name)return function(base)_G[name]={};setmetatable(_G[name],{__index=base})end end
function super()end
CUIScriptWnd={};ui_events={}
function printf(...)end
function Register_UI(...)end
weather={is_paused=function()return paused end,pause=function(on)paused=on;applied[#applied+1]={'pause',on}end,
 set_value_numric=function(p,v)applied[#applied+1]={'num',p,v}end,
 set_value_vector=function(p,x,y,z,w)applied[#applied+1]={'vec',p,x,y,z,w}end,
 set_value_string=function(p,v)applied[#applied+1]={'str',p,v}end}
level={set_weather=function(n,now)applied[#applied+1]={'weather',n,now}end}
''')
lua.execute(source)
lua.execute(r'''
start();assert(GUI==nil,'ordinary online player cannot open editor')
role=2
local shown=false
GUI={IsShown=function()return shown end,ShowDialog=function()shown=true end,Refresh=function()end}
local owner={IsShown=function()return false end}
start(owner);assert(shown)
local cell={SetText=function()end}
local e=setmetatable({idx_p={rain_density=1,sky_color=2,clouds_color=3,sky_texture=4},
 idx_g={{1},{1,2,3},{1,2,3,4},{1,2}},par={cell,cell,cell,cell},
 Reset_FolderList=function()end,Print=function()error('unexpected invalid parameter')end},{__index=WeatherEditor})
e:Apply('rain_density',1,{rain_density={.4}})
e:Apply('sky_color',2,{sky_color={.1,.2,.3}})
e:Apply('clouds_color',3,{clouds_color={.1,.2,.3,.4}})
e:Apply('sky_texture',4,{sky_texture={'clear','01'}})
assert(applied[1][1]=='num' and applied[1][3]==.4)
assert(applied[2][1]=='vec' and applied[2][5]==.3)
assert(applied[3][6]==.4 and applied[4][3]=='sky\\clear01')
e:PauseEngine(true);e:PauseEngine(true);assert(#applied==5 and paused)
e:PauseEngine(false);assert(#applied==6 and not paused)
e.list_weather={CurrentID=function()return 1 end};e.weather_files={'w_rain2'}
e.Refresh=function()end;e.MSG=function()end;e:On_Weather()
assert(applied[7][1]=='weather' and applied[7][2]=='w_rain2' and applied[7][3]==true)
''')
for method in ('InitControls','On_Time','On_Param','Viewer_Update','OnBTN_Copy','OnBTN_Paste','OnKeyboard'):
    assert 'function WeatherEditor:'+method+'(' in source
print('PASS restored full weather editor: controls/viewer, typed values, preset, pause idempotency, online role gate')
