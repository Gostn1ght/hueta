#pragma once
#include <cstddef>
#include <cstdint>

namespace netcoop_world
{
// Supplied only by the native admission coordinator AFTER it owns this
// location lease. The worker renews that lease; it never claims or takes over.
struct CheckpointWorkerScope
{
    char location[65]{},instance[33]{};
    std::uint64_t world=0,seed=0,epoch=0,fence=0;
    unsigned lease_ms=15000;
};
struct CheckpointWorkerCapture
{
    char character[33]{};
    std::uint64_t generation=0,session=0,version=0,revision=0;
    unsigned slot=0;
};
enum class CheckpointCaptureState : unsigned { Missing,Buffered,Staged,Durable,Rejected };
struct CheckpointWorkerResult
{
    CheckpointCaptureState state=CheckpointCaptureState::Missing;
    std::uint64_t generation=0,revision=0,version=0,bytes=0;
    char sha256[65]{};
    bool latest_submitted=false,retiring=false;
};
struct CheckpointWorkerStatus
{
    bool initialized=false,ready=false,stopping=false,configuration_error=false,storage_error=false,authority_lost=false;
    unsigned captures=0,buffered=0;
    unsigned renewal_http_status=0,renewal_failures=0;
    std::uint64_t bytes=0,lease_renewals=0;
};

// No JSON, credentials, engine objects or exceptions cross this boundary.
// start/stop/destruction: coordinator thread, with all other callers quiesced.
// Other calls may run concurrently between lifecycle operations.
class CheckpointWorker
{
    struct State;
    State* state_=nullptr;
public:
    CheckpointWorker() noexcept=default;
    ~CheckpointWorker();
    CheckpointWorker(const CheckpointWorker&)=delete;
    CheckpointWorker& operator=(const CheckpointWorker&)=delete;
    // Starts asynchronous config/spool IO; true is not readiness/admission.
    bool start(const char* config_path,const wchar_t* spool_path,const CheckpointWorkerScope&) noexcept;
    // Owns bytes on success. Buffered is NOT locally/master durable.
    bool submit(const CheckpointWorkerCapture&,const void* bytes,std::size_t count) noexcept;
    bool poll(const char* character,std::uint64_t generation,CheckpointWorkerResult&) noexcept;
    bool generation_floor(const char* character,std::uint64_t&) noexcept;
    // Coordinator must first persist/consume the exact durable receipt.
    // A subsequent Missing result while initialized confirms local retirement.
    bool release(const char* character,std::uint64_t generation) noexcept;
    CheckpointWorkerStatus status() noexcept;
    // Stages buffered captures locally, without waiting for master completion.
    // false requires coordinator recovery/fallback; never a durable success.
    // In-flight filesystem IO can still delay joining, as with local saves.
    bool stop() noexcept;
};
}
