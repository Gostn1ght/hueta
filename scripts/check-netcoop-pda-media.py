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
