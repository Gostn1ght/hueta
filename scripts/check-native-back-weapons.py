"""CI-only actual weapon/owner bodies and actual xrCore affine matrix methods."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def method(text, signature):
    start = text.index(signature)
    begin = text.index('{', start)
    depth = 1
    end = begin + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


weapon = (ROOT/'src/xrGame/Weapon.cpp').read_text(encoding='utf-8')
owner = (ROOT/'src/xrGame/InventoryOwner.cpp').read_text(encoding='utf-8')
matrix = (ROOT/'src/xrCore/_matrix.h').read_text(encoding='utf-8')
assert 'dwXF_Frame = dwFP_Frame = u32(-1);' in weapon
actual_math = '\n'.join(method(matrix, signature) for signature in (
    'ICF SelfRef set(const Tvector& R,', 'ICF SelfRef identity(', 'ICF SelfRef mul(const Self& A,', 'ICF SelfRef mul_43(',
    'IC SelfRef invert(const Self& a)', 'ICF void transform_dir(Tvector& dest, const Tvector& v) const',
    'ICF void transform_tiny(Tvector& dest, const Tvector& v) const'))
source = r'''
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>
#ifdef _MSC_VER
#pragma warning(disable:4201)
#endif
using u16=uint16_t;using u32=uint32_t;using BOOL=bool;
constexpr bool TRUE=true,FALSE=false;constexpr u16 BI_NONE=u16(-1);
constexpr u16 INV_SLOT_2=2,INV_SLOT_3=3,BACKPACK_SLOT=13,eItemPlaceSlot=1;
constexpr float flt_zero=1e-6f;
#define IC inline
#define ICF inline
#define VERIFY(x) assert(x)
float _abs(float x){return std::fabs(x);}bool fis_zero(float x){return std::fabs(x)<1e-6f;}
struct Fvector{
 float x,y,z;
 Fvector& set(float a,float b,float c){x=a;y=b;z=c;return *this;}
 Fvector& set(const Fvector& v){*this=v;return *this;}
 Fvector& sub(const Fvector& a,const Fvector& b){return set(a.x-b.x,a.y-b.y,a.z-b.z);}
 Fvector& crossproduct(const Fvector& a,const Fvector& b){return set(a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x);}
 float square_magnitude()const{return x*x+y*y+z*z;}float magnitude()const{return std::sqrt(square_magnitude());}
 Fvector& normalize(){float n=magnitude();assert(n>0);x/=n;y/=n;z/=n;return *this;}
};
bool _valid(const Fvector& v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
struct Fmatrix{
 using T=float;using Self=Fmatrix;using SelfRef=Fmatrix&;using Tvector=Fvector;
 union{struct{Fvector i;float _14_;Fvector j;float _24_;Fvector k;float _34_;Fvector c;float _44_;};
 struct{float _11,_12,_13,_14,_21,_22,_23,_24,_31,_32,_33,_34,_41,_42,_43,_44;};float m[4][4];};
 Fmatrix(){identity();}
''' + actual_math + r'''
 void mulA_43(const Fmatrix& a){Fmatrix b=*this;mul_43(a,b);}
};
bool _valid(const Fmatrix& m){return _valid(m.i)&&_valid(m.j)&&_valid(m.k)&&_valid(m.c);}
float determinant(const Fmatrix& m){Fvector v;v.crossproduct(m.j,m.k);return m.i.x*v.x+m.i.y*v.y+m.i.z*v.z;}
#define DET(m) determinant(m)
bool near(const Fvector& a,const Fvector& b){return std::fabs(a.x-b.x)<.002f&&std::fabs(a.y-b.y)<.002f&&std::fabs(a.z-b.z)<.002f;}
Fvector add(Fvector a,Fvector b){return {a.x+b.x,a.y+b.y,a.z+b.z};}
Fmatrix rotate(float angle){Fmatrix m;float c=std::cos(angle),s=std::sin(angle);m.i={c,s,0};m.j={-s,c,0};return m;}
struct Fbox{Fvector center{.2f,.3f,.4f},half{.1f,.2f,.5f};void get_CD(Fvector& c,Fvector& h){c=center;h=half;}};
struct VisData{Fbox box;};
struct IRenderVisual{virtual ~IRenderVisual()=default;VisData vis;VisData& getVisData(){return vis;}};
struct Bone{Fmatrix bind_transform,pose;u16 parent=BI_NONE;u16 GetParentID(){return parent;}};
struct IKinematics:IRenderVisual{
 std::vector<Bone> bones=std::vector<Bone>(2);u16 spine=1;unsigned calculations=0;
 u16 LL_BoneID(const char*){return spine;}u16 LL_BoneCount(){return u16(bones.size());}
 Bone& LL_GetData(u16 n){return bones.at(n);}Fmatrix& LL_GetTransform(u16 n){return bones.at(n).pose;}
 void CalculateBones(bool){++calculations;}void CalculateBones_Invalidate(){}
};
struct CObject{virtual ~CObject()=default;CObject* owner_ref=nullptr;IRenderVisual* visual=nullptr;Fmatrix pose;bool destroyed=false;
 struct RenderData{Fmatrix& xform;explicit RenderData(Fmatrix& value):xform(value){}}renderable{pose};
 CObject* H_Parent()const{return owner_ref;}IRenderVisual* Visual()const{return visual;}Fmatrix& XFORM(){return pose;}
 const Fmatrix& XFORM()const{return pose;}bool getDestroy()const{return destroyed;}
};
template<class T,class U>T smart_cast(U* p){return dynamic_cast<T>(p);}
struct CInventoryItem:CObject{struct CInventory* m_pInventory=nullptr;u16 slot=3,place=1;
 u16 CurrPlace()const{return place;}u16 CurrSlot()const{return slot;}virtual void renderable_Render(){}};
using PIItem=CInventoryItem*;using TIItemContainer=std::vector<PIItem>;
struct CInventory{PIItem slots[14]={},active=nullptr;TIItemContainer m_all;
 PIItem ItemFromSlot(u16 n)const{return slots[n];}PIItem ActiveItem()const{return active;}};
namespace netcoop{bool active=true;bool enabled(){return active;}bool pure_client(){return active;}}
struct CAttachmentOwner{virtual ~CAttachmentOwner()=default;bool custom=false;unsigned attached_draws=0;
 bool attached(const CInventoryItem*)const{return custom;}void renderable_Render(){++attached_draws;}};
struct CInventoryOwner:CAttachmentOwner{CInventory inv;bool simplified=false;
 CInventory& inventory(){return inv;}const CInventory& inventory()const{return inv;}
 bool use_simplified_visual()const{return simplified;}void renderable_Render();};
struct CEntityAlive:CObject{bool alive=true;bool g_Alive()const{return alive;}virtual void g_WeaponBones(int& l,int& r,int& r2){l=1;r=0;r2=1;}};
struct CActor:CEntityAlive,CInventoryOwner{};
struct CAI_Stalker:CEntityAlive,CInventoryOwner{bool strap=false;void g_WeaponBones(int&,int&,int&)override;};
struct CCustomDevice:CInventoryItem{bool IsHidden(){return true;}void renderable_Render(){}};
struct WeaponBase:CInventoryItem{unsigned normal_draws=0;void renderable_Render(){++normal_draws;}};
struct CWeapon:WeaponBase{
 using inherited=WeaponBase;bool m_netcoop_back_mode=false,m_netcoop_back_valid=false,m_strapped_mode=false,can_strap=true,single=false;
 Fmatrix m_Offset,m_StrapOffset,m_netcoop_prone_offset;u32 dwXF_Frame=u32(-1);int capacity=30,state=0;unsigned draws=0,lights=0,hud_calls=0;
 bool netcoop_prone_attachment_active()const{return false;}bool netcoop_back_carried()const;bool netcoop_back_transform(Fmatrix&)const;void UpdateXForm();void UpdatePosition(const Fmatrix&);void renderable_Render();
 int GetAmmoMagSize()const{return capacity;}bool can_be_strapped()const{return can_strap;}bool strapped_mode()const{return m_strapped_mode;}
 bool IsSingleHanded()const{return single;}int GetState(){return state;}int HandDependence(){return 1;}
 Fvector& Position(){return pose.c;}void RenderLight(){++lights;}bool IsZoomed(){return false;}bool IsRotatingToZoom(){return false;}
 bool ZoomTexture(){return false;}void RenderHud(bool){++hud_calls;}void on_renderable_Render(){++draws;}
};
constexpr int hd1Hand=1,eReload=1;
bool IsGameTypeSingle(){return true;}
void CAI_Stalker::g_WeaponBones(int& l,int& r,int& r2){CEntityAlive::g_WeaponBones(l,r,r2);
 if(auto* w=smart_cast<CWeapon*>(inventory().ActiveItem()))w->m_strapped_mode=strap;}
struct{u32 dwFrame=1;}Device;
''' + '\n'.join(method(weapon, signature) for signature in (
    'bool CWeapon::netcoop_back_carried()', 'bool CWeapon::netcoop_back_transform(',
    'void CWeapon::UpdateXForm()', 'void CWeapon::renderable_Render()', 'void CWeapon::UpdatePosition(')) + '\n' + method(owner, 'void CInventoryOwner::renderable_Render()') + r'''
void equip(CEntityAlive& entity,CInventoryOwner& owner,CWeapon& w,IRenderVisual& model,u16 slot){
 w.owner_ref=&entity;w.visual=&model;w.slot=slot;w.place=eItemPlaceSlot;w.m_pInventory=&owner.inv;owner.inv.slots[slot]=&w;}
void setup(IKinematics& skeleton,Fmatrix delta){
 skeleton.bones[0].bind_transform=rotate(.3f);skeleton.bones[0].bind_transform.c={0,.5f,0};
 skeleton.bones[1].bind_transform=rotate(1.5707963f);skeleton.bones[1].bind_transform.c={0,.8f,0};skeleton.bones[1].parent=0;
 Fmatrix global;global.mul_43(skeleton.bones[0].bind_transform,skeleton.bones[1].bind_transform);
 skeleton.bones[1].pose.mul_43(delta,global);skeleton.bones[0].pose=skeleton.bones[0].bind_transform;
}
int main(){
 CActor actor;CAI_Stalker npc;IKinematics skeleton;IRenderVisual models[2];CWeapon left,right;
 Fmatrix delta=rotate(.4f);setup(skeleton,delta);actor.visual=npc.visual=&skeleton;
 actor.pose=rotate(.8f);actor.pose.c={1000,40,-900};
 equip(actor,actor,left,models[0],INV_SLOT_2);equip(actor,actor,right,models[1],INV_SLOT_3);
 assert(left.netcoop_back_carried()&&right.netcoop_back_carried());
 for(unsigned i=0;i<100;++i){
  models[0].vis.box.center={float(i%7)*.3f-1,float(i%9)*.2f-.8f,float(i%5)*.4f-1};
  models[0].vis.box.half.z=.2f+float(i%8)*.1f;
  Fmatrix back;assert(left.netcoop_back_transform(back));Fvector actual,offset,expected;
  back.transform_tiny(actual,models[0].vis.box.center);
  // Highest rotated corner stays at shoulder+12cm, whatever model length.
  const auto half=models[0].vis.box.half;
  const float y=.12f-half.z*.968245837f-half.x*.25f;
  delta.transform_dir(offset,Fvector{-.14f,y,-.14f});
  actor.XFORM().transform_tiny(expected,add(skeleton.bones[1].pose.c,offset));
  assert(near(actual,expected));assert(std::fabs(DET(back)-1.f)<.001f);
 }
 Fmatrix a,b;assert(left.netcoop_back_transform(a)&&right.netcoop_back_transform(b));
 Fvector ac,bc;a.transform_tiny(ac,models[0].vis.box.center);b.transform_tiny(bc,models[1].vis.box.center);
 Fvector distance;distance.sub(ac,bc);assert(distance.magnitude()>.27f);
 actor.renderable_Render();assert(left.draws==1&&right.draws==1&&left.lights==0&&left.hud_calls==0);
 assert(actor.attached_draws==1&&left.state==0&&right.state==0);
 // A moved torso/world in the same frame must not reuse a hand/frame cache.
 actor.pose.c.x+=50;left.renderable_Render();Fvector shifted;left.pose.transform_tiny(shifted,models[0].vis.box.center);
 ac.x+=50;assert(near(shifted,ac));
 actor.inv.active=&left;left.m_strapped_mode=true;left.renderable_Render();
 assert(!left.m_netcoop_back_mode&&!left.m_strapped_mode&&left.lights==1&&left.hud_calls==1);
 actor.inv.active=nullptr;left.renderable_Render();assert(left.m_netcoop_back_mode&&left.lights==1);
 CInventoryItem backpack;actor.inv.slots[BACKPACK_SLOT]=&backpack;
 assert(right.netcoop_back_transform(b));b.transform_tiny(bc,models[1].vis.box.center);
 // Owner 2026-10-17: the backpack no longer moves the guns.
 actor.inv.slots[BACKPACK_SLOT]=nullptr;assert(right.netcoop_back_transform(a));a.transform_tiny(ac,models[1].vis.box.center);
 assert(near(bc,ac));
 left.single=true;assert(left.netcoop_back_transform(a));
 // Refusals hide an invalid attachment instead of rendering its old transform.
 skeleton.spine=BI_NONE;auto before=left.draws;left.renderable_Render();assert(left.draws==before&&!left.m_netcoop_back_valid);
 skeleton.spine=1;skeleton.bones[1].parent=1;assert(!left.netcoop_back_transform(a));setup(skeleton,delta);
 skeleton.bones[0].bind_transform.i={0,0,0};assert(!left.netcoop_back_transform(a));setup(skeleton,delta);
 models[0].vis.box.center.x=std::numeric_limits<float>::quiet_NaN();assert(!left.netcoop_back_transform(a));models[0].vis.box.center={};
 models[0].vis.box.half.z=20;assert(!left.netcoop_back_transform(a));models[0].vis.box.half.z=.5f;
 left.place=2;assert(!left.netcoop_back_carried());left.place=1;
 left.capacity=0;assert(!left.netcoop_back_carried());left.capacity=30;
 left.destroyed=true;assert(!left.netcoop_back_carried());left.destroyed=false;
 actor.alive=false;assert(!left.netcoop_back_carried());actor.alive=true;
 actor.custom=true;assert(!left.netcoop_back_carried());actor.custom=false;
 left.m_pInventory=&npc.inv;assert(!left.netcoop_back_carried());left.m_pInventory=&actor.inv;
 netcoop::active=false;assert(!left.netcoop_back_carried());netcoop::active=true;
 // NPC selected/strapped versus selected/unstrapped, with cached bad strap
 // offsets deliberately far away; the stable body anchor must ignore them.
 actor.inv.slots[2]=nullptr;left.single=false;equip(npc,npc,left,models[0],2);npc.inv.active=&left;
 left.m_StrapOffset.c={900,900,900};npc.pose.c={-200,5,600};npc.strap=true;
 left.renderable_Render();assert(left.m_netcoop_back_mode&&left.m_netcoop_back_valid);
 npc.strap=false;left.renderable_Render();assert(!left.m_netcoop_back_mode);
 npc.strap=true;left.renderable_Render();assert(left.m_netcoop_back_mode);
 std::puts("PASS actual back weapon/owner bodies with xrCore matrix math: stable animated bind frame, model centering, distinct slots, same-frame movement, NPC strap/hand switch, player hand exclusion, shoulder mount independent of the backpack and invalid-data refusal");
}
'''
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native compilation is permitted only in GitHub Actions')
with TemporaryDirectory(prefix='back-weapons-') as temporary:
    folder = Path(temporary)
    cpp, exe = folder/'back.cpp', folder/('back.exe' if os.name == 'nt' else 'back')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/utf-8', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:'+str(exe)] if os.name == 'nt' else
               ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True, timeout=10)
