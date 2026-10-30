// Included inside namespace netcoop in netcoop.cpp after netcoop_cluster.inc.
// Small shared records for server Lua that every location server of the
// cluster sees: faction membership, leaders, applications, bounties
// (doc 47). One file per record in $app_data_root$/netcoop_store/<bucket>/,
// written atomically (temp + rename) under a machine-wide mutex; swap is a
// compare-and-swap so two servers deciding at once cannot lose an update.
// Values are opaque strings (the Lua side keeps data-only tables in them).

static const u32 store_value_limit = 65536;
static bool admission_store_record(LPCSTR operation,LPCSTR bucket,LPCSTR key,LPCSTR expected,LPCSTR value,xr_string& output,bool& swapped);

struct StoreLock
{
	ClusterFileLock lock; // netcoop.cpp: works across machines sharing app data
	bool owned;
	StoreLock() : lock("shared_store"), owned(lock.held) {}
};

static bool store_name_valid(LPCSTR name)
{
	if (!name || !name[0] || xr_strlen(name) > 96) return false;
	for (const char* c = name; *c; ++c)
		if (!isalnum((unsigned char)*c) && *c != '_' && *c != '-') return false;
	return true;
}

static bool store_path(LPCSTR bucket, LPCSTR key, string_path& path)
{
	if (!store_name_valid(bucket) || (key && !store_name_valid(key))) return false;
	string_path root;
	FS.update_path(root, "$app_data_root$", master_cluster_plan() ? "netcoop_store_cache\\":"netcoop_store\\");
	CreateDirectoryA(root, nullptr);
	string_path dir;
	xr_sprintf(dir, "%s%s\\", root, bucket);
	CreateDirectoryA(dir, nullptr);
	if (key) xr_sprintf(path, "%s%s.txt", dir, key);
	else xr_strcpy(path, dir);
	return true;
}

static bool store_read_file(LPCSTR path, xr_string& value)
{
	value.clear();
	FILE* f = fopen(path, "rb");
	if (!f) return false;
	char buffer[4096];
	size_t n;
	while ((n = fread(buffer, 1, sizeof(buffer), f)) > 0 && value.size() <= store_value_limit) value.append(buffer, n);
	const bool ok = !ferror(f);
	fclose(f);
	return ok && value.size() <= store_value_limit;
}

static bool store_write_file(LPCSTR path, LPCSTR value)
{
	string_path temp;
	xr_sprintf(temp, "%s.%u.tmp", path, GetCurrentProcessId());
	FILE* f = fopen(temp, "wb");
	if (!f) return false;
	const size_t size = xr_strlen(value);
	const bool ok = fwrite(value, 1, size, f) == size && fflush(f) == 0 && _commit(_fileno(f)) == 0;
	if (fclose(f) != 0 || !ok || !MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
	{
		DeleteFileA(temp);
		return false;
	}
	return true;
}

// Lua: netcoop_store_read(bucket, key) -> value, "" when there is none.
LPCSTR script_store_read(LPCSTR bucket, LPCSTR key)
{
	static xr_string value;
	value.clear();
	string_path path;
	if (!enabled() || !store_path(bucket, key, path)) return "";
	if(master_cluster_plan()) {
		bool swapped=false;
		if(admission_store_record("store_read",bucket,key,nullptr,nullptr,value,swapped)) {store_write_file(path,value.c_str());return value.c_str();}
		// Read-only bootstrap/recovery view exported by the master. Never read
		// the old authority file or write it while this cluster is managed.
		store_read_file(path,value);return value.c_str();
	}
	StoreLock lock;
	if (!lock.owned) return "";
	store_read_file(path, value);
	return value.c_str();
}

// Lua: netcoop_store_swap(bucket, key, expected, value) -> true when the
// record still held `expected` ("" = absent) and now holds `value` ("" removes it).
bool script_store_swap(LPCSTR bucket, LPCSTR key, LPCSTR expected, LPCSTR value)
{
	string_path path;
	if (!enabled() || !expected || !value || xr_strlen(value) > store_value_limit || !store_path(bucket, key, path)) return false;
	if(master_cluster_plan()) {
		xr_string ignored;bool swapped=false;
		if(!admission_store_record("store_swap",bucket,key,expected,value,ignored,swapped) || !swapped) return false;
		store_write_file(path,value);return true; // derived cache only
	}
	StoreLock lock;
	if (!lock.owned) return false;
	xr_string current;
	store_read_file(path, current);
	if (current != expected) return false;
	if (!value[0]) return DeleteFileA(path) || GetLastError() == ERROR_FILE_NOT_FOUND;
	return store_write_file(path, value);
}

// Lua: netcoop_store_keys(bucket) -> "key key ..." (sorted).
LPCSTR script_store_keys(LPCSTR bucket)
{
	static xr_string keys;
	keys.clear();
	string_path dir;
	if (!enabled() || !store_path(bucket, nullptr, dir)) return "";
	if(master_cluster_plan()) {bool swapped=false;if(admission_store_record("store_keys",bucket,nullptr,nullptr,nullptr,keys,swapped)) return keys.c_str();}
	string_path mask;
	xr_sprintf(mask, "%s*.txt", dir);
	xr_vector<xr_string> names;
	WIN32_FIND_DATAA found;
	HANDLE search = FindFirstFileA(mask, &found);
	if (search != INVALID_HANDLE_VALUE)
	{
		do
		{
			xr_string name = found.cFileName;
			if (name.size() > 4) name.resize(name.size() - 4);
			if (store_name_valid(name.c_str())) {
				xr_string contents;string_path path;xr_sprintf(path,"%s%s.txt",dir,name.c_str());
				if(!master_cluster_plan() || (store_read_file(path,contents) && !contents.empty())) names.push_back(name);
			}
		} while (FindNextFileA(search, &found));
		FindClose(search);
	}
	std::sort(names.begin(), names.end());
	for (const xr_string& name : names)
	{
		if (!keys.empty()) keys += " ";
		keys += name;
	}
	return keys.c_str();
}

// Lua: netcoop_actor_character(actor_id) -> "login_slot" of the player's
// character on this server ("" for NPCs and the server's own Actor).
LPCSTR script_actor_character(u16 actor_id)
{
	static string128 key;
	key[0] = 0;
	auto found = s_actor_character.find(actor_id);
	if (found == s_actor_character.end()) return key;
	xr_strcpy(key, found->second.c_str());
	for (char* c = key; *c; ++c) if (*c == ':') *c = '_';
	return key;
}

// Lua: netcoop_set_character_faction(actor_id, faction): the character's
// faction for future spawns and the character list; saved right away. The
// live Actor's community is set by the caller (set_character_community).
bool script_set_character_faction(u16 actor_id, LPCSTR faction)
{
	auto found = s_actor_character.find(actor_id);
	if (found == s_actor_character.end() || !faction || !faction[0] || xr_strlen(faction) > 32) return false;
	for (const char* c = faction; *c; ++c)
		if (!isalnum((unsigned char)*c) && *c != '_') return false;
	Character& character = s_characters[found->second];
	if (character.faction == faction) return true;
	Msg("[Lost Zone][factions] %s slot %u: %s -> %s", character.account.c_str(), character.slot, character.faction.c_str(), faction);
	character.faction = faction;
	return character_save_actor(actor_id, nullptr, true);
}
