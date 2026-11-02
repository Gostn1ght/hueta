"""CI-only actual mixed-owner destroy guards, stationary-car hits and graph API."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,subprocess
if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native checks must run in GitHub Actions')
root=Path(__file__).resolve().parents[1]
def method(file,name):
    s=(root/file).read_text(encoding='utf-8');a=s.index(name);b=s.index('{',a);e=b+1;depth=1
    while depth:depth+=(s[e]=='{')-(s[e]=='}');e+=1
    return s[a:e]
source=r'''
#include "netcoop_destroy_tree.h"
#include <cassert>
#include <map>
#include <cstdio>
using u32=unsigned;
struct CObject{virtual ~CObject()=default;};struct CCar:CObject{};
template<class T>T smart_cast(CObject* p){return dynamic_cast<T>(p);}
namespace netcoop{bool client=false;bool pure_client(){return client;}}
struct Graph{bool valid_vertex_id(u32 id){return id<10;}};
struct AI{Graph graph;Graph&level_graph(){return graph;}}instance;
AI&ai(){return instance;}
'''+method('src/xrGame/Actor.cpp','static bool actor_collision_damage_local(')+method('src/xrGame/level_script.cpp','bool valid_vertex(')+r'''
int main(){
 assert(netcoop::destroy_authorized(false,false,true));
 assert(netcoop::destroy_authorized(false,true,false)); // authoritative cleanup of migrated ownership
 assert(netcoop::destroy_authorized(true,false,false)); // recursion from a previously validated root
 assert(!netcoop::destroy_authorized(false,false,false)); // forged root remains refused
 std::map<unsigned,std::vector<unsigned>> tree{{1,{2,3}},{2,{4}},{3,{}},{4,{}}};
 std::map<unsigned,unsigned> parent{{2,1},{3,1},{4,2}};
 auto read=[&](unsigned id)->const std::vector<unsigned>*{auto it=tree.find(id);return it==tree.end()?nullptr:&it->second;};
 auto linked=[&](unsigned p,unsigned c){auto it=parent.find(c);return it!=parent.end()&&it->second==p;};
 assert(netcoop::destroy_tree_valid(1,read,linked));
 parent[4]=3;assert(!netcoop::destroy_tree_valid(1,read,linked));parent[4]=2;
 tree[4]={1};parent[1]=4;assert(!netcoop::destroy_tree_valid(1,read,linked));tree[4].clear();
 tree[1]={2,2};assert(!netcoop::destroy_tree_valid(1,read,linked));tree[1]={2,3};
 tree.erase(4);assert(!netcoop::destroy_tree_valid(1,read,linked));tree[4]={};
 std::vector<unsigned> children{25857};unsigned attempts=0;
 assert(!netcoop::destroy_children(children,[&](unsigned){++attempts;}));assert(attempts==1&&children[0]==25857);
 children={2,3};attempts=0;
 assert(netcoop::destroy_children(children,[&](unsigned id){++attempts;children.erase(std::find(children.begin(),children.end(),id));}));
 assert(attempts==2&&children.empty());
 CCar car;CObject ground;
 assert(actor_collision_damage_local(&car));netcoop::client=true;
 assert(!actor_collision_damage_local(&car));assert(actor_collision_damage_local(&ground));assert(actor_collision_damage_local(nullptr));
 assert(valid_vertex(0)&&valid_vertex(9)&&!valid_vertex(10)&&!valid_vertex(~0u));
 puts("PASS actual destroy progress/authorization/graph, replica-car damage exclusion, respawn vertex API");
}
'''
native=(root/'src/xrGame/xrServer_process_event_destroy.cpp').read_text(encoding='utf-8')
assert 'while (!e_dest->children.empty())' not in native
assert 'netcoop::destroy_authorized(' in native and 'netcoop::destroy_children(' in native and 'netcoop::destroy_tree_valid(' in native
assert 'def("valid_vertex", valid_vertex)' in (root/'src/xrGame/level_script.cpp').read_text(encoding='utf-8')
with TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'destroy.cpp';exe=Path(tmp)/('destroy.exe' if os.name=='nt' else 'destroy')
    cpp.write_text(source,encoding='utf-8');inc=str(root/'src/xrGame')
    command=(['cl','/nologo','/std:c++17','/EHsc','/I'+inc,str(cpp),'/Fe:'+str(exe)] if os.name=='nt' else ['g++','-std=c++17','-I',inc,str(cpp),'-o',str(exe)])
    subprocess.run(command,cwd=tmp,check=True);subprocess.run([str(exe)],cwd=tmp,check=True,timeout=10)
