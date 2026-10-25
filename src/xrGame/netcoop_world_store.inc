// W1 (doc 41): the world survives server restarts.
//
// Before: the server always started a new game ("server(all/.../alife/new)"),
// so every restart or crash rebuilt the world from the spawn: dead NPCs came
// back, corpses, dropped items, furniture, stashes and campfires were gone,
// containers were refilled and the world clock started over. Characters
// survived only because they live in their own files.
//
// Now, with -netcoop_world=<name>, the server saves the whole ALife world
// (the engine's own save: time, every entity online and offline, registries,
// GAMMA's script state) every 5 minutes and when the last player leaves, and
// starts from the newest complete save instead of a new game.
// - Two slots, <name>_a and <name>_b, are written in turn; a pointer file
//   <name>.current names the newest complete one and is replaced atomically
//   after the save. A crash while saving leaves the previous world intact.
// - Players are not part of the world: their characters come from their
//   own files. Living player Actors found in a loaded world (they were
//   online when it was saved) are released with everything they carried,
//   before anyone can see them; dead players' bodies stay as corpses.
// - The world clock continues from the saved time (owner's choice pending:
//   whether offline real time should pass; doc 41 section 21).

// Crash tests (doc 43 G13): -netcoop_world_crash=<point> ends the process at
// that point of a save, as a kill or power loss would; the next start must
// load the last complete commit. Points: before_alife, after_alife,
// pointer_temp, after_pointer. scripts/run-world-crash-test.ps1 uses them.
static void world_store_crash_point(LPCSTR point)
{
	LPCSTR option = strstr(Core.Params, "-netcoop_world_crash=");
	if (!option) return;
	string64 wanted = "";
	sscanf_s(option + xr_strlen("-netcoop_world_crash="), "%63[a-z_]", wanted, (unsigned)sizeof(wanted));
	if (xr_strcmp(wanted, point)) return;
	Msg("[NetAnomaly][world] crash test: terminating at %s", point);
	FlushLog();
	TerminateProcess(GetCurrentProcess(), 3);
}

// -netcoop_world_save_period=<seconds> (tests); 5 minutes otherwise.
static u32 world_store_period_ms()
{
	static u32 period = 0;
	if (!period)
	{
		u32 seconds = 0;
		LPCSTR option = strstr(Core.Params, "-netcoop_world_save_period=");
		if (option) sscanf_s(option + xr_strlen("-netcoop_world_save_period="), "%u", &seconds);
		period = seconds >= 5 ? seconds * 1000 : 300000;
	}
	return period;
}

static const u32 world_save_period_ms = 300000;
static bool s_world_loaded = false;
static bool s_world_cleanup_pending = false;
static u32 s_world_last_save = 0;
static bool world_store_name(string64& out);
static u32 s_world_commits = 0;              // successful world commits in this process
static bool s_world_save_requested = false;   // a character waits for a world commit
static xr_map<u16, u32> s_world_taken;        // player Actor -> commit count when it took an item

static void world_store_note_taken(u16 actor_id) { s_world_taken[actor_id] = s_world_commits; }
static void world_store_request_save() { s_world_save_requested = true; }
static bool world_store_takes_committed(u16 actor_id)
{
	string64 world;
	if (!world_store_name(world)) return true; // no persistent world: nothing to order
	auto taken = s_world_taken.find(actor_id);
	return taken == s_world_taken.end() || s_world_commits > taken->second;
}
static u32 s_world_previous_players = 0;
static bool s_world_committed = false;
static u32 s_world_last_attempt = 0;
static const u32 world_save_retry_ms = 15000;

struct WorldSnapshotDigest
{
	u64 bytes = 0;
	u64 hash = 14695981039346656037ULL;
	bool recorded = false;
};

static bool world_store_name(string64& out)
{
	out[0] = 0;
	LPCSTR option = strstr(Core.Params, "-netcoop_world=");
	if (!option || !enabled() || pure_client()) return false;
	option += xr_strlen("-netcoop_world=");
	u32 length = 0;
	while (option[length] && option[length] != ' ' && option[length] != '\t' && option[length] != '\r' && option[length] != '\n')
	{
		// Reserve "_a" / "_b" and a terminator. Never silently truncate
		// names: two different worlds must not alias the same save slots.
		if (length + 3 >= sizeof(out)) return false;
		const char c = option[length];
		if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')) return false;
		out[length] = c;
		++length;
	}
	out[length] = 0;
	return length > 0;
}

static void world_store_pointer_path(LPCSTR world, string_path& path)
{
	string128 file;
	xr_sprintf(file, "%s.current", world);
	FS.update_path(path, "$game_saves$", file);
}

static bool world_store_native_exists(LPCSTR path)
{
	// Native fopen writes are not guaranteed to be in the engine's VFS cache.
	return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
}

static bool world_store_read_pointer(LPCSTR world, string64& save, WorldSnapshotDigest* digest = nullptr,
	WorldSnapshotDigest* script_digest = nullptr)
{
	save[0] = 0;
	string_path path;
	world_store_pointer_path(world, path);
	FILE* f = fopen(path, "rb");
	if (!f) return false;
	char content[256] = {};
	const size_t read = fread(content, 1, sizeof(content) - 1, f);
	const bool complete = fgetc(f) == EOF && !ferror(f);
	const bool closed = fclose(f) == 0;
	if (!complete || !closed || !read || memchr(content, 0, read)) return false;
	const char* newline = strchr(content, '\n');
	const size_t first_line = newline ? size_t(newline - content) : read;
	if (first_line >= sizeof(save)) return false;
	memcpy(save, content, first_line);
	save[first_line] = 0;
	if (first_line && save[first_line - 1] == '\r') save[first_line - 1] = 0;
	if (strchr(save, '\r')) return false;
	// Only this world's two slots are valid: a damaged pointer must never
	// select another world or an arbitrary save path.
	string64 slot_a, slot_b;
	xr_sprintf(slot_a, "%s_a", world);
	xr_sprintf(slot_b, "%s_b", world);
	if (xr_strcmp(save, slot_a) != 0 && xr_strcmp(save, slot_b) != 0) return false;
	WorldSnapshotDigest parsed;
	WorldSnapshotDigest script;
	if (newline && newline[1])
	{
		unsigned long long bytes = 0, hash = 0;
		unsigned long long script_bytes = 0, script_hash = 0;
		char line_end = 0, extra = 0;
		if (strncmp(newline + 1, "LZW3 ", 5) == 0)
		{
			if (sscanf(newline + 1, "LZW3 %llu %llx %llu %llx%c%c", &bytes, &hash,
				&script_bytes, &script_hash, &line_end, &extra) != 5 || !script_bytes) return false;
			script.bytes = script_bytes; script.hash = script_hash; script.recorded = true;
		}
		else if (sscanf(newline + 1, "LZW2 %llu %llx%c%c", &bytes, &hash, &line_end, &extra) != 3) return false;
		if (!bytes || line_end != '\n') return false;
		parsed.bytes = bytes; parsed.hash = hash; parsed.recorded = true;
	}
	if (digest) *digest = parsed;
	if (script_digest) *script_digest = script;
	return true;
}

static void world_store_snapshot_path(LPCSTR save, LPCSTR extension, string_path& path)
{
	string128 file;
	xr_sprintf(file, "%s%s", save, extension);
	// GAMMA's before_save callback lowercases the script sidecar basename.
	if (xr_strcmp(extension, ".scoc") == 0)
		for (char* c = file; *c; ++c) if (*c >= 'A' && *c <= 'Z') *c = char(*c + ('a' - 'A'));
	FS.update_path(path, "$game_saves$", file);
}

static bool world_store_snapshot_digest(LPCSTR save, WorldSnapshotDigest& digest, bool flush,
	LPCSTR extension = SAVE_EXTENSION)
{
	string_path path;
	world_store_snapshot_path(save, extension, path);
	FILE* f = fopen(path, flush ? "rb+" : "rb");
	if (!f) return false;
	digest = {};
	unsigned char buffer[65536];
	size_t read;
	while ((read = fread(buffer, 1, sizeof(buffer), f)) != 0)
	{
		digest.bytes += read;
		for (size_t i = 0; i < read; ++i) { digest.hash ^= buffer[i]; digest.hash *= 1099511628211ULL; }
	}
	const bool checked = !ferror(f) && digest.bytes > 0 &&
		(!flush || _commit(_fileno(f)) == 0);
	const bool closed = fclose(f) == 0;
	digest.recorded = checked && closed;
	return digest.recorded;
}

static bool world_store_write_pointer(LPCSTR world, LPCSTR save)
{
	string_path path, temp;
	world_store_pointer_path(world, path);
	WorldSnapshotDigest digest, script;
	if (!world_store_snapshot_digest(save, digest, true) ||
		!world_store_snapshot_digest(save, script, true, ".scoc")) return false;
	xr_sprintf(temp, "%s.tmp", path);
	FILE* f = fopen(temp, "wb");
	if (!f) return false;
	string256 manifest;
	xr_sprintf(manifest, "%s\nLZW3 %llu %llx %llu %llx\n", save,
		static_cast<unsigned long long>(digest.bytes), static_cast<unsigned long long>(digest.hash),
		static_cast<unsigned long long>(script.bytes), static_cast<unsigned long long>(script.hash));
	const bool written = fwrite(manifest, 1, xr_strlen(manifest), f) == xr_strlen(manifest) && fflush(f) == 0 && _commit(_fileno(f)) == 0;
	const bool closed = fclose(f) == 0;
	world_store_crash_point("pointer_temp");
	return written && closed && MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}

// CALifeSimulator constructor: load the newest saved world instead of a new game.
bool world_store_choose_start(LPSTR game_or_spawn, u32 game_size, LPSTR new_or_load, u32 mode_size)
{
	string64 world, save;
	if (!world_store_name(world)) return false;
	s_world_loaded = false;
	s_world_cleanup_pending = false;
	s_world_last_save = s_world_previous_players = 0;
	s_world_committed = false;
	s_world_last_attempt = 0;
	WorldSnapshotDigest expected, expected_script;
	if (!world_store_read_pointer(world, save, &expected, &expected_script))
	{
		string_path path;
		world_store_pointer_path(world, path);
		string128 a, b;
		xr_sprintf(a, "%s_a%s", world, SAVE_EXTENSION);
		xr_sprintf(b, "%s_b%s", world, SAVE_EXTENSION);
		string_path path_a, path_b;
		FS.update_path(path_a, "$game_saves$", a);
		FS.update_path(path_b, "$game_saves$", b);
		CHECK_OR_EXIT(!world_store_native_exists(path) && !world_store_native_exists(path_a) && !world_store_native_exists(path_b),
			"Persistent world pointer is missing/corrupt; recovery required. Refusing to create a new world.");
		Msg("[NetAnomaly][world] '%s': no saved world yet, starting a new one", world);
		return false;
	}
	string128 file;
	xr_sprintf(file, "%s%s", save, SAVE_EXTENSION);
	string_path snapshot_path;
	FS.update_path(snapshot_path, "$game_saves$", file);
	if (!world_store_native_exists(snapshot_path))
	{
		CHECK_OR_EXIT(false, "Committed world snapshot is missing; recovery required");
	}
	if (expected.recorded)
	{
		WorldSnapshotDigest actual;
		CHECK_OR_EXIT(world_store_snapshot_digest(save, actual, false) &&
			actual.bytes == expected.bytes && actual.hash == expected.hash,
			"Committed world snapshot checksum mismatch; recovery required");
	}
	else Msg("[NetAnomaly][world] '%s': legacy snapshot has no checksum; next commit upgrades it", world);
	WorldSnapshotDigest actual_script;
	CHECK_OR_EXIT(world_store_snapshot_digest(save, actual_script, false, ".scoc"),
		"World script state is missing/empty; refusing to reset NPC/stash state during legacy migration");
	if (expected_script.recorded)
	{
		CHECK_OR_EXIT(actual_script.bytes == expected_script.bytes && actual_script.hash == expected_script.hash,
			"Committed world script state is missing/corrupt; recovery required");
	}
	xr_strcpy(game_or_spawn, game_size, save);
	xr_strcpy(new_or_load, mode_size, "load");
	s_world_loaded = true;
	s_world_committed = true;
	s_world_cleanup_pending = true;
	Msg("[NetAnomaly][world] '%s': loading saved world %s", world, save);
	return true;
}

// Living player Actors saved with the world (they were online then) are
// released with their inventories: the players come back from their files.
bool world_store_cleanup_pending()
{
	return s_world_cleanup_pending;
}

void world_store_cleanup_loaded()
{
	if (!s_world_cleanup_pending || !ai().get_alife()) return;
	s_world_cleanup_pending = false;
	CALifeSimulator* sim = const_cast<CALifeSimulator*>(ai().get_alife());
	CSE_ALifeCreatureActor* story = sim->graph().actor();
	xr_vector<CSE_ALifeDynamicObject*> players;
	// The mutable objects() overload is protected; the public const registry
	// is sufficient while collecting ids, before any release mutates it.
	for (const auto& entry : static_cast<const CALifeSimulator*>(sim)->objects().objects())
	{
		CSE_ALifeCreatureActor* actor = smart_cast<CSE_ALifeCreatureActor*>(entry.second);
		if (actor && actor != story && actor->get_health() > 0.f) players.push_back(entry.second);
	}
	for (CSE_ALifeDynamicObject* actor : players)
	{
		Msg("[NetAnomaly][world] released player Actor %u from the saved world (%u items)", actor->ID, u32(actor->children.size()));
		if (actor->m_bOnline)
			sim->switch_offline(actor);
		sim->release(actor, true);
	}
}

bool world_store_save_now(LPCSTR reason)
{
	ProfileScope profile(prof_io);
	string64 world;
	if (!world_store_name(world) || !ai().get_alife() || !g_pGameLevel) return false;
	s_world_last_attempt = real_time_ms();
	string64 save, previous, slot_a;
	xr_sprintf(slot_a, "%s_a", world);
	// Derive the next slot from the committed pointer, not a process-local
	// counter reset by restart. Never overwrite the last committed snapshot,
	// including after a failed save or a failed pointer replacement.
	const bool has_pointer = world_store_read_pointer(world, previous);
	if (!has_pointer)
	{
		string_path path;
		world_store_pointer_path(world, path);
		if (s_world_committed || world_store_native_exists(path))
		{
			Msg("! [NetAnomaly][world] refusing save: committed pointer is corrupt/inaccessible");
			return false;
		}
	}
	const bool current_a = has_pointer && xr_strcmp(previous, slot_a) == 0;
	xr_sprintf(save, "%s_%c", world, current_a ? 'b' : 'a');
	// The engine writes GAMMA state before writing the ALife snapshot. Remove
	// only the inactive slot's sidecar first: a callback that silently fails
	// must not commit a stale sidecar left by an older save of this slot.
	string_path script_path;
	world_store_snapshot_path(save, ".scoc", script_path);
	FILE* old_script = fopen(script_path, "rb");
	if (old_script)
	{
		fclose(old_script);
		if (remove(script_path) != 0)
		{
			Msg("! [NetAnomaly][world] cannot clear inactive script snapshot %s", script_path);
			return false;
		}
	}
	CTimer timer;
	timer.Start();
	// No Level().ClientSend()/ClientSave() here: the single-player client
	// save sends M_SAVE_PACKET, which the netcoop server rejects anyway, and
	// on the dedicated server it faulted inside Objects_net_Save before the
	// first packet, so every world save failed (2026-10-06 selftest). The
	// ALife snapshot is taken from the server entities.
	LPCSTR stage = "physics props";
	world_store_crash_point("before_alife");
	try
	{
		if (!world_store_capture_physics_props()) return false;
		stage = "alife snapshot";
		const_cast<CALifeSimulator*>(ai().get_alife())->save(save, false);
	}
	catch (const std::exception& e)
	{
		Msg("! [NetAnomaly][world] saving %s failed (%s) at %s: %s", save, reason, stage, e.what());
		return false;
	}
	catch (...)
	{
		Msg("! [NetAnomaly][world] saving %s failed (%s) at %s", save, reason, stage);
		return false;
	}
	world_store_crash_point("after_alife");
	// GAMMA ignores some Lua file-write errors. Verify the exact encoded data,
	// not merely a nonempty/stale sidecar, before committing the pair.
	::luabind::functor<bool> script_snapshot_ready;
	bool snapshot_matches = false;
	if (ai().script_engine().functor("zz_netcoop_world_rules.script_snapshot_matches", script_snapshot_ready))
	{
		// A Lua error here is a failed check, not a server crash.
		try { snapshot_matches = script_snapshot_ready(save); }
		catch (...) { snapshot_matches = false; }
	}
	if (!snapshot_matches)
	{
		Msg("! [NetAnomaly][world] incomplete script snapshot %s; keeping the previous commit", save);
		return false;
	}
	if (!world_store_write_pointer(world, save))
	{
		Msg("! [NetAnomaly][world] saved %s but could not point %s.current to it", save, world);
		return false;
	}
	world_store_crash_point("after_pointer");
	s_world_last_save = real_time_ms();
	s_world_committed = true;
	++s_world_commits;
	s_world_save_requested = false;
	Msg("[NetAnomaly][world] saved %s (%s) in %u ms", save, reason, timer.GetElapsed_ms());
	return true;
}

// Every server_update: periodic save, and one when the last player leaves.
// Logins wait for the first committed world (a persistent world only).
bool world_store_admission_open()
{
	string64 world;
	return !world_store_name(world) || (s_world_committed && !s_world_cleanup_pending);
}

static void world_store_update(xrServer* server)
{
	string64 world;
	if (!world_store_name(world) || !ai().get_alife()) return;
	struct CountPlayers
	{
		xrServer* server; u32 count;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (CL != server->GetServerClient() && CL->owner) ++count;
		}
	} counter = {server, 0};
	server->ForEachClientDo(counter);
	const u32 now = real_time_ms();
	if (!s_world_last_save) s_world_last_save = now;
	// A new world is committed once before any player is admitted (doc 43
	// G12): 30 s after start, when the initial population is in place.
	if (!s_world_committed)
	{
		if (now - s_world_last_save >= 30000 && now - s_world_last_attempt >= world_save_retry_ms)
			world_store_save_now("bootstrap");
		s_world_previous_players = counter.count;
		return;
	}
	if (counter.count == 0 && s_world_previous_players > 0) world_store_save_now("last player left");
	// Characters with items from the world wait for this; at most once a minute.
	else if (s_world_save_requested && now - s_world_last_save >= 60000 &&
		now - s_world_last_attempt >= world_save_retry_ms) world_store_save_now("player items");
	else if (now - s_world_last_save >= world_store_period_ms() &&
		now - s_world_last_attempt >= world_save_retry_ms) world_store_save_now("periodic");
	s_world_previous_players = counter.count;
}
