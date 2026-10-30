#include "lzm_service.h"

#include <windows.h>

#include <algorithm>
#include <charconv>
#include <condition_variable>
#include <fstream>
#include <sstream>
#include <filesystem>
#include "lzm_world_files.h"

namespace lzm
{
// -- credentials (http.py) ---------------------------------------------------------------------------
static bool token_ok(const std::string& token)
{
    if (token.size() < 32 || token.size() > 256) return false;
    for (unsigned char c : token)
        if (!(isalnum(c) || c == '_' || c == '-') || c >= 0x80) return false;
    return true;
}

Credentials::Credentials(const json& config)
{
    if (!config.is_object() || config.empty() || config.size() > 128) throw Invalid("invalid server credentials configuration");
    std::vector<std::string> seen;
    for (auto it = config.begin(); it != config.end(); ++it)
    {
        identifier(it.key());
        const json& data = it.value();
        std::string role = data.is_object() && data.contains("role") && data["role"].is_string() ? data["role"].get<std::string>() : "";
        if (role != "admin" && role != "location" && role != "observer") throw Invalid("invalid server credential role");
        json token = data.contains("token") ? data["token"] : json();
        json locations = data.contains("locations") ? data["locations"] : json::array();
        if (!token.is_string() || !token_ok(token.get<std::string>())) throw Invalid("server token must contain at least 32 ASCII characters");
        if (!locations.is_array() || locations.size() > 64) throw Invalid("invalid location allowlist");
        Principal principal{ it.key(), role, {} };
        for (auto& l : locations) principal.locations.push_back(identifier(l));
        if (role == "location" && principal.locations.empty()) throw Invalid("location principal needs an explicit allowlist");
        std::string digest = sha256_raw(token.get<std::string>());
        if (std::find(seen.begin(), seen.end(), digest) != seen.end()) throw Invalid("server tokens must be unique");
        seen.push_back(digest);
        entries.push_back({ digest, principal });
    }
}

std::optional<Principal> Credentials::authenticate(const std::optional<std::string>& header) const
{
    if (!header || header->rfind("Bearer ", 0) != 0 || header->size() > 300) return std::nullopt;
    std::string token = header->substr(7);
    for (unsigned char c : token)
        if (c >= 0x80) return std::nullopt;
    std::string digest = sha256_raw(token);
    std::optional<Principal> found;
    for (auto& entry : entries)
        if (constant_time_equal(digest, entry.first) && !found) found = entry.second;
    return found;
}

std::string exception_type(const std::exception& error)
{
    if (dynamic_cast<const Invalid*>(&error)) return "Invalid";
    if (dynamic_cast<const Conflict*>(&error)) return "Conflict";
    if (dynamic_cast<const Unavailable*>(&error)) return "Unavailable";
    if (dynamic_cast<const Forbidden*>(&error)) return "PermissionError";
    if (dynamic_cast<const UnavailableHandler*>(&error)) return "UnavailableHandler";
    if (dynamic_cast<const json::type_error*>(&error)) return "TypeError";
    if (dynamic_cast<const std::invalid_argument*>(&error)) return "ValueError";
    if (dynamic_cast<const json::out_of_range*>(&error)) return "KeyError";
    return "RuntimeError";
}

// -- the plan (gateway.py) ---------------------------------------------------------------------------------------
static std::string read_file(const std::wstring& path)
{
    std::ifstream in(path, std::ios::binary);
    if (!in) return {};
    std::ostringstream text;
    text << in.rdbuf();
    return text.str();
}

static bool location_name_ok(const std::string& name)
{
    if (name.empty() || name.size() > 64) return false;
    for (unsigned char c : name)
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_')) return false;
    return true;
}

static bool host_ok(const std::string& host)
{
    if (host.empty() || host.size() > 253) return false;
    for (unsigned char c : host)
        if (!(isalnum(c) || c == '.' || c == '-') || c >= 0x80) return false;
    return true;
}

std::vector<PlanLocation> read_cluster(const std::wstring& path)
{
    std::vector<PlanLocation> out;
    std::string section;
    for (auto raw : split(read_file(path), '\n'))
    {
        std::string line = trim(split(raw, ';')[0]);
        if (line.empty()) continue;
        if (line.front() == '[' && line.back() == ']')
        {
            section = lower(trim(line.substr(1, line.size() - 2)));
            continue;
        }
        size_t eq = line.find('=');
        if (section != "locations" || eq == std::string::npos) continue;
        std::string name = trim(line.substr(0, eq)), value = trim(line.substr(eq + 1));
        size_t colon = value.rfind(':');
        std::string host = colon == std::string::npos ? "" : value.substr(0, colon);
        std::string port = colon == std::string::npos ? value : value.substr(colon + 1);
        bool digits = !port.empty() && std::all_of(port.begin(), port.end(), [](char c) { return c >= '0' && c <= '9'; });
        if (location_name_ok(name) && (host.empty() || host_ok(host)) && digits && port.size() < 7)
        {
            int number = std::stoi(port);
            if (number > 0 && number < 65536) out.push_back({ name, host, number });
        }
    }
    return out;
}

int read_entry_port(const std::wstring& path)
{
    std::string section;
    for (auto raw : split(read_file(path), '\n'))
    {
        std::string line = trim(split(raw, ';')[0]);
        if (!line.empty() && line.front() == '[' && line.back() == ']') { section = lower(trim(line.substr(1, line.size() - 2))); continue; }
        size_t eq = line.find('=');
        if (section == "cluster" && eq != std::string::npos && trim(line.substr(0, eq)) == "entry_port")
        {
            std::string value = trim(line.substr(eq + 1));
            if (!value.empty() && value.size() < 7 && std::all_of(value.begin(), value.end(), [](char c) { return c >= '0' && c <= '9'; }))
            {
                // 1267 was the default (Marsh's UDP number); the entry is 5446 now.
                const int port = std::stoi(value);
                return port == 1267 ? 5446 : port;
            }
        }
    }
    // Owner 2026-10-25: players always enter on port 5446.
    return 5446;
}

// -- the service (__main__.run) -----------------------------------------------------------------------------------
Service::Service(const Options& options) : cluster_(options.cluster), runtime_root_(options.runtime_root)
{
    json config = loads(read_file(options.config));
    if (!config.is_object() || !config.contains("schema") || config["schema"] != 1) throw Invalid("unsupported service configuration");
    credentials_ = std::make_unique<Credentials>(config.contains("credentials") ? config["credentials"] : json());
    std::string key;
    {
        std::string hexkey = config.value("signing_key", std::string());
        if (hexkey.size() % 2) throw Invalid("invalid signing key");
        for (size_t i = 0; i < hexkey.size(); i += 2) key += char(std::stoi(hexkey.substr(i, 2), nullptr, 16));
    }
    int port = options.port ? *options.port : (config.contains("port") ? int(as_int(config["port"])) : 38477);
    if (port < 0 || port > 65535) throw Invalid("invalid service port");
    std::string database = config.value("database", std::string());
    if (database.empty() || database.find("..") != std::string::npos || database.find(':') != std::string::npos ||
        database[0] == '\\' || database[0] == '/')
        throw Invalid("database must stay inside the service configuration folder");
    std::wstring folder = options.config.substr(0, options.config.find_last_of(L"\\/") + 1);
    store_ = std::make_unique<Store>(folder + widen(database));
    std::optional<uint64_t> world_id, seed;
    if (config.contains("world_id") && !config["world_id"].is_null()) world_id = config["world_id"].get<uint64_t>();
    if (config.contains("seed") && !config["seed"].is_null()) seed = config["seed"].get<uint64_t>();
    world_ = std::make_unique<World>(*store_, world_id, seed, config.contains("initial_ms") ? as_number(config["initial_ms"]) : 0.0,
                                     config.contains("scale") ? as_number(config["scale"]) : 10.0);
    timelines_ = std::make_unique<Timelines>(*world_);
    ownership_ = std::make_unique<Ownership>(*world_);
    transfers_ = std::make_unique<Transfers>(*world_, *ownership_, key);
    saves_ = std::make_unique<PlayerSaves>(*world_, *ownership_);
    initialize_records(options.runtime_root);
    check_supported();
    director_ = std::make_unique<Director>(*world_, *timelines_, config.contains("director") ? config["director"] : json());
    worker_succeeded(0);
    if(!options.runtime_root.empty()) world_files_=std::make_unique<WorldFiles>(*store_,options.runtime_root,options.cluster);
    http_ = std::make_unique<HttpServer>("127.0.0.1", port, 16, [this](HttpRequest& r, const std::function<bool(size_t)>& body) { return handle(r, body); });
    log_line(format("Lost Zone World listening on 127.0.0.1:%d; epoch=%lld", http_->port(), (long long)*store_->epoch));
    if (options.gateway_port > 0)
    {
        gateway_ = std::make_unique<HttpServer>("0.0.0.0", options.gateway_port, 64,
                                                [this](HttpRequest& r, const std::function<bool(size_t)>&) { return handle_entry(r); },
                                                false, "LostZoneMaster");
        log_line(format("Lost Zone entry for players on TCP port %d (open it in the router as well)", options.gateway_port));
    }
    // Last: a constructor that throws must not leave a running thread behind.
    worker_ = std::thread([this] { loop(); });
}

Service::~Service() { stop(); }
bool Service::ready() const {return ready_ && (!world_files_ || world_files_->ready());}

void Service::stop()
{
    if (stopped_.exchange(true)) return;
    wake_.notify_all();
    if (worker_.joinable()) worker_.join();
    ready_ = false;
    if (gateway_) gateway_->stop();
    if (http_) http_->stop();
    if (world_files_) world_files_->stop();
    try
    {
        if (world_ && store_->epoch) world_->sample();
    }
    catch (...) {}
    store_->close();
}

// The engine master runs what the location servers use. A world that used the
// Python service's offline simulation, quests or trade (admin-only features no
// map calls) stays with that service until those parts are ported.
void Service::check_supported()
{
    std::lock_guard<std::recursive_mutex> guard(store_->lock);
    Db& db = store_->db;
    int64_t quests = db.scalar("SELECT COUNT(*) FROM quest").get<int64_t>() + db.scalar("SELECT COUNT(*) FROM quest_requirement").get<int64_t>();
    int64_t routes = db.scalar("SELECT COUNT(*) FROM route WHERE active=1").get<int64_t>();
    int64_t offline = db.scalar("SELECT COUNT(*) FROM entity WHERE writer LIKE 'offline:%'").get<int64_t>();
    int64_t foreign = db.scalar("SELECT COUNT(*) FROM scheduled_event WHERE state='PENDING' AND type NOT IN ('TimelinePhase','CorpseCleanupBatch')").get<int64_t>();
    if (quests || routes || offline || foreign)
        throw Unavailable(format("world uses offline simulation/quests (quests=%lld routes=%lld offline=%lld events=%lld)",
                                 (long long)quests, (long long)routes, (long long)offline, (long long)foreign));
}

void Service::loop()
{
    int64_t last = monotonic_ns(), planned = 0;
    while (true)
    {
        {
            std::unique_lock<std::mutex> lock(wake_lock_);
            wake_.wait_for(lock, std::chrono::seconds(1), [this] { return stopped_.load(); });
        }
        if (stopped_) break;
        try
        {
            int64_t processed = timelines_->scheduler.run_due(64, 10);
            if (monotonic_ns() - planned >= 2000000000LL)
            {
                planned = monotonic_ns();
                for (auto& line : director_->tick()) log_line("[мир] " + line);
            }
            if (monotonic_ns() - last >= 5000000000LL)
            {
                world_->sample();
                last = monotonic_ns();
            }
            worker_succeeded(processed);
        }
        catch (const std::exception& error)
        {
            worker_failed(exception_type(error));
        }
    }
}

void Service::worker_succeeded(int64_t processed)
{
    if (processed < 0 || processed > 256) throw Invalid("invalid checkpoint worker event count");
    std::lock_guard<std::recursive_mutex> guard(store_->lock);
    store_->require_epoch(store_->db);
    json pending = store_->db.one("SELECT 1 FROM scheduled_event WHERE state='PENDING' AND due_world_ms<=? LIMIT 1", { world_->now() });
    std::lock_guard<std::mutex> status(status_lock_);
    last_cycle_ns_ = monotonic_ns();
    events_processed_ += processed;
    worker_error_type_.clear();
    ready_ = pending.is_null();
}

void Service::worker_failed(const std::string& type)
{
    std::lock_guard<std::mutex> status(status_lock_);
    worker_error_type_ = type;
    ready_ = false;
}

std::string Service::worker_error()
{
    std::lock_guard<std::mutex> status(status_lock_);
    return worker_error_type_;
}

json Service::recovery_status()
{
    std::lock_guard<std::recursive_mutex> guard(store_->lock);
    store_->require_epoch(store_->db);
    json durable = store_->db.one("SELECT world_id,epoch,world_ms,event_highwater,revision FROM world WHERE singleton=1");
    auto rows = store_->db.all("SELECT id,type,aggregate_id,due_world_ms,priority,expected_version FROM scheduled_event "
                               "WHERE state='PENDING' ORDER BY due_world_ms,priority,id LIMIT 1025");
    json now;
    try { now = world_->now(); }
    catch (const Unavailable&) {}
    json oldest;
    if (!rows.empty())
    {
        oldest = rows[0];
        oldest["handler_registered"] = world_->scheduler_handlers.count(oldest["type"].get<std::string>()) > 0;
    }
    std::lock_guard<std::mutex> status(status_lock_);
    json due;
    if (!now.is_null())
    {
        int64_t count = 0;
        for (size_t i = 0; i < rows.size() && i < 1024; ++i)
            if (rows[i]["due_world_ms"].get<double>() <= now.get<double>()) ++count;
        due = count;
    }
    return { { "schema", 1 }, { "admission_ready", ready() }, { "world", durable }, { "observed_world_ms", now },
             { "pending_sample_count", std::min<size_t>(rows.size(), 1024) }, { "pending_has_more", rows.size() > 1024 },
             { "due_sample_count", due }, { "oldest_pending", oldest },
             { "worker_error_type", worker_error_type_.empty() ? json() : json(worker_error_type_) },
             { "events_processed", events_processed_ },
             { "last_cycle_age_ms", last_cycle_ns_ ? json(double(monotonic_ns() - *last_cycle_ns_) / 1e6) : json() } };
}

bool Service::allow(const std::string& actor)
{
    // RateLimit(rate=100, burst=200) per credential.
    std::lock_guard<std::mutex> guard(rate_lock_);
    int64_t now = monotonic_ns();
    auto it = buckets_.find(actor);
    double credit = 200;
    int64_t previous = now;
    if (it != buckets_.end()) { credit = it->second.first; previous = it->second.second; }
    credit = std::min(200.0, credit + double(now - previous) / 1e9 * 100);
    if (credit < 1)
    {
        buckets_[actor] = { credit, now };
        return false;
    }
    buckets_[actor] = { credit - 1, now };
    return true;
}

void Service::allowed(const Principal& principal, const json& location)
{
    std::string name = identifier(location);
    if (principal.role != "admin" && std::find(principal.locations.begin(), principal.locations.end(), name) == principal.locations.end())
        throw Forbidden("location is outside this server's allowlist");
}

namespace
{
struct Spec
{
    std::vector<std::string> required;
    std::vector<std::pair<std::string, json>> optional;
};

json bind_args(const json& args, const Spec& spec)
{
    json out = json::object();
    for (auto it = args.begin(); it != args.end(); ++it)
    {
        bool known = std::find(spec.required.begin(), spec.required.end(), it.key()) != spec.required.end();
        for (auto& o : spec.optional) known = known || o.first == it.key();
        if (!known) throw Invalid("arguments do not match the command contract");
        out[it.key()] = it.value();
    }
    for (auto& r : spec.required)
        if (!args.contains(r)) throw Invalid("arguments do not match the command contract");
    for (auto& o : spec.optional)
        if (!args.contains(o.first)) out[o.first] = o.second;
    return out;
}
} // namespace

json Service::execute(const Principal& principal, const json& request)
{
    if (principal.role == "observer") throw Forbidden("read-only observer cannot mutate world state");
    if (!request.is_object() || request.size() != 3 || !request.contains("command_id") || !request.contains("operation") || !request.contains("arguments"))
        throw Invalid("command requires command_id, operation and arguments");
    const json& args = request["arguments"];
    const json& operation_value = request["operation"];
    if (!args.is_object() || !operation_value.is_string()) throw Invalid("invalid command arguments");
    std::string operation = operation_value.get<std::string>();
    if (!request["command_id"].is_string()) throw Invalid("expected a 128-bit lowercase persistent ID");
    std::string command_id = request["command_id"].get<std::string>();
    const std::string& actor = principal.actor;
    static const std::map<std::string, Spec> administrative = {
        { "world_scale", { { "value" }, {} } },
        { "world_state", { { "name", "version", "state" }, {} } },
        { "timeline_schedule", { { "name", "timeline_id", "version", "times", "parameters" }, {} } },
    };
    static const std::map<std::string, Spec> functions = {
        { "location_claim", { { "location" }, { { "capacity", 128 }, { "ttl_ms", 15000 } } } },
        { "location_renew", { { "location", "fence" }, { { "ttl_ms", 15000 } } } },
        { "location_recover", { { "location", "fence" }, {} } },
        { "entity_create", { { "entity_id", "kind", "location", "fence", "state" },
                             { { "account", nullptr }, { "policy", nullptr }, { "owner", nullptr }, { "capacity", 64 } } } },
        { "entity_update", { { "entity_id", "fence", "version", "state" }, {} } },
        { "session_disconnect", { { "character_id", "fence", "version", "state" }, {} } },
        { "session_resume", { { "character_id", "location", "fence", "version" }, {} } },
        { "entity_death", { { "entity_id", "fence", "version", "cause" }, {} } },
        { "corpse_cleanup", { { "entity_id", "fence", "version" }, {} } },
        { "item_create", { { "item_id", "section", "location", "fence" },
                           { { "kind", "WORLD" }, { "holder", nullptr }, { "quantity", 1 }, { "state", nullptr } } } },
        { "item_move", { { "item_id", "location", "fence", "version", "source_kind", "source_holder", "target_kind", "target_holder", "requester" }, {} } },
        { "transfer_prepare", { { "entity_id", "source", "source_fence", "target", "entity_version" }, { { "ttl_ms", 60000 } } } },
        { "transfer_claim", { { "token", "target_fence" }, {} } },
        { "transfer_commit", { { "transfer_id", "target_fence" }, {} } },
        { "transfer_abort", { { "transfer_id", "source_fence" }, {} } },
        { "native_save_begin", { { "character_id", "fence", "session_fence", "entity_version", "base_revision", "slot", "byte_count", "sha256" }, {} } },
        { "native_save_append", { { "character_id", "fence", "session_fence", "upload_id", "offset", "data" }, {} } },
        { "native_save_finish", { { "character_id", "fence", "session_fence", "upload_id" }, {} } },
        { "native_save_cancel", { { "character_id", "fence", "session_fence", "upload_id" }, {} } },
        { "admin_relay", { { "account", "order", "values" }, {} } },
        { "account_list", { { "after" }, {} } },
        { "account_put", { { "accounts", "only_new" }, {} } },
        { "store_read", { { "location", "fence", "bucket", "key" }, {} } },
        { "store_keys", { { "location", "fence", "bucket" }, {} } },
        { "store_swap", { { "location", "fence", "bucket", "key", "expected", "value" }, {} } },
    };
    json bound;
    if (administrative.count(operation))
    {
        if (principal.role != "admin") throw Forbidden("administrative command");
        bound = bind_args(args, administrative.at(operation));
    }
    else if (functions.count(operation))
    {
        if (operation == "admin_relay" && principal.role != "location")
            throw Forbidden("administrator orders are relayed by a location authority");
        if (operation.rfind("account_", 0) == 0 && principal.role != "location")
            throw Forbidden("accounts are kept for the location authorities");
        if (operation.rfind("store_",0)==0 && principal.role!="location") throw Forbidden("shared storage requires a location authority");
        if (operation.rfind("native_save_", 0) == 0)
        {
            if (principal.role != "location") throw Forbidden("native checkpoints require a location authority");
            std::lock_guard<std::recursive_mutex> guard(store_->lock);
            json row = store_->db.one("SELECT location FROM entity WHERE id=?", { args.contains("character_id") ? args["character_id"] : json() });
            if (row.is_null()) throw Invalid("unknown character");
            allowed(principal, row["location"]);
        }
        if (args.contains("location")) allowed(principal, args["location"]);
        if (operation == "transfer_prepare") allowed(principal, args.contains("source") ? args["source"] : json());
        else if (operation == "transfer_claim") allowed(principal, transfers_->verify(args.contains("token") ? args["token"] : json())["target"]);
        else if (operation == "transfer_commit" || operation == "transfer_abort")
        {
            json status = transfers_->status(actor, args.contains("transfer_id") ? args["transfer_id"] : json());
            allowed(principal, operation == "transfer_commit" ? status["target"] : status["source"]);
        }
        else if (operation == "entity_update" || operation == "entity_death" || operation == "corpse_cleanup" || operation == "session_disconnect")
        {
            std::lock_guard<std::recursive_mutex> guard(store_->lock);
            json id = args.contains("entity_id") ? args["entity_id"] : (args.contains("character_id") ? args["character_id"] : json());
            json row = store_->db.one("SELECT location FROM entity WHERE id=?", { id });
            if (row.is_null()) throw Invalid("unknown entity");
            allowed(principal, row["location"]);
        }
        bound = bind_args(args, functions.at(operation));
    }
    else
        throw Invalid("unknown operation");

    if (operation == "world_scale") return world_->set_scale(actor, command_id, bound["value"]);
    if (operation == "world_state") return world_->set_state(actor, command_id, bound["name"], bound["version"], bound["state"]);
    if (operation == "timeline_schedule")
        return timelines_->schedule(actor, command_id, bound["name"], bound["timeline_id"], bound["version"], bound["times"], bound["parameters"]);
    if (operation == "location_claim") return world_->claim_location(actor, command_id, bound["location"], bound["capacity"], bound["ttl_ms"]);
    if (operation == "location_renew") return world_->renew_location(actor, command_id, bound["location"], bound["fence"], bound["ttl_ms"]);
    if (operation == "location_recover") return ownership_->recover_location(actor, command_id, bound);
    if (operation == "entity_create") return ownership_->create_entity(actor, command_id, bound);
    if (operation == "entity_update") return ownership_->update_entity(actor, command_id, bound);
    if (operation == "session_disconnect") return ownership_->disconnect(actor, command_id, bound);
    if (operation == "session_resume") return ownership_->resume(actor, command_id, bound);
    if (operation == "entity_death") return ownership_->kill(actor, command_id, bound);
    if (operation == "corpse_cleanup") return ownership_->cleanup_corpse(actor, command_id, bound);
    if (operation == "item_create") return ownership_->create_item(actor, command_id, bound);
    if (operation == "item_move") return ownership_->move_item(actor, command_id, bound);
    if (operation == "transfer_prepare") return transfers_->prepare(actor, command_id, bound);
    if (operation == "transfer_claim") return transfers_->claim(actor, command_id, bound);
    if (operation == "transfer_commit") return transfers_->commit(actor, command_id, bound);
    if (operation == "transfer_abort") return transfers_->abort(actor, command_id, bound);
    if (operation == "native_save_begin") return saves_->begin(actor, command_id, bound);
    if (operation == "native_save_append") return saves_->append(actor, command_id, bound);
    if (operation == "native_save_finish") return saves_->finish(actor, command_id, bound);
    if (operation == "admin_relay") return admin_relay(actor, command_id, bound);
    if (operation == "account_list") return account_list(bound);
    if (operation == "account_put") return account_put(bound);
    if (operation.rfind("store_",0)==0) return record_exchange(actor,command_id,operation,bound);
    return saves_->cancel(actor, command_id, bound);
}

#include "lzm_records.inc"

// http.py admin_relay: an in-game administrator's world order, relayed by the
// location that verified his account (owner 2026-10-23: time and weather set
// from the admin menu or the weather editor reached one map only). It goes to
// the operations the master console uses, so every location follows it.
// Accounts (owner 2026-10-25, doc 154: "the database belongs to the master
// only"): login, role, salt and PBKDF2 hash, money, device digest, approval and
// Firebase UID, the fields of the old netcoop_accounts.txt. A location mirrors
// them (account_list after its last revision) and sends what it changed
// (account_put; only_new: the one-time import of an old file).
static std::string account_field(const json& account, const char* name, size_t limit, bool empty_ok)
{
    if (!account.contains(name) || !account[name].is_string()) throw Invalid("invalid account field");
    std::string text = account[name].get<std::string>();
    if ((!empty_ok && text.empty()) || text.size() > limit) throw Invalid("invalid account field");
    for (unsigned char c : text)
        if (c < 33 || c >= 127 || c == '|') throw Invalid("invalid account field");
    return text;
}

json Service::account_list(const json& args)
{
    const json& after = args["after"];
    if (!after.is_number_integer() || after.get<int64_t>() < 0) throw Invalid("invalid account revision");
    std::lock_guard<std::recursive_mutex> guard(store_->lock);
    const int64_t limit = 1000;
    json accounts = json::array();
    for (auto& row : store_->db.all("SELECT login,role,salt,hash,money,device,approval,firebase_uid,revision FROM account"
                                    " WHERE revision>? ORDER BY revision LIMIT ?", { after, json(limit) }))
        accounts.push_back(row);
    // A full page: the next request continues after its last row.
    json revision = int64_t(accounts.size()) == limit ? accounts.back()["revision"]
                                                      : store_->db.scalar("SELECT COALESCE(MAX(revision),0) FROM account");
    return { { "revision", revision }, { "accounts", accounts } };
}

json Service::account_put(const json& args)
{
    const json& list = args["accounts"];
    if (!list.is_array() || list.empty() || list.size() > 200 || !args["only_new"].is_boolean()) throw Invalid("invalid account batch");
    const bool only_new = args["only_new"].get<bool>();
    std::vector<Db::Params> rows;
    std::vector<int64_t> masks;
    for (const json& account : list)
    {
        if (!account.is_object() || (account.size() != 8 && account.size() != 9) || !account.contains("money")) throw Invalid("invalid account record");
        const auto fields=account.value("fields",json(15));
        if(!fields.is_number_integer() || fields.get<int64_t>()<1 || fields.get<int64_t>()>15) throw Invalid("invalid account fields");
        masks.push_back(fields.get<int64_t>());
        std::string login = account_field(account, "login", 20, false);
        if (login.size() < 3 || !std::all_of(login.begin(), login.end(), [](char c) { return isalnum((unsigned char)c) || c == '_' || c == '-' || c == '.'; }))
            throw Invalid("invalid account login");
        std::string role = account_field(account, "role", 16, false), approval = account_field(account, "approval", 16, false);
        if ((role != "admin" && role != "player") || (approval != "pending" && approval != "approved" && approval != "rejected"))
            throw Invalid("invalid account state");
        const json& money = account["money"];
        if (!money.is_null() && (!money.is_number_integer() || money.get<int64_t>() < 0 || money.get<int64_t>() > 4294967295LL))
            throw Invalid("invalid account money");
        rows.push_back({ lower(login), login, role, account_field(account, "salt", 256, false), account_field(account, "hash", 256, false),
                         money, account_field(account, "device", 128, true), approval, account_field(account, "firebase_uid", 128, true) });
    }
    return store_->transaction([&](Db& tx) -> json {
        const int64_t revision = tx.scalar("SELECT COALESCE(MAX(revision),0) FROM account").get<int64_t>() + 1;
        int64_t changed = 0;
        size_t index=0;
        for (auto& row : rows)
        {
            row.push_back(revision);
            if(!only_new) row.push_back(masks[index]);
            ++index;
            changed += tx.exec(only_new ? "INSERT OR IGNORE INTO account VALUES(?,?,?,?,?,?,?,?,?,?)"
                                        : "INSERT INTO account VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10) ON CONFLICT(key) DO UPDATE SET"
                                          " role=CASE WHEN (?11 & 4)!=0 THEN excluded.role ELSE account.role END,"
                                          " salt=CASE WHEN (?11 & 1)!=0 THEN excluded.salt ELSE account.salt END,"
                                          " hash=CASE WHEN (?11 & 1)!=0 THEN excluded.hash ELSE account.hash END,"
                                          " money=CASE WHEN (?11 & 2)!=0 THEN excluded.money ELSE account.money END,"
                                          " device=CASE WHEN (?11 & 1)!=0 THEN excluded.device ELSE account.device END,"
                                          " approval=CASE WHEN (?11 & 8)!=0 THEN excluded.approval ELSE account.approval END,"
                                          " firebase_uid=CASE WHEN (?11 & 1)!=0 THEN excluded.firebase_uid ELSE account.firebase_uid END,revision=excluded.revision",
                               row);
        }
        return json{ { "revision", revision }, { "changed", changed } };
    });
}

json Service::admin_relay(const std::string& actor, const std::string& command_id, const json& args)
{
    const json& account = args["account"];
    const json& order_value = args["order"];
    const json& values = args["values"];
    if (!account.is_string() || account.get<std::string>().empty() || account.get<std::string>().size() > 64)
        throw Invalid("invalid administrator account");
    for (unsigned char c : account.get<std::string>())
        if (c < 32 || c == 127) throw Invalid("invalid administrator account");
    static const std::vector<std::string> orders = { "weather", "emission", "psi_storm", "scale", "advance" };
    if (!order_value.is_string() || std::find(orders.begin(), orders.end(), order_value.get<std::string>()) == orders.end() || !values.is_object())
        throw Invalid("unknown administrator order");
    persistent_id(command_id);
    const std::string order = order_value.get<std::string>();
    auto keys_are = [&](std::initializer_list<const char*> keys) {
        if (values.size() != keys.size()) return false;
        for (const char* key : keys)
            if (!values.contains(key)) return false;
        return true;
    };
    json result;
    if (order == "scale")
    {
        if (!keys_are({ "value" })) throw Invalid("scale order requires value");
        result = world_->set_scale(actor, command_id, values["value"]);
    }
    else if (order == "advance")
    {
        if (!keys_are({ "game_s" })) throw Invalid("advance order requires game_s");
        const json& game_s = values["game_s"];
        finite(game_s, .001, 30 * 86400);
        // Python: game_s * 1000 keeps an int an int (the journal hashes compare)
        const json game_ms = game_s.is_number_integer() ? json(game_s.get<int64_t>() * 1000) : json(game_s.get<double>() * 1000);
        result = world_->advance(actor, command_id, game_ms);
    }
    else
    {
        json durations, parameters;
        if (order == "weather")
        {
            if (!keys_are({ "source", "target", "transition_s" })) throw Invalid("weather order requires source, target and transition_s");
            durations = json::array({ values["transition_s"] });
            parameters = { { "source", values["source"] }, { "target", values["target"] } };
        }
        else
        {
            if (!keys_are({ "durations", "intensity" })) throw Invalid("event order requires durations and intensity");
            durations = values["durations"];
            parameters = { { "intensity", values["intensity"] } };
        }
        auto [times, planned] = Timelines::plan(*world_, order, command_id, durations, parameters);
        result = timelines_->schedule(actor, command_id, order, command_id, nullptr, times, planned);
    }
    std::printf("[master] administrator %s via %s: %s %s\n", account.get<std::string>().c_str(), actor.c_str(), order.c_str(),
                canonical(values).c_str());
    std::fflush(stdout);
    return result;
}

static bool all_digits(const std::string& v, size_t max_len, bool allow_zero)
{
    if (v.empty() || v.size() > max_len) return false;
    if (v[0] == '0') return allow_zero && v.size() == 1;
    return std::all_of(v.begin(), v.end(), [](char c) { return c >= '0' && c <= '9'; });
}

static HttpResponse reply(int status, const json& body) { return { status, canonical(body, 16 * 1024 * 1024) }; }

static const std::string& first(const std::map<std::string, std::vector<std::string>>& query, const std::string& name, const std::string& fallback)
{
    auto it = query.find(name);
    return it == query.end() ? fallback : it->second[0];
}

HttpResponse Service::handle(HttpRequest& request, const std::function<bool(size_t)>& read_body)
{
    if (request.method != "GET" && request.method != "POST") return { 501, "", "text/html;charset=utf-8" };
    try
    {
        auto authenticated = credentials_->authenticate(request.header("authorization"));
        if (!authenticated) return reply(401, { { "error", "server authentication required" } });
        Principal principal = *authenticated;
        if (!allow(principal.actor)) return reply(429, { { "error", "server request limit reached" } });
        auto instances = request.all("x-lostzone-instance");
        if (instances.size() > 1) throw Invalid("one runtime instance header is required");
        if (!instances.empty())
        {
            if (principal.role != "location") throw Forbidden("only location authorities may bind a runtime instance");
            persistent_id(instances[0]);
            principal.actor = "runtime:" + sha256_hex(principal.actor) + ":" + instances[0];
        }
        auto bindings = request.all("x-lostzone-world");
        if (!bindings.empty())
        {
            if (bindings.size() != 1 || instances.empty()) throw Invalid("one bound runtime world header is required");
            auto parts = split(bindings[0], ':');
            if (parts.size() != 3 || !all_digits(parts[0], 20, false) || !all_digits(parts[1], 20, true) || !all_digits(parts[2], 19, false))
                throw Invalid("invalid bound world identity");
            auto number = [](const std::string& text, uint64_t& out) {
                auto r = std::from_chars(text.data(), text.data() + text.size(), out);
                return r.ec == std::errc();
            };
            uint64_t world_id = 0, seed = 0, epoch = 0;
            bool parsed = number(parts[0], world_id) && number(parts[1], seed) && number(parts[2], epoch);
            if (!parsed || world_id != world_->world_id || seed != world_->seed || int64_t(epoch) != *store_->epoch)
                throw Conflict("runtime world identity or master epoch changed");
        }
        if (request.method == "GET" && request.path == "/v1/status")
        {
            if (principal.role != "admin") throw Forbidden("recovery status is restricted to administrators");
            return reply(200, { { "result", recovery_status() } });
        }
        if (!ready()) return reply(503, { { "error", "world authority is recovering" } });
        json result;
        if (request.method == "GET")
        {
            const std::string& path = request.path;
            if (path == "/v1/clock") result = world_->sample();
            else if (path == "/v1/bootstrap") result = world_->bootstrap_snapshot(false);
            else if (path == "/v1/engine-bootstrap") result = world_->bootstrap_snapshot(true);
            else if (path == "/v1/events" && principal.role == "admin")
            {
                auto query = parse_qs(request.query, false);
                json events = json::array();
                for (auto& e : store_->events(parse_int(first(query, "after", "0")), parse_int(first(query, "limit", "256")))) events.push_back(e);
                result = { { "events", events } };
            }
            else if (path == "/v1/transfer")
            {
                auto query = parse_qs(request.query, false);
                result = transfers_->status(principal.actor, first(query, "id", ""));
            }
            else if (path == "/v1/location")
            {
                auto query = parse_qs(request.query, false);
                std::string location = first(query, "id", "");
                int64_t fence = parse_int(first(query, "fence", "0"));
                allowed(principal, location);
                result = ownership_->location_state(principal.actor, location, fence);
            }
            else if (path == "/v1/player-admission")
            {
                if (principal.role != "location") throw Forbidden("native slot inspection requires a location authority");
                if (instances.empty() || bindings.empty()) throw Invalid("native slot inspection requires a bound runtime world");
                if (request.query.size() > 1024) throw Invalid("native slot query exceeds bounds");
                auto query = parse_qs(request.query, true, 5);
                std::vector<std::string> names;
                for (auto& q : query) names.push_back(q.first);
                std::vector<std::string> expected = { "account", "epoch", "fence", "location", "slot" };
                bool shape = names == expected;
                for (auto& q : query) shape = shape && q.second.size() == 1;
                if (!shape) throw Invalid("invalid native slot query");
                for (const char* n : { "slot", "fence", "epoch" })
                    if (!all_digits(query[n][0], 19, false)) throw Invalid("invalid native slot numeric field");
                std::string location = query["location"][0];
                allowed(principal, location);
                result = saves_->inspect(principal.actor, query["account"][0], parse_int(query["slot"][0]), location,
                                         parse_int(query["fence"][0]), parse_int(query["epoch"][0]));
            }
            else if (path == "/v1/player-save")
            {
                if (principal.role != "location") throw Forbidden("native checkpoints require a location authority");
                auto query = parse_qs(request.query, true);
                std::vector<std::string> required = { "character_id", "fence", "session_fence", "revision" };
                bool shape = true;
                for (auto& r : required) shape = shape && query.count(r);
                for (auto& q : query)
                {
                    bool known = std::find(required.begin(), required.end(), q.first) != required.end() || q.first == "offset" || q.first == "transfer_id";
                    shape = shape && known && q.second.size() == 1;
                }
                if (!shape) throw Invalid("invalid native checkpoint query");
                std::string character_id = query["character_id"][0];
                std::optional<std::string> transfer_id;
                if (query.count("transfer_id")) transfer_id = query["transfer_id"][0];
                {
                    std::lock_guard<std::recursive_mutex> guard(store_->lock);
                    json row = transfer_id && !transfer_id->empty() ? store_->db.one("SELECT target AS owner FROM transfer WHERE id=?", { *transfer_id })
                                           : store_->db.one("SELECT location AS owner FROM entity WHERE id=?", { character_id });
                    if (row.is_null()) throw Invalid("unknown native checkpoint owner");
                    allowed(principal, row["owner"]);
                }
                result = saves_->read(principal.actor, character_id, parse_int(query["fence"][0]), parse_int(query["session_fence"][0]),
                                      parse_int(query["revision"][0]), parse_int(first(query, "offset", "0")), transfer_id);
            }
            else
                return reply(404, { { "error", "unknown or unavailable endpoint" } });
        }
        else
        {
            if (request.header("transfer-encoding") || request.all("content-length").size() != 1) throw Invalid("one Content-Length header is required");
            int64_t length = parse_int(*request.header("content-length"));
            if (length < 1 || length > (request.path=="/v1/store" ? 256*1024:65536)) return reply(413, { { "error", "request body exceeds limit" } });
            if (request.content_type() != "application/json") throw Invalid("JSON Content-Type is required");
            if (!read_body(size_t(length))) throw Invalid("incomplete request body");
            const std::string& path = request.path;
            if (path == "/v1/command") result = execute(principal, strict_json(request.body));
            else if(path=="/v1/store")
            {
                if(principal.role!="location" || instances.size()!=1 || bindings.size()!=1) throw Forbidden("shared store needs a bound location authority");
                const auto command=strict_json(request.body);
                const auto operation=command.value("operation",std::string());
                if(operation!="store_read" && operation!="store_keys" && operation!="store_swap") throw Invalid("not a shared storage operation");
                result=execute(principal,command);
            }
            else if (path == "/v1/console" && principal.role == "admin")
            {
                json args = strict_json(request.body);
                if (!args.is_object() || args.size() != 1 || !args.contains("line") || !args["line"].is_string())
                    throw Invalid("console request takes one line");
                std::string line = trim(args["line"].get<std::string>());
                std::istringstream words(line);
                std::string word;
                words >> word;
                word = lower(word);
                if (!line.empty() && (word == "quit" || word == "exit")) throw Invalid("the master stops from its window");
                result = { { "text", console(line) } };
            }
            else if (path == "/v1/snapshot" && principal.role == "admin")
            {
                if (strict_json(request.body) != json::object()) throw Invalid("snapshot endpoint takes an empty object");
                world_->sample();
                result = store_->snapshot();
            }
            else
                return reply(404, { { "error", "unknown or unavailable endpoint" } });
        }
        return reply(200, { { "result", result } });
    }
    catch (const Forbidden&) { return reply(403, { { "error", "server is not permitted to perform this operation" } }); }
    catch (const Conflict& error) { return reply(409, { { "error", error.what() } }); }
    catch (const Invalid&) { return reply(400, { { "error", "invalid request contract" } }); }
    catch (const json::type_error&) { return reply(400, { { "error", "invalid request contract" } }); }
    catch (const std::invalid_argument&) { return reply(400, { { "error", "invalid request contract" } }); }
    catch (const Unavailable&) { return reply(503, { { "error", "world authority is unavailable" } }); }
    catch (const std::exception&) { return reply(503, { { "error", "world transaction could not be completed" } }); }
}

// gateway.ACCOUNT
static bool valid_account(const std::string& account)
{
    if (account.size() < 3 || account.size() > 20) return false;
    return std::all_of(account.begin(), account.end(), [](char c) {
        return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '-';
    });
}

// gateway.home: the map a character lives on, nothing for a new one.
std::optional<std::string> Service::home(const std::string& account, int64_t slot)
{
    std::string id = native_identity(world_->world_id, world_->seed, account, slot);
    std::lock_guard<std::recursive_mutex> guard(store_->lock);
    json row = store_->db.one("SELECT location FROM entity WHERE id=? AND kind='CHARACTER'", { id });
    if (row.is_null()) return std::nullopt;
    return row["location"].get<std::string>();
}

HttpResponse Service::handle_entry(HttpRequest& request)
{
    auto respond = [](int status, const json& body) { return HttpResponse{ status, python_dumps(body), "application/json" }; };
    if (request.method != "GET") return respond(405, { { "error", "read-only" } });
    {
        std::lock_guard<std::mutex> guard(entry_lock_);
        int64_t now = monotonic_ns();
        auto& hits = entry_hits_[request.address];
        hits.erase(std::remove_if(hits.begin(), hits.end(), [&](int64_t t) { return now - t >= 10000000000LL; }), hits.end());
        if (hits.size() >= 20) return respond(429, { { "error", "too many requests" } });
        hits.push_back(now);
        if (entry_hits_.size() > 4096)
            for (auto it = entry_hits_.begin(); it != entry_hits_.end();)
                it = (it->second.empty() || now - it->second.back() >= 10000000000LL) ? entry_hits_.erase(it) : std::next(it);
    }
    if (request.path != "/v1/entry") return respond(404, { { "error", "unknown endpoint" } });
    try
    {
        // The client names its account and slot (owner 2026-10-24: "the master
        // connects you, from its database, to the map you were on last, or to
        // Cordon when you are new"): the character's map when it runs, Cordon
        // for a new character, otherwise the first running map.
        auto query = parse_qs(request.query, false, 4);
        std::optional<std::string> account;
        int64_t slot = 1;
        if (query.count("account") && !query["account"].empty()) account = query["account"][0];
        if (query.count("slot") && !query["slot"].empty())
        {
            const std::string& text = query["slot"][0];
            bool digits = !text.empty() && text.size() <= 2 && std::all_of(text.begin(), text.end(), [](char c) { return c >= '0' && c <= '9'; });
            slot = digits ? std::stoll(text) : -1;
        }
        auto plan = read_cluster(cluster_);
        std::lock_guard<std::recursive_mutex> guard(store_->lock);
        int64_t now = world_->real_ms();
        std::vector<std::string> alive;
        for (auto& row : store_->db.all("SELECT location FROM location_lease WHERE expires_ms>?", { now })) alive.push_back(row["location"].get<std::string>());
        auto running = [&](const std::string& name) {
            if(std::find(alive.begin(),alive.end(),name)==alive.end()) return false;
            if(runtime_root_.empty()) return true;
            try {
                auto location=std::find_if(plan.begin(),plan.end(),[&](const PlanLocation& p){return p.name==name;});
                if(location==plan.end()) return false;
                const auto folder=cluster_.substr(0,cluster_.find_last_of(L"\\/")+1)+L"netcoop_cluster\\";
                const auto state=loads(read_file(folder+L"admission_"+std::to_wstring(location->port)+L".json"));
                HANDLE process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,state.value("pid",DWORD(0)));
                if(!process) return false;
                DWORD code=0,characters=4096;wchar_t executable[4096]{};
                const bool live=GetExitCodeProcess(process,&code) && code==STILL_ACTIVE && QueryFullProcessImageNameW(process,0,executable,&characters);
                CloseHandle(process);
                if(!live || _wcsicmp(executable,(runtime_root_+L"\\dedicated\\LostZoneServerDX11.exe").c_str())!=0) return false;
                return state.value("ready",false) && state.value("updated",int64_t(0))>=int64_t(time(nullptr))-30 &&
                    state.value("epoch",int64_t(0))==store_->epoch.value_or(0);
            }catch(...) {return false;}
        };
        // The client keeps the address it reached the master with (Radmin VPN players).
        auto answer = [&](const PlanLocation& location) {
            return respond(200, { { "schema", 1 }, { "location", location.name }, { "host", "" }, { "port", location.port } });
        };
        if(!ready()) return respond(503,{{"schema",1},{"state","recovering"},{"location",""},{"retry_seconds",3}});
        if(!runtime_root_.empty() && GetFileAttributesW((runtime_root_+L"\\appdata\\server\\netcoop_cluster\\host_master_paused.txt").c_str())!=INVALID_FILE_ATTRIBUTES)
            return respond(503,{{"schema",1},{"state","disabled"},{"location",""},{"retry_seconds",0}});
        if (account && valid_account(*account) && slot >= 0 && slot <= 10)
        {
            // Listing slots needs any healthy location, not the old character's
            // map. Entering a character must keep that exact map.
            if(slot==0) {
                for(const auto& location:plan) if(location.name=="l01_escape" && running(location.name)) return answer(location);
                for(const auto& location:plan) if(running(location.name)) return answer(location);
            }
            const std::string wanted=slot==0 ? "l01_escape":home(*account,slot).value_or("l01_escape");
            const auto target=std::find_if(plan.begin(),plan.end(),[&](const PlanLocation& location){return location.name==wanted;});
            if(target==plan.end()) return respond(503,{{"schema",1},{"state","unplanned"},{"location",wanted},{"retry_seconds",0}});
            if(running(wanted)) return answer(*target);
            const auto folder=cluster_.substr(0,cluster_.find_last_of(L"\\/")+1)+L"netcoop_cluster";
            const auto mode=folder+L"\\host_mode_"+widen(wanted)+L".txt";
            std::ifstream in(mode);std::string selected;in>>selected;
            in.close();
            if(selected=="off") return respond(503,{{"schema",1},{"state","disabled"},{"location",wanted},{"retry_seconds",0}});
            std::string state="starting";int retry=3;
            try {
                const auto view=loads(read_file(folder+L"\\host_view_native.json"));
                if(view.value("updated",int64_t(0))>=int64_t(time(nullptr))-30)
                    for(const auto& map:view["maps"]) if(map.value("map",std::string())==wanted) {
                        state=map.value("state",std::string("starting"));
                        if(state=="failed") retry=0;
                    }
            }catch(...) {}
            if(state!="failed") {
                const auto wake=folder+L"\\wake_"+widen(wanted)+L".txt",temporary=wake+L".entry."+std::to_wstring(GetCurrentThreadId())+L".tmp";
                {std::ofstream out(temporary,std::ios::binary|std::ios::trunc);out<<"gateway\n";}
                if(!MoveFileExW(temporary.c_str(),wake.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) state="control_error";
            }
            log_line(format("[diag][entry] target=%s udp=%d state=%s retry_seconds=%d",wanted.c_str(),target->port,state.c_str(),retry));
            return respond(503,{{"schema",1},{"state",state},{"location",wanted},{"retry_seconds",retry}});
        }
        for (auto& location : plan)
            if (running(location.name)) return answer(location);
    }
    catch (...) {}
    return respond(503, { { "error", "no location is running" } });
}
} // namespace lzm
