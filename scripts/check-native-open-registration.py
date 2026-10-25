"""CI only: execute the actual admission prefix of finish_auth, including bans."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import sys as _sys; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from netcoop_source import netcoop_cpp

root=Path(__file__).resolve().parents[1]
text=netcoop_cpp(root, encoding='utf-8-sig')
start=text.index('static bool finish_auth(')
end=text.index('    // Slot zero authenticates',start)
admission=text[start:end]+'    return false;\n}\n' # the world master phase follows the prefix (doc 135)
start=text.index('static bool read_account_link(')
link_reader=text[start:text.index('\nvoid server_on_auth(',start)]
source=r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <map>
#include <string>
#include <vector>
#include <cstring>
using u32=unsigned;using LPCSTR=const char*;using xr_string=std::string;
enum Role {role_none,role_player,role_admin};
struct Account {
 xr_string login,salt,hash,device,firebase_uid;Role role=role_player;
 unsigned approval=1,money=0,failures=0,locked_until=0;bool touched=false,has_money=false;
};
struct xrClientData {unsigned ID=1;xr_string netcoop_login;Role netcoop_role=role_none;};
struct PendingAuth {
 unsigned client=1;xr_string login="Player",salt="fixture-salt",hash="fixture-digest",device="fixture-device",firebase_uid,legacy_hash;
 bool create=false,hashed=true,firebase=false;
};
struct LoginInUse {xr_string login;xrClientData* self=nullptr;};
std::map<xr_string,Account> s_accounts;bool s_accounts_dirty=false;
xrClientData test_client;unsigned saves=0;xr_string rejection;bool banned=false;
struct xrServer {
 bool disconnected=false,duplicate=false;
 xrClientData* ID_to_client(unsigned){return disconnected?nullptr:&test_client;}
 xrClientData* FindClient(const LoginInUse&){return duplicate?&test_client:nullptr;}
};
void to_lower(xr_string& value){for(char& c:value)c=char(std::tolower(static_cast<unsigned char>(c)));}
Account* account_find(LPCSTR name){xr_string key=name;to_lower(key);auto i=s_accounts.find(key);return i==s_accounts.end()?nullptr:&i->second;}
void accounts_save(){++saves;s_accounts_dirty=false;}
bool accounts_available(){return true;}
void reject(xrServer*,xrClientData*,LPCSTR reason){rejection=reason;}
bool constant_time_equal(const xr_string& a,const xr_string& b){return a==b;}
bool server_banned(const xr_string&,const xr_string&){return banned;}
u32 GetTickCount(){return 1000;}
void Msg(LPCSTR,...){ }
struct NET_Packet {
 std::vector<unsigned char> bytes;u32 pos=0;
 u32 r_tell()const{return pos;}u32 r_elapsed()const{return u32(bytes.size())-pos;}
 void r_seek(u32 p){assert(p<=bytes.size());pos=p;}
 u32 r_u32(){assert(r_elapsed()>=4);u32 v=0;for(unsigned i=0;i<4;++i)v|=u32(bytes[pos++])<<(8*i);return v;}
};
bool read_string(NET_Packet& p,char* out,unsigned capacity){
 unsigned n=0;while(p.r_elapsed()){char c=char(p.bytes[p.pos++]);if(!c){out[n]=0;return true;}
 if(n+1>=capacity)return false;out[n++]=c;}return false;
}
bool key_valid(LPCSTR key){return std::strlen(key)==64 && std::strspn(key,"0123456789abcdef")==64;}
void SecureZeroMemory(void* p,unsigned n){std::memset(p,0,n);}
''' + admission + link_reader + r'''
void reset(){s_accounts.clear();s_accounts_dirty=false;test_client={};saves=0;rejection.clear();banned=false;}
Account legacy(unsigned approval,Role role=role_player){
 Account a;a.login="Player";a.salt="fixture-salt";a.hash="fixture-digest";a.device="fixture-device";
 a.role=role;a.approval=approval;a.has_money=true;a.money=5000;return a;
}
int main(){
 xrServer server;PendingAuth request;
 for(unsigned old: {0u,1u,2u})for(Role role: {role_player,role_admin}){
  reset();s_accounts["player"]=legacy(old,role);finish_auth(&server,&request);
  assert(rejection.empty() && test_client.netcoop_login=="Player" && test_client.netcoop_role==role);
  const auto& a=s_accounts.at("player");assert(a.approval==1 && saves==(old==1?0u:1u));
  assert(a.role==role && a.money==5000 && a.has_money && a.salt==request.salt && a.hash==request.hash && a.device==request.device);
 }
 reset();request.create=true;finish_auth(&server,&request);
 assert(rejection.empty() && saves==1 && s_accounts.at("player").approval==1);
 assert(test_client.netcoop_role==role_player && s_accounts.at("player").role==role_player);
 reset();request.hashed=false;finish_auth(&server,&request);
 assert(!rejection.empty() && s_accounts.empty() && test_client.netcoop_role==role_none && !saves);
 request.hashed=true;request.create=false;
 for(unsigned old: {0u,2u}){
  reset();s_accounts["player"]=legacy(old);request.hash="wrong-fixture-digest";finish_auth(&server,&request);
  assert(rejection=="Wrong password" && test_client.netcoop_role==role_none);
  assert(s_accounts.at("player").approval==old && !saves);
  request.hash="fixture-digest";
  reset();s_accounts["player"]=legacy(old);request.device="other-fixture-device";finish_auth(&server,&request);
  assert(!rejection.empty() && test_client.netcoop_role==role_none && s_accounts.at("player").approval==old && !saves);
  request.device="fixture-device";
  reset();s_accounts["player"]=legacy(old);banned=true;finish_auth(&server,&request);
  assert(rejection=="You are banned on this server" && test_client.netcoop_role==role_none);
  assert(s_accounts.at("player").approval==old && !saves);
 }
 reset();s_accounts["player"]=legacy(0);server.duplicate=true;finish_auth(&server,&request);
 assert(rejection=="This account is already online" && !saves);server.duplicate=false;
 reset();request.firebase=true;request.firebase_uid="fixture-uid";s_accounts["player"]=legacy(0);
 s_accounts["player"].firebase_uid="different-fixture-uid";finish_auth(&server,&request);
 assert(rejection=="Wrong password" && !saves && test_client.netcoop_role==role_none);
 reset();s_accounts["player"]=legacy(0);s_accounts["player"].firebase_uid=request.firebase_uid;finish_auth(&server,&request);
 assert(rejection.empty() && saves==1 && test_client.netcoop_role==role_player);
 assert(s_accounts.at("player").firebase_uid==request.firebase_uid);
 reset();server.disconnected=true;finish_auth(&server,&request);assert(s_accounts.empty() && !saves && rejection.empty());
 server.disconnected=false;
 // The 17.5 password migration erased the Google UID. Device alone cannot
 // restore it: a verified Google identity AND the remembered old password
 // are required, with all normal device/ban checks before persistence.
 for(const xr_string proof: {xr_string(),xr_string("wrong"),xr_string("fixture-digest")}){
  reset();s_accounts["player"]=legacy(1,role_admin);request.legacy_hash=proof;finish_auth(&server,&request);
  const auto& a=s_accounts.at("player");
  if(proof=="fixture-digest"){
   assert(rejection.empty() && saves==1 && a.firebase_uid==request.firebase_uid && test_client.netcoop_role==role_admin);
   assert(a.hash=="fixture-digest" && a.salt=="fixture-salt" && a.money==5000);
  }else assert(rejection=="Wrong password" && !saves && a.firebase_uid.empty());
 }
 for(bool ban: {false,true}){
  reset();s_accounts["player"]=legacy(1);banned=ban;request.device=ban?"fixture-device":"other";
  finish_auth(&server,&request);assert(!rejection.empty() && !saves && s_accounts.at("player").firebase_uid.empty());
 }
 request.device="fixture-device";
 reset();s_accounts["player"]=legacy(1);s_accounts["player"].firebase_uid="another-google-user";
 finish_auth(&server,&request);assert(rejection=="Wrong password" && !saves);
 // Matching verified Google UID works independently of an obsolete cached password.
 reset();s_accounts["player"]=legacy(1);s_accounts["player"].firebase_uid=request.firebase_uid;
 request.legacy_hash="obsolete";finish_auth(&server,&request);assert(rejection.empty() && !saves);
 // Optional proof must not eat the storage marker of old/new clients.
 for(unsigned n: {0u,1u,3u,4u,16u}){
  NET_Packet p;p.bytes.assign(n,0x54);xr_string key;assert(read_account_link(p,key) && p.pos==0 && key.empty());
 }
 for(bool terminate: {false,true}){
  NET_Packet p;p.bytes={0x4c,0x5a,0x4c,0x4b};p.bytes.insert(p.bytes.end(),64,'a');
  if(terminate){p.bytes.push_back(0);p.bytes.insert(p.bytes.end(),{0x4c,0x5a,0x53,0x54});}
  xr_string key;assert(read_account_link(p,key)==terminate);
  if(terminate)assert(key==xr_string(64,'a') && p.r_u32()==0x54535a4c);
 }
 NET_Packet invalid;invalid.bytes={0x4c,0x5a,0x4c,0x4b,'z',0};xr_string key;assert(!read_account_link(invalid,key));
}
'''
if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Native fixture compiles only in GitHub Actions; no local compiler invocation.')
with TemporaryDirectory(prefix='open-registration-') as temporary:
    target=Path(temporary);cpp=target/'auth.cpp';exe=target/('auth.exe' if os.name=='nt' else 'auth')
    cpp.write_text(source,encoding='utf-8')
    args=(['cl','/nologo','/std:c++17','/EHsc','/W4','/WX',str(cpp),'/Fe:'+str(exe)] if os.name=='nt'
          else ['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)])
    subprocess.run(args,cwd=target,check=True);subprocess.run([str(exe)],cwd=target,check=True)
print('PASS actual auth admission/link parser: verified Google plus old password recovery, storage rewind, truncated proof rejection; roles/credentials retained, wrong password/device/identity, duplicate login and bans denied')
