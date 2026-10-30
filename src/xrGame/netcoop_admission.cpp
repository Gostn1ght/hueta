// Exception-enabled, no engine/PCH headers (doc 135). Every HTTP call runs on
// the coordinator thread; the simulation thread only queues and polls.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "netcoop_admission.h"
#include "netcoop_checkpoint_worker.h"
#include "netcoop_player_checkpoint.h"
#include <algorithm>
#include <cmath>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <thread>

namespace netcoop_world
{
#ifdef _WIN32
namespace
{
constexpr std::uint64_t maximum=0x7fffffffffffffffULL;
constexpr unsigned lease_ms=15000;
std::string text(const char* value,std::size_t limit)
{
    if(!value) return std::string();
    std::size_t length=0;while(length<=limit && value[length]) ++length;
    if(length>limit) throw std::invalid_argument("admission text budget");
    return std::string(value,length);
}
std::string lower(std::string value)
{
    for(char& c:value) if(c>='A' && c<='Z') c=char(c-'A'+'a');
    return value;
}
std::string random_hex()
{
    unsigned char bytes[16]{};
    if(BCryptGenRandom(nullptr,bytes,sizeof(bytes),BCRYPT_USE_SYSTEM_PREFERRED_RNG)<0)
        throw std::runtime_error("admission identity unavailable");
    return checkpoint_hex_bytes(std::string(reinterpret_cast<const char*>(bytes),sizeof(bytes)));
}
template<std::size_t N> void put(char (&target)[N],const std::string& value)
{
    const auto count=std::min(value.size(),N-1);std::memcpy(target,value.data(),count);target[count]=0;
}
std::string key(const std::string& account,unsigned slot){return lower(account)+":"+std::to_string(slot);}
// The master's account row; false: a malformed one (skipped).
bool account_from(const BridgeJson& row,AccountRecord& out)
{
    const auto take=[&](const char* name,char* target,std::size_t size)
    {
        if(!row.contains(name) || !row[name].is_string()) return false;
        const auto& value=row[name].get_ref<const std::string&>();
        if(value.size()>=size) return false;
        std::memcpy(target,value.data(),value.size());target[value.size()]=0;
        return true;
    };
    out=AccountRecord();
    if(!row.is_object() || !take("login",out.login,sizeof(out.login)) || !take("role",out.role,sizeof(out.role)) ||
       !take("approval",out.approval,sizeof(out.approval)) || !take("salt",out.salt,sizeof(out.salt)) ||
       !take("hash",out.hash,sizeof(out.hash)) || !take("device",out.device,sizeof(out.device)) ||
       !take("firebase_uid",out.firebase,sizeof(out.firebase)) || !row.contains("money")) return false;
    const auto& money=row["money"];
    if(money.is_null()) return true;
    if(!money.is_number_unsigned() || money.get<std::uint64_t>()>0xffffffffULL) return false;
    out.has_money=true;out.money=std::uint32_t(money.get<std::uint64_t>());
    return true;
}
BridgeJson account_json(const AccountRecord& record)
{
    return BridgeJson{{"login",record.login},{"role",record.role},{"salt",record.salt},{"hash",record.hash},
        {"money",record.has_money ? BridgeJson(record.money):BridgeJson()},{"device",record.device},
        {"approval",record.approval},{"firebase_uid",record.firebase},{"fields",record.fields}};
}
}

struct AdmissionCoordinator::State
{
    // One admitted character: the master versions the next capture builds on.
    struct Character
    {
        std::string id,account;
        unsigned slot=0;
        std::uint64_t session=0,version=0,revision=0,generation=0,last=0;
        std::vector<std::uint64_t> outstanding; // submitted, not yet retired
        bool leaving=false;
    };
    enum class Kind { Admit,Leave,Depart,Order };
    struct Job
    {
        Kind kind=Kind::Admit;
        std::uint64_t ticket=0,deadline=0;
        std::string account,local,token,target,source;
        unsigned slot=0;
        WorldOrder order=WorldOrder::Weather;
        std::vector<double> values;
    };
    struct Outcome
    {
        AdmissionResult admission;
        DepartureResult departure;
        OrderResult order;
        std::vector<unsigned char> bytes;
        bool final=false;
    };

    std::string config_path,location,instance;
    std::wstring spool;
    WriterConfig config;
    CheckpointWorker worker;
    std::mutex lock;
    std::condition_variable wake;
    std::deque<Job> jobs;
    std::map<std::uint64_t,Outcome> outcomes;
    std::map<std::string,Character> characters; // key(account,slot)
    // Accounts (doc 154): puts keep their command ID across retries.
    struct AccountPut { std::string id; BridgeJson records; bool only_new=false; };
    std::deque<AccountPut> account_puts;
    std::vector<AccountRecord> account_changes;
    std::uint64_t account_revision=0,account_polled=0;
    AccountsState accounts_state=AccountsState::Waiting;
    std::uint64_t next_ticket=1,epoch=0,fence=0;
    bool stopping=false,ready=false,failed=false;
    unsigned last_http_status=0,open_attempts=0;
    std::string phase="initializing";
    std::thread thread;

    State(std::string file,std::string map,std::wstring directory)
        :config_path(std::move(file)),location(std::move(map)),instance(random_hex()),spool(std::move(directory))
    { thread=std::thread([this]{run();}); }

    bool request(const std::string& method,const std::string& path,const std::string& payload,BridgeJson& result,unsigned& status)
    {
        const bool ok=writer_request(config,instance,epoch,method,path,payload,result,status);
        {std::lock_guard<std::mutex> guard(lock);last_http_status=status;}
        return ok;
    }
    void set_phase(const char* value) {std::lock_guard<std::mutex> guard(lock);phase=value;}
    // One master command, the SAME command ID on every retry, until a reply,
    // a permanent refusal or the deadline.
    CheckpointStep command(const std::string& operation,const BridgeJson& arguments,BridgeJson& result,std::uint64_t deadline,
        const std::string& id=std::string())
    {
        const auto command_id=id.empty() ? random_hex():id;
        const auto payload=BridgeJson{{"command_id",command_id},{"operation",operation},{"arguments",arguments}}.dump();
        for(;;)
        {
            unsigned status=0;
            if(request("POST","/v1/command",payload,result,status)) return CheckpointStep::Complete;
            if(checkpoint_failure(status)==CheckpointStep::Rejected) return CheckpointStep::Rejected;
            if(GetTickCount64()>=deadline || halted()) return CheckpointStep::Retry;
            pause(250);
        }
    }
    bool halted(){std::lock_guard<std::mutex> guard(lock);return stopping;}
    void pause(unsigned ms)
    {
        std::unique_lock<std::mutex> guard(lock);
        wake.wait_for(guard,std::chrono::milliseconds(ms),[this]{return stopping;});
    }

    // Lease, adoption of this location's records, checkpoint worker.
    bool open()
    {
        {std::lock_guard<std::mutex> guard(lock);++open_attempts;phase="writer_config";}
        {
            std::ifstream file(config_path,std::ios::binary);char encoded[4097];
            if(!file) return false;
            file.read(encoded,sizeof(encoded));
            config=WriterConfig::parse(std::string(encoded,std::size_t(file.gcount())),location);
        }
        const auto deadline=GetTickCount64()+120000; // the master may still be starting
        set_phase("master_clock");
        BridgeJson clock;
        for(;;)
        {
            unsigned status=0;
            const bool ok=writer_request(config,instance,0,"GET","/v1/clock","",clock,status);
            {std::lock_guard<std::mutex> guard(lock);last_http_status=status;}
            if(ok) break;
            if(GetTickCount64()>=deadline || halted()) return false;
            pause(1000);
        }
        set_phase("world_identity");
        if(bridge_unsigned(clock,"world_id")!=config.world || bridge_unsigned(clock,"seed")!=config.seed) return false;
        epoch=bridge_unsigned(clock,"authority_epoch");
        if(!epoch || epoch>maximum) return false;
        BridgeJson claim;
        const auto claim_deadline=GetTickCount64()+60000;
        // Another owner's lease of this location (a previous run) expires
        // after its TTL; the claim is retried with the same command ID.
        const auto claim_id=random_hex();
        set_phase("location_claim");
        for(;;)
        {
            const auto step=command("location_claim",{{"location",location},{"capacity",128},{"ttl_ms",lease_ms}},claim,claim_deadline,claim_id);
            if(step==CheckpointStep::Complete) break;
            if(GetTickCount64()>=claim_deadline || halted()) return false;
            pause(1000);
        }
        fence=bridge_unsigned(claim,"fence");
        if(!fence || fence>maximum || claim.value("location",std::string())!=location) return false;
        BridgeJson recovered;
        set_phase("location_recover");
        if(command("location_recover",{{"location",location},{"fence",fence}},recovered,GetTickCount64()+30000)!=CheckpointStep::Complete)
            return false;
        // A capture spooled by an earlier run (another instance or fence) can
        // never be finished: every capture is a complete image of the local
        // file, so the next one supersedes it. Only this run's folder stays.
        CreateDirectoryW(spool.c_str(),nullptr);
        const std::wstring folder=L"run_"+std::to_wstring(fence)+L"_"+std::wstring(instance.begin(),instance.end());
        {
            std::error_code error;
            for(const auto& entry:std::filesystem::directory_iterator(spool,error))
                if(entry.is_directory(error) && entry.path().filename().wstring()!=folder)
                    std::filesystem::remove_all(entry.path(),error);
        }
        const auto directory=spool+L"\\"+folder;
        CheckpointWorkerScope scope;
        put(scope.location,location);put(scope.instance,instance);
        scope.world=config.world;scope.seed=config.seed;scope.epoch=epoch;scope.fence=fence;scope.lease_ms=lease_ms;
        set_phase("checkpoint_worker");
        if(!worker.start(config_path.c_str(),directory.c_str(),scope)) return false;
        const auto ready_deadline=GetTickCount64()+30000;
        for(;;)
        {
            const auto worker_status=worker.status();
            if(worker_status.ready) {set_phase("ready");return true;}
            if(worker_status.configuration_error || worker_status.authority_lost || GetTickCount64()>=ready_deadline || halted())
                return false;
            pause(100);
        }
    }

    void finish(std::uint64_t ticket,Outcome&& outcome)
    {
        std::lock_guard<std::mutex> guard(lock);
        outcome.final=true;outcomes[ticket]=std::move(outcome);
    }
    void refuse(const Job& job,const std::string& reason,AdmissionState state=AdmissionState::Refused)
    {
        Outcome outcome;
        if(job.kind==Kind::Depart) {outcome.departure.state=DepartureState::Refused;put(outcome.departure.reason,reason);}
        else if(job.kind==Kind::Order) {outcome.order.state=OrderState::Refused;put(outcome.order.reason,reason);}
        else {outcome.admission.state=state;put(outcome.admission.reason,reason);}
        finish(job.ticket,std::move(outcome));
    }

    // Waits until the newest capture of this character is durable (and
    // retires it), so the master holds the newest image before a handoff.
    bool settle(Character& character,std::uint64_t deadline)
    {
        if(!character.last) return true;
        for(;;)
        {
            // The worker sends one character's captures in order and keeps a
            // durable one until it is released: release while waiting.
            retire(character.id,character.outstanding);
            CheckpointWorkerResult result;
            const bool polled=worker.poll(character.id.c_str(),character.last,result);
            if(!polled) break; // already retired
            if(result.state==CheckpointCaptureState::Durable)
            {
                if(result.version) character.version=result.version;
                if(result.revision) character.revision=result.revision;
                break;
            }
            if(result.state==CheckpointCaptureState::Rejected) return false;
            if(GetTickCount64()>=deadline || halted()) return false;
            pause(100);
        }
        retire(character.id,character.outstanding);
        return true;
    }
    // Retires durable captures (the worker keeps each until released).
    void retire(const std::string& id,std::vector<std::uint64_t>& generations)
    {
        for(auto it=generations.begin();it!=generations.end();)
        {
            CheckpointWorkerResult result;
            if(!worker.poll(id.c_str(),*it,result)) {it=generations.erase(it);continue;}
            if(result.state==CheckpointCaptureState::Durable && worker.release(id.c_str(),*it)) {++it;continue;}
            ++it;
        }
    }
    void sweep()
    {
        std::vector<std::pair<std::string,std::vector<std::uint64_t>>> work;
        {
            std::lock_guard<std::mutex> guard(lock);
            for(const auto& entry:characters) if(!entry.second.outstanding.empty()) work.emplace_back(entry.first,entry.second.outstanding);
        }
        for(auto& item:work)
        {
            std::string id;
            {
                std::lock_guard<std::mutex> guard(lock);
                auto found=characters.find(item.first);if(found==characters.end()) continue;
                id=found->second.id;
            }
            const auto before=item.second;
            retire(id,item.second);
            std::lock_guard<std::mutex> guard(lock);
            auto found=characters.find(item.first);if(found==characters.end()) continue;
            auto& list=found->second.outstanding;
            // Drop the generations this pass saw retired; keep newer ones.
            for(const auto generation:before)
                if(std::find(item.second.begin(),item.second.end(),generation)==item.second.end())
                    list.erase(std::remove(list.begin(),list.end(),generation),list.end());
        }
    }

    void admit(const Job& job)
    {
        const auto account=lower(job.account);
        const auto id=checkpoint_player_id(config.world,config.seed,account,job.slot);
        BridgeJson result;
        // A level changer's handoff: claim and commit the frozen character.
        // A token the master refuses for good (the passage was finished,
        // aborted or expired; owner 2026-10-17: refused at every login after
        // a reconnect) is stale: it is dropped and the login goes on as usual.
        bool stale_token=false;
        if(!job.token.empty())
        {
            const auto claim=command("transfer_claim",{{"token",job.token},{"target_fence",fence}},result,job.deadline);
            if(claim==CheckpointStep::Retry)
                return refuse(job,"the world master did not answer for this passage",AdmissionState::Unavailable);
            // A refusal leaves no result object to read.
            const bool reply=claim==CheckpointStep::Complete && result.is_object();
            const auto transfer=reply ? result.value("id",std::string()):std::string();
            if(!reply || !checkpoint_hex(transfer,32) || result.value("entity_id",std::string())!=id)
                stale_token=true;
            else if(result.value("state",std::string())!="COMMITTED" &&
                command("transfer_commit",{{"transfer_id",transfer},{"target_fence",fence}},result,job.deadline)!=CheckpointStep::Complete)
                return refuse(job,"the transfer could not be committed by the world master");
        }
        const auto finish_admission=[&](Outcome&& outcome){outcome.admission.stale_token=stale_token;finish(job.ticket,std::move(outcome));};
        PlayerSlotObservation slot;unsigned status=0;
        for(;;)
        {
            const auto step=inspect_player_slot(config,instance,epoch,account,job.slot,fence,slot,status);
            if(step==CheckpointStep::Complete) break;
            if(step==CheckpointStep::Rejected)
                return refuse(job,status==409 ? "the character is active, in transit or has an unfinished save on another location":
                    "the world master refused this character slot");
            if(GetTickCount64()>=job.deadline || halted()) return refuse(job,"the world master did not answer",AdmissionState::Unavailable);
            pause(250);
        }
        if(slot.state==PlayerSlotStatus::Elsewhere)
        {
            Outcome outcome;
            outcome.admission.state=AdmissionState::Elsewhere;
            put(outcome.admission.home,slot.home);
            put(outcome.admission.reason,"the character is on "+slot.home);
            return finish_admission(std::move(outcome));
        }
        Character character;
        character.id=id;character.account=account;character.slot=job.slot;
        if(slot.state==PlayerSlotStatus::Absent)
        {
            // A new character, or one older than the master: its local file
            // becomes the first checkpoint with the first capture.
            if(command("entity_create",{{"entity_id",id},{"kind","CHARACTER"},{"location",location},{"fence",fence},
                {"state",BridgeJson::object()},{"account",account}},result,job.deadline)!=CheckpointStep::Complete)
                return refuse(job,"the world master could not register this character");
            character.version=bridge_unsigned(result,"version");character.session=1;character.revision=0;
        }
        else if(slot.state==PlayerSlotStatus::Disconnected)
        {
            if(command("session_resume",{{"character_id",id},{"location",location},{"fence",fence},{"version",slot.entity_version}},
                result,job.deadline)!=CheckpointStep::Complete)
                return refuse(job,"the world master could not resume this character here");
            character.version=bridge_unsigned(result,"version");character.session=bridge_unsigned(result,"session_fence");
            character.revision=slot.revision;
        }
        else if(slot.state==PlayerSlotStatus::Active)
        {
            character.version=slot.entity_version;character.session=slot.session_fence;character.revision=slot.revision;
        }
        else return refuse(job,"this character slot has an unactivated import on the world master",AdmissionState::Unavailable);
        if(!character.version || !character.session) return refuse(job,"the world master returned an invalid session");
        std::uint64_t floor=0;worker.generation_floor(id.c_str(),floor);
        character.generation=floor;
        Outcome outcome;
        outcome.admission.state=AdmissionState::Admitted;put(outcome.admission.character,id);
        outcome.admission.revision=character.revision;
        // Always return the authoritative image: the engine cache can be
        // older than a matching disk backup after this map was visited before.
        // Local files are consulted only when importing a slot with no revision.
        if(character.revision)
        {
            CheckpointDownload read(id,fence,character.session,character.revision,slot.sha256,std::size_t(slot.bytes));
            auto send=[this](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& reply,unsigned& code)
            { return request(method,path,payload,reply,code); };
            for(;;)
            {
                const auto step=read.step(send);
                if(step==CheckpointStep::Complete) break;
                if(step==CheckpointStep::Rejected) return refuse(job,"the world master's checkpoint could not be read");
                if(step==CheckpointStep::Retry)
                {
                    if(GetTickCount64()>=job.deadline || halted()) return refuse(job,"the world master's checkpoint read timed out");
                    pause(250);
                }
            }
            const auto& raw=read.bytes();
            outcome.bytes.assign(raw.begin(),raw.end());outcome.admission.master_bytes=true;
        }
        {
            std::lock_guard<std::mutex> guard(lock);
            characters[key(account,job.slot)]=std::move(character);
        }
        finish_admission(std::move(outcome));
    }

    bool take(const Job& job,Character& character)
    {
        std::lock_guard<std::mutex> guard(lock);
        auto found=characters.find(key(job.account,job.slot));
        if(found==characters.end()) return false;
        character=found->second;return true;
    }
    void forget(const Job& job)
    {
        std::lock_guard<std::mutex> guard(lock);
        characters.erase(key(job.account,job.slot));
    }
    void leave(const Job& job)
    {
        Character character;
        if(!take(job,character)) return finish(job.ticket,Outcome{});
        const bool durable=settle(character,job.deadline);
        BridgeJson result;
        // An unfinished capture blocks the disconnect on the master; the
        // character stays ACTIVE there and the next login resumes it as is.
        if(durable)
            command("session_disconnect",{{"character_id",character.id},{"fence",fence},{"version",character.version},
                {"state",BridgeJson::object()}},result,job.deadline);
        forget(job);
        finish(job.ticket,Outcome{});
    }
    void depart(const Job& job)
    {
        Character character;
        if(!take(job,character)) return refuse(job,"the character is not admitted through the world master");
        if(!settle(character,job.deadline)) return refuse(job,"the character's last save has not reached the world master");
        BridgeJson result;
        if(command("transfer_prepare",{{"entity_id",character.id},{"source",location},{"source_fence",fence},
            {"target",job.target},{"entity_version",character.version},{"ttl_ms",300000}},result,job.deadline)!=CheckpointStep::Complete)
            return refuse(job,"the world master refused the passage (the target location is unavailable or full)");
        const auto token=result.value("token",std::string());
        if(token.empty() || token.size()>2048) return refuse(job,"the world master returned an invalid transfer");
        forget(job);
        Outcome outcome;outcome.departure.state=DepartureState::Ready;put(outcome.departure.token,token);
        finish(job.ticket,std::move(outcome));
    }

    void carry_out(const Job& job)
    {
        BridgeJson values;
        const auto& v=job.values;
        switch(job.order)
        {
        case WorldOrder::Weather: values={{"source",job.source},{"target",job.target},{"transition_s",v[0]}};break;
        case WorldOrder::Emission:
        case WorldOrder::PsiStorm: values={{"durations",BridgeJson::array({v[0],v[1],v[2]})},{"intensity",v[3]}};break;
        case WorldOrder::Scale: values={{"value",v[0]}};break;
        case WorldOrder::Advance: values={{"game_s",v[0]}};break;
        }
        static const char* const names[]={"weather","emission","psi_storm","scale","advance"};
        BridgeJson result;
        const auto step=command("admin_relay",{{"account",job.account},{"order",names[unsigned(job.order)]},{"values",values}},
            result,job.deadline);
        if(step==CheckpointStep::Rejected) return refuse(job,"the world master refused the order");
        if(step!=CheckpointStep::Complete) return refuse(job,"the world master did not answer");
        Outcome outcome;outcome.order.state=OrderState::Done;
        finish(job.ticket,std::move(outcome));
    }

    // What this location changed goes first (a login on another map reads it
    // next), then the master's changes since the last revision, once a second.
    void accounts_sync()
    {
        for(;;)
        {
            AccountPut put;
            {
                std::lock_guard<std::mutex> guard(lock);
                if(account_puts.empty() || accounts_state==AccountsState::Unsupported) break;
                put=account_puts.front();
            }
            const auto payload=BridgeJson{{"command_id",put.id},{"operation","account_put"},
                {"arguments",{{"accounts",put.records},{"only_new",put.only_new}}}}.dump();
            BridgeJson result;unsigned status=0;
            if(!request("POST","/v1/command",payload,result,status) && checkpoint_failure(status)==CheckpointStep::Retry) return;
            std::lock_guard<std::mutex> guard(lock);
            account_puts.pop_front(); // done, or a record the master refuses for good
        }
        const auto now=GetTickCount64();
        if(account_polled && now-account_polled<1000) return;
        account_polled=now;
        for(int page=0;page<64;++page)
        {
            const auto payload=BridgeJson{{"command_id",random_hex()},{"operation","account_list"},
                {"arguments",{{"after",account_revision}}}}.dump();
            BridgeJson result;unsigned status=0;
            if(!request("POST","/v1/command",payload,result,status))
            {
                if(checkpoint_failure(status)==CheckpointStep::Rejected)
                {
                    std::lock_guard<std::mutex> guard(lock);
                    if(accounts_state==AccountsState::Waiting) accounts_state=AccountsState::Unsupported;
                }
                return;
            }
            if(!result.contains("accounts") || !result["accounts"].is_array() || !result.contains("revision") ||
               !result["revision"].is_number_unsigned()) return;
            std::vector<AccountRecord> rows;
            for(const auto& row:result["accounts"])
            {
                AccountRecord record;
                if(account_from(row,record)) rows.push_back(record);
            }
            const auto revision=result["revision"].get<std::uint64_t>();
            const bool last=result["accounts"].size()<1000;
            std::lock_guard<std::mutex> guard(lock);
            account_changes.insert(account_changes.end(),rows.begin(),rows.end());
            account_revision=std::max(account_revision,revision);
            if(last) { accounts_state=AccountsState::Synced;break; }
        }
    }

    void run() noexcept
    {
        bool opened=false;
        try{opened=open();}catch(...){opened=false;}
        {
            std::lock_guard<std::mutex> guard(lock);
            ready=opened;failed=!opened;wake.notify_all();
        }
        auto retry_at=GetTickCount64()+10000;
        for(;;)
        {
            // Initial connection failure is recoverable. Keep the coordinator
            // and queued results alive; never switch to a local account store
            // merely because the authority is temporarily unreachable.
            if(!opened && !halted() && GetTickCount64()>=retry_at)
            {
                worker.stop();
                try{opened=open();}catch(...){opened=false;}
                {std::lock_guard<std::mutex> guard(lock);ready=opened;failed=!opened;wake.notify_all();}
                retry_at=GetTickCount64()+10000;
            }
            if(opened) try{accounts_sync();}catch(...){}
            Job job;
            bool idle=false;
            {
                std::unique_lock<std::mutex> guard(lock);
                wake.wait_for(guard,std::chrono::milliseconds(500),[this]{return stopping || !jobs.empty();});
                if(jobs.empty())
                {
                    if(stopping) break;
                    idle=true;
                }
                else {job=std::move(jobs.front());jobs.pop_front();}
            }
            if(idle)
            {
                if(opened) try{sweep();}catch(...){}
                continue;
            }
            try
            {
                if(!opened) refuse(job,"the world master is unavailable",AdmissionState::Unavailable);
                else if(job.kind==Kind::Admit) admit(job);
                else if(job.kind==Kind::Leave) leave(job);
                else if(job.kind==Kind::Order) carry_out(job);
                else depart(job);
            }
            catch(...){refuse(job,"the world master exchange failed",AdmissionState::Unavailable);}
        }
        worker.stop();
    }
    std::uint64_t queue(Job&& job)
    {
        std::lock_guard<std::mutex> guard(lock);
        if(stopping || jobs.size()>1024) return 0;
        job.ticket=next_ticket++;
        const auto ticket=job.ticket;
        jobs.push_back(std::move(job));wake.notify_all();
        return ticket;
    }
};

AdmissionCoordinator::~AdmissionCoordinator(){stop();}
bool AdmissionCoordinator::accounts_take(std::vector<AccountRecord>& changed,AccountsState& state) noexcept
{
    changed.clear();state=AccountsState::Waiting;
    if(!state_) return false;
    try
    {
        std::lock_guard<std::mutex> guard(state_->lock);
        state=state_->accounts_state;
        changed.swap(state_->account_changes);
        return true;
    }
    catch(...){return false;}
}
bool AdmissionCoordinator::accounts_put(const AccountRecord* records,std::size_t count,bool only_new) noexcept
{
    if(!state_ || !records || !count) return false;
    try
    {
        std::vector<State::AccountPut> batches;
        for(std::size_t first=0;first<count;first+=100) // the master takes 64 KiB a request
        {
            State::AccountPut put;put.id=random_hex();put.only_new=only_new;put.records=BridgeJson::array();
            for(std::size_t i=first;i<count && i<first+100;++i) put.records.push_back(account_json(records[i]));
            batches.push_back(std::move(put));
        }
        std::lock_guard<std::mutex> guard(state_->lock);
        if(state_->stopping || state_->account_puts.size()+batches.size()>4096) return false;
        for(auto& put:batches) state_->account_puts.push_back(std::move(put));
        state_->wake.notify_all();
        return true;
    }
    catch(...){return false;}
}
bool AdmissionCoordinator::store_record(const char* operation,const char* bucket,const char* key_name,const char* expected,const char* value,
                                       std::string& output,bool& swapped) noexcept
{
    output.clear();swapped=false;if(!state_) return false;
    try {
        const auto op=text(operation,32),b=text(bucket,96),k=text(key_name,96);
        if(op!="store_read" && op!="store_keys" && op!="store_swap") return false;
        WriterConfig config;std::string instance,location;std::uint64_t epoch=0,fence=0;
        {std::lock_guard<std::mutex> guard(state_->lock);if(!state_->ready || state_->stopping) return false;
            config=state_->config;instance=state_->instance;location=state_->location;epoch=state_->epoch;fence=state_->fence;}
        BridgeJson args={{"location",location},{"fence",fence},{"bucket",b}};
        if(op!="store_keys") args["key"]=k;
        if(op=="store_swap") {args["expected"]=checkpoint_base64(text(expected,65536));args["value"]=checkpoint_base64(text(value,65536));}
        const auto payload=BridgeJson{{"command_id",random_hex()},{"operation",op},{"arguments",args}}.dump();
        BridgeJson result;unsigned status=0;
        if(!writer_request(config,instance,epoch,"POST","/v1/store",payload,result,status)) return false;
        if(op=="store_swap") {if(!result.contains("swapped") || !result["swapped"].is_boolean()) return false;swapped=result["swapped"].get<bool>();}
        else output=checkpoint_unbase64(result.at("value").get<std::string>(),op=="store_keys" ? 512*1024:65536);
        return true;
    }catch(...){return false;}
}

bool AdmissionCoordinator::start(const char* config_path,const char* location,const wchar_t* spool_path) noexcept
{
    stop();
    try
    {
        const auto config=text(config_path,2048),map=text(location,64);
        if(config.empty() || map.empty() || !spool_path) return false;
        if(GetFileAttributesA(config.c_str())==INVALID_FILE_ATTRIBUTES) return false;
        std::size_t length=0;while(length<=2048 && spool_path[length]) ++length;
        if(!length || length>2048) return false;
        state_=new State(config,map,std::wstring(spool_path,length));
        return true;
    }
    catch(...){state_=nullptr;return false;}
}
CoordinatorStatus AdmissionCoordinator::status() noexcept
{
    CoordinatorStatus result;
    if(!state_) return result;
    try
    {
        std::lock_guard<std::mutex> guard(state_->lock);
        result.started=true;result.ready=state_->ready && !state_->stopping;result.failed=state_->failed;
        result.epoch=state_->epoch;result.fence=state_->fence;
        result.characters=unsigned(state_->characters.size());result.pending=unsigned(state_->jobs.size());
        result.http_status=state_->last_http_status;result.attempts=state_->open_attempts;
        put(result.phase,state_->phase);
        const auto checkpoint=state_->worker.status();
        if(checkpoint.authority_lost || checkpoint.configuration_error) {result.ready=false;result.failed=true;put(result.phase,"checkpoint_authority_lost");}
    }
    catch(...){}
    return result;
}
std::uint64_t AdmissionCoordinator::admit(const char* account,unsigned slot,const void* local,std::size_t local_size,const char* token) noexcept
{
    try
    {
        if(!state_ || local_size>checkpoint_limit || (local_size && !local)) return 0;
        State::Job job;job.kind=State::Kind::Admit;
        job.account=text(account,20);job.slot=slot;job.token=text(token,2048);
        if(local_size) job.local.assign(static_cast<const char*>(local),local_size);
        if(job.account.size()<3 || slot<1 || slot>10) return 0;
        job.deadline=GetTickCount64()+30000;
        return state_->queue(std::move(job));
    }
    catch(...){return 0;}
}
bool AdmissionCoordinator::poll_admission(std::uint64_t ticket,AdmissionResult& result,std::vector<unsigned char>& bytes) noexcept
{
    result={};bytes.clear();
    try
    {
        if(!state_) {result.state=AdmissionState::Unavailable;return true;}
        std::lock_guard<std::mutex> guard(state_->lock);
        auto found=state_->outcomes.find(ticket);
        if(found==state_->outcomes.end()) return false;
        result=found->second.admission;bytes.swap(found->second.bytes);
        state_->outcomes.erase(found);return true;
    }
    catch(...){result={};result.state=AdmissionState::Unavailable;return true;}
}
bool AdmissionCoordinator::capture(const char* account,unsigned slot,const void* bytes,std::size_t count) noexcept
{
    try
    {
        if(!state_ || !bytes || count<4) return false;
        std::lock_guard<std::mutex> guard(state_->lock);
        auto found=state_->characters.find(key(text(account,20),slot));
        if(found==state_->characters.end() || !state_->ready) return false;
        auto& character=found->second;
        CheckpointWorkerCapture value;
        put(value.character,character.id);value.slot=slot;
        value.generation=character.generation+1;value.session=character.session;
        value.version=character.version;value.revision=character.revision;
        if(!state_->worker.submit(value,bytes,count)) return false;
        // Each finished capture advances the entity version and revision by one.
        character.generation=value.generation;character.last=value.generation;
        character.outstanding.push_back(value.generation);
        ++character.version;++character.revision;
        return true;
    }
    catch(...){return false;}
}
bool AdmissionCoordinator::leave(const char* account,unsigned slot) noexcept
{
    try
    {
        if(!state_) return false;
        State::Job job;job.kind=State::Kind::Leave;job.account=text(account,20);job.slot=slot;
        job.deadline=GetTickCount64()+60000;
        return state_->queue(std::move(job))!=0;
    }
    catch(...){return false;}
}
std::uint64_t AdmissionCoordinator::depart(const char* account,unsigned slot,const char* target) noexcept
{
    try
    {
        if(!state_) return 0;
        State::Job job;job.kind=State::Kind::Depart;job.account=text(account,20);job.slot=slot;job.target=text(target,64);
        if(job.target.empty() || job.target.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")!=std::string::npos)
            return 0;
        job.deadline=GetTickCount64()+20000;
        return state_->queue(std::move(job));
    }
    catch(...){return 0;}
}
bool AdmissionCoordinator::poll_departure(std::uint64_t ticket,DepartureResult& result) noexcept
{
    result={};
    try
    {
        if(!state_) {result.state=DepartureState::Refused;return true;}
        std::lock_guard<std::mutex> guard(state_->lock);
        auto found=state_->outcomes.find(ticket);
        if(found==state_->outcomes.end()) return false;
        result=found->second.departure;state_->outcomes.erase(found);return true;
    }
    catch(...){result={};result.state=DepartureState::Refused;return true;}
}
bool AdmissionCoordinator::admitted(const char* account,unsigned slot) noexcept
{
    try
    {
        if(!state_) return false;
        std::lock_guard<std::mutex> guard(state_->lock);
        return state_->characters.count(key(text(account,20),slot))!=0;
    }
    catch(...){return false;}
}
std::uint64_t AdmissionCoordinator::world_order(const char* account,WorldOrder order,const char* source,const char* target,
    const double* values,unsigned count) noexcept
{
    try
    {
        if(!state_ || !values) return 0;
        static const unsigned needed[]={1,4,4,1,1};
        if(unsigned(order)>unsigned(WorldOrder::Advance) || count!=needed[unsigned(order)]) return 0;
        State::Job job;job.kind=State::Kind::Order;job.order=order;job.account=text(account,64);
        job.values.assign(values,values+count);
        for(double value:job.values) if(!std::isfinite(value)) return 0;
        if(order==WorldOrder::Weather)
        {
            job.source=text(source,64);job.target=text(target,64);
            if(job.source.empty() || job.target.empty()) return 0;
        }
        if(job.account.empty()) return 0;
        job.deadline=GetTickCount64()+15000;
        return state_->queue(std::move(job));
    }
    catch(...){return 0;}
}
bool AdmissionCoordinator::poll_order(std::uint64_t ticket,OrderResult& result) noexcept
{
    result={};
    try
    {
        if(!state_) {result.state=OrderState::Refused;return true;}
        std::lock_guard<std::mutex> guard(state_->lock);
        auto found=state_->outcomes.find(ticket);
        if(found==state_->outcomes.end()) return false;
        result=found->second.order;state_->outcomes.erase(found);return true;
    }
    catch(...){result={};result.state=OrderState::Refused;return true;}
}
void AdmissionCoordinator::stop() noexcept
{
    if(!state_) return;
    auto state=state_;state_=nullptr;
    try
    {
        {std::lock_guard<std::mutex> guard(state->lock);state->stopping=true;}state->wake.notify_all();
        if(state->thread.joinable()) state->thread.join();
        delete state;
    }
    catch(...){}
}
#else
struct AdmissionCoordinator::State {};
AdmissionCoordinator::~AdmissionCoordinator()=default;
bool AdmissionCoordinator::start(const char*,const char*,const wchar_t*) noexcept{return false;}
CoordinatorStatus AdmissionCoordinator::status() noexcept{return {};}
std::uint64_t AdmissionCoordinator::admit(const char*,unsigned,const void*,std::size_t,const char*) noexcept{return 0;}
bool AdmissionCoordinator::poll_admission(std::uint64_t,AdmissionResult& result,std::vector<unsigned char>& bytes) noexcept
{result={};result.state=AdmissionState::Unavailable;bytes.clear();return true;}
bool AdmissionCoordinator::capture(const char*,unsigned,const void*,std::size_t) noexcept{return false;}
bool AdmissionCoordinator::leave(const char*,unsigned) noexcept{return false;}
std::uint64_t AdmissionCoordinator::depart(const char*,unsigned,const char*) noexcept{return 0;}
bool AdmissionCoordinator::poll_departure(std::uint64_t,DepartureResult& result) noexcept{result={};result.state=DepartureState::Refused;return true;}
bool AdmissionCoordinator::admitted(const char*,unsigned) noexcept{return false;}
std::uint64_t AdmissionCoordinator::world_order(const char*,WorldOrder,const char*,const char*,const double*,unsigned) noexcept{return 0;}
bool AdmissionCoordinator::poll_order(std::uint64_t,OrderResult& result) noexcept{result={};result.state=OrderState::Refused;return true;}
bool AdmissionCoordinator::accounts_take(std::vector<AccountRecord>& changed,AccountsState& state) noexcept
{changed.clear();state=AccountsState::Unsupported;return false;}
bool AdmissionCoordinator::accounts_put(const AccountRecord*,std::size_t,bool) noexcept{return false;}
bool AdmissionCoordinator::store_record(const char*,const char*,const char*,const char*,const char*,std::string& output,bool& swapped) noexcept
{output.clear();swapped=false;return false;}
void AdmissionCoordinator::stop() noexcept{}
#endif
}
