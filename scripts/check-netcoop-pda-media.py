"""Actual client camera/recorder, background transport and server libraries."""
from pathlib import Path
import runpy
s=runpy.run_path(str(Path(__file__).with_name('check-netcoop-pdanet-photo.py')))
lua,g,load,run,to_client,flush=map(s.__getitem__,['lua','g','load','run','to_client','flush_commands'])
root=s['root'];client=g.netcoop_pdanet_client
lua.execute('commands={};equipped_pda=901;netcoop_pda.reset();netcoop_pda.receive("fixture901|901|1/1|");function AddUniqueCall(f) media_tick=f end')
to_client(run(1,'pdanet hello'))
media=load('netcoop_pda_media',root/'client/netcoop_pda_media.script');media.on_game_start()
photo=load('netcoop_pdanet_photo',root/'client/netcoop_pdanet_photo.script')
voice=load('netcoop_pdanet_voice',root/'client/netcoop_pdanet_voice.script')
# Keep a received photo on this physical device; the background path saves pixels
# without sending anything to a chat and acknowledges the server index.
pid='f'*16;g.files['c_'+pid]='RERTIAQUJD'
assert photo.keep(pid,'l01_escape')
photo_id=photo.photos[1].id
for _ in range(50):
 g.tg+=100;g.media_tick();to_client(flush(1))
 if media.ready(): break
assert media.ready() and photo.photos[1].cloud
library=run(1,'pdanet library');to_client(library);to_client(flush(1))
assert any(p.id==photo_id for p in client.library.photos.values())
# A different PC has no DDS cache. The physical device's server index and pixel
# chunks rebuild its gallery; an account-wide local index cannot provide it.
g.files=lua.table()
photo=load('netcoop_pdanet_photo',root/'client/netcoop_pdanet_photo.script')
to_client(run(1,'pdanet library'));to_client(flush(1))
assert any(p.id==photo_id for p in photo.photos.values())
p=next(p for p in photo.photos.values() if p.id==photo_id)
assert g.files[photo.file_name(p)]=='RERTIAQUJD'
# Dictaphone uses the same physical library and sharded transport, not a profile
# number. It follows the device after reload too.
lua.execute('''
rec={data="RElDVA==",secs=0,on=false}
function netcoop_record_start(limit) rec.on=true;rec.limit=limit;return true end
function netcoop_record_seconds() return rec.secs end
function netcoop_record_stop() rec.on=false;return rec.data end
function netcoop_record_active() return rec.on end
''')
voice.dict_start();g.rec.secs=7;voice.dict_stop()
aid=voice.records[1].id
for _ in range(50):
 g.tg+=100;g.media_tick();to_client(flush(1))
 if media.ready(): break
assert media.ready() and voice.records[1].cloud
voice=load('netcoop_pdanet_voice',root/'client/netcoop_pdanet_voice.script')
to_client(run(1,'pdanet library'));to_client(flush(1))
assert any(r.id==aid and r.data=='RElDVA==' for r in voice.records.values())
# A remote library lists a large record without eagerly fetching its audio.
lua.execute('commands={};netcoop_pdanet_voice.reset_content()')
to_client(run(1,'pdanet library'))
assert not any('pdanet aget' in c for c in g.commands.values())
# Requesting playback fetches this recording, and no other library item.
lua.execute('function netcoop_play_start() return 7 end')
voice.dict_play(1);to_client(flush(1))
assert voice.records[1].data=='RElDVA=='
# Neither a late reply nor an unfinished recording/capture can fill a replacement.
late=run(1,'pdanet notes')
voice.dict_start()
lua.execute('''
equipped_pda=904
local item={id=function() return 904 end,section=function() return "device_pda_3" end}
pda_items[904]=item;players[1].pda_item=item
netcoop_pda.reset();netcoop_pda.receive("fixture904|904|1/1|")
''')
to_client(run(1,'pdanet hello'));to_client(late)
voice.on_game_start();g.callbacks.actor_on_update()
to_client(run(1,'pdanet library'));photo.load()
assert client.slot_device.uid=='fixture904' and len(photo.photos)==0 and len(voice.records)==0
assert not voice.recording()
assert media.ready()
print('PASS real PDA media flow: physical gallery/recorder, background upload acknowledgments, cache-free client recovery, new-device isolation, stale reply rejection and interrupted recording')

# Real scripted tab constructors and stale edit drafts, with engine widgets
# stubbed. A physical-device change must clear even a cached notes window.
notes_window=g.pdanet_notes()
storage_window=g.pdanet_storage()
notes_window.title_edit.SetText(notes_window.title_edit,'Old PDA private draft')
notes_window.body_edit.SetText(notes_window.body_edit,'Must not enter a replacement')
lua.execute('''
equipped_pda=905
local item={id=function() return 905 end,section=function() return "device_pda_1" end}
pda_items[905]=item;players[1].pda_item=item
''')
to_client(run(1,'pdanet hello'))
assert notes_window.title_edit.GetText(notes_window.title_edit)==''
assert notes_window.body_edit.GetText(notes_window.body_edit)==''
print('PASS actual USB tab construction and cached notes draft reset on device change')

# Imported attachments use the same authorized media helpers as live chats.
# Their storage identifiers must not replace a photo or recording in the UI.
g.archive_window=storage_window
lua.execute('''
local ph,vo=netcoop_pdanet_photo,netcoop_pdanet_voice
local oldphoto,oldplay=ph.message_photo,vo.play_message
ph.message_photo=function(m) assert(m.k=="photo");return "fixture/archive_photo" end
archive_played=false
vo.play_message=function(m) assert(m.k=="voice");archive_played=true end
local n=netcoop_pdanet_client
n.storage.archive={{name="Saved conversation",count=2}}
archive_window:Archive(1,1)
n.storage.view={name="Saved conversation",chat=1,msg=1,total=2,message={k="photo",d="abcdef1234567890 l01_escape",t=1}}
n.notify("storage")
assert(archive_window.arc.img.shown and archive_window.arc.img.texture=="fixture/archive_photo")
assert(not archive_window.arc.body.text:find("abcdef1234567890",1,true))
archive_window._cb[archive_window._ids[archive_window.arc.close]]()
n.notify("photo")
assert(not archive_window.arc.img.shown and not archive_window.arc_open)
archive_window:Archive(1,2)
assert(not archive_window.arc.img.shown and not archive_window.arc.play.shown)
n.storage.view={name="Saved conversation",chat=1,msg=2,total=2,message={k="voice",d="bbbbbbbbbbbbbbbb 7",t=1}}
n.notify("storage")
assert(archive_window.arc.play.shown and not archive_window.arc.img.shown)
archive_window._cb[archive_window._ids[archive_window.arc.play]]()
assert(archive_played and not archive_window.arc.body.text:find("bbbbbbbbbbbbbbbb",1,true))
n.notify("device_reset")
assert(not archive_window.arc_open and not archive_window.arc.play.shown)
ph.message_photo,vo.play_message=oldphoto,oldplay
''')
print('PASS imported photo/voice UI, hidden media IDs, closed-overlay and device-change isolation')

# A known foreign-device password must also have a reachable UI control.
lua.execute('''
local n=netcoop_pdanet_client
local old=n.slot_device
n.foreign=true;n.slot_device={serial="TEST",lock=true,hacked=false,level=1}
archive_window.tick_at=0;archive_window:Update()
assert(archive_window.dev.edit.shown and archive_window.dev.unlock.shown)
archive_window.dev.edit:SetText("known-password")
n.notify("device_reset")
assert(archive_window.dev.edit:GetText()=="")
n.foreign=false;n.slot_device=old
archive_window.tick_at=0;archive_window:Update()
assert(not archive_window.dev.edit.shown and not archive_window.dev.unlock.shown)
''')
print('PASS foreign-password entry is reachable and cleared when the device changes')

# Complete the native 6 MiB/8 MiB-base64 recording at a slow 10 upload ticks/s.
# The previous fixed one-minute deadline silently killed long uploads halfway.
big_id='e'*16
big='QUJD'*(2*1024*1024)
lua.execute('commands={}')
assert media.push('audio',big_id,big,600)
for _ in range(2400):
 g.tg+=100;g.media_tick();to_client(flush(1))
 if media.ready(): break
assert media.ready()
meta=lua.eval('function(id) return netcoop_transit.deserialize(netcoop_store_read("pda_audio",id)) end')(big_id)
assert meta and meta.library and meta.device=='fixture905' and meta.parts>100
print('PASS full 8 MiB recording persisted at 10 ticks/s without the old one-minute timeout')
