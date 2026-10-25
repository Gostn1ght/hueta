"""Run the actual account/character menu in Lua 5.1 with UI/transport stubs.
Requires lupa; does not validate native transport or visual rendering.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from lupa.lua51 import LuaRuntime
root=Path(__file__).resolve().parents[1]
temporary = TemporaryDirectory(prefix='netcoop-menu-')
cache = Path(temporary.name)
(cache/'logs').mkdir()
lua=LuaRuntime(unpack_returned_tuples=True)
lua.globals().test_path=cache.as_posix()+'/'
lua.execute(r'''
state,role,account,present=0,0,'',false
commands,characters,previews,callbacks,controls={},{},{},{},{}
local Widget={}
function Widget:SetText(v) self.text=v end
function Widget:GetText() return self.text or '' end
function Widget:TextControl() return self end
function Widget:Show(v) self.shown=v; self.enabled=v end
function Widget:IsShown() return self.shown or false end
function Widget:Enable(v) self.enabled=v end
function Widget:CaptureFocus() end
function Widget:SetWndRect() end
function Widget:SetWndPos(v) self.position=v end
function Widget:GetWndPos() return self.position or {x=0,y=0} end
function Widget:SetWndSize() end
function Widget:SetAutoDelete() end
function Widget:HideDialog() self.shown=false end
function Widget:ShowDialog() self.shown=true end
function Widget:Register() end
function Widget:AddCallback(id,event,fn,selfref) callbacks[id]=function() return fn(selfref) end end
function Widget:Clear() self.rows={} end
function Widget:AddWindow(w) self.rows=self.rows or {}; self.rows[#self.rows+1]=w end
function Widget:OnKeyboard() return false end
function Widget:Update() end
function Widget:AttachChild() end
function Widget:InitTexture() end
function Widget:SetTextureRect() end
function Widget:SetStretchTexture() end
function Widget:SetFont() end
function Widget:SetTextColor() end
function Widget:InitMessageBox(template) self.template=template end
local function widget(id) local w=setmetatable({shown=true}, {__index=Widget}); if id then controls[id]=w end; return w end
CUIScriptWnd=Widget
function class(name)
 _G[name]={}
 return function(base)
  setmetatable(_G[name], {__index=base,__call=function(c,...)
   local obj=setmetatable({}, {__index=c}); obj:__init(...); last_window=obj; return obj
  end})
 end
end
function super() end
function Frect() return {set=function(s) return s end} end
function vector2() return {set=function(s,x,y) s.x=x;s.y=y;return s end} end
function CUIStatic() return widget() end
function CScriptXmlInit() return {ParseFile=function() end,InitStatic=function(s,id) return widget(id) end,
 InitEditBox=function(s,id) return widget(id) end,Init3tButton=function(s,id) return widget(id) end,
 InitScrollView=function(s,id) return widget(id) end} end
function getFS() return {update_path=function(s,alias,name) return test_path..name end} end
function netcoop_account() return account end
function netcoop_account_state() return state end
function netcoop_role() return role end
function netcoop_login(login,pass,register) account=login; return true end
auth_requests={}
function netcoop_frontend_auth(options) auth_requests[#auth_requests+1]=options; return true end
function netcoop_character(slot,name,faction,economy,loadout) characters[#characters+1]={slot=slot,name=name,loadout=loadout}; return true end
room_model=false;room_presented=false
function netcoop_preview_clear() room_model=false;room_presented=false end
function netcoop_preview_visible() return room_model and room_presented end
function netcoop_preview_focus(object) camera_target=object;camera_done=false end
function netcoop_preview_ready() return camera_done~=false end
function finish_camera() camera_done=true;if room_model then room_presented=true end;last_window:Update() end
function netcoop_preview_point(object) return {x=300,y=400} end
function netcoop_preview_weapon(section) last_weapon=section;return true end
function CUIMessageBoxEx() return CUIStatic() end
cursor={x=0,y=0}; pick_result=-1; last_hover=-1; clicks_played=0
function GetCursorPosition() return {x=cursor.x,y=cursor.y} end
function netcoop_preview_pick(x,y) return pick_result end
function netcoop_preview_hover(object) last_hover=object end
now=0; music_started=0; music_stopped=0; music_sounds={}
function device() return {time_continual=function() return now end} end
sound_object=setmetatable({s2d=1},{__call=function(_,path)
 local sound={path=path,active=false,volume=1}
 function sound:play()
  self.active=true
  if self.path=='interface\\inv_button' then clicks_played=clicks_played+1
  else music_started=music_started+1;music_sounds[#music_sounds+1]=self end
 end
 function sound:stop() self.active=false;music_stopped=music_stopped+1 end
 function sound:playing() return self.active end
 return sound
end})
function netcoop_preview_model(model,pose) room_model=true;previews[#previews+1]={model=model,pose=pose}; return true end
function netcoop_rp_list() return 'bar_1=bar;hands_pockets=pockets;sit_1=sit1;sit_2=sit2;sit_3=sit3;hands_behind=behind;sleep=sleep;' end
function exec_console_cmd(cmd) commands[#commands+1]=cmd end
function printf() end
game={translate_string=function(s) return s end}
ini_sys={section_exist=function() return false end}
level={present=function() return present end}
ui_events={BUTTON_CLICKED=1,WINDOW_KEY_PRESSED=2,MESSAGE_BOX_QUIT_WIN_CLICKED=3,WINDOW_KEY_RELEASED=4}
DIK_keys={DIK_ESCAPE=1,DIK_RETURN=28,DIK_NUMPADENTER=156,DIK_LEFT=203,DIK_RIGHT=205,DIK_UP=200,DIK_DOWN=208,DIK_TAB=15,MOUSE_1=337}
key_bindings={kINVENTORY=9}
function bind_to_dik(action,index) assert(type(index)=='number','native binding needs both arguments'); return index==0 and 23 or 24 end
settings_created=0
function Register_UI(id) assert(id=='UIOptions') end
ui_options={UIOptions=function()
 settings_created=settings_created+1
 return setmetatable({background=widget()}, {__index=Widget})
end}
CUIMMShniaga={epi_main=0,epi_new_game=1}
''')
radio_root = root/'scripts/netcoop-overlay/client'
lua.execute("netcoop_menu_stations={}; netcoop_menu_radio={}")
lua.execute("local f=assert(loadstring(...)); setfenv(f,netcoop_menu_stations); f()", (radio_root/'netcoop_menu_stations.script').read_text())
lua.execute("setmetatable(netcoop_menu_radio,{__index=_G}); local f=assert(loadstring(...)); setfenv(f,netcoop_menu_radio); f()", (radio_root/'netcoop_menu_radio.script').read_text())
menu_source = Path(sys.argv[1]) if len(sys.argv) > 1 else root/'scripts/netcoop-overlay/client/netcoop_login_ui.script'
lua.execute(menu_source.read_text(encoding='cp1251'))
lua.execute("assert(rawget(netcoop_login_wnd, 'Show') == nil, 'native Show must stay inherited')")
lua.execute(r'''
local menu={HideDialog=function(s) s.hidden=true end,Show=function() end,ShowDialog=function() end}
local approved_menu={}; state=2
assert(frontend_update(approved_menu)==false)
state=0
assert(frontend_update(menu)==true)
assert(not controls.input_code.shown and not controls.input_code.enabled, 'legacy account form must not show a verification-code overlay')
controls.input_login:SetText('tester_pending'); controls.input_pass:SetText('')
callbacks.btn_reg(); assert(#characters==0 and #commands==0)
controls.input_pass:SetText('test-password')
callbacks.btn_reg(); assert(characters[#characters].slot==0)
assert(#commands==0 and auth_requests[#auth_requests]=='127.0.0.1/name=tester_pending/port=1267')
assert(frontend_update(menu)==false)
local requests=#auth_requests; callbacks.btn_enter(); assert(#auth_requests==requests)
state=1; on_auth_result(false,0,'Registration pending administrator approval')
last_window:Update()
assert(not controls.btn_reg.shown and controls.input_login.enabled==false)
local n=#characters; callbacks.btn_reg(); assert(#characters==n)
callbacks.btn_enter(); assert(characters[#characters].slot==0)
state=2; cache_characters('Alpha|Beta|||'); cache_previews('actors\\novice.ogf|stalker|\nactors\\armor.ogf|dolg|\n')
on_auth_result(true,1,'Account verified'); last_window:Update()
assert(#commands==0)
assert(controls.name.text=='Alpha' and previews[#previews].pose==-2)
finish_camera()
assert(callbacks.room_next~=nil and callbacks.room_previous~=nil and not controls.details_panel.shown, 'camera arrows and hidden character list')
assert(last_window:CharacterLimit()==1 and not controls.slot2.shown and not controls.slot10.shown)
local n=#characters; last_window:SelectCharacter(2); assert(#characters==n)
local previous=last_window.mode; last_window:ShowProfile(2); assert(last_window.mode==previous)
assert(callbacks.preview_pose_1==nil and callbacks.char_poses==nil)
role=2; cache_characters('Alpha|Beta||||||||');last_window:ShowCharacters()
assert(last_window:CharacterLimit()==10 and controls.slot10.shown)
callbacks.char_slot2();assert(controls.name.text=='Beta')
callbacks.char_slot1();assert(controls.name.text=='Alpha')
callbacks.char_slot10(); assert(controls.info.text:find('10 / 10',1,true))
callbacks.char_slot1(); last_window:ActivateObject(0); camera_done=true;last_window:Update(); callbacks.server_connect()
assert(characters[#characters].slot==1 and characters[#characters].name=='Alpha')
assert(can_mcm()==true);role=0;assert(can_mcm()==false)
''')
print('Actual menu Lua: first screen, saved-account bypass, empty-password rejection, account verification without world-start commands, pending account lock, one/ten character allowance, admin slot 10 and seated 3D preview PASS')

lua.execute(r'''
commands,characters,cloud_requests,drafts={},{},{},{}
cloud_state,cloud_account=0,'cloud_user'
function netcoop_firebase_state() return cloud_state end
function netcoop_firebase_account() return cloud_account end
function netcoop_firebase_email() return 'user@example.invalid' end
function netcoop_firebase_login_email() return cloud_state~=0 and 'original@example.invalid' or '' end
logouts=0
function netcoop_firebase_logout() logouts=logouts+1; cloud_state=0; return true end
cloud_identity='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
function netcoop_firebase_identity() return cloud_identity end
function netcoop_firebase_request(action,email,password,username)
 cloud_requests[#cloud_requests+1]={action=action,email=email,password=password,username=username,code=action=='verify' and password or nil}; return true
end
draft_stores={}; draft_scope='127.0.0.1:5446'; draft_stores[draft_scope]=drafts
draft_owners={[cloud_identity]=draft_stores}; current_draft_owner=cloud_identity
function netcoop_draft_server(address)
 if current_draft_owner~=cloud_identity then
  draft_stores=draft_owners[cloud_identity] or {};draft_owners[cloud_identity]=draft_stores;current_draft_owner=cloud_identity
 end
 draft_scope=address;draft_stores[address]=draft_stores[address] or {}; drafts=draft_stores[address];return true
end
function netcoop_draft(slot,field) return drafts[slot] and drafts[slot][field] or '' end
function netcoop_save_draft(slot,name,description,history,faction,economy,loadout)
 drafts[slot]={name=name,description=description,history=history,faction=faction,economy=tostring(economy),loadout=loadout}; return true
end
function netcoop_character_profile(description,history) profile={description,history}; return true end
ini_sys={section_exist=function(s,section) return section=='medkit' or section=='wpn_ak74' end}
function SYS_GetParam(kind,section,key,fallback)
 if key=='visual' and section=='wpn_ak74' then return 'rifle.ogf' end
 if key=='slot' and section=='wpn_ak74' then return 2 end
 if key=='inv_grid_width' then return section=='wpn_ak74' and 5 or 1 end
 if key=='inv_grid_height' then return section=='wpn_ak74' and 2 or 1 end
 return fallback
end
function GetFontLetterica16Russian() return {} end
function CUIMessageBoxEx() return CUIStatic() end
function GetARGB() return 0 end
utils_xml={get_icons_texture=function() return 'icons' end,get_item_axis=function() return 0,0,50,50 end}
function netcoop_preview_weapon(section) last_weapon=section;return true end
function netcoop_preview_point(index) return {x=300+index*200,y=400+index*80} end
camera_done=true; camera_target=-1
function netcoop_preview_focus(object) camera_target=object;camera_done=false end
function netcoop_preview_ready() return camera_done end
function finish_camera() camera_done=true;if room_model then room_presented=true end;last_window:Update() end
''')
lua.execute(menu_source.read_text(encoding='cp1251'))
lua.execute(r'''
local menu={HideDialog=function() end,Show=function() end,ShowDialog=function() end}
assert(frontend_update(menu)==true)
local account_music=music_started
last_window:Update();netcoop_menu_radio.track(1);netcoop_menu_radio.toggle();netcoop_menu_radio.toggle()
assert(music_started==account_music, 'account screen must remain silent, including direct radio controls')
-- A new player starts on registration: email, call sign, password and its repeat.
assert(last_window.screen=='register' and controls.input_login.shown and controls.input_login.enabled and controls.input_pass2.shown)
assert(not controls.input_code.shown and not controls.input_code.enabled, 'hidden verification code must not steal account-name input')
assert(not controls.input_addr.shown and not controls.input_addr.enabled)
callbacks.tab_login();assert(last_window.screen=='login' and not controls.input_login.shown and not controls.input_pass2.shown)
assert(controls.input_email.enabled and controls.input_pass.enabled and controls.btn_reset.shown and not controls.btn_reg.shown)
callbacks.tab_register();assert(last_window.screen=='register' and controls.input_login.enabled and #last_window.fields==4)
controls.input_email:SetText('user@example.invalid'); controls.input_login:SetText('cloud_user')
controls.input_pass:SetText('tiny'); callbacks.btn_reg()
assert(#cloud_requests==0 and last_window.msg.text=='st_netcoop_cloud_password_invalid' and last_window.focus_index==3)
controls.input_pass:SetText('test-password'); controls.input_pass2:SetText('typo-password'); callbacks.btn_reg()
assert(#cloud_requests==0 and last_window.msg.text=='st_netcoop_passwords_mismatch' and last_window.focus_index==4)
controls.input_pass2:SetText('test-password'); callbacks.btn_reg()
assert(cloud_requests[1].action=='register' and cloud_requests[1].username=='cloud_user' and #commands==0 and #characters==0)
assert(controls.input_pass.text=='test-password', 'typed password stays while the request runs')
callbacks.btn_reg(); assert(#cloud_requests==1)
assert(not controls.tab_register.enabled and not controls.tab_login.enabled and not controls.input_email.enabled)
callbacks.tab_login();assert(last_window.form_mode=='register', 'form tabs must not interrupt an account request')
-- An already registered email moves to sign-in with the same email and password.
on_cloud_result(false,'EMAIL_EXISTS','',false); last_window:Update()
assert(last_window.screen=='login' and last_window.msg.text=='st_netcoop_email_exists' and last_window.focus_index==2)
assert(controls.input_email.text=='user@example.invalid' and controls.input_pass.text=='test-password' and controls.input_email.enabled)
callbacks.tab_register(); callbacks.btn_reg(); assert(cloud_requests[2].action=='register')
cloud_state=1; on_cloud_result(true,'','cloud_user',false); last_window:Update()
assert(last_window.screen=='verify' and last_window.title.text=='st_netcoop_verify_title')
assert(not controls.input_pass.shown and not controls.input_email.shown and not controls.input_code.shown and not controls.tab_login.shown)
assert(controls.input_pass.text=='' and controls.input_pass2.text=='', 'passwords cleared once the account exists')
assert(controls.btn_enter.text=='st_netcoop_wrong_email' and controls.btn_reset.text=='st_netcoop_sign_out')
assert(last_window.msg.text:find('st_netcoop_verify_sent',1,true))
-- The registration email was just sent: resend waits with a countdown.
assert(not controls.btn_reg.enabled and controls.btn_reg.text=='st_netcoop_resend_wait')
callbacks.btn_reg(); assert(#cloud_requests==2)
-- Verification is automatic and leaves correction/sign-out usable while it polls.
now=4999;last_window:Update();assert(#cloud_requests==2)
now=5000;last_window:Update();assert(cloud_requests[3].action=='verify' and cloud_requests[3].code=='')
assert(controls.btn_enter.enabled and controls.btn_reset.enabled)
local before=#cloud_requests;last_window:Update();assert(#cloud_requests==before,'one polling request at a time')
on_cloud_result(false,'EMAIL_NOT_VERIFIED','cloud_user',false)
now=30000;last_window:Update()
assert(last_window.verify_poll and controls.btn_reg.enabled and controls.btn_reg.text=='st_netcoop_resend_email')
before=#cloud_requests;callbacks.btn_reg();assert(#cloud_requests==before,'resend waits for the current poll')
on_cloud_result(false,'EMAIL_NOT_VERIFIED','cloud_user',false)
assert(cloud_requests[#cloud_requests].action=='resend','queued resend follows the poll')
on_cloud_result(true,'','cloud_user',false);last_window:Update()
assert(last_window.screen=='verify' and last_window.msg.text:find('st_netcoop_resend_done',1,true) and not controls.btn_reg.enabled)
-- A mistyped address is changed on the same account (no second account).
callbacks.btn_enter()
assert(last_window.screen=='change_email' and controls.input_email.enabled and controls.input_pass.shown and not controls.input_login.shown)
assert(controls.input_email.text=='user@example.invalid' and controls.btn_enter.text=='st_netcoop_cancel')
callbacks.btn_reg();assert(last_window.msg.text=='st_netcoop_change_email_same')
controls.input_email:SetText('fixed@example.invalid');callbacks.btn_reg();assert(last_window.msg.text=='st_netcoop_cloud_password_invalid')
controls.input_pass:SetText('test-password');before=#cloud_requests;callbacks.btn_reg()
local change=cloud_requests[before+1]
assert(change.action=='change_email' and change.email=='fixed@example.invalid' and change.password=='test-password')
now=40000;last_window:Update();assert(#cloud_requests==before+1,'no verification poll while the address is edited')
on_cloud_result(false,'INVALID_LOGIN_CREDENTIALS','cloud_user',false);last_window:Update()
assert(last_window.screen=='change_email' and last_window.msg.text=='st_netcoop_change_email_password_invalid')
assert(controls.input_email.text=='fixed@example.invalid' and controls.input_pass.text=='test-password' and last_window.focus_index==2)
callbacks.btn_reg();on_cloud_result(true,'','cloud_user',false);last_window:Update()
assert(last_window.screen=='verify' and last_window.msg.text:find('st_netcoop_change_email_sent',1,true))
-- Esc while changing the address cancels the change instead of quitting.
callbacks.btn_enter();last_window:OnKeyboard(DIK_keys.DIK_ESCAPE,ui_events.WINDOW_KEY_PRESSED)
assert(last_window.screen=='verify' and not (last_window.quit_box and last_window.quit_box.shown))
-- Sign out of the unconfirmed account, then sign in to another one.
if last_window.verify_poll then on_cloud_result(false,'EMAIL_NOT_VERIFIED','cloud_user',false) end
callbacks.btn_reset();assert(logouts==1 and cloud_state==0 and last_window.screen=='login' and last_window.msg.text=='st_netcoop_signed_out')
assert(controls.input_email.text=='original@example.invalid' and last_window.focus_index==2)
controls.input_email:SetText('bad@@example.invalid');callbacks.btn_enter()
assert(last_window.msg.text=='st_netcoop_email_invalid' and last_window.focus_index==1)
controls.input_email:SetText('correct@example.invalid');controls.input_pass:SetText('test-password');callbacks.btn_enter()
assert(cloud_requests[#cloud_requests].action=='login' and cloud_requests[#cloud_requests].email=='correct@example.invalid')
on_cloud_result(false,'INVALID_LOGIN_CREDENTIALS','',false);last_window:Update()
assert(last_window.screen=='login' and controls.input_email.enabled and last_window.msg.text=='st_netcoop_bad_credentials')
assert(controls.input_email.text=='correct@example.invalid' and controls.input_pass.text=='test-password' and last_window.focus_index==2)
callbacks.btn_enter();assert(cloud_requests[#cloud_requests].action=='login')
cloud_state=1;on_cloud_result(true,'','cloud_user',false);last_window:Update()
assert(last_window.screen=='verify' and not last_window.force_login and not controls.input_email.shown)
now=now+60000;last_window:Update();assert(cloud_requests[#cloud_requests].action=='verify')
cloud_state=2;on_cloud_result(true,'','cloud_user',true);last_window:Update()
assert(last_window.mode=='profile' and #commands==0)
last_window:Update();assert(music_started==account_music, 'profile creation must remain silent')
controls.input_name:SetText('Loner One'); controls.input_description:SetText('Brown jacket')
controls.input_history:SetText('A separate character history')
canonical_loads, injected_loads=0,0
new_game_loadout_injector_mcm={_LoadLoadout=function(menu) canonical_loads=canonical_loads+1;menu.canonical=true end}
local picker={LoadLoadout=function(menu) injected_loads=injected_loads+1;menu.canonical=false end}
ui_mm_faction_select={UINewGame=setmetatable(picker,{__call=function(class,owner)
 local hidden={Show=function() end}
 last_creator={owner=owner,actions={},SetAutoDelete=function() end,HideDialog=function(s) s.shown=false end,ShowDialog=function(s) s.shown=true end,Show=function(s,v) s.shown=v end,
  AddCallback=function(s,id,event,fn,selfref) s.actions[id]=function() return fn(selfref) end end,
  character_name={SetText=function(s,v) s.name=v end,GetText=function(s) return s.name end},scroll_options=hidden,list_map=hidden}
 last_creator.actions.btn_start=function() error('Legacy start callback must be replaced') end
 class.LoadLoadout(last_creator,false)
 setmetatable(last_creator,{__index=class})
 return last_creator
end})}
callbacks.profile_next(); assert(last_creator.character_name.name=='Loner One' and last_creator.canonical and canonical_loads==1)
assert(#commands==0 and #characters==0)
last_creator.access=true; last_creator.points_left=10; last_creator.selected_economy='st_econ_1'; last_creator.selected_faction='stalker'
last_creator.CC={inventory={cell={{section='medkit',IsShown=function() return true end,CountChilds=function() return 2 end}}}}
netcoop_login_ui={finish_creation=finish_creation}
local original_save=netcoop_save_draft
netcoop_save_draft=function() return false end
last_creator.actions.btn_start()
assert(last_creator.shown and last_window.mode=='profile' and last_creator.netcoop_status.text=='st_netcoop_loadout_save_failed')
assert(last_creator.CC.inventory.cell[1]:CountChilds()==2 and last_window.profile_data.history=='A separate character history')
netcoop_save_draft=function() error('fixture write error') end
last_creator.actions.btn_start()
assert(last_creator.shown and last_creator.netcoop_status.text=='st_netcoop_loadout_error')
netcoop_save_draft=original_save
last_creator.actions.btn_back()
assert(last_window.mode=='profile' and not last_creator.shown and controls.input_history.text=='A separate character history')
local loads=canonical_loads
callbacks.profile_next();assert(canonical_loads==loads and last_creator.CC.inventory.cell[1]:CountChilds()==2, 'back must preserve selected equipment')
last_creator.actions.btn_start()
assert(drafts[1].loadout=='medkit,medkit,medkit')
assert(drafts[1].history=='A separate character history')
assert(last_window.mode=='characters' and controls.name.text=='Loner One' and #commands==0)
assert(not controls.input_email.shown and not controls.background.shown)
last_window:Update();assert(music_started==account_music, 'loaded room must wait for a successfully presented frame')
drafts[1].loadout='medkit,medkit,medkit,wpn_ak74';last_window:ShowCharacters()
assert(last_weapon=='' and controls.inventory_scroll==nil and controls.safe==nil and callbacks.char_inventory==nil)
finish_camera()
-- The inventory key no longer opens anything in the menu.
last_window:OnKeyboard(23,ui_events.WINDOW_KEY_PRESSED)
assert(last_window.room_view==nil and last_window.character_panel.shown and previews[#previews].pose==-2)
-- Esc on the character screen asks before quitting; nothing runs until confirmed.
last_window:OnKeyboard(DIK_keys.DIK_ESCAPE,ui_events.WINDOW_KEY_PRESSED)
assert(last_window.quit_box.shown and last_window.quit_box.template=='message_box_lostzone_quit' and #commands==0)
callbacks.quit_box(); assert(commands[#commands]=='quit'); commands={}
-- A second click while the camera is still moving is ignored.
last_window:ActivateObject(3);assert(settings_created==0 and last_window.room_view=='settings')
last_window:ActivateObject(3);assert(last_window.room_view=='settings','double click toggled the view')
finish_camera();assert(settings_created==1 and not last_window.shown)
last_window:CloseRoomView(); last_window:ShowDialog(true);last_window:Show(true)
last_window:ActivateObject(3);finish_camera();assert(settings_created==1)
last_window:CloseRoomView(); last_window:ShowDialog(true);last_window:Show(true)
local options_factory=ui_options.UIOptions;last_window.opt_dlg=nil
ui_options.UIOptions=function() error('fixture options failure') end
last_window:ActivateObject(3);finish_camera();assert(last_window.shown and controls.status.text=='st_netcoop_settings_error')
ui_options.UIOptions=options_factory
-- Changing servers must not expose or reuse another server's draft.
finish_camera()
controls.server_edit:SetText('Other-Server.example:1268');callbacks.server_save()
assert(draft_scope=='other-server.example:1268' and (last_window.names[1] or '')=='' and previews[#previews].pose==-2)
assert(draft_stores['127.0.0.1:5446'][1].name=='Loner One')
controls.server_edit:SetText('127.0.0.1:5446');callbacks.server_save();assert(last_window.names[1]=='Loner One' and previews[#previews].pose==-2)
last_window:ActivateObject(0); finish_camera();assert(controls.server_panel.shown,'server panel');callbacks.server_connect(); assert(cloud_requests[#cloud_requests].action=='refresh' and #commands==0,'server refresh')
on_cloud_result(false,'NETWORK_ERROR','cloud_user',true); assert(#commands==0)
callbacks.server_connect(); on_cloud_result(true,'','cloud_user',true)
assert(characters[#characters].name=='Loner One' and characters[#characters].slot==1)
assert(profile[1]=='Brown jacket' and #commands==2)
cache_characters('Server saved name||||');last_window:ShowCharacters();assert(last_window.names[1]=='Server saved name')
cloud_identity='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';last_window:ShowCharacters();assert((last_window.names[1] or '')=='' and previews[#previews].pose==-2)
cloud_identity='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';last_window:ShowCharacters();assert(last_window.names[1]=='Server saved name')
-- Network failure while refreshing a verified account does not ask for another email code.
last_window:ResetCloud();assert(not controls.input_code.shown and not controls.btn_reg.shown)
-- A remembered cloud account is refreshed before the frontend skips login.
commands={}; local again={HideDialog=function() end,Show=function() end,ShowDialog=function() end}
local before=#cloud_requests; assert(frontend_update(again)==true)
assert(#cloud_requests==before+1 and cloud_requests[#cloud_requests].action=='refresh' and #commands==0)
''')
lua.execute(r"""
on_cloud_result(true,'','cloud_user',true);last_window:Update()
assert(last_window.mode=='characters')
finish_camera()
commands={};controls.server_edit:SetText('role-test.example:1267');callbacks.server_check()
assert(cloud_requests[#cloud_requests].action=='refresh')
on_cloud_result(true,'','cloud_user',true)
assert(characters[#characters].slot==0 and #commands==0)
on_auth_result(false,0,'Server is unavailable')
assert(last_window.mode=='characters' and last_window:CharacterLimit()==1 and #commands==0)
callbacks.server_check();on_cloud_result(true,'','cloud_user',true)
role=2;cache_characters('Admin One|||||||||Admin Ten');on_auth_result(true,2,'Account verified')
assert(last_window:CharacterLimit()==10 and #commands==0)
last_window.slot=10;last_window:ChangeSlot(0);assert(controls.name.text=='Admin Ten')
controls.server_edit:SetText('another-role-server.example:1267');callbacks.server_save()
assert(last_window:CharacterLimit()==1 and not controls.slot10.shown)
""")
print('Firebase menu: separate account/character, verification gate, duplicate request lock, offline starter draft, stack counts, inventory key, refreshed world entry, remembered login PASS')
lua.execute(r"""
-- Closing a room view brings the camera back to the overview.
finish_camera(); last_window:ActivateObject(0); finish_camera(); assert(camera_target==0 and controls.server_panel.shown)
callbacks.room_back(); assert(camera_target==-1 and last_window.room_view==nil and not controls.server_panel.shown)
finish_camera()
-- A failing action is logged with its element name and stack; the menu keeps working.
last_window:Bind('fixture_fail', function() error('fixture failure') end)
assert(callbacks.fixture_fail()==false)
local f=assert(io.open(test_path..'logs\\lostzone_menu_errors.log'))
local text=f:read('*a'); f:close()
assert(text:find('fixture_fail',1,true) and text:find('fixture failure',1,true) and text:find('traceback',1,true))
callbacks.char_slot1(); assert(controls.name.text~=nil)
-- A native callback error is caught the same way.
local saved=cloud_error; assert(on_cloud_result(true,'','cloud_user',true)~=nil)
""")
print('Stage 0: camera arrows, no backpack/safe, Esc asks to quit, double click ignored while the camera moves, camera returns on close, logged guarded errors PASS')
lua.execute(r"""
-- Stage 2: the room objects are the buttons.
finish_camera(); last_window:CloseRoomView(); finish_camera()
assert(callbacks.char_enter==nil and callbacks.char_back==nil and not controls.details_panel.shown, 'old floating controls removed')
-- Hover over the PDA: highlight, label, one click sound.
local sounds=clicks_played
pick_result=0; cursor={x=300,y=330}; last_window:Update()
assert(last_hover==0 and last_window.hover_label.shown and last_window.hover_label.text=='st_netcoop_obj_pda')
assert(clicks_played==sounds+1); last_window:Update(); assert(clicks_played==sounds+1, 'sound only on change')
-- The door is behind the overview camera: never hovered from there.
pick_result=4; cursor={x=310,y=340}; last_window:Update(); assert(last_hover==-1)
-- Off every object: no highlight, no label.
pick_result=-1; cursor={x=320,y=350}; last_window:Update()
assert(last_hover==-1 and not last_window.hover_label.shown)
-- Arrows move the selection left to right: PDA, character, radio.
last_window:OnKeyboard(DIK_keys.DIK_DOWN,ui_events.WINDOW_KEY_PRESSED); last_window:Update(); assert(last_hover==0)
last_window:OnKeyboard(DIK_keys.DIK_DOWN,ui_events.WINDOW_KEY_PRESSED); last_window:Update(); assert(last_hover==2)
last_window:OnKeyboard(DIK_keys.DIK_UP,ui_events.WINDOW_KEY_PRESSED); last_window:Update(); assert(last_hover==0)
-- Tab shows every label while held (the door's too, it is off screen).
last_window:OnKeyboard(DIK_keys.DIK_TAB,ui_events.WINDOW_KEY_PRESSED); last_window:Update()
local shown=0; for _,label in pairs(last_window.tab_labels) do if label.shown then shown=shown+1 end end
assert(shown==5 and not last_window.hover_label.shown)
last_window:OnKeyboard(DIK_keys.DIK_TAB,ui_events.WINDOW_KEY_RELEASED); last_window:Update()
for _,label in pairs(last_window.tab_labels) do assert(not label.shown) end
-- Moving the mouse takes over from the keyboard; a click on the PDA opens the server view.
cursor={x=500,y=320}; pick_result=0; last_window:Update(); assert(last_hover==0)
last_window:OnKeyboard(DIK_keys.MOUSE_1,ui_events.WINDOW_KEY_PRESSED)
assert(last_window.room_view=='server' and last_hover==-1)
-- No highlight and no clicks on objects while the camera moves.
last_window:Update(); assert(last_hover==-1)
finish_camera(); assert(controls.server_panel.shown)
callbacks.room_back(); finish_camera(); assert(last_window.room_view==nil)
-- Edge arrows and left/right keys turn to the door. Clicking asks to quit only.
cache_characters('Door Tester||||||||||'); last_window:ShowCharacters(); finish_camera()
commands={}; local requests=#cloud_requests; local joins=#characters
callbacks.room_next(); assert(last_window.room_view=='door' and camera_target==4)
assert(not controls.room_back.shown, 'door has no Back overlay')
callbacks.room_next(); assert(last_window.room_view=='door','ignore rapid camera turn')
finish_camera(); pick_result=4; cursor={x=512,y=380}; last_window:Update(); assert(last_hover==4)
last_window:OnKeyboard(DIK_keys.MOUSE_1,ui_events.WINDOW_KEY_PRESSED)
assert(last_window.quit_box.shown and #cloud_requests==requests and #characters==joins and #commands==0)
last_window.quit_box:HideDialog() -- stay in the game
last_window:OnKeyboard(DIK_keys.DIK_LEFT,ui_events.WINDOW_KEY_PRESSED)
assert(camera_target==-1 and last_window.room_view==nil); finish_camera()
-- Character list appears only after clicking the character, and closes with Back.
last_window:ActivateObject(2); assert(not controls.details_panel.shown)
finish_camera(); assert(controls.details_panel.shown and camera_target==2)
callbacks.char_slot1(); finish_camera(); assert(camera_target==2 and controls.details_panel.shown)
callbacks.room_back(); finish_camera(); assert(not controls.details_panel.shown)
-- Radio is distinct from the toolbox and leaves the menu music running on close.
local options=settings_created
last_window:ActivateObject(1); finish_camera()
assert(controls.radio_panel.shown and settings_created==options and camera_target==1)
local station=netcoop_menu_radio.info(); callbacks.radio_station_next()
assert(netcoop_menu_radio.info()~=station)
callbacks.radio_track_next(); local _,track=netcoop_menu_radio.info(); assert(track:find('2 /',1,true))
callbacks.radio_volume_up(); local _,_,gain=netcoop_menu_radio.info(); assert(gain==0.30)
callbacks.radio_toggle(); local _,_,_,enabled=netcoop_menu_radio.info(); assert(not enabled)
callbacks.radio_toggle(); callbacks.room_back(); finish_camera()
assert(not controls.radio_panel.shown and music_sounds[#music_sounds].active)
-- Volume bounds, auto advance, no overlapping tracks, stop on world entry.
for i=1,40 do netcoop_menu_radio.volume(0.05) end
local _,_,gain=netcoop_menu_radio.info(); assert(gain==1)
for i=1,40 do netcoop_menu_radio.volume(-0.05) end
local _,_,gain=netcoop_menu_radio.info(); assert(gain==0 and not music_sounds[#music_sounds].active)
netcoop_menu_radio.volume(0.25); local old=music_sounds[#music_sounds]; old.active=false
now=now+6000; netcoop_menu_radio.update()
local _,track=netcoop_menu_radio.info(); assert(track:find('3 /',1,true))
local active=0; for _,sound in ipairs(music_sounds) do if sound.active then active=active+1 end end
assert(active==1)
present=true; netcoop_menu_radio.update(); assert(not music_sounds[#music_sounds].active);present=false
-- Enter from the PDA refreshes credentials, then stops the music before world start.
last_window:ActivateObject(0); finish_camera(); callbacks.server_connect()
assert(cloud_requests[#cloud_requests].action=='refresh' and #commands==0)
on_cloud_result(true,'','cloud_user',true)
assert(#commands==2 and not music_sounds[#music_sounds].active)

""")
print('Room interactions: camera arrows, quit confirmation, PDA entry, character dialog, toolbox settings, radio controls and audio lifecycle PASS')

temporary.cleanup()

# The base menu must not load another Lua class during its native constructor.
# Loading the account module here can disrupt luabind construction.
lua.execute((root/'scripts/netcoop-overlay/client/ui_main_menu.script').read_text(encoding='cp1251'))
lua.execute(r'''
local old_xml=CScriptXmlInit
function CScriptXmlInit()
 local x=old_xml()
 x.InitFrame=x.InitStatic; x.InitTextWnd=x.InitStatic
 return x
end
function CUIMessageBoxEx() return CUIStatic() end
function GetARGB() return 0 end
function CUIScriptWnd:SetTextAlignment() end
function CUIScriptWnd:SetColor() end
main_menu.get_main_menu=function() return {} end
netcoop_login_ui=setmetatable({}, {__index=function() error('Account module loaded during native main-menu construction') end})
local function test_menu(in_game,admin,expected)
 present=in_game;role=admin and 2 or 1
 local menu=setmetatable({}, {__index=main_menu})
 menu:InitControls()
 assert(#menu.menu_buttons==expected)
 menu:Show(false);for _, b in ipairs(menu.menu_buttons) do assert(not b.shown) end
 menu:Show(true);for _, b in ipairs(menu.menu_buttons) do assert(b.shown) end
end
test_menu(false,false,3);test_menu(false,true,3)
test_menu(true,false,4);test_menu(true,true,4)
''')
print('Actual base-menu controls: no nested account-class load, player/admin buttons and show/hide PASS')

lua.execute(r"""
-- Remembered account: Continue (Enter) or Switch account; profile Back returns here.
present=false;cloud_state=2;last_window.force_login=false;last_window.form_mode=nil
last_window:ResetCloud()
assert(last_window.screen=='signed_in' and controls.btn_enter.text=='st_netcoop_continue' and controls.btn_reset.text=='st_netcoop_switch_account')
assert(not controls.input_email.shown and not controls.tab_login.shown and not controls.btn_reg.shown)
local before=#cloud_requests;last_window:OnKeyboard(DIK_keys.DIK_RETURN,ui_events.WINDOW_KEY_PRESSED)
assert(cloud_requests[before+1].action=='refresh')
on_cloud_result(false,'NETWORK_ERROR','cloud_user',true);last_window:Update()
assert(last_window.screen=='signed_in' and last_window.msg.text=='st_netcoop_cloud_network_error')
last_window.names={};drafts={};last_window:ShowProfile(1);last_window:OnBack()
assert(last_window.mode=='account' and last_window.screen=='signed_in', 'profile Back without characters keeps the signed-in account')
-- Switch account: sign-in form with the old email; Tab walks the fields.
callbacks.btn_reset();assert(cloud_state==0 and last_window.screen=='login' and last_window.focus_index==2)
last_window:OnKeyboard(DIK_keys.DIK_TAB,ui_events.WINDOW_KEY_PRESSED);assert(last_window.focus_index==1)
last_window:OnKeyboard(DIK_keys.DIK_TAB,ui_events.WINDOW_KEY_PRESSED);assert(last_window.focus_index==2)
-- Forgot password keeps the form and reports the result there.
controls.input_email:SetText('');callbacks.btn_reset();assert(last_window.msg.text=='st_netcoop_email_invalid')
controls.input_email:SetText('new@example.invalid');callbacks.btn_reset();assert(cloud_requests[#cloud_requests].action=='reset')
on_cloud_result(true,'','',false);last_window:Update()
assert(last_window.screen=='login' and last_window.msg.text=='st_netcoop_reset_sent' and controls.input_email.text=='new@example.invalid')
-- Registration by Enter from the last field.
callbacks.tab_register();assert(last_window.screen=='register' and #last_window.fields==4)
controls.input_login:SetText('new_user');controls.input_pass:SetText('test-password');controls.input_pass2:SetText('test-password')
last_window:OnKeyboard(DIK_keys.DIK_RETURN,ui_events.WINDOW_KEY_PRESSED)
assert(cloud_requests[#cloud_requests].action=='register' and cloud_requests[#cloud_requests].email=='new@example.invalid')
cloud_state=1;on_cloud_result(true,'','new_user',false);last_window:Update()
assert(last_window.screen=='verify' and last_window.title.text=='st_netcoop_verify_title')
-- Sign-out during a verification poll waits for the poll (it would save the session again).
now=now+6000;last_window:Update();assert(last_window.verify_poll)
callbacks.btn_reset();assert(cloud_state==1 and last_window.sign_out_after_poll and last_window.msg.text=='st_netcoop_wait_request')
on_cloud_result(false,'EMAIL_NOT_VERIFIED','new_user',false)
assert(cloud_state==0 and last_window.screen=='login' and logouts==3)
-- Leaving the room stops playback; account/profile updates cannot restart it.
netcoop_preview_clear();local before=music_started;netcoop_menu_radio.update()
netcoop_menu_radio.volume(0.05);netcoop_menu_radio.station(1);netcoop_menu_radio.track(1)
assert(music_started==before and not music_sounds[#music_sounds].active)
""")
print('Account screens: register with repeat, existing email to sign-in, resend countdown, change email, sign out/switch, forgot password, Tab/Enter, poll ordering PASS')
