// Exception-enabled, no engine/PCH headers. All filesystem/HTTP work stays
// here, including startup. The caller supplies an already authorized scope.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "netcoop_checkpoint_worker.h"
#include "netcoop_checkpoint_outbox.h"
#include <condition_variable>
#include <cstring>
#include <fstream>
#include <mutex>
#include <thread>

namespace netcoop_world
{
#ifdef _WIN32
namespace
{
constexpr std::uint64_t maximum=0x7fffffffffffffffULL;
std::string fixed(const char* text,std::size_t maximum_size)
{
    if(!text) throw std::invalid_argument("checkpoint text missing");
    std::size_t length=0;while(length<=maximum_size && text[length]) ++length;
    if(length>maximum_size) throw std::invalid_argument("checkpoint text budget");
    return std::string(text,length);
}
std::string character_id(const char* text)
{
    auto result=fixed(text,32);
    if(!checkpoint_hex(result,32)) throw std::invalid_argument("checkpoint character identity");
    return result;
}
std::string command_id()
{
    unsigned char bytes[16]{};
    if(BCryptGenRandom(nullptr,bytes,sizeof(bytes),BCRYPT_USE_SYSTEM_PREFERRED_RNG)<0)
        throw std::runtime_error("checkpoint renewal identity unavailable");
    return checkpoint_hex_bytes(std::string(reinterpret_cast<const char*>(bytes),sizeof(bytes)));
}
CheckpointCapture capture(const CheckpointWorkerCapture& value,std::uint64_t fence)
{
    const auto id=character_id(value.character);
    if(!value.generation || value.generation>maximum || !value.session || value.session>maximum ||
        !value.version || value.version>=maximum || value.revision>=maximum || value.slot<1 || value.slot>10)
        throw std::invalid_argument("checkpoint capture bounds");
    return {id,value.generation,fence,value.session,value.version,value.revision,value.slot};
}
}

struct CheckpointWorker::State
{
    using Key=std::pair<std::string,std::uint64_t>;
    struct Record
    {
        CheckpointCapture capture;
        CheckpointWorkerResult result;
        std::string raw;
        std::uint64_t retry=0;
        bool staged=false,retiring=false;
    };
    std::string config_path,instance,location;
    std::wstring spool_path;
    CheckpointWorkerScope scope;
    WriterConfig config;
    std::mutex lock;
    std::condition_variable wake;
    bool stopping=false,initialized=false,configuration_error=false,storage_error=false,authority_lost=false;
    bool fatal=false,all_staged=false;
    std::uint64_t lease_deadline=0,renewals=0,bytes=0;
    unsigned renewal_http_status=0,renewal_failures=0;
    std::map<Key,Record> records;
    std::map<std::string,std::uint64_t> floor;
    std::thread pump,heartbeat;

    State(std::string file,std::wstring directory,CheckpointWorkerScope value)
        :config_path(std::move(file)),instance(fixed(value.instance,32)),location(fixed(value.location,64)),
         spool_path(std::move(directory)),scope(value)
    { pump=std::thread([this]{run();}); }
    bool lease_ready_locked() const
    { return initialized && !stopping && !fatal && !authority_lost && GetTickCount64()<lease_deadline; }
    bool ready_locked() const {return lease_ready_locked() && !storage_error;}
    CheckpointWorkerStatus status()
    {
        std::lock_guard<std::mutex> guard(lock);
        CheckpointWorkerStatus result;
        result.initialized=initialized;result.ready=ready_locked();result.stopping=stopping;
        result.configuration_error=configuration_error;result.storage_error=storage_error;result.authority_lost=authority_lost;
        result.captures=unsigned(records.size());result.bytes=bytes;result.lease_renewals=renewals;
        result.renewal_http_status=renewal_http_status;result.renewal_failures=renewal_failures;
        for(const auto& record:records) if(!record.second.staged) ++result.buffered;
        return result;
    }
    void renew() noexcept
    {
        try
        {
            while(true)
            {
                std::string id=command_id();
                const auto sent=GetTickCount64(); // Keep original send time across lost replies.
                bool accepted=false;
                while(!accepted)
                {
                    {std::lock_guard<std::mutex> guard(lock);if(stopping || authority_lost) return;}
                    BridgeJson result;unsigned http_status=0;
                    const auto payload=BridgeJson{{"command_id",id},{"operation","location_renew"},
                        {"arguments",{{"location",location},{"fence",scope.fence},{"ttl_ms",scope.lease_ms}}}}.dump();
                    const bool ok=writer_request(config,instance,scope.epoch,"POST","/v1/command",payload,result,http_status);
                    bool valid=false;
                    if(ok)
                        valid=result.is_object() && result.value("location",std::string())==location &&
                            bridge_unsigned(result,"fence")==scope.fence && bridge_unsigned(result,"expires_ms")>0;
                    std::unique_lock<std::mutex> guard(lock);
                    if(stopping) return;
                    renewal_http_status=http_status;
                    if(!valid)++renewal_failures;
                    if(valid)
                    {
                        lease_deadline=sent+scope.lease_ms;++renewals;accepted=true;wake.notify_all();
                    }
                    else
                    {
                        // A malformed success or any permanent HTTP refusal
                        // seals this scope. Never claim/recover another lease.
                        if(ok || checkpoint_failure(http_status)==CheckpointStep::Rejected)
                        {authority_lost=true;lease_deadline=0;wake.notify_all();return;}
                        wake.wait_for(guard,std::chrono::milliseconds(250),[this]{return stopping;});
                    }
                }
                std::unique_lock<std::mutex> guard(lock);
                const auto now=GetTickCount64();
                const auto delay=lease_deadline>now ? std::min<std::uint64_t>(5000,std::min<std::uint64_t>(scope.lease_ms/3,lease_deadline-now)):0;
                wake.wait_for(guard,std::chrono::milliseconds(delay),[this]{return stopping;});
                if(stopping) return;
            }
        }
        catch(...)
        {std::lock_guard<std::mutex> guard(lock);authority_lost=true;lease_deadline=0;wake.notify_all();}
    }
    void seed(CheckpointOutbox& queue)
    {
        auto restored_floor=queue.generations();
        std::map<Key,Record> restored;
        std::uint64_t total=0;
        for(const auto& item:queue.captures())
        {
            if(item.fence!=scope.fence) throw std::invalid_argument("checkpoint recovered lease fence changed");
            Record record;record.capture=item;record.staged=true;
            record.result.state=CheckpointCaptureState::Staged;record.result.generation=item.generation;
            record.result.bytes=queue.capture_bytes(item.character,item.generation);total+=record.result.bytes;
            restored.emplace(Key{item.character,item.generation},std::move(record));
        }
        std::lock_guard<std::mutex> guard(lock);
        records.swap(restored);floor.swap(restored_floor);bytes=total;initialized=true;
    }
    bool stage_one(CheckpointOutbox& queue)
    {
        Key key;CheckpointCapture item;std::string raw;
        {
            std::lock_guard<std::mutex> guard(lock);
            auto found=std::find_if(records.begin(),records.end(),[](const auto& pair){return !pair.second.staged;});
            if(found==records.end()) return false;
            key=found->first;item=found->second.capture;raw.swap(found->second.raw);
        }
        bool accepted=false;
        try {accepted=queue.enqueue(item,raw);}
        catch(...)
        {
            std::lock_guard<std::mutex> guard(lock);raw.swap(records.at(key).raw);throw;
        }
        {
            std::lock_guard<std::mutex> guard(lock);
            auto& record=records.at(key);
            if(accepted){record.staged=true;record.result.state=CheckpointCaptureState::Staged;storage_error=false;}
            else {raw.swap(record.raw);storage_error=true;}
        }
        if(!accepted) throw std::runtime_error("checkpoint staging not durable");
        return true;
    }
    bool retire_one(CheckpointOutbox& queue)
    {
        Key key;
        {
            std::lock_guard<std::mutex> guard(lock);
            auto found=std::find_if(records.begin(),records.end(),[](const auto& pair){return pair.second.retiring;});
            if(found==records.end()) return false;
            key=found->first;
        }
        if(!queue.retire(key.first,key.second)) throw std::runtime_error("checkpoint retirement not durable");
        std::lock_guard<std::mutex> guard(lock);
        bytes-=records.at(key).result.bytes;records.erase(key);storage_error=false;return true;
    }
    bool send_one(CheckpointOutbox& queue,std::size_t& cursor)
    {
        auto pending=queue.pending();
        for(std::size_t count=0;count<pending.size();++count)
        {
            const auto character=pending[(cursor+count)%pending.size()];
            Key key;
            {
                std::lock_guard<std::mutex> guard(lock);
                if(!lease_ready_locked()) return false; // Retry storage errors before re-admitting producers.
                auto first=records.lower_bound(Key{character,0});
                if(first==records.end() || first->first.first!=character) throw std::logic_error("checkpoint scheduler identity");
                if(first->second.result.state!=CheckpointCaptureState::Staged || first->second.retry>GetTickCount64()) continue;
                key=first->first;
            }
            cursor=(cursor+count+1)%pending.size();
            auto request=[this](const std::string& method,const std::string& path,const std::string& payload,BridgeJson& result,unsigned& http_status)
            {
                return writer_request(config,instance,scope.epoch,method,path,payload,result,http_status);
            };
            const auto outcome=queue.advance(character,request);
            BridgeJson receipt;
            if(outcome==CheckpointStep::Complete) receipt=queue.completion(character);
            std::lock_guard<std::mutex> guard(lock);
            auto& record=records.at(key);
            if(outcome==CheckpointStep::Progress || outcome==CheckpointStep::Complete) storage_error=false;
            if(outcome==CheckpointStep::Rejected) record.result.state=CheckpointCaptureState::Rejected;
            else if(outcome==CheckpointStep::Retry) record.retry=GetTickCount64()+250;
            else if(outcome==CheckpointStep::Complete)
            {
                const auto& result=receipt.at("result");
                record.result.revision=bridge_unsigned(result,"revision");record.result.version=bridge_unsigned(result,"entity_version");
                const auto sha=result.at("sha256").get<std::string>();
                if(!checkpoint_hex(sha,64) || bridge_unsigned(receipt,"generation")!=key.second)
                    throw std::invalid_argument("checkpoint receipt identity");
                std::memcpy(record.result.sha256,sha.c_str(),65);record.result.state=CheckpointCaptureState::Durable;
            }
            return true;
        }
        return false;
    }
    void run() noexcept
    {
        try
        {
            {
                std::ifstream file(config_path,std::ios::binary);char encoded[4097];
                if(!file) throw std::invalid_argument("checkpoint configuration unavailable");
                file.read(encoded,sizeof(encoded));config=WriterConfig::parse(std::string(encoded,std::size_t(file.gcount())),location);
                if(config.world!=scope.world || config.seed!=scope.seed) throw std::invalid_argument("checkpoint world changed");
            }
        }
        catch(...){std::lock_guard<std::mutex> guard(lock);configuration_error=true;return;}
        try
        {
            CheckpointOutbox queue(spool_path,config,instance,scope.epoch);seed(queue);
            heartbeat=std::thread([this]{renew();});
            std::size_t cursor=0;
            for(;;)
            {
                bool progress=false,stop=false;
                {std::lock_guard<std::mutex> guard(lock);stop=stopping;}
                try
                {
                    progress=retire_one(queue);
                    progress=stage_one(queue) || progress;
                    if(!stop) progress=send_one(queue,cursor) || progress;
                }
                catch(const std::invalid_argument&)
                {std::lock_guard<std::mutex> guard(lock);storage_error=true;fatal=true;}
                catch(const std::runtime_error&)
                {std::lock_guard<std::mutex> guard(lock);storage_error=true;progress=false;}
                std::unique_lock<std::mutex> guard(lock);
                bool buffered=false,retiring=false;
                for(const auto& record:records){buffered|=!record.second.staged;retiring|=record.second.retiring;}
                if(stopping && ((!buffered && !retiring) || storage_error || fatal)) {all_staged=!buffered;return;}
                if(fatal) {wake.wait(guard,[this]{return stopping;});all_staged=!buffered;return;}
                if(!progress) wake.wait_for(guard,std::chrono::milliseconds(250));
            }
        }
        catch(...){std::lock_guard<std::mutex> guard(lock);storage_error=true;fatal=true;}
    }
    bool submit(const CheckpointWorkerCapture& value,const void* data,std::size_t count)
    {
        const auto item=capture(value,scope.fence);
        if(!checkpoint_format(data,count)) return false;
        const auto source=static_cast<const char*>(data);
        std::lock_guard<std::mutex> guard(lock);
        if(!ready_locked() || records.size()>=outbox_jobs || count>outbox_bytes-bytes) return false;
        auto known=floor.find(item.character);
        if(known!=floor.end() && item.generation<=known->second) return false;
        if(known==floor.end() && floor.size()>=outbox_history) return false;
        const Record* previous=nullptr;
        for(const auto& record:records) if(record.first.first==item.character)
        {
            if(record.second.result.state==CheckpointCaptureState::Rejected) return false;
            previous=&record.second;
        }
        if(previous && (item.session!=previous->capture.session || item.slot!=previous->capture.slot ||
            item.version!=previous->capture.version+1 || item.revision!=previous->capture.revision+1)) return false;
        Record record;record.capture=item;record.raw.assign(source,count);
        record.result.state=CheckpointCaptureState::Buffered;record.result.generation=item.generation;record.result.bytes=count;
        const Key key{item.character,item.generation};
        records.emplace(key,std::move(record));
        try
        {
            if(known==floor.end()) floor.emplace(item.character,item.generation);
            else known->second=item.generation;
        }
        catch(...){records.erase(key);throw;}
        bytes+=count;wake.notify_all();return true;
    }
};

CheckpointWorker::~CheckpointWorker(){stop();}
bool CheckpointWorker::start(const char* path,const wchar_t* directory,const CheckpointWorkerScope& scope) noexcept
{
    if(!stop()) return false;
    try
    {
        const auto config=fixed(path,4096),location=fixed(scope.location,64),instance=fixed(scope.instance,32);
        if(config.empty() || location.empty() || location.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")!=std::string::npos ||
            !checkpoint_hex(instance,32) || !scope.world || !scope.epoch || scope.epoch>maximum || !scope.fence || scope.fence>maximum ||
            scope.lease_ms<1000 || scope.lease_ms>60000 || !directory) return false;
        std::size_t length=0;while(length<=2048 && directory[length]) ++length;
        if(!length || length>2048) return false;
        auto state=std::make_unique<State>(config,std::wstring(directory,length),scope);state_=state.release();return true;
    }
    catch(...){return false;}
}
bool CheckpointWorker::submit(const CheckpointWorkerCapture& value,const void* bytes,std::size_t count) noexcept
{try{return state_ && state_->submit(value,bytes,count);}catch(...){return false;}}
bool CheckpointWorker::poll(const char* id,std::uint64_t generation,CheckpointWorkerResult& result) noexcept
{
    result={};
    try
    {
        const auto character=character_id(id);if(!state_) return false;
        std::lock_guard<std::mutex> guard(state_->lock);
        const auto found=state_->records.find(State::Key{character,generation});if(found==state_->records.end()) return false;
        result=found->second.result;result.retiring=found->second.retiring;
        result.latest_submitted=state_->floor.at(character)==generation;return true;
    }
    catch(...){result={};return false;}
}
bool CheckpointWorker::generation_floor(const char* id,std::uint64_t& output) noexcept
{
    output=0;
    try
    {
        const auto character=character_id(id);if(!state_) return false;
        std::lock_guard<std::mutex> guard(state_->lock);if(!state_->initialized) return false;
        const auto found=state_->floor.find(character);if(found!=state_->floor.end()) output=found->second;return true;
    }
    catch(...){output=0;return false;}
}
bool CheckpointWorker::release(const char* id,std::uint64_t generation) noexcept
{
    try
    {
        const auto character=character_id(id);if(!state_) return false;
        std::lock_guard<std::mutex> guard(state_->lock);if(state_->stopping || state_->fatal) return false;
        auto found=state_->records.find(State::Key{character,generation});
        if(found==state_->records.end() || found->second.result.state!=CheckpointCaptureState::Durable) return false;
        found->second.retiring=true;state_->wake.notify_all();return true;
    }
    catch(...){return false;}
}
CheckpointWorkerStatus CheckpointWorker::status() noexcept
{try{return state_ ? state_->status():CheckpointWorkerStatus{};}catch(...){return {};}}
bool CheckpointWorker::stop() noexcept
{
    if(!state_) return true;
    auto state=state_;state_=nullptr;
    try
    {
        {std::lock_guard<std::mutex> guard(state->lock);state->stopping=true;}state->wake.notify_all();
        if(state->pump.joinable()) state->pump.join();
        if(state->heartbeat.joinable()) state->heartbeat.join();
        const bool result=state->all_staged;delete state;return result;
    }
    catch(...){state_=state;return false;} // Retain state for coordinator recovery/retry.
}
#else
struct CheckpointWorker::State {};
CheckpointWorker::~CheckpointWorker()=default;
bool CheckpointWorker::start(const char*,const wchar_t*,const CheckpointWorkerScope&) noexcept{return false;}
bool CheckpointWorker::submit(const CheckpointWorkerCapture&,const void*,std::size_t) noexcept{return false;}
bool CheckpointWorker::poll(const char*,std::uint64_t,CheckpointWorkerResult& result) noexcept{result={};return false;}
bool CheckpointWorker::generation_floor(const char*,std::uint64_t& result) noexcept{result=0;return false;}
bool CheckpointWorker::release(const char*,std::uint64_t) noexcept{return false;}
CheckpointWorkerStatus CheckpointWorker::status() noexcept{return {};}
bool CheckpointWorker::stop() noexcept{return true;}
#endif
}
