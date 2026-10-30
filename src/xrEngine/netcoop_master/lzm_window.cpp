#include "lzm_window.h"

#include <windows.h>
#include <windowsx.h>
#include <commctrl.h>
#include <dwmapi.h>
#include <richedit.h>
#include <shellapi.h>
#include <uxtheme.h>

#include <algorithm>
#include <cctype>
#include <ctime>
#include <tuple>
#include <atomic>
#include <fstream>
#include <sstream>

#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "uxtheme.lib")
#pragma comment(lib, "shell32.lib")

namespace lzm
{
// -- calendar --------------------------------------------------------------------------------------------
std::string calendar_text(double world_ms)
{
    if (!(world_ms >= 0) || world_ms > 3e17) return "—";
    int64_t ms = int64_t(world_ms);
    int64_t days = ms / 86400000, rest = ms % 86400000;
    // days since 0001-01-01 -> civil date (H. Hinnant's days_from_civil inverse)
    int64_t z = days - 719162 + 719468;  // to 1970 epoch, then shifted to 0000-03-01
    int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    int64_t doe = z - era * 146097;
    int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t y = yoe + era * 400;
    int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    int64_t mp = (5 * doy + 2) / 153;
    int64_t d = doy - (153 * mp + 2) / 5 + 1;
    int64_t m = mp < 10 ? mp + 3 : mp - 9;
    if (m <= 2) ++y;
    return format("%02lld.%02lld.%04lld  %02lld:%02lld", (long long)d, (long long)m, (long long)y, (long long)(rest / 3600000),
                  (long long)(rest / 60000 % 60));
}

namespace
{
COLORREF rgb(int r, int g, int b) { return RGB(r, g, b); }
const COLORREF C_BG = rgb(10, 10, 11), C_SURFACE = rgb(16, 16, 18), C_RAISED = rgb(24, 24, 27), C_HOVER = rgb(32, 32, 36),
               C_LINE = rgb(38, 38, 42), C_TEXT = rgb(232, 230, 225), C_MUTED = rgb(140, 140, 145), C_DIM = rgb(90, 90, 95),
               C_ACCENT = rgb(217, 164, 65), C_ACCENT_HOVER = rgb(230, 182, 96), C_GREEN = rgb(76, 195, 138), C_AMBER = rgb(224, 168, 74),
               C_RED = rgb(229, 83, 75);

const std::map<std::string, std::wstring> MAP_NAMES = {
    { "k00_marsh", L"Болота" }, { "l01_escape", L"Кордон" }, { "l02_garbage", L"Свалка" }, { "l03_agroprom", L"Агропром" },
    { "l03u_agr_underground", L"Подземелья Агропрома" }, { "l04_darkvalley", L"Тёмная долина" }, { "l04u_labx18", L"Лаборатория X-18" },
    { "l05_bar", L"Бар" }, { "l06_rostok", L"Дикая территория" }, { "l07_military", L"Армейские склады" }, { "l08_yantar", L"Янтарь" },
    { "l08u_brainlab", L"Лаборатория X-16" }, { "l09_deadcity", L"Мёртвый город" }, { "l10_limansk", L"Лиманск" }, { "l10_radar", L"Радар" },
    { "l10_red_forest", L"Рыжий лес" }, { "l10u_bunker", L"Лаборатория X-19" }, { "l11_hospital", L"Госпиталь" }, { "l11_pripyat", L"Припять" },
    { "l12_stancia", L"ЧАЭС" }, { "l12_stancia_2", L"ЧАЭС-2" }, { "l12u_control_monolith", L"Монолит" }, { "l12u_sarcofag", L"Саркофаг" },
    { "l13_generators", L"Генераторы" }, { "l13u_warlab", L"Варлаб" }, { "k01_darkscape", L"Тёмная лощина" },
    { "k02_trucks_cemetery", L"Кладбище техники" }, { "y04_pole", L"Поляна" }, { "zaton", L"Затон" }, { "jupiter", L"Юпитер" },
    { "jupiter_underground", L"Путепровод «Припять-1»" }, { "pripyat", L"Припять (ЗП)" }, { "labx8", L"Лаборатория X-8" } };
const std::vector<std::pair<std::string, std::wstring>> WEATHER = { { "clear", L"ясно" }, { "partly", L"переменная облачность" },
                                                                     { "cloudy", L"облачно" }, { "rain", L"дождь" }, { "storm", L"гроза" },
                                                                     { "foggy", L"туман" } };
const std::map<std::string, std::wstring> PHASES = { { "SCHEDULED", L"запланирован" }, { "WARNING", L"предупреждение" }, { "ACTIVE", L"идёт" },
                                                     { "PEAK", L"пик" }, { "ENDED", L"закончился" } };
// GAMMA's emission (2220 game s) and psi storm (1030 game s), the director's phase split.
const char* EMISSION_NOW = "emission 555 777 888 100";
const char* PSI_NOW = "psi 257.5 360.5 412 100";

std::wstring map_name(const std::string& id)
{
    auto it = MAP_NAMES.find(id);
    return it == MAP_NAMES.end() ? widen(id) : it->second;
}

std::wstring weather_name(const std::string& id)
{
    for (auto& w : WEATHER)
        if (w.first == id) return w.second;
    return widen(id);
}

std::wstring span(double ms)
{
    int64_t minutes = ms > 0 ? int64_t(ms / 60000) : 0;
    if (minutes >= 60) return std::to_wstring(minutes / 60) + L" ч " + (minutes % 60 < 10 ? L"0" : L"") + std::to_wstring(minutes % 60) + L" мин";
    return std::to_wstring(minutes) + L" мин";
}

struct LocationRow { std::string id; std::wstring name, state, address; int players = 0; bool online = false, planned = false; };
struct PlayerRow { std::string login, name, location, faction, role, ping, state; };

struct View
{
    bool ready = false;
    std::string world_id, worker_error;
    int64_t epoch = 0;
    double world_ms = 0, scale = 10;
    json weather, emission, psi;
    std::vector<LocationRow> locations;
    std::vector<PlayerRow> players;
};

struct Button { int id; std::wstring text; RECT rc{}; bool accent = false; COLORREF color = 0; };
enum { B_EMISSION = 1, B_PSI, B_WEATHER, B_SPEED, B_LOGS, B_TOGGLE, B_RUN, B_LOC_ON, B_LOC_OFF, T_LOCATIONS = 100, T_PLAYERS, T_JOURNAL, T_CONSOLE };

struct State
{
    WindowOptions options;
    std::unique_ptr<Service> service;
    std::mutex service_lock;  // the poller reads the service, the UI thread replaces it
    std::string service_error;
    int64_t started_ns = 0;
    HWND hwnd = nullptr, locations = nullptr, players = nullptr, journal = nullptr, output = nullptr, input = nullptr;
    int tab = 0;
    std::vector<Button> buttons, tabs;
    int hover = -1;
    float dpi = 1;
    HFONT f_ui = nullptr, f_small = nullptr, f_bold = nullptr, f_title = nullptr, f_value = nullptr, f_mono = nullptr;
    std::mutex lines_lock;
    std::vector<std::pair<std::string, std::string>> lines;
    std::mutex view_lock;
    std::optional<View> view;
    std::atomic<bool> closing{ false };
    std::thread poller;
    std::wstring status_text;
    COLORREF status_color = C_MUTED;
    std::vector<LocationRow> shown_locations;
    std::vector<PlayerRow> shown_players;
    RECT content{};
    WNDPROC input_proc = nullptr, list_proc = nullptr;
    json selftest;
    int64_t watchdog_started_ns = 0;  // the hoster's watchdog was started from here
};

State* g_state = nullptr;
std::mutex g_state_lock;

int px(State& s, int v) { return int(v * s.dpi + 0.5f); }

HFONT make_font(State& s, const wchar_t* face, int points, int weight)
{
    return CreateFontW(-MulDiv(points, int(96 * s.dpi), 72), 0, 0, 0, weight, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                       CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, face);
}

bool font_exists(const wchar_t* face)
{
    HDC dc = GetDC(nullptr);
    LOGFONTW lf{};
    lf.lfCharSet = DEFAULT_CHARSET;
    wcsncpy_s(lf.lfFaceName, face, _TRUNCATE);
    bool found = false;
    EnumFontFamiliesExW(dc, &lf, [](const LOGFONTW*, const TEXTMETRICW*, DWORD, LPARAM p) -> int { *(bool*)p = true; return 0; }, (LPARAM)&found, 0);
    ReleaseDC(nullptr, dc);
    return found;
}

// -- the view, read off the UI thread --------------------------------------------------------------------------
std::vector<PlayerRow> read_rosters(const std::wstring& folder, const std::map<int, std::string>& ports)
{
    std::vector<PlayerRow> rows;
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW((folder + L"\\players_*.txt").c_str(), &data);
    if (find == INVALID_HANDLE_VALUE) return rows;
    FILETIME now_ft;
    GetSystemTimeAsFileTime(&now_ft);
    ULARGE_INTEGER now{ { now_ft.dwLowDateTime, now_ft.dwHighDateTime } };
    do
    {
        ULARGE_INTEGER written{ { data.ftLastWriteTime.dwLowDateTime, data.ftLastWriteTime.dwHighDateTime } };
        if (now.QuadPart > written.QuadPart && now.QuadPart - written.QuadPart > 15ULL * 10000000ULL) continue;  // that map stopped
        std::string name = narrow(data.cFileName);
        int port = 0;
        try { port = int(parse_int(name.substr(8, name.size() - 12))); }
        catch (...) { continue; }
        std::ifstream in(folder + L"\\" + data.cFileName, std::ios::binary);
        std::ostringstream text;
        text << in.rdbuf();
        for (auto line : split(text.str(), '\n'))
        {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            auto f = split(line, '|');
            if (f.size() < 6 || f[0].empty()) continue;
            auto it = ports.find(port);
            rows.push_back({ f[0], f[1], it == ports.end() ? "порт " + std::to_string(port) : it->second, f[3], f[4], f[5], "" });
        }
    } while (FindNextFileW(find, &data));
    FindClose(find);
    return rows;
}

// -- the hoster's location servers (owner 2026-10-24, spec 1.2) -----------------------------------------------
// The hoster's watchdog (hoster\netcoop_cluster_watchdog.ps1) starts and stops
// the location servers: it reads host_command_<map>.txt ("start", or "stop":
// save the world and quit) and publishes host_view_<pc>.json - each map's
// state - in the cluster folder, the mailbox the hoster's panel uses too. The
// master's Locations tab switches maps there without a restart; the state it
// shows comes back from the watchdog and from the maps' leases.
struct HostMap { std::string state, mode; int progress = -1, retry_seconds = 0; int64_t exit_code = 0; bool has_exit_code = false; };
struct HostView { bool fresh = false; std::map<std::string, HostMap> maps; };

HostView read_host_view(const std::wstring& folder)
{
    HostView v;
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW((folder + L"\\host_view_*.json").c_str(), &data);
    if (find == INVALID_HANDLE_VALUE) return v;
    const int64_t now = int64_t(time(nullptr));
    do
    {
        std::ifstream in(folder + L"\\" + data.cFileName, std::ios::binary);
        std::ostringstream text;
        text << in.rdbuf();
        std::string body = text.str();
        if (body.size() >= 3 && body.compare(0, 3, "\xEF\xBB\xBF") == 0) body.erase(0, 3);
        try
        {
            json view = loads(body);
            if (!view.contains("updated") || !view["updated"].is_number()) continue;
            const int64_t updated = view["updated"].get<int64_t>();
            if (updated < now - 30 || updated > now + 5) continue;
            v.fresh = true;
            if (!view.contains("maps") || !view["maps"].is_array()) continue;
            for (const json& m : view["maps"])
            {
                if (!m.is_object() || !m.contains("map") || !m["map"].is_string()) continue;
                HostMap row;
                if (m.contains("state") && m["state"].is_string()) row.state = m["state"].get<std::string>();
                if (m.contains("mode") && m["mode"].is_string()) row.mode = m["mode"].get<std::string>();
                if (m.contains("progress") && m["progress"].is_number()) row.progress = int(m["progress"].get<double>());
                if (m.contains("retry_seconds") && m["retry_seconds"].is_number()) row.retry_seconds = std::max(0, std::min(300, m["retry_seconds"].get<int>()));
                if (m.contains("exit_code") && m["exit_code"].is_number()) { row.exit_code = m["exit_code"].get<int64_t>(); row.has_exit_code = true; }
                v.maps[m["map"].get<std::string>()] = row;
            }
        }
        catch (...) {}
    } while (FindNextFileW(find, &data));
    FindClose(find);
    return v;
}

// <root>\appdata\server\netcoop_cluster -> <root>
std::wstring runtime_root(const std::wstring& cluster_folder)
{
    std::wstring root = cluster_folder;
    for (int i = 0; i < 3; ++i)
    {
        size_t cut = root.find_last_of(L"\\/");
        if (cut == std::wstring::npos) return L"";
        root.resize(cut);
    }
    return root;
}

bool write_host_command(const std::wstring& folder, const std::string& map, const std::string& action)
{
    if (map.empty() || !std::all_of(map.begin(), map.end(), [](char c) { return std::isalnum((unsigned char)c) || c == '_'; })) return false;
    CreateDirectoryW(folder.c_str(), nullptr);
    std::wstring target = folder + L"\\host_command_" + widen(map) + L".txt";
    std::wstring temporary = target + L"." + std::to_wstring(GetCurrentProcessId()) + L".tmp";
    {
        std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
        if (!out) return false;
        out << action;
    }
    return MoveFileExW(temporary.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
}

// The watchdog reads the commands; it is started from here when it is not
// running (its view is not fresh), at most once a minute.
bool ensure_watchdog(State& s, bool fresh)
{
    if (fresh) return true;
    if (s.watchdog_started_ns && monotonic_ns() - s.watchdog_started_ns < 60000000000LL) return true;
    std::wstring root = runtime_root(s.options.roster_folder);
    std::wstring script = root + L"\\hoster\\netcoop_cluster_watchdog.ps1";
    if (root.empty() || GetFileAttributesW(script.c_str()) == INVALID_FILE_ATTRIBUTES) return false;
    std::wstring line = L"powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + L"\" -Runtime \"" + root + L"\" -NoAutoStart";
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    std::vector<wchar_t> buffer(line.begin(), line.end());
    buffer.push_back(0);
    if (!CreateProcessW(nullptr, buffer.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, root.c_str(), &si, &pi)) return false;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    s.watchdog_started_ns = monotonic_ns();
    log_line("Запущено управление локациями хостера (watchdog).");
    return true;
}

View build_view(Service& service, const WindowOptions& options)
{
    View v;
    json status = service.recovery_status();
    v.ready = status["admission_ready"].get<bool>();
    v.world_id = status["world"]["world_id"].get<std::string>();
    v.epoch = status["world"]["epoch"].get<int64_t>();
    v.worker_error = status["worker_error_type"].is_null() ? "" : status["worker_error_type"].get<std::string>();
    Store& store = service.store();
    World& world = service.world();
    std::vector<json> leases, sessions;
    {
        std::lock_guard<std::recursive_mutex> guard(store.lock);
        store.require_epoch(store.db);
        v.world_ms = world.now();
        v.scale = store.db.scalar("SELECT scale FROM world WHERE singleton=1").get<double>();
        for (const char* name : { "weather", "emission", "psi_storm" })
        {
            json row = store.db.one("SELECT state FROM world_state WHERE name=?", { name });
            if (row.is_null() || row["state"].get<std::string>().size() > 65536) continue;
            json state = loads(row["state"].get<std::string>());
            json evaluated = Timelines::evaluate(name, state, v.world_ms);
            evaluated["times"] = state["times"];
            (std::string(name) == "weather" ? v.weather : std::string(name) == "emission" ? v.emission : v.psi) = evaluated;
        }
        leases = store.db.all("SELECT location, expires_ms FROM location_lease ORDER BY location LIMIT 256");
        sessions = store.db.all("SELECT s.account AS account, s.state AS state, e.location AS location FROM player_session s "
                                "JOIN entity e ON e.id=s.character_id WHERE s.state IN ('ACTIVE','FROZEN') ORDER BY e.location, s.account LIMIT 512");
    }
    int64_t real = world.real_ms();
    auto plan = read_cluster(options.service.cluster);
    std::map<int, std::string> ports;
    for (auto& p : plan) ports[p.port] = p.name;
    std::vector<PlayerRow> players = read_rosters(options.roster_folder, ports);
    for (auto& s : sessions)
    {
        std::string account = s["account"].get<std::string>();
        auto it = std::find_if(players.begin(), players.end(), [&](const PlayerRow& r) { return lower(r.login) == lower(account); });
        if (it == players.end()) players.push_back({ account, "", s["location"].get<std::string>(), "", "", "", s["state"].get<std::string>() });
        else it->state = s["state"].get<std::string>();
    }
    std::sort(players.begin(), players.end(), [](const PlayerRow& a, const PlayerRow& b) {
        return a.location != b.location ? a.location < b.location : lower(a.login) < lower(b.login);
    });
    v.players = players;
    std::map<std::string, int64_t> expiry;
    for (auto& l : leases) expiry[l["location"].get<std::string>()] = l["expires_ms"].get<int64_t>();
    std::vector<std::pair<std::string, std::string>> names;  // id, address
    for (auto& p : plan) names.push_back({ p.name, (p.host.empty() ? "этот ПК" : p.host) + ":" + std::to_string(p.port) });
    const size_t planned = names.size();
    for (auto& e : expiry)
        if (std::none_of(names.begin(), names.end(), [&](auto& n) { return n.first == e.first; })) names.push_back({ e.first, "" });
    // All 33 maps from the start (owner 2026-10-24), the plan's first.
    for (auto& m : MAP_NAMES)
        if (std::none_of(names.begin(), names.end(), [&](auto& n) { return n.first == m.first; })) names.push_back({ m.first, "" });
    HostView host = read_host_view(options.roster_folder);
    for (size_t i = 0; i < names.size(); ++i)
    {
        auto& n = names[i];
        LocationRow row;
        row.id = n.first;
        row.name = map_name(n.first);
        row.planned = i < planned;
        row.address = n.second.empty() ? L"—" : widen(n.second);
        auto it = expiry.find(n.first);
        row.online = it != expiry.end() && it->second > real;
        auto h = host.maps.find(n.first);
        const std::string state = h != host.maps.end() ? h->second.state : "";
        if (h != host.maps.end() && state != "running" && state != "saving") row.online = false;
        if (row.online) row.state = state == "saving" ? L"сохраняет мир…" : L"в сети";
        else if (state == "loading")
            row.state = L"загружается" + (h->second.progress > 0 ? L" · " + std::to_wstring(h->second.progress) + L"%" : L"");
        else if (state == "running") row.state = L"запускается";
        else if (state == "queued") row.state = L"в очереди на запуск";
        else if (state == "memory") row.state = L"ждёт память";
        else if (state == "master_stopped") row.state = L"мастер остановлен";
        else if (state == "loading_timeout") row.state = L"загрузка затянулась";
        else if (state == "retry") row.state = L"сбой · повтор через " + std::to_wstring(h->second.retry_seconds) + L" с";
        else if (state == "failed") row.state = L"остановлена после сбоев" + (h->second.has_exit_code ? L" · код " + std::to_wstring(h->second.exit_code) : L"");
        else if (state == "saving") row.state = L"сохраняет мир…";
        else if (it != expiry.end()) row.state = L"не отвечает";
        else row.state = row.planned ? L"выключена" : L"нет в плане хостера";
        for (auto& p : players) row.players += p.location == n.first;
        v.locations.push_back(row);
    }
    return v;
}

void poll(State* s)
{
    while (!s->closing)
    {
        std::optional<View> view;
        try
        {
            std::lock_guard<std::mutex> guard(s->service_lock);
            if (s->service && s->service->running()) view = build_view(*s->service, s->options);
        }
        catch (...) {}
        {
            std::lock_guard<std::mutex> guard(s->view_lock);
            s->view = view;
        }
        for (int i = 0; i < 10 && !s->closing; ++i) Sleep(100);
    }
}

// -- drawing ----------------------------------------------------------------------------------------------------------
void fill(HDC dc, const RECT& rc, COLORREF color)
{
    HBRUSH brush = CreateSolidBrush(color);
    FillRect(dc, &rc, brush);
    DeleteObject(brush);
}

void text(HDC dc, const std::wstring& t, RECT rc, HFONT font, COLORREF color, UINT flags = DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS)
{
    SelectObject(dc, font);
    SetTextColor(dc, color);
    SetBkMode(dc, TRANSPARENT);
    DrawTextW(dc, t.c_str(), int(t.size()), &rc, flags | DT_NOPREFIX);
}

void card(State& s, HDC dc, RECT rc, const wchar_t* title, const std::wstring& value, const std::wstring& detail, COLORREF value_color = C_TEXT)
{
    fill(dc, rc, C_LINE);
    RECT inner{ rc.left + 1, rc.top + 1, rc.right - 1, rc.bottom - 1 };
    fill(dc, inner, C_SURFACE);
    int pad = px(s, 16);
    text(dc, title, { rc.left + pad, rc.top + px(s, 10), rc.right - pad, rc.top + px(s, 30) }, s.f_small, C_MUTED);
    text(dc, value, { rc.left + pad, rc.top + px(s, 30), rc.right - pad, rc.top + px(s, 62) }, s.f_value, value_color);
    text(dc, detail, { rc.left + pad, rc.top + px(s, 62), rc.right - pad, rc.bottom - px(s, 8) }, s.f_small, C_MUTED);
}

std::pair<std::wstring, std::wstring> weather_text(const json& state)
{
    if (state.is_null()) return { L"ещё не задана", L"" };
    const json& p = state["parameters"];
    std::wstring target = weather_name(p["target"].get<std::string>());
    std::string phase = state["phase"].get<std::string>();
    double blend = state.contains("blend") ? state["blend"].get<double>() : 1;
    if (phase == "TRANSITION" && blend < 1)
        return { target, L"смена: " + weather_name(p["source"].get<std::string>()) + L" → " + target + L" · " + std::to_wstring(int(blend * 100)) + L"%" };
    if (phase == "SCHEDULED") return { weather_name(p["source"].get<std::string>()), L"дальше: " + target };
    return { target, L"установилась" };
}

std::pair<std::wstring, std::wstring> event_text(const json& state, double now)
{
    if (state.is_null()) return { L"не запланирован", L"" };
    std::string phase = state["phase"].get<std::string>();
    const json& times = state["times"];
    if (phase == "SCHEDULED") return { L"через " + span(times["WARNING"].get<double>() - now), L"игрового времени" };
    if (phase == "ENDED") return { L"нет", L"следующий назначит мастер" };
    return { PHASES.at(phase), L"до конца " + span(times["ENDED"].get<double>() - now) };
}

void layout(State& s)
{
    RECT rc;
    GetClientRect(s.hwnd, &rc);
    int m = px(s, 24);
    int y = px(s, 96 + 96 + 16);  // header + cards + gap
    s.buttons.clear();
    auto add = [&](int id, const std::wstring& t, int& x, bool right = false, bool accent = false, COLORREF color = C_TEXT) {
        HDC dc = GetDC(s.hwnd);
        SelectObject(dc, s.f_bold);
        SIZE size;
        GetTextExtentPoint32W(dc, t.c_str(), int(t.size()), &size);
        ReleaseDC(s.hwnd, dc);
        int w = size.cx + px(s, 32), h = px(s, 36);
        Button b{ id, t };
        if (right) { b.rc = { x - w, y, x, y + h }; x -= w + px(s, 8); }
        else { b.rc = { x, y, x + w, y + h }; x += w + px(s, 8); }
        b.accent = accent;
        b.color = color;
        s.buttons.push_back(b);
    };
    int x = m;
    add(B_EMISSION, L"Выброс сейчас", x);
    add(B_PSI, L"Пси-шторм сейчас", x);
    add(B_WEATHER, L"Сменить погоду  ▾", x);
    add(B_SPEED, L"Скорость времени  ▾", x);
    int r = rc.right - m;
    bool running = s.service && s.service->running();
    add(B_TOGGLE, running ? L"Остановить мастер" : L"Запустить мастер", r, true, false, running ? C_RED : C_GREEN);
    add(B_LOGS, L"Журналы", r, true);
    y += px(s, 36 + 14);
    s.tabs.clear();
    x = m;
    View view;
    {
        std::lock_guard<std::mutex> guard(s.view_lock);
        if (s.view) view = *s.view;
    }
    int online = 0;
    for (auto& l : view.locations) online += l.online;
    std::vector<std::wstring> names = { L"Локации · " + std::to_wstring(online) + L"/" + std::to_wstring(view.locations.size()),
                                        L"Игроки · " + std::to_wstring(view.players.size()), L"Журнал", L"Консоль" };
    for (int i = 0; i < 4; ++i)
    {
        HDC dc = GetDC(s.hwnd);
        SelectObject(dc, s.f_bold);
        SIZE size;
        GetTextExtentPoint32W(dc, names[size_t(i)].c_str(), int(names[size_t(i)].size()), &size);
        ReleaseDC(s.hwnd, dc);
        Button t{ T_LOCATIONS + i, names[size_t(i)] };
        t.rc = { x, y, x + size.cx + px(s, 36), y + px(s, 36) };
        x = t.rc.right;
        s.tabs.push_back(t);
    }
    y += px(s, 36);
    s.content = { m, y, rc.right - m, rc.bottom - px(s, 34) };
    int w = s.content.right - s.content.left, h = s.content.bottom - s.content.top;
    MoveWindow(s.locations, s.content.left, s.content.top, w, h, TRUE);
    MoveWindow(s.players, s.content.left, s.content.top, w, h, TRUE);
    MoveWindow(s.journal, s.content.left, s.content.top, w, h, TRUE);
    int line = px(s, 40);
    MoveWindow(s.output, s.content.left, s.content.top, w, h - line - px(s, 8), TRUE);
    MoveWindow(s.input, s.content.left + px(s, 86), s.content.bottom - line + px(s, 10), w - px(s, 86) - px(s, 140), line - px(s, 18), TRUE);
    ShowWindow(s.locations, s.tab == 0 ? SW_SHOW : SW_HIDE);
    ShowWindow(s.players, s.tab == 1 ? SW_SHOW : SW_HIDE);
    ShowWindow(s.journal, s.tab == 2 ? SW_SHOW : SW_HIDE);
    ShowWindow(s.output, s.tab == 3 ? SW_SHOW : SW_HIDE);
    ShowWindow(s.input, s.tab == 3 ? SW_SHOW : SW_HIDE);
    if (s.tab == 0)
    {
        // Switch the selected maps (several with Ctrl / Shift) without restarting anything.
        MoveWindow(s.locations, s.content.left, s.content.top, w, h - line - px(s, 8), TRUE);
        int bx = s.content.left;
        for (auto [bid, label, color] : { std::make_tuple(int(B_LOC_ON), std::wstring(L"Включить выбранные"), C_GREEN),
                                          std::make_tuple(int(B_LOC_OFF), std::wstring(L"Выключить выбранные"), C_RED) })
        {
            HDC dc = GetDC(s.hwnd);
            SelectObject(dc, s.f_bold);
            SIZE size;
            GetTextExtentPoint32W(dc, label.c_str(), int(label.size()), &size);
            ReleaseDC(s.hwnd, dc);
            Button b{ bid, label };
            b.rc = { bx, s.content.bottom - line, bx + size.cx + px(s, 32), s.content.bottom };
            b.color = color;
            bx = b.rc.right + px(s, 8);
            s.buttons.push_back(b);
        }
    }
    if (s.tab == 3)
    {
        Button run{ B_RUN, L"Выполнить" };
        run.rc = { s.content.right - px(s, 132), s.content.bottom - line, s.content.right, s.content.bottom };
        run.accent = true;
        s.buttons.push_back(run);
    }
    for (HWND list : { s.locations, s.players })
    {
        int columns = Header_GetItemCount(ListView_GetHeader(list));
        if (columns) ListView_SetColumnWidth(list, columns - 1, LVSCW_AUTOSIZE_USEHEADER);
    }
}

void paint(State& s, HDC target)
{
    RECT rc;
    GetClientRect(s.hwnd, &rc);
    HDC dc = CreateCompatibleDC(target);
    HBITMAP bitmap = CreateCompatibleBitmap(target, rc.right, rc.bottom);
    HGDIOBJ old = SelectObject(dc, bitmap);
    fill(dc, rc, C_BG);
    int m = px(s, 24);
    text(dc, L"LOST ZONE", { m, px(s, 14), rc.right / 2, px(s, 52) }, s.f_title, C_TEXT);
    text(dc, L"Мастер мира · календарь, погода, выбросы и переходы всех локаций", { m, px(s, 52), rc.right / 2 + px(s, 200), px(s, 76) }, s.f_small, C_MUTED);
    View view;
    bool have = false;
    {
        std::lock_guard<std::mutex> guard(s.view_lock);
        if (s.view) { view = *s.view; have = true; }
    }
    bool running = s.service && s.service->running();
    std::wstring state = L"● остановлен", detail = L"карты не пускают игроков без мастера";
    COLORREF color = C_RED;
    if (running && !have) { state = L"● запуск"; detail = L"мастер открывает мир…"; color = C_AMBER; }
    else if (running)
    {
        state = view.ready ? L"● работает" : L"● восстанавливает мир";
        color = view.ready ? C_GREEN : C_AMBER;
        int64_t up = (monotonic_ns() - s.started_ns) / 1000000000LL;
        detail = L"WorldID " + widen(view.world_id) + L" · эпоха " + std::to_wstring(view.epoch) + L" · работает " + std::to_wstring(up / 3600) +
                 L" ч " + (up / 60 % 60 < 10 ? L"0" : L"") + std::to_wstring(up / 60 % 60) + L" мин" +
                 (view.worker_error.empty() ? L"" : L" · ошибка обработчика: " + widen(view.worker_error));
    }
    else if (!s.service_error.empty())
        detail = widen(s.service_error);
    text(dc, state, { rc.right / 2, px(s, 18), rc.right - m, px(s, 50) }, s.f_value, color, DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
    text(dc, detail, { rc.left + m, px(s, 52), rc.right - m, px(s, 76) }, s.f_small, C_MUTED, DT_RIGHT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);
    // cards
    int top = px(s, 96), height = px(s, 96), gap = px(s, 10);
    int width = (rc.right - 2 * m - 4 * gap) / 5;
    auto at = [&](int i) { return RECT{ m + i * (width + gap), top, m + i * (width + gap) + width, top + height }; };
    if (have)
    {
        card(s, dc, at(0), L"КАЛЕНДАРЬ ЗОНЫ", widen(calendar_text(view.world_ms)), L"скорость времени ×" + widen(python_float(view.scale)));
        auto w = weather_text(view.weather);
        card(s, dc, at(1), L"ПОГОДА", w.first, w.second);
        auto e = event_text(view.emission, view.world_ms);
        card(s, dc, at(2), L"ВЫБРОС", e.first, e.second, view.emission.is_object() && view.emission["phase"] != "ENDED" && view.emission["phase"] != "SCHEDULED" ? C_AMBER : C_TEXT);
        auto p = event_text(view.psi, view.world_ms);
        card(s, dc, at(3), L"ПСИ-ШТОРМ", p.first, p.second, view.psi.is_object() && view.psi["phase"] != "ENDED" && view.psi["phase"] != "SCHEDULED" ? C_AMBER : C_TEXT);
        int online = 0;
        for (auto& l : view.locations) online += l.online;
        card(s, dc, at(4), L"МИР", std::to_wstring(online) + L" из " + std::to_wstring(view.locations.size()) + L" локаций",
             L"игроков в мире: " + std::to_wstring(view.players.size()));
    }
    else
        for (int i = 0; i < 5; ++i) card(s, dc, at(i), i == 0 ? L"КАЛЕНДАРЬ ЗОНЫ" : i == 1 ? L"ПОГОДА" : i == 2 ? L"ВЫБРОС" : i == 3 ? L"ПСИ-ШТОРМ" : L"МИР", L"—", L"");
    // buttons and tabs
    for (size_t i = 0; i < s.buttons.size(); ++i)
    {
        const Button& b = s.buttons[i];
        bool hot = s.hover == b.id;
        fill(dc, b.rc, b.accent ? (hot ? C_ACCENT_HOVER : C_ACCENT) : (hot ? C_HOVER : C_RAISED));
        text(dc, b.text, b.rc, s.f_bold, b.accent ? C_BG : b.color ? b.color : C_TEXT, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    }
    for (size_t i = 0; i < s.tabs.size(); ++i)
    {
        const Button& t = s.tabs[i];
        bool selected = int(i) == s.tab, hot = s.hover == t.id;
        fill(dc, t.rc, selected ? C_RAISED : hot ? C_SURFACE : C_BG);
        text(dc, t.text, t.rc, s.f_bold, selected ? C_ACCENT : hot ? C_TEXT : C_MUTED, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        if (selected) fill(dc, { t.rc.left, t.rc.bottom - px(s, 2), t.rc.right, t.rc.bottom }, C_ACCENT);
    }
    fill(dc, { s.content.left, s.content.top - 1, s.content.right, s.content.top }, C_LINE);
    if (s.tab == 3)
    {
        int line = px(s, 40);
        RECT bar{ s.content.left, s.content.bottom - line, s.content.right - px(s, 140), s.content.bottom };
        fill(dc, bar, C_RAISED);
        text(dc, L"master ›", { bar.left + px(s, 12), bar.top, bar.left + px(s, 86), bar.bottom }, s.f_mono, C_ACCENT);
    }
    text(dc, s.status_text, { m, rc.bottom - px(s, 30), rc.right - m, rc.bottom - px(s, 6) }, s.f_small, s.status_color);
    BitBlt(target, 0, 0, rc.right, rc.bottom, dc, 0, 0, SRCCOPY);
    SelectObject(dc, old);
    DeleteObject(bitmap);
    DeleteDC(dc);
}

// -- rich text journal ---------------------------------------------------------------------------------------------
void append(HWND edit, const std::wstring& t, COLORREF color)
{
    int length = GetWindowTextLengthW(edit);
    SendMessageW(edit, EM_SETSEL, length, length);
    CHARFORMAT2W format{};
    format.cbSize = sizeof(format);
    format.dwMask = CFM_COLOR;
    format.crTextColor = color;
    SendMessageW(edit, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&format);
    SendMessageW(edit, EM_REPLACESEL, FALSE, (LPARAM)t.c_str());
    int lines = int(SendMessageW(edit, EM_GETLINECOUNT, 0, 0));
    if (lines > 4000)
    {
        int cut = int(SendMessageW(edit, EM_LINEINDEX, lines - 3000, 0));
        SendMessageW(edit, EM_SETSEL, 0, cut);
        SendMessageW(edit, EM_REPLACESEL, FALSE, (LPARAM)L"");
    }
    SendMessageW(edit, WM_VSCROLL, SB_BOTTOM, 0);
}

HWND make_rich(State& s, HWND parent)
{
    HWND edit = CreateWindowExW(0, MSFTEDIT_CLASS, L"", WS_CHILD | WS_VSCROLL | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL, 0, 0, 10, 10,
                                parent, nullptr, GetModuleHandleW(nullptr), nullptr);
    SendMessageW(edit, EM_SETBKGNDCOLOR, 0, C_SURFACE);
    CHARFORMAT2W format{};
    format.cbSize = sizeof(format);
    format.dwMask = CFM_COLOR | CFM_FACE | CFM_SIZE;
    format.crTextColor = C_TEXT;
    format.yHeight = 10 * 20;
    wcscpy_s(format.szFaceName, font_exists(L"Cascadia Mono") ? L"Cascadia Mono" : L"Consolas");
    SendMessageW(edit, EM_SETCHARFORMAT, SCF_ALL, (LPARAM)&format);
    RECT margins{ px(s, 12), px(s, 8), px(s, 12), px(s, 8) };
    (void)margins;
    SendMessageW(edit, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(px(s, 12), px(s, 12)));
    SetWindowTheme(edit, L"DarkMode_Explorer", nullptr);
    return edit;
}

LRESULT CALLBACK list_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    State* s = g_state;
    if (message == WM_NOTIFY && s)
    {
        auto header = (LPNMHDR)lparam;
        if (header->code == NM_CUSTOMDRAW && header->hwndFrom == ListView_GetHeader(hwnd))
        {
            auto draw = (LPNMCUSTOMDRAW)lparam;
            if (draw->dwDrawStage == CDDS_PREPAINT)
            {
                RECT all;
                GetClientRect(header->hwndFrom, &all);
                fill(draw->hdc, all, C_RAISED);
                return CDRF_NOTIFYITEMDRAW;
            }
            if (draw->dwDrawStage == CDDS_ITEMPREPAINT)
            {
                fill(draw->hdc, draw->rc, C_RAISED);
                wchar_t title[64] = {};
                HDITEMW item{};
                item.mask = HDI_TEXT;
                item.pszText = title;
                item.cchTextMax = 63;
                SendMessageW(header->hwndFrom, HDM_GETITEMW, WPARAM(draw->dwItemSpec), (LPARAM)&item);
                RECT rc = draw->rc;
                rc.left += px(*s, 10);
                text(draw->hdc, title, rc, s->f_small, C_MUTED);
                fill(draw->hdc, { draw->rc.right - 1, draw->rc.top + px(*s, 6), draw->rc.right, draw->rc.bottom - px(*s, 6) }, C_LINE);
                return CDRF_SKIPDEFAULT;
            }
        }
    }
    return CallWindowProcW(s ? s->list_proc : DefWindowProcW, hwnd, message, wparam, lparam);
}

HWND make_list(State& s, HWND parent, const std::vector<std::pair<std::wstring, int>>& columns, bool many = false)
{
    HWND list = CreateWindowExW(0, WC_LISTVIEWW, L"", WS_CHILD | LVS_REPORT | (many ? 0 : LVS_SINGLESEL) | LVS_SHOWSELALWAYS | LVS_NOSORTHEADER, 0, 0, 10, 10,
                                parent, nullptr, GetModuleHandleW(nullptr), nullptr);
    ListView_SetExtendedListViewStyle(list, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER);
    ListView_SetBkColor(list, C_SURFACE);
    ListView_SetTextBkColor(list, C_SURFACE);
    ListView_SetTextColor(list, C_TEXT);
    SetWindowTheme(list, L"DarkMode_Explorer", nullptr);
    SendMessageW(list, WM_SETFONT, (WPARAM)s.f_ui, TRUE);
    // Row height from a small image list.
    HIMAGELIST spacer = ImageList_Create(1, px(s, 30), ILC_COLOR32, 1, 0);
    ListView_SetImageList(list, spacer, LVSIL_SMALL);
    for (size_t i = 0; i < columns.size(); ++i)
    {
        LVCOLUMNW column{};
        column.mask = LVCF_TEXT | LVCF_WIDTH;
        column.pszText = (LPWSTR)columns[i].first.c_str();
        column.cx = px(s, columns[i].second);
        SendMessageW(list, LVM_INSERTCOLUMNW, WPARAM(i), (LPARAM)&column);
    }
    s.list_proc = (WNDPROC)SetWindowLongPtrW(list, GWLP_WNDPROC, (LONG_PTR)list_proc);
    return list;
}

void set_rows(HWND list, const std::vector<std::vector<std::wstring>>& rows, const std::vector<int>& tags)
{
    int selected = ListView_GetNextItem(list, -1, LVNI_SELECTED);
    std::wstring key;
    if (selected >= 0)
    {
        wchar_t buffer[256] = {};
        LVITEMW get{};
        get.iSubItem = 0;
        get.pszText = buffer;
        get.cchTextMax = 255;
        SendMessageW(list, LVM_GETITEMTEXTW, WPARAM(selected), (LPARAM)&get);
        key = buffer;
    }
    SendMessageW(list, WM_SETREDRAW, FALSE, 0);
    ListView_DeleteAllItems(list);
    for (size_t r = 0; r < rows.size(); ++r)
    {
        LVITEMW item{};
        item.mask = LVIF_TEXT | LVIF_PARAM;
        item.iItem = int(r);
        item.pszText = (LPWSTR)rows[r][0].c_str();
        item.lParam = tags[r];
        int index = int(SendMessageW(list, LVM_INSERTITEMW, 0, (LPARAM)&item));
        for (size_t c = 1; c < rows[r].size(); ++c)
        {
            LVITEMW cell{};
            cell.iSubItem = int(c);
            cell.pszText = (LPWSTR)rows[r][c].c_str();
            SendMessageW(list, LVM_SETITEMTEXTW, WPARAM(index), (LPARAM)&cell);
        }
        if (!key.empty() && rows[r][0] == key) ListView_SetItemState(list, index, LVIS_SELECTED, LVIS_SELECTED);
    }
    SendMessageW(list, WM_SETREDRAW, TRUE, 0);
    InvalidateRect(list, nullptr, TRUE);
}

bool operator==(const LocationRow& a, const LocationRow& b) { return a.id == b.id && a.state == b.state && a.address == b.address && a.players == b.players; }
bool operator==(const PlayerRow& a, const PlayerRow& b)
{
    return a.login == b.login && a.name == b.name && a.location == b.location && a.faction == b.faction && a.role == b.role && a.ping == b.ping && a.state == b.state;
}

void refresh_lists(State& s)
{
    View view;
    {
        std::lock_guard<std::mutex> guard(s.view_lock);
        if (!s.view) return;
        view = *s.view;
    }
    if (!(view.locations == s.shown_locations))
    {
        std::vector<std::vector<std::wstring>> rows;
        std::vector<int> tags;
        for (auto& l : view.locations)
        {
            rows.push_back({ l.name, widen(l.id), l.state, l.address, l.players ? std::to_wstring(l.players) : L"" });
            tags.push_back(l.online ? 1 : 0);
        }
        set_rows(s.locations, rows, tags);
        s.shown_locations = view.locations;
    }
    if (!(view.players == s.shown_players))
    {
        std::vector<std::vector<std::wstring>> rows;
        std::vector<int> tags;
        for (auto& p : view.players)
        {
            std::wstring role = p.role == "admin" ? L"Админ" : p.role == "leader" ? L"Лидер" : p.role == "player" ? L"Игрок" : p.role.empty() ? L"—" : widen(p.role);
            rows.push_back({ widen(p.login), p.name.empty() ? L"—" : widen(p.name), map_name(p.location), p.faction.empty() ? L"—" : widen(p.faction), role,
                             p.ping.empty() ? L"—" : widen(p.ping) + L" мс" });
            tags.push_back(p.state == "FROZEN" ? 3 : p.role == "admin" ? 2 : 1);
        }
        set_rows(s.players, rows, tags);
        s.shown_players = view.players;
    }
}

void drain_journal(State& s)
{
    std::vector<std::pair<std::string, std::string>> lines;
    {
        std::lock_guard<std::mutex> guard(s.lines_lock);
        lines.swap(s.lines);
    }
    for (auto& [stamp, line] : lines)
    {
        std::string low = lower(line);
        COLORREF color = C_TEXT;
        if (low.find("error") != std::string::npos || low.find("ошибк") != std::string::npos || low.find("остановлен:") != std::string::npos ||
            low.find("failed") != std::string::npos)
            color = C_RED;
        else if (line.rfind("[мир]", 0) == 0)
            color = C_ACCENT;
        append(s.journal, widen(stamp) + L"  ", C_DIM);
        append(s.journal, widen(line) + L"\r\n", color);
    }
}

void set_status(State& s, const std::string& t, COLORREF color)
{
    s.status_text = widen(t);
    s.status_color = color;
    InvalidateRect(s.hwnd, nullptr, FALSE);
}

void command(State& s, const std::string& line, const wchar_t* confirm = nullptr)
{
    if (confirm && MessageBoxW(s.hwnd, confirm, L"Lost Zone — мастер", MB_YESNO | MB_ICONQUESTION) != IDYES) return;
    if (!s.service || !s.service->running())
    {
        set_status(s, "Мастер не запущен.", C_RED);
        return;
    }
    std::string answer = s.service->console(line);
    bool failed = answer.rfind("Команда не выполнена", 0) == 0;
    append(s.output, L"master › " + widen(line) + L"\r\n", C_ACCENT);
    append(s.output, widen(answer) + L"\r\n", failed ? C_RED : C_TEXT);
    set_status(s, split(answer, '\n')[0], failed ? C_RED : C_GREEN);
}

void pause_host_launches(State& s, bool pause)
{
    if (s.options.roster_folder.empty()) return;
    const std::wstring path = s.options.roster_folder + L"\\host_master_paused.txt";
    if (pause)
    {
        CreateDirectoryW(s.options.roster_folder.c_str(), nullptr);
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        if (out) out << "paused\n";
        else log_line("Не удалось приостановить очередь запуска локаций.");
    }
    else DeleteFileW(path.c_str());
}

void start_service(State& s)
{
    std::lock_guard<std::mutex> guard(s.service_lock);
    try
    {
        s.service = std::make_unique<Service>(s.options.service);
        pause_host_launches(s, false);
        s.service_error.clear();
        s.started_ns = monotonic_ns();
    }
    catch (const std::exception& error)
    {
        s.service.reset();
        s.service_error = exception_type(error) + ": " + error.what();
        log_line("Мастер не запустился: " + s.service_error);
    }
}

void stop_service(State& s)
{
    std::lock_guard<std::mutex> guard(s.service_lock);
    if (s.service)
    {
        pause_host_launches(s, true);
        HCURSOR cursor = SetCursor(LoadCursor(nullptr, IDC_WAIT));
        s.service->stop();
        s.service.reset();
        {
            std::lock_guard<std::mutex> view(s.view_lock);
            s.view.reset();
        }
        SetCursor(cursor);
        log_line("Мастер остановлен, календарь сохранён.");
    }
}

// The selected rows of the Locations tab -> host commands.
std::vector<std::string> selected_maps(State& s)
{
    std::vector<std::string> maps;
    for (int i = ListView_GetNextItem(s.locations, -1, LVNI_SELECTED); i >= 0; i = ListView_GetNextItem(s.locations, i, LVNI_SELECTED))
        if (size_t(i) < s.shown_locations.size()) maps.push_back(s.shown_locations[size_t(i)].id);
    return maps;
}

void switch_locations(State& s, bool on, const std::vector<std::string>& maps)
{
    if (on && (!s.service || !s.service->running()))
    {
        set_status(s, "Сначала включите мастер, затем запускайте локации.", C_AMBER);
        return;
    }
    if (maps.empty())
    {
        set_status(s, "Выберите локации в списке (несколько - с Ctrl или Shift).", C_AMBER);
        return;
    }
    std::wstring names;
    for (auto& m : maps)
    {
        if (!names.empty()) names += L", ";
        names += map_name(m);
    }
    if (!on && MessageBoxW(s.hwnd, (L"Выключить: " + names + L"?\nКаждая сохранит мир перед выходом; игроков на ней выкинет в меню.").c_str(),
                           L"Lost Zone — мастер", MB_YESNO | MB_ICONQUESTION) != IDYES)
        return;
    std::vector<std::string> failed;
    for (auto& m : maps)
        if (!write_host_command(s.options.roster_folder, m, on ? "start" : "stop")) failed.push_back(m);
    bool managed = ensure_watchdog(s, read_host_view(s.options.roster_folder).fresh);
    log_line(std::string(on ? "Включение" : "Выключение") + " локаций: " + narrow(names));
    if (!failed.empty()) set_status(s, "Не удалось передать команду: " + failed.front(), C_RED);
    else if (!managed) set_status(s, "Команда записана, но управление хостера (hoster\\netcoop_cluster_watchdog.ps1) не найдено.", C_AMBER);
    else set_status(s, narrow((on ? L"Включаются: " : L"Выключаются (с сохранением мира): ") + names), C_GREEN);
}

void click(State& s, int id)
{
    if (id >= T_LOCATIONS && id <= T_CONSOLE)
    {
        s.tab = id - T_LOCATIONS;
        layout(s);
        if (s.tab == 3) SetFocus(s.input);
        InvalidateRect(s.hwnd, nullptr, FALSE);
        return;
    }
    switch (id)
    {
    case B_EMISSION: command(s, EMISSION_NOW, L"Начать выброс на всех локациях сейчас?"); break;
    case B_PSI: command(s, PSI_NOW, L"Начать пси-шторм на всех локациях сейчас?"); break;
    case B_WEATHER:
    case B_SPEED:
    {
        HMENU menu = CreatePopupMenu();
        if (id == B_WEATHER)
            for (size_t i = 0; i < WEATHER.size(); ++i) AppendMenuW(menu, MF_STRING, 1 + i, WEATHER[i].second.c_str());
        else
            for (int v : { 1, 2, 5, 10, 20, 50 })
                AppendMenuW(menu, MF_STRING, UINT_PTR(v), (L"×" + std::to_wstring(v) + (v == 10 ? L"  (как в GAMMA)" : L"")).c_str());
        RECT rc{};
        for (auto& b : s.buttons)
            if (b.id == id) rc = b.rc;
        POINT at{ rc.left, rc.bottom };
        ClientToScreen(s.hwnd, &at);
        int chosen = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_LEFTALIGN | TPM_TOPALIGN, at.x, at.y, 0, s.hwnd, nullptr);
        DestroyMenu(menu);
        if (!chosen) break;
        if (id == B_WEATHER)
        {
            std::string current = "clear";
            {
                std::lock_guard<std::mutex> guard(s.view_lock);
                if (s.view && s.view->weather.is_object()) current = s.view->weather["parameters"]["target"].get<std::string>();
            }
            command(s, "weather " + current + " " + WEATHER[size_t(chosen - 1)].first + " 600");
        }
        else
            command(s, "scale " + std::to_string(chosen));
        break;
    }
    case B_LOGS: ShellExecuteW(s.hwnd, L"open", s.options.log_folder.c_str(), nullptr, nullptr, SW_SHOWNORMAL); break;
    case B_LOC_ON: switch_locations(s, true, selected_maps(s)); break;
    case B_LOC_OFF: switch_locations(s, false, selected_maps(s)); break;
    case B_TOGGLE:
        if (s.service && s.service->running())
        {
            if (MessageBoxW(s.hwnd, L"Без мастера карты перестанут пускать игроков, погода и выбросы остановятся. Остановить мастер?",
                            L"Lost Zone — мастер", MB_YESNO | MB_ICONWARNING) == IDYES)
                stop_service(s);
        }
        else
            start_service(s);
        layout(s);
        InvalidateRect(s.hwnd, nullptr, FALSE);
        break;
    case B_RUN:
    {
        wchar_t buffer[300] = {};
        GetWindowTextW(s.input, buffer, 299);
        std::string line = trim(narrow(buffer));
        SetWindowTextW(s.input, L"");
        if (!line.empty()) command(s, line);
        break;
    }
    }
}

LRESULT CALLBACK input_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    State* s = g_state;
    if (s && message == WM_KEYDOWN && wparam == VK_RETURN)
    {
        click(*s, B_RUN);
        return 0;
    }
    if (s && message == WM_CHAR && wparam == VK_RETURN) return 0;
    return CallWindowProcW(s ? s->input_proc : DefWindowProcW, hwnd, message, wparam, lparam);
}

void finish_selftest(State& s, bool ok, const std::string& error)
{
    json result = s.selftest;
    result["ok"] = ok;
    if (!error.empty()) result["error"] = error;
    stop_service(s);
    result["stopped"] = !s.service;
    std::ofstream out(s.options.selftest, std::ios::binary);
    out << result.dump(1);
    s.closing = true;
    DestroyWindow(s.hwnd);
}

LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    State* s = g_state;
    switch (message)
    {
    case WM_CREATE:
    {
        s->hwnd = hwnd;
        BOOL dark = TRUE;
        DwmSetWindowAttribute(hwnd, 20, &dark, sizeof(dark));
        s->locations = make_list(*s, hwnd, { { L"ЛОКАЦИЯ", 240 }, { L"КАРТА", 200 }, { L"СОСТОЯНИЕ", 190 }, { L"АДРЕС", 180 }, { L"ИГРОКИ", 80 } }, true);
        s->players = make_list(*s, hwnd, { { L"ИГРОК", 160 }, { L"ПЕРСОНАЖ", 180 }, { L"ЛОКАЦИЯ", 200 }, { L"ФРАКЦИЯ", 130 }, { L"РОЛЬ", 90 }, { L"ПИНГ", 80 } });
        s->journal = make_rich(*s, hwnd);
        s->output = make_rich(*s, hwnd);
        append(s->output, L"help — список команд мастера. Остановка мастера — кнопкой сверху.\r\n", C_MUTED);
        s->input = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | ES_AUTOHSCROLL, 0, 0, 10, 10, hwnd, nullptr, GetModuleHandleW(nullptr), nullptr);
        SendMessageW(s->input, WM_SETFONT, (WPARAM)s->f_mono, TRUE);
        SendMessageW(s->input, EM_SETLIMITTEXT, 256, 0);
        s->input_proc = (WNDPROC)SetWindowLongPtrW(s->input, GWLP_WNDPROC, (LONG_PTR)input_proc);
        layout(*s);
        SetTimer(hwnd, 1, 1000, nullptr);
        SetTimer(hwnd, 2, 250, nullptr);
        return 0;
    }
    case WM_SIZE:
        layout(*s);
        InvalidateRect(hwnd, nullptr, FALSE);
        return 0;
    case WM_GETMINMAXINFO:
    {
        auto info = (MINMAXINFO*)lparam;
        info->ptMinTrackSize = { px(*s, 960), px(*s, 640) };
        return 0;
    }
    case WM_ERASEBKGND: return 1;
    case WM_PAINT:
    {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        paint(*s, dc);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_TIMER:
        if (wparam == 2)
        {
            drain_journal(*s);
            return 0;
        }
        refresh_lists(*s);
        layout(*s);
        InvalidateRect(hwnd, nullptr, FALSE);
        if (!s->options.selftest.empty())
        {
            bool have;
            View view;
            {
                std::lock_guard<std::mutex> guard(s->view_lock);
                have = s->view.has_value();
                if (have) view = *s->view;
            }
            if (!s->service) finish_selftest(*s, false, s->service_error.empty() ? "service stopped" : s->service_error);
            else if (have && view.ready)
            {
                std::string status = s->service->console("status");
                std::string refused = s->service->console("quit");
                const bool written = write_host_command(s->options.roster_folder, "k00_marsh", "start");
                std::ifstream command(s->options.roster_folder + L"\\host_command_k00_marsh.txt", std::ios::binary);
                std::string action((std::istreambuf_iterator<char>(command)), std::istreambuf_iterator<char>());
                s->selftest = { { "status", split(status, '\n')[0] }, { "quit", refused }, { "locations", view.locations.size() },
                                { "host_command", written && action == "start" },
                                { "calendar", calendar_text(view.world_ms) }, { "api_port", s->service->api_port() } };
                finish_selftest(*s, status.rfind("Мастер: готов", 0) == 0 && view.locations.size() >= 33 && written && action == "start", "");
            }
            else if ((monotonic_ns() - s->started_ns) > 90000000000LL)
                finish_selftest(*s, false, "timeout");
        }
        return 0;
    case WM_MOUSEMOVE:
    {
        POINT at{ GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam) };
        int hover = -1;
        for (auto* list : { &s->buttons, &s->tabs })
            for (auto& b : *list)
                if (PtInRect(&b.rc, at)) hover = b.id;
        if (hover != s->hover)
        {
            s->hover = hover;
            InvalidateRect(hwnd, nullptr, FALSE);
            TRACKMOUSEEVENT track{ sizeof(track), TME_LEAVE, hwnd, 0 };
            TrackMouseEvent(&track);
        }
        SetCursor(LoadCursor(nullptr, hover >= 0 ? IDC_HAND : IDC_ARROW));
        return 0;
    }
    case WM_MOUSELEAVE:
        s->hover = -1;
        InvalidateRect(hwnd, nullptr, FALSE);
        return 0;
    case WM_LBUTTONUP:
    {
        POINT at{ GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam) };
        for (auto* list : { &s->buttons, &s->tabs })
            for (auto& b : *list)
                if (PtInRect(&b.rc, at))
                {
                    click(*s, b.id);
                    return 0;
                }
        return 0;
    }
    case WM_NOTIFY:
    {
        auto header = (LPNMHDR)lparam;
        if (header->code == NM_CUSTOMDRAW && (header->hwndFrom == s->locations || header->hwndFrom == s->players))
        {
            auto draw = (LPNMLVCUSTOMDRAW)lparam;
            if (draw->nmcd.dwDrawStage == CDDS_PREPAINT) return CDRF_NOTIFYITEMDRAW;
            if (draw->nmcd.dwDrawStage == CDDS_ITEMPREPAINT)
            {
                int tag = int(draw->nmcd.lItemlParam);
                bool selected = ListView_GetItemState(header->hwndFrom, int(draw->nmcd.dwItemSpec), LVIS_SELECTED) != 0;
                COLORREF color = header->hwndFrom == s->locations ? (tag ? C_GREEN : C_DIM) : (tag == 2 ? C_ACCENT : tag == 3 ? C_AMBER : C_TEXT);
                draw->clrText = selected ? C_ACCENT : color;
                draw->clrTextBk = selected ? C_HOVER : C_SURFACE;
                draw->nmcd.uItemState &= ~(CDIS_SELECTED | CDIS_FOCUS);
                return CDRF_NEWFONT;
            }
        }
        return 0;
    }
    case WM_CTLCOLOREDIT:
    {
        static HBRUSH brush = CreateSolidBrush(C_RAISED);
        SetTextColor((HDC)wparam, C_TEXT);
        SetBkColor((HDC)wparam, C_RAISED);
        return (LRESULT)brush;
    }
    case WM_CLOSE:
        if (s->service && s->service->running() && s->options.selftest.empty() &&
            MessageBoxW(hwnd, L"Закрыть окно и остановить мастер? Карты перестанут пускать игроков.", L"Lost Zone — мастер",
                        MB_YESNO | MB_ICONWARNING) != IDYES)
            return 0;
        s->closing = true;
        stop_service(*s);
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}
} // namespace

void window_journal(const std::string& line)
{
    std::lock_guard<std::mutex> guard(g_state_lock);
    if (!g_state) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    std::lock_guard<std::mutex> lines(g_state->lines_lock);
    if (g_state->lines.size() < 20000) g_state->lines.push_back({ format("%02d:%02d:%02d", t.wHour, t.wMinute, t.wSecond), line });
}

int run_window(const WindowOptions& options)
{
    LoadLibraryW(L"Msftedit.dll");
    INITCOMMONCONTROLSEX controls{ sizeof(controls), ICC_LISTVIEW_CLASSES };
    InitCommonControlsEx(&controls);
    auto state = std::make_unique<State>();
    state->options = options;
    UINT dpi = 96;
    if (auto user32 = GetModuleHandleW(L"user32.dll"))
        if (auto get = (UINT(WINAPI*)())GetProcAddress(user32, "GetDpiForSystem")) dpi = get();
    state->dpi = float(dpi) / 96.0f;
    const wchar_t* ui = L"Segoe UI";
    const wchar_t* head = font_exists(L"Bahnschrift") ? L"Bahnschrift SemiBold" : ui;
    state->f_ui = make_font(*state, ui, 10, FW_NORMAL);
    state->f_small = make_font(*state, ui, 9, FW_NORMAL);
    state->f_bold = make_font(*state, ui, 10, FW_SEMIBOLD);
    state->f_title = make_font(*state, head, 22, FW_SEMIBOLD);
    state->f_value = make_font(*state, head, 15, FW_SEMIBOLD);
    state->f_mono = make_font(*state, font_exists(L"Cascadia Mono") ? L"Cascadia Mono" : L"Consolas", 10, FW_NORMAL);
    {
        std::lock_guard<std::mutex> guard(g_state_lock);
        g_state = state.get();
    }
    start_service(*state);
    state->started_ns = monotonic_ns();
    state->poller = std::thread(poll, state.get());

    WNDCLASSEXW wc{ sizeof(wc) };
    wc.lpfnWndProc = window_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = CreateSolidBrush(C_BG);
    wc.lpszClassName = L"LostZoneMasterWindow";
    wc.hIcon = LoadIconW(GetModuleHandleW(nullptr), MAKEINTRESOURCEW(1));
    if (!wc.hIcon) wc.hIcon = LoadIcon(nullptr, IDI_APPLICATION);
    RegisterClassExW(&wc);
    HWND hwnd = CreateWindowExW(0, wc.lpszClassName, L"Lost Zone — мастер мира", WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
                                px(*state, 1180), px(*state, 800), nullptr, nullptr, wc.hInstance, nullptr);
    ShowWindow(hwnd, options.selftest.empty() ? SW_SHOWNORMAL : SW_SHOWNOACTIVATE);
    UpdateWindow(hwnd);
    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0)
    {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    state->closing = true;
    if (state->poller.joinable()) state->poller.join();
    stop_service(*state);
    {
        std::lock_guard<std::mutex> guard(g_state_lock);
        g_state = nullptr;
    }
    return 0;
}
} // namespace lzm
