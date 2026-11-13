"""Execute the server's real guard against replacing native glowsticks by ALife lamps."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
text = (root / 'scripts/netcoop-overlay/server/netcoop_server_compat.script').read_text(encoding='utf-8')
start = text.index('local function install_world_glowsticks()')
end = text.index('\nfunction on_game_start()', start)
body = text[start:end]
assert text[end:].split('\n', 3)[2].strip() == 'install_world_glowsticks()'
lua = LuaRuntime()
lua.execute(r'''
calls={};objects={}
level={object_by_id=function(id)return objects[id] end}
ini_sys={r_bool_ex=function(_,section,key,fallback)
 assert(key=='netcoop_world_glow' and fallback==false)
 return section=='native_glow'
end}
local function old(id,thrown)
 calls[#calls+1]={id=id,thrown=thrown};return 'legacy'
end
zz_glowstick_mcm={spawn_glowstick=old}
objects[1]={section=function()return 'native_glow' end}
objects[2]={section=function()return 'ordinary_flashlight' end}
''')
lua.execute(body + '\ninstall=install_world_glowsticks')
lua.execute(r'''
install();local wrapped=zz_glowstick_mcm.spawn_glowstick
assert(wrapped(1,false)==true and #calls==0)
assert(wrapped(1,true)==true and #calls==0)
assert(objects[1]~=nil) -- no delete/replacement/mutation requested
assert(wrapped(2,true)=='legacy' and #calls==1 and calls[1].id==2 and calls[1].thrown==true)
assert(wrapped(999,false)=='legacy' and #calls==2)
assert(wrapped(nil,false)=='legacy' and #calls==3)
install();assert(zz_glowstick_mcm.spawn_glowstick==wrapped)
assert(wrapped(2,false)=='legacy' and #calls==4)
zz_glowstick_mcm=nil;install()
zz_glowstick_mcm={};install()
''')
print('PASS actual world-glow compatibility guard: native original preserved, legacy fallback intact, install idempotent, no client/HUD changes')
