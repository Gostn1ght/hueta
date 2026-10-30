"""Execute the real config path resolver and client migration with a fake VFS.

Only the archive reader is replaced. Win32 paths, filesystem operations and
the shipped C++ migration/resolver functions are compiled unchanged in CI.
"""
import os
from pathlib import Path
import subprocess
import tempfile

if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run on Windows GitHub Actions')
root = Path(__file__).resolve().parents[1]
source = (root/'src/xrServerEntities/script_storage.cpp').read_text(encoding='utf-8-sig')
resolver = source[source.index('static void config_io_parent('):source.index('static int config_io_call(')]
prefix = r'''
#define NOMINMAX
#include <windows.h>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <map>
#include <vector>
#include <cstdio>
#include <cstring>
#include <cassert>
using u32=unsigned;using u64=unsigned long long;using string_path=char[520];using string128=char[128];using xr_string=std::string;
#define xr_strlen std::strlen
#define xr_strcmp std::strcmp
#define Msg(...) std::printf(__VA_ARGS__)
template<size_t N,class... Args> void xr_sprintf(char (&dst)[N],const char* format,Args... args){assert(sprintf_s(dst,N,format,args...)>=0);}
template<size_t N> void xr_strcpy(char (&dst)[N],const char* src){assert(strcpy_s(dst,N,src)==0);}
template<size_t N> void xr_strcat(char (&dst)[N],const char* src){assert(strcat_s(dst,N,src)==0);}
u32 crc32(const void* p,u32 count){u32 h=2166136261;for(u32 i=0;i<count;++i) h=(h^((const unsigned char*)p)[i])*16777619;return h;}
u32 path_crc32(const void* p,u32 count){return crc32(p,count);}
bool g_dedicated_server=false;
struct IReader{std::string bytes;const void* pointer(){return bytes.data();}u32 length(){return u32(bytes.size());}};
struct FakeFS {
 struct Path{const char* m_Path;};std::map<std::string,std::string> aliases,archive;Path current{};unsigned rescans=0;
 Path* get_path(const char* alias){current.m_Path=aliases.at(alias).c_str();return &current;}
 template<size_t N> void update_path(char (&out)[N],const char* alias,const char* relative){xr_strcpy(out,(aliases.at(alias)+relative).c_str());}
 template<size_t N> bool exist(char (&out)[N],const char* alias,const char* relative){update_path(out,alias,relative);return archive.count(relative)||std::filesystem::exists(out);}
 IReader* r_open(const char* alias,const char* relative){
  const auto path=aliases.at(alias)+relative;std::ifstream in(path,std::ios::binary);if(in){std::ostringstream bytes;bytes<<in.rdbuf();return new IReader{bytes.str()};}
  auto found=archive.find(relative);return found==archive.end()?nullptr:new IReader{found->second};
 }
 void r_close(IReader*& r){delete r;r=nullptr;}
 void rescan_path(const char*,bool){++rescans;}
} FS;
struct CInifile {
 std::map<std::string,std::string> rows;
 CInifile(const char* path,bool=true,bool=true,bool=false){
  std::string relative=path;auto base=FS.aliases.at("$game_config$");if(relative.rfind(base,0)==0)relative.erase(0,base.size());
  IReader* reader=FS.r_open("$game_config$",relative.c_str());assert(reader);std::istringstream in(reader->bytes);std::string line;
  while(std::getline(in,line)){auto eq=line.find('=');if(eq!=std::string::npos)rows[line.substr(0,eq)]=line.substr(eq+1);}FS.r_close(reader);
 }
 bool line_exist(const char*,const char* name){return rows.count(name)!=0;}
 const char* r_string(const char*,const char* name){return rows.at(name).c_str();}
};
std::string read(const std::string& path){std::ifstream in(path,std::ios::binary);std::ostringstream bytes;bytes<<in.rdbuf();return bytes.str();}
void write(const std::string& path,const std::string& bytes){std::filesystem::create_directories(std::filesystem::path(path).parent_path());std::ofstream out(path,std::ios::binary);out<<bytes;assert(out.good());}
'''
main = r'''
int main(int argc,char**argv){
 const std::string root=std::filesystem::absolute(argv[1]).string()+"\\";
 FS.aliases={{"$fs_root$",root},{"$game_config$",root+"appdata\\player\\configs\\"},{"$app_data_root$",root+"appdata\\player\\"}};
 const auto base=FS.aliases.at("$game_config$");FS.archive["default.ltx"]="archived-default";
 string_path resolved;bool writing=false;
 assert(config_io_path((base+"default.ltx").c_str(),"rb",resolved,writing));assert(!writing && read(resolved)=="archived-default");
 assert(!std::filesystem::exists(base+"default.ltx")); // read cache cannot shadow future archives
 FS.archive["default.ltx"]="updated-default";
 assert(config_io_path((base+"default.ltx").c_str(),"r",resolved,writing));assert(read(resolved)=="updated-default");
 assert(config_io_path((root+"client\\configs\\default.ltx").c_str(),"ab",resolved,writing));
 assert(writing && std::string(resolved)==base+"default.ltx" && read(resolved)=="updated-default");
 {std::ofstream append(resolved,std::ios::binary|std::ios::app);append<<"+custom";}
 assert(config_io_path((root+"gamedata\\configs\\default.ltx").c_str(),"rb",resolved,writing));assert(read(resolved)=="updated-default+custom");
 assert(config_io_path((base+"custom\\new.ltx").c_str(),"wb",resolved,writing));assert(writing);write(resolved,"new");
 assert(!config_io_path((base+"..\\private.txt").c_str(),"w",resolved,writing));
 assert(!config_io_path((root+"private.txt").c_str(),"w",resolved,writing));
 const auto old=root+"client\\configs\\";write(old+"unchanged.ltx","same");write(old+"changed.ltx","user-edit");write(old+"axr_options.ltx","user-mcm");
 write(old+"existing.ltx","old");write(base+"existing.ltx","newer");
 u64 size=0,hash=0;assert(client_config_digest((old+"unchanged.ltx").c_str(),size,hash));char record[128];sprintf_s(record,"%llu,%llx",size,hash);
 FS.archive["netcoop\\config_migration_000047.ltx"]=std::string("[old_configs]\nunchanged.ltx=")+record+"\n";
 migrate_client_configs();
 assert(!std::filesystem::exists(root+"client"));assert(!std::filesystem::exists(base+"unchanged.ltx"));
 assert(read(base+"changed.ltx")=="user-edit" && read(base+"axr_options.ltx")=="user-mcm" && read(base+"existing.ltx")=="newer");
 assert(FS.rescans==1);migrate_client_configs();assert(FS.rescans==1);
 bool backup=false;for(const auto& path:std::filesystem::directory_iterator(root+"appdata\\player\\migration"))backup|=std::filesystem::exists(path.path()/"configs"/"axr_options.ltx");assert(backup);
 std::puts("PASS actual native config resolver: archived reads, updated defaults, mutable append, legacy aliases, path bounds; client migration preserves custom files and backups, idempotent rerun");
}
'''
with tempfile.TemporaryDirectory(prefix='lz config fixture ') as temporary:
    work = Path(temporary)
    cpp = work/'fixture.cpp'
    cpp.write_text(prefix + resolver + '\n#include "' + (root/'src/xrEngine/client_config_migration.h').as_posix() + '"\n' + main,encoding='utf-8')
    subprocess.run(['cl','/nologo','/std:c++17','/EHsc','/utf-8','/W3',str(cpp),'/Fe:'+str(work/'fixture.exe'),'/Fo:'+str(work/'fixture.obj')],cwd=work,check=True)
    subprocess.run([str(work/'fixture.exe'),str(work/'game')],cwd=work,check=True,timeout=30)
