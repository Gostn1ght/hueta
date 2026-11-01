"""CI only: execute real trunk packets, anchor reach, menu closure and reset."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

root = Path(__file__).resolve().parents[1]
vehicles = ''.join((root / f'src/xrGame/{n}').read_text(encoding='utf-8-sig') for n in ('netcoop_vehicles.inc', 'netcoop_vehicle_server.inc', 'netcoop_vehicle_client.inc', 'netcoop_vehicle_seat.inc'))
menu = (root / 'src/xrGame/ui/UIActorMenu.cpp').read_text(encoding='utf-8-sig')
reach = vehicles[vehicles.index('bool box_anchor_within_reach('):vehicles.index('static const u16 vehicle_seat_free')]
packet = vehicles[vehicles.index('static void client_trunk_open('):vehicles.index('void client_on_vehicle(')]
reset = vehicles[vehicles.index('void vehicles_reset()'):vehicles.index('static void client_trunk_open(')]
distance = menu[menu.index('void CUIActorMenu::CheckDistance()'):menu.index('EDDListType CUIActorMenu::GetListType')]
source = r'''
#include <cassert>
#include <cmath>
#include <map>
#include <vector>
using u16=unsigned short;using u32=unsigned;
struct Fvector {float x=0,y=0,z=0;float distance_to(const Fvector& b)const {
 return std::sqrt((x-b.x)*(x-b.x)+(y-b.y)*(y-b.y)+(z-b.z)*(z-b.z));}};
struct CGameObject {
 u16 id=0;Fvector pos;float radius=1;bool destroyed=false,awareness=false;
 u16 ID()const{return id;}const Fvector& Position()const{return pos;}
 float Radius()const{return radius;}bool getDestroy()const{return destroyed;}
 bool NeedOsoznanieMode()const{return awareness;}
};
using CObject=CGameObject;
template<class T>T smart_cast(CGameObject* value){return static_cast<T>(value);}
std::map<u16,CObject*> objects;
struct ObjectList {CObject* net_Find(u16 id) {auto i=objects.find(id);return i==objects.end()?nullptr:i->second;}};
struct TestLevel {ObjectList Objects;} test_level;
TestLevel& Level(){return test_level;}
struct {u32 dwTimeGlobal=100;} Device;
struct NET_Packet {
 std::vector<unsigned char> data;unsigned cursor=0;
 u32 r_elapsed()const{return unsigned(data.size())-cursor;}
 u16 r_u16(){assert(r_elapsed()>=2);auto lo=data[cursor++];auto hi=data[cursor++];return u16(lo|(hi<<8));}
};
namespace netcoop {
std::map<u16,u16> s_box_anchor;
std::map<u16,unsigned> s_vehicle_seats,s_vehicles_sv,s_vehicles_cl,s_vehicle_hud;
std::vector<unsigned> s_vehicle_arrivals,s_vehicle_conditions;
u32 s_vehicle_inbox_check=99,s_vehicle_keys=1,s_vehicle_keys_sent=99;
u16 s_trunk_pending=0xffff;u32 s_trunk_pending_until=0;
''' + reach + reset + packet + r'''
}
#define VERIFY(v) assert(v)
struct Hint {unsigned discarded=0;void Discard(){++discarded;}} test_hint;
Hint* g_btnHint=&test_hint;
struct CUIActorMenu {
 CGameObject* m_pActorInvOwner=nullptr;CGameObject* m_pPartnerInvOwner=nullptr;CGameObject* m_pInvBox=nullptr;
 unsigned hidden=0;void HideDialog(){++hidden;}void CheckDistance();
};
''' + distance + r'''
int main(){
 CGameObject actor,box,car,npc;box.id=500;box.pos.y=-50;car.id=501;objects[501]=&car;
 CUIActorMenu ui;ui.m_pActorInvOwner=&actor;ui.m_pInvBox=&box;
 ui.CheckDistance();assert(ui.hidden==1); // an ordinary distant box still closes
 NET_Packet grant{{244,1,245,1}};netcoop::client_trunk_open(grant);
 assert(netcoop::s_trunk_pending==500 && netcoop::s_trunk_pending_until==3100);
 assert(netcoop::s_box_anchor.at(500)==501);
 ui.hidden=0;ui.CheckDistance();assert(ui.hidden==0); // below-map trunk, nearby car
 car.pos.x=4;ui.CheckDistance();assert(ui.hidden==1);car.pos.x=0;
 car.destroyed=true;ui.CheckDistance();assert(ui.hidden==2);car.destroyed=false;
 objects.clear();ui.CheckDistance();assert(ui.hidden==3);objects[501]=&car;
 for(auto bytes:std::vector<std::vector<unsigned char>>{{},{1},{1,2,3},{1,2,3,4,5},{255,255},{244,1,244,1}}){
  NET_Packet invalid{bytes};netcoop::client_trunk_open(invalid);
  assert(netcoop::s_trunk_pending==500 && netcoop::s_box_anchor.at(500)==501);
 }
 NET_Packet legacy{{244,1}};netcoop::client_trunk_open(legacy);
 assert(netcoop::s_box_anchor.empty());ui.CheckDistance();assert(ui.hidden==4);
 ui.m_pInvBox=nullptr;ui.m_pPartnerInvOwner=&npc;npc.pos.x=4;
 ui.CheckDistance();assert(ui.hidden==5);npc.awareness=true;ui.CheckDistance();assert(ui.hidden==5);
 netcoop::s_box_anchor[500]=501;netcoop::s_vehicle_seats[501]=1;
 netcoop::s_vehicles_sv[501]=1;netcoop::s_vehicles_cl[501]=1;
 netcoop::s_vehicle_arrivals.push_back(1);netcoop::s_vehicle_conditions.push_back(1);
 netcoop::s_vehicle_hud[501]=99;netcoop::vehicles_reset();
 assert(netcoop::s_vehicle_hud.empty());
 assert(netcoop::s_box_anchor.empty() && netcoop::s_vehicle_seats.empty());
 assert(netcoop::s_vehicles_sv.empty() && netcoop::s_vehicles_cl.empty());
 assert(netcoop::s_vehicle_arrivals.empty() && netcoop::s_vehicle_conditions.empty());
 assert(netcoop::s_trunk_pending==0xffff && netcoop::s_trunk_pending_until==0);
 assert(!netcoop::s_vehicle_inbox_check && !netcoop::s_vehicle_keys && !netcoop::s_vehicle_keys_sent);
}
'''

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native fixture compiles only in GitHub Actions; no local compiler invocation.')
with TemporaryDirectory(prefix='trunk-reach-') as temporary:
    folder = Path(temporary)
    cpp = folder / 'trunk.cpp'
    exe = folder / ('trunk.exe' if os.name == 'nt' else 'trunk')
    cpp.write_text(source, encoding='utf-8')
    args = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:'+str(exe)]
            if os.name == 'nt' else
            ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(args, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
print('PASS real trunk packet/reach/menu/reset: nearby car, far/missing/destroyed anchor, legacy and malformed packets, NPC distance')
