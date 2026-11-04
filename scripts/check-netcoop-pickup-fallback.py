"""Exercise the actual addon wrapper: disabled DotMarks must not swallow MP pickup."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

root=Path(__file__).resolve().parents[1]
source=(root/'scripts/netcoop-overlay/client/z_fdda_pickup_intercept_dotmarks.script').read_bytes().decode('latin-1')
cases=0
for multiplayer in (False,True):
    for disabled in (False,True):
        for redirected in (False,True):
            lua=LuaRuntime()
            lua.execute('''
                calls=0; original={id=1}; redirect={id=2}
                liz_fdda_redone_item_pickup={actor_on_item_before_pickup=function(obj,flags)
                    calls=calls+1; selected=obj; flags.ret_value=false
                end}
                ui_hud_dotmarks={
                    fdda_handles_pickups=function() return true end,
                    killswitch=function(feature) assert(feature=='pickup');return disabled end,
                    item_pickup_intercept=function(obj,flags)
                        if disabled then return nil end
                        if redirected then return redirect end
                        return nil
                    end
                }
                netcoop_enabled=function() return multiplayer end
                flags={ret_value=true}
            ''')
            lua.globals().multiplayer=multiplayer
            lua.globals().disabled=disabled
            lua.globals().redirected=redirected
            lua.execute(source)
            lua.execute('liz_fdda_redone_item_pickup.actor_on_item_before_pickup(original,flags)')
            expected=(not disabled and redirected) or (multiplayer and disabled)
            assert lua.globals().calls==int(expected),(multiplayer,disabled,redirected)
            if expected:
                assert lua.eval('selected.id')==(1 if disabled else 2)
            assert lua.eval('flags.ret_value') is False
            cases+=1
print(f'PASS actual pickup wrapper {cases}: MP disabled-DotMarks fallback, normal target selection and SP unchanged')

# Scanner startup/clock rollback is not an inventory denial. Execute both real
# monkeypatch variants and keep deliberate denials once the scanner is ready.
for addon in ('liz_fdda_redone_item_pickup','take_item_anim'):
    for rebinding in (False,True):
        lua=LuaRuntime()
        lua.execute("""
            calls=0;intercepts=0
            ui_hud_dotmarks={fdda_handles_pickups=function()return true end,
              killswitch=function()return false end,
              netcoop_pickup_rebinding=function()return rebinding end,
              item_pickup_intercept=function(obj,flags)intercepts=intercepts+1;flags.ret_value=false end}
            netcoop_enabled=function()return true end
            flags={ret_value=false}
        """)
        lua.globals().rebinding=rebinding
        lua.execute(addon+'={actor_on_item_before_pickup=function()calls=calls+1 end}')
        lua.execute(source)
        lua.execute(addon+'.actor_on_item_before_pickup({},flags)')
        assert lua.globals().calls==0
        assert lua.eval('flags.ret_value') is rebinding
        assert lua.globals().intercepts==int(not rebinding)
print('PASS scanner rebinding: both FDDA variants defer to native checks; ready-scanner denials preserved')
