"""CI-only real ignition input and authoritative entry/exit reservation."""
import os,subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
def method(file,name):
 s=(root/file).read_text(encoding='utf-8');a=s.index(name);b=s.index('{',a);e=b+1;depth=1
 while depth:depth+=(s[e]=='{')-(s[e]=='}');e+=1
 return s[a:e]
source=r'''#include <cassert>
#include <vector>
#include <cstdio>
using u8=unsigned char;using u16=unsigned short;using u32=unsigned;
constexpr u16 BI_NONE=65535;
struct Fvector{float x=0,y=0,z=0;};struct Fmatrix{Fvector c;void invert(const Fmatrix&m){c={-m.c.x,-m.c.y,-m.c.z};}void transform_tiny(Fvector&out,Fvector in){out={in.x+c.x,in.y+c.y,in.z+c.z};}};
struct Shell{void Enable(){}};
struct CCar{
 enum{netcoop_key_forward=1,netcoop_key_back=2,netcoop_key_left=4,netcoop_key_right=8,netcoop_key_handbrake=16};
 struct{bool on=false;}m_netcoop_heli;bool b_engine_on=false;u8 m_netcoop_keys=0;unsigned started=0,pressed[5]{},released[5]{},opens=0,closes=0;Shell shell;Fmatrix pose;
 Shell*PPhysicsShell(){return &shell;}void StartEngine(){++started;b_engine_on=true;}void Clutch(){}
 void PressForward(){++pressed[0];}void ReleaseForward(){++released[0];}void PressBack(){++pressed[1];}void ReleaseBack(){++released[1];}
 void PressLeft(){++pressed[2];}void ReleaseLeft(){++released[2];}void PressRight(){++pressed[3];}void ReleaseRight(){++released[3];}
 void PressBreaks(){++pressed[4];}void ReleaseBreaks(){++released[4];}void netcoop_drive(u8);
 Fmatrix&XFORM(){return pose;}u16 ID(){return 5;}u16 netcoop_nearest_entry_door(const Fvector&){return 10;}void DoorOpen(u16){++opens;}void DoorClose(u16){++closes;}
};
struct Motion{void invalidate(){}};
struct CActor{u8 m_netcoop_seat_phase=0;u32 m_netcoop_seat_phase_start=0;u16 m_netcoop_seat_door=BI_NONE;
 Fvector position,m_netcoop_seat_outside;Motion m_netcoop_seat_motion;bool m_netcoop_seat_driver=true,seated=false;
 Fvector&Position(){return position;}u16 ID(){return 7;}};
struct Seat{Fmatrix local;};struct VehicleSeats{std::vector<Seat>seats{Seat{},Seat{}};};
struct VehicleRuntime{std::vector<u16>seats{65535,65535};bool dirty=false;u8 keys=0;};
struct World{u32 now=1000;u32 timeServer(){return now;}}world;World&Level(){return world;}
bool exit_clear=true;unsigned reservations=0;
Fvector vehicle_exit_position(CCar*,const VehicleSeats&,const Seat&,bool*clear){*clear=exit_clear;return {2,0,0};}
void vehicle_seat_server(CCar*,VehicleRuntime&v,const VehicleSeats&,u8 i,CActor*a){v.seats[i]=a->ID();a->seated=true;++reservations;}
void Msg(const char*,...){}
'''+method('src/xrGame/Car.cpp','void CCar::netcoop_drive(')+method('src/xrGame/netcoop_vehicles.inc','static bool vehicle_transition(')+r'''
int main(){
 CCar car;car.netcoop_drive(1);car.netcoop_drive(2);assert(!car.started&&!car.pressed[0]&&!car.pressed[1]&&!car.m_netcoop_keys);
 car.netcoop_drive(4|16);assert(car.pressed[2]==1&&car.pressed[4]==1&&!car.started);
 car.netcoop_drive(0);assert(car.released[2]==1&&car.released[4]==1);
 car.netcoop_drive(1);car.StartEngine();car.netcoop_drive(1);assert(car.started==1&&car.pressed[0]==1);
 car.netcoop_drive(1);assert(car.pressed[0]==1);car.b_engine_on=false;car.netcoop_drive(1);assert(car.released[0]==1&&!car.m_netcoop_keys);
 CCar heli;heli.m_netcoop_heli.on=true;heli.netcoop_drive(16);assert(!heli.started); // collective is not ignition
 CActor actor;VehicleRuntime v;VehicleSeats poses;actor.position={-2,0,0};
 assert(vehicle_transition(&car,v,poses,0,&actor,false));assert(actor.seated&&v.seats[0]==7&&actor.m_netcoop_seat_phase==1&&car.opens==1);
 assert(actor.m_netcoop_seat_outside.x==-2&&actor.m_netcoop_seat_phase_start==1000);
 assert(!vehicle_transition(&car,v,poses,0,&actor,false)&&reservations==1); // repeat cannot reserve again
 actor.m_netcoop_seat_phase=0;exit_clear=false;assert(!vehicle_transition(&car,v,poses,0,&actor,true));assert(actor.seated&&actor.m_netcoop_seat_phase==0);
 exit_clear=true;assert(vehicle_transition(&car,v,poses,0,&actor,true));assert(actor.m_netcoop_seat_phase==2&&actor.m_netcoop_seat_outside.x==2&&v.seats[0]==7);
 assert(!vehicle_transition(&car,v,poses,2,&actor,true));
 puts("PASS actual vehicle controls/transitions: manual ignition, held pedal, stall release, steering/handbrake, helicopter collective, seat reservation, duplicate entry, blocked exit and delayed release");
}
'''
with TemporaryDirectory() as tmp:
 cpp=Path(tmp)/'vehicle.cpp';exe=Path(tmp)/('vehicle.exe' if os.name=='nt' else 'vehicle');cpp.write_text(source)
 cmd=['cl','/nologo','/std:c++17','/EHsc',str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else ['g++','-std=c++17','-fsanitize=address,undefined',str(cpp),'-o',str(exe)]
 subprocess.run(cmd,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True)
