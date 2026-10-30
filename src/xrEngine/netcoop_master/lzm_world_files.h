// A-Life's durable outbox belongs to the master. Import/commit one consistent
// pointer + engine save + Lua sidecar; no half-snapshot becomes a database head.
#pragma once
#include "lzm_store.h"
#include "lzm_cluster_plan.h"
#include <windows.h>
#include <atomic>
#include <thread>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <ctime>

namespace lzm {
class WorldFiles
{
    Store& store_;
    std::wstring root_,pending_;
    std::atomic<bool> stopping_{false},ready_{false};
    std::thread worker_;
    std::vector<std::string> worlds_;
    std::map<std::string,std::string> seen_;
    std::set<std::string> bootstrapped_;
    static constexpr size_t block_size=512*1024;
    struct Input {
        HANDLE handle=INVALID_HANDLE_VALUE;
        explicit Input(const std::wstring& path):handle(CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
            nullptr,OPEN_EXISTING,FILE_FLAG_SEQUENTIAL_SCAN,nullptr)) {if(handle==INVALID_HANDLE_VALUE) throw Unavailable("world snapshot cannot be read");}
        ~Input(){if(handle!=INVALID_HANDLE_VALUE) CloseHandle(handle);}
        std::vector<uint8_t> next() {
            std::vector<uint8_t> bytes(block_size);DWORD got=0;
            if(!ReadFile(handle,bytes.data(),DWORD(bytes.size()),&got,nullptr)) throw Unavailable("world snapshot read failed");
            bytes.resize(got);return bytes;
        }
    };
    static bool exists(const std::wstring& path) {return GetFileAttributesW(path.c_str())!=INVALID_FILE_ATTRIBUTES;}
    static std::string small(const std::wstring& path) {
        if(!exists(path)) return "";
        Input in(path);const auto bytes=in.next();if(bytes.size()>1024) throw Invalid("world pointer exceeds its budget");
        return std::string(bytes.begin(),bytes.end());
    }
    static uint64_t fnv(uint64_t hash,const std::vector<uint8_t>& data) {for(uint8_t c:data) {hash^=c;hash*=1099511628211ULL;}return hash;}
    std::wstring pointer(const std::string& world) const {return pending_+L"\\"+widen(world)+L".current";}
    static std::string slot(const std::string& world,const std::string& image) {
        auto save=plan_trim(image.substr(0,image.find('\n')));
        if(save!=world+"_a" && save!=world+"_b") throw Invalid("world pointer names an invalid slot");
        return save;
    }
    static void verify_pointer(const std::string& image,const json& manifest) {
        const auto newline=image.find('\n');if(newline==std::string::npos) return; // original bare pointer
        std::istringstream in(image.substr(newline+1));std::string version;
        if(!(in>>version)) return;
        uint64_t bytes=0,hash=0,script_bytes=0,script_hash=0;
        if(version!="LZW2" && version!="LZW3") throw Invalid("unsupported world pointer");
        if(!(in>>bytes>>std::hex>>hash)) throw Invalid("invalid engine world digest");
        if(bytes!=manifest[0]["bytes"].get<uint64_t>() || hash!=manifest[0]["fnv"].get<uint64_t>()) throw Invalid("world engine snapshot checksum mismatch");
        if(version=="LZW3") {
            if(!(in>>std::dec>>script_bytes>>std::hex>>script_hash) || script_bytes!=manifest[1]["bytes"].get<uint64_t>() || script_hash!=manifest[1]["fnv"].get<uint64_t>())
                throw Invalid("world Lua snapshot checksum mismatch");
        }
        std::string extra;if(in>>extra) throw Invalid("unexpected world pointer tail");
    }
    void atomic(const std::wstring& path,const std::string& bytes) {
        const auto temporary=path+L".master.tmp";
        HANDLE out=CreateFileW(temporary.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(out==INVALID_HANDLE_VALUE) throw Unavailable("cannot create restored world pointer");
        DWORD written=0;const bool ok=WriteFile(out,bytes.data(),DWORD(bytes.size()),&written,nullptr) && written==bytes.size() && FlushFileBuffers(out);CloseHandle(out);
        if(!ok || !MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) throw Unavailable("cannot install restored world pointer");
    }
    bool ingest(const std::string& world) {
        const auto image=small(pointer(world));if(image.empty()) return false;
        const auto digest=sha256_hex(image);
        if(seen_[world]==digest) return false;
        {
            std::lock_guard<std::recursive_mutex> guard(store_.lock);
            const auto head=store_.db.one("SELECT r.pointer_hash FROM master_world_head h JOIN master_world_revision r ON r.id=h.capture WHERE h.world=?",{world});
            if(!head.is_null() && head["pointer_hash"]==digest) {seen_[world]=digest;return false;}
        }
        const auto save=slot(world,image),capture=token_hex(16);json manifest=json::array();
        store_.transaction([&](Db& tx) {store_.require_epoch(tx);tx.exec("INSERT INTO master_world_revision(id,world,pointer,pointer_hash,manifest,complete) VALUES(?,?,?,?,?,0)",
            {capture,world,image,digest,"[]"});});
        try {
            for(unsigned part=0;part<2;++part) {
                const auto name=save+(part ? ".scoc":".scop");Input in(pending_+L"\\"+widen(name));
                uint64_t count=0,hash=14695981039346656037ULL;unsigned index=0;
                for(;;) {
                    auto bytes=in.next();if(bytes.empty()) break;
                    count+=bytes.size();if(count>1024ULL*1024*1024) throw Invalid("world snapshot exceeds 1 GiB");hash=fnv(hash,bytes);
                    const auto chunk_hash=sha256_hex(std::string(bytes.begin(),bytes.end()));
                    store_.transaction([&](Db& tx) {store_.require_epoch(tx);tx.exec("INSERT INTO master_world_part VALUES(?,?,?,?,?)",
                        {capture,part,index,chunk_hash,json::binary(bytes)});});++index;
                    if(stopping_) throw Unavailable("world capture interrupted; durable outbox retained");
                }
                if(!count) throw Invalid("world snapshot or Lua sidecar is empty");
                manifest.push_back({{"file",name},{"bytes",count},{"fnv",hash},{"chunks",index}});
            }
            verify_pointer(image,manifest);
            if(small(pointer(world))!=image) throw Unavailable("world pointer changed during capture; retry the next complete version");
            store_.transaction([&](Db& tx) {
                store_.require_epoch(tx);
                tx.exec("UPDATE master_world_revision SET manifest=?,complete=1 WHERE id=?",{canonical(manifest),capture});
                tx.exec("INSERT INTO master_world_head VALUES(?,?) ON CONFLICT(world) DO UPDATE SET capture=excluded.capture",{world,capture});
                const auto obsolete=tx.all("SELECT id FROM master_world_revision WHERE world=? AND id NOT IN (SELECT id FROM master_world_revision WHERE world=? AND complete=1 ORDER BY sequence DESC LIMIT 2)",{world,world});
                for(const auto& row:obsolete) {tx.exec("DELETE FROM master_world_part WHERE capture=?",{row["id"]});tx.exec("DELETE FROM master_world_revision WHERE id=?",{row["id"]});}
            });
            seen_[world]=digest;
            log_line(format("[diag][world-store] committed world=%s engine_bytes=%llu lua_bytes=%llu capture=%s",world.c_str(),
                (unsigned long long)manifest[0]["bytes"].get<uint64_t>(),(unsigned long long)manifest[1]["bytes"].get<uint64_t>(),capture.c_str()));
            return true;
        }catch(...) {
            store_.transaction([&](Db& tx) {tx.exec("DELETE FROM master_world_part WHERE capture=?",{capture});tx.exec("DELETE FROM master_world_revision WHERE id=? AND complete=0",{capture});});throw;
        }
    }
    bool restore(const std::string& world) {
        json head;
        {std::lock_guard<std::recursive_mutex> guard(store_.lock);head=store_.db.one("SELECT r.* FROM master_world_head h JOIN master_world_revision r ON r.id=h.capture WHERE h.world=? AND r.complete=1",{world});}
        if(head.is_null()) return false;
        const auto manifest=loads(head["manifest"].get<std::string>()),capture=head["id"];
        const auto image=head["pointer"].get<std::string>();const auto save=slot(world,image);
        if(manifest.size()!=2 || sha256_hex(image)!=head["pointer_hash"]) throw Invalid("invalid master world manifest");
        for(unsigned part=0;part<2;++part) {
            const auto name=save+(part ? ".scoc":".scop");if(manifest[part]["file"]!=name) throw Invalid("world manifest path mismatch");
            const auto temporary=pending_+L"\\"+widen(name)+L".master.tmp";
            HANDLE out=CreateFileW(temporary.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
            if(out==INVALID_HANDLE_VALUE) throw Unavailable("cannot create world recovery output");
            uint64_t count=0,hash=14695981039346656037ULL;
            try {
                const auto chunks=manifest[part]["chunks"].get<unsigned>();if(!chunks || chunks>2048) throw Invalid("world manifest chunk budget");
                for(unsigned index=0;index<chunks;++index) {
                    json row;{std::lock_guard<std::recursive_mutex> guard(store_.lock);row=store_.db.one("SELECT digest,data FROM master_world_part WHERE capture=? AND part=? AND number=?",{capture,part,index});}
                    if(row.is_null() || !row["data"].is_binary()) throw Invalid("world recovery chunk is missing");
                    const auto& bytes=row["data"].get_binary();
                    if(bytes.empty() || bytes.size()>block_size || sha256_hex(std::string(bytes.begin(),bytes.end()))!=row["digest"]) throw Invalid("world recovery chunk checksum mismatch");
                    DWORD written=0;if(!WriteFile(out,bytes.data(),DWORD(bytes.size()),&written,nullptr) || written!=bytes.size()) throw Unavailable("world recovery write failed");
                    count+=bytes.size();hash=fnv(hash,bytes);
                }
                if(count!=manifest[part]["bytes"] || hash!=manifest[part]["fnv"] || !FlushFileBuffers(out)) throw Invalid("restored world checksum mismatch");
                CloseHandle(out);out=INVALID_HANDLE_VALUE;
                if(!MoveFileExW(temporary.c_str(),(pending_+L"\\"+widen(name)).c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) throw Unavailable("cannot install recovered world snapshot");
            }catch(...) {if(out!=INVALID_HANDLE_VALUE) CloseHandle(out);DeleteFileW(temporary.c_str());throw;}
        }
        atomic(pointer(world),image);seen_[world]=head["pointer_hash"].get<std::string>();
        log_line("[diag][world-store] restored world="+world+" from verified SQLite chunks");return true;
    }
    void migrate(const std::string& world) {
        const auto legacy=root_+L"\\appdata\\server\\savedgames";
        // The original files are preserved. Copy only this world's known save
        // names, and do not overwrite an already queued master-owned capture.
        for(const auto& suffix:{L".current",L".scop",L".scoc",L"_a.scop",L"_a.scoc",L"_b.scop",L"_b.scoc"}) {
            const auto name=widen(world)+suffix,source=legacy+L"\\"+name,target=pending_+L"\\"+name;
            if(exists(source) && !exists(target) && !CopyFileW(source.c_str(),target.c_str(),TRUE)) throw Unavailable("cannot preserve legacy world snapshot");
        }
        if(!exists(pointer(world)) && exists(pending_+L"\\"+widen(world)+L".scop")) {
            if(!exists(pending_+L"\\"+widen(world)+L".scoc")) throw Invalid("legacy world has no Lua sidecar; refusing a reset");
            for(const auto& extension:{L".scop",L".scoc"})
                if(!CopyFileW((pending_+L"\\"+widen(world)+extension).c_str(),(pending_+L"\\"+widen(world)+L"_a"+extension).c_str(),TRUE) && GetLastError()!=ERROR_FILE_EXISTS)
                    throw Unavailable("cannot stage legacy world migration");
            atomic(pointer(world),world+"_a\n");
        }
    }
    void initialize() {
        {std::lock_guard<std::recursive_mutex> guard(store_.lock);
            store_.db.exec("DELETE FROM master_world_part WHERE capture IN (SELECT id FROM master_world_revision WHERE complete=0)");
            store_.db.exec("DELETE FROM master_world_revision WHERE complete=0");}
        for(const auto& world:worlds_) {
            if(stopping_) return;
            if(bootstrapped_.count(world)) continue;
            bool head=false;{std::lock_guard<std::recursive_mutex> guard(store_.lock);head=!store_.db.one("SELECT capture FROM master_world_head WHERE world=?",{world}).is_null();}
            if(!exists(pointer(world)) && head) {restore(world);bootstrapped_.insert(world);continue;}
            if(!head) migrate(world);
            if(exists(pointer(world))) {
                try {if(!ingest(world)) restore(world);bootstrapped_.insert(world);continue;}
                catch(const std::exception& e) {
                    log_line("[diag][world-store] pending snapshot cannot be committed world="+world+" reason="+e.what());
                    const auto backup=root_+L"\\appdata\\master\\recovery\\"+widen(world+"_"+token_hex(8));std::filesystem::create_directories(backup);
                    for(const auto& f:std::filesystem::directory_iterator(pending_)) if(f.path().filename().wstring().rfind(widen(world),0)==0)
                        CopyFileW(f.path().c_str(),(backup+L"\\"+f.path().filename().wstring()).c_str(),TRUE);
                    if(!restore(world)) throw;bootstrapped_.insert(world);continue;
                }
            }
            if(!restore(world) && (exists(pending_+L"\\"+widen(world)+L"_a.scop") || exists(pending_+L"\\"+widen(world)+L"_b.scop")))
                throw Invalid("world has snapshots but no committed pointer; recovery required");
            bootstrapped_.insert(world);
        }
        ready_=true;log_line(format("[diag][world-store] ready worlds=%zu; database heads and durable outboxes are consistent",worlds_.size()));
    }
    void run() noexcept {
        while(!stopping_) {
            try {
                if(!ready_) initialize();
                else for(const auto& world:worlds_) {if(stopping_) break;ingest(world);}
            }catch(const std::exception& error) {log_line("[diag][world-store] recovery/commit failed: "+std::string(error.what()));}
            for(int i=0;i<20 && !stopping_;++i) Sleep(100);
        }
    }
public:
    WorldFiles(Store& store,const std::wstring& root,const std::wstring& plan):store_(store),root_(root),pending_(root+L"\\appdata\\master\\pending\\worlds") {
        std::filesystem::create_directories(pending_);
        const auto identity=store_.db.one("SELECT world_id,seed FROM world WHERE singleton=1");
        const auto authority=pending_+L"\\_authority.json";
        if(exists(authority)) {if(loads(small(authority))!=identity) throw Invalid("world outbox belongs to a different master identity");}
        else atomic(authority,canonical(identity));
        store_.db.script("CREATE TABLE IF NOT EXISTS master_world_revision(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,world TEXT NOT NULL,pointer TEXT NOT NULL,pointer_hash TEXT NOT NULL,manifest TEXT NOT NULL,complete INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS master_world_head(world TEXT PRIMARY KEY,capture TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS master_world_part(capture TEXT NOT NULL,part INTEGER NOT NULL,number INTEGER NOT NULL,digest TEXT NOT NULL,data BLOB NOT NULL,PRIMARY KEY(capture,part,number));");
        std::ifstream in(plan);std::ostringstream text;text<<in.rdbuf();const auto ini=parse_cluster_sections(text.str());
        const auto found=ini.find("locations");if(found!=ini.end()) for(const auto& pair:found->second)
            worlds_.push_back(pair.first=="k00_marsh" ? "zone":pair.first=="l01_escape" ? "zone_escape":"zone_"+pair.first);
        worker_=std::thread([this]{run();});
    }
    ~WorldFiles(){stop();}
    void stop(){stopping_=true;if(worker_.joinable()) worker_.join();}
    bool ready() const {return ready_;}
};
} // namespace lzm
