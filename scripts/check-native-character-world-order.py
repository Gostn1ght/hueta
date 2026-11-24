"""CI-only actual character-save admission prefix and world-take generations.

Capture/persistence tail is a boundary hook, not a simulated full engine save.
No local game/native execution. A one-item model checks crash-image conservation.
"""
import os,subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks run only in Windows GitHub Actions')
root=Path(__file__).resolve().parents[1]
characters=(root/'src/xrGame/netcoop_characters.inc').read_text(encoding='utf-8')
world=(root/'src/xrGame/netcoop_world_store.inc').read_text(encoding='utf-8')
start=characters.index('static bool character_save_actor(')
prefix=characters[start:characters.index('Character& character = *tracked;',start)]
def function(text,signature):
    start=text.index(signature);opening=text.index('{',start);depth=0
    for end in range(opening,len(text)):
        if text[end]=='{':depth+=1
        elif text[end]=='}':
            depth-=1
            if not depth:return text[start:end+1]
    raise AssertionError(signature)
source=r'''
#include <cassert>
#include <map>
#include <cstring>
#include <cstdio>
using u16=unsigned short;using u32=unsigned;using LPCSTR=const char*;using string64=char[64];
template<class K,class V>using xr_map=std::map<K,V>;
struct Character{};struct CharacterDestination{};
Character character;bool tracked_ok=true,persistent=true,save_ok=true,advance=true;
int level_token=0;int* g_pGameLevel=&level_token;
struct LevelStub{int* Server=&level_token;}level;
LevelStub& Level(){return level;}
Character* character_tracked_for_save(u16){return tracked_ok ? &character:nullptr;}
void Msg(LPCSTR,...){}
u32 s_world_commits=0;bool s_world_save_requested=false;xr_map<u16,u32>s_world_taken;
bool world_store_name(string64&){return persistent;}
unsigned saves=0,captures=0;int disk_world_items=1,disk_character_items=0;
bool world_store_save_now(LPCSTR reason){
 assert(std::strcmp(reason,"player items")==0);++saves;
 if(save_ok && advance){++s_world_commits;disk_world_items=0;}
 return save_ok;
}
'''+function(world,'static void world_store_note_taken(')+'\n'+function(world,'static void world_store_request_save(')+'\n'+function(world,'static bool world_store_takes_committed(')+'\n'+prefix+r'''
    (void)destination;
    ++captures;disk_character_items=1;return true; // capture/commit boundary
}
void reset(){
 tracked_ok=persistent=save_ok=advance=true;g_pGameLevel=&level_token;level.Server=&level_token;
 saves=captures=s_world_commits=0;s_world_save_requested=false;s_world_taken.clear();
 disk_world_items=1;disk_character_items=0;
}
int main(){
 // Untracked/unavailable actors never get to a world save or capture.
 reset();tracked_ok=false;assert(!character_save_actor(7,nullptr));assert(!saves && !captures);
 reset();g_pGameLevel=nullptr;assert(!character_save_actor(7,nullptr));assert(!saves && !captures);
 reset();level.Server=nullptr;assert(!character_save_actor(7,nullptr));assert(!saves && !captures);
 // No pickup and nonpersistent worlds retain their prior no-world-save path.
 reset();assert(character_save_actor(7,nullptr));assert(!saves && captures==1);
 reset();persistent=false;world_store_note_taken(7);assert(character_save_actor(7,nullptr));assert(!saves);
 // A background checkpoint requests save, preserves its prior durable image.
 reset();world_store_note_taken(7);assert(!character_save_actor(7,nullptr,true));
 assert(s_world_save_requested && !saves && !captures && disk_world_items+disk_character_items==1);
 // Failed world save: retry cannot capture the item into a newer character.
 reset();world_store_note_taken(7);save_ok=false;
 for(int i=0;i<3;++i)assert(!character_save_actor(7,nullptr));
 assert(saves==3 && !captures && disk_world_items+disk_character_items==1);
 // Successful return without a newer committed generation is insufficient.
 reset();world_store_note_taken(7);advance=false;assert(!character_save_actor(7,nullptr));
 assert(saves==1 && !captures && disk_world_items+disk_character_items==1);
 // Eventual durable world commit admits capture exactly after removal.
 save_ok=advance=true;CharacterDestination target;
 assert(character_save_actor(7,&target));assert(saves==2 && captures==1);
 assert(disk_world_items==0 && disk_character_items==1);
 assert(character_save_actor(7,nullptr));assert(saves==2 && captures==2);
 // A later pickup needs a later generation; unrelated actors do not block.
 world_store_note_taken(7);save_ok=false;
 assert(character_save_actor(8,nullptr));assert(!character_save_actor(7,nullptr));
 // An already committed pickup can be checkpointed in background too.
 reset();world_store_note_taken(7);++s_world_commits;
 assert(character_save_actor(7,nullptr,true));assert(!saves && captures==1);
 std::puts("PASS actual character world-order gate: failed/unconfirmed world commit refuses capture; background request, durable retry, per-actor generations and no-persistence compatibility; one-item crash image conserved");
}
'''
with TemporaryDirectory(prefix='lz-character-world-') as temporary:
    folder=Path(temporary);cpp=folder/'check.cpp';cpp.write_text(source,encoding='utf-8');exe=folder/'check.exe'
    subprocess.run(['cl','/nologo','/EHsc','/std:c++17','/W4','/WX',str(cpp),'/Fe:'+str(exe),'/Fo:'+str(folder/'check.obj')],cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True,timeout=30)
