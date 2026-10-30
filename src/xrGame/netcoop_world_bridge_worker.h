#pragma once

#include "netcoop_world_clock.h"

namespace netcoop_world
{
struct BridgeDiagnostics
{
    bool ready=false, fetched=false, accepted=false;
    bool master_binding=false;
    std::uint64_t rtt_ms=0;
    double drift_game_ms=0;
    unsigned weather_phase=0,emission_phase=0;
    double weather_blend=0;
    unsigned http_status=0, transport_error=0, api_port=0;
};

// Coherent, bounded read-only projection. No credential, JSON or private state
// crosses the engine boundary. Local writer epoch is never the master epoch.
struct BridgeTimelineProjection
{
    bool present=false;
    std::uint64_t version=0,seed=0;
    char id[33]{},source[129]{},target[129]{};
    double warning=0,active=0,peak=0,ended=0,intensity=0;
};
struct MasterProjection
{
    WorldStateSnapshot world{};
    std::uint64_t event_watermark=0,local_world=0,local_seed=0,local_epoch=0;
    char location[129]{};
    bool master_binding=false;
    double estimated_world_ms=0,weather_blend=0;
    unsigned weather_phase=0,emission_phase=0;
    BridgeTimelineProjection weather{},emission{},psi_storm{};
    bool authority=false;
    char master_location[129]{};
};

// Parsing, IO, follower errors and threads are isolated in an exception-enabled
// translation unit without engine headers. This boundary never throws.
class WorldBridgeWorker
{
    struct State;
    State* state_=nullptr;
public:
    WorldBridgeWorker() noexcept=default;
    ~WorldBridgeWorker();
    WorldBridgeWorker(const WorldBridgeWorker&)=delete;
    WorldBridgeWorker& operator=(const WorldBridgeWorker&)=delete;
    // 0: absent optional config; -1: invalid/unavailable; 1: started observer.
    int start(const char* config_path, const WorldStateSnapshot& local, const char* location=nullptr) noexcept;
    BridgeDiagnostics tick(const WorldStateSnapshot& local) noexcept;
    // Simulation thread only, after tick(). Fails closed and clears output on
    // identity/epoch mismatch, expired holdover or missing accepted bootstrap.
    // This API grants no authority to apply the projection to game state.
    bool read_projection(const WorldStateSnapshot& local, MasterProjection& output) noexcept;
    void stop() noexcept;
};
}
