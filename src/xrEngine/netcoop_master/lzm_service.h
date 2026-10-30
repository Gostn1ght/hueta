// http.py, console.py, gateway.py and __main__.run(): the running master.
#pragma once
#include "lzm_http.h"
#include "lzm_ownership.h"

#include <condition_variable>

namespace lzm
{
struct Principal
{
    std::string actor, role;
    std::vector<std::string> locations;
};

class Credentials
{
public:
    explicit Credentials(const json& entries);
    std::optional<Principal> authenticate(const std::optional<std::string>& header) const;
    std::vector<std::pair<std::string, Principal>> entries;  // sha256(token) raw, principal
};

struct Snapshot;  // the window's view, see lzm_window.h
class WorldFiles;

class Service
{
public:
    struct Options
    {
        std::wstring config;
        int gateway_port = 0;      // 0 = no public entry
        std::wstring cluster;      // location plan for the entry
        std::optional<int> port;   // --port
        std::wstring runtime_root; // native host package; empty for API fixtures
    };
    explicit Service(const Options& options);
    ~Service();
    void stop();
    bool running() const { return !stopped_; }
    bool ready() const;

    // console.py: one operator line (quit/exit are refused: the window stops it).
    std::string console(const std::string& line);
    json recovery_status();

    Store& store() { return *store_; }
    World& world() { return *world_; }
    std::string worker_error();
    int api_port() const { return http_ ? http_->port() : 0; }

private:
    std::unique_ptr<Store> store_;
    std::unique_ptr<World> world_;
    std::unique_ptr<Timelines> timelines_;
    std::unique_ptr<Director> director_;
    std::unique_ptr<Ownership> ownership_;
    std::unique_ptr<Transfers> transfers_;
    std::unique_ptr<PlayerSaves> saves_;
    std::unique_ptr<Credentials> credentials_;
    std::unique_ptr<WorldFiles> world_files_;
    std::unique_ptr<HttpServer> http_, gateway_;
    std::wstring cluster_, runtime_root_;
    std::atomic<bool> ready_{ true }, stopped_{ false };
    std::mutex status_lock_;
    std::optional<int64_t> last_cycle_ns_;
    int64_t events_processed_ = 0;
    std::string worker_error_type_;
    std::thread worker_;
    std::mutex wake_lock_;
    std::condition_variable wake_;
    std::mutex rate_lock_;
    std::map<std::string, std::pair<double, int64_t>> buckets_;
    std::mutex entry_lock_;
    std::map<std::string, std::vector<int64_t>> entry_hits_;

    void check_supported();
    void loop();
    void worker_succeeded(int64_t processed);
    void worker_failed(const std::string& type);
    bool allow(const std::string& actor);
    json execute(const Principal& principal, const json& request);
    void allowed(const Principal& principal, const json& location);
    HttpResponse handle(HttpRequest& request, const std::function<bool(size_t)>& read_body);
    HttpResponse handle_entry(HttpRequest& request);
    std::string timeline_command(const std::string& name, const std::vector<std::string>& args);
    json admin_relay(const std::string& actor, const std::string& command_id, const json& args);
    json account_list(const json& args);
    json account_put(const json& args);
    void initialize_records(const std::wstring& root);
    json record_exchange(const std::string& actor,const std::string& command_id,const std::string& operation,const json& args);
    std::optional<std::string> home(const std::string& account, int64_t slot);
};

// gateway.read_cluster: [locations] name = host:port in file order.
struct PlanLocation { std::string name, host; int port; };
std::vector<PlanLocation> read_cluster(const std::wstring& path);
int read_entry_port(const std::wstring& path);
std::string exception_type(const std::exception& error);
} // namespace lzm
