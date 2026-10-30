// The master's command line inside the engine executable:
//   LostZoneServerDX11.exe -netcoop_master                    the master window (defaults of a server folder)
//   LostZoneServerDX11.exe -netcoop_master window --config <runtime\config.json> --cluster <plan> [--gateway-port N]
//   LostZoneServerDX11.exe -netcoop_master serve  --config ...      without a window (journal on stdout)
//   ... init | writer-config | bridge-config                        the configuration files (__main__.py)
#include "lzm_config.h"
#include "lzm_window.h"
#include "lzm_host.h"

#include <windows.h>
#include <shellapi.h>

#include <algorithm>
#include <fstream>
#include <iterator>
#include <regex>

namespace lzm
{
namespace
{
std::wstring full_path(const std::wstring& path)
{
    wchar_t buffer[MAX_PATH * 4];
    DWORD n = GetFullPathNameW(path.c_str(), DWORD(std::size(buffer)), buffer, nullptr);
    return n ? std::wstring(buffer, n) : path;
}

std::wstring exe_folder()
{
    wchar_t buffer[MAX_PATH * 4];
    GetModuleFileNameW(nullptr, buffer, DWORD(std::size(buffer)));
    std::wstring path(buffer);
    return path.substr(0, path.find_last_of(L"\\/"));
}

std::wstring parent(const std::wstring& path) { return path.substr(0, path.find_last_of(L"\\/")); }
bool exists(const std::wstring& path) { return GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES; }

void make_dirs(const std::wstring& folder)
{
    if (folder.empty() || exists(folder)) return;
    make_dirs(parent(folder));
    CreateDirectoryW(folder.c_str(), nullptr);
}

struct Journal
{
    std::mutex lock;
    std::ofstream file;
    HANDLE out = nullptr;
    bool window = false;
};
Journal g_journal;

void open_journal(const std::wstring& path, bool window)
{
    make_dirs(parent(path));
    g_journal.file.open(path, std::ios::app | std::ios::binary);
    HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    if (out && out != INVALID_HANDLE_VALUE && GetFileType(out) != FILE_TYPE_UNKNOWN) g_journal.out = out;
    g_journal.window = window;
    set_log_sink([](const std::string& raw) {
        static const std::regex sensitive("\\b(?:password|passwd|token|secret|signing_key|authorization)\\b", std::regex::icase);
        std::string line = std::regex_search(raw, sensitive) ? "[redacted sensitive diagnostic line]" : raw;
        std::lock_guard<std::mutex> guard(g_journal.lock);
        if (g_journal.out)
        {
            std::string text = line + "\n";
            DWORD written = 0;
            WriteFile(g_journal.out, text.data(), DWORD(text.size()), &written, nullptr);
        }
        if (g_journal.file)
        {
            SYSTEMTIME t;
            GetSystemTime(&t);
            g_journal.file << format("[%04d-%02d-%02dT%02d:%02d:%02d+00:00] ", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond) << line << "\n";
            g_journal.file.flush();
        }
        if (g_journal.window) window_journal(line);
    });
}

// The panel keeps the last ten master journals (netcoop_master_control.ps1).
std::wstring new_journal(const std::wstring& folder)
{
    make_dirs(folder);
    std::vector<std::pair<FILETIME, std::wstring>> old;
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW((folder + L"\\master_*.log").c_str(), &data);
    if (find != INVALID_HANDLE_VALUE)
    {
        do
            old.push_back({ data.ftLastWriteTime, data.cFileName });
        while (FindNextFileW(find, &data));
        FindClose(find);
    }
    std::sort(old.begin(), old.end(), [](auto& a, auto& b) { return CompareFileTime(&a.first, &b.first) > 0; });
    for (size_t i = 9; i < old.size(); ++i) DeleteFileW((folder + L"\\" + old[i].second).c_str());
    SYSTEMTIME t;
    GetLocalTime(&t);
    return folder + L"\\" + widen(format("master_%04d%02d%02d_%02d%02d%02d.log", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond));
}

struct RootLock
{
    HANDLE handle=nullptr;
    ~RootLock(){if(handle) CloseHandle(handle);}
};

struct Args
{
    std::wstring mode = L"window";
    std::optional<std::wstring> config, destination, cluster, log_file, root, selftest;
    std::vector<std::string> locations;
    std::optional<int> port, gateway_port;
    std::optional<uint64_t> world_id, seed;
    std::optional<double> initial_ms, scale;
    bool authority = false, replace = false, add_location = false, initialized = false;
};

Args parse(const std::vector<std::wstring>& argv)
{
    Args a;
    size_t i = 0;
    if (i < argv.size() && argv[i].rfind(L"--", 0) != 0) a.mode = argv[i++];
    auto value = [&](const wchar_t* name) -> std::wstring {
        if (i + 1 >= argv.size()) throw Invalid("missing value for " + narrow(name));
        return argv[++i];
    };
    for (; i < argv.size(); ++i)
    {
        const std::wstring& o = argv[i];
        if (o == L"--config") a.config = value(L"--config");
        else if (o == L"--location") a.locations.push_back(narrow(value(L"--location")));
        else if (o == L"--port") a.port = int(parse_int(narrow(value(L"--port"))));
        else if (o == L"--destination") a.destination = value(L"--destination");
        else if (o == L"--world-id") a.world_id = uint64_t(std::stoull(value(L"--world-id")));
        else if (o == L"--seed") a.seed = uint64_t(std::stoull(value(L"--seed")));
        else if (o == L"--initial-ms") a.initial_ms = std::stod(value(L"--initial-ms"));
        else if (o == L"--scale") a.scale = std::stod(value(L"--scale"));
        else if (o == L"--authority") a.authority = true;
        else if (o == L"--replace") a.replace = true;
        else if (o == L"--add-location") a.add_location = true;
        else if (o == L"--gateway-port") a.gateway_port = int(parse_int(narrow(value(L"--gateway-port"))));
        else if (o == L"--cluster") a.cluster = value(L"--cluster");
        else if (o == L"--log-file") a.log_file = value(L"--log-file");
        else if (o == L"--root") a.root = value(L"--root");
        else if (o == L"--selftest") a.selftest = value(L"--selftest");
        else if (o == L"--initialized") a.initialized = true;
        else throw Invalid("unknown option " + narrow(o));
    }
    return a;
}
} // namespace

int master_main(const std::vector<std::wstring>& argv)
{
    bool show_error=argv.empty() || argv[0]==L"window" || argv[0]==L"console" || argv[0].rfind(L"--",0)==0;
    try
    {
        Args a = parse(argv);
        // <root>\dedicated\LostZoneServerDX11.exe: the server folder is one level up.
        std::wstring root = a.root ? full_path(*a.root) : parent(exe_folder());
        std::wstring config = a.config ? full_path(*a.config) : root + L"\\appdata\\master\\config.json";
        if (a.mode == L"init")
        {
            if (!a.config) throw Invalid("init requires --config");
            create_config(config, a.locations, a.world_id, a.seed, a.initial_ms, a.scale);
            return 0;
        }
        if (a.mode == L"writer-config")
        {
            if (!a.config || !a.destination || a.locations.size() != 1 || a.authority) throw Invalid("writer-config requires one location and its destination");
            if (a.add_location) add_location_credential(config, a.locations[0]);
            create_writer_config(config, full_path(*a.destination), a.locations[0], a.replace);
            return 0;
        }
        if (a.mode == L"bridge-config")
        {
            if (!a.config || !a.destination) throw Invalid("bridge-config requires --destination in the server userdata folder");
            if (!a.authority) throw Invalid("the engine master writes the authority bridge only");
            create_bridge_config(config, full_path(*a.destination), true, a.replace);
            return 0;
        }
        if (a.mode != L"serve" && a.mode != L"window" && a.mode != L"console" && a.mode!=L"bootstrap") throw Invalid("unknown master mode");
        RootLock instance;
        const auto lock_name=L"Local\\LostZoneMaster_"+widen(sha256_hex(lower(narrow(full_path(root)))));
        instance.handle=CreateMutexW(nullptr,FALSE,lock_name.c_str());
        if (!instance.handle || GetLastError()==ERROR_ALREADY_EXISTS) throw Unavailable("the master for this folder is already open");
        std::wstring plan = a.cluster ? full_path(*a.cluster) : root + L"\\appdata\\server\\netcoop_cluster.ltx";
        Service::Options service;
        service.config = config;
        service.port = a.port;
        service.cluster = plan;
        if(!a.config && !a.selftest) service.runtime_root=root;
        const std::wstring journal = a.log_file ? full_path(*a.log_file) : new_journal(root+L"\\appdata\\server\\netcoop_cluster");
        open_journal(journal,a.mode!=L"serve");
        if (!a.config && !a.selftest)
        {
            // Every start, including an existing installation, completes missing
            // maps and refreshes stale writer credentials. No PowerShell/Python.
            prepare_engine_cluster(root,config,plan);
        }
        service.gateway_port = a.gateway_port ? *a.gateway_port : (exists(plan) ? read_entry_port(plan) : 0);
        if (service.gateway_port < 0 || service.gateway_port > 65535) throw Invalid("the player entry needs a valid port and the location plan");
        if(a.mode==L"bootstrap") return 0; // preparation only: no listeners or processes
        std::wstring journal_folder = root + L"\\appdata\\server\\netcoop_cluster";
        if (a.mode == L"serve")
        {
            Service running(service);
            std::unique_ptr<HostController> host;
            if(!a.config && !a.selftest) host=std::make_unique<HostController>(root,plan);
            while (running.running()) {if(host) {host->epoch(uint64_t(*running.store().epoch));host->enabled(running.ready());}Sleep(1000);}
            return 0;
        }
        WindowOptions window;
        window.service = service;
        window.roster_folder = parent(plan) + L"\\netcoop_cluster";
        window.log_folder = parent(journal);
        if (a.selftest) window.selftest = full_path(*a.selftest);
        return run_window(window);
    }
    catch (const std::exception& error)
    {
        // Private config/checkpoint exception text is never echoed.
        log_line("[diag][master] stopped type=" + exception_type(error) + " reason=" + error.what());
        if(show_error) {
            std::string reason=error.what();
            static const std::regex sensitive("password|passwd|token|secret|signing_key|authorization",std::regex::icase);
            if(std::regex_search(reason,sensitive)) reason="Приватная конфигурация недействительна; проверьте журнал мастера.";
            MessageBoxW(nullptr,(L"Мастер не запустился.\n\n"+widen(reason)+L"\n\nЖурнал: appdata\\server\\netcoop_cluster\\master_*.log").c_str(),L"Lost Zone — мастер сервера",MB_OK|MB_ICONERROR);
        }
        HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
        if (err && err != INVALID_HANDLE_VALUE)
        {
            std::string text = "Master stopped: " + exception_type(error) + ". Check the private configuration and log.\n";
            DWORD written = 0;
            WriteFile(err, text.data(), DWORD(text.size()), &written, nullptr);
        }
        return 1;
    }
}
} // namespace lzm

// x_ray.cpp WinMain: "-netcoop_master" turns the server executable into the master.
int netcoop_master_entry()
{
    int count = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &count);
    std::vector<std::wstring> args;
    bool after = false;
    wchar_t executable[4096];GetModuleFileNameW(nullptr,executable,4096);
    const auto slash=wcsrchr(executable,L'\\');
    if(_wcsicmp(slash ? slash+1:executable,L"LostZoneMaster.exe")==0) after=true;
    for (int i = 1; i < count; ++i)
    {
        if (std::wstring(argv[i]) == L"-netcoop_master") after = true;
        else if (after) args.push_back(argv[i]);
    }
    LocalFree(argv);
    return lzm::master_main(args);
}

bool netcoop_master_named_entry()
{
    wchar_t executable[4096];GetModuleFileNameW(nullptr,executable,4096);
    const auto slash=wcsrchr(executable,L'\\');
    return _wcsicmp(slash ? slash+1:executable,L"LostZoneMaster.exe")==0;
}
