"""CI-only native test: level-transition & server-restart lifecycle fixes.

Compiles and runs real production slices from:
- src/xrGame/Level.cpp (StopPrefetchThread + ProcessPrefetchEvents joinable worker & heap reuse)
- src/xrGame/Level_network_spawn.cpp (netcoop_client_start_game per-CLevel ABA fix)
- src/xrGame/xrServer_CL_connect.cpp (server_host_ready, netcoop_join_pump, Perform_connect_spawn)
- src/xrGame/netcoop_world_store.inc (world_store_cleanup_loaded online->offline switch before release)
Also verifies structural invariants across ModelPool.cpp, Level_network.cpp, alife_simulator.cpp,
alife_dynamic_object.cpp, and alife_trader_abstract.cpp.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks must run in GitHub Actions")

root = Path(__file__).resolve().parents[1]

# Structural invariants on renderer, teardown, and ALife online/offline switches
model_pool = (root / "src/Layers/xrRender/ModelPool.cpp").read_text(encoding="utf-8", errors="replace")
create_slice = model_pool[model_pool.index("dxRender_Visual* CModelPool::Create("):model_pool.index("dxRender_Visual* CModelPool::CreateChild(")]
assert "bAllowChildrenDuplicate = TRUE;\n\t\t\treturn nullptr;" in create_slice or (
    create_slice.index("bAllowChildrenDuplicate = TRUE;") < create_slice.index("return nullptr;")
), "ModelPool::Create must restore bAllowChildrenDuplicate before returning nullptr on missing model"

level_net = (root / "src/xrGame/Level_network.cpp").read_text(encoding="utf-8", errors="replace")
net_stop = level_net[level_net.index("void CLevel::net_Stop()"):level_net.index("void CLevel::ClientSend(")]
igame_stop = net_stop.index("IGame_Level::net_Stop();")
for pre_reset in ("StopPrefetchThread();", "netcoop::client_voice_reset();", "netcoop::client_vehicle_sounds_reset();", "netcoop::lua_functors_reset();"):
    assert pre_reset in net_stop and net_stop.index(pre_reset) < igame_stop, f"{pre_reset} must run before IGame_Level::net_Stop()"
for post_reset in ("netcoop::items_reset();", "netcoop::pda_reset();", "netcoop::marks_reset();", "netcoop::client_map_positions_reset();", "netcoop::client_session_reset();"):
    assert post_reset in net_stop and net_stop.index(post_reset) > igame_stop, f"{post_reset} must run in CLevel::net_Stop()"

alife_sim = (root / "src/xrGame/alife_simulator.cpp").read_text(encoding="utf-8", errors="replace")
assert "netcoop::world_store_cleanup_loaded();" in alife_sim

alife_do = (root / "src/xrGame/alife_dynamic_object.cpp").read_text(encoding="utf-8", errors="replace")
box_online = alife_do[alife_do.index("void CSE_ALifeInventoryBox::add_online("):alife_do.index("void CSE_ALifeInventoryBox::add_offline(")]
box_offline = alife_do[alife_do.index("void CSE_ALifeInventoryBox::add_offline("):]
assert "objects().object(*I, true)" in box_online
assert "--i;" not in box_offline and "--n;" not in box_offline

alife_tr = (root / "src/xrGame/alife_trader_abstract.cpp").read_text(encoding="utf-8", errors="replace")
tr_online = alife_tr[alife_tr.index("void add_online_impl("):alife_tr.index("void CSE_ALifeTraderAbstract::add_online(")]
assert "objects().object(*I, true)" in tr_online

# Slice production C++ functions for ASan/UBSan + MSVC native execution
level_cpp = (root / "src/xrGame/Level.cpp").read_text(encoding="utf-8", errors="replace")
assert "static HANDLE prefetch_thread_signal" not in level_cpp
assert "!g_dedicated_server && !netcoop::enabled()" in level_cpp
prefetch_slice = level_cpp[
    level_cpp.index("void CLevel::StopPrefetchThread()"):
    level_cpp.index("// demonized: If called manually, be aware of ProcessPrefetchEvents thread, which may modify spawn_events queue at the same time, maybe fix later\nvoid CLevel::ProcessSpawnEvents()")
]

spawn_cpp = (root / "src/xrGame/Level_network_spawn.cpp").read_text(encoding="utf-8", errors="replace")
start_game_slice = spawn_cpp[
    spawn_cpp.index("static void netcoop_client_start_game(CLevel* level)"):
    spawn_cpp.index("void CLevel::cl_Process_Spawn(")
]

cl_connect_cpp = (root / "src/xrGame/xrServer_CL_connect.cpp").read_text(encoding="utf-8", errors="replace")
join_slice = cl_connect_cpp[
    cl_connect_cpp.index("static const u32 join_slots"):
    cl_connect_cpp.index("void xrServer::SendConfigFinished(")
]
on_connected_slice = cl_connect_cpp[
    cl_connect_cpp.index("void xrServer::OnCL_Connected(IClient* _CL)"):
    cl_connect_cpp.index("void xrServer::SendConnectResult(")
]

world_store = (root / "src/xrGame/netcoop_world_store.inc").read_text(encoding="utf-8", errors="replace")
cleanup_slice = world_store[
    world_store.index("bool world_store_cleanup_pending()"):
    world_store.index("bool world_store_save_now(")
]
admission_open_slice = world_store[
    world_store.index("bool world_store_admission_open()"):
    world_store.index("static void world_store_update(")
]

source = r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <Condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <new>
#include <set>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
#include <algorithm>

using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using LPCSTR = const char*;
using BOOL = int;
using string64 = char[64];
constexpr BOOL TRUE = 1;
constexpr BOOL FALSE = 0;

void Msg(const char*, ...) {}
void FlushLog() {}
#define VERIFY2(cond, msg) assert(cond)
#define PROF_EVENT(name)

template <class T> using xr_vector = std::vector<T>;
template <class K, class V> using xr_map = std::map<K, V>;
template <class K, class V> using xr_unordered_map = std::unordered_map<K, V>;
template <class T> using xr_set = std::set<T>;

struct HandleObj {
    enum Kind { Event, Thread } kind;
    std::mutex mtx;
    std::condition_variable cv;
    bool signaled = false;
    std::thread thr;
    explicit HandleObj(Kind k) : kind(k) {}
};
using HANDLE = HandleObj*;
constexpr u32 INFINITE = 0xFFFFFFFFu;

HANDLE CreateManualEvent() { return new HandleObj(HandleObj::Event); }
void SetEvent(HANDLE h) {
    std::lock_guard<std::mutex> lk(h->mtx);
    h->signaled = true;
    h->cv.notify_all();
}
void ResetEvent(HANDLE h) {
    std::lock_guard<std::mutex> lk(h->mtx);
    h->signaled = false;
}
void WaitForSingleObject(HANDLE h, u32) {
    if (h->kind == HandleObj::Thread) {
        if (h->thr.joinable()) h->thr.join();
        return;
    }
    std::unique_lock<std::mutex> lk(h->mtx);
    h->cv.wait(lk, [&] { return h->signaled; });
}
void CloseHandle(HANDLE h) {
    if (h->kind == HandleObj::Thread && h->thr.joinable()) h->thr.join();
    delete h;
}
HANDLE SpawnWorker(void (*fn)(void*), void* arg) {
    auto* h = new HandleObj(HandleObj::Thread);
    h->thr = std::thread(fn, arg);
    return h;
}

struct xrSRWLock { std::shared_mutex m; };
struct xrSRWLockGuard {
    std::shared_mutex& m;
    bool shared;
    xrSRWLockGuard(xrSRWLock& l, bool s = false) : m(l.m), shared(s) {
        if (shared) m.lock_shared(); else m.lock();
    }
    xrSRWLockGuard(xrSRWLock* l, bool s = false) : m(l->m), shared(s) {
        if (shared) m.lock_shared(); else m.lock();
    }
    ~xrSRWLockGuard() {
        if (shared) m.unlock_shared(); else m.unlock();
    }
};

struct RenderMock {
    std::atomic<u32> prefetched{0};
    void models_PrefetchOne(const char*, bool) {
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
        prefetched.fetch_add(1, std::memory_order_relaxed);
    }
} render_mock, *Render = &render_mock;

int spawn_antifreeze_debug = 0;

struct NET_Event { u16 id = 0; };
struct NET_Queue_Event {
    xr_vector<NET_Event> queue;
    void insert(const NET_Event& e) { queue.push_back(e); }
};
struct prefetch_event {
    u16 id = 0;
    NET_Event p;
    xr_vector<std::string> models;
};
using prefetch_event_queue = std::deque<prefetch_event>;
using spawn_events_data_map = xr_unordered_map<u16, prefetch_event>;

struct CoreMock { const char* Params = "-netcoop -netcoop_world=zone"; } Core;
struct DeviceMock { u32 dwTimeGlobal = 1000; } Device;
struct CTimer { void Start() {} u32 GetElapsed_ms() const { return 1; } };

unsigned start_game_calls = 0;
namespace luabind {
template <class R> struct functor {
    void operator()() const { ++start_game_calls; }
};
}
struct SettingsMock {
    LPCSTR r_string(LPCSTR, LPCSTR) const { return "_G.start_game_callback"; }
} settings_mock, *pSettings = &settings_mock;

struct ScriptEngineMock {
    template <class F> bool functor(LPCSTR, F&) const { return true; }
};

struct CSE_Abstract;
struct xrClientData;
struct NET_Packet;

constexpr u16 M_SPAWN_OBJECT_PHANTOM = 1 << 0;
constexpr u16 M_SPAWN_OBJECT_ASPLAYER = 1 << 1;
constexpr u16 M_SPAWN_UPDATE = 1 << 2;

struct Flags16 {
    u16 flags = 0;
    void set(u16 mask, BOOL val) { if (val) flags |= mask; else flags &= u16(~mask); }
    BOOL is(u16 mask) const { return (flags & mask) != 0; }
};

struct CSE_Abstract {
    u16 ID = 0;
    u16 ID_Parent = 0xffff;
    BOOL net_Processed = FALSE;
    Flags16 s_flags;
    xrClientData* owner = nullptr;
    std::string name_replace;
    virtual ~CSE_Abstract() = default;
    void set_name_replace(LPCSTR s) { name_replace = s ? s : ""; }
    void Spawn_Write(NET_Packet&, BOOL local);
    void UPDATE_Write(NET_Packet&) {}
};

struct CSE_ALifeObject : CSE_Abstract {
    xr_vector<u8> client_data;
    bool keep_data = false;
    bool keep_saved_data_anyway() const { return keep_data; }
};

struct CSE_ALifeDynamicObject : CSE_ALifeObject {
    bool m_bOnline = false;
    xr_vector<u16> children;
};

struct CSE_ALifeCreatureActor : CSE_ALifeDynamicObject {
    float health = 1.0f;
    float get_health() const { return health; }
};

template <class T, class U> T smart_cast(U* p) { return dynamic_cast<T>(p); }

struct NET_Packet {
    struct Buf { u32 count = 0; } B;
    xr_vector<BOOL> local_writes;
};
void CSE_Abstract::Spawn_Write(NET_Packet& P, BOOL local) {
    P.B.count = 16;
    P.local_writes.push_back(local);
}
int net_flags(BOOL, BOOL) { return 0; }

struct ClientID {
    u32 id = 0;
    void set(u32 v) { id = v; }
    u32 value() const { return id; }
    bool operator==(const ClientID& o) const { return id == o.id; }
};

struct game_PlayerState {
    std::string name = "player";
    LPCSTR getName() const { return name.c_str(); }
};

struct IClient {
    ClientID ID;
    u32 process_id = 0;
    virtual ~IClient() = default;
};

struct xrClientData : IClient {
    CSE_Abstract* owner = nullptr;
    game_PlayerState* ps = nullptr;
    BOOL net_ConnectionDataRequested = TRUE;
    BOOL net_Accepted = FALSE;
    unsigned clear_inputs = 0;
    void ClearInputState() { ++clear_inputs; }
};

struct GameSvMock {
    xr_vector<u32> connected;
    void OnPlayerConnect(ClientID id) { connected.push_back(id.value()); }
};

struct CActor {};
CActor* g_test_actor = nullptr;
CActor* Actor() { return g_test_actor; }

struct CLevel {
    bool m_netcoop_game_started = false;
    void* Server = nullptr;
    void* game = nullptr;

    xrSRWLock prefetch_lock;
    HANDLE prefetch_signal = nullptr;
    void* prefetch_worker = nullptr;
    std::atomic<bool> closeSignal{false};
    NET_Queue_Event* spawn_events = nullptr;
    spawn_events_data_map* spawn_events_data = nullptr;
    prefetch_event_queue* prefetch_events = nullptr;
    xr_set<std::string>* prefetched_models = nullptr;

    struct spawn_and_prefetch_events {
        NET_Queue_Event* spawn_events;
        spawn_events_data_map* spawn_events_data;
        prefetch_event_queue* prefetch_events;
        xr_set<std::string>* prefetched_models;
        std::atomic<bool>* closeSignal;
        xrSRWLock* prefetch_lock;
        HANDLE signal;
    };

    CLevel() {
        spawn_events = new NET_Queue_Event();
        spawn_events_data = new spawn_events_data_map();
        prefetch_events = new prefetch_event_queue();
        prefetched_models = new xr_set<std::string>();
    }
    void StartPrefetchThread() {
        prefetch_signal = CreateManualEvent();
        auto* args = new spawn_and_prefetch_events{
            spawn_events, spawn_events_data, prefetch_events, prefetched_models,
            &closeSignal, &prefetch_lock, prefetch_signal
        };
        prefetch_worker = SpawnWorker(ProcessPrefetchEvents, args);
    }
    ~CLevel() {
        StopPrefetchThread();
        delete spawn_events;
        delete spawn_events_data;
        delete prefetch_events;
        delete prefetched_models;
    }
    void StopPrefetchThread();
    static void ProcessPrefetchEvents(void* args);
};

CLevel* g_pGameLevel = nullptr;

struct GraphMock {
    CSE_ALifeCreatureActor* story = nullptr;
    CSE_ALifeCreatureActor* actor() const { return story; }
};
struct ObjectRegistryMock {
    xr_map<u16, CSE_ALifeDynamicObject*> map;
    const xr_map<u16, CSE_ALifeDynamicObject*>& objects() const { return map; }
};
struct CALifeSimulator {
    GraphMock g;
    ObjectRegistryMock reg;
    xr_vector<u16> switched_offline;
    xr_vector<u16> released;
    const GraphMock& graph() const { return g; }
    const ObjectRegistryMock& objects() const { return reg; }
    void switch_offline(CSE_ALifeDynamicObject* obj) {
        assert(obj->m_bOnline);
        obj->m_bOnline = false;
        switched_offline.push_back(obj->ID);
    }
    void release(CSE_ALifeDynamicObject* obj, bool) {
        // Must NEVER be called while obj->m_bOnline is still true!
        assert(!obj->m_bOnline);
        released.push_back(obj->ID);
        reg.map.erase(obj->ID);
    }
};

struct AIMock {
    CALifeSimulator* sim = nullptr;
    ScriptEngineMock se;
    const CALifeSimulator* get_alife() const { return sim; }
    const ScriptEngineMock& script_engine() const { return se; }
} ai_mock;
AIMock& ai() { return ai_mock; }

namespace netcoop {
static bool s_world_cleanup_pending = false;
static bool s_world_committed = true;
static bool world_store_name(string64& out) {
    std::snprintf(out, sizeof(out), "zone");
    return true;
}
__CLEANUP_SLICE__
__ADMISSION_OPEN_SLICE__
} // namespace netcoop

struct xrServer {
    xrClientData* SV_Client = nullptr;
    xr_map<u32, xrClientData*> clients;
    xr_map<u16, CSE_Abstract*> entities;
    xr_vector<u16> conn_spawned_ids;
    xr_vector<std::pair<u32, NET_Packet>> sent;
    GameSvMock game_inst;
    GameSvMock* game = &game_inst;

    xrClientData* GetServerClient() const { return SV_Client; }
    IClient* ID_to_client(ClientID id) const {
        auto it = clients.find(id.value());
        return it == clients.end() ? nullptr : it->second;
    }
    CSE_Abstract* ID_to_entity(u16 id) const {
        auto it = entities.find(id);
        return it == entities.end() ? nullptr : it->second;
    }
    void SendTo(ClientID id, NET_Packet& P, int = 0) { sent.emplace_back(id.value(), P); }
    void Export_game_type(IClient*) {}
    void Perform_game_export() {}
    void SendConfigFinished(ClientID const&) {}
    void SendConnectionData(IClient* _CL) {
        conn_spawned_ids.clear();
        auto* CL = static_cast<xrClientData*>(_CL);
        NET_Packet P;
        for (auto& kv : entities) kv.second->net_Processed = FALSE;
        for (auto& kv : entities) Perform_connect_spawn(kv.second, CL, P);
    }
    void Perform_connect_spawn(CSE_Abstract* E, xrClientData* CL, NET_Packet& P);
    void OnCL_Connected(IClient* _CL);
};

__PREFETCH_SLICE__
__START_GAME_SLICE__
__JOIN_SLICE__
__ON_CONNECTED_SLICE__

int main() {
    // 1. SPAWN_ANTIFREEZE joinable worker + heap reuse at identical CLevel* address
    alignas(CLevel) unsigned char level_storage[sizeof(CLevel)];
    for (int round = 0; round < 3; ++round) {
        CLevel* lvl = new (level_storage) CLevel();
        lvl->StartPrefetchThread();
        {
            xrSRWLockGuard g(lvl->prefetch_lock);
            prefetch_event ev;
            ev.id = u16(100 + round);
            ev.models = {"actors\\stalker_hero\\stalker_hero_1.ogf", "weapons\\ak74\\wpn_ak74.ogf"};
            lvl->prefetch_events->push_back(ev);
        }
        SetEvent(lvl->prefetch_signal);
        std::this_thread::sleep_for(std::chrono::milliseconds(3));
        // Destroy while worker may be mid-prefetch or idle, then immediately reuse same address
        lvl->StopPrefetchThread();
        lvl->~CLevel();
    }
    assert(render_mock.prefetched.load() >= 1);

    // 2. netcoop_client_start_game ABA regression: placement-new two CLevels at the exact same address
    ai_mock.sim = nullptr;
    start_game_calls = 0;
    int dummy_game = 1;
    CLevel* first_level = new (level_storage) CLevel();
    first_level->game = &dummy_game;
    netcoop_client_start_game(first_level);
    netcoop_client_start_game(first_level); // second spawn on same level must not re-run
    assert(start_game_calls == 1);
    first_level->~CLevel();

    CLevel* second_level = new (level_storage) CLevel();
    assert(second_level == first_level); // exact ABA address match!
    second_level->game = &dummy_game;
    netcoop_client_start_game(second_level);
    assert(start_game_calls == 2); // must fire for the new level despite identical pointer!

    // 3. world_store_cleanup_loaded: switches online saved player Actors offline BEFORE release()
    CALifeSimulator sim;
    CSE_ALifeCreatureActor story_actor;
    story_actor.ID = 0;
    story_actor.m_bOnline = true;
    CSE_ALifeCreatureActor stale_online_player;
    stale_online_player.ID = 42;
    stale_online_player.m_bOnline = true;
    stale_online_player.health = 0.9f;
    CSE_ALifeCreatureActor dead_player_corpse;
    dead_player_corpse.ID = 43;
    dead_player_corpse.m_bOnline = true;
    dead_player_corpse.health = 0.0f;

    sim.g.story = &story_actor;
    sim.reg.map[0] = &story_actor;
    sim.reg.map[42] = &stale_online_player;
    sim.reg.map[43] = &dead_player_corpse;
    ai_mock.sim = &sim;

    netcoop::s_world_cleanup_pending = true;
    assert(!netcoop::world_store_admission_open());
    netcoop::world_store_cleanup_loaded();
    assert(!netcoop::world_store_cleanup_pending());
    assert(netcoop::world_store_admission_open());
    assert(sim.switched_offline.size() == 1 && sim.switched_offline[0] == 42);
    assert(sim.released.size() == 1 && sim.released[0] == 42);
    assert(sim.reg.map.count(0) == 1 && sim.reg.map.count(43) == 1);

    // 4. Server-restart join race: remote client arrives BEFORE SV_Client owns story actor
    xrServer srv;
    g_pGameLevel = second_level;
    g_test_actor = nullptr;

    CSE_ALifeCreatureActor world_actor;
    world_actor.ID = 0;
    world_actor.s_flags.set(M_SPAWN_OBJECT_ASPLAYER, TRUE);
    world_actor.client_data = {1, 2, 3, 4};

    CSE_ALifeObject stash_box;
    stash_box.ID = 10;
    stash_box.client_data = {9, 8, 7};

    srv.entities[0] = &world_actor;
    srv.entities[10] = &stash_box;

    game_PlayerState host_ps{"host"}, remote_ps{"itzrealme"};
    xrClientData host_cl, remote_cl;
    host_cl.ID.set(1); host_cl.ps = &host_ps;
    remote_cl.ID.set(2); remote_cl.ps = &remote_ps;
    srv.SV_Client = &host_cl;
    srv.clients[1] = &host_cl;
    srv.clients[2] = &remote_cl;

    // Remote client finishes auth skipped check FIRST while host_cl is not yet accepted and Actor() is null!
    srv.OnCL_Connected(&remote_cl);
    assert(!remote_cl.net_Accepted);
    assert(world_actor.owner == nullptr && stash_box.owner == nullptr);
    assert(world_actor.client_data.size() == 4 && stash_box.client_data.size() == 3);

    // Pump while host still not ready -> remote stays queued
    netcoop_join_pump(&srv);
    assert(!remote_cl.net_Accepted);

    // Even if Perform_connect_spawn were called directly for remote_cl on unowned entities, remote_cl cannot claim ownership
    {
        NET_Packet tmp;
        for (auto& kv : srv.entities) kv.second->net_Processed = FALSE;
        srv.conn_spawned_ids.clear();
        srv.Perform_connect_spawn(&world_actor, &remote_cl, tmp);
        assert(world_actor.owner == nullptr && remote_cl.owner == nullptr);
        assert(world_actor.client_data.size() == 4);
    }

    // Now local SV_Client connects and spawns Actor()
    srv.OnCL_Connected(&host_cl);
    assert(host_cl.net_Accepted);
    assert(host_cl.owner == &world_actor && world_actor.owner == &host_cl && stash_box.owner == &host_cl);
    assert(world_actor.client_data.empty() && stash_box.client_data.empty());

    CActor spawned_host_actor;
    g_test_actor = &spawned_host_actor;

    // Nextserver tick pumps remote_cl cleanly without stealing host entities
    netcoop_join_pump(&srv);
    assert(remote_cl.net_Accepted);
    assert(host_cl.owner == &world_actor && world_actor.owner == &host_cl);
    assert(remote_cl.owner == nullptr);
    assert(srv.game_inst.connected.size() == 2 && srv.game_inst.connected[0] == 1 && srv.game_inst.connected[1] == 2);

    g_pGameLevel = nullptr;
    second_level->~CLevel();

    std::puts("PASS native session lifecycle: joinable SPAWN_ANTIFREEZE heap reuse, CLevel ABA start_game_callback, offline switch before world_store release, and SV_Client boot join ordering");
    return 0;
}
'''

source = (
    source.replace("Condition_variable", "condition_variable")
    .replace("__CLEANUP_SLICE__", cleanup_slice)
    .replace("__ADMISSION_OPEN_SLICE__", admission_open_slice)
    .replace("__PREFETCH_SLICE__", prefetch_slice)
    .replace("__START_GAME_SLICE__", start_game_slice)
    .replace("__JOIN_SLICE__", join_slice)
    .replace("__ON_CONNECTED_SLICE__", on_connected_slice)
)

with TemporaryDirectory() as tmp:
    cpp = Path(tmp) / "session_lifecycle.cpp"
    exe = Path(tmp) / ("session_lifecycle.exe" if os.name == "nt" else "session_lifecycle")
    cpp.write_text(source, encoding="utf-8")
    command = (
        ["cl", "/nologo", "/utf-8", "/std:c++17", "/EHsc", "/W4", "/WX", "/wd4127", "/wd4458", str(cpp), "/Fe:" + str(exe)]
        if os.name == "nt"
        else [
            "g++", "-std=c++17", "-pthread", "-Wall", "-Wextra", "-Wshadow", "-Wno-shadow=compatible-local", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
            str(cpp), "-o", str(exe),
        ]
    )
    subprocess.run(command, cwd=tmp, check=True)
    subprocess.run([str(exe)], cwd=tmp, check=True)
