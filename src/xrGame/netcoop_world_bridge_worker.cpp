// No pch_script/xrCore headers: this isolated module needs ordinary C++
// unwinding for JSON validation, mutexes, threads and WinHTTP RAII handles.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "netcoop_world_bridge_worker.h"
#include "netcoop_world_bridge.h"
#include <condition_variable>
#include <cstring>
#include <fstream>
#include <memory>
#include <mutex>
#include <thread>

namespace netcoop_world
{
static std::uint64_t bridge_mono_ms() noexcept
{
#ifdef _WIN32
    return GetTickCount64();
#else
    return std::uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
#endif
}

struct WorldBridgeWorker::State
{
    BridgeConfig config;
    BridgeObserver observer;
    std::uint64_t local_world,local_seed,local_epoch;
    std::mutex lock;
    std::condition_variable wake;
    bool stopping=false, pending=false, successful=false;
    BridgeBootstrap incoming{};
    std::uint64_t sent=0, received=0;
    unsigned last_http=0,last_transport=0;
    std::thread worker;

    State(BridgeConfig connection, const WorldStateSnapshot& local)
        : config(std::move(connection)),
          observer(config.bound ? config.master_world:local.clock.world_id,
                   config.bound ? config.master_seed:local.world_seed),
          local_world(local.clock.world_id),local_seed(local.world_seed),
          local_epoch(local.clock.authority_epoch),worker([this]{run();}) {}
    ~State()
    {
        { std::lock_guard<std::mutex> guard(lock);stopping=true; }
        wake.notify_all();
        if (worker.joinable()) worker.join();
    }
    void run() noexcept
    {
        for (;;)
        {
            { std::lock_guard<std::mutex> guard(lock);if (stopping) return; }
            BridgeBootstrap result{};
            const auto started=bridge_mono_ms();
            bool ok=false;
            unsigned http=0,transport=0;
            try
            {
#ifdef _WIN32
                SetLastError(0);
                ok=bridge_fetch(config,result,&http);
                if(!ok) transport=GetLastError();
#endif
            }
            catch (...) {} // Fail closed; no payloads or credentials in logs.
            const auto finished=bridge_mono_ms();
            std::unique_lock<std::mutex> guard(lock);
            incoming=std::move(result);successful=ok;sent=started;received=finished;pending=true;
            last_http=http;last_transport=transport;
            if (wake.wait_for(guard,std::chrono::seconds(5),[this]{return stopping;})) return;
        }
    }
    bool matches_local(const WorldStateSnapshot& local) const noexcept
    {
        return local.clock.world_id==local_world && local.world_seed==local_seed &&
            local.clock.authority_epoch==local_epoch;
    }
    BridgeDiagnostics tick(const WorldStateSnapshot& local)
    {
        if (!matches_local(local)) return {};
        BridgeBootstrap sample{};
        bool available=false,ok=false;
        std::uint64_t started=0,finished=0;
        unsigned http=0,transport=0;
        {
            std::lock_guard<std::mutex> guard(lock);
            if (pending) {sample=incoming;available=true;ok=successful;started=sent;finished=received;pending=false;}
            http=last_http;transport=last_transport;
        }
        BridgeDiagnostics result;
        result.master_binding=config.bound;
        result.http_status=http;result.transport_error=transport;result.api_port=config.port;
        result.fetched=available && ok;
        result.rtt_ms=finished>=started ? finished-started : 0;
        if (result.fetched)
            result.accepted=observer.receive(sample,started,finished)==SyncResult::applied;
        const auto now=bridge_mono_ms();
        result.ready=observer.ready(now);
        if (result.ready)
        {
            const auto calendar=observer.estimate(now);
            result.drift_game_ms=calendar-local.clock.world_ms;
            const auto& globals=observer.globals();
            result.weather_phase=bridge_weather_phase(globals.weather,calendar);
            result.weather_blend=bridge_weather_blend(globals.weather,calendar);
            result.emission_phase=bridge_emission_phase(globals.emission,calendar);
        }
        return result;
    }
    static BridgeTimelineProjection project(const BridgeTimeline& timeline)
    {
        BridgeTimelineProjection result;
        result.present=timeline.present;result.version=timeline.version;result.seed=timeline.seed;
        // Sizes are bounded by the wire parser; include each terminating NUL.
        std::memcpy(result.id,timeline.id.c_str(),timeline.id.size()+1);
        std::memcpy(result.source,timeline.source.c_str(),timeline.source.size()+1);
        std::memcpy(result.target,timeline.target.c_str(),timeline.target.size()+1);
        result.warning=timeline.warning;result.active=timeline.active;result.peak=timeline.peak;
        result.ended=timeline.ended;result.intensity=timeline.intensity;
        return result;
    }
    bool read_projection(const WorldStateSnapshot& local, MasterProjection& output)
    {
        const auto now=bridge_mono_ms();
        if (!matches_local(local) || !observer.ready(now)) return false;
        const auto& globals=observer.globals();
        output.world=globals.world;output.event_watermark=globals.event_watermark;
        output.local_world=local_world;output.local_seed=local_seed;output.local_epoch=local_epoch;
        output.master_binding=config.bound;
        std::memcpy(output.location,config.location.c_str(),config.location.size()+1);
        output.estimated_world_ms=observer.estimate(now);
        output.weather=project(globals.weather);output.emission=project(globals.emission);
        output.psi_storm=project(globals.psi_storm);output.authority=config.authority;
        output.weather_phase=bridge_weather_phase(globals.weather,output.estimated_world_ms);
        output.weather_blend=bridge_weather_blend(globals.weather,output.estimated_world_ms);
        output.emission_phase=bridge_emission_phase(globals.emission,output.estimated_world_ms);
        return true;
    }
};

WorldBridgeWorker::~WorldBridgeWorker() {stop();}
int WorldBridgeWorker::start(const char* path, const WorldStateSnapshot& local, const char* location) noexcept
{
    stop();
    try
    {
        if (!path || !*path || !valid(local.clock) || local.schema!=1 || !local.state_revision) return -1;
        std::ifstream input(path,std::ios::binary);
        if (!input) return 0;
        char bytes[4097];input.read(bytes,sizeof(bytes));
        auto config=BridgeConfig::parse(std::string(bytes,std::size_t(input.gcount())));
        if (!config.matches_local(local,location)) return -1;
        auto state=std::make_unique<State>(std::move(config),local);
        state_=state.release();
        return 1;
    }
    catch (...) {return -1;}
}
BridgeDiagnostics WorldBridgeWorker::tick(const WorldStateSnapshot& local) noexcept
{
    if (!state_) return {};
    try {return state_->tick(local);}
    catch (...) {return {};}
}
bool WorldBridgeWorker::read_projection(const WorldStateSnapshot& local, MasterProjection& output) noexcept
{
    output={};
    if (!state_) return false;
    try {if (state_->read_projection(local,output)) return true;}
    catch (...) {}
    output={};
    return false;
}
void WorldBridgeWorker::stop() noexcept
{
    delete state_;
    state_=nullptr;
}
}
