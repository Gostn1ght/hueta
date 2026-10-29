// Included inside namespace netcoop in netcoop.cpp. Accounts authenticate a
// connection; character slots own gameplay state. No client-supplied saves.
struct Character
{
	xr_string account, name, faction, loadout, description, history;
	u8 slot = 1, economy = 1;
	bool initialized = false, respawn = false;
	u32 last_save = 0;
	NET_Packet actor;
	xr_vector<u8> progress;
	// state: uid, portions and cartridge sequence (netcoop_items.inc), NCH7+.
	struct Item { xr_string section; u16 parent, place = 0; NET_Packet spawn; xr_vector<u8> state; };
	xr_vector<Item> items, safe;
	u32 storage_revision = 1;
	u32 inventory_cells = 0; // NCH9: last server-captured capacity; zero is a legacy/new-slot fallback.
	xr_string storage_request, storage_signature;
};
static xr_map<xr_string, Character> s_characters;
static xr_map<u16, xr_string> s_actor_character;
struct CharacterRestore
{
	xr_vector<std::pair<u16, u16>> places, entities; // runtime item -> expected parent
	bool inventory_complete = false, attempted = false;
	u32 last_attempt = 0;
	u32 since = 0;
	bool clock_started = false, rejected = false;
};
static xr_map<u16, CharacterRestore> s_character_restore;
static bool character_capture_progress(Character& character, CActor* actor);
static bool character_restore_progress(Character& character, CActor* actor);
static void character_restore_timeout(u16 actor_id);

bool server_character_accepts(xrClientData* CL, u16 type)
{
	if (!CL) return true;
	if (!server_stopping() && (!CL->owner || s_character_restore.find(CL->owner->ID) == s_character_restore.end())) return true;
	switch (type)
	{
	case M_CL_UPDATE:
		CL->net_Ready = TRUE; // acknowledge connection readiness, never apply the unfinished actor payload
		return false;
	case M_CL_INPUT: case M_EVENT: case M_EVENT_PACK:
	case M_MOVE_PLAYERS_RESPOND: case M_GAMEMESSAGE: case M_PLAYER_FIRE:
	case M_NETCOOP_TRADE: case M_NETCOOP_CAMPFIRE: case M_NETCOOP_ITEM_ACTION:
	case M_NETCOOP_TRANSFER: case M_NETCOOP_ITEM_REPORT: case M_NETCOOP_TALK:
	case M_NETANOMALY_CMD:
		return false;
	default:
		return true; // connection/ready ACKs still work; level changer reports its loading refusal
	}
}


static xr_string character_key(LPCSTR account, u8 slot)
{
	xr_string key = account;
	to_lower(key);
	key += ":";
	key += char('0' + slot);
	return key;
}

static void character_path(LPCSTR account, u8 slot, string_path& path)
{
	xr_string login = account;
	to_lower(login);
	string128 file;
	xr_sprintf(file, "netcoop_character_%s_%u.bin", login.c_str(), slot);
	FS.update_path(path, "$app_data_root$", file);
}

static bool character_name_valid(LPCSTR name)
{
	if (!name || !name[0] || xr_strlen(name) > 63) return false;
	for (const unsigned char* c = (const unsigned char*)name; *c; ++c)
		if (*c < 32 || *c == '|') return false;
	return true;
}

bool script_character(int slot, LPCSTR name, LPCSTR faction, int economy, LPCSTR loadout)
{
	if (slot < 0 || slot > 10 || !name || !faction || !loadout || xr_strlen(loadout) > 4096) return false;
	s_client_character_slot = u8(slot);
	s_client_character_name = name;
	s_client_character_faction = faction;
	s_client_character_economy = u8(economy);
	s_client_character_loadout = loadout;
	return true;
}

struct CharacterInput
{
 const u8* data;
 size_t remaining;
 CharacterInput(const void* bytes, size_t size) : data(static_cast<const u8*>(bytes)), remaining(size) {}
 size_t read(void* output, size_t size, size_t count)
 {
  if (!size || count > remaining / size) return 0;
  const size_t bytes = size * count;
  if (bytes) memcpy(output, data, bytes);
  data += bytes; remaining -= bytes;
  return count;
 }
 int get()
 {
  if (!remaining) return EOF;
  --remaining; return *data++;
 }
};

static bool character_read_string(CharacterInput* f, xr_string& value, u32 max_size)
{
	value.clear();
	for (u32 n = 0; n <= max_size; ++n)
	{
		const int c = f->get();
		if (c == EOF) return false;
		if (!c) return true;
		value += char(c);
	}
	return false;
}

static u32 character_checksum(const void* data, u32 size)
{
	// Keep the existing hardware speed on SSE4.2, use the same polynomial on
	// older CPUs. Do not change xrCore CRC used by archives and other formats.
	return (CPU::ID.feature & _CPU_FEATURE_SSE4_2) ? crc32(data, size) : save_checksum::crc32c(data, size);
}

static bool character_checksum_matches(const void* data, u32 size, u32 expected, bool legacy_crc)
{
	return character_checksum(data, size) == expected ||
		(legacy_crc && save_checksum::legacy_ieee(data, size) == expected);
}

static bool character_read_packet(CharacterInput* f, NET_Packet& packet, bool legacy_crc)
{
	u32 size, crc;
	if (f->read(&size, 4, 1) != 1 || f->read(&crc, 4, 1) != 1 || size > sizeof(packet.B.data)) return false;
	packet.B.count = size;
	packet.r_pos = 0;
	return (!size || f->read(packet.B.data, 1, size) == size) && character_checksum_matches(packet.B.data, size, crc, legacy_crc);
}

// Count first, then allocate and fill one exact immutable NCH image. No FILE,
// engine object pointer or Lua state is passed to the commit/HTTP worker.
struct CharacterSnapshot
{
	xr_vector<u8> data;
	size_t offset = 0;
	bool counting = true, valid = true;
	static const size_t limit = 20u * 1024 * 1024;
	void write(const void* source, size_t size)
	{
		if (!valid || offset > limit || size > limit - offset ||
			(!counting && (offset > data.size() || size > data.size() - offset)))
		{ valid = false; return; }
		if (!counting && size) memcpy(data.data() + offset, source, size);
		offset += size;
	}
	void string(const xr_string& value, size_t maximum)
	{
		if (value.size() > maximum || xr_strlen(value.c_str()) != value.size()) { valid = false; return; }
		write(value.c_str(), value.size() + 1);
	}
};

static void character_write_packet(CharacterSnapshot& output, const NET_Packet& packet)
{
	const u32 size = packet.B.count;
	if (size > sizeof(packet.B.data)) { output.valid = false; return; }
	const u32 crc = output.counting ? 0 : character_checksum(packet.B.data, size);
	output.write(&size, 4); output.write(&crc, 4);
	output.write(packet.B.data, size);
}

static void character_write_state(CharacterSnapshot& output, const xr_vector<u8>& state)
{
	if (state.size() > 512) { output.valid = false; return; }
	const u16 size = u16(state.size());
	output.write(&size, 2); output.write(state.data(), size);
}

static bool character_read_state(CharacterInput* f, xr_vector<u8>& state)
{
	u16 size = 0;
	if (f->read(&size, 2, 1) != 1 || size > 512) return false;
	state.resize(size);
	return !size || f->read(state.data(), 1, size) == size;
}

static bool character_snapshot(const Character& character, xr_vector<u8>& snapshot)
{
	snapshot.clear();
	if (!character_name_valid(character.name.c_str()) || character.items.size() > 512 || character.safe.size() > 512 ||
		character.progress.size() > 1048576 || !character.storage_revision || character.inventory_cells > 512) return false;
	CharacterSnapshot output;
	for (unsigned pass = 0; pass < 2; ++pass)
	{
		if (pass) { output.data.resize(output.offset); output.offset = 0; output.counting = false; }
		const u32 magic = 0x3948434e; // Same NCH9 bytes as the local durable file.
		output.write(&magic, 4);
		output.string(character.name, 63); output.string(character.faction, 32); output.string(character.loadout, 4096);
		output.string(character.description, 512); output.string(character.history, 1536);
		const u8 flags[] = {character.economy, u8(character.initialized ? 1 : 0), u8(character.respawn ? 1 : 0)};
		output.write(flags, sizeof(flags));
		character_write_packet(output, character.actor);
		auto inventory = [&output](const xr_vector<Character::Item>& items)
		{
			const u32 count = u32(items.size()); output.write(&count, 4);
			for (u32 index = 0; index < count; ++index)
			{
				const Character::Item& item = items[index];
				if (item.parent > index) { output.valid = false; return; }
				output.string(item.section, 128); output.write(&item.parent, 2); output.write(&item.place, 2);
				character_write_packet(output, item.spawn); character_write_state(output, item.state);
			}
		};
		inventory(character.items);
		const u32 size = u32(character.progress.size());
		const u32 crc = output.counting ? 0 : character_checksum(character.progress.data(), size);
		output.write(&size, 4); output.write(&crc, 4); output.write(character.progress.data(), size);
		output.write(&character.storage_revision, 4);
		output.string(character.storage_request, 32); output.string(character.storage_signature, 80);
		inventory(character.safe);
		output.write(&character.inventory_cells, 4);
		if (!output.valid) return false;
	}
	if (output.offset != output.data.size()) return false;
	snapshot.swap(output.data);
	return true;
}

// Autosaves pass owned bytes to the IO worker; even opening/writing/flushing
// the temporary file must not block the simulation. An accepted queue entry
// is pending, not durable acknowledgement. Sync saves retain their barrier.
struct CharacterCommit { xr_string temp, path; xr_vector<u8> snapshot; u64 bytes = 0; };
static bool admission_capture(const Character& character, const xr_vector<u8>& snapshot); // netcoop_admission.inc
static xrCriticalSection s_commit_lock;
static xr_deque<CharacterCommit> s_commits;
static bool s_commit_worker = false;
static volatile LONG s_commit_busy = 0;
static const u32 character_commit_count_limit = 256;
static const u64 character_commit_byte_limit = 32ull * 1024 * 1024;
static u64 s_commit_bytes = 0, s_commit_active_bytes = 0;
static xr_string s_commit_active_path;

// At most one pending complete snapshot per path. A newer snapshot contains
// the full inventory/safe/progress, so it can supersede a queued older one.
// The in-flight snapshot remains counted and is never replaced underneath I/O.
static bool character_commit_enqueue(CharacterCommit&& commit)
{
	if (!commit.bytes || commit.bytes > character_commit_byte_limit || commit.bytes != commit.snapshot.size()) return false;
	const u64 bytes = commit.bytes;
	s_commit_lock.Enter();
	auto previous = s_commits.end();
	for (auto it = s_commits.begin(); it != s_commits.end(); ++it)
		if (it->path == commit.path) { previous = it; break; }
	const u64 old_bytes = previous != s_commits.end() ? previous->bytes : 0;
	if ((previous == s_commits.end() && s_commits.size() >= character_commit_count_limit) ||
		s_commit_bytes - old_bytes + commit.bytes > character_commit_byte_limit ||
		(previous != s_commits.end() && previous->temp == commit.temp))
	{
		s_commit_lock.Leave();
		return false;
	}
	if (previous == s_commits.end())
	{
		// xalloc::construct accepts const T&: push_back(rvalue) would still
		// copy this large image. Default-construct, then transfer its buffers.
		s_commits.emplace_back();
		std::swap(s_commits.back(), commit);
	}
	else std::swap(*previous, commit); // Old bytes are freed by the producer, outside the queue lock.
	s_commit_bytes = s_commit_bytes - old_bytes + bytes;
	s_commit_lock.Leave();
	return true;
}

static bool character_commit_take(CharacterCommit& commit)
{
	s_commit_lock.Enter();
	const bool have = !s_commits.empty() && !s_commit_busy;
	if (have)
	{
		commit = std::move(s_commits.front()); s_commits.pop_front();
		s_commit_active_bytes = commit.bytes;
		s_commit_active_path = commit.path;
		InterlockedExchange(&s_commit_busy, 1);
	}
	s_commit_lock.Leave();
	return have;
}

static void character_commit_finish()
{
	s_commit_lock.Enter();
	s_commit_bytes -= s_commit_active_bytes;
	s_commit_active_bytes = 0;
	s_commit_active_path.clear();
	InterlockedExchange(&s_commit_busy, 0);
	s_commit_lock.Leave();
}

// A synchronous checkpoint only orders writes for its own character. Pull
// that path to the front; unrelated queued players must not stall a transfer.
// The single simulation-thread producer cannot enqueue a newer same-path
// write while it is waiting here. Shutdown keeps the global (null) barrier.
static bool character_commit_pending(LPCSTR path)
{
	s_commit_lock.Enter();
	bool pending = s_commit_busy && (!path || s_commit_active_path == path);
	if (!path) pending = pending || !s_commits.empty();
	else
		for (auto it = s_commits.begin(); it != s_commits.end(); ++it)
			if (it->path == path)
			{
				std::iter_swap(s_commits.begin(), it);
				pending = true;
				break;
			}
	s_commit_lock.Leave();
	return pending;
}

static bool character_temp_path(LPCSTR path, bool background, string_path& temp)
{
	static u64 sequence = 0;
	if (sequence == u64(-1)) return false;
	const int length = snprintf(temp, sizeof(temp), "%s.%u.%llu%s.tmp", path, u32(GetCurrentProcessId()),
		static_cast<unsigned long long>(++sequence), background ? "" : ".sync");
	return length >= 0 && size_t(length) < sizeof(temp);
}

static bool character_sync_commit(FILE* f, LPCSTR temp, LPCSTR path)
{
	const bool ok = !ferror(f) && fflush(f) == 0 && _commit(_fileno(f)) == 0;
	const bool closed = fclose(f) == 0;
	if (!ok || !closed || !MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
	{
		DeleteFileA(temp);
		return false;
	}
	return true;
}

static bool character_commit_file(const CharacterCommit& commit)
{
    if (!commit.bytes || commit.bytes != commit.snapshot.size() || commit.bytes > character_commit_byte_limit) return false;
    FILE* f = fopen(commit.temp.c_str(), "wb");
    if (!f) return false;
    if (fwrite(commit.snapshot.data(), 1, commit.snapshot.size(), f) != commit.snapshot.size())
    {
        fclose(f); DeleteFileA(commit.temp.c_str()); return false;
    }
    return character_sync_commit(f, commit.temp.c_str(), commit.path.c_str());
}

static void character_commit_worker(void*)
{
	for (;;)
	{
		CharacterCommit commit;
		if (!character_commit_take(commit)) { Sleep(5); continue; }
		if (!character_commit_file(commit))
		{
			Msg("! [Lost Zone] character commit failed: %s", commit.path.c_str());
			DeleteFileA(commit.temp.c_str());
		}
		character_commit_finish();
	}
}

// A synchronous save must not be overtaken by an older background one.
static void character_commits_flush(LPCSTR path = nullptr)
{
	while (character_commit_pending(path)) Sleep(1);
}

static void character_commits_flush_account(LPCSTR account)
{
	for (u8 slot = 1; slot <= 10; ++slot)
	{
		string_path path;
		character_path(account, slot, path);
		character_commits_flush(path);
	}
}

static bool character_save(Character& character, bool background = false)
{
    string_path path, temp;
    character_path(character.account.c_str(), character.slot, path);
    if (!background) character_commits_flush(path);
    if (!character_temp_path(path, background, temp)) return false;
    CharacterCommit commit;
    commit.path = path; commit.temp = temp;
    if (!character_snapshot(character, commit.snapshot)) return false;
    commit.bytes = u64(commit.snapshot.size());
    if (!admission_capture(character, commit.snapshot)) return false; // do not hand off an image the master never queued
    if (background)
    {
        if (!character_commit_enqueue(std::move(commit))) return false;
        s_commit_lock.Enter();
        if (!s_commit_worker) { s_commit_worker = true; thread_spawn(character_commit_worker, "netcoop-save", 0, nullptr); }
        s_commit_lock.Leave();
    }
    else if (!character_commit_file(commit)) return false;
    character.last_save = real_time_ms();
    return true;
}

static bool character_decode(const void* bytes, size_t byte_count, Character& character)
{
 if (!bytes || !byte_count || byte_count > CharacterSnapshot::limit) return false;
 CharacterInput input(bytes, byte_count);
 CharacterInput* f = &input;
	u32 magic = 0, count = 0;
	bool ok = f->read(&magic, 4, 1) == 1 && (magic == 0x3348434e || magic == 0x3448434e || magic == 0x3548434e || magic == 0x3648434e || magic == 0x3748434e || magic == 0x3848434e || magic == 0x3948434e) &&
		character_read_string(f, character.name, 63) && character_read_string(f, character.faction, 32) &&
		character_read_string(f, character.loadout, 4096);
	if (ok && magic >= 0x3548434e) ok = character_read_string(f, character.description, 512) && character_read_string(f, character.history, 1536);
	const bool legacy_crc = magic < 0x3848434e;
	if (ok)
	{
		character.economy = u8(f->get());
		const int initialized = f->get(), respawn = f->get();
		character.initialized = initialized == 1; character.respawn = respawn == 1;
		if (initialized < 0 || initialized > 1 || respawn < 0 || respawn > 1) { return false; }
		ok = character_read_packet(f, character.actor, legacy_crc) && f->read(&count, 4, 1) == 1 && count <= 512;
	}
	for (u32 i = 0; ok && i < count; ++i)
	{
		Character::Item item;
		ok = character_read_string(f, item.section, 128) && f->read(&item.parent, 2, 1) == 1 &&
			item.parent <= i && (magic == 0x3348434e || f->read(&item.place, 2, 1) == 1) &&
			character_read_packet(f, item.spawn, legacy_crc) && (magic < 0x3748434e || character_read_state(f, item.state)) &&
			pSettings->section_exist(item.section.c_str());
		if (ok) character.items.push_back(std::move(item));
	}
	if (ok && magic != 0x3348434e)
	{
		u32 size = 0, crc = 0;
		ok = f->read(&size, 4, 1) == 1 && f->read(&crc, 4, 1) == 1 && size <= 1048576;
		if (ok)
		{
			character.progress.resize(size);
			ok = (!size || f->read(character.progress.data(), 1, size) == size) && character_checksum_matches(character.progress.data(), size, crc, legacy_crc);
		}
	}
    if (ok && magic>=0x3648434e)
    {
        ok=f->read(&character.storage_revision,4,1)==1 && character.storage_revision &&
            character_read_string(f,character.storage_request,32) && character_read_string(f,character.storage_signature,80) &&
            f->read(&count,4,1)==1 && count<=512;
        for (u32 i=0;ok && i<count;++i)
        {
            Character::Item item;
            ok=character_read_string(f,item.section,128) && f->read(&item.parent,2,1)==1 && item.parent<=i &&
                f->read(&item.place,2,1)==1 && character_read_packet(f,item.spawn,legacy_crc) &&
                (magic<0x3748434e || character_read_state(f,item.state)) && pSettings->section_exist(item.section.c_str());
            if (ok) character.safe.push_back(std::move(item));
        }
    }
    if (ok && magic>=0x3948434e) ok=f->read(&character.inventory_cells,4,1)==1 && character.inventory_cells<=512;
    ok=ok && input.remaining==0;

 return ok && character_name_valid(character.name.c_str());
}

static bool character_load_image(LPCSTR account, u8 slot, const void* bytes, size_t size)
{
 Character character;
 character.account = account; character.slot = slot;
 if (!character_decode(bytes, size, character)) return false;
 s_characters[character_key(account, slot)] = std::move(character);
 return true;
}

static Character* character_load(LPCSTR account, u8 slot)
{
 const xr_string key = character_key(account, slot);
 auto cached = s_characters.find(key);
 if (cached != s_characters.end()) return &cached->second;
 string_path path; character_path(account, slot, path);
 FILE* file = fopen(path, "rb");
 if (!file) return nullptr;
 bool ok = fseek(file, 0, SEEK_END) == 0;
 const long size = ok ? ftell(file) : -1;
 ok = ok && size > 0 && size_t(size) <= CharacterSnapshot::limit && fseek(file, 0, SEEK_SET) == 0;
 xr_vector<u8> bytes;
 if (ok) { bytes.resize(size); ok = fread(bytes.data(), 1, bytes.size(), file) == bytes.size() && !ferror(file); }
 fclose(file);
 if (!ok || !character_load_image(account, slot, bytes.data(), bytes.size()))
 {
  Msg("! [Lost Zone] cannot read character slot %u for %s", slot, account);
  return nullptr;
 }
 return &s_characters[key];
}

static bool character_validate_loadout(LPCSTR faction, u8 economy, LPCSTR loadout)
{
	if (economy < 1 || economy > 3 || xr_strlen(faction) > 20 || xr_strlen(loadout) > 4096) return false;
	string_path path;
	if (!FS.exist(path, "$game_config$", "items\\settings\\new_game_loadouts.ltx")) return false;
	CInifile ini(path, TRUE, TRUE, FALSE);
	xr_string section = faction; section += "_loadout";
	if (!ini.section_exist(section.c_str())) return false;
	string64 budget_key;
	xr_sprintf(budget_key, "total_points_eco_%u", economy);
	const float budget = ini.r_float("points", budget_key);
	float used = 0.f;
	// No backpack-cell limit here: freeplay's points already bound the kit,
	// and GAMMA's mandatory items alone fill 29 of the 60 cells - every real
	// kit with two guns and armour was refused ("loadout_save_failed", owner's
	// log 2026-10-10). Over 60 cells the player just cannot pick up more.
	xr_map<xr_string, u32> selected;
	const u32 count = _GetItemCount(loadout);
	if (count > 256) return false;
	for (u32 i = 0; loadout[0] && i < count; ++i)
	{
		string128 item, field;
		_GetItem(loadout, i, item);
		_Trim(item);
		if (!pSettings->section_exist(item) || !ini.line_exist(section.c_str(), item)) return false;
		LPCSTR values = ini.r_string(section.c_str(), item);
		_GetItem(values, 1, field); const u32 available = u32(atoi(field));
		_GetItem(values, 2, field); const float price = float(atof(field));
		if (++selected[item] > available || !_valid(price) || price < 0.f) return false;
		if (_GetItemCount(values) >= 4)
		{
			_GetItem(values, 3, field);
			if (economy > atoi(field)) return false;
		}
		used += price;
		if (used > budget) return false;
	}
	return true;
}

static bool character_select(xrClientData* CL, u8 slot, LPCSTR name, LPCSTR faction, u8 economy, LPCSTR loadout)
{
	// Enforce the allowance from the authenticated server account, never the UI or a cached role.
	if (!CL || slot < 1 || slot > (CL->netcoop_role == role_admin ? 10 : 1)) return false;
	Character* character = character_load(CL->netcoop_login.c_str(), slot);
	if (!character)
	{
		// A damaged existing save must not be replaced by a new empty character.
		string_path existing; character_path(CL->netcoop_login.c_str(),slot,existing);
		if (GetFileAttributesA(existing)!=INVALID_FILE_ATTRIBUTES) return false;
		// A damaged save must never be silently replaced by a fresh character.
		string_path path; character_path(CL->netcoop_login.c_str(), slot, path);
		if (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) return false;
		if (!character_name_valid(name) || !character_validate_loadout(faction, economy, loadout)) return false;
		Character created;
		created.account = CL->netcoop_login.c_str(); created.slot = slot;
		created.name = name; created.faction = faction; created.economy = economy; created.loadout = loadout;
		created.actor.B.count = 0;
		if (!character_save(created)) return false;
		const xr_string key = character_key(created.account.c_str(), slot);
		s_characters[key] = std::move(created);
		character = &s_characters[key];
	}
	CL->netcoop_character_slot = slot;
	CL->netcoop_character_name = character->name.c_str();
	return true;
}

static CloudJson s_drafts = CloudJson::object();
static xr_string s_drafts_owner, s_drafts_file, s_drafts_server, s_drafts_loaded_key;
bool script_draft_server(LPCSTR address)
{
    if (!address || !address[0] || xr_strlen(address) > 128) return false;
    xr_string canonical = address; to_lower(canonical);
    for (unsigned char c : canonical)
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '-' || c == ':')) return false;
    s_drafts_server = canonical; return true;
}
static void drafts_load()
{
    firebase_load();
    if (s_drafts_server.empty()) s_drafts_server = "127.0.0.1:1267";
    const xr_string scope = xr_string(s_firebase_session.uid.c_str()) + "|" + s_drafts_server;
    if (s_drafts_loaded_key == scope) return;
    s_drafts_loaded_key = scope;
    s_drafts_owner = s_firebase_session.uid.c_str(); s_drafts = CloudJson::object();
    u8 digest[32];
    if (!pbkdf2(scope.data(), u32(scope.size()), "characters", 10, 1, digest, sizeof(digest))) return;
    s_drafts_file = "netcoop_drafts_" + to_hex(digest, sizeof(digest)) + ".bin";
    if (!cloud_secret_file(s_drafts_file.c_str(), s_drafts, false) && s_drafts_server == "127.0.0.1:1267")
    {
        // Existing unscoped drafts belong to the original local server only.
        u8 previous[32];
        if (pbkdf2(s_drafts_owner.data(), u32(s_drafts_owner.size()), "characters", 10, 1, previous, sizeof(previous)))
        {
            const xr_string legacy = "netcoop_drafts_" + to_hex(previous, sizeof(previous)) + ".bin";
            if (cloud_secret_file(legacy.c_str(), s_drafts, false)) cloud_secret_file(s_drafts_file.c_str(), s_drafts, true);
        }
    }
}
bool script_save_draft(int slot, LPCSTR name, LPCSTR description, LPCSTR history, LPCSTR faction, int economy, LPCSTR loadout)
{
    drafts_load();
    if (s_drafts_owner.empty() || slot < 1 || slot > 10 || !character_name_valid(name) || !description || !history ||
        xr_strlen(description) > 512 || xr_strlen(history) > 1536 || !faction || !loadout ||
        !character_validate_loadout(faction, u8(economy), loadout)) return false;
    const auto key = std::to_string(slot);
    CloudJson saved = s_drafts;
    saved[key] = {{"name", cloud_convert(name, 1251, CP_UTF8)}, {"description", cloud_convert(description, 1251, CP_UTF8)},
        {"history", cloud_convert(history, 1251, CP_UTF8)}, {"faction", faction}, {"economy", std::to_string(economy)}, {"loadout", loadout}};
    if (!cloud_secret_file(s_drafts_file.c_str(), saved, true)) return false;
    s_drafts = saved;
    return true;
}
LPCSTR script_draft(int slot, LPCSTR field)
{
    static std::string result;
    result.clear(); drafts_load();
    const auto key = std::to_string(slot);
    if (field && slot >= 1 && slot <= 10 && s_drafts.contains(key) && s_drafts[key].is_object())
        result = cloud_convert(cloud_string(s_drafts[key], field), CP_UTF8, 1251);
    return result.c_str();
}
bool script_profile(LPCSTR description, LPCSTR history)
{
    if (!description || !history || xr_strlen(description) > 512 || xr_strlen(history) > 1536) return false;
    s_client_description = description; s_client_history = history;
    return true;
}

static void character_clear_dead_body_state(CSE_Abstract* actor, bool respawn)
{
	if (!respawn) return;
	// Client data contains the old body's conditions/inventory-owner state.
	// Progress is restored separately; a fresh body starts with fresh defaults.
	actor->client_data.clear();
	if (CSE_ALifeCreatureActor* creature = smart_cast<CSE_ALifeCreatureActor*>(actor))
	{
		creature->set_health(1.f);
		// The old body's killer travelled into every new Actor ("server
		// entity has a killer and is not dead" on each respawn).
		creature->set_killer_id(ALife::_OBJECT_ID(-1));
		creature->m_game_death_time = 0;
	}
}

bool server_character_load_actor(xrClientData* CL, CSE_Abstract* actor)
{
	if (!CL || !CL->netcoop_login.size()) return false;
	Character* character = character_load(CL->netcoop_login.c_str(), CL->netcoop_character_slot);
	if (!character) return false;
	if (character->initialized && character->actor.B.count)
	{
		NET_Packet packet = character->actor;
		if (!actor->Spawn_Read(packet)) return false;
		actor->ID = actor->ID_Parent = actor->ID_Phantom = 0xffff;
		actor->m_bALifeControl = false;
		if (CSE_PHSkeleton* skeleton = smart_cast<CSE_PHSkeleton*>(actor)) skeleton->_flags.zero();
		if (CSE_ALifeCreatureActor* creature = smart_cast<CSE_ALifeCreatureActor*>(actor))
		{ creature->m_holderID = 0xffff; creature->m_bOnline = true; }
	}
	character_clear_dead_body_state(actor, character->respawn);
	CSE_ALifeTraderAbstract* trader = smart_cast<CSE_ALifeTraderAbstract*>(actor);
	if (trader)
	{
		trader->m_character_name = character->name;
		trader->m_character_name_str = character->name;
		if (!character->initialized)
		{
			trader->set_character_profile(shared_str((xr_string("actor_") + character->faction).c_str()));
			// Freeplay's starting money for the faction (new_game_loadouts.ltx
			// [<faction>_money]); only while the account has no money yet -
			// money belongs to the account, a second character keeps it.
			Account* account = account_find(CL->netcoop_login.c_str());
			string_path path;
			if (account && !account->has_money && FS.exist(path, "$game_config$", "items\\settings\\new_game_loadouts.ltx"))
			{
				CInifile ini(path, TRUE, TRUE, FALSE);
				const xr_string section = character->faction + "_money";
				if (ini.line_exist(section.c_str(), "money"))
				{
					trader->m_dwMoney = u32(_max(0.f, ini.r_float(section.c_str(), "money")));
					Msg("[Lost Zone] new character '%s': %u RU (%s)", character->name.c_str(), trader->m_dwMoney, section.c_str());
				}
			}
		}
		// The faction may have changed since the Actor was saved (accepted,
		// expelled, renegade; doc 47): the character's faction wins.
		else if (!character->faction.empty())
		{
			const CHARACTER_COMMUNITY_INDEX index = CHARACTER_COMMUNITY::IdToIndex(
				shared_str((xr_string("actor_") + character->faction).c_str()), CHARACTER_COMMUNITY_INDEX(-1), true);
			if (index != CHARACTER_COMMUNITY_INDEX(-1)) trader->m_community_index = index;
		}
	}
	CSE_ALifeCreatureActor* creature = smart_cast<CSE_ALifeCreatureActor*>(actor);
	// Saves from another server map retain inventory and progress, but use
	// that map's arrival point rather than coordinates in a different world.
	const bool same_level = creature && ai().valid_game_vertex(creature->m_tGraphID) &&
		ai().valid_game_vertex(ai().game_graph().current_level_vertex()) &&
		ai().game_graph().vertex(creature->m_tGraphID)->level_id() ==
		ai().game_graph().vertex(ai().game_graph().current_level_vertex())->level_id();
	const bool placed = character->initialized && !character->respawn && same_level &&
		ai().get_level_graph() && ai().level_graph().valid_vertex_id(creature->m_tNodeID) && _valid(creature->o_Position);
	// A saved or arrival point far above or below its level vertex (a level
	// changer's destination, an old save) would put the player in the air or
	// under the ground: stand on the vertex instead (doc 43 H13).
	if (placed)
	{
		const Fvector ground = ai().level_graph().vertex_position(creature->m_tNodeID);
		if (_abs(ground.y - creature->o_Position.y) > 3.f || ground.distance_to_xz(creature->o_Position) > 5.f)
		{
			Msg("[Lost Zone] %s: position %.1f %.1f %.1f is off its level vertex, placed at %.1f %.1f %.1f",
				character->name.c_str(), creature->o_Position.x, creature->o_Position.y, creature->o_Position.z,
				ground.x, ground.y, ground.z);
			creature->o_Position = ground;
		}
	}
	return placed;
}

static bool character_spawn_saved_items(xrServer* server, xrClientData* CL, const Character& character, CharacterRestore& restore)
{
	if (character.items.size() > 512) return false;
	for (u32 i = 0; i < character.items.size(); ++i)
		if (character.items[i].parent > i) return false;
	xr_vector<u16> parents; parents.push_back(CL->owner->ID);
	for (const Character::Item& saved : character.items)
	{
		CSE_Abstract* item = server->game->spawn_begin(saved.section.c_str());
		if (!item) return false;
		NET_Packet packet = saved.spawn;
		if (!item->Spawn_Read(packet)) { F_entity_Destroy(item); return false; }
		item->ID = item->ID_Phantom = 0xffff;
		item->ID_Parent = parents[saved.parent];
		item->s_flags.assign(M_SPAWN_OBJECT_LOCAL);
		CSE_Abstract* spawned = server->game->spawn_end(item, CL->ID);
		if (!spawned) return false;
		item_state_restore(spawned->ID, saved.state);
		restore.entities.push_back(std::make_pair(spawned->ID, parents[saved.parent]));
		parents.push_back(spawned->ID);
		if (!saved.parent && saved.place) restore.places.push_back(std::make_pair(spawned->ID, saved.place));
	}
	return true;
}

void server_character_spawn_items(xrClientData* CL)
{
	if (!CL || !CL->owner || !CL->netcoop_login.size()) return;
	if (s_actor_character.find(CL->owner->ID) != s_actor_character.end()) return;
	CharacterRestore& restore = s_character_restore[CL->owner->ID];
	restore = CharacterRestore(); // IDs may have belonged to an abandoned partial restore
	Character* character = character_load(CL->netcoop_login.c_str(), CL->netcoop_character_slot);
	if (!character) return;
	s_actor_character[CL->owner->ID] = character_key(character->account.c_str(), character->slot);
	xrServer* server = Level().Server;
	if (character->initialized)
	{
		if (!character_spawn_saved_items(server, CL, *character, restore))
		{
			Msg("! [Lost Zone] inventory restore incomplete for actor %u; preserving saved character", CL->owner->ID);
			return;
		}
	}
	else
	{
		const u32 count = _GetItemCount(character->loadout.c_str());
		for (u32 i = 0; character->loadout.size() && i < count; ++i)
		{
			string128 section; _GetItem(character->loadout.c_str(), i, section); _Trim(section);
			CSE_Abstract* item = server->game->spawn_begin(section);
			if (!item) return;
			item->ID_Parent = CL->owner->ID;
			item->s_flags.assign(M_SPAWN_OBJECT_LOCAL);
			CSE_Abstract* spawned = server->game->spawn_end(item, CL->ID);
			if (!spawned) return;
			restore.entities.push_back(std::make_pair(spawned->ID, CL->owner->ID));
		}
		// Match freeplay's ammunition allowance for each selected firearm.
        string_path path;
        if (FS.exist(path, "$game_config$", "items\\settings\\new_game_loadouts.ltx"))
        {
            CInifile ini(path, TRUE, TRUE, FALSE);
            for (u32 i = 0; character->loadout.size() && i < count; ++i)
            {
                string128 weapon, ammo; _GetItem(character->loadout.c_str(), i, weapon); _Trim(weapon);
                if (!pSettings->line_exist(weapon, "ammo_class") || !pSettings->line_exist(weapon, "slot")) continue;
                const u32 slot = pSettings->r_u32(weapon, "slot");
                if (slot != 1 && slot != 2 && !(slot == 0 && pSettings->line_exist(weapon, "animation_slot") && pSettings->r_u32(weapon, "animation_slot") == 1)) continue;
                _GetItem(pSettings->r_string(weapon, "ammo_class"), 0, ammo); _Trim(ammo);
                if (ini.line_exist("ammo_type_per_wpn", weapon)) xr_strcpy(ammo, ini.r_string("ammo_type_per_wpn", weapon));
                if (!pSettings->section_exist(ammo)) continue;
                const u32 box = pSettings->line_exist(ammo, "box_size") ? pSettings->r_u32(ammo, "box_size") : 50;
                u32 remaining = ini.line_exist("ammo_count", ammo) ? ini.r_u32("ammo_count", ammo) : (box < 30 ? box * 2 : box);
                // freeplay's whole allowance (the backpack cells do not cut it)
                while (remaining && box)
                {
                    CSE_Abstract* item = server->game->spawn_begin(ammo);
                    if (!item) return;
                    CSE_ALifeItemAmmo* bullets = smart_cast<CSE_ALifeItemAmmo*>(item);
                    if (!bullets) { F_entity_Destroy(item); return; }
                    bullets->a_elapsed = u16(_min(remaining, box)); remaining -= bullets->a_elapsed;
                    item->ID_Parent = CL->owner->ID; item->s_flags.assign(M_SPAWN_OBJECT_LOCAL);
                    CSE_Abstract* spawned = server->game->spawn_end(item, CL->ID);
                    if (!spawned) return;
                    restore.entities.push_back(std::make_pair(spawned->ID, CL->owner->ID));
                }
            }
        }
        character->initialized = true;
	}
	restore.inventory_complete = true;
	Msg("[Lost Zone] character '%s' slot %u loaded for %s", character->name.c_str(), character->slot, character->account.c_str());
}

// Refuse the whole checkpoint before clearing the previous inventory. The
// capture below has finite depth/count limits; silently skipping one child
// would otherwise lose that item on the next login or location transition.
static bool character_inventory_complete(xrServer* server, CSE_Abstract* parent, u32 depth, xr_vector<u16>& visited)
{
	if (!parent) return false;
	if (depth > 8) return parent->children.empty();
	for (u16 id : parent->children)
	{
		if (id == 0xffff || visited.size() >= 513 || std::find(visited.begin(), visited.end(), id) != visited.end()) return false;
		CSE_Abstract* item = server->game->get_entity_from_eid(id);
		if (item && item->ID == id && storage_launcher_charge(item, parent->ID)) continue;
		if (!item || item->ID != id || item->ID_Parent != parent->ID || !smart_cast<CSE_ALifeInventoryItem*>(item)) return false;
		// A runtime child can attach before the budgeted item scan applies its
		// saved UID/portions. Keep the previous snapshot until that scan finishes.
		if (!item_state_ready_for_save(id)) return false;
		visited.push_back(id);
		if (!character_inventory_complete(server, item, depth + 1, visited)) return false;
	}
	return true;
}

static void character_capture_items(xrServer* server, Character& character, CSE_Abstract* parent, u16 parent_index, u32 depth)
{
	if (depth > 8) return;
	for (u16 id : parent->children)
	{
		CSE_Abstract* item = server->game->get_entity_from_eid(id);
		if (!item || character.items.size() >= 512 || !smart_cast<CSE_ALifeInventoryItem*>(item)) continue;
		if (CInventoryItem* runtime = smart_cast<CInventoryItem*>(Level().Objects.net_Find(id)))
		{
			if (CSE_ALifeInventoryItem* saved = smart_cast<CSE_ALifeInventoryItem*>(item))
			{ saved->m_fCondition = runtime->GetCondition(); saved->m_upgrades = runtime->get_upgrades(); }
			if (CWeapon* weapon = smart_cast<CWeapon*>(Level().Objects.net_Find(id)))
				if (CSE_ALifeItemWeapon* saved = smart_cast<CSE_ALifeItemWeapon*>(item))
				{ saved->a_elapsed = u16(weapon->GetAmmoElapsed()); saved->ammo_type = weapon->GetAmmoType(); saved->m_addon_flags.flags = weapon->GetAddonsState(); }
		}
		Character::Item record;
		record.parent = parent_index; record.section = item->s_name.c_str();
		if (CInventoryItem* runtime = smart_cast<CInventoryItem*>(Level().Objects.net_Find(id))) record.place = runtime->m_ItemCurrPlace.value;
		item->Spawn_Write(record.spawn, TRUE);
		item_state_for_save(id, record.state);
		character.items.push_back(std::move(record));
		const u16 index = u16(character.items.size());
		character_capture_items(server, character, item, index, depth + 1);
	}
}

// A level changer's arrival point on another map (netcoop_cluster.inc).
struct CharacterDestination { GameGraph::_GRAPH_ID game_vertex; u32 level_vertex; Fvector position, angles; };

static Character* character_tracked_for_save(u16 actor_id)
{
	if (s_character_restore.find(actor_id) != s_character_restore.end()) return nullptr;
	const auto key = s_actor_character.find(actor_id);
	if (key == s_actor_character.end()) return nullptr;
	const auto found = s_characters.find(key->second);
	return found == s_characters.end() ? nullptr : &found->second;
}

// Captures the Actor into its character and writes the file; with a
// destination the saved position is that point instead of the current one.
static bool character_save_actor(u16 actor_id, const CharacterDestination* destination, bool background = false)
{
	Character* tracked = character_tracked_for_save(actor_id);
	if (!tracked || !g_pGameLevel || !Level().Server) return false;
	// Items taken from the world since the last world commit: writing the
	// character first would duplicate them if the server died before the
	// world was saved (on the ground again and in the inventory). Background
	// saves wait for the world save (requested now); a final save (logout,
	// level changer) saves the world first.
	if (!world_store_takes_committed(actor_id))
	{
		if (background) { world_store_request_save(); return false; }
		world_store_save_now("player items");
		if (!world_store_takes_committed(actor_id)) Msg("! [Lost Zone] world save before character save failed; saving the character anyway");
	}
	Character& character = *tracked;
	xrServer* server = Level().Server;
	CSE_Abstract* actor = server->game->get_entity_from_eid(actor_id);
	CActor* runtime = smart_cast<CActor*>(Level().Objects.net_Find(actor_id));
	CSE_ALifeCreatureActor* entity = smart_cast<CSE_ALifeCreatureActor*>(actor);
	if (!entity || !runtime) return false;
	if (runtime->g_Alive())
	{
		xr_vector<u16> visited; visited.push_back(actor_id);
		if (!character_inventory_complete(server, actor, 0, visited))
		{
				Msg("[Lost Zone] character save refused: inventory tree/state is incomplete, cyclic, or exceeds capture limits (actor %u)", actor_id);
			return false;
		}
	}
	if (!character_capture_progress(character, runtime)) return false;
	entity->m_dwMoney = runtime->get_money();
	entity->m_rank = runtime->Rank(); entity->m_reputation = runtime->Reputation();
	entity->o_Position = runtime->Position();
	if (ai().valid_game_vertex(runtime->ai_location().game_vertex_id()))
		entity->m_tGraphID = runtime->ai_location().game_vertex_id();
	if (ai().get_level_graph())
		entity->m_tNodeID = ai().level_graph().vertex_id(runtime->Position());
	character.respawn = !runtime->g_Alive();
	character.items.clear();
	if (runtime->g_Alive()) character_capture_items(server, character, actor, 0, 0);
	const Fvector position = entity->o_Position, angles = entity->o_Angle;
	const SRotation torso = entity->o_torso;
	const GameGraph::_GRAPH_ID graph = entity->m_tGraphID;
	const u32 node = entity->m_tNodeID;
	if (destination)
	{
		entity->o_Position = destination->position; entity->o_Angle = destination->angles;
		entity->m_tGraphID = destination->game_vertex; entity->m_tNodeID = destination->level_vertex;
		entity->o_torso.yaw = destination->angles.y; entity->o_torso.pitch = destination->angles.x; entity->o_torso.roll = 0.f;
	}
	// A dead character resumes alive; its former inventory stays in the world.
	const float health = entity->get_health();
	entity->set_health(runtime->g_Alive() ? runtime->GetfHealth() : 1.f);
	actor->Spawn_Write(character.actor, TRUE);
	entity->set_health(health);
	if (destination)
	{
		entity->o_Position = position; entity->o_Angle = angles; entity->o_torso = torso;
		entity->m_tGraphID = graph; entity->m_tNodeID = node;
	}
	character.inventory_cells = storage_live_capacity(runtime);
	character.initialized = true;
    if (character.storage_revision!=0xffffffffu) ++character.storage_revision;
	if (character_save(character, background)) return true;
	Msg("! [Lost Zone] character save failed for %s slot %u", character.account.c_str(), character.slot);
	return false;
}

void server_character_save_actor(u16 actor_id) { character_save_actor(actor_id, nullptr, true); }

static void characters_restore_update()
{
	for (auto it = s_character_restore.begin(); it != s_character_restore.end();)
	{
		const u32 now = real_time_ms();
		if (!it->second.clock_started) { it->second.since = now; it->second.clock_started = true; }
		if (!it->second.rejected && u32(now - it->second.since) >= 60000)
		{
			it->second.rejected = true;
			Msg("! [Lost Zone] character %u restore timed out: inventory_complete=%u, expected_items=%u; keeping previous checkpoint",
				it->first, u32(it->second.inventory_complete), u32(it->second.entities.size()));
			character_restore_timeout(it->first);
		}
		if (it->second.rejected) { ++it; continue; }
		CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(it->first));
		if (!actor) { ++it; continue; }
		if (!it->second.inventory_complete) { ++it; continue; }
		bool ready = true;
		for (const auto& expected : it->second.entities)
		{
			CGameObject* item = smart_cast<CGameObject*>(Level().Objects.net_Find(expected.first));
			if (!item || !item->H_Parent() || item->H_Parent()->ID() != expected.second ||
				!item_state_ready_for_save(expected.first)) { ready = false; break; }
		}
		if (!ready) { ++it; continue; }
		const auto key = s_actor_character.find(actor->ID());
		if (key == s_actor_character.end()) { ++it; continue; }
		const auto character = s_characters.find(key->second);
		if (character == s_characters.end()) { ++it; continue; }
		if (it->second.attempted && u32(now - it->second.last_attempt) < 1000) { ++it; continue; }
		it->second.attempted = true; it->second.last_attempt = now;
		if (!character_restore_progress(character->second, actor))
		{
			Msg("! [Lost Zone] progress restore still pending for actor %u; gameplay and saving held", actor->ID());
			++it; continue;
		}
		// Clear automatic spawn placements, then restore slots before the belt
		// so the outfit's capacity is available to equipped artefacts.
		for (u32 pass = 0; pass < 3; ++pass)
			for (const auto& value : it->second.places)
			{
				SInvItemPlace place; place.value = value.second;
				if (pass == 1 && place.type != eItemPlaceSlot) continue;
				if (pass == 2 && place.type != eItemPlaceBelt) continue;
				NET_Packet packet;
				CGameObject::u_EventGen(packet, pass == 0 ? GEG_PLAYER_ITEM2RUCK : pass == 1 ? GEG_PLAYER_ITEM2SLOT : GEG_PLAYER_ITEM2BELT, actor->ID());
				packet.w_u16(value.first);
				if (pass == 1) { packet.w_u16(place.slot_id); packet.w_u8(1); }
				CGameObject::u_EventSend(packet);
			}
		it = s_character_restore.erase(it);
	}
}

static void characters_update(xrServer* server)
{
	characters_restore_update();
	struct Save
	{
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (!CL->owner || !CL->netcoop_login.size()) return;
			Character* character = character_load(CL->netcoop_login.c_str(), CL->netcoop_character_slot);
			if (character && real_time_ms() - character->last_save >= 20000) server_character_save_actor(CL->owner->ID);
		}
	} save;
	server->ForEachClientDo(save);
}
