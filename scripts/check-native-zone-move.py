"""Actual script anomaly movement and hit-contact gate, using engine boundary doubles."""
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks run only in Windows GitHub Actions")
root = Path(__file__).resolve().parents[1] / "src/xrGame"
zone = (root / "CustomZone.cpp").read_text(encoding="utf-8")
restr = (root / "space_restrictor.cpp").read_text(encoding="utf-8")
assert "m_script_moved_since_touch = false;\n\t\tfeel_touch_update(" in zone
script_entry = (root / "script_game_object3.cpp").read_text(encoding="latin-1")
assert "zone->MoveScript(pos);" in script_entry[script_entry.index("void CScriptGameObject::MoveAnomaly("):][:400]


def method(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


methods = "\n".join((
    method(restr, "void CSpaceRestrictor::spatial_move("),
    method(zone, "void CCustomZone::MoveScript("),
    method(zone, "void CCustomZone::AffectObjects("),
))
source = r"""
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include <vector>
struct Fvector {float x=0,y=0,z=0;};
bool _valid(const Fvector& v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
struct Matrix {Fvector c;void translate_over(const Fvector& v){c=v;}};
struct DeviceState {unsigned dwFrame=1,dwPrecacheFrame=0;} Device;
struct CGameObject {Fvector position;bool killed=false;bool getDestroy()const{return killed;}};
struct Contact {CGameObject* object;};
struct Base {
    Matrix matrix;
    Fvector registered;
    unsigned updates=0;
    void spatial_move(){registered=matrix.c;++updates;}
};
struct CSpaceRestrictor:Base {
    using inherited=Base;
    bool cache=true;
    void actual(bool value){cache=value;}
    void spatial_move();
};
struct CCustomZone:CSpaceRestrictor {
    using OBJECT_INFO_VEC_IT=std::vector<Contact>::iterator;
    std::vector<Contact> m_ObjectInfoMap;
    std::vector<CGameObject*> affected;
    unsigned m_dwAffectFrameNum=0,visual_moves=0,checks=0;
    bool m_script_moved_since_touch=false;
    Matrix& XFORM(){return matrix;}
    const Fvector& Position()const{return matrix.c;}
    void OnMove(){assert(registered.x==Position().x&&!cache);++visual_moves;}
    bool feel_touch_contact(CGameObject* obj){++checks;return std::abs(obj->position.x-Position().x)<1.f;}
    void Affect(Contact* contact){affected.push_back(contact->object);}
    void MoveScript(Fvector pos);
    void AffectObjects();
};
""" + methods + r"""
int main(){
    CCustomZone item;
    CGameObject old_contact{{0,0,0}},remaining{{15,0,0}},destroyed{{15,0,0},true};
    item.m_ObjectInfoMap={{&old_contact},{&remaining},{&destroyed},{nullptr}};
    item.MoveScript({15,0,0});
    assert(item.Position().x==15&&item.registered.x==15&&!item.cache&&item.visual_moves==1&&item.m_script_moved_since_touch);
    item.MoveScript({15,0,0});item.MoveScript({std::numeric_limits<float>::quiet_NaN(),0,0});
    assert(item.updates==1&&item.visual_moves==1);
    item.AffectObjects();assert(item.affected.size()==1&&item.affected[0]==&remaining&&item.checks==2);
    item.AffectObjects();assert(item.affected.size()==1&&item.checks==2);
    // Model the scheduler replacing the touch list at the new position.
    CGameObject new_contact{{15.2f,0,0}};
    item.m_ObjectInfoMap={{&remaining},{&new_contact}};
    item.m_script_moved_since_touch=false;
    ++Device.dwFrame;Device.dwPrecacheFrame=1;item.AffectObjects();
    assert(item.affected.size()==1);
    ++Device.dwFrame;Device.dwPrecacheFrame=0;item.AffectObjects();
    assert(item.affected.size()==3&&item.affected.back()==&new_contact&&item.checks==2);
    std::puts("PASS moved zone refreshes spatial registration and invalidates old contacts before damage");
}
"""
with TemporaryDirectory(prefix="lz-zone-move-") as path:
    folder = Path(path)
    cpp = folder / "move.cpp"
    exe = folder / "move.exe"
    cpp.write_text(source, encoding="utf-8")
    subprocess.run(["cl", "/nologo", "/std:c++17", "/EHsc", "/W4", "/WX", str(cpp),
                    "/Fe:" + str(exe)], cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True, timeout=30)
