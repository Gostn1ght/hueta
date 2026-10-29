"""Actual character reader/writer and both actual xrCore CPU checksum paths.

Native compilation runs only in GitHub Actions. Legacy binary inputs come
from an independent Python encoder; new saves run the actual durable writer.
"""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory
import zlib

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Native checks must run in GitHub Actions')
root = Path(__file__).resolve().parents[1]
characters = (root/'src/xrGame/netcoop_characters.inc').read_text(encoding='utf-8')
core = (root/'src/xrCore/crc32.cpp').read_text(encoding='utf-8')
# Global archive/world CRC behavior must not change as a side effect of this fix.
assert hashlib.sha256(core.encode()).hexdigest() == 'da60b67b5bedc8086dfbe91eebb7ee7bee56696b5d6e8eedb58e6a9568b1268d'
world = (root/'src/xrGame/netcoop_world_store.inc').read_text(encoding='utf-8')
assert 'crc32(' not in world and 'digest.hash *= 1099511628211ULL' in world

def block(marker):
    start = characters.index(marker)
    opening = characters.index('{', start)
    depth, end = 1, opening+1
    while depth:
        depth += (characters[end] == '{') - (characters[end] == '}')
        end += 1
    return characters[start:end]

actual = characters[characters.index('struct Character\n'):characters.index('static xr_map<xr_string, Character>')]
for marker in ('static xr_string character_key(', 'static void character_path(', 'static bool character_name_valid('):
    actual += '\n'+block(marker)
actual += '\n'+characters[characters.index('struct CharacterInput\n'):characters.index('// Autosaves pass owned bytes')]
actual += '\n'+block('static bool character_sync_commit(')
actual += '\n'+block('static bool character_commit_file(')
# The world master mirror (doc 135) receives each image; here it only counts them.
actual += '\nunsigned fixture_mirrored=0;static bool fixture_master_refuses=false;static bool admission_capture(const Character&, const xr_vector<u8>& image){if(fixture_master_refuses)return false;if(!image.empty())++fixture_mirrored;return true;}\n'
actual += '\n'+block('static bool character_save(Character&')
actual += '\nstatic xr_map<xr_string, Character> s_characters;\n'+block('static bool character_decode(')+'\n'+block('static bool character_load_image(')+'\n'+block('static Character* character_load(')

def crc32c(data):
    value = 0xffffffff
    for byte in data:
        value ^= byte
        for _ in range(8): value = (value >> 1) ^ (0x82f63b78 if value & 1 else 0)
    return value

def legacy(version, algorithm, upgrade=False):
    original_version = version
    if upgrade: version = 9
    offsets = {}
    data = bytearray(b'NCH'+str(version).encode())
    def number(fmt, value): data.extend(struct.pack('<'+fmt, value))
    def string(value): data.extend(value+b'\0')
    def packet(label, value):
        number('I', len(value)); number('I', algorithm(value))
        offsets[label] = len(data); data.extend(value)
    def item(label, section, parent, place):
        string(section); number('H', parent)
        if version >= 4: number('H', place if original_version >= 4 else 0)
        packet(label, bytes(range(1,32)))
        if version >= 7:
            state=b'\x13\0'+struct.pack('<QHBBB',1234567,40632,1,1,2) if original_version >= 7 else b''
            number('H', len(state)); data.extend(state)
    for text in (b'Fixture', b'stalker', b'bandage=1'): string(text)
    if version >= 5:
        string(b'profile\xe8\xe3\xf0\xee\xea' if original_version >= 5 else b''); string(b'profile history' if original_version >= 5 else b'')
    data.extend(b'\x01\x01\x00')
    packet('actor', bytes(range(32)))
    offsets['count'] = len(data); number('I', 2)
    item('item', b'bandage', 0, 8195)
    item('nested', b'wpn_pm', 1, 8194)
    if version >= 4: packet('progress', bytes(range(41)) if original_version >= 4 else b'')
    if version >= 6:
        number('I', 19 if original_version >= 6 else 1); string(b'request-id' if original_version >= 6 else b''); string(b'signature' if original_version >= 6 else b'')
        number('I', 1 if original_version >= 6 else 0)
        if original_version >= 6: item('safe', b'ammo_9x18_fmj', 0, 8195)
    if version >= 9:
        offsets['capacity']=len(data); number('I',240 if original_version >= 9 else 0)
    return bytes(data), offsets

source = r'''
#define _CRT_SECURE_NO_WARNINGS
#define NOMINMAX
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include <map>
#include <array>
#include <iostream>
#include <fstream>
#include <iterator>
#include <random>
#include <algorithm>
#include <immintrin.h>
#ifdef _WIN32
#include <windows.h>
#include <io.h>
#else
#include <unistd.h>
using __int64=long long;
#define _ftelli64 ftello
#define _fileno fileno
#define _commit fsync
#define MOVEFILE_REPLACE_EXISTING 1
#define MOVEFILE_WRITE_THROUGH 2
bool MoveFileExA(const char* from,const char* to,int){return std::rename(from,to)==0;}
bool DeleteFileA(const char* file){return std::remove(file)==0;}
#endif
#include "netcoop_save_checksum.h"
using u8=std::uint8_t;using u16=std::uint16_t;using u32=std::uint32_t;using u64=std::uint64_t;
using LPCSTR=const char*;using xr_string=std::string;using string_path=char[260];using string128=char[128];
template<class T>using xr_vector=std::vector<T>;
template<class K,class V>using xr_map=std::map<K,V>;
constexpr u32 _CPU_FEATURE_SSE4_2=1;
namespace CPU {struct {u32 feature=0;}ID;}
''' + core.replace('#include "stdafx.h"', '') + r'''
void to_lower(std::string& text){for(char& c:text)if(c>='A'&&c<='Z')c=char(c+('a'-'A'));}
size_t xr_strlen(const char* text){return std::strlen(text);}
template<size_t N,class... A>void xr_sprintf(char (&out)[N],const char* format,A... args){int count=std::snprintf(out,N,format,args...);assert(count>=0&&size_t(count)<N);}
struct {std::string path="candidate.bin";void update_path(char* out,const char*,const char*){std::strcpy(out,path.c_str());}}FS;
struct NET_Packet {struct {u32 count=0;alignas(8)u8 data[16384]={};}B;u32 r_pos=0;};
struct Settings {bool section_exist(const char* text){return std::string(text)=="bandage"||std::string(text)=="wpn_pm"||std::string(text)=="ammo_9x18_fmj";}}settings;
Settings* pSettings=&settings;
void Msg(const char*,...){}
u32 real_time_ms(){return 777;}
namespace netcoop {
struct CharacterCommit {std::string temp,path;xr_vector<u8> snapshot;u64 bytes=0;};
CharacterCommit fixture_commit;bool fixture_admit=true;
struct {void Enter(){}void Leave(){}}s_commit_lock;
bool s_commit_worker=true;
constexpr u64 character_commit_byte_limit=32ull*1024*1024;
void character_commit_worker(void*){}
void thread_spawn(void(*)(void*),const char*,int,void*){assert(false);}
void character_commits_flush(LPCSTR=nullptr){}
bool character_temp_path(const char* path,bool,char* temp){return std::snprintf(temp,260,"%s.tmp",path)>0;}
bool character_commit_enqueue(CharacterCommit&& value){if(!fixture_admit)return false;fixture_commit=std::move(value);return true;}
bool forbid_disk=false;
FILE* checked_open(const char* path,const char* mode){assert(!forbid_disk);return ::fopen(path,mode);}
#define fopen checked_open
''' + actual + r'''
}
using namespace netcoop;
std::vector<u8> bytes(const std::string& path){std::ifstream f(path,std::ios::binary);assert(f);return {std::istreambuf_iterator<char>(f),std::istreambuf_iterator<char>()};}
void write_bytes(const std::string& path,const std::vector<u8>& data){std::ofstream f(path,std::ios::binary);f.write(reinterpret_cast<const char*>(data.data()),data.size());assert(f);}
void select(const std::string& path,bool sse){FS.path=path;CPU::ID.feature=sse?_CPU_FEATURE_SSE4_2:0;s_characters.clear();}
Character* load(const std::string& path,bool sse){select(path,sse);return character_load("fixture",1);}
void equal(const Character& a,const Character& b){
 assert(a.name==b.name&&a.faction==b.faction&&a.loadout==b.loadout&&a.description==b.description&&a.history==b.history);
 assert(a.economy==b.economy&&a.initialized==b.initialized&&a.respawn==b.respawn);
 assert(a.actor.B.count==b.actor.B.count&&std::memcmp(a.actor.B.data,b.actor.B.data,a.actor.B.count)==0);
 assert(a.inventory_cells==b.inventory_cells);
 assert(a.progress==b.progress&&a.storage_revision==b.storage_revision&&a.storage_request==b.storage_request&&a.storage_signature==b.storage_signature);
 auto inventory=[](const auto& x,const auto& y){assert(x.size()==y.size());for(size_t i=0;i<x.size();++i){assert(x[i].section==y[i].section&&x[i].parent==y[i].parent&&x[i].place==y[i].place&&x[i].state==y[i].state);assert(x[i].spawn.B.count==y[i].spawn.B.count&&std::memcmp(x[i].spawn.B.data,y[i].spawn.B.data,x[i].spawn.B.count)==0);}};
 inventory(a.items,b.items);inventory(a.safe,b.safe);
}
int main(){
 const char* vector="123456789";
 assert(save_checksum::crc32c(vector,9)==0x1cf96d7c&&save_checksum::legacy_ieee(vector,9)==0xcbf43926);
 assert(save_checksum::crc32c(nullptr,0)==0xffffffff&&save_checksum::legacy_ieee(nullptr,0)==0);
 std::mt19937 random(173);alignas(8)std::array<u8,1024> sample{};
 for(unsigned n=0;n<300;++n){for(auto& b:sample)b=u8(random());unsigned length=random()%900;
  CPU::ID.feature=1;const auto hardware=crc32(sample.data(),length);assert(hardware==save_checksum::crc32c(sample.data(),length));
  CPU::ID.feature=0;const auto fallback=crc32(sample.data(),length);assert(fallback==save_checksum::legacy_ieee(sample.data(),length));
  assert(character_checksum(sample.data(),length)==hardware);CPU::ID.feature=1;assert(character_checksum(sample.data(),length)==hardware);
  CPU::ID.feature=0;
  for(unsigned offset=1;offset<8;++offset){assert(character_checksum_matches(sample.data()+offset,length,save_checksum::crc32c(sample.data()+offset,length),false));}
 }
 for(int version=3;version<=9;++version)for(const char* algorithm:{"sse","ieee"}){
  const std::string file="v"+std::to_string(version)+"_"+algorithm+".bin";
  const auto original=bytes(file);
  if(version>=8&&std::string(algorithm)=="ieee"){assert(!load(file,false)&&!load(file,true));continue;}
  assert(load(file,false));Character reference=*load(file,false);assert(load(file,true));equal(reference,*load(file,true));
  assert(reference.items.size()==2&&reference.actor.B.count==32);
  assert(reference.items[1].parent==1&&reference.items[0].spawn.B.count==31);
  assert(reference.items[0].place==(version>=4?8195:0));
  assert(reference.progress.size()==(version>=4?41:0)&&reference.safe.size()==(version>=6?1:0));
  assert(reference.items[0].state.size()==(version>=7?15:0));
  assert(reference.inventory_cells==(version>=9?240u:0u));
  if(version>=6)assert(reference.safe[0].spawn.B.count==31&&reference.storage_revision==19);
  assert(bytes(file)==original); // read/admission never rewrites an old snapshot
  select("portable-soft.bin",false);assert(character_save(reference));const auto soft=bytes(FS.path);
  select("portable-hard.bin",true);assert(character_save(reference));assert(soft==bytes(FS.path));
  assert(soft[0]=='N'&&soft[1]=='C'&&soft[2]=='H'&&soft[3]=='9');
  assert(soft==bytes("upgraded-v"+std::to_string(version)+".bin"));
  // Autosave must not open/create a file on the producer. It owns a complete
  // immutable byte image even if the actor/inventory/progress changes next.
  select("queued-v"+std::to_string(version)+".bin",false);std::remove(FS.path.c_str());
  forbid_disk=true;assert(character_save(reference,true));forbid_disk=false;
  assert(!std::ifstream(FS.path));assert(fixture_commit.snapshot==soft);
  const Character saved=reference;reference.actor.B.data[0]^=1;reference.items[0].spawn.B.data[0]^=1;
  reference.items[0].state.assign(4,99);reference.progress.assign(8,42);reference.name="changed";
  assert(fixture_commit.snapshot==soft);reference=saved;
  assert(character_commit_file(fixture_commit));assert(bytes(FS.path)==soft);
  fixture_admit=false;reference.last_save=321;forbid_disk=true;
  assert(!character_save(reference,true)&&reference.last_save==321);forbid_disk=false;fixture_admit=true;
  assert(bytes(FS.path)==soft);
  // Reject malformed snapshots before any disk/queue mutation, never truncate.
  for(unsigned invalid=0;invalid<7;++invalid){
   Character bad=reference;
   if(invalid==0)bad.items[0].state.resize(513);
   if(invalid==1)bad.actor.B.count=16385;
   if(invalid==2)bad.items[0].parent=1;
   if(invalid==3)bad.history.resize(1537,'x');
   if(invalid==4)bad.progress.resize(1048577);
   if(invalid==5)bad.name=std::string("bad\0name",8);
   if(invalid==6)bad.inventory_cells=513;
   std::vector<u8> output{1,2,3};assert(!character_snapshot(bad,output)&&output.empty());
   forbid_disk=true;assert(!character_save(bad,true));forbid_disk=false;
   assert(bytes(FS.path)==soft);
  }
  assert(load("portable-soft.bin",true));equal(reference,*load("portable-soft.bin",true));
  assert(load("portable-hard.bin",false));equal(reference,*load("portable-hard.bin",false));
 }
 // Restore admission rejects bad checksums, not just an unsupported CPU.
 std::ifstream corrupt_list("corrupt.txt");std::string path;
 while(std::getline(corrupt_list,path)){assert(!load(path,false)&&!load(path,true));}
 const auto good=bytes("v8_sse.bin");
 for(size_t end=0;end<good.size();++end){write_bytes("truncated.bin",{good.begin(),good.begin()+end});assert(!load("truncated.bin",false));}
 auto extra=good;extra.push_back(0);write_bytes("extra.bin",extra);assert(!load("extra.bin",true));
 // Master replies use the same actual decoder without touching any file.
 select("no-such-local-character.bin",true);
 assert(character_load_image("fixture",1,good.data(),good.size()));
 Character retained=*character_load("fixture",1);
 for(size_t end=0;end<good.size();++end){
  assert(!character_load_image("fixture",1,good.data(),end));
  equal(retained,*character_load("fixture",1));
 }
 assert(!character_load_image("fixture",1,nullptr,0));
 fixture_master_refuses=true;assert(!character_save(retained,true));fixture_master_refuses=false;
 equal(retained,*character_load("fixture",1));
 // Explicitly reproduce the old loader's opposite-hardware checksum failure.
 assert(save_checksum::crc32c(sample.data(),900)!=save_checksum::legacy_ieee(sample.data(),900));
 std::cout<<"PASS actual NCH3..9 reader/durable writer, both actual CPU CRC paths, independent golden byte images, no autosave producer IO, immutable queued snapshots, refused malformed/overflow payloads, legacy upgrade, opposite CPU, empty progress, inventory/safe/profile preservation, corruption/truncation/unknown-version rejection\n";
}
'''
# The full actual loader caches admitted characters; declare its cache before it.
# The cache is declared before both memory and legacy-file loaders.

with TemporaryDirectory(prefix='lostzone-checksum-') as temp:
    folder = Path(temp)
    corrupt = []
    for version in range(3,10):
        (folder/f'upgraded-v{version}.bin').write_bytes(legacy(version,crc32c,upgrade=True)[0])
        for name, algorithm in (('sse',crc32c),('ieee',zlib.crc32)):
            data, offsets = legacy(version,algorithm)
            (folder/f'v{version}_{name}.bin').write_bytes(data)
            for label in ('actor','item','nested','progress','safe'):
                if label not in offsets: continue
                changed = bytearray(data); changed[offsets[label]] ^= 0x80
                path = f'bad_{version}_{name}_{label}.bin'
                (folder/path).write_bytes(changed); corrupt.append(path)
    good, offsets = legacy(8,crc32c)
    for label, mutate in (
        ('version',lambda d: d.__setitem__(3,ord('A'))),
        ('count',lambda d: d.__setitem__(slice(offsets['count'],offsets['count']+4),struct.pack('<I',513))),
        ('packet',lambda d: d.__setitem__(slice(offsets['actor']-8,offsets['actor']-4),struct.pack('<I',16385))),
    ):
        changed=bytearray(good);mutate(changed);path=f'bad_{label}.bin'
        (folder/path).write_bytes(changed);corrupt.append(path)
    (folder/'corrupt.txt').write_text('\n'.join(corrupt)+'\n',encoding='utf-8')
    cpp=folder/'check.cpp';cpp.write_text(source,encoding='utf-8')
    exe=folder/('check.exe' if os.name=='nt' else 'check')
    include=root/'src/xrGame'
    if os.name=='nt':
        command=['cl','/nologo','/EHsc','/std:c++17','/W4',f'/I{include}',str(cpp),f'/Fe:{exe}']
    else:
        command=['g++','-std=c++17','-O1','-g','-Wall','-Wextra','-msse4.2','-fsanitize=address,undefined',
                 '-fno-omit-frame-pointer',f'/I{include}'.replace('/I','-I',1),str(cpp),'-o',str(exe)]
    subprocess.run(command,cwd=folder,check=True)
    subprocess.run([str(exe)],cwd=folder,check=True)
