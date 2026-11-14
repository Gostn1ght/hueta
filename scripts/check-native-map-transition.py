"""CI-only: real map route gate and pointer update during location changes."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
native=(root/'src/xrGame/map_location.cpp').read_text(encoding='utf-8-sig')
start=native.index('\telse if (',native.index('void CMapLocation::UpdateSpot('))
end=native.index('\n\t\tmap_point_path.clear();',start)
route=native[start:end].replace('else if','if',1)
pointer=native[native.index('void CMapLocation::UpdateSpotPointer('):native.index('void CMapLocation::UpdateMiniMap(')]
assert 'CObject* entity = Level().CurrentEntity();' in pointer
cache=(root/'src/xrGame/netcoop.cpp').read_text(encoding='utf-8')
cache=cache[cache.index('namespace\n{\nstruct ClientMapPosition'):cache.index('bool corpse_loot_drops()')]
stop=(root/'src/xrGame/Level_network.cpp').read_text(encoding='utf-8-sig')
assert stop.index('remove_objects();',stop.index('void CLevel::net_Stop()')) < stop.index('netcoop::client_map_positions_reset();')
source=r"""
#include <cassert>
#include <cmath>
#include <cstdio>
#include <string>
#include <map>
using u32=unsigned;using u16=unsigned short;using LPCSTR=const char*;
using shared_str=std::string;template<class K,class V>using xr_map=std::map<K,V>;
const char* operator*(const std::string& value){return value.c_str();}
struct Fvector{float x=0,y=0,z=0;void set(float a,float b,float c){x=a;y=b;z=c;}
 float distance_to(const Fvector& b)const{return std::sqrt((x-b.x)*(x-b.x)+(y-b.y)*(y-b.y)+(z-b.z)*(z-b.z));}};
struct Fvector2{float x=0,y=0;};
struct CObject{Fvector position;Fvector& Position(){return position;}};
struct CMapSpotPointer{bool parent=false;u32 color=0;unsigned writes=0;Fvector2 pos;float heading=0;
 bool GetParent(){return parent;}float GetWidth(){return 12;}void SetWndPos(Fvector2 p){pos=p;++writes;}
 void SetHeading(float h){heading=h;}u32 GetTextureColor(){return color;}void SetTextureColor(u32 c){color=c;}};
using CMapSpot=CMapSpotPointer;
struct CUICustomMap{std::string name="cordon";bool visible=true;unsigned attached=0;float distance=-1;
 const std::string& MapName(){return name;}bool GetPointerTo(Fvector2 p,float,Fvector2& out,float& h){out=p;h=.5f;return visible;}
 void AttachChild(CMapSpotPointer*){++attached;}Fvector2 ConvertLocalToReal(Fvector2 p,int){return p;}
 int BoundRect(){return 0;}void SetPointerDistance(float value){distance=value;}};
struct CGameTask{};
struct TaskManager{bool task=true;CGameTask entry;CGameTask* HasGameTask(void*,bool){return task?&entry:nullptr;}};
struct World{CObject* entity=nullptr;std::string location="cordon";TaskManager manager;
 const std::string& name(){return location;}CObject* CurrentEntity(){return entity;}TaskManager& GameTaskManager(){return manager;}}world;
World& Level(){return world;}World* g_pGameLevel=&world;
CObject* player=nullptr;CObject* Actor(){return player;}
struct AI{bool graph=true;void* get_game_graph(){return graph?this:nullptr;}}fixture_ai;
AI& ai(){return fixture_ai;}
namespace GameGraph{using _GRAPH_ID=unsigned;}
struct ServerObject{unsigned m_tGraphID=17;};
u32 subst_alpha(u32 color,u32 alpha){return(color&0xffffffu)|(alpha<<24);}
struct CMapLocation{ServerObject* m_owner_se_object=nullptr;bool has_pointer=true;Fvector2 m_position_on_map;
 CMapSpotPointer* GetSpotPointer(CMapSpot* sp){return has_pointer?sp:nullptr;}
 bool route(CUICustomMap* map,CMapSpot* sp);
 void UpdateSpotPointer(CUICustomMap*,CMapSpotPointer*);};
"""+'\nbool CMapLocation::route(CUICustomMap* map,CMapSpot* sp){\n'+route+r"""
 return dest_graph_id==17;
 }return false;
}
"""+pointer+'\nnamespace netcoop{\n'+cache+'\n}\n'+r"""
int main(){
 CMapLocation spot;CMapSpotPointer icon;CUICustomMap map;CObject actor;ServerObject se;
 player=&actor;
 // Pure client: a foreign objective has a map cache but no ALife pointer.
 assert(!spot.route(&map,&icon));
 spot.m_owner_se_object=&se;assert(spot.route(&map,&icon));
 fixture_ai.graph=false;assert(!spot.route(&map,&icon));fixture_ai.graph=true;
 player=nullptr;assert(!spot.route(&map,&icon));player=&actor;
 map.name="radar";assert(!spot.route(&map,&icon));map.name="cordon";
 spot.has_pointer=false;assert(!spot.route(&map,&icon));spot.has_pointer=true;
 // A map/task packet may arrive before actor spawn or after its relcase.
 spot.UpdateSpotPointer(&map,&icon);assert(!icon.writes&&!map.attached);
 world.entity=&actor;spot.m_position_on_map={30,40};spot.UpdateSpotPointer(&map,&icon);
 assert(icon.writes==1&&map.attached==1&&map.distance==50&&icon.color>>24==150);
 icon.parent=true;spot.UpdateSpotPointer(&map,&icon);assert(icon.writes==1);icon.parent=false;
 map.visible=false;spot.UpdateSpotPointer(&map,&icon);assert(icon.writes==1);map.visible=true;
 world.manager.task=false;map.distance=-1;spot.UpdateSpotPointer(&map,&icon);assert(map.distance==-1&&icon.writes==2);
 world.entity=nullptr;spot.UpdateSpotPointer(&map,&icon);assert(icon.writes==2);
 Fvector saved_position;saved_position.set(1,2,3);Fvector out;shared_str map_name;
 netcoop::client_map_position_set(501,saved_position,"radar");
 assert(netcoop::client_map_position(501,out,map_name)&&out.y==2&&map_name=="radar");
 netcoop::client_map_positions_reset();assert(!netcoop::client_map_position(501,out,map_name));
 netcoop::client_map_position_set(501,saved_position,"jupiter");
 assert(netcoop::client_map_position(501,out,map_name)&&map_name=="jupiter");
 netcoop::client_map_position_clear(501);assert(!netcoop::client_map_position(501,out,map_name));
 puts("PASS actual map route gate/pointer: no foreign ALife dereference, missing graph/player, pre-spawn/teardown entity, normal SP route and pointer distance/alpha retained");
}
"""
with TemporaryDirectory() as temporary:
    cpp=Path(temporary)/'map-transition.cpp'
    exe=Path(temporary)/('map-transition.exe'if os.name=='nt'else'map-transition')
    cpp.write_text(source,encoding='utf-8')
    command=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)]if os.name=='nt'else
             ['g++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=temporary,check=True)
    subprocess.run([str(exe)],cwd=temporary,check=True,timeout=15)
