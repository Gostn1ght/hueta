"""Actual compact multiplayer weather window: authority, commands, close/return."""
from pathlib import Path
from lupa.lua51 import LuaRuntime
lua=LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
role=1;commands={};owner={hidden=false}
function owner:HideDialog() self.hidden=true end
function owner:ShowDialog() self.hidden=false end
function netcoop_role() return role end
function netcoop_command(c) commands[#commands+1]=c end
function class(name) return function(base)
 local c={};_G[name]=c
 setmetatable(c,{__index=base,__call=function(_,...) local o=setmetatable({}, {__index=c});c.__init(o,...);return o end})
end end
function super() end
CUIScriptWnd={SetWndRect=function()end,SetAutoDelete=function()end,Register=function()end,
 AddCallback=function(self,id,event,fn,target) self.callbacks=self.callbacks or {};self.callbacks[id]=function() return fn(target) end end,
 ShowDialog=function(self)self.shown=true end,HideDialog=function(self)self.shown=false end,OnKeyboard=function()return false end}
function Frect() return {set=function(self)return self end} end
function vector2() return {set=function(self)return self end} end
local function widget()return {SetText=function()end,SetWndPos=function()end,TextControl=function(self)return self end}end
function CScriptXmlInit()return {ParseFile=function()end,InitStatic=widget,InitTextWnd=widget,Init3tButton=widget}end
game={translate_string=function(s)return s end}
ui_events={BUTTON_CLICKED=1,WINDOW_KEY_PRESSED=2};DIK_keys={DIK_ESCAPE=27}
''')
source=(Path(__file__).parent/'netcoop-overlay/client/ui_debug_weather.script').read_text(encoding='utf-8-sig')
lua.execute(source)
lua.execute(r'''
start(owner);assert(not GUI and not owner.hidden,'ordinary player cannot open controls')
role=2;start(owner);assert(GUI and GUI.shown and owner.hidden)
local window=GUI
for i=1,12 do window.callbacks['weather_'..i]() end
assert(#commands==12 and commands[1]=='weather clear' and commands[6]=='weather_edit pause 0')
assert(commands[7]=='time 1' and commands[9]=='timescale 1' and commands[12]=='psi start')
role=1;window.callbacks.weather_1();assert(#commands==12,'revoked role cannot issue an edit')
assert(window:OnKeyboard(27,2) and not GUI and not owner.hidden and not window.shown)
''')
print('PASS actual weather window: server commands only, admin gate, revoked role, bounded actions and Escape returns to owner')
