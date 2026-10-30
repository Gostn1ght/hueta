#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include <string>

// M2b native admission coordinator (doc 135): the world master is the primary
// store of player characters. A location server claims its lease, admits a
// player only through the master (create / resume / transfer claim), takes the
// master's durable checkpoint over its local file, mirrors every save and
// closes the session after the last save is durable. No JSON, credentials,
// engine objects or exceptions cross this boundary.
namespace netcoop_world
{
// Elsewhere: the character lives on another location (home); the player is
// sent there instead of being refused (owner 2026-10-17).
enum class AdmissionState : unsigned { Pending, Admitted, Refused, Unavailable, Elsewhere };
struct AdmissionResult
{
    AdmissionState state=AdmissionState::Pending;
    char character[33]{};
    std::uint64_t revision=0;
    bool master_bytes=false; // the bytes are the master's durable checkpoint, newer than the local file
    char reason[160]{};
    char home[65]{};
    bool stale_token=false; // the passage token was finished/expired: delete it
};
enum class DepartureState : unsigned { Pending, Ready, Refused };
struct DepartureResult
{
    DepartureState state=DepartureState::Pending;
    char token[2049]{};
    char reason[160]{};
};
// An administrator's world order, carried out by the world master for every
// location (owner 2026-10-23: time and weather changed one map only).
// Weather: source/target cycle or preset, values[0] transition game seconds.
// Emission/PsiStorm: values[0..2] phase durations, values[3] intensity.
// Scale: values[0]. Advance: values[0] game seconds forward.
enum class WorldOrder : unsigned { Weather, Emission, PsiStorm, Scale, Advance };
enum class OrderState : unsigned { Pending, Done, Refused };
struct OrderResult
{
    OrderState state=OrderState::Pending;
    char reason[160]{};
};
// One account as the world master keeps it (owner 2026-10-25, doc 154: the
// master is the only store; a location keeps a mirror).
struct AccountRecord
{
    char login[21]{},role[8]{},approval[10]{};
    char salt[257]{},hash[257]{},device[129]{},firebase[129]{};
    bool has_money=false;
    std::uint32_t money=0;
};
// Waiting: no complete copy yet. Unsupported: the master has no accounts
// (an older one): the location keeps its file.
enum class AccountsState : unsigned { Waiting, Synced, Unsupported };
struct CoordinatorStatus
{
    bool started=false,ready=false,failed=false;
    std::uint64_t epoch=0,fence=0;
    unsigned characters=0,pending=0;
    unsigned http_status=0, attempts=0;
    char phase[64]{};
};

// start/stop: simulation thread. The other calls only queue work or read a
// result; all HTTP and filesystem IO runs on the coordinator's own threads.
class AdmissionCoordinator
{
    struct State;
    State* state_=nullptr;
public:
    AdmissionCoordinator() noexcept=default;
    ~AdmissionCoordinator();
    AdmissionCoordinator(const AdmissionCoordinator&)=delete;
    AdmissionCoordinator& operator=(const AdmissionCoordinator&)=delete;
    // Asynchronous: claims the location lease, adopts the location's records
    // and starts the checkpoint worker. False: no master writer (local files).
    bool start(const char* config_path,const char* location,const wchar_t* spool_path) noexcept;
    CoordinatorStatus status() noexcept;
    // local: the local character file's bytes (nullptr/0 without one), compared
    // with the master's checkpoint. token: a master transfer token from the
    // source location, or nullptr. 0: refused at once (invalid identity).
    std::uint64_t admit(const char* account,unsigned slot,const void* local,std::size_t local_size,const char* token) noexcept;
    // true once final; bytes receive the master checkpoint when master_bytes.
    bool poll_admission(std::uint64_t ticket,AdmissionResult& result,std::vector<unsigned char>& bytes) noexcept;
    // Mirrors one complete local snapshot (NCH bytes) of an admitted character.
    bool capture(const char* account,unsigned slot,const void* bytes,std::size_t count) noexcept;
    // The player left: the session closes after the last capture is durable.
    bool leave(const char* account,unsigned slot) noexcept;
    // Level changer: after the last capture is durable the master freezes the
    // character for the target location and returns its transfer token.
    std::uint64_t depart(const char* account,unsigned slot,const char* target) noexcept;
    bool poll_departure(std::uint64_t ticket,DepartureResult& result) noexcept;
    bool admitted(const char* account,unsigned slot) noexcept;
    // 0: not queued (no coordinator, invalid order).
    std::uint64_t world_order(const char* account,WorldOrder order,const char* source,const char* target,
                              const double* values,unsigned count) noexcept;
    bool poll_order(std::uint64_t ticket,OrderResult& result) noexcept;
    // The records the master changed since the last call (all of them first).
    bool accounts_take(std::vector<AccountRecord>& changed,AccountsState& state) noexcept;
    // Queues records for the master; only_new keeps the ones it has (import).
    bool accounts_put(const AccountRecord* records,std::size_t count,bool only_new) noexcept;
    // Rare synchronous Lua shared-record operations, bounded loopback IO.
    // Values remain opaque bytes; the master performs the atomic CAS.
    bool store_record(const char* operation,const char* bucket,const char* key,const char* expected,const char* value,
                      std::string& output,bool& swapped) noexcept;
    void stop() noexcept;
};
}
