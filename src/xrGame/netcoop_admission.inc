// Included inside namespace netcoop in netcoop.cpp, after the cluster.
// M2b (doc 135): with a location writer configuration from the server panel
// the world master is the primary store of player characters. The local
// character file stays the working copy and the fallback without a master.
static netcoop_world::AdmissionCoordinator s_admission;
static bool s_admission_started = false, s_admission_ready_logged = false, s_admission_failed_logged = false;
static u64 s_admission_retry = 0;
static u64 s_admission_diagnostic_at = 0;
static bool s_admission_announced_ready = false;

static bool admission_store_record(LPCSTR operation,LPCSTR bucket,LPCSTR key,LPCSTR expected,LPCSTR value,xr_string& output,bool& swapped)
{
	std::string bytes;
	const bool ok=s_admission.store_record(operation,bucket,key,expected,value,bytes,swapped);
	if(ok) output.assign(bytes.data(),bytes.size());
	else Msg("! [diag][storage] operation=%s bucket=%s key=%s unavailable; no local write",operation,bucket,key ? key:"");
	return ok;
}

static bool admission_active() { return s_admission_started; }
static bool admission_ready() { return s_admission_started && s_admission.status().ready; }

// accounts.inc: the world master's accounts (doc 154).
static bool admission_accounts_take(std::vector<netcoop_world::AccountRecord>& changed, netcoop_world::AccountsState& state)
{
	changed.clear();
	state = netcoop_world::AccountsState::Waiting;
	return s_admission_started && s_admission.accounts_take(changed, state);
}

static bool admission_accounts_put(const std::vector<netcoop_world::AccountRecord>& records, bool only_new)
{
	return s_admission_started && !records.empty() && s_admission.accounts_put(records.data(), records.size(), only_new);
}
static void world_orders_update();

static void admission_update()
{
	if (!g_pGameLevel || !Level().Server) return;
	if (!s_admission_started)
	{
		if (!s_master_required) return; // a single server without a master keeps its local files
		const u64 now = GetTickCount64();
		if (s_admission_retry && now - s_admission_retry < 10000) return;
		s_admission_retry = now;
		LPCSTR map = *Level().name();
		if (!map || !map[0]) return;
		string_path config, spool;
		string128 name;
		xr_sprintf(name, "netcoop_world_writer_%s.json", map);
		FS.update_path(config, "$app_data_root$", name);
		if (GetFileAttributesA(config) == INVALID_FILE_ATTRIBUTES) {
			Msg("! [diag][admission] writer configuration missing map=%s port=%u path=%s; start or repair the native master",map,cluster_port(),config);return;
		}
		xr_sprintf(name, "netcoop_checkpoint_spool_%s", map);
		FS.update_path(spool, "$app_data_root$", name);
		wchar_t wide[520] = {};
		if (!MultiByteToWideChar(CP_ACP, 0, spool, -1, wide, 519)) return;
		s_admission_started = s_admission.start(config, map, wide);
		if (s_admission_started)
			Msg("[Lost Zone][master] characters of map %s are kept by the world master (location writer configured)", map);
		return;
	}
	const netcoop_world::CoordinatorStatus status = s_admission.status();
	if(status.ready) accounts_load(); // prime account mirror before advertising this map
	const bool join_ready=status.ready && s_accounts_master && master_ready() && world_store_admission_open();
	const u64 diagnostic_now=GetTickCount64();
	if (!s_admission_diagnostic_at || diagnostic_now-s_admission_diagnostic_at>=15000 || s_admission_announced_ready!=join_ready)
	{
		s_admission_announced_ready=join_ready;
		s_admission_diagnostic_at=diagnostic_now;
		Msg("[diag][admission] map=%s port=%u ready=%u failed=%u phase=%s http=%u attempts=%u epoch=%llu fence=%llu characters=%u pending=%u",
			*Level().name(),cluster_port(),status.ready,status.failed,status.phase,status.http_status,status.attempts,status.epoch,status.fence,status.characters,status.pending);
		string_path folder,path;cluster_dir(folder);
		xr_sprintf(path,"%sadmission_%u.json",folder,cluster_port());
		string1024 record;
		xr_sprintf(record,"{\"updated\":%u,\"pid\":%u,\"map\":\"%s\",\"ready\":%s,\"failed\":%s,\"phase\":\"%s\",\"http\":%u,\"attempts\":%u,\"epoch\":%llu}",
			cluster_now(),GetCurrentProcessId(),*Level().name(),join_ready ? "true":"false",status.failed ? "true":"false",status.phase,status.http_status,status.attempts,status.epoch);
		cluster_write_line(path,record,false);
	}
	world_orders_update();
	if (status.ready && !s_admission_ready_logged)
	{
		s_admission_ready_logged = true;
		Msg("[Lost Zone][master] location lease taken (fence %llu, epoch %llu): players are admitted through the world master",
			status.fence, status.epoch);
	}
	if (status.failed && !s_admission_failed_logged)
	{
		s_admission_failed_logged = true;
		Msg("! [Lost Zone][master] the location could not take its lease: phase=%s http=%u; connection will be retried automatically",status.phase,status.http_status);
	}
	if (status.ready) s_admission_failed_logged=false;
}

void server_admission_stop()
{
	s_admission.stop(); // joins the coordinator and the checkpoint worker (staged captures stay on disk)
	s_admission_started = s_admission_ready_logged = s_admission_failed_logged = false;
	s_admission_retry = 0;
	s_admission_diagnostic_at = 0;
	s_admission_announced_ready = false;
}

// characters.inc: every complete local snapshot of an admitted character.
static bool admission_capture(const Character& character, const xr_vector<u8>& snapshot)
{
	if (!s_admission_started) return true;
	if (snapshot.empty()) return false;
	if (!s_admission.admitted(character.account.c_str(), character.slot)) return true; // initial draft / legacy import
	if (!s_admission.capture(character.account.c_str(), character.slot, snapshot.data(), snapshot.size()))
	{
		Msg("! [Lost Zone][master] save of %s slot %u was not queued by the world master; handoff refused",
			character.account.c_str(), character.slot);
		return false;
	}
	return true;
}

static bool admission_read_file(LPCSTR path, xr_vector<u8>& bytes, u32 limit)
{
	bytes.clear();
	FILE* f = fopen(path, "rb");
	if (!f) return false;
	fseek(f, 0, SEEK_END);
	const long size = ftell(f);
	fseek(f, 0, SEEK_SET);
	bool ok = size > 0 && u32(size) <= limit;
	if (ok) { bytes.resize(size); ok = fread(bytes.data(), 1, size, f) == size_t(size); }
	fclose(f);
	if (!ok) bytes.clear();
	return ok;
}

static void admission_token_path(LPCSTR login, u8 slot, string_path& path) { cluster_file("mtoken", login, slot, path); }

// The source location writes the master's transfer token next to the ticket.
static xr_string admission_token(LPCSTR login, u8 slot)
{
	string_path path; admission_token_path(login, slot, path);
	xr_vector<u8> bytes;
	if (!admission_read_file(path, bytes, 2048)) return xr_string();
	xr_string token((const char*)bytes.data(), bytes.size());
	if (token.find_first_of("\r\n\t ") != xr_string::npos) return xr_string();
	return token;
}

static bool admission_write_token(LPCSTR login, u8 slot, LPCSTR token)
{
	string_path path, temp;
	admission_token_path(login, slot, path);
	xr_sprintf(temp, "%s.tmp", path);
	FILE* f = fopen(temp, "wb");
	if (!f) return false;
	const size_t size = xr_strlen(token);
	const bool ok = fwrite(token, 1, size, f) == size && fflush(f) == 0;
	fclose(f);
	return ok && MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}

// Decode a complete master checkpoint in memory. A malformed image never
// overwrites a good local backup or half-replaces the cached character.
static bool admission_apply_master_bytes(LPCSTR login, u8 slot, const std::vector<unsigned char>& bytes)
{
 if (!character_load_image(login, slot, bytes.data(), bytes.size())) return false;
 Msg("[Lost Zone][master] %s slot %u: the world master's save loaded in memory (%u bytes)", login, slot, u32(bytes.size()));
 return true;
}

// The player left this location (not through a level changer).
static void admission_leave(const xr_string& key)
{
	if (!s_admission_started) return;
	const size_t colon = key.rfind(':');
	if (colon == xr_string::npos) return;
	const xr_string login = key.substr(0, colon);
	const int slot = colon + 1 < key.size() ? int(key[colon + 1] - '0') : 0; // character_key: one character, 1-10
	if (slot >= 1 && slot <= 10 && s_admission.admitted(login.c_str(), u32(slot))) s_admission.leave(login.c_str(), u32(slot));
}

static bool admission_admitted(LPCSTR login, u8 slot) { return s_admission_started && s_admission.admitted(login, slot); }
static u64 admission_depart(LPCSTR login, u8 slot, LPCSTR target) { return s_admission.depart(login, slot, target); }

// Level changers waiting for the world master's handoff ticket.
static void admission_departures_update(xrServer* server)
{
	if (!s_admission_started) return;
	for (auto it = s_cluster_leaving.begin(); it != s_cluster_leaving.end();)
	{
		ClusterLeaving& leaving = it->second;
		const u32 client_value = it->first;
		++it;
		if (!leaving.departure) continue;
		netcoop_world::DepartureResult result;
		if (!s_admission.poll_departure(leaving.departure, result)) continue;
		leaving.departure = 0;
		ClientID id; id.set(client_value);
		xrClientData* CL = static_cast<xrClientData*>(server->ID_to_client(id));
		const auto key = s_actor_character.find(leaving.actor);
		const xr_string character = key != s_actor_character.end() ? key->second : xr_string();
		const size_t colon = character.rfind(':');
		const xr_string login = colon == xr_string::npos ? xr_string() : character.substr(0, colon);
		const u8 slot = colon != xr_string::npos && colon + 1 < character.size() ? u8(character[colon + 1] - '0') : 0;
		if (result.state != netcoop_world::DepartureState::Ready)
		{
			if (CL && CL->owner) cluster_departure_undo(server, CL, leaving.actor, result.reason[0] ? result.reason : "the world master refused the passage");
			else s_cluster_leaving.erase(client_value);
			continue;
		}
		if (login.empty() || !admission_write_token(login.c_str(), slot, result.token))
			Msg("! [Lost Zone][cluster] %s: the world master's handoff could not be written for the target", login.c_str());
		// From here on this server never saves the character again.
		s_actor_character.erase(leaving.actor);
		if (!login.empty()) cluster_lease_release(login.c_str());
		leaving.since = real_time_ms();
		if (CL)
		{
			string256 data;
			xr_sprintf(data, "%s|%u|%s", leaving.host.c_str(), leaving.port, leaving.level.c_str());
			script_send_to_actor(leaving.actor, "netcoop_transfer", data);
		}
		Msg("[Lost Zone][cluster] %s leaves for %s (%s:%u), handed off by the world master", login.c_str(),
			leaving.level.c_str(), leaving.host.c_str(), leaving.port);
	}
}

// World orders (owner 2026-10-23): an administrator's weather, emission, psi
// storm, time scale or calendar jump, and the game's own calendar jumps
// (sleep, travel, campfire waiting), go to the world master, which carries
// them out for every location; a single map changing its own hour or sky
// fell out of step with the rest of the Zone.
static xr_vector<std::pair<u64, xr_string>> s_world_orders; // ticket, what it was

static bool world_order_available()
{
	return s_admission_started && s_admission.status().ready;
}

static bool world_order(LPCSTR account, netcoop_world::WorldOrder order, LPCSTR source, LPCSTR target,
	const double* values, u32 count, LPCSTR what)
{
	if (!world_order_available() || s_world_orders.size() >= 64) return false;
	const u64 ticket = s_admission.world_order(account, order, source, target, values, count);
	if (!ticket) return false;
	s_world_orders.push_back(std::make_pair(ticket, xr_string(what)));
	Msg("[Lost Zone][master] %s: sent to the world master", what);
	return true;
}

static void world_orders_update()
{
	for (auto it = s_world_orders.begin(); it != s_world_orders.end();)
	{
		netcoop_world::OrderResult result;
		if (!s_admission.poll_order(it->first, result)) { ++it; continue; }
		if (result.state == netcoop_world::OrderState::Done)
			Msg("[Lost Zone][master] %s: carried out by the world master for every location", it->second.c_str());
		else
			Msg("! [Lost Zone][master] %s: %s", it->second.c_str(), result.reason);
		it = s_world_orders.erase(it);
	}
}

// level.change_game_time on a location server with the world master.
bool world_time_advance(double game_seconds)
{
	if (!(game_seconds > 0.0) || !world_order_available()) return false;
	string128 what; xr_sprintf(what, "calendar +%.0f game s", game_seconds);
	return world_order("game", netcoop_world::WorldOrder::Advance, "", "", &game_seconds, 1, what);
}

// Server Lua: netcoop_world_order(account, order, source, target, a, b, c, d).
// order: weather (source, target, a = transition s), emission / psi_storm
// (a, b, c = phase durations s, d = intensity), scale (a), advance (a = s).
bool script_world_order(LPCSTR account, LPCSTR order, LPCSTR source, LPCSTR target, float a, float b, float c, float d)
{
	if (!order || !Level().Server) return false;
	const double values[] = {a, b, c, d};
	string256 what;
	xr_sprintf(what, "%s order of %s", order, account ? account : "?");
	if (!xr_strcmp(order, "weather"))
		return world_order(account, netcoop_world::WorldOrder::Weather, source, target, values, 1, what);
	if (!xr_strcmp(order, "emission"))
		return world_order(account, netcoop_world::WorldOrder::Emission, "", "", values, 4, what);
	if (!xr_strcmp(order, "psi_storm"))
		return world_order(account, netcoop_world::WorldOrder::PsiStorm, "", "", values, 4, what);
	if (!xr_strcmp(order, "scale"))
		return world_order(account, netcoop_world::WorldOrder::Scale, "", "", values, 1, what);
	if (!xr_strcmp(order, "advance"))
		return world_order(account, netcoop_world::WorldOrder::Advance, "", "", values, 1, what);
	return false;
}
