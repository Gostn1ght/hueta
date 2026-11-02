"""Actual two-server PDA network + USB persistence and physical ACL regression."""
from pathlib import Path
import runpy
scope=runpy.run_path(str(Path(__file__).with_name('check-netcoop-pdanet.py')))
g,lua,servers,cmd,last=map(scope.__getitem__,['g','lua','servers','cmd','last'])
read=lambda b,k: lua.eval('function(b,k) return netcoop_transit.deserialize(netcoop_store_read(b,k)) end')(b,k)
lua.execute(r'''
players[10]={char="legacy10",name="Леший",server=1,pda=1000}
players[11]={char="fresh11",name="Ворон",server=2,pda=1010}
make_item(1000,"device_pda_2","physical1000");items[1000].owner=10
make_item(1001,"device_pda_3","physical1001");items[1001].owner=10
make_item(1010,"device_pda_1","physical1010");items[1010].owner=11
make_item(1002,"lz_pda_data_usb","usb1002");items[1002].owner=10
make_item(1003,"lz_pda_hack_usb","usb1003");items[1003].owner=11
local function put(b,k,v) assert(netcoop_store_swap(b,k,"",netcoop_transit.serialize(v))) end
put("pda_prof","legacy10",{uid="887766",name="Леший",icon="",contacts={},chats={}})
netcoop_store_swap("pda_uid","887766","","legacy10")
put("pda_memo","legacy10",{{id="1",title="Тайник",text="Мои старые записи"}})
netcoop_store_swap("pda_lock","legacy10","",netcoop_store_read("pda_lock","u501"))
''')
a=last(cmd(0,10,'pdanet hello'),'state');assert a.uid=='887766' and a.locked
assert last(cmd(0,10,'pdanet unlock secret2'),'state').locked is None
assert last(cmd(0,10,'pdanet notes'),'notes')[1].text=='Мои старые записи'
cmd(0,10,'pdanet lockset secret2|')
assert not last(cmd(0,10,'pdanet hello'),'state').has_lock, 'legacy password must never reappear after removal'
# The same account equips a replacement, then recovers the original from another server.
g.players[10].pda=1001
b=last(cmd(0,10,'pdanet hello'),'state');assert b.uid!=a.uid and not b.has_lock and len(b.contacts)==0
assert len(last(cmd(0,10,'pdanet notes'),'notes'))==0
cmd(0,10,'pdanet lockset |targetpass')
g.players[10].pda=1000
assert last(cmd(1,10,'pdanet hello'),'state').uid==a.uid
cmd(0,10,'pdanet note new|Проверка|Только этот КПК')
# Populate two full current chat histories (>64 KiB combined). Archive data must
# be sharded rather than rejected by the real native shared-store key/value bounds.
lua.execute(r'''
local p=netcoop_transit.deserialize(netcoop_store_read("pda_prof","physical1000"))
for n=1,2 do
 local cid="archive_fixture_"..n
 local chat={seq=90,kind="d",members={[p.uid]=true},msgs={}}
 for i=1,90 do chat.msgs[i]={s=i,f=p.uid,k="text",x=string.rep("x",400)..i,t=i,g=i} end
 p.chats[cid]=90
 assert(netcoop_store_swap("pda_chat",cid,"",netcoop_transit.serialize(chat)))
end
assert(netcoop_store_swap("pda_prof","physical1000",netcoop_store_read("pda_prof","physical1000"),netcoop_transit.serialize(p)))
netcoop_store_swap("pda_marks","physical1000","","abcdef")
netcoop_store_swap("map_known","physical1000","",netcoop_transit.serialize({l01_escape={camp=true}}))
''')
photo='a'*16
cmd(0,10,f'pdanet gbeg {photo} 1 l01_escape')
assert any(k=='stored' for k,v in cmd(0,10,f'pdanet aup {photo} 1 RERTIAQUJD'))
assert last(cmd(0,10,'pdanet library'),'library').photos[1].id==photo
r=last(cmd(0,10,'pdanet usb_backup 1002'),'storage');assert r.done=='usb_backup'
# Flash drives cannot impersonate each other, and no client-provided UID can pick
# somebody else's backup. The slot and inventory parent are authoritative.
assert last(cmd(0,10,'pdanet usb_backup 1003'),'err')=='data flash drive required'
g.players[10].pda=1001
cmd(0,10,'pdanet hello')
assert last(cmd(1,10,'pdanet usb_restore 1002'),'err')=='locked'
cmd(0,10,'pdanet unlock targetpass')
r=last(cmd(0,10,'pdanet usb_restore 1002'),'storage');assert r.done=='usb_restore'
assert len(r.archive)==2 and r.archive[1].count==90
st=last(cmd(0,10,'pdanet hello'),'state')
assert st.uid==b.uid and st.has_lock, 'restore retains target UID/password/hardware identity'
assert len(st.chats)==0, 'history copies cannot grant membership of source private chats'
assert len(last(cmd(0,10,'pdanet notes'),'notes'))==2
assert g.netcoop_store_read('pda_marks','physical1001')=='abcdef'
assert read('map_known','physical1001').l01_escape.camp
assert last(cmd(0,10,'pdanet usb_archive 1 90'),'storage').view.message.x.endswith('90')
assert any(k=='photo' for k,v in cmd(0,10,f'pdanet pget {photo}')), 'copied gallery grants access to its actual pixels'
assert last(cmd(1,11,f'pdanet pget {photo}'),'err')=='no such photo'
# Moving the SAME physical PDA transfers its data. A hacker needs the other
# flash drive, must keep it, and unlocking consumes exactly one of five charges.
lua.execute('players[10].pda=nil;players[11].pda=1001;items[1001].owner=11;items[1003].owner=10')
assert last(cmd(1,11,'pdanet hello'),'state').foreign
assert last(cmd(1,11,'pdanet hack'),'err')=='hack flash drive required'
lua.execute('items[1003].owner=11')
assert last(cmd(1,11,'pdanet hack'),'device').hack_total==90000
lua.execute('items[1003].owner=10')
g.tg+=2500;g.current_server=2;servers[1].update_world()
assert any(x[1]=='err' and x[2]=='hack interrupted' for x in g.take(11).values())
lua.execute('items[1003].owner=11')
cmd(1,11,'pdanet hack');g.tg+=91000;g.current_server=2;servers[1].update_world()
assert read('pda_tool','usb1003').left==4
assert not last(cmd(1,11,'pdanet hello'),'state').foreign
assert len(last(cmd(1,11,'pdanet notes'),'notes'))==2
# Factory reset erases this device; it does not load the new holder's other
# PDA or resurrect legacy data. The hardware serial survives; network UID rotates.
serial=last(cmd(1,11,'pdanet device'),'device').serial
cmd(1,11,'pdanet gbeg '+('b'*16)+' 1 l01_escape')
st=last(cmd(1,11,'pdanet wipe'),'state');assert st.uid not in (a.uid,b.uid)
assert not any(k=='stored' for k,v in cmd(1,11,'pdanet aup '+('b'*16)+' 1 RERTIAQUJD')), 'reset cancels in-flight media'
assert last(cmd(1,11,'pdanet device'),'device').serial==serial
assert len(last(cmd(1,11,'pdanet notes'),'notes'))==0
assert len(last(cmd(1,11,'pdanet library'),'library').photos)==0
# Restore journal survives failed writes; the next server completes it before
# exposing any profile data, independently of whether the USB is still carried.
lua.execute('players[10].pda=1000;items[1000].owner=10;items[1002].owner=10')
cmd(0,10,'pdanet hello')
lua.execute(r'''
real_swap=netcoop_store_swap
block_restore=true
function netcoop_store_swap(b,k,old,new)
 if block_restore and b=="pda_memo" and k=="physical1000" then return false end
 return real_swap(b,k,old,new)
end
-- Make the target differ so an actual write is required.
real_swap("pda_memo","physical1000",netcoop_store_read("pda_memo","physical1000"),"")
''')
assert last(cmd(0,10,'pdanet usb_restore 1002'),'err')=='restore pending'
assert g.netcoop_store_read('pda_restore','physical1000')!=''
lua.execute('block_restore=false;items[1002].owner=11')
assert last(cmd(1,10,'pdanet hello'),'state').uid==a.uid
assert len(last(cmd(1,10,'pdanet notes'),'notes'))==2
assert g.netcoop_store_read('pda_restore','physical1000')==''
print('PASS physical PDA: one-time legacy migration; independent accounts/devices/locks; USB inventory ACL; full paged chat archive; photo bytes; interrupted and charged hacking; reset; cross-server interrupted restore recovery; actual native storage bounds')

# Same-length storage corruption is detected before journalling any target writes.
lua.execute(r'''
items[1002].owner=10
local meta=netcoop_transit.deserialize(netcoop_store_read("pda_usb","usb1002"))
corrupt_key=meta.usb.."_"..meta.revision.."_pda_memo_1"
original_blob=netcoop_store_read("pda_usb_blob",corrupt_key)
assert(real_swap("pda_usb_blob",corrupt_key,original_blob,"X"..original_blob:sub(2)))
''')
assert last(cmd(0,10,'pdanet usb_restore 1002'),'err')=='damaged backup'
assert g.netcoop_store_read('pda_restore','physical1000')==''
assert len(last(cmd(0,10,'pdanet notes'),'notes'))==2
lua.execute('assert(real_swap("pda_usb_blob",corrupt_key,netcoop_store_read("pda_usb_blob",corrupt_key),original_blob))')
print('PASS USB backup checksum rejects same-length damaged data without altering the target')

# The native recorder permits 6 MiB of binary data (8 MiB in base64). Its
# library upload must accept that size instead of silently remaining local.
large='c'*16
replies=cmd(0,10,f'pdanet rbeg {large} 2300 600')
assert not any(k=='err' for k,v in replies), replies
print('PASS PDA library accepts the native recorder upper bound (2300 transport chunks)')

# Known device passwords grant access without spending a hacking charge.
lua.execute('''
make_item(1020,"device_pda_1","physical1020");items[1020].owner=10;players[10].pda=1020
''')
cmd(0,10,'pdanet hello');cmd(0,10,'pdanet lockset |shared123')
cmd(0,10,'pdanet note new|Borrowed|Authorized by the owner password')
lua.execute('players[10].pda=1000;players[11].pda=1020;items[1020].owner=11;items[1003].owner=10')
assert last(cmd(1,11,'pdanet hello'),'state').foreign
assert last(cmd(1,11,'pdanet unlock wrong'),'err')=='wrong password'
assert not last(cmd(1,11,'pdanet unlock shared123'),'state').foreign
assert len(last(cmd(1,11,'pdanet notes'),'notes'))==1
assert read('pda_tool','usb1003').left==4
# An owner may explicitly reset an unlocked owned device too.
lua.execute('players[11].pda=1001')
uid_before=last(cmd(1,11,'pdanet hello'),'state').uid
assert last(cmd(1,11,'pdanet wipe'),'state').uid!=uid_before
# Forgotten own password: another actor session, same character/PDA; a real
# decryption drive resets only the password, keeping UID/notes/gallery intact.
cmd(0,10,'pdanet lockset |forgotten123')
lua.execute('''
players[12]={char="legacy10",name="Леший",server=2,pda=1000}
players[10].pda=nil;items[1000].owner=12;items[1003].owner=12
''')
locked=last(cmd(1,12,'pdanet hello'),'state');assert locked.locked
assert last(cmd(1,12,'pdanet hack'),'device').hack_total==70000
assert last(cmd(1,12,'pdanet wipe'),'err')=='not hacked', 'locked owned PDA cannot bypass its password by resetting'
g.tg+=71000;g.current_server=2;servers[1].update_world()
st=last(cmd(1,12,'pdanet hello'),'state')
assert st.uid==locked.uid and not st.has_lock
assert len(last(cmd(1,12,'pdanet notes'),'notes'))==2
assert read('pda_tool','usb1003').left==3
# Exhausted tools remain exhausted after changing hands and servers.
lua.execute('''
local old=netcoop_store_read("pda_tool","usb1003")
assert(netcoop_store_swap("pda_tool","usb1003",old,netcoop_transit.serialize({left=0})))
make_item(1030,"device_pda_1","physical1030");items[1030].owner=11;players[11].pda=1030
''')
cmd(1,11,'pdanet hello')
lua.execute('players[11].pda=nil;players[12].pda=1030;items[1030].owner=12')
assert last(cmd(1,12,'pdanet hack'),'err')=='hack flash drive required'
print('PASS PDA access: known foreign password, owned factory reset, forgotten-password recovery without data loss, exhausted physical tools')
