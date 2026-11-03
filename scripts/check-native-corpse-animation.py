"""CI-only actual corpse track gate and renderer UpdateTracks interaction."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]


def method(path, signature):
    source = (root / path).read_text(encoding='utf-8')
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


physics = (root / 'src/xrGame/CharacterPhysicsSupport.cpp').read_text(encoding='utf-8')
gate = physics[physics.index('struct NetcoopCorpseTracks'):physics.index('void CCharacterPhysicsSupport::in_UpdateCL()')]
source = r'''
#include <cassert>
#include <cstdio>
using u32=unsigned;
#define _DBG_SINGLE_USE_MARKER
struct {u32 dwTimeGlobal=100;} RDEVICE;
struct IKinematicsAnimated;
struct IUpdateTracksCallback {virtual ~IUpdateTracksCallback()=default;virtual bool operator()(float,IKinematicsAnimated&)=0;};
struct IKinematicsAnimated {
 IUpdateTracksCallback* callback=nullptr;
 virtual ~IKinematicsAnimated()=default;
 IUpdateTracksCallback* GetUpdateTracksCalback(){return callback;}
 void SetUpdateTracksCalback(IUpdateTracksCallback* p){callback=p;}
};
struct CKinematicsAnimated:IKinematicsAnimated {
 u32 Update_LastTime=0, advances=0;
 void LL_UpdateTracks(float,bool,bool){++advances;}
 void UpdateTracks();
};
struct IRenderVisual {IKinematicsAnimated* model=nullptr;IKinematicsAnimated* dcast_PKinematicsAnimated(){return model;}};
struct CEntityAlive {bool alive=true;IRenderVisual* visual=nullptr;bool g_Alive(){return alive;}IRenderVisual* Visual(){return visual;}unsigned ID(){return 7;}};
namespace netcoop {bool active=true;bool enabled(){return active;}}
template<class...T>void Msg(const char*,T...){}
''' + gate + method('src/Layers/xrRender/SkeletonAnimated.cpp', 'void CKinematicsAnimated::UpdateTracks()') + r'''
struct ForeignCallback:IUpdateTracksCallback {bool operator()(float,IKinematicsAnimated&){return false;}};
int main(){
 CEntityAlive entity;netcoop_update_corpse_tracks(entity,false);
 IRenderVisual visual;entity.visual=&visual;netcoop_update_corpse_tracks(entity,true);
 CKinematicsAnimated model;visual.model=&model;
 ForeignCallback existing;model.callback=&existing;
 netcoop_update_corpse_tracks(entity,false);assert(model.callback==&existing);
 entity.alive=false;netcoop_update_corpse_tracks(entity,false);assert(model.callback==&existing);
 // Full ragdoll, not a merely wounded or dying character: all live tracks,
 // including non-physical ears/jaw, keep their exact last sampled pose.
 netcoop_update_corpse_tracks(entity,true);assert(model.callback==&s_netcoop_corpse_tracks);
 model.UpdateTracks();assert(model.advances==0&&model.Update_LastTime==100);
 RDEVICE.dwTimeGlobal=200;model.UpdateTracks();assert(model.advances==0&&model.Update_LastTime==200);
 netcoop_update_corpse_tracks(entity,true);assert(model.callback==&s_netcoop_corpse_tracks);
 // Reused or revived model: release ONLY our callback and let the real
 // renderer advance normally again. An unrelated callback is preserved.
 entity.alive=true;netcoop_update_corpse_tracks(entity,true);assert(!model.callback);
 RDEVICE.dwTimeGlobal=300;model.UpdateTracks();assert(model.advances==1);
 model.callback=&existing;netcoop_update_corpse_tracks(entity,false);assert(model.callback==&existing);
 netcoop::active=false;entity.alive=false;netcoop_update_corpse_tracks(entity,true);assert(model.callback==&existing);
 netcoop::active=true;netcoop_update_corpse_tracks(entity,true);netcoop::active=false;
 netcoop_update_corpse_tracks(entity,true);assert(!model.callback);
 puts("PASS actual ragdoll track gate and renderer: no live ear/head tracks, null visual, living/wounded paths, model reuse and unrelated callbacks");
}
'''
update = method('src/xrGame/CharacterPhysicsSupport.cpp', 'void CCharacterPhysicsSupport::in_UpdateCL()')
assert update.index('netcoop_update_corpse_tracks(') < update.index('netcoop::pure_client() && m_pPhysicsShell')
with TemporaryDirectory() as temporary:
    cpp = Path(temporary) / 'corpse.cpp'
    exe = Path(temporary) / ('corpse.exe' if os.name == 'nt' else 'corpse')
    cpp.write_text(source, encoding='utf-8')
    command = (['cl', '/nologo', '/std:c++17', '/EHsc', str(cpp), '/Fe:'+str(exe)] if os.name == 'nt' else
               ['g++', '-std=c++17', '-fsanitize=address,undefined', str(cpp), '-o', str(exe)])
    subprocess.run(command, cwd=temporary, check=True)
    subprocess.run([str(exe)], cwd=temporary, check=True, timeout=15)
