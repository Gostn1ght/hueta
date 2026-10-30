// Compiled only in the GitHub test executable, never into the game project.
#ifdef LZM_TEST_FIXTURES
#include "lzm_world_files.h"
#include "lzm_world.h"
#include "lzm_host.h"
#include <cassert>
#include <cstdio>

static void put_file(const std::filesystem::path& path,const std::string& bytes) {
    std::filesystem::create_directories(path.parent_path());std::ofstream out(path,std::ios::binary);out<<bytes;assert(out.good());
}
static std::string get_file(const std::filesystem::path& path) {
    std::ifstream in(path,std::ios::binary);std::ostringstream text;text<<in.rdbuf();return text.str();
}
static uint64_t fixture_fnv(const std::string& bytes) {uint64_t hash=14695981039346656037ULL;for(unsigned char c:bytes) {hash^=c;hash*=1099511628211ULL;}return hash;}
static std::string fixture_pointer(const std::string& slot,const std::string& engine,const std::string& lua) {
    return lzm::format("%s\nLZW3 %llu %llx %llu %llx\n",slot.c_str(),(unsigned long long)engine.size(),(unsigned long long)fixture_fnv(engine),
        (unsigned long long)lua.size(),(unsigned long long)fixture_fnv(lua));
}
static void wait_storage(lzm::WorldFiles& files) {
    const auto deadline=GetTickCount64()+20000;
    while(!files.ready() && GetTickCount64()<deadline) Sleep(25);
    assert(files.ready());
}
int lzm_storage_fixture(const std::wstring& folder) {
    using namespace lzm;
    const std::filesystem::path root(folder),legacy=root/L"appdata/server/savedgames",pending=root/L"appdata/master/pending/worlds";
    assert(!std::filesystem::exists(root));std::filesystem::create_directories(root);
    const auto plan=root/L"cluster.ltx";put_file(plan,"[locations]\nk00_marsh=127.0.0.1:45671\n");
    Store store((root/L"world.sqlite").wstring());World world(store,71,9,1000,10);
    std::string engine1(2*1024*1024+17,'A');engine1[3]=char(255);const std::string lua1="Lua-sidecar-one";
    put_file(legacy/L"zone_a.scop",engine1);put_file(legacy/L"zone_a.scoc",lua1);put_file(legacy/L"zone.current",fixture_pointer("zone_a",engine1,lua1));
    {WorldFiles files(store,folder,plan.wstring());wait_storage(files);assert(store.db.scalar("SELECT COUNT(*) FROM master_world_head")==1);}
    assert(get_file(pending/L"zone_a.scop")==engine1);
    assert(get_file(legacy/L"zone_a.scop")==engine1); // retained source backup
    // Same pointer but a damaged working file must be restored from SQLite.
    put_file(pending/L"zone_a.scop","damaged");
    {WorldFiles files(store,folder,plan.wstring());wait_storage(files);}
    assert(get_file(pending/L"zone_a.scop")==engine1);
    const std::string engine2="second engine snapshot",lua2="second Lua sidecar";
    put_file(pending/L"zone_b.scop",engine2);put_file(pending/L"zone_b.scoc",lua2);put_file(pending/L"zone.current",fixture_pointer("zone_b",engine2,lua2));
    {WorldFiles files(store,folder,plan.wstring());wait_storage(files);}
    assert(store.db.scalar("SELECT COUNT(*) FROM master_world_revision WHERE complete=1")==2);
    // Missing cache cannot make the retained old legacy world win over the DB.
    for(const auto& entry:std::filesystem::directory_iterator(pending)) if(entry.path().filename()!=L"_authority.json") std::filesystem::remove(entry.path());
    {WorldFiles files(store,folder,plan.wstring());wait_storage(files);}
    assert(get_file(pending/L"zone_b.scop")==engine2 && get_file(pending/L"zone_b.scoc")==lua2);
    assert(get_file(pending/L"zone.current")==fixture_pointer("zone_b",engine2,lua2));
    // Half-written new capture: retain the previous head and recover its pair.
    put_file(pending/L"zone_a.scop","third");put_file(pending/L"zone_a.scoc","wrong-sidecar");
    put_file(pending/L"zone.current",fixture_pointer("zone_a","third","expected-sidecar"));
    {WorldFiles files(store,folder,plan.wstring());wait_storage(files);}
    assert(get_file(pending/L"zone.current")==fixture_pointer("zone_b",engine2,lua2));
    assert(store.db.scalar("SELECT COUNT(*) FROM master_world_revision WHERE complete=0")==0);
    assert(store.db.scalar("SELECT COUNT(*) FROM master_world_part WHERE capture NOT IN (SELECT id FROM master_world_revision)")==0);
    puts("PASS actual native world storage: WAL SQLite BLOB chunks, coherent engine/Lua/pointer commit, restart, cache corruption repair, pending capture replay, old-backup protection, partial rollback");
    return 0;
}

namespace lzm {
struct HostControllerFixture {
    static int run(const std::wstring& root) {
        assert(!std::filesystem::exists(root));std::filesystem::create_directories(root);
        const auto plan=root+L"\\plan.ltx";
        put_file(plan,"[locations]\nk00_marsh=127.0.0.1:45671\nl01_escape=127.0.0.1:45673\n[launch]\nk00_marsh=hidden_base\nl01_escape=rookie_village\n[on_demand]\nk00_marsh=1\nl01_escape=1\n");
        HostController controller(root,plan);controller.stopping_=true;controller.worker_.join();
        assert(controller.maps_.size()==2);
        auto& a=controller.maps_[0];auto& b=controller.maps_[1];
        assert(!a.process && !b.process); // no executable exists in this fixture
        controller.enabled_=true;controller.free_ram_=0;controller.free_commit_=100;controller.need_=6;
        controller.write(controller.file("host_command_",a),"start");controller.update(a);controller.queue();
        assert(a.mode=="on" && a.state=="memory" && !a.process);
        controller.write(controller.file("host_command_",a),"stop");controller.update(a);controller.free_ram_=100;controller.queue();
        assert(a.mode=="off" && !a.process);
        controller.write(controller.file("host_command_",a),"start");controller.update(a);
        controller.write(controller.folder_+L"\\host_master_paused.txt","paused");controller.queue();assert(a.state=="master_stopped" && !a.process);
        DeleteFileW((controller.folder_+L"\\host_master_paused.txt").c_str());controller.enabled_=false;controller.queue();assert(a.state=="master_wait");
        controller.enabled_=true;
        a.process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION|SYNCHRONIZE,FALSE,GetCurrentProcessId());assert(a.process);
        a.pid=GetCurrentProcessId();a.loading=true;a.state="loading";a.launched=GetTickCount64();
        controller.write(controller.file("host_command_",b),"start");controller.update(b);controller.queue();
        assert(b.state=="queued" && !b.process);
        controller.write(controller.file("host_command_",a),"stop");controller.update(a);
        assert(a.state=="saving" && a.expected && a.mode=="off");
        assert(controller.read(controller.folder_+L"\\host_stop_"+std::to_wstring(a.plan.port)+L".txt")=="stop|"+std::to_string(GetCurrentProcessId()));
        assert(GetExitCodeProcess(a.process,&a.exit) && a.exit==STILL_ACTIVE); // stop never terminates the owner
        controller.budget();controller.publish();
        const auto view=loads(controller.read(controller.folder_+L"\\host_view_native.json"));assert(view["maps"].size()==2 && view["controller"]=="native");
        puts("PASS actual native controller: persistent stop/start, cancellation before launch, real memory gate, serialization, paused/recovering master, PID-bound saved stop, live snapshot; no game process started");
        return 0;
    }
};
}
int lzm_host_fixture(const std::wstring& root) {return lzm::HostControllerFixture::run(root);}
#endif
