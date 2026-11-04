"""CI-only execution of actual car pedals, gearbox, parking and auto-reverse."""
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]


def method(name):
    source = (root / 'src/xrGame/Car.cpp').read_text(encoding='utf-8')
    start = source.index(name)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


source = r'''
#include <cassert>
#include <cmath>
#include <algorithm>
#include <array>
#include <limits>
#include <vector>
#include <cstdio>
using u8=unsigned char;using u32=unsigned;using std::size_t;
template<class T>using xr_vector=std::vector<T>;
template<class T>T _min(T a,T b){return std::min(a,b);}
#define VERIFY2(x,msg) assert(x)
constexpr float EPS=.00001f;
struct Fvector{float x=0,y=0,z=0;float square_magnitude()const{return x*x+y*y+z*z;}
 float dotproduct(Fvector b)const{return x*b.x+y*b.y+z*b.z;}};
bool _valid(Fvector v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
struct {u32 dwTimeGlobal=1000;float fTimeGlobal=1;}Device;
namespace netcoop{bool active=true;bool enabled(){return active;}}
struct Shell{Fvector v;void get_LinearVel(Fvector&o){o=v;}void Enable(){}};
struct CCar{
 struct {bool on=false,pilot=false;}m_netcoop_heli;
 bool m_netcoop_parking=true,brp=false,fwp=false,bkp=false,b_breaks=false;
 bool b_engine_on=false,b_clutch=false,b_auto_switch_transmission=true,b_transmission_switching=false;
 bool driving=false,parked=true,m_netcoop_lights=false;u32 m_netcoop_shift_at=0;
 float m_current_rpm=0,m_current_engine_power=0,m_min_rpm=850,m_break_start=0,m_break_time=.5f;
 float simulated_rpm=2000;size_t gear=1;unsigned auto_up=0,auto_down=0,started=0;
 Shell shell;Shell*m_pPhysicsShell=&shell;
 struct WheelBreak{float last=-1;void Break(float k){last=k;}};
 struct WheelDrive{unsigned updates=0;void UpdatePower(){++updates;}};
 xr_vector<WheelBreak>m_breaking_wheels{WheelBreak{}};
 xr_vector<WheelDrive>m_driving_wheels{WheelDrive{}};
 xr_vector<std::array<float,3>>m_gear_ratious{{-1,1000,3000},{1,1000,3000},{2,1000,3000},{3,1000,3000}};
 struct {void SwitchHeadLights(){}}m_lights;
 struct Matrix{Fvector k{0,0,1};}matrix;Matrix&XFORM(){return matrix;}
 Shell*PPhysicsShell(){return m_pPhysicsShell;}
 void Clutch(){b_clutch=true;}void Unclutch(){b_clutch=false;}
 void Drive(){if(b_clutch&&b_engine_on)driving=true;}
 void NeutralDrive(){driving=false;}
 void StartBreaking(){b_breaks=true;m_break_start=Device.fTimeGlobal;}
 void StopBreaking(){b_breaks=false;}
 void HandBreak(){parked=true;}void ReleaseHandBreak(){parked=false;}
 void Starter(){++started;}void StartEngine(){++started;b_engine_on=true;}
 void StopEngine(){b_engine_on=false;driving=false;}
 void DriveForward(){Clutch();if(gear==0)Transmission(1);Starter();Drive();}
 void DriveBack(){Clutch();Transmission(0);Starter();Drive();}
 size_t CurrentTransmission()const{return gear;}
 void Transmission(size_t g){assert(g<m_gear_ratious.size());gear=g;Drive();}
 void TransmissionUp(){++auto_up;}void TransmissionDown(){++auto_down;}
 float EngineDriveSpeed(){return simulated_rpm;}float EnginePower(){return 1;}
 void processing_activate(){}void netcoop_drive(u8){fwp=false;bkp=false;brp=false;}
 void ResetKeys(){fwp=false;bkp=false;brp=false;}void netcoop_heli_toggle_gear(){}
 bool netcoop_manual_controls()const;void netcoop_shift(bool);void netcoop_toggle(u8);void netcoop_engage(bool);
 void PressForward();void PressBack();void PressBreaks();void ReleaseForward();void ReleaseBack();void ReleaseBreaks();
 void UpdatePower();void UpdateBack();
};
''' + '\n'.join(method(name) for name in [
    'bool CCar::netcoop_manual_controls()', 'void CCar::netcoop_shift(',
    'void CCar::netcoop_toggle(', 'void CCar::netcoop_engage(',
    'void CCar::PressForward()', 'void CCar::PressBack()', 'void CCar::PressBreaks()',
    'void CCar::ReleaseForward()', 'void CCar::ReleaseBack()', 'void CCar::ReleaseBreaks()',
    'void CCar::UpdatePower()', 'void CCar::UpdateBack()',
]) + r'''
int main(){
 CCar c;c.netcoop_engage(true);assert(c.parked&&c.m_netcoop_parking&&!c.driving);
 c.PressForward();assert(!c.b_engine_on&&!c.driving&&!c.started); // ignition is explicit
 c.netcoop_toggle(0);assert(c.b_engine_on&&!c.driving);
 c.netcoop_toggle(5);assert(!c.m_netcoop_parking&&!c.parked&&c.driving);
 c.ReleaseForward();assert(!c.driving&&c.gear==1);
 c.netcoop_shift(true);assert(c.gear==2);
 c.netcoop_shift(true);assert(c.gear==2);Device.dwTimeGlobal+=200;
 c.netcoop_shift(true);assert(c.gear==3);Device.dwTimeGlobal+=200;
 c.netcoop_shift(true);assert(c.gear==3);
 c.PressForward();assert(c.gear==3&&c.driving);
 c.PressBack();assert(c.b_breaks&&!c.driving);c.ReleaseForward();assert(c.gear==3&&c.b_breaks);
 Device.fTimeGlobal+=1;c.UpdateBack();assert(c.gear==3&&c.b_breaks&&c.m_breaking_wheels[0].last==1);
 c.ReleaseBack();assert(!c.b_breaks&&c.gear==3&&!c.driving);
 c.PressBack();c.PressForward();assert(!c.driving);c.ReleaseBack();assert(c.driving&&c.gear==3);
 c.netcoop_toggle(5);assert(c.m_netcoop_parking&&c.parked&&!c.driving);
 c.ReleaseForward();c.PressForward();assert(c.parked&&!c.driving); // latch survives key release
 c.netcoop_toggle(5);assert(c.driving&&!c.parked);
 c.PressBreaks();assert(!c.driving&&c.parked);c.ReleaseBreaks();assert(c.driving&&!c.parked);
 c.netcoop_toggle(5);c.PressBreaks();c.ReleaseBreaks();assert(c.parked&&c.m_netcoop_parking&&!c.driving);
 c.netcoop_toggle(5);c.netcoop_toggle(0);assert(!c.b_engine_on);
 c.PressBack();c.UpdateBack();assert(c.b_breaks&&!c.driving&&c.gear==3); // engine-off braking
 c.ReleaseBack();c.ReleaseForward();
 // No engine speed is permitted to change a manually selected gear.
 c.simulated_rpm=5000;c.UpdatePower();c.simulated_rpm=100;c.UpdatePower();
 assert(!c.auto_up&&!c.auto_down&&c.gear==3&&c.m_driving_wheels[0].updates==2);
 c.gear=1;Device.dwTimeGlobal+=200;c.shell.v={0,0,1};c.netcoop_shift(false);assert(c.gear==1);
 c.shell.v={0,0,0};c.netcoop_shift(false);assert(c.gear==0);Device.dwTimeGlobal+=200;
 c.netcoop_shift(false);assert(c.gear==0);
 c.shell.v={0,0,-1};c.netcoop_shift(true);assert(c.gear==0);
 c.shell.v={std::numeric_limits<float>::quiet_NaN(),0,0};c.netcoop_shift(true);assert(c.gear==0);
 c.shell.v={0,0,0};c.netcoop_toggle(0);c.PressForward();assert(c.gear==0&&c.driving); // W in deliberate R
 c.ReleaseForward();assert(c.gear==0);c.netcoop_shift(true);assert(c.gear==1);
 c.netcoop_engage(false);assert(c.m_netcoop_parking&&c.parked&&!c.driving&&!c.b_engine_on);
 c.gear=999;Device.dwTimeGlobal+=200;c.netcoop_shift(false);assert(c.gear==999);
 c.m_gear_ratious.clear();c.netcoop_shift(true);assert(c.gear==999);
 CCar heli;heli.m_netcoop_heli.on=true;heli.netcoop_toggle(5);assert(heli.m_netcoop_parking);
 heli.netcoop_shift(true);assert(heli.gear==1);heli.netcoop_engage(true);assert(!heli.parked);
 netcoop::active=false;CCar sp;sp.netcoop_shift(true);assert(sp.gear==1);
 sp.simulated_rpm=4000;sp.UpdatePower();assert(sp.auto_up==1);sp.simulated_rpm=500;sp.UpdatePower();assert(sp.auto_down==1);
 sp.PressBack();sp.UpdateBack();assert(sp.gear==0); // original SP auto reverse retained
 puts("PASS actual manual transmission, independent pedals, latched parking, standstill reverse, ignition, helicopter/SP controls");
}
'''
with TemporaryDirectory() as tmp:
    cpp = Path(tmp) / 'manual.cpp'
    exe = Path(tmp) / ('manual.exe' if os.name == 'nt' else 'manual')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', str(cpp), '/Fe:'+str(exe)] if os.name == 'nt' else
               ['g++', '-std=c++17', '-fsanitize=address,undefined', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=tmp, check=True)
    subprocess.run([str(exe)], cwd=tmp, check=True, timeout=15)
