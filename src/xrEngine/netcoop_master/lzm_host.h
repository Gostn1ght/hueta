// Native host control. No external watchdog, panel, Python or game-loop calls.
// The worker owns process handles; its mailbox and snapshots are atomic files.
#pragma once
#include "lzm_service.h"
#include "lzm_cluster_plan.h"
#include <windows.h>
#include <iphlpapi.h>
#include <psapi.h>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <chrono>
#include <ctime>
#pragma comment(lib,"iphlpapi.lib")
#pragma comment(lib,"psapi.lib")

namespace lzm {
class HostController
{
    friend struct HostControllerFixture;
    struct Map {
        PlanLocation plan;std::string start,world,mode="auto",state="stopped",detail;
        bool demand=true,loading=false,expected=false,blocked=false;
        HANDLE process=nullptr;DWORD pid=0,exit=0;unsigned failures=0,players=0;
        uint64_t launched=0,retry_at=0,healthy_at=0;bool has_exit=false;
    };
    std::wstring root_,folder_,exe_;
    std::vector<Map> maps_;
    HANDLE mutex_=nullptr;
    std::atomic<bool> stopping_{false},enabled_{false};
    std::atomic<bool> stop_all_{false};
    std::atomic<unsigned> active_{0};
    std::atomic<uint64_t> master_epoch_{0};
    std::thread worker_;
    double free_ram_=0,free_commit_=0,need_=6;
    uint64_t last_heartbeat_=0;

    static std::string read(const std::wstring& path) {
        std::ifstream in(path,std::ios::binary);std::ostringstream s;s<<in.rdbuf();return plan_trim(s.str());
    }
    static bool exists(const std::wstring& path) {return GetFileAttributesW(path.c_str())!=INVALID_FILE_ATTRIBUTES;}
    static void write(const std::wstring& path,const std::string& text) {
        const auto temporary=path+L"."+std::to_wstring(GetCurrentProcessId())+L".tmp";
        {std::ofstream out(temporary,std::ios::binary|std::ios::trunc);if(!out || !(out<<text)) throw Unavailable("host control file cannot be written");}
        bool installed=false;
        for(unsigned attempt=0;attempt<40;++attempt) {
            if(MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) {installed=true;break;}
            if(GetLastError()!=ERROR_SHARING_VIOLATION && GetLastError()!=ERROR_ACCESS_DENIED) break;
            Sleep(10);
        }
        if (!installed) {
            DeleteFileW(temporary.c_str());throw Unavailable("host control file cannot be installed");
        }
    }
    std::wstring file(const std::string& prefix,const Map& m) const {return folder_+L"\\"+widen(prefix+m.plan.name)+L".txt";}
    std::string mode(const Map& m) const {
        auto value=read(file("host_mode_",m));
        return value=="on" || value=="off" ? value:"auto";
    }
    void transition(Map& m,const std::string& state,const std::string& detail="") {
        if(m.state!=state || m.detail!=detail) {
            log_line(format("[diag][host] map=%s udp=%d pid=%lu state=%s -> %s reason=%s",m.plan.name.c_str(),m.plan.port,
                m.pid,m.state.c_str(),state.c_str(),detail.c_str()));m.state=state;m.detail=detail;
        }
    }
    // An existing dedicated process is adopted only when both its UDP owner
    // and its full executable path match. A foreign listener is never killed.
    DWORD udp_owner(int port) const {
        ULONG bytes=0;
        if(GetExtendedUdpTable(nullptr,&bytes,FALSE,2,UDP_TABLE_OWNER_PID,0)!=ERROR_INSUFFICIENT_BUFFER) return 0;
        std::vector<unsigned char> data(bytes);
        if(GetExtendedUdpTable(data.data(),&bytes,FALSE,2,UDP_TABLE_OWNER_PID,0)!=NO_ERROR) return 0;
        const auto table=reinterpret_cast<const MIB_UDPTABLE_OWNER_PID*>(data.data());
        for(DWORD i=0;i<table->dwNumEntries;++i) {
            const DWORD raw=table->table[i].dwLocalPort;
            if(int(((raw&255)<<8)|((raw>>8)&255))==port) return table->table[i].dwOwningPid;
        }return 0;
    }
    bool adopt(Map& m) {
        const DWORD pid=udp_owner(m.plan.port);if(!pid) return false;
        HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION|SYNCHRONIZE,FALSE,pid);
        if(!p) {transition(m,"failed","UDP port is owned by an inaccessible process "+std::to_string(pid));m.blocked=true;return false;}
        wchar_t path[4096];DWORD size=4096;
        const bool same=QueryFullProcessImageNameW(p,0,path,&size) && _wcsicmp(path,exe_.c_str())==0;
        if(!same) {CloseHandle(p);transition(m,"failed","UDP port occupied by another program pid="+std::to_string(pid));m.blocked=true;return false;}
        m.process=p;m.pid=pid;m.loading=true;m.launched=GetTickCount64();
        transition(m,"loading","adopted existing dedicated process");return true;
    }
    void stop_map(Map& m) {
        if(!m.process) return;
        write(folder_+L"\\host_stop_"+std::to_wstring(m.plan.port)+L".txt","stop|"+std::to_string(m.pid));
        m.expected=true;transition(m,"saving","requested saved exit; no forced termination");
    }
    void command(Map& m) {
        const auto source=file("host_command_",m),claimed=source+L"."+std::to_wstring(GetCurrentProcessId())+L".claimed";
        if(!MoveFileExW(source.c_str(),claimed.c_str(),0)) return;
        const auto action=read(claimed);DeleteFileW(claimed.c_str());
        if(action!="start" && action!="stop" && action!="restart" && action!="auto") {log_line("[diag][host] invalid command for "+m.plan.name);return;}
        m.mode=action=="stop" ? "off":action=="auto" ? "auto":"on";
        write(file("host_mode_",m),m.mode);
        if(action!="stop") {m.failures=0;m.blocked=false;m.retry_at=0;m.has_exit=false;}
        log_line("[diag][host] operator map="+m.plan.name+" action="+action+" mode="+m.mode);
        if(action=="stop" || action=="restart") stop_map(m);
    }
    bool status(Map& m) {
        std::istringstream in(read(folder_+L"\\status_"+std::to_wstring(m.plan.port)+L".txt"));
        uint64_t stamp=0;unsigned capacity=0;
        if(!(in>>stamp>>m.players>>capacity) || stamp+30<uint64_t(time(nullptr)) || stamp>uint64_t(time(nullptr))+5) {m.players=0;return false;}
        return true;
    }
    void update(Map& m) {
        command(m);m.mode=mode(m);
        if(!m.process) return;
        DWORD exit=STILL_ACTIVE;
        if(!GetExitCodeProcess(m.process,&exit)) {transition(m,"failed","cannot inspect dedicated process");return;}
        if(exit!=STILL_ACTIVE) {
            CloseHandle(m.process);m.process=nullptr;m.has_exit=true;m.exit=exit;m.pid=0;
            const bool failure=!m.expected && (exit!=0 || m.loading);
            m.loading=false;m.healthy_at=0;
            if(failure) {++m.failures;m.blocked=m.failures>=3;m.retry_at=GetTickCount64()+30000ULL*(1ULL<<std::min(m.failures-1,3u));
                transition(m,m.blocked ? "failed":"retry","process exit="+std::to_string(exit));}
            else {
                if(!m.expected && (m.mode=="on" || !m.demand)) {m.mode="off";write(file("host_mode_",m),"off");}
                transition(m,"stopped","saved or deliberate clean exit");
            }
            m.expected=false;return;
        }
        if(m.mode=="off" && !m.expected) stop_map(m);
        if(!m.expected && master_epoch_) {
            try {
                const auto diagnostic=loads(read(folder_+L"\\admission_"+std::to_wstring(m.plan.port)+L".json"));
                const auto epoch=diagnostic.value("epoch",uint64_t(0));
                if(diagnostic.value("pid",0u)==m.pid && diagnostic.value("updated",int64_t(0))>=int64_t(time(nullptr))-45 && epoch && epoch!=master_epoch_) {
                    log_line("[diag][host] old master epoch at map="+m.plan.name+"; requesting saved restart");stop_map(m);
                }
            }catch(...) {}
        }
        const bool ready=status(m);
        if(ready && !m.expected) {
            if(m.loading) {m.loading=false;m.healthy_at=GetTickCount64();DeleteFileW(file("wake_",m).c_str());}
            transition(m,"running","world is responding; master lease is checked separately");
            if(m.healthy_at && GetTickCount64()-m.healthy_at>300000) m.failures=0;
        }
        else if(m.loading && !m.expected && GetTickCount64()-m.launched>600000) {
            m.loading=false; // do not block every other map behind a hung load
            transition(m,"loading_timeout","no ready heartbeat after 600 seconds; process retained for diagnosis");
        }
    }
    void budget() {
        MEMORYSTATUSEX memory{sizeof(memory)};if(!GlobalMemoryStatusEx(&memory)) throw Unavailable("memory counters unavailable");
        free_ram_=double(memory.ullAvailPhys)/1073741824.0-3;free_commit_=double(memory.ullAvailPageFile)/1073741824.0-3;
        double bytes=0;unsigned count=0;
        for(auto& m:maps_) if(m.process) {PROCESS_MEMORY_COUNTERS_EX counters{};counters.cb=sizeof(counters);
            if(GetProcessMemoryInfo(m.process,reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters),sizeof(counters))) {bytes+=double(counters.PrivateUsage);++count;}}
        need_=std::max(6.0,count ? 2.0*bytes/count/1073741824.0:6.0);
    }
    void launch(Map& m) {
        if(adopt(m) || m.blocked) return;
        const auto log=m.plan.name=="k00_marsh" ? "srv":"srv_"+m.plan.name;
        std::wstring args=L"\""+exe_+L"\" -nosplashwindow -noprefetch -netcoop -multi_instance -netcoop_background -logname "+widen(log)+
            L" -fsltx fsgame_server.ltx -netport "+std::to_wstring(m.plan.port)+L" -netcoop_start_location="+widen(m.start)+L" -netcoop_world="+widen(m.world)+
            L" -netcoop_hibernate=120 "+(m.demand ? std::wstring(L"-netcoop_idle_exit=21600 "):L"")+
            L"-start \"server(all/single/alife/new/portsv="+std::to_wstring(m.plan.port)+L"/maxplayers=129)\" \"client(localhost/name=serverauthority/port="+
            std::to_wstring(m.plan.port)+L"/portcl="+std::to_wstring(m.plan.port+1)+L")\"";
        DeleteFileW((folder_+L"\\host_stop_"+std::to_wstring(m.plan.port)+L".txt").c_str());
        DeleteFileW((folder_+L"\\status_"+std::to_wstring(m.plan.port)+L".txt").c_str());
        STARTUPINFOW si{sizeof(si)};si.dwFlags=STARTF_USESHOWWINDOW;si.wShowWindow=SW_HIDE;
        PROCESS_INFORMATION p{};
        if(!CreateProcessW(exe_.c_str(),args.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW|NORMAL_PRIORITY_CLASS,nullptr,root_.c_str(),&si,&p)) {
            m.blocked=true;transition(m,"failed","CreateProcess Win32="+std::to_string(GetLastError()));return;
        }
        CloseHandle(p.hThread);m.process=p.hProcess;m.pid=p.dwProcessId;m.loading=true;m.expected=false;m.launched=GetTickCount64();
        transition(m,"loading","native serialized launch");
    }
    void queue() {
        const bool paused=!enabled_ || exists(folder_+L"\\host_master_paused.txt");
        bool loading=false;for(const auto& m:maps_) loading|=m.process && m.loading;
        for(auto& m:maps_) {
            if(m.process || m.mode=="off") continue;
            const bool requested=m.mode=="on" || !m.demand || exists(file("wake_",m));
            if(!requested) {transition(m,"stopped");continue;}
            if(m.blocked) continue;
            if(paused) {transition(m,exists(folder_+L"\\host_master_paused.txt") ? "master_stopped":"master_wait","waiting for master service and verified world storage");continue;}
            if(m.retry_at>GetTickCount64()) continue;
            if(loading) {transition(m,"queued","another map is loading");continue;}
            if(free_ram_<need_ || free_commit_<need_) {transition(m,"memory","insufficient loading budget");continue;}
            if(exists(file("host_command_",m))) continue; // consume a late stop before launch
            launch(m);loading=m.process && m.loading;
        }
    }
    void publish() {
        json rows=json::array();
        unsigned active=0;for(const auto& map:maps_) active+=map.process!=nullptr;active_=active;
        for(const auto& m:maps_) rows.push_back({{"map",m.plan.name},{"port",m.plan.port},{"processId",m.pid},{"state",m.state},{"mode",m.mode},
            {"detail",m.detail},{"players",m.players},{"progress",m.state=="running" ? 100:0},{"failures",m.failures},
            {"retry_seconds",m.retry_at>GetTickCount64() ? int((m.retry_at-GetTickCount64()+999)/1000):0},
            {"exit_code",m.has_exit ? json(m.exit):json()}});
        write(folder_+L"\\host_view_native.json",json({{"updated",int64_t(time(nullptr))},{"controller","native"},{"pid",GetCurrentProcessId()},
            {"maps",rows},{"memory",{{"free_gb",free_ram_},{"commit_gb",free_commit_},{"need_gb",need_}}}}).dump());
        if(GetTickCount64()-last_heartbeat_>15000) {last_heartbeat_=GetTickCount64();
            log_line(format("[diag][host] heartbeat maps=%zu memory_free_gb=%.2f commit_free_gb=%.2f load_need_gb=%.2f enabled=%u",maps_.size(),free_ram_,free_commit_,need_,unsigned(enabled_.load())));}
    }
    void run() noexcept {
        while(!stopping_) {
            try {for(auto& m:maps_) {update(m);if(stop_all_ && m.process && !m.expected) stop_map(m);}budget();queue();publish();}
            catch(const std::exception& e) {log_line("[diag][host] controller error: "+std::string(e.what()));}
            for(int i=0;i<10 && !stopping_;++i) Sleep(100);
        }
    }
public:
    HostController(const std::wstring& root,const std::wstring& plan):root_(root),folder_(root+L"\\appdata\\server\\netcoop_cluster"),exe_(root+L"\\dedicated\\LostZoneServerDX11.exe") {
        std::filesystem::create_directories(folder_);
        std::string hash=sha256_hex(lower(narrow(root)));for(auto& c:hash) if(c>='a' && c<='f') c-=32;
        mutex_=CreateMutexW(nullptr,FALSE,(L"Local\\LostZoneCluster_"+widen(hash)).c_str());
        if(!mutex_ || GetLastError()==ERROR_ALREADY_EXISTS) {if(mutex_) CloseHandle(mutex_);mutex_=nullptr;throw Unavailable("another controller owns this server folder; close the old panel/watchdog");}
        try {
            const auto ini=parse_cluster_sections(read(plan));
            std::set<std::string> local={"","127.0.0.1","localhost","0.0.0.0"},hosts;
            wchar_t computer[256];DWORD computer_size=256;if(GetComputerNameW(computer,&computer_size)) local.insert(lower(narrow(computer)));
            ULONG adapter_bytes=0;GetAdaptersInfo(nullptr,&adapter_bytes);std::vector<unsigned char> adapters(adapter_bytes);
            if(adapter_bytes && GetAdaptersInfo(reinterpret_cast<IP_ADAPTER_INFO*>(adapters.data()),&adapter_bytes)==NO_ERROR)
                for(auto* a=reinterpret_cast<IP_ADAPTER_INFO*>(adapters.data());a;a=a->Next)
                    for(auto* ip=&a->IpAddressList;ip;ip=ip->Next) local.insert(ip->IpAddress.String);
            for(const auto& p:read_cluster(plan)) hosts.insert(lower(p.host));
            if(hosts.size()==1) local.insert(*hosts.begin());
            auto cluster=ini.find("cluster");if(cluster!=ini.end() && cluster->second.count("local_host")) local.insert(lower(cluster->second.at("local_host")));
            for(const auto& p:read_cluster(plan)) {
                if(!local.count(lower(p.host))) {log_line("[diag][host] remote map="+p.name+" address="+p.host+":"+std::to_string(p.port)+"; not launched on this PC");continue;}
                Map m;m.plan=p;
                auto launch=ini.find("launch");if(launch==ini.end() || !launch->second.count(p.name)) continue;
                m.start=launch->second.at(p.name);
                if(m.start.empty() || m.start.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")!=std::string::npos) throw Invalid("invalid start section for "+p.name);
                m.world=p.name=="k00_marsh" ? "zone":p.name=="l01_escape" ? "zone_escape":"zone_"+p.name;
                auto demand=ini.find("on_demand");m.demand=demand==ini.end() || !demand->second.count(p.name) || demand->second.at(p.name)!="0";
                m.mode=mode(m);adopt(m);maps_.push_back(std::move(m));
            }
            log_line(format("[diag][host] native controller owns %zu maps; exe=%s",maps_.size(),narrow(exe_).c_str()));
            unsigned active=0;for(const auto& map:maps_) active+=map.process!=nullptr;active_=active;
            worker_=std::thread([this]{run();});
        } catch(...) {for(auto& m:maps_) if(m.process) CloseHandle(m.process);CloseHandle(mutex_);mutex_=nullptr;throw;}
    }
    ~HostController() {stopping_=true;if(worker_.joinable()) worker_.join();for(auto& m:maps_) if(m.process) CloseHandle(m.process);if(mutex_) CloseHandle(mutex_);}
    void enabled(bool value) {enabled_=value;}
    void epoch(uint64_t value) {master_epoch_=value;}
    unsigned active() const {return active_;}
    void shutdown_locations() {enabled_=false;stop_all_=true;}
    void resume() {stop_all_=false;}
};
} // namespace lzm
