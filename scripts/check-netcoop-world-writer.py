"""CI-only native writer transport against the real durable HTTP master."""
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import json
import base64
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import time

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks must run in GitHub Actions")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from lostzone import Store, World
from lostzone.http import Credentials, Dispatcher, Server
from lostzone.__main__ import create_config, create_writer_config
from lostzone.native_save import identity
sys.path.insert(0, str(root / "backend/tests"))
from test_native_save import native_fixture

source = r'''
#define NOMINMAX
#include "netcoop_checkpoint_outbox.h"
#include "netcoop_checkpoint_worker.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <set>
#include <atomic>
#include <thread>
using namespace netcoop_world;
template<class F>void rejects(F f){bool failed=false;try{f();}catch(const std::exception&){failed=true;}assert(failed);}
#ifdef _WIN32
std::string text_file(const char* filename){std::ifstream in(filename,std::ios::binary);return std::string(std::istreambuf_iterator<char>(in),{});}
std::wstring wide(const std::string& value){
 const int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,value.data(),int(value.size()),nullptr,0);assert(count>0);
 std::wstring result(std::size_t(count),L'\0');assert(MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,value.data(),int(value.size()),&result[0],count)==count);return result;
}
std::wstring outbox_root(const char* fixture){return wide(fixture)+L".outbox \u043e\u0447\u0435\u0440\u0435\u0434\u044c";}
std::string disk_read(const std::wstring& name){
 HANDLE f=CreateFileW(name.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);assert(f!=INVALID_HANDLE_VALUE);
 LARGE_INTEGER size{};assert(GetFileSizeEx(f,&size) && size.QuadPart>=0 && size.QuadPart<=21*1024*1024);
 std::string bytes(std::size_t(size.QuadPart),'\0');DWORD got=0;
 assert(bytes.empty() || (ReadFile(f,&bytes[0],DWORD(bytes.size()),&got,nullptr) && got==bytes.size()));CloseHandle(f);return bytes;
}
void disk_write(const std::wstring& name,const std::string& bytes){
 HANDLE f=CreateFileW(name.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,0,nullptr);assert(f!=INVALID_HANDLE_VALUE);DWORD got=0;
 assert(WriteFile(f,bytes.data(),DWORD(bytes.size()),&got,nullptr) && got==bytes.size() && FlushFileBuffers(f));CloseHandle(f);
}
std::wstring job_file(const std::wstring& root){
 const auto index=bridge_json(disk_read(root+L"\\outbox.json"),outbox_index_limit);
 const auto tx=index["jobs"][0]["transaction"].get<std::string>();return root+L"\\snapshot-"+wide(tx)+L".nch";
}
CheckpointCapture job(std::string character,std::uint64_t generation,std::uint64_t fence,std::uint64_t session,
 std::uint64_t version,std::uint64_t revision){return {std::move(character),generation,fence,session,version,revision,1};}
void outbox_crash(char** argv){
 const auto cfg=WriterConfig::parse(text_file(argv[2]),"garbage");
 const auto context=bridge_json(text_file(argv[6]),4096);
 const auto instance=context["instance"].get<std::string>(),character=context["character"].get<std::string>();
 const auto epoch=bridge_unsigned(context,"epoch");
 CheckpointOutbox queue(outbox_root(argv[3]),cfg,instance,epoch);
 auto request=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& result,unsigned& status){
  const bool ok=writer_request(cfg,instance,epoch,method,path,payload,result,status);
  if(ok && bridge_json(payload,65536)["operation"]=="native_save_finish"){
   // Hard process death AFTER SQLite commit and BEFORE local cursor write.
   TerminateProcess(GetCurrentProcess(),73);std::abort();
  }
  return ok;
 };
 for(unsigned i=0;i<100;++i) assert(queue.advance(character,request)==CheckpointStep::Progress);
 assert(false && "crash fixture did not reach Finish");
}
void kill_after_master_commit(char** argv,const std::string& instance,std::uint64_t epoch,const std::string& character){
 const std::string context_name=std::string(argv[3])+".crash-context.json";
 {std::ofstream out(context_name,std::ios::binary);out<<BridgeJson{{"instance",instance},{"epoch",epoch},{"character",character}}.dump();assert(out.good());}
 wchar_t executable[4096]{};assert(GetModuleFileNameW(nullptr,executable,4096));
 std::wstring command=L"\""+std::wstring(executable)+L"\"";
 for(unsigned i=1;i<5;++i) command+=L" \""+wide(argv[i])+L"\"";
 command+=L" --outbox-crash \""+wide(context_name)+L"\"";
 STARTUPINFOW start{};start.cb=sizeof(start);PROCESS_INFORMATION child{};
 assert(CreateProcessW(nullptr,&command[0],nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,nullptr,&start,&child));
 const auto waited=WaitForSingleObject(child.hProcess,15000);
 if(waited!=WAIT_OBJECT_0) TerminateProcess(child.hProcess,74);
 DWORD code=0;assert(GetExitCodeProcess(child.hProcess,&code));CloseHandle(child.hThread);CloseHandle(child.hProcess);
 assert(waited==WAIT_OBJECT_0 && code==73);
}
void outbox_checks(char** argv,const WriterConfig& config,const std::string& instance,std::uint64_t epoch,
 const std::string& character,std::uint64_t fence,std::uint64_t session,const std::string& raw,
 const std::string& next_raw,const std::string& last_raw){
 const auto root=outbox_root(argv[3]),index=root+L"\\outbox.json";
 auto actual=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& result,unsigned& status){
  return writer_request(config,instance,epoch,method,path,payload,result,status);
 };
 auto newest=job(character,30,fence,session,9,4);
 {
  CheckpointOutbox queue(root,config,instance,epoch);
  auto captured=raw;assert(queue.enqueue(job(character,10,fence,session,7,2),captured));
  captured.assign("NCH9 producer changed after admission");assert(disk_read(job_file(root))==raw);
  assert(queue.enqueue(job(character,20,fence,session,8,3),next_raw));
  assert(queue.pending()==std::vector<std::string>{character});
  rejects([&]{CheckpointOutbox duplicate(root,config,instance,epoch);});
  rejects([&]{queue.completion(character);});rejects([&]{queue.retire(character,10);});
  assert(!queue.enqueue(job(character,10,fence,session,7,2),raw));
  rejects([&]{queue.enqueue(job(character,30,fence,session,10,4),last_raw);});
  rejects([&]{queue.enqueue(job(character,30,fence,session+1,9,4),last_raw);});
  const auto before=disk_read(index);
  HANDLE held=CreateFileW(index.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);assert(held!=INVALID_HANDLE_VALUE);
  assert(!queue.enqueue(newest,last_raw));assert(disk_read(index)==before && queue.accepted_generation(character)==20);CloseHandle(held);
  assert(queue.enqueue(newest,last_raw)); // Same generation remains admissible after failed journal publication.
 }
 kill_after_master_commit(argv,instance,epoch,character);
 {
  CheckpointOutbox queue(root,config,instance,epoch);
  rejects([&]{queue.completion(character);});
  const auto before=disk_read(index);
  HANDLE held=CreateFileW(index.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);assert(held!=INVALID_HANDLE_VALUE);
  assert(queue.advance(character,actual)==CheckpointStep::Retry);rejects([&]{queue.completion(character);});
  assert(disk_read(index)==before);CloseHandle(held);
  assert(queue.advance(character,actual)==CheckpointStep::Complete);
  auto completed=queue.completion(character);assert(completed["generation"]==10 && completed["latest_accepted"]==false);
  assert(completed["result"]["revision"]==3 && completed["result"]["entity_version"]==8);
  assert(!queue.retire(character,20));
  held=CreateFileW(index.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);assert(held!=INVALID_HANDLE_VALUE);
  assert(!queue.retire(character,10));CloseHandle(held);assert(queue.retire(character,10));
  assert(!queue.enqueue(job(character,10,fence,session,7,2),raw));
  for(unsigned generation:{20U,30U}){
   rejects([&]{queue.completion(character);});
   CheckpointStep step=CheckpointStep::Progress;
   for(unsigned tries=0;tries<20 && step!=CheckpointStep::Complete;++tries){step=queue.advance(character,actual);assert(step!=CheckpointStep::Rejected);}
   assert(step==CheckpointStep::Complete);
   completed=queue.completion(character);
   assert(completed["generation"]==generation && completed["latest_accepted"]==(generation==30));
   assert(completed["result"]["revision"]==(generation==20 ? 4:5));
   if(generation==20) assert(queue.retire(character,generation));
  }
 }
 const auto committed_index=disk_read(index),committed_snapshot=disk_read(job_file(root));
 rejects([&]{CheckpointOutbox stale(root,config,instance,epoch+1);});
 rejects([&]{CheckpointOutbox stale(root,config,std::string(32,'9'),epoch);});
 assert(disk_read(index)==committed_index && disk_read(job_file(root))==committed_snapshot);
 {
  CheckpointOutbox queue(root,config,instance,epoch);rejects([&]{queue.completion(character);});
  auto refused=[](const std::string&,const std::string&,const std::string&,BridgeJson& out,unsigned& status){out=BridgeJson();status=409;return false;};
  assert(queue.advance(character,refused)==CheckpointStep::Rejected);rejects([&]{queue.completion(character);});
  assert(queue.advance(character,actual)==CheckpointStep::Complete && queue.completion(character)["latest_accepted"]==true);
  assert(queue.retire(character,30) && queue.pending().empty());
 }
 {CheckpointOutbox queue(root,config,instance,epoch);assert(queue.pending().empty() && queue.accepted_generation(character)==30 && !queue.enqueue(newest,last_raw));}
 CheckpointDownload restored(character,fence,session,5,checkpoint_sha256(last_raw),last_raw.size());
 for(unsigned i=0;i<20 && restored.step(actual)!=CheckpointStep::Complete;++i){}
 assert(restored.bytes()==last_raw);
 // Recovery validates all references before deleting any unreferenced file.
 const auto damaged=root+L".damaged";
 {CheckpointOutbox queue(damaged,config,instance,epoch);assert(queue.enqueue(job(character,1,fence,session,10,5),raw));}
 const auto snapshot=job_file(damaged),orphan=damaged+L"\\snapshot-00000000000000000000000000000000.nch";
 const auto saved=disk_read(snapshot);
 auto bad=saved;bad.back()=char(static_cast<unsigned char>(bad.back())^1U);disk_write(snapshot,bad);disk_write(orphan,"unaccepted crash residue");
 rejects([&]{CheckpointOutbox queue(damaged,config,instance,epoch);});assert(disk_read(snapshot)==bad && disk_read(orphan)=="unaccepted crash residue");
 disk_write(snapshot,saved);
 disk_write(damaged+L"\\unrelated.txt","leave me intact");
 rejects([&]{CheckpointOutbox queue(damaged,config,instance,epoch);});assert(disk_read(orphan)=="unaccepted crash residue");
 assert(DeleteFileW((damaged+L"\\unrelated.txt").c_str()));disk_write(damaged+L"\\outbox.next","partial index");
 {CheckpointOutbox queue(damaged,config,instance,epoch);assert(queue.pending().size()==1);}
 assert(GetFileAttributesW(orphan.c_str())==INVALID_FILE_ATTRIBUTES && GetFileAttributesW((damaged+L"\\outbox.next").c_str())==INVALID_FILE_ATTRIBUTES);
 const auto missing=damaged+L".saved-index";
 assert(MoveFileExW((damaged+L"\\outbox.json").c_str(),missing.c_str(),MOVEFILE_WRITE_THROUGH));
 rejects([&]{CheckpointOutbox queue(damaged,config,instance,epoch);});assert(disk_read(snapshot)==saved);
 assert(MoveFileExW(missing.c_str(),(damaged+L"\\outbox.json").c_str(),MOVEFILE_WRITE_THROUGH));
 const auto linked=damaged+L".link-target";disk_write(linked,"never truncate a hardlink peer");
 assert(CreateHardLinkW((damaged+L"\\outbox.next").c_str(),linked.c_str(),nullptr));
 rejects([&]{CheckpointOutbox queue(damaged,config,instance,epoch);});assert(disk_read(linked)=="never truncate a hardlink peer");
 assert(DeleteFileW((damaged+L"\\outbox.next").c_str()));
 {CheckpointOutbox queue(damaged,config,instance,epoch);assert(queue.pending().size()==1);}
 // Count and byte budgets are actual filesystem admission, with no HTTP.
 const auto bounded=root+L".bounded";
 {
  CheckpointOutbox queue(bounded,config,instance,epoch);
  for(unsigned i=0;i<outbox_jobs;++i){char name[33];std::snprintf(name,sizeof(name),"%032x",i+1);assert(queue.enqueue(job(name,1,1,1,1,0),"NCH9"));}
  assert(!queue.enqueue(job(std::string(32,'f'),1,1,1,1,0),"NCH9"));
 }
 {CheckpointOutbox queue(bounded,config,instance,epoch);assert(queue.pending().size()==outbox_jobs);}
 {
  CheckpointOutbox queue(root+L".bytes",config,instance,epoch);
  std::string large(checkpoint_limit,'x');large.replace(0,4,"NCH9");
  for(unsigned i=0;i<3;++i) assert(queue.enqueue(job(std::string(32,char('a'+i)),1,1,1,1,0),large));
  assert(!queue.enqueue(job(std::string(32,'d'),1,1,1,1,0),large));
  large.resize(4*1024*1024);assert(queue.enqueue(job(std::string(32,'d'),1,1,1,1,0),large));
  assert(!queue.enqueue(job(std::string(32,'e'),1,1,1,1,0),"NCH9"));
 }
 std::cout<<"PASS durable checkpoint outbox: hard process death after SQLite Finish, same-command replay, per-character FIFO/generation barrier, disk-publication failures, fresh proof after restart, fencing, exact latest bytes\n";
 std::cout<<"PASS actual outbox files: exclusive process lock, Unicode path, count/64MiB budget, corruption/missing index preserved, bounded orphan cleanup, unknown files and hardlinks refused\n";
}
unsigned worker_wait_stage=0;
template<class F>void eventually(F condition){
 const auto stage=++worker_wait_stage;
 const auto end=GetTickCount64()+10000;
 while(!condition()){
  if(GetTickCount64()>=end){std::cerr<<"checkpoint worker wait stage "<<stage<<" timed out\n";assert(false);}
  Sleep(5);
 }
}
void worker_checks(char** argv,const std::string& instance,std::uint64_t epoch,const std::string& character,
 std::uint64_t fence,std::uint64_t session,const std::string& next_raw,const std::string& last_raw){
 const auto root=outbox_root(argv[3])+L".worker";
 CheckpointWorkerScope context;std::memcpy(context.location,"garbage",8);std::memcpy(context.instance,instance.c_str(),33);
 context.world=71;context.epoch=epoch;context.fence=fence;context.lease_ms=3000;
 auto ticket=[&](std::uint64_t generation,std::uint64_t version,std::uint64_t revision){
  CheckpointWorkerCapture result;std::memcpy(result.character,character.c_str(),33);
  result.generation=generation;result.session=session;result.version=version;result.revision=revision;result.slot=1;return result;
 };
 CheckpointWorkerResult result;result.revision=999;
 CheckpointWorker worker;assert(!worker.poll(nullptr,1,result) && result.revision==0);
 assert(!worker.submit(ticket(1,10,5),last_raw.data(),last_raw.size()));
 assert(worker.start(argv[2],root.c_str(),context));
 eventually([&]{return worker.status().ready;});
 std::uint64_t floor=99;assert(worker.generation_floor(character.c_str(),floor) && floor==0);
 assert(!worker.release(character.c_str(),1));
 assert(worker.submit(ticket(1,10,5),next_raw.data(),next_raw.size()));
 eventually([&]{return worker.poll(character.c_str(),1,result) && result.state==CheckpointCaptureState::Durable;});
 assert(result.latest_submitted && result.revision==6 && result.version==11 && result.bytes==next_raw.size());
 // Block publication of a NEW capture while keeping an older durable receipt.
 // The renewal thread must continue despite the pump's storage failures.
 HANDLE held=CreateFileW((root+L"\\outbox.next").c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,0,nullptr);
 assert(held!=INVALID_HANDLE_VALUE);
 auto mutable_capture=last_raw;
 assert(worker.submit(ticket(2,11,6),mutable_capture.data(),mutable_capture.size()));mutable_capture.assign("producer changed");
 eventually([&]{return worker.status().storage_error;});
 assert(worker.poll(character.c_str(),1,result) && result.state==CheckpointCaptureState::Durable && !result.latest_submitted);
 assert(worker.poll(character.c_str(),2,result) && result.state==CheckpointCaptureState::Buffered);
 const auto renewals=worker.status().lease_renewals;
 Sleep(3500);assert(worker.status().lease_renewals>=renewals+2 && !worker.status().authority_lost);
 assert(worker.release(character.c_str(),1));
 CloseHandle(held);
 eventually([&]{return !worker.poll(character.c_str(),1,result);});
 eventually([&]{return worker.poll(character.c_str(),2,result) && result.state==CheckpointCaptureState::Durable;});
 assert(result.latest_submitted && result.revision==7 && result.version==12 && std::string(result.sha256)==checkpoint_sha256(last_raw));
 assert(!worker.submit(ticket(1,10,5),next_raw.data(),next_raw.size()));
 assert(worker.stop());
 // Only the disk-refusal/independent-renewal case deliberately uses3s.
 // Later 32-file/64MiB shutdown-drain cases use the normal15s lease:
 // filesystem staging has no promise to finish inside the short test TTL.
 context.lease_ms=15000;
 // Reopen the real journal and obtain fresh Finish proof; no new save revision.
 assert(worker.start(argv[2],root.c_str(),context));eventually([&]{return worker.status().ready;});
 assert(worker.generation_floor(character.c_str(),floor) && floor==2);
 eventually([&]{return worker.poll(character.c_str(),2,result) && result.state==CheckpointCaptureState::Durable;});
 assert(result.revision==7 && result.latest_submitted);
 assert(worker.release(character.c_str(),2));eventually([&]{return !worker.poll(character.c_str(),2,result);});
 assert(worker.stop());
 assert(worker.start(argv[2],root.c_str(),context));eventually([&]{return worker.status().ready;});
 assert(worker.generation_floor(character.c_str(),floor) && floor==2);
 // The shared count budget includes memory, spool and unconsumed receipts.
 for(unsigned i=0;i<outbox_jobs;++i) assert(worker.submit(ticket(i+3,i+12,i+7),last_raw.data(),last_raw.size()));
 assert(worker.status().captures==outbox_jobs);
 assert(!worker.submit(ticket(35,44,39),last_raw.data(),last_raw.size()));
 eventually([&]{return worker.poll(character.c_str(),3,result) && result.state==CheckpointCaptureState::Durable;});
 assert(result.revision==8 && !result.latest_submitted);
 assert(worker.stop()); // Stages all remaining accepted memory, not a network drain.
 {
  const auto config=WriterConfig::parse(text_file(argv[2]),"garbage");
  CheckpointOutbox recovered(root,config,instance,epoch);assert(recovered.captures().size()==outbox_jobs);
  assert(recovered.accepted_generation(character)==34);
 }
 // Concurrent producers use different identities; the master refuses their
 // unknown entities, and the worker retains those staged refusals for recovery.
 assert(worker.start(argv[2],(root+L".concurrent").c_str(),context));eventually([&]{return worker.status().ready;});
 std::atomic<unsigned> accepted{0};std::vector<std::thread> producers;
 for(unsigned thread=0;thread<4;++thread) producers.emplace_back([&,thread]{
  for(unsigned i=0;i<8;++i){auto value=ticket(1,1,0);std::snprintf(value.character,sizeof(value.character),"%032x",100+thread*8+i);
   if(worker.submit(value,"NCH9",4)) ++accepted;}
 });
 for(auto& producer:producers) producer.join();assert(accepted==32 && worker.status().captures==32);
 assert(worker.stop());
 assert(worker.start(argv[2],(root+L".bytes").c_str(),context));eventually([&]{return worker.status().ready;});
 std::string large(checkpoint_limit,'x');large.replace(0,4,"NCH9");
 for(unsigned i=0;i<3;++i){auto value=ticket(1,1,0);std::memset(value.character,char('a'+i),32);assert(worker.submit(value,large.data(),large.size()));}
 auto value=ticket(1,1,0);std::memset(value.character,'d',32);assert(!worker.submit(value,large.data(),large.size()));
 large.resize(4*1024*1024);assert(worker.submit(value,large.data(),large.size()));
 std::memset(value.character,'e',32);assert(!worker.submit(value,"NCH9",4));assert(worker.status().bytes==outbox_bytes);
 assert(worker.stop());
 // An already-owned scope is REQUIRED. Wrong instance cannot claim/recover it.
 auto wrong=context;std::memset(wrong.instance,'9',32);
 assert(worker.start(argv[2],(root+L".fenced").c_str(),wrong));
 eventually([&]{return worker.status().authority_lost;});assert(!worker.status().ready);
 assert(!worker.submit(ticket(1,1,0),last_raw.data(),last_raw.size()));assert(worker.stop());
 wrong=context;++wrong.world;
 assert(worker.start(argv[2],(root+L".badconfig").c_str(),wrong));
 eventually([&]{return worker.status().configuration_error;});assert(!worker.status().initialized && !worker.stop());
 std::cout<<"PASS actual threaded checkpoint worker: owned producer bytes, independent lease renewal during disk refusal, latest submitted generation, fresh replay on restart, local shutdown drain and shared count/64MiB bounds\n";
 std::cout<<"PASS worker authority/engine boundary: concurrent producers, retained refusals, no takeover, wrong world config, fixed credential-free diagnostics and noexcept lifecycle\n";
}
#endif
int main(int argc,char** argv){
 (void)argc;(void)argv;
#ifdef _WIN32
 if(argc==7 && std::string(argv[5])=="--outbox-crash"){outbox_crash(argv);return 1;}
#endif
 BridgeJson body={{"schema",1},{"mode","writer"},{"host","127.0.0.1"},{"port",12345},
  {"token",std::string(48,'s')},{"actor","location:cordon"},{"location","cordon"},
  {"master_world_id",71},{"master_world_seed",0}};
 auto config=WriterConfig::parse(body.dump(),"cordon");assert(config.world==71 && config.seed==0);
 for(const char* key:{"host","mode","actor","location","token"}){
  auto invalid=body;invalid[key]="bad";rejects([&]{WriterConfig::parse(invalid.dump(),"cordon");});
 }
 rejects([&]{WriterConfig::parse(body.dump(),"garbage");});
 for(auto value:{BridgeJson(0),BridgeJson(-1),BridgeJson(65536),BridgeJson(true),BridgeJson(1.5)}){
  auto invalid=body;invalid["port"]=value;rejects([&]{WriterConfig::parse(invalid.dump(),"cordon");});
 }
 auto extra=body;extra["admin"]=true;rejects([&]{WriterConfig::parse(extra.dump(),"cordon");});
 assert(writer_instance_valid(std::string(32,'a')) && !writer_instance_valid(std::string(32,'A')));
 for(const std::string text:{"","f","fo","foo","foob","fooba","foobar"})
  assert(checkpoint_unbase64(checkpoint_base64(text))==text);
 std::string binary;for(unsigned i=0;i<256;++i) binary+=char(i);
 assert(checkpoint_unbase64(checkpoint_base64(binary))==binary);
 for(const std::string bad:{"Zh==","Zm9=","Zg==AAAA","Zg="," Zg==","Zg??"})
  rejects([&]{checkpoint_unbase64(bad);});
 rejects([&]{checkpoint_unbase64("Zm9v",2);});
 std::cout<<"PASS bounded canonical checkpoint codec: binary bytes, padding bits, malformed input and decode limits\n";
#ifdef _WIN32
 assert(argc==5);
 auto read=[](const char* filename){std::ifstream in(filename,std::ios::binary);return std::string(std::istreambuf_iterator<char>(in),{});};
 auto src=WriterConfig::parse(read(argv[1]),"cordon"),dst=WriterConfig::parse(read(argv[2]),"garbage");
 auto proxy=WriterConfig::parse(read(argv[4]),"garbage");
 const std::string a(32,'a'),b(32,'b'),c(32,'c');
 BridgeJson result;unsigned status=0,seq=0;
 // Actual socket faults after HTTP 200: short body, read timeout, complete
 // malformed JSON, invalid envelope, oversized declaration, then recovery.
 for(unsigned fault=0;fault<6;++fault){
  bool ok=false;try{ok=writer_request(proxy,c,0,"GET","/v1/clock","",result,status);}
  catch(const std::exception&){assert(false && "response fault escaped transport");}
  assert(ok==(fault==5));assert(status==(fault<2 ? 0U:200U));
  if(fault<5) assert(result.is_null());else assert(result["ok"]==true);
 }
 std::cout<<"PASS actual WinHTTP response faults: truncated body and timeout retry, malformed/bounded protocol refusal, recovery without escaping exceptions\n";
 assert(writer_request(src,a,0,"GET","/v1/clock","",result,status));
 assert(result["world_id"]==71 && result["seed"]==0);auto epoch=bridge_unsigned(result,"authority_epoch");
 auto command=[&](const WriterConfig& cfg,const std::string& instance,const std::string& operation,
                  const BridgeJson& args,std::string id=""){
  if(id.empty()){char token[33];std::snprintf(token,sizeof(token),"%032x",++seq);id=token;}
  return writer_request(cfg,instance,epoch,"POST","/v1/command",
   BridgeJson{{"command_id",id},{"operation",operation},{"arguments",args}}.dump(),result,status);
 };
 assert(command(src,a,"location_claim",{{"location","cordon"}}));auto sf=bridge_unsigned(result,"fence");
 assert(!command(src,b,"location_claim",{{"location","cordon"}}) && status==409 && result.is_null());
 assert(!command(src,b,"location_renew",{{"location","cordon"},{"fence",sf}}) && status==409);
 assert(command(dst,c,"location_claim",{{"location","garbage"}}));auto tf=bridge_unsigned(result,"fence");
 assert(!command(src,a,"location_claim",{{"location","garbage"}}) && status==403);
 auto wrong=src;wrong.seed=1;
 assert(!command(wrong,a,"location_renew",{{"location","cordon"},{"fence",sf}}) && status==409);
 ++epoch;assert(!command(src,a,"location_renew",{{"location","cordon"},{"fence",sf}}) && status==409);--epoch;
 const std::string npc(32,'1'),group(32,'2'),mutant(32,'3'),item(32,'4');
 assert(command(src,a,"entity_create",{{"entity_id",npc},{"kind","NPC"},{"location","cordon"},{"fence",sf},
  {"state",{{"health",0.72},{"engine_state","saved NPC state"}}}}));
 assert(command(src,a,"entity_create",{{"entity_id",mutant},{"kind","MUTANT"},{"location","cordon"},{"fence",sf},
  {"state",{{"health",0.41}}}}));
 assert(command(src,a,"entity_create",{{"entity_id",group},{"kind","GROUP"},{"location","cordon"},{"fence",sf},
  {"state",{{"member_ids",BridgeJson::array({npc,mutant})}}}}));
 assert(command(src,a,"item_create",{{"item_id",item},{"section","wpn_ak74"},{"location","cordon"},{"fence",sf},
  {"kind","NPC"},{"holder",npc},{"state",{{"condition",0.53},{"rounds",17}}}}));
 assert(command(src,a,"transfer_prepare",{{"entity_id",group},{"source","cordon"},{"source_fence",sf},
  {"target","garbage"},{"entity_version",1}}));
 const auto transfer=result["transfer_id"].get<std::string>(),token=result["token"].get<std::string>();
 assert(!command(src,a,"entity_update",{{"entity_id",npc},{"fence",sf},{"version",1},{"state",{{"health",1}}}}) && status==409);
 assert(command(dst,c,"transfer_claim",{{"token",token},{"target_fence",tf}}));
 assert(result["checkpoint"]["entities"].size()==3 && result["checkpoint"]["items"].size()==1);
 assert(result["checkpoint"]["items"][0]["id"]==item);
 const std::string commit(32,'f');
 assert(command(dst,c,"transfer_commit",{{"transfer_id",transfer},{"target_fence",tf}},commit));
 assert(result["state"]=="COMMITTED");auto committed=result;
 assert(command(dst,c,"transfer_commit",{{"transfer_id",transfer},{"target_fence",tf}},commit) && result==committed);
 assert(writer_request(dst,c,epoch,"GET","/v1/location?id=garbage&fence="+std::to_string(tf),"",result,status));
 assert(result["entities"].size()==3 && result["items"].size()==1);
 assert(writer_request(src,a,epoch,"GET","/v1/transfer?id="+transfer,"",result,status) && result["state"]=="COMMITTED");
 assert(!command(src,a,"world_scale",{{"value",100}}) && status==0);
 auto admin=src;admin.token=std::string(48,'a');
 assert(!command(admin,b,"location_claim",{{"location","cordon"}}) && status==403);
 // Real native transport, complete NCH9 bytes, private loopback master.
 const auto fixture=bridge_json(read(argv[3]),1024*1024);
 for(const auto& vector:fixture["identities"])
  assert(checkpoint_player_id(bridge_unsigned(vector,"world"),bridge_unsigned(vector,"seed"),vector["account"].get<std::string>(),
   unsigned(bridge_unsigned(vector,"slot")))==vector["id"]);
 for(const auto& vector:fixture["hashes"])
  assert(checkpoint_sha256(vector["input"].get<std::string>())==vector["sha256"]);
 rejects([&]{checkpoint_player_id(0,0,"alice",1);});
 rejects([&]{checkpoint_player_id(71,0,"../alice",1);});
 rejects([&]{checkpoint_player_id(71,0,"alice",11);});
 rejects([&]{checkpoint_player_id(71,0,"al ice",1);});
 const auto character=fixture["character_id"].get<std::string>();
 PlayerSlotObservation observation;
 assert(inspect_player_slot(src,a,epoch,"nobody",1,sf,observation,status)==CheckpointStep::Complete);
 assert(observation.state==PlayerSlotStatus::Absent && observation.revision==0 && observation.session_fence==0);
 assert(command(src,a,"entity_create",{{"entity_id",character},{"kind","CHARACTER"},{"location","cordon"},
  {"fence",sf},{"account","alice"},{"state",{{"position",BridgeJson::array({1,2,3})}}}}));
 assert(inspect_player_slot(src,a,epoch,"ALICE",1,sf,observation,status)==CheckpointStep::Complete);
 assert(observation.state==PlayerSlotStatus::Active && observation.entity_version==1 && observation.revision==0);
 assert(inspect_player_slot(src,b,epoch,"alice",1,sf,observation,status)==CheckpointStep::Rejected && status==409);
 assert(observation.state==PlayerSlotStatus::Missing && observation.character.empty());
 assert(inspect_player_slot(wrong,a,epoch,"alice",1,sf,observation,status)==CheckpointStep::Rejected && status==409);
 assert(inspect_player_slot(src,a,0,"alice",1,sf,observation,status)==CheckpointStep::Rejected && status==0);
 assert(inspect_player_slot(src,a,epoch,"../alice",1,sf,observation,status)==CheckpointStep::Rejected);
 auto begin=[&](){return command(src,a,"native_save_begin",{{"character_id",character},{"fence",sf},
  {"session_fence",1},{"entity_version",1},{"base_revision",0},{"slot",1},
  {"byte_count",fixture["bytes"]},{"sha256",fixture["sha256"]}});};
 assert(begin());auto upload=result["upload_id"].get<std::string>();
 assert(inspect_player_slot(src,a,epoch,"alice",1,sf,observation,status)==CheckpointStep::Rejected && status==409);
 assert(command(src,a,"native_save_cancel",{{"character_id",character},{"fence",sf},{"session_fence",1},{"upload_id",upload}}));
 assert(begin());upload=result["upload_id"].get<std::string>();
 assert(!command(src,a,"native_save_finish",{{"character_id",character},{"fence",sf},{"session_fence",1},{"upload_id",upload}}) && status==409);
 assert(!command(src,a,"session_disconnect",{{"character_id",character},{"fence",sf},{"version",1},{"state",BridgeJson::object()}}) && status==409);
 for(const auto& chunk:fixture["chunks"]){
  const auto args=BridgeJson{{"character_id",character},{"fence",sf},{"session_fence",1},{"upload_id",upload},
   {"offset",chunk["offset"]},{"data",chunk["data"]}};
  assert(!command(src,b,"native_save_append",args) && status==409);
  assert(command(src,a,"native_save_append",args));
 }
 const std::string finish(32,'e');
 const auto finish_args=BridgeJson{{"character_id",character},{"fence",sf},{"session_fence",1},{"upload_id",upload}};
 assert(command(src,a,"native_save_finish",finish_args,finish));
 const auto durable=result;assert(result["durable"]==true && result["revision"]==1 && result["sha256"]==fixture["sha256"]);
 assert(command(src,a,"native_save_finish",finish_args,finish) && result==durable);
 assert(inspect_player_slot(src,a,epoch,"alice",1,sf,observation,status)==CheckpointStep::Complete);
 assert(observation.state==PlayerSlotStatus::Active && observation.entity_version==2 && observation.revision==1 &&
  observation.sha256==fixture["sha256"] && observation.bytes==fixture["bytes"]);
 const auto slot_path="/v1/player-admission?account=alice&slot=1&location=cordon&fence="+std::to_string(sf)+"&epoch="+std::to_string(epoch);
 assert(!writer_request(src,a,0,"GET",slot_path,"",result,status) && status==0);
 assert(writer_request(src,a,epoch,"GET",slot_path,"",result,status));
 const auto slot_body=result;
 for(const auto* field:{"schema","slot","epoch","fence","entity_version","session_fence"}){
  auto bad=slot_body;bad[field]=true;rejects([&]{PlayerSlotObservation::parse(bad,src,epoch,"alice",1,sf);});
 }
 for(unsigned fault=0;fault<6;++fault){auto bad=slot_body;
  if(fault==0)bad["status"]="FROZEN";if(fault==1)bad["checkpoint"]["bytes"]=checkpoint_limit+1;
  if(fault==2)bad["world_id"]="071";if(fault==3)bad["checkpoint"]["sha256"]="bad";
  if(fault==4)bad["private"]="extra";if(fault==5)bad["character_id"]=std::string(32,'0');
  rejects([&]{PlayerSlotObservation::parse(bad,src,epoch,"alice",1,sf);});
 }
 auto staged_body=slot_body;staged_body["status"]="STAGED";staged_body["checkpoint"]=nullptr;
 staged_body["entity_version"]=0;staged_body["session_fence"]=0;
 assert(PlayerSlotObservation::parse(staged_body,src,epoch,"alice",1,sf).state==PlayerSlotStatus::Staged);
 // The character lives on another location: only its name comes back.
 auto home_body=staged_body;home_body["status"]="ELSEWHERE";home_body["home"]="l02_garbage";
 {const auto home=PlayerSlotObservation::parse(home_body,src,epoch,"alice",1,sf);
  assert(home.state==PlayerSlotStatus::Elsewhere && home.home=="l02_garbage" && !home.revision);}
 for(unsigned fault=0;fault<5;++fault){auto bad=home_body;
  if(fault==0)bad.erase("home");if(fault==1)bad["home"]="";if(fault==2)bad["home"]="../x";
  if(fault==3)bad["home"]=src.location;if(fault==4)bad["entity_version"]=1;
  rejects([&]{PlayerSlotObservation::parse(bad,src,epoch,"alice",1,sf);});
 }
 {auto stray=staged_body;stray["home"]="l02_garbage";rejects([&]{PlayerSlotObservation::parse(stray,src,epoch,"alice",1,sf);});}
 auto page_path=[&](std::uint64_t fence,std::uint64_t session,const BridgeJson& offset){
  return "/v1/player-save?character_id="+character+"&fence="+std::to_string(fence)+
   "&session_fence="+std::to_string(session)+"&revision=1&offset="+std::to_string(offset.get<std::uint64_t>());
 };
 for(const auto& chunk:fixture["chunks"]){
  const auto path=page_path(sf,1,chunk["offset"]);
  assert(!writer_request(src,a,0,"GET",path,"",result,status) && status==0);
  assert(writer_request(src,a,epoch,"GET",path,"",result,status));
  assert(result["data"]==chunk["data"] && result["sha256"]==fixture["sha256"] && result["bytes"]==fixture["bytes"]);
 }
 // Logout/reconnect increments the session fence without losing the save.
 assert(command(src,a,"session_disconnect",{{"character_id",character},{"fence",sf},{"version",2},{"state",{{"position",BridgeJson::array({4,5,6})}}}}));
 assert(inspect_player_slot(src,a,epoch,"alice",1,sf,observation,status)==CheckpointStep::Complete);
 assert(observation.state==PlayerSlotStatus::Disconnected && observation.session_fence==2 && observation.entity_version==3);
 assert(!writer_request(src,a,epoch,"GET",page_path(sf,1,0),"",result,status) && status==409);
 assert(command(src,a,"session_resume",{{"character_id",character},{"location","cordon"},{"fence",sf},{"version",3}}));
 assert(result["session_fence"]==3 && result["version"]==4);
 assert(command(src,a,"transfer_prepare",{{"entity_id",character},{"source","cordon"},{"source_fence",sf},{"target","garbage"},{"entity_version",4}}));
 const auto character_transfer=result["transfer_id"].get<std::string>(),character_token=result["token"].get<std::string>();
 assert(inspect_player_slot(src,a,epoch,"alice",1,sf,observation,status)==CheckpointStep::Rejected && status==409);
 assert(!writer_request(src,a,epoch,"GET",page_path(sf,3,0),"",result,status) && status==409);
 assert(command(dst,c,"transfer_claim",{{"token",character_token},{"target_fence",tf}}));
 const auto frozen_session=bridge_unsigned(result,"session_fence");
 assert(!writer_request(dst,c,epoch,"GET",page_path(tf,frozen_session,0),"",result,status) && status==403);
 for(const auto& chunk:fixture["chunks"]){
  assert(writer_request(dst,c,epoch,"GET",page_path(tf,frozen_session,chunk["offset"])+"&transfer_id="+character_transfer,"",result,status));
  assert(result["data"]==chunk["data"] && result["sha256"]==fixture["sha256"]);
 }
 assert(command(dst,c,"transfer_commit",{{"transfer_id",character_transfer},{"target_fence",tf}}));
 assert(inspect_player_slot(dst,c,epoch,"alice",1,tf,observation,status)==CheckpointStep::Complete);
 assert(observation.state==PlayerSlotStatus::Active && observation.entity_version==6 && observation.session_fence==frozen_session+1);
 std::cout<<"PASS actual native admission lookup: same-request world/instance binding, canonical identity, compact typed head, incomplete/frozen/stale-owner refusal, disconnect and transfer lifecycle, malformed reply rejection\n";
 assert(!writer_request(src,a,epoch,"GET",page_path(sf,3,0),"",result,status) && status==403);
 assert(writer_request(dst,c,epoch,"GET",page_path(tf,frozen_session+1,0),"",result,status));
 assert(result["data"]==fixture["chunks"][0]["data"]);
 // The native client state machine owns encoding, command identity and ack
 // validation. The socket proxy truncates successful begin/append/finish
 // replies AFTER the real master commits, without faking transport status.
 std::string raw;for(const auto& chunk:fixture["chunks"]) raw+=checkpoint_unbase64(chunk["data"].get<std::string>());
 const std::string transaction(32,'d');
 auto make_upload=[&]{return std::make_unique<CheckpointUpload>(raw,character,tf,frozen_session+1,6,1,1,transaction);};
 auto upload_client=make_upload();rejects([&]{upload_client->durable();});
 std::set<std::string> dropped;
 auto actual=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& out,unsigned& code){
  return writer_request(dst,c,epoch,method,path,payload,out,code);
 };
 auto unreliable=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& out,unsigned& code){
  const bool ok=writer_request(proxy,c,epoch,method,path,payload,out,code);
  const auto op=bridge_json(payload,65536)["operation"].get<std::string>();
  if(!ok && code==0){assert(out.is_null());dropped.insert(op);}
  return ok;
 };
 bool uploaded=false,resumed=false;
 for(unsigned tries=0;tries<30 && !uploaded;++tries){
  const auto step=upload_client->step(unreliable);assert(step!=CheckpointStep::Rejected);
  if(step==CheckpointStep::Retry && dropped.count("native_save_append") && !resumed){
   auto cursor=bridge_json(upload_client->cursor().dump(),4096);auto restored=make_upload();
   auto tampered=cursor;tampered["binding"]=std::string(64,'0');rejects([&]{restored->restore_cursor(tampered);});
   tampered=cursor;tampered["offset"]=1;rejects([&]{restored->restore_cursor(tampered);});
   restored->restore_cursor(cursor);upload_client=std::move(restored);resumed=true;
  }
  uploaded=step==CheckpointStep::Complete;
 }
 assert(uploaded && resumed && dropped.size()==3 && upload_client->durable()["revision"]==2);
 auto restored=make_upload();restored->restore_cursor(upload_client->cursor());
 rejects([&]{restored->durable();}); // a saved cursor never proves commit
 auto bad_ack=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& out,unsigned& code){
  const bool ok=actual(method,path,payload,out,code);if(ok) out["bytes"]=raw.size()+1;return ok;
 };
 assert(restored->step(bad_ack)==CheckpointStep::Rejected);rejects([&]{restored->durable();});
 assert(restored->step(actual)==CheckpointStep::Complete && restored->durable()==upload_client->durable());
 auto wrong_snapshot=std::make_unique<CheckpointUpload>(raw,character,tf,frozen_session+1,6,1,2,transaction);
 rejects([&]{wrong_snapshot->restore_cursor(upload_client->cursor());});
 const auto sha=fixture["sha256"].get<std::string>();
 const auto count=std::size_t(bridge_unsigned(fixture,"bytes"));
 CheckpointDownload download(character,tf,frozen_session+1,2,sha,count);
 rejects([&]{download.bytes();});
 auto lost_read=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& out,unsigned& code){
  assert(actual(method,path,payload,out,code));out=BridgeJson();code=0;return false;
 };
 assert(download.step(lost_read)==CheckpointStep::Retry);
 auto bad_metadata=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& out,unsigned& code){
  const bool ok=actual(method,path,payload,out,code);if(ok) out["sha256"]=std::string(64,'0');return ok;
 };
 assert(download.step(bad_metadata)==CheckpointStep::Rejected);rejects([&]{download.bytes();});
 bool downloaded=false;
 for(unsigned tries=0;tries<10 && !downloaded;++tries){
  const auto step=download.step(actual);assert(step!=CheckpointStep::Rejected);downloaded=step==CheckpointStep::Complete;
 }
 assert(downloaded && download.bytes()==raw);
 CheckpointDownload corrupt(character,tf,frozen_session+1,2,sha,count);
 auto corrupt_last=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& out,unsigned& code){
  const bool ok=actual(method,path,payload,out,code);
  if(ok && bridge_unsigned(out,"next_offset")==count){auto bytes=checkpoint_unbase64(out["data"].get<std::string>());bytes[0]=char(static_cast<unsigned char>(bytes[0])^1U);out["data"]=checkpoint_base64(bytes);}
  return ok;
 };
 bool refused=false;
 for(unsigned tries=0;tries<10 && !refused;++tries) refused=corrupt.step(corrupt_last)==CheckpointStep::Rejected;
 assert(refused && corrupt.step(actual)==CheckpointStep::Rejected);rejects([&]{corrupt.bytes();});
 rejects([&]{CheckpointDownload invalid(character,tf,1,2,sha,checkpoint_limit+1);});
 assert(checkpoint_failure(409)==CheckpointStep::Rejected && checkpoint_failure(429)==CheckpointStep::Retry);
 assert(checkpoint_failure(200)==CheckpointStep::Retry && "incomplete HTTP success must retry the same idempotent command");
 CheckpointUpload stale(raw,character,sf,1,7,2,1,std::string(32,'b'));
 auto old_source=[&](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& out,unsigned& code){
  return writer_request(src,a,epoch,method,path,payload,out,code);
 };
 assert(stale.step(old_source)==CheckpointStep::Rejected && stale.cursor()["phase"]==0);
 assert(command(dst,c,"location_renew",{{"location","garbage"},{"fence",tf},{"ttl_ms",60000}}));
 outbox_checks(argv,dst,c,epoch,character,tf,frozen_session+1,raw,
  checkpoint_unbase64(fixture["next_raw"].get<std::string>()),checkpoint_unbase64(fixture["last_raw"].get<std::string>()));
 worker_checks(argv,c,epoch,character,tf,frozen_session+1,
  checkpoint_unbase64(fixture["next_raw"].get<std::string>()),checkpoint_unbase64(fixture["last_raw"].get<std::string>()));
 std::cout<<"PASS native checkpoint client: Python-compatible UUID5/SHA256, lost begin/append/finish replies, bound cursor recovery, commit replay, exact binary download, unexposed corrupt/partial reads\n";
 std::cout<<"PASS actual WinHTTP NCH9 chunks: cancel, stale writer, durable replay, exact read, disconnect/resume, fenced handoff read before activation\n";
 std::cout<<"PASS actual WinHTTP master: separate runtime leases, scope/world/epoch checks, frozen source, group NPC+mutant+inventory transferred with the same IDs, idempotent commit\n";
#endif
 std::cout<<"PASS writer config: exact schema, loopback-only endpoint, map identity, bounded credential and persistent instance\n";
}
'''


class FaultProxyHandler(BaseHTTPRequestHandler):
    """Fixture-only loopback proxy; never log request headers or bodies."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, body, declared=None, pause=False):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body) if declared is None else declared))
        self.send_header("Connection", "close")
        self.end_headers()
        if pause:
            time.sleep(.8)  # WinHTTP's actual receive timeout is 500 ms.
        try:
            self.wfile.write(body)
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        finally:
            self.close_connection = True

    def do_GET(self):
        index = self.server.get_count
        self.server.get_count += 1
        body = b'{"result":{"ok":true}}'
        if index == 0:
            self.reply(body[:5], len(body))
        elif index == 1:
            self.reply(b"", 10, pause=True)
        elif index == 2:
            self.reply(b'{"result":')
        elif index == 3:
            self.reply(b'{"result":null}')
        elif index == 4:
            self.reply(b"", 2*1024*1024+1)
        else:
            self.reply(body)

    def do_POST(self):
        size = int(self.headers["Content-Length"])
        assert 1 <= size <= 65536
        payload = self.rfile.read(size)
        operation = json.loads(payload)["operation"]
        headers = {key: self.headers[key] for key in
                   ("Authorization", "X-LostZone-Instance", "X-LostZone-World", "Content-Type")}
        connection = http.client.HTTPConnection("127.0.0.1", self.server.upstream_port, timeout=5)
        try:
            connection.request("POST", "/v1/command", payload, headers)
            response = connection.getresponse()
            body = response.read()
            assert response.status == 200, "upstream fixture command failed"
        finally:
            connection.close()
        if operation not in self.server.dropped:
            self.server.dropped.add(operation)
            self.reply(body[:max(1, len(body)//2)], len(body))
        else:
            self.reply(body)


class FaultProxy(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, upstream_port):
        self.upstream_port, self.get_count, self.dropped = upstream_port, 0, set()
        super().__init__(("127.0.0.1", 0), FaultProxyHandler)


with TemporaryDirectory(prefix="world-writer-") as tmp:
    folder = Path(tmp)
    cpp = folder / "writer.cpp"
    exe = folder / ("writer.exe" if os.name == "nt" else "writer")
    cpp.write_text(source, encoding="utf-8")
    include = str(root / "src/xrGame")
    command = (["cl", "/nologo", "/std:c++17", "/EHsc", "/W4", "/WX", "/O2", "/I"+include,
                str(cpp), str(root / "src/xrGame/netcoop_checkpoint_worker.cpp"), "/Fe:"+str(exe), "/link", "winhttp.lib"] if os.name == "nt" else
               ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2", "-I", include, str(cpp), "-o", str(exe)])
    subprocess.run(command, cwd=tmp, check=True)
    if os.name != "nt":
        subprocess.run([str(exe)], cwd=tmp, check=True)
    else:
        store = Store(folder / "world.db")
        world = World(store, world_id=71, seed=0)
        credentials = {"location:cordon":{"role":"location","locations":["cordon"],"token":"s"*48},
                       "location:garbage":{"role":"location","locations":["garbage"],"token":"d"*48},
                       "admin":{"role":"admin","token":"a"*48}}
        server = Server(("127.0.0.1", 0), Dispatcher(world, b"k"*32), Credentials(credentials))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        proxy = FaultProxy(server.server_address[1])
        proxy_thread = threading.Thread(target=proxy.serve_forever)
        proxy_thread.start()
        try:
            config = folder / "private.json"
            create_config(config, ["cordon", "garbage"], world_id=71, seed=0)
            data = json.loads(config.read_bytes())
            data["credentials"] = credentials
            data["port"] = server.server_address[1]
            config.write_text(json.dumps(data))
            paths = []
            for location in ("cordon", "garbage"):
                dest = folder / ("netcoop_world_writer_"+location+".json")
                create_writer_config(config, dest, location)
                paths.append(str(dest))
            raw = native_fixture(9, progress=b"quest/info/behavior"*4000)
            native = folder / "native-fixture.json"
            identities=[(71,0,"ALIce",1),(71,0,"alice",2),(72,0,"alice",1),(71,1,"alice",1),
                        (2**64-1,2**64-1,"Ab_.-09",10)]
            native.write_text(json.dumps({"character_id":identity(71,0,"alice",1),"bytes":len(raw),
                "next_raw":base64.b64encode(native_fixture(9,progress=b"queued generation20")).decode("ascii"),
                "last_raw":base64.b64encode(native_fixture(9,progress=b"queued generation30 newest complete progress")).decode("ascii"),
                "identities":[dict(world=w,seed=s,account=a,slot=n,id=identity(w,s,a,n)) for w,s,a,n in identities],
                "hashes":[dict(input=text,sha256=hashlib.sha256(text.encode()).hexdigest()) for text in ("","abc","binary\\0data")],
                "sha256":hashlib.sha256(raw).hexdigest(),"chunks":[
                    {"offset":offset,"data":base64.b64encode(raw[offset:offset+30720]).decode("ascii")}
                    for offset in range(0,len(raw),30720)]}), encoding="utf-8")
            proxy_config = folder / "proxy-writer.json"
            proxy_body = json.loads(Path(paths[1]).read_bytes())
            proxy_body["port"] = proxy.server_address[1]
            proxy_config.write_text(json.dumps(proxy_body), encoding="utf-8")
            subprocess.run([str(exe), *paths, str(native), str(proxy_config)], cwd=tmp, check=True)
            assert proxy.get_count == 6
            assert proxy.dropped == {"native_save_begin", "native_save_append", "native_save_finish"}
            assert store.db.execute("SELECT COUNT(*) FROM entity WHERE location='garbage'").fetchone()[0] == 4
            assert store.db.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 1
            assert store.db.execute("SELECT COUNT(*) FROM world_event WHERE type='TransferCommitted'").fetchone()[0] == 2
            payload = store.db.execute("SELECT payload_base64 FROM native_player_save ORDER BY revision DESC LIMIT 1").fetchone()[0]
            assert base64.b64decode(payload) == native_fixture(9,progress=b"queued generation30 newest complete progress")
            assert store.db.execute("SELECT COUNT(*) FROM native_player_save").fetchone()[0] == 2
            assert store.db.execute("SELECT MAX(revision) FROM native_player_save").fetchone()[0] == 8
            assert store.db.execute("SELECT COUNT(*) FROM world_event WHERE type='NativePlayerSaveCommitted'").fetchone()[0] == 8
        finally:
            proxy.shutdown()
            proxy.server_close()
            proxy_thread.join()
            server.shutdown()
            server.server_close()
            thread.join()
            store.close()
