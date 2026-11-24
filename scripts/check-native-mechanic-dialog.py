"""Actual mechanic dialogue eligibility and request dispatch in Windows CI."""
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks run only in Windows GitHub Actions")

root = Path(__file__).resolve().parents[1] / "src/xrGame"
server = (root / "netcoop_tasks.inc").read_text(encoding="utf-8")
begin = server.index("static bool can_open_talk_upgrade(")
policy = server[begin:server.index("static void server_on_talk_dialogue(", begin)]
begin = server.index("\tif (op == talk_upgrade)")
dispatch = server[begin:server.index("\n\tif (!valid ||", begin)]
wire = (root / "netcoop_dialogue.inc").read_text(encoding="utf-8")
assert "talk_flag_mechanic = 4" in wire
assert "state.mechanic = !!(flags & talk_flag_mechanic);" in wire
assert "(state.mechanic ? talk_flag_mechanic : 0)" in server
assert "state.mechanic = state.open && can_open_talk_upgrade(actor, npc);" in server
ui = (root / "ui/UITalkWnd.cpp").read_text(encoding="utf-8")
assert "m_netcoop_trade || UITalkDialogWnd->mechanic_mode" in ui
assert "netcoop::client_talk_upgrade();" in ui

source = r"""
#include <cassert>
#include <cstring>
#include <cstdio>
#include <vector>
using u16=unsigned short;
struct Character {
    bool mechanic=false;
    bool upgrade_mechanic() const{return mechanic;}
};
struct CInventoryOwner {
    CInventoryOwner* partner=nullptr;
    bool talking=true, talk_enabled=true;
    Character profile;
    bool IsTalking() const{return talking;}
    CInventoryOwner* GetTalkPartner() const{return partner;}
    bool IsTalkEnabled() const{return talk_enabled;}
    const Character& SpecificCharacter() const{return profile;}
};
struct CActor:CInventoryOwner {
    u16 id=5;
    u16 ID() const{return id;}
};
const int talk_upgrade=3;
std::vector<int> s_talk_sessions{7};
int scopes=0,opened=0;
struct ServerVictimScope {
    explicit ServerVictimScope(CActor* value){assert(value->ID()==5);++scopes;}
    ~ServerVictimScope(){--scopes;}
};
void server_open_ui(u16 actor,const char* kind,u16 npc){
    assert(scopes==1 && actor==5 && npc==15 && !std::strcmp(kind,"upgrade"));
    ++opened;
}
""" + policy + r"""
void request(CActor* actor,CInventoryOwner* npc,bool valid,bool session,int op=talk_upgrade){
    const u16 npc_id=15;
    const auto found=session ? s_talk_sessions.begin():s_talk_sessions.end();
""" + dispatch + r"""
}
int main(){
    CActor actor,other;
    CInventoryOwner technician;
    actor.partner=&technician;
    technician.partner=&actor;
    request(&actor,&technician,true,true);assert(opened==0);
    technician.profile.mechanic=true;
    request(&actor,&technician,false,true);assert(opened==0); // Native target/range/life validation failed.
    request(&actor,&technician,true,false);assert(opened==0);
    technician.partner=&other;
    request(&actor,&technician,true,true);assert(opened==0);
    technician.partner=&actor;
    technician.talk_enabled=false;
    request(&actor,&technician,true,true);assert(opened==0);
    technician.talk_enabled=true;
    request(&actor,&technician,true,true,0);assert(opened==0);
    actor.talking=false;
    request(&actor,&technician,true,true);assert(opened==0);
    actor.talking=true;
    request(&actor,&technician,true,true);assert(opened==1 && scopes==0);
    std::puts("PASS mechanic dialog: current two-way session, authoritative mechanic profile, range/life gate, scoped owner opening");
}
"""
with TemporaryDirectory(prefix="lz-mechanic-dialog-") as temporary:
    folder = Path(temporary)
    cpp = folder / "mechanic.cpp"
    exe = folder / "mechanic.exe"
    cpp.write_text(source, encoding="utf-8")
    subprocess.run(["cl", "/nologo", "/std:c++17", "/EHsc", "/W4", "/WX", str(cpp),
                    "/Fe:" + str(exe)], cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True, timeout=30)
