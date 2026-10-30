// Master-owned shared records. Values are opaque bytes encoded on the wire;
// no JSON payload from a mod or device/account value is written to diagnostics.
static std::string record_name(const json& value)
{
    if(!value.is_string()) throw Invalid("record name must be a string");
    const auto name=value.get<std::string>();
    if(name.empty() || name.size()>96 || name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)
        throw Invalid("invalid record name");
    return name;
}

void Service::initialize_records(const std::wstring& root)
{
    store_->db.script("CREATE TABLE IF NOT EXISTS master_record(bucket TEXT NOT NULL,key TEXT NOT NULL,data TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(bucket,key));");
    if(root.empty()) return;
    // Existing files are imported only when a key is absent. An authoritative
    // deletion is a tombstone, so a retained backup cannot resurrect it later.
    const auto legacy=root+L"\\appdata\\server\\netcoop_store";
    size_t imported=0;
    std::error_code error;
    for(const auto& file:std::filesystem::recursive_directory_iterator(legacy,error))
    {
        if(!file.is_regular_file() || file.path().extension()!=L".txt") continue;
        const auto relative=file.path().lexically_relative(legacy);
        if(std::distance(relative.begin(),relative.end())!=2) continue;
        std::string bucket,key;
        try {bucket=record_name(narrow(relative.begin()->wstring()));key=record_name(narrow(file.path().stem().wstring()));}
        catch(const Invalid&) {log_line("[diag][migration] skipped legacy file with an invalid shared-record name");continue;}
        if(file.file_size()>65536) throw Invalid("legacy shared record exceeds the supported size");
        std::ifstream in(file.path(),std::ios::binary);std::ostringstream bytes;bytes<<in.rdbuf();
        if(!in || bytes.str().size()>65536) throw Unavailable("legacy shared record cannot be imported");
        imported+=size_t(store_->db.exec("INSERT OR IGNORE INTO master_record VALUES(?,?,?,1)",{bucket,key,base64(bytes.str())}));
    }
    const auto ban_path=root+L"\\appdata\\server\\netcoop_bans.txt";
    if(std::filesystem::exists(ban_path)) {
        std::ifstream in(ban_path,std::ios::binary);std::ostringstream bytes;bytes<<in.rdbuf();
        if(!in || bytes.str().size()>65536) throw Invalid("legacy ban list exceeds its migration budget");
        imported+=size_t(store_->db.exec("INSERT OR IGNORE INTO master_record VALUES('_system','bans',?,1)",{base64(bytes.str())}));
    }
    for(const auto& row:store_->db.all("SELECT bucket,key,data FROM master_record")) {
        const auto bucket=record_name(row["bucket"]),key=record_name(row["key"]);
        std::string bytes;if(!base64_decode(row["data"].get<std::string>(),bytes) || bytes.size()>65536) throw Invalid("invalid master record image");
        const auto directory=root+L"\\appdata\\server\\netcoop_store_cache\\"+widen(bucket);
        std::filesystem::create_directories(directory);
        const auto path=directory+L"\\"+widen(key)+L".txt",temporary=path+L".native.tmp";
        {std::ofstream out(temporary,std::ios::binary|std::ios::trunc);if(!out || !(out<<bytes)) throw Unavailable("cannot export master record cache");}
        if(!MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) throw Unavailable("cannot install master record cache");
    }
    log_line(format("[diag][migration] shared records imported=%zu; legacy files retained as backups",imported));
}

json Service::record_exchange(const std::string& actor,const std::string& command_id,const std::string& operation,const json& args)
{
    const auto bucket=record_name(args["bucket"]),location=identifier(args["location"]);
    const auto fence=as_int(args["fence"]);
    if(operation=="store_keys" || operation=="store_read")
    {
        return store_->transaction([&](Db& tx)->json {
            world_->require_location(tx,actor,location,fence);
            if(operation=="store_keys") {
                std::string keys;
                for(const auto& row:tx.all("SELECT key FROM master_record WHERE bucket=? AND data<>'' ORDER BY key LIMIT 4097",{bucket})) {
                    if(!keys.empty()) keys+=" ";keys+=row["key"].get<std::string>();
                    if(keys.size()>512*1024) throw Unavailable("too many shared record keys");
                }
                return {{"value",base64(keys)}};
            }
            const auto row=tx.one("SELECT data FROM master_record WHERE bucket=? AND key=?",{bucket,record_name(args["key"])});
            return {{"value",row.is_null() ? json(""):row["data"]}};
        });
    }
    const auto key=record_name(args["key"]);
    std::string expected,value;
    if(!args["expected"].is_string() || !args["value"].is_string() ||
       !base64_decode(args["expected"].get<std::string>(),expected) || !base64_decode(args["value"].get<std::string>(),value) ||
       expected.size()>65536 || value.size()>65536) throw Invalid("shared record value exceeds its budget");
    return store_->command(actor,command_id,{{"operation",operation},{"arguments",args}},[&](Db& tx)->json {
        world_->require_location(tx,actor,location,fence);
        const auto row=tx.one("SELECT data,revision FROM master_record WHERE bucket=? AND key=?",{bucket,key});
        const auto encoded=row.is_null() ? "":row["data"].get<std::string>();
        if(encoded!=base64(expected)) return {{"swapped",false}};
        const int64_t revision=row.is_null() ? 1:as_int(row["revision"])+1;
        tx.exec("INSERT INTO master_record VALUES(?,?,?,?) ON CONFLICT(bucket,key) DO UPDATE SET data=excluded.data,revision=excluded.revision",
            {bucket,key,base64(value),revision});
        log_line(format("[diag][storage] swap bucket=%s key=%s bytes=%zu revision=%lld",bucket.c_str(),key.c_str(),value.size(),(long long)revision));
        return {{"swapped",true},{"revision",revision}};
    });
}
