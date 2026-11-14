"""Actual inventory removal clears hands before the slot disappears (CI only)."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks must run in GitHub Actions")
root = Path(__file__).resolve().parents[1]
text = (root / "src/xrGame/Inventory.cpp").read_text(encoding="utf-8")
start = text.index("void CInventory::netcoop_remove_from_hands(")
end = text.index("bool CInventory::DropItem(", start)
for name in ("DropItem", "Slot", "Belt", "Ruck"):
    begin = text.index("bool CInventory::" + name + "(")
    stop = text.index("\n}", begin)
    method = text[begin:stop]
    assert method.index("netcoop_remove_from_hands(pIItem)") < method.index("m_slots[pIItem->CurrSlot()].m_pIItem = NULL")
source = r'''
#include <cassert>
#include <cstdio>
using u16=unsigned short;using u32=unsigned;
constexpr u16 NO_ACTIVE_SLOT=0xffff;
constexpr u16 DETECTOR_SLOT=9;
#define FALSE false
namespace CHUDState{constexpr unsigned eHidden=0;}
struct Item;
namespace netcoop{bool active=true,client=true;bool enabled(){return active;}bool client_owns_hud_item(const Item*);}
struct Owner{virtual ~Owner()=default;};struct CActor:Owner{bool seated=false;bool netcoop_seated(){return seated;}};
template<class T,class U>T smart_cast(U* p){return dynamic_cast<T>(p);}
struct CHudItem{
 unsigned next=2,state=2,hidden=0;
 void SetNextState(unsigned s){next=s;}
 unsigned GetState(){return state;}
 void OnStateSwitch(unsigned s,unsigned){state=s;++hidden;}
};
struct CWeapon{unsigned unzoomed=0;bool zoomed=true;bool IsZoomed(){return zoomed;}void OnZoomOut(){++unzoomed;}};
struct Item{
 virtual ~Item()=default;
 bool owned=true;
 u16 slot=3;CHudItem hud;CWeapon weapon;bool device=false;
 u16 CurrSlot(){return slot;}
 CHudItem* cast_hud_item(){return &hud;}
 CWeapon* cast_weapon(){return device?nullptr:&weapon;}
};
using PIItem=Item*;
namespace netcoop{bool client_owns_hud_item(const Item* item){return active&&client&&item&&item->owned;}}
struct Hud{unsigned detaches=0;template<class T>void detach_item(T* item){++detaches;item->attached=false;}}hud;
Hud* g_player_hud=&hud;
struct CCustomDevice:Item{
 static constexpr unsigned eHidden=CHUDState::eHidden;
 bool m_bWorking=true,m_bNeedActivation=true,m_bZoomed=true,pending=true,animation=true,attached=true;
 float m_fZoomfactor=1;u32 m_netcoop_state_sync=999;unsigned sends=0,off=0;
 Item& object(){return *this;}unsigned GetState(){return this->hud.state;}
 void StopCurrentAnimWithoutCallback(){animation=false;}
 void SetPending(bool value){pending=value;}bool IsPending(){return pending;}
 void TurnDeviceInternal(bool value){m_bWorking=value;++off;}
 void SetState(unsigned state){this->hud.state=state;}void SetNextState(unsigned state){this->hud.next=state;}
 void SwitchState(unsigned state){SetState(state);SetNextState(state);++sends;}
 bool IsAttachedToHUD(){return attached;}
 void netcoop_holster();
};
struct CInventory{
 Owner* m_pOwner=nullptr;
 u16 m_iActiveSlot=3,m_iNextActiveSlot=3,m_iPrevActiveSlot=3;
 Item* held=nullptr;PIItem ActiveItem(){return held;}
 Item* secondary=nullptr;PIItem ItemFromSlot(u16 slot){assert(slot==DETECTOR_SLOT);return secondary;}
 void netcoop_remove_from_hands(PIItem);bool netcoop_holster_in_vehicle();
};
'''
device = (root / 'src/xrGame/CustomDevice.cpp').read_text(encoding='utf-8')
device_start = device.index('void CCustomDevice::netcoop_holster()')
device_end = device.index('void CCustomDevice::ToggleDevice(', device_start)
source += device[device_start:device_end] + '\n' + text[start:end]
source += r'''
int main(){
 CActor actor;Owner npc;Item item;CInventory inv;inv.m_pOwner=&actor;
 inv.netcoop_remove_from_hands(&item);
 assert(item.hud.hidden==1 && item.hud.state==0 && item.hud.next==0 && item.weapon.unzoomed==1);
 assert(inv.m_iActiveSlot==NO_ACTIVE_SLOT && inv.m_iNextActiveSlot==NO_ACTIVE_SLOT && inv.m_iPrevActiveSlot==NO_ACTIVE_SLOT);
 inv.netcoop_remove_from_hands(&item);assert(item.hud.hidden==1);
 inv.m_iActiveSlot=3;inv.m_iNextActiveSlot=5;inv.m_iPrevActiveSlot=5;
 inv.netcoop_remove_from_hands(&item);assert(inv.m_iActiveSlot==NO_ACTIVE_SLOT && inv.m_iNextActiveSlot==5 && inv.m_iPrevActiveSlot==5);
 item.device=true;inv.m_iActiveSlot=3;inv.netcoop_remove_from_hands(&item);assert(item.weapon.unzoomed==2);
 item.device=false;item.weapon.zoomed=false;inv.m_iActiveSlot=5;inv.m_iNextActiveSlot=3;
 inv.netcoop_remove_from_hands(&item);assert(inv.m_iActiveSlot==5 && inv.m_iNextActiveSlot==NO_ACTIVE_SLOT && item.weapon.unzoomed==2);
 inv.m_iActiveSlot=3;inv.m_iNextActiveSlot=3;inv.m_pOwner=&npc;
 auto count=item.hud.hidden;inv.netcoop_remove_from_hands(&item);assert(item.hud.hidden==count && inv.m_iActiveSlot==3);
 inv.m_pOwner=&actor;netcoop::active=false;inv.netcoop_remove_from_hands(&item);assert(item.hud.hidden==count && inv.m_iActiveSlot==3);
 netcoop::active=true;inv.m_pOwner=&actor;actor.seated=true;inv.held=&item;
 CCustomDevice left;inv.secondary=&left;
 inv.m_iActiveSlot=3;inv.m_iNextActiveSlot=5;inv.m_iPrevActiveSlot=7;
 auto before=item.hud.hidden;
 assert(inv.netcoop_holster_in_vehicle() && item.hud.hidden==before+1);
 assert(!left.m_bWorking&&!left.animation&&!left.pending&&!left.m_bNeedActivation&&!left.m_bZoomed);
 assert(left.hud.state==0&&left.hud.next==0&&left.off==1&&left.sends==1&&!left.attached);
 left.m_netcoop_state_sync=777;
 assert(inv.netcoop_holster_in_vehicle()&&left.sends==1&&left.off==1&&left.m_netcoop_state_sync==777);
 assert(inv.m_iActiveSlot==NO_ACTIVE_SLOT && inv.m_iNextActiveSlot==NO_ACTIVE_SLOT && inv.m_iPrevActiveSlot==NO_ACTIVE_SLOT);
 inv.held=nullptr;inv.m_iNextActiveSlot=5;assert(inv.netcoop_holster_in_vehicle() && inv.m_iNextActiveSlot==NO_ACTIVE_SLOT);
 left.m_bWorking=true;
 actor.seated=false;inv.m_iNextActiveSlot=3;assert(!inv.netcoop_holster_in_vehicle() && inv.m_iNextActiveSlot==3&&left.m_bWorking);
 actor.seated=true;netcoop::active=false;assert(!inv.netcoop_holster_in_vehicle());
 netcoop::active=true;inv.m_pOwner=&npc;assert(!inv.netcoop_holster_in_vehicle());
 assert(left.m_bWorking);
 CCustomDevice server;netcoop::client=false;g_player_hud=nullptr;server.netcoop_holster();
 assert(server.hud.state==0&&server.hud.next==0&&!server.m_bWorking&&!server.pending&&server.sends==0);
 CCustomDevice loading;netcoop::client=true;loading.netcoop_holster();
 assert(loading.hud.state==0&&!loading.m_bWorking&&loading.sends==0);
 CCustomDevice observer;netcoop::client=true;observer.owned=false;observer.attached=false;g_player_hud=&hud;
 observer.netcoop_holster();assert(observer.sends==0&&observer.hud.state==0&&!observer.m_bWorking);
 std::puts("PASS actual secondary device vehicle holster: animation/work/light off, no automatic reactivation, one owner event, no refresh flood, observer/dedicated HUD safe");
 std::puts("PASS actual hand removal and seated activation fence: hidden state, zoom, active/pending/previous slots, devices, NPC/freeplay guards");
}
'''
with TemporaryDirectory() as tmp:
    cpp = Path(tmp) / "hands.cpp"
    exe = Path(tmp) / ("hands.exe" if os.name == "nt" else "hands")
    cpp.write_text(source, encoding="utf-8")
    command = (["cl", "/nologo", "/std:c++17", "/EHsc", "/W4", "/WX", str(cpp), "/Fe:" + str(exe)]
               if os.name == "nt" else ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)])
    subprocess.run(command, cwd=tmp, check=True)
    subprocess.run([str(exe)], cwd=tmp, check=True)
