"""CI-only: real device UI owner gates across drop, transfer and HUD teardown."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]


def function(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


hud = (root / 'src/xrGame/HudItem.cpp').read_text(encoding='utf-8-sig')
tasks = (root / 'src/xrGame/netcoop_tasks.inc').read_text(encoding='utf-8')
owner = function(tasks, 'bool client_owns_hud_item(const CObject* item)')
gate = function(hud, 'static bool netcoop_hud_script_ui_allowed(')
update_start = hud.index('if (script_ui && netcoop_hud_script_ui_allowed(&object()))')
update_end = hud.index('script_ui->Update();', update_start) + len('script_ui->Update();')
update = hud[update_start:update_end]
attach = function(hud, 'void CHudItem::on_a_hud_attach()')
attach = attach[:attach.index('if (script_ui_funct')] + '++attach_allowed;\n}'
render = function(hud, 'void CHudItem::render_item_3d_ui()')
render = render[:render.index('if (script_ui)')] + '++render_allowed;\n}'
source = r'''
#include <cassert>
#include <cstdio>
struct CObject {const CObject* parent=nullptr;const CObject* H_Parent()const{return parent;}};
struct World {const CObject* control=nullptr;const CObject* CurrentControlEntity(){return control;}}world;
World& Level(){return world;}
bool g_dedicated_server=false;
namespace netcoop {bool client=true;bool pure_client(){return client;}
''' + owner + '\n}\n' + gate + r'''
struct UI {unsigned updates=0;void Update(){++updates;}}ui;
int hud_instance=0;int* g_player_hud=&hud_instance;
struct CHudItem {
 CObject item;UI* script_ui=&ui;bool data=true;unsigned attach_allowed=0,render_allowed=0;
 CObject& object(){return item;}void* HudItemData(){return data?this:nullptr;}
 void on_a_hud_attach();void render_item_3d_ui();
 void update(){
''' + update + '\n}\n};\n' + attach + '\n' + render + r'''
int main(){
 CObject local,other;world.control=&local;CHudItem device;device.item.parent=&local;
 device.update();device.on_a_hud_attach();device.render_item_3d_ui();
 assert(ui.updates==1&&device.attach_allowed==1&&device.render_allowed==1);
 // Keep the same allocated screen as the device changes physical owner.
 device.item.parent=&other;
 device.update();device.on_a_hud_attach();device.render_item_3d_ui();
 device.item.parent=nullptr;device.update();device.on_a_hud_attach();device.render_item_3d_ui();
 device.item.parent=&local;world.control=nullptr;
 device.update();device.on_a_hud_attach();device.render_item_3d_ui();
 assert(ui.updates==1&&device.attach_allowed==1&&device.render_allowed==1);
 world.control=&local;g_dedicated_server=true;
 device.update();device.on_a_hud_attach();device.render_item_3d_ui();
 assert(ui.updates==1&&device.attach_allowed==1&&device.render_allowed==1);
 g_dedicated_server=false;g_player_hud=nullptr;device.render_item_3d_ui();
 g_player_hud=&hud_instance;device.data=false;device.render_item_3d_ui();
 assert(device.render_allowed==1);
 device.data=true;device.update();device.render_item_3d_ui();
 assert(ui.updates==2&&device.render_allowed==2);
 device.script_ui=nullptr;device.update();assert(ui.updates==2);device.script_ui=&ui;
 netcoop::client=false;device.item.parent=nullptr;
 device.update();device.on_a_hud_attach();device.render_item_3d_ui();
 assert(ui.updates==3&&device.attach_allowed==2&&device.render_allowed==3);
 std::puts("PASS actual device UI gates: owner, foreign/dropped screen, no local actor, dedicated server, missing HUD/model, ownership return and freeplay");
}
'''
with TemporaryDirectory(prefix='device-ui-') as temporary:
    folder = Path(temporary)
    cpp = folder / 'check.cpp'
    exe = folder / ('check.exe' if os.name == 'nt' else 'check')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(cpp), '/Fe:' + str(exe)]
               if os.name == 'nt' else
               ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=folder, check=True)
    subprocess.run([str(exe)], cwd=folder, check=True)
