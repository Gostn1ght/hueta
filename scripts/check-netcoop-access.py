"""Compile the actual console policy and character-selection function with host stubs.

Exercises authorization boundaries without launching or controlling the game UI.
Requires the installed Visual Studio C++ toolchain.
"""
from pathlib import Path
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
out = root.parent / 'build-logs' / 'menu-access'
out.mkdir(parents=True, exist_ok=True)
console = (root / 'src/xrEngine/XR_IOConsole.cpp').read_text(encoding='cp1251')
policy = console[console.index('static bool player_console_allowed()'):console.index('void CConsole::ExecuteCommand(')]
characters = (root / 'src/xrGame/netcoop_characters.inc').read_text(encoding='cp1251')
selection = characters[characters.index('static bool character_select('):characters.index('static CloudJson s_drafts')]
firebase_source = (root / 'src/xrGame/netcoop_firebase.inc').read_text(encoding='cp1251')
firebase_config = firebase_source[firebase_source.index('static bool firebase_enabled()'):firebase_source.index('static std::string cloud_form_encode(')]
stub = r''' 
#include <cassert>
#include <cstring>
#include <string>
#include <map>
#include <cstdio>
using LPCSTR = const char*;
using u8 = unsigned char;
using u32 = unsigned;
void Msg(const char*,...){}
using xr_string = std::string;
using string_path = char[1024];
struct { LPCSTR Params = "-netcoop"; } Core;
bool g_dedicated_server = false;
struct Persistent { bool admin = false; bool CanUsePlayerConsole() { return admin; } } persistent;
Persistent* g_pGamePersistent = nullptr;
int xr_strcmp(LPCSTR a, LPCSTR b) { return strcmp(a,b); }
const int role_admin = 2;
const unsigned INVALID_FILE_ATTRIBUTES = ~0u;
unsigned GetFileAttributesA(LPCSTR) { return INVALID_FILE_ATTRIBUTES; }
struct Character {
    xr_string account,name="Existing character",faction,loadout;
    u8 slot=1,economy=1; bool respawn=false;u32 storage_revision=1;
    struct { struct { unsigned count; } B; } actor;
};
struct xrClientData {
    int netcoop_role = 1;
    xr_string netcoop_login = "account", netcoop_character_name;
    u8 netcoop_character_slot = 0;
};
std::map<xr_string,Character> s_characters;
Character existing;
const bool TRUE=true,FALSE=false;
struct { bool exist(string_path&,LPCSTR,LPCSTR) { return true; } } FS;
LPCSTR fixture_api="abcdefghijklmnopqrstuvwxyz", fixture_endpoint=nullptr;
struct CInifile {
 CInifile(LPCSTR,bool,bool,bool) {}
 bool line_exist(LPCSTR,LPCSTR) { return true; }
 LPCSTR r_string(LPCSTR,LPCSTR key) { return strcmp(key,"api_key")==0 ? fixture_api : fixture_endpoint; }
};
static bool s_firebase_config_loaded=false;
static xr_string s_firebase_api,s_email_code_endpoint;
int loads=0;
Character* character_load(LPCSTR,u8) { ++loads; return &existing; }
void character_path(LPCSTR,u8,string_path& path) { path[0]=0; }
bool character_call_sign_valid(LPCSTR) { return true; }
bool character_starter_loadout(xr_string& kit) {kit="starter";return true;}
bool character_validate_loadout(LPCSTR,u8,LPCSTR) { return true; }
bool character_save(Character&) { return true; }
xr_string character_key(LPCSTR,u8) { return "character"; }
'''
cases = r'''
int main() {
    assert(firebase_enabled()); assert(s_email_code_endpoint.empty());
    s_firebase_config_loaded=false;s_firebase_api.clear();fixture_api=nullptr;
    assert(!firebase_enabled());
    s_firebase_config_loaded=false;fixture_api="abcdefghijklmnopqrstuvwxyz";fixture_endpoint="https://example.invalid/exec";
    assert(firebase_enabled());assert(s_email_code_endpoint==fixture_endpoint);
    assert(!player_console_allowed()); // Startup cannot inherit a cached admin flag.
    g_pGamePersistent=&persistent;
    assert(!player_console_allowed());
    persistent.admin=true; assert(player_console_allowed());
    persistent.admin=false;g_dedicated_server=true;assert(player_console_allowed());
    g_dedicated_server=false;Core.Params="";assert(!player_console_allowed());
    Core.Params="-netcoop";
    for (auto name : {"god", "g_god", "demo_record", "lua", "run_script", "spawn", "ra", "netcoop_set_role", "e_signal"})
        assert(!player_internal_command(name,"on"));
    for (auto name : {"vid_mode", "snd_volume_eff", "mouse_sens", "bind", "cfg_load", "main_menu", "disconnect", "quit", "ssfx_ao", "shader_param_1", "scope_brightness", "mouse_sens_aim", "discord_status"})
        assert(player_internal_command(name,"value"));
    assert(player_internal_command("start","client(127.0.0.1/name=user/port=1267)"));
    assert(!player_internal_command("start","server(all/single/alife/new) client(localhost)"));
    assert(!player_internal_command("start","SeRvEr(all/single/alife/new)"));
    assert(!player_internal_command("rs_wireframe","on"));
    // GAMMA's optics/thermal/voice settings are local (owner 2026-10-12: black scopes).
    for (auto name : {"s3ds_param_1", "sds_enable", "heat_vision_mode", "zoom_step_count", "voice_volume",
                      "sil_glow_color", "markswitch_current", "slot_0", "netcoop_smooth", "lua_gcstep"})
        assert(player_internal_command(name,"1"));
    for (auto name : {"lua_studio_connect", "lua_debug", "time_factor", "ai_die_in_anomaly", "g_game_difficulty",
                      "wpn_degradation", "ph_iterations", "r4_wireframe", "g_hit_pwr_modif"})
        assert(!player_internal_command(name,"1"));
    xrClientData client;
    assert(!character_select(nullptr,1,"x","stalker",1,""));
    assert(character_select(&client,1,"x","stalker",1,""));
    for (u8 slot : {u8(0),u8(2),u8(5),u8(10),u8(11),u8(255)}) {
        int before=loads;assert(!character_select(&client,slot,"x","stalker",1,""));assert(loads==before);
    }
    client.netcoop_role=2;
    assert(character_select(&client,1,"x","stalker",1,""));
    for (u8 slot=2;slot<=10;++slot) {
        assert(!character_select(&client,slot,"x","stalker",1,""));assert(client.netcoop_character_slot==1);
    }
    assert(!character_select(&client,11,"x","stalker",1,""));
    client.netcoop_role=1;assert(!character_select(&client,10,"x","stalker",1,""));
    puts("Native access policy: player/admin/dedicated, script/config command gate, case variants, server slot limits and empty mail config PASS");
}
'''
source = out / 'access.cpp'
source.write_text(stub + firebase_config + policy + selection + cases, encoding='utf-8')
vcvars = Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
setup_file = out / 'environment.cmd'
setup_file.write_text('@echo off\ncall "' + str(vcvars) + '" >nul\nif errorlevel 1 exit /b 1\nset\n', encoding='ascii')
setup = subprocess.run(['cmd','/d','/c',str(setup_file)], capture_output=True, check=True)
env = os.environ.copy()
for line in setup.stdout.decode('mbcs').splitlines():
    key, sep, value = line.partition('=')
    if sep and key: env[key] = value
compiler = Path(env['VCToolsInstallDir']) / 'bin/Hostx64/x64/cl.exe'
subprocess.run([str(compiler),'/nologo','/EHsc','/std:c++17',str(source),f'/Fo:{out / "access.obj"}',f'/Fe:{out / "access.exe"}'], env=env, check=True)
subprocess.run([str(out / 'access.exe')], check=True)
