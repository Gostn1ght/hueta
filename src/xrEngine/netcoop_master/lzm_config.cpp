// __main__.py: the master's private configuration and the key files it hands
// to the maps (bridge for every map, one writer per map).
#include "lzm_config.h"
#include "lzm_service.h"
#include "lzm_cluster_plan.h"

#include <windows.h>

#include <fstream>
#include <set>
#include <sstream>
#include <filesystem>

namespace lzm
{
static std::string read_file(const std::wstring& path)
{
    std::ifstream in(path, std::ios::binary);
    if (!in) throw Invalid("configuration cannot be read");
    std::ostringstream text;
    text << in.rdbuf();
    return text.str();
}

static bool exists(const std::wstring& path) { return GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES; }

static void make_parent(const std::wstring& path)
{
    std::wstring folder = path.substr(0, path.find_last_of(L"\\/"));
    if (folder.empty() || exists(folder)) return;
    make_parent(folder);
    CreateDirectoryW(folder.c_str(), nullptr);
}

// O_CREAT|O_EXCL + fsync, or a temporary file moved over the old one.
static void write_new(const std::wstring& path, const std::string& data, bool replace)
{
    make_parent(path);
    std::wstring temporary = path + L"." + widen(token_hex(16)) + L".tmp";
    HANDLE file = CreateFileW(replace ? temporary.c_str() : path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
    {
        if (GetLastError() == ERROR_FILE_EXISTS) throw Invalid("configuration already exists; credentials were not replaced");
        throw Unavailable("configuration file cannot be created");
    }
    DWORD written = 0;
    bool ok = WriteFile(file, data.data(), DWORD(data.size()), &written, nullptr) && written == data.size() && FlushFileBuffers(file);
    CloseHandle(file);
    if (!ok)
    {
        DeleteFileW(replace ? temporary.c_str() : path.c_str());
        throw Unavailable("configuration file cannot be written");
    }
    if (replace && !MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
    {
        DeleteFileW(temporary.c_str());
        throw Unavailable("configuration file cannot be replaced");
    }
}

static json load_config(const std::wstring& path)
{
    json config = loads(read_file(path));
    if (!config.is_object() || !config.contains("schema") || config["schema"] != 1) throw Invalid("unsupported service configuration");
    return config;
}

static std::pair<uint64_t, uint64_t> world_identity(const json& world_id, const json& seed)
{
    if (!world_id.is_number_integer() || (!world_id.is_number_unsigned() && world_id.get<int64_t>() <= 0)) throw Invalid("invalid WorldID");
    if (!seed.is_number_integer() || (!seed.is_number_unsigned() && seed.get<int64_t>() < 0)) throw Invalid("invalid world seed");
    return { world_id.get<uint64_t>(), seed.get<uint64_t>() };
}

static bool engine_location_ok(const std::string& name)
{
    if (name.empty() || name.size() > 64) return false;
    for (unsigned char c : name)
        if (!(isalnum(c) || c == '_') || c >= 0x80) return false;
    return true;
}

void create_config(const std::wstring& path, std::vector<std::string> locations, std::optional<uint64_t> world_id,
                   std::optional<uint64_t> seed, std::optional<double> initial_ms, std::optional<double> scale)
{
    if (exists(path)) throw Invalid("configuration already exists; credentials were not replaced");
    if (world_id.has_value() != seed.has_value()) throw Invalid("explicit world identity requires both WorldID and seed");
    if (locations.empty()) locations.push_back("hidden_base");
    std::set<std::string> sorted(locations.begin(), locations.end());
    json credentials = { { "admin", { { "role", "admin" }, { "token", token_urlsafe(48) } } } };
    for (auto& location : sorted)
    {
        identifier(location);
        credentials["location:" + location] = { { "role", "location" }, { "locations", { location } }, { "token", token_urlsafe(48) } };
    }
    credentials["observer:engine"] = { { "role", "observer" }, { "locations", json::array() }, { "token", token_urlsafe(48) } };
    json config = { { "schema", 1 }, { "database", "world.sqlite" }, { "port", 38477 }, { "signing_key", token_hex(32) }, { "credentials", credentials } };
    if (world_id)
    {
        if (*world_id == 0) throw Invalid("invalid WorldID");
        config["world_id"] = *world_id;
        config["seed"] = *seed;
    }
    if (initial_ms) config["initial_ms"] = finite(*initial_ms);
    if (scale) config["scale"] = finite(*scale, 0.001, 1000);
    write_new(path, python_dumps(config, false, 2), false);
}

bool add_location_credential(const std::wstring& path, const std::string& location)
{
    if (!engine_location_ok(location)) throw Invalid("invalid engine location name");
    json config = load_config(path);
    json& credentials = config["credentials"];
    Credentials check(credentials);
    std::string actor = "location:" + location;
    if (credentials.contains(actor)) return false;
    for (auto& entry : credentials)
        if (entry.contains("locations"))
            for (auto& l : entry["locations"])
                if (l == location) throw Invalid("another credential already covers this location");
    credentials[actor] = { { "role", "location" }, { "locations", { location } }, { "token", token_urlsafe(48) } };
    Credentials recheck(credentials);
    write_new(path, python_dumps(config, false, 2), true);
    return true;
}

void create_writer_config(const std::wstring& config_path, const std::wstring& destination, const std::string& location, bool replace)
{
    if (!engine_location_ok(location)) throw Invalid("invalid engine location name");
    std::wstring name = destination.substr(destination.find_last_of(L"\\/") + 1);
    if (name != widen("netcoop_world_writer_" + location + ".json")) throw Invalid("writer config filename must match its location");
    json config = load_config(config_path);
    Credentials check(config["credentials"]);
    std::string actor = "location:" + location;
    json credential = config["credentials"].contains(actor) ? config["credentials"][actor] : json();
    if (!credential.is_object() || credential.value("role", "") != "location" || credential.value("locations", json()) != json::array({ location }))
        throw Invalid("one dedicated location credential is required");
    auto [world_id, seed] = world_identity(config.contains("world_id") ? config["world_id"] : json(), config.contains("seed") ? config["seed"] : json());
    int64_t port = config.contains("port") ? as_int(config["port"]) : 38477;
    if (port < 1 || port > 65535) throw Invalid("writer requires a fixed loopback port");
    json body = { { "schema", 1 }, { "mode", "writer" }, { "host", "127.0.0.1" }, { "port", port }, { "token", credential["token"] },
                  { "actor", actor }, { "location", location }, { "master_world_id", world_id }, { "master_world_seed", seed } };
    std::string encoded = canonical(body);
    if (exists(destination) && read_file(destination) == encoded) return;
    if (exists(destination) && !replace) throw Invalid("writer config exists; explicit replacement required");
    write_new(destination, encoded, true);
}

void create_bridge_config(const std::wstring& config_path, const std::wstring& destination, bool authority, bool replace)
{
    json config = load_config(config_path);
    Credentials check(config["credentials"]);
    json entry = config["credentials"].contains("observer:engine") ? config["credentials"]["observer:engine"] : json();
    if (!entry.is_object() || entry.value("role", "") != "observer") throw Invalid("a dedicated read-only engine observer is required");
    int64_t port = config.contains("port") ? as_int(config["port"]) : 38477;
    if (port < 1 || port > 65535) throw Invalid("shadow bridge requires a fixed loopback port");
    std::wstring name = destination.substr(destination.find_last_of(L"\\/") + 1);
    if (name != L"netcoop_world_bridge.json") throw Invalid("engine bridge file must be netcoop_world_bridge.json");
    json body = { { "schema", 1 }, { "mode", "shadow" }, { "host", "127.0.0.1" }, { "port", port }, { "token", entry["token"] } };
    if (authority)
    {
        auto [world_id, seed] = world_identity(config.contains("world_id") ? config["world_id"] : json(), config.contains("seed") ? config["seed"] : json());
        body = { { "schema", 3 }, { "mode", "authority" }, { "host", "127.0.0.1" }, { "port", port }, { "token", entry["token"] },
                 { "master_world_id", world_id }, { "master_world_seed", seed } };
    }
    const auto encoded=python_dumps(body);
    if (exists(destination) && read_file(destination)==encoded) return;
    write_new(destination, encoded, replace);
}

void prepare_engine_cluster(const std::wstring& root, const std::wstring& config_path, const std::wstring& plan_path)
{
    const std::string old_plan=exists(plan_path) ? read_file(plan_path):"";
    const std::string complete=complete_cluster_plan(old_plan);
    if (complete!=old_plan)
    {
        if (exists(plan_path))
        {
            const auto backup=plan_path+L".before-native-completion.bak";
            if (!exists(backup) && !CopyFileW(plan_path.c_str(),backup.c_str(),TRUE)) throw Unavailable("cannot back up the location plan");
        }
        write_new(plan_path,complete,true);
        log_line("[diag][cluster] plan completed: all 33 maps have UDP ports and launch sections; previous addresses preserved");
    }
    const auto locations=read_cluster(plan_path);
    if (!exists(config_path))
    {
        const auto legacy=root+L"\\hoster\\master\\runtime\\config.json";
        if (exists(legacy) && legacy!=config_path)
        {
            auto config=load_config(legacy);
            const auto database=config.value("database",std::string());
            if (database.empty() || database.find("..")!=std::string::npos || database.find_first_of(":/\\")!=std::string::npos)
                throw Invalid("legacy database must be a filename inside the master folder");
            const auto old_db=legacy.substr(0,legacy.find_last_of(L"\\/")+1)+widen(database);
            const auto new_db=config_path.substr(0,config_path.find_last_of(L"\\/")+1)+L"world.sqlite";
            make_parent(new_db);
            if (exists(new_db)) throw Invalid("master migration destination already has a database; check the saved migration state");
            if (exists(old_db))
            {
                const auto temporary=new_db+L"."+widen(token_hex(8))+L".tmp";
                try
                {
                    Db source;source.open(old_db,true);
                    source.exec("VACUUM INTO ?",{narrow(temporary)});
                    source.close();
                    Db verify;verify.open(temporary,true);
                    if (verify.scalar("PRAGMA integrity_check")!="ok") throw Invalid("migrated master database failed integrity check");
                    verify.close();
                    if (!MoveFileExW(temporary.c_str(),new_db.c_str(),MOVEFILE_WRITE_THROUGH)) throw Unavailable("cannot install migrated master database");
                }
                catch (...) {DeleteFileW(temporary.c_str());throw;}
            }
            config["database"]="world.sqlite";
            write_new(config_path,python_dumps(config,false,2),false);
            log_line("[diag][migration] legacy master copied to appdata/master; SQLite snapshot verified; original retained");
        }
        else
        {
            std::vector<std::string> maps;for (const auto& map:locations) maps.push_back(map.name);
            const uint64_t id=std::stoull(token_hex(8),nullptr,16)&0x3fffffffffffffffULL;
            const uint64_t seed=std::stoull(token_hex(8),nullptr,16)&0x3fffffffffffffffULL;
            double calendar=63676137600000.0;
            std::error_code error;
            for (const auto& f:std::filesystem::directory_iterator(root+L"\\appdata\\server\\netcoop_cluster",error))
            {
                const auto name=f.path().filename().string();
                if (name.rfind("clock_",0)!=0 || f.path().extension()!=L".txt") continue;
                std::ifstream in(f.path());double stamp=0,game=0;
                if (in>>stamp>>game && std::isfinite(game) && game>calendar && game<3e17) calendar=game;
            }
            create_config(config_path,maps,id ? id:1,seed,calendar,10.0);
            log_line("[diag][master] new private configuration created in appdata/master");
        }
    }
    for (const auto& map:locations) add_location_credential(config_path,map.name);
    // Refresh every file from the same final credential set. A stale local key
    // must not survive merely because its filesystem timestamp is recent.
    for (const auto& map:locations)
        create_writer_config(config_path,root+L"\\appdata\\server\\netcoop_world_writer_"+widen(map.name)+L".json",map.name,true);
    create_bridge_config(config_path,root+L"\\appdata\\server\\netcoop_world_bridge.json",true,true);
    const auto config=load_config(config_path);
    log_line(format("[diag][master] bootstrap complete maps=%zu api=127.0.0.1:%lld entry_tcp=%d",locations.size(),
        (long long)as_int(config["port"]),read_entry_port(plan_path)));
}
} // namespace lzm
