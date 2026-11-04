"""CI-only real wheel brake/ignition and loaded-engine stall boundaries."""
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]


def method(file, name):
    source = (root / file).read_text(encoding='utf-8')
    start = source.index(name)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


physics = method('src/xrGame/Car.cpp', 'void CCar::PhDataUpdate(')
assert physics.index('UpdatePower();') < physics.index('netcoop_vehicle_dynamics::stall_due(')
assert physics.index('UpdatePower();') < physics.index('if (brp || (netcoop::enabled() && netcoop_parking_brake()))')
assert physics.index('if (netcoop::pure_client())') < physics.index('netcoop_vehicle_dynamics::stall_due(')
source = r'''
#include <cassert>
#include <limits>
#include <vector>
#include <cstdio>
#include "netcoop_vehicle_dynamics.h"
namespace netcoop {bool active=true;bool enabled(){return active;}}
struct {unsigned dwTimeGlobal=12345;} Device;
struct Shell{float mass=1000;float getMass(){return mass;}};
struct Sound{void Start(){}};
struct CCar{
 Shell shell;Sound sound;Sound*m_car_sound=&sound;
 float m_fuel=1,m_current_rpm=0,m_netcoop_low_rpm_seconds=0;bool b_engine_on=false,b_starting=false;unsigned m_dwStartTime=0;
 struct Wheel{CCar*car=nullptr;float radius=.35f,last_torque=-1,last_speed=-1;void ApplyDriveAxisVelTorque(float speed,float torque){last_speed=speed;last_torque=torque;}};
 struct SWheelBreak{Wheel*pwheel;float hand_break_torque=.018f;void HandBreak();};
 std::vector<SWheelBreak>m_breaking_wheels;
 Shell*PPhysicsShell(){return &shell;}float EffectiveGravity(){return 9.81f;}
 void PlayExhausts(){}void Starter();void StartEngine();
};
constexpr float EPS=.0001f;
''' + method('src/xrGame/Car.cpp', 'void CCar::Starter()') + method('src/xrGame/Car.cpp', 'void CCar::StartEngine()') + method('src/xrGame/CarWheels.cpp', 'void CCar::SWheelBreak::HandBreak()') + r'''
int main(){
 using namespace netcoop_vehicle_dynamics;
 CCar car;CCar::Wheel wheel;wheel.car=&car;car.m_breaking_wheels={{&wheel},{&wheel}};
 car.m_breaking_wheels[0].HandBreak();assert(wheel.last_speed==0&&std::abs(wheel.last_torque-1800)<.01f);
 car.shell.mass=10000;wheel.radius=.6f;car.m_breaking_wheels[0].HandBreak();
 assert(std::abs(wheel.last_torque-29430)<.02f);
 netcoop::active=false;car.m_breaking_wheels[0].HandBreak();assert(std::abs(wheel.last_torque-1800)<.01f);
 assert(parking_torque(true,40000,10000,9.81f,.6f,2)==40000); // strong donor brakes retained
 assert(parking_torque(true,123,1000,9.81f,.4f,0)==123);
 assert(parking_torque(true,123,-1,9.81f,.4f,2)==123);
 assert(parking_torque(true,123,1000,9.81f,std::numeric_limits<float>::quiet_NaN(),2)==123);
 float low=0;
 // Near-idle rounding must NEVER accumulate a stall, however long it lasts.
 for(int i=0;i<6000;++i)assert(!stall_due(true,true,false,false,true,false,899,1000,.01f,low));
 assert(low==0);
 assert(!stall_due(true,true,false,false,true,false,0,1000,.02f,low));
 assert(!stall_due(true,true,false,false,true,false,1000,1000,.02f,low)&&low==0);
 for(int i=0;i<74;++i)assert(!stall_due(true,true,false,false,true,false,300,1000,.01f,low));
 assert(stall_due(true,true,false,false,true,false,300,1000,.02f,low));
 assert(!stall_due(true,true,false,false,false,false,0,1000,.1f,low)&&low==0); // unloaded clutch
 assert(!stall_due(true,true,false,false,true,true,0,1000,.1f,low)&&low==0); // neutral
 assert(!stall_due(true,true,false,false,true,false,0,1000,5.f,low)&&low<=.1f); // one long hitch
 assert(!stall_due(true,true,true,false,true,false,0,1000,.1f,low)&&low==0); // cranking
 assert(!stall_due(true,true,false,true,true,false,0,1000,.1f,low)&&low==0); // governed
 assert(!stall_due(true,false,false,false,true,false,0,1000,.1f,low)&&low==0);
 assert(stall_due(false,true,false,false,true,false,999,1000,.01f,low)); // original SP threshold
 car.m_netcoop_low_rpm_seconds=1;car.m_dwStartTime=1;car.StartEngine();
 assert(car.b_engine_on&&car.b_starting&&car.m_dwStartTime==Device.dwTimeGlobal&&car.m_netcoop_low_rpm_seconds==0);
 CCar dry;dry.m_fuel=0;dry.StartEngine();assert(!dry.b_engine_on);
 puts("PASS actual car ignition/wheel brake and sustained stall boundaries: no near-idle flicker stall, truck mass-scaled joint torque, parked brake reapplied after drive torque, client/SP preserved");
}
'''
with TemporaryDirectory() as temporary:
    cpp = Path(temporary) / 'vehicle.cpp'
    exe = Path(temporary) / ('vehicle.exe' if os.name == 'nt' else 'vehicle')
    cpp.write_text(source, encoding='utf-8')
    include = str(root / 'src/xrGame')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/I'+include, str(cpp), '/Fe:'+str(exe)] if os.name == 'nt' else
               ['g++', '-std=c++17', '-fsanitize=address,undefined', '-I', include, str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=temporary, check=True)
    subprocess.run([str(exe)], cwd=temporary, check=True, timeout=15)
