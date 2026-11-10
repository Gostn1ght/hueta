"""CI-only actual optional prone mount loading, gating and world composition."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
text = (root/'src/xrGame/Weapon.cpp').read_text(encoding='utf-8')

def method(name):
    start=text.index(name);end=text.index('{',start)+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

source=r'''
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include <map>
#include <string>
using LPCSTR=const char*;
struct Fvector {
 float x=0,y=0,z=0;
 void set(Fvector v){*this=v;}
 float square_magnitude()const{return x*x+y*y+z*z;}
 float magnitude()const{return std::sqrt(square_magnitude());}
 float dotproduct(Fvector v)const{return x*v.x+y*v.y+z*v.z;}
};
struct Fmatrix {
 Fvector i{1,0,0},j{0,1,0},k{0,0,1},c;
 void identity(){*this=Fmatrix{};}
 Fvector rotate(Fvector v)const{return {i.x*v.x+j.x*v.y+k.x*v.z,i.y*v.x+j.y*v.y+k.y*v.z,i.z*v.x+j.z*v.y+k.z*v.z};}
 void mul(const Fmatrix&a,const Fmatrix&b){Fmatrix r;r.i=a.rotate(b.i);r.j=a.rotate(b.j);r.k=a.rotate(b.k);r.c=a.rotate(b.c);r.c.x+=a.c.x;r.c.y+=a.c.y;r.c.z+=a.c.z;*this=r;}
};
float DET(const Fmatrix&m){return m.i.x*(m.j.y*m.k.z-m.j.z*m.k.y)-m.j.x*(m.i.y*m.k.z-m.i.z*m.k.y)+m.k.x*(m.i.y*m.j.z-m.i.z*m.j.y);}
float _abs(float x){return std::abs(x);}bool fis_zero(float x){return std::abs(x)<.000001f;}
bool _valid(Fvector v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
bool _valid(const Fmatrix&m){return _valid(m.i)&&_valid(m.j)&&_valid(m.k)&&_valid(m.c);}
#define VERIFY(x) assert(x)
void Msg(LPCSTR,...){ }
struct Ini{std::map<std::string,Fvector> rows;bool line_exist(LPCSTR,LPCSTR key){return rows.count(key)!=0;}Fvector r_fvector3(LPCSTR,LPCSTR key){return rows.at(key);}}ini;
Ini*pSettings=&ini;
struct Entity{virtual ~Entity()=default;};
struct Motion{bool present=true;bool valid()const{return present;}};
struct CActor:Entity{bool alive=true,seated=false,m_netcoop_prone_launcher_authored=true;Motion m_netcoop_prone_motion;bool g_Alive()const{return alive;}bool netcoop_seated()const{return seated;}};
template<class T,class U>T smart_cast(U*value){return dynamic_cast<T>(value);}
namespace netcoop{bool client=true;bool pure_client(){return client;}}
struct CWeapon {
 Entity*parent=nullptr;bool m_netcoop_prone_offset_valid=false,m_strapped_mode=false;
 Fmatrix m_netcoop_prone_offset,m_Offset,m_StrapOffset;
 struct{Fmatrix xform;}renderable;
 Entity*H_Parent()const{return parent;}Fvector position;
 Fvector&Position(){return position;}Fmatrix&XFORM(){return renderable.xform;}
 void netcoop_load_prone_attachment(LPCSTR);bool netcoop_prone_attachment_active()const;void UpdatePosition(const Fmatrix&);
};
'''+''.join(method(name) for name in (
    'void CWeapon::netcoop_load_prone_attachment(',
    'bool CWeapon::netcoop_prone_attachment_active() const',
    'void CWeapon::UpdatePosition('))+r'''
int main(){
 CActor actor;CWeapon weapon;weapon.parent=&actor;weapon.m_Offset.c={1,2,3};weapon.m_StrapOffset.c={4,5,6};Fmatrix world;world.i={0,0,-1};world.k={1,0,0};world.c={10,20,30};
 weapon.netcoop_load_prone_attachment("rpg");assert(!weapon.m_netcoop_prone_offset_valid);weapon.UpdatePosition(world);assert(weapon.XFORM().c.x==13&&weapon.XFORM().c.y==22&&weapon.XFORM().c.z==29);
 ini.rows={{"netcoop_prone_right",{1,0,0}},{"netcoop_prone_up",{0,1,0}},{"netcoop_prone_forward",{0,0,1}},{"netcoop_prone_position",{.1f,.2f,.3f}}};
 weapon.netcoop_load_prone_attachment("rpg");assert(weapon.netcoop_prone_attachment_active());weapon.UpdatePosition(world);assert(std::abs(weapon.XFORM().c.x-10.3f)<.0001f&&std::abs(weapon.XFORM().c.z-29.9f)<.0001f&&weapon.Position().x==10);
 actor.m_netcoop_prone_launcher_authored=false;assert(!weapon.netcoop_prone_attachment_active());actor.m_netcoop_prone_launcher_authored=true;
 actor.m_netcoop_prone_motion.present=false;assert(!weapon.netcoop_prone_attachment_active());actor.m_netcoop_prone_motion.present=true;
 actor.alive=false;assert(!weapon.netcoop_prone_attachment_active());actor.alive=true;actor.seated=true;assert(!weapon.netcoop_prone_attachment_active());actor.seated=false;
 netcoop::client=false;assert(!weapon.netcoop_prone_attachment_active());netcoop::client=true;
 weapon.m_strapped_mode=true;assert(!weapon.netcoop_prone_attachment_active());weapon.UpdatePosition(world);assert(weapon.XFORM().c.x==16);weapon.m_strapped_mode=false;
 Entity npc;weapon.parent=&npc;assert(!weapon.netcoop_prone_attachment_active());weapon.parent=nullptr;assert(!weapon.netcoop_prone_attachment_active());weapon.parent=&actor;
 for(Fvector invalid: {Fvector{0,0,0},Fvector{2,0,0},Fvector{0,1,0},Fvector{std::numeric_limits<float>::quiet_NaN(),0,0},Fvector{std::numeric_limits<float>::infinity(),0,0}}){ini.rows["netcoop_prone_right"]=invalid;weapon.netcoop_load_prone_attachment("rpg");assert(!weapon.m_netcoop_prone_offset_valid);}
 ini.rows["netcoop_prone_right"]={1,0,0};ini.rows.erase("netcoop_prone_forward");weapon.netcoop_load_prone_attachment("rpg");assert(!weapon.m_netcoop_prone_offset_valid);
 std::puts("PASS actual optional prone mount: complete rigid basis, finite bounded data, world composition, no effect on legacy clips/standing/dead/seated/NPC/server/strapped weapons");
}
'''
with TemporaryDirectory(prefix='prone-mount-native-') as temporary:
    folder=Path(temporary);cpp=folder/'mount.cpp';exe=folder/'mount.exe';cpp.write_text(source,encoding='utf-8')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)],cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=15)
