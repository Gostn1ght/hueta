// Included inside namespace netcoop in netcoop.cpp after netcoop_shared_store.inc.
// Hardware bans and the dedicated console's Players tab (owner 2026-10-12).
//
// A ban is kept by login and by the account's device digest (the hash the
// client sends at every login, never the hardware data itself), so a banned
// player cannot come back with a new account from the same computer. The
// file is shared by every location server of the cluster, like the accounts.

struct BanEntry
{
	xr_string login;  // lower case
	xr_string device; // may be empty: the account never logged in from a device
	u32 since;
};

static xr_vector<BanEntry> s_bans;
static FILETIME s_bans_stamp = {};
static bool s_bans_loaded = false;
static xr_string s_bans_image;

static void bans_path(string_path& path)
{
	if(master_cluster_plan()) {store_path("_system","bans",path);return;}
	FS.update_path(path, "$app_data_root$", "netcoop_bans.txt");
}

static void bans_refresh()
{
	string_path path;
	bans_path(path);
	if(master_cluster_plan()) {const LPCSTR image=script_store_read("_system","bans");s_bans_image=image ? image:"";}
	WIN32_FILE_ATTRIBUTE_DATA data;
	const bool exists = !!GetFileAttributesExA(path, GetFileExInfoStandard, &data);
	if (s_bans_loaded && exists && !CompareFileTime(&data.ftLastWriteTime, &s_bans_stamp)) return;
	if (s_bans_loaded && !exists && s_bans.empty()) return;
	s_bans_loaded = true;
	s_bans.clear();
	if (!exists) return;
	s_bans_stamp = data.ftLastWriteTime;
	FILE* f = fopen(path, "rb");
	if (!f) return;
	char line[512];
	while (fgets(line, sizeof(line), f))
	{
		if (line[0] == '#' || line[0] == '\r' || line[0] == '\n') continue;
		char login[96] = {}, device[96] = {};
		unsigned since = 0;
		// login|device|since ; the device may be empty ("login||since").
		const char* bar = strchr(line, '|');
		if (!bar || bar - line >= (int)sizeof(login)) continue;
		strncpy_s(login, line, bar - line);
		const char* bar2 = strchr(bar + 1, '|');
		if (!bar2 || bar2 - bar - 1 >= (int)sizeof(device)) continue;
		strncpy_s(device, bar + 1, bar2 - bar - 1);
		since = strtoul(bar2 + 1, nullptr, 10);
		BanEntry entry;
		entry.login = login;
		to_lower(entry.login);
		entry.device = key_valid(device) ? device : "";
		entry.since = since;
		if (login_valid(entry.login.c_str())) s_bans.push_back(entry);
	}
	fclose(f);
}

static bool bans_save()
{
	if(master_cluster_plan()) {
		xr_string image="# Lost Zone bans: login|device-digest|unix-time\n";
		for(const auto& entry:s_bans) {string256 line;xr_sprintf(line,"%s|%s|%u\n",entry.login.c_str(),entry.device.c_str(),entry.since);image+=line;}
		if(!script_store_swap("_system","bans",s_bans_image.c_str(),image.c_str())) return false;
		s_bans_image=image;return true;
	}
	string_path path, temp;
	bans_path(path);
	xr_sprintf(temp, "%s.%u.tmp", path, GetCurrentProcessId());
	FILE* f = fopen(temp, "wb");
	if (!f) return false;
	fprintf(f, "# Lost Zone bans: login|device-digest|unix-time (written by the server console)\n");
	for (const BanEntry& entry : s_bans)
		fprintf(f, "%s|%s|%u\n", entry.login.c_str(), entry.device.c_str(), entry.since);
	const bool ok = fflush(f) == 0 && _commit(_fileno(f)) == 0;
	fclose(f);
	if (!ok || !MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
	{
		DeleteFileA(temp);
		return false;
	}
	WIN32_FILE_ATTRIBUTE_DATA data;
	if (GetFileAttributesExA(path, GetFileExInfoStandard, &data)) s_bans_stamp = data.ftLastWriteTime;
	return true;
}

// Login time (finish_auth): this login or this computer is banned.
static bool server_banned(const xr_string& login, const xr_string& device)
{
	bans_refresh();
	xr_string key = login;
	to_lower(key);
	for (const BanEntry& entry : s_bans)
		if (entry.login == key || (!device.empty() && !entry.device.empty() && constant_time_equal(entry.device, device)))
			return true;
	return false;
}

struct FindLogin
{
	xr_string login;
	xrClientData* found = nullptr;
	void operator()(IClient* client)
	{
		xrClientData* CL = static_cast<xrClientData*>(client);
		if (found || !CL->netcoop_login.size()) return;
		xr_string name = CL->netcoop_login.c_str();
		to_lower(name);
		if (name == login) found = CL;
	}
};

bool server_ban(LPCSTR login, xr_string& message)
{
	if (!login || !login_valid(login)) { message = "invalid login"; return false; }
	Account* a = account_find(login);
	if (!a) { message = "account not found"; return false; }
	bans_refresh();
	xr_string key = a->login;
	to_lower(key);
	for (const BanEntry& entry : s_bans)
		if (entry.login == key) { message = a->login + " is already banned"; return false; }
	BanEntry entry;
	entry.login = key;
	entry.device = a->device;
	entry.since = u32(time(nullptr));
	s_bans.push_back(entry);
	if (!bans_save()) { s_bans.pop_back(); message = "cannot write netcoop_bans.txt"; return false; }
	message = a->login + (a->device.empty() ? " banned (no device bound yet: by login)" : " banned with the computer");
	Msg("[Lost Zone] %s", message.c_str());
	if (g_pGameLevel && Level().Server)
	{
		FindLogin find;
		find.login = key;
		Level().Server->ForEachClientDo(find);
		if (find.found) Level().Server->DisconnectClient(find.found, "@You are banned on this server");
	}
	return true;
}

// sv_account_role: the online player gets the new role at once.
bool server_apply_role_online(LPCSTR login, u8 role)
{
	if (!g_pGameLevel || !Level().Server || !login) return false;
	FindLogin find;
	find.login = login;
	to_lower(find.login);
	Level().Server->ForEachClientDo(find);
	if (!find.found) return false;
	find.found->netcoop_role = role;
	if (role != role_admin) find.found->netcoop_admin_god = false;
	NET_Packet P;
	P.w_begin(M_NETCOOP_SCRIPT);
	P.w_stringZ("netcoop_role");
	P.w_stringZ(role == role_admin ? "admin" : "player");
	Level().Server->SendTo(find.found->ID, P, net_flags(TRUE, TRUE));
	return true;
}

bool server_unban(LPCSTR login, xr_string& message)
{
	if (!login || !login_valid(login)) { message = "invalid login"; return false; }
	bans_refresh();
	xr_string key = login;
	to_lower(key);
	const size_t before = s_bans.size();
	s_bans.erase(std::remove_if(s_bans.begin(), s_bans.end(),
		[&](const BanEntry& entry) { return entry.login == key; }), s_bans.end());
	if (s_bans.size() == before) { message = xr_string(login) + " is not banned"; return false; }
	if (!bans_save()) { s_bans_loaded = false; message = "cannot write netcoop_bans.txt"; return false; }
	message = xr_string(login) + " unbanned";
	Msg("[Lost Zone] %s", message.c_str());
	return true;
}

void server_list_bans(xr_string& out)
{
	bans_refresh();
	string256 line;
	xr_sprintf(line, "%u ban(s):", u32(s_bans.size()));
	out = line;
	for (const BanEntry& entry : s_bans)
	{
		xr_sprintf(line, "\n  %-20s %s", entry.login.c_str(), entry.device.empty() ? "by login" : "login + computer");
		out += line;
	}
}

// Lua (netcoop_factions) keeps leaders in the cluster's shared store.
static xr_string console_lua(LPCSTR function, LPCSTR a = "", LPCSTR b = "", LPCSTR c = "")
{
	::luabind::functor<LPCSTR> f;
	if (!g_pGameLevel || !ai().script_engine().functor(function, f)) return xr_string();
	try
	{
		LPCSTR result = f(a, b, c);
		return result ? result : "";
	}
	catch (...)
	{
		Msg("! [Lost Zone] %s failed", function);
		return xr_string();
	}
}

bool server_leader(LPCSTR login, u8 slot, LPCSTR faction, xr_string& message)
{
	if (!login || !login_valid(login) || slot < 1 || slot > 10 || !faction || !faction[0])
	{
		message = "usage: sv_leader <login> <slot> <faction|off>";
		return false;
	}
	string16 slot_text;
	xr_sprintf(slot_text, "%u", slot);
	message = console_lua("netcoop_factions.console_leader", login, slot_text, faction);
	if (message.empty()) { message = "factions are not loaded"; return false; }
	const bool ok = message[0] == '*';
	if (message.size() > 2 && (message[0] == '*' || message[0] == '!') && message[1] == ' ') message.erase(0, 2);
	return ok;
}

void console_players(xr_vector<SConsolePlayer>& out)
{
	out.clear();
	if (!g_pGameLevel || !Level().Server || pure_client()) return;
	// id|faction|role for online Actors (faction community and leadership).
	xr_map<u16, std::pair<xr_string, xr_string>> roster;
	// Faction scripts run once ALife is up (not while the level loads).
	const xr_string text = ai().get_alife() ? console_lua("netcoop_factions.console_roster") : xr_string();
	for (size_t at = 0; at < text.size();)
	{
		size_t end = text.find('\n', at);
		if (end == xr_string::npos) end = text.size();
		const xr_string line = text.substr(at, end - at);
		at = end + 1;
		const size_t a = line.find('|'), b = a == xr_string::npos ? a : line.find('|', a + 1);
		if (b == xr_string::npos) continue;
		roster[u16(strtoul(line.c_str(), nullptr, 10))] = std::make_pair(line.substr(a + 1, b - a - 1), line.substr(b + 1));
	}
	struct Collect
	{
		xrServer* server;
		xr_vector<SConsolePlayer>* out;
		xr_map<u16, std::pair<xr_string, xr_string>>* roster;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (CL == server->GetServerClient() || !CL->netcoop_login.size()) return;
			SConsolePlayer row = {};
			xr_strcpy(row.login, CL->netcoop_login.c_str());
			xr_strcpy(row.name, CL->netcoop_character_name.size() ? CL->netcoop_character_name.c_str() : CL->netcoop_login.c_str());
			row.id = CL->owner ? CL->owner->ID : u16(-1);
			row.slot = CL->netcoop_character_slot;
			row.admin = CL->netcoop_role == role_admin;
			row.online = true;
			row.ping = CL->stats.getPing();
			auto it = roster->find(row.id);
			if (it != roster->end())
			{
				xr_strcpy(row.faction, it->second.first.c_str());
				row.leader = it->second.second == "leader";
				row.deputy = it->second.second == "deputy";
			}
			row.role = row.admin ? SConsolePlayer::role_admin : row.leader ? SConsolePlayer::role_leader : SConsolePlayer::role_player;
			out->push_back(row);
		}
	} collect = {Level().Server, &out, &roster};
	Level().Server->ForEachClientDo(collect);
	bans_refresh();
	for (const BanEntry& entry : s_bans)
	{
		SConsolePlayer row = {};
		const Account* a = account_find(entry.login.c_str());
		xr_strcpy(row.login, a ? a->login.c_str() : entry.login.c_str());
		xr_strcpy(row.name, row.login);
		row.id = u16(-1);
		row.banned = true;
		row.admin = a && a->role == role_admin;
		row.role = row.admin ? SConsolePlayer::role_admin : SConsolePlayer::role_player;
		out.push_back(row);
	}
}

// The world master's window (owner 2026-10-17: "move the players into the
// master to manage them from there"): every location lists its players in
// the shared cluster folder and runs the administrator commands the window
// leaves there for it. Only the console's own administrator commands are
// taken; the folder is the hosting machine's.
static u32 s_master_window_roster = 0, s_master_window_commands = 0;

static void master_window_clean(char* text)
{
	for (char* c = text; *c; ++c)
		if (*c == '|' || *c == '\n' || *c == '\r') *c = ' ';
}

static bool master_window_allowed(const xr_string& line)
{
	if (line.empty() || line.size() > 240 || line.find_first_of(";\r\n") != xr_string::npos) return false;
	static const char* const allowed[] = {"sv_ban ", "sv_unban ", "sv_account_role ", "sv_leader ", "sv_cmd "};
	for (const char* prefix : allowed)
		if (!line.compare(0, xr_strlen(prefix), prefix)) return true;
	return false;
}

static void master_window_update(xrServer* server, u32 now)
{
	if (!server || pure_client() || !g_pGameLevel) return;
	string_path dir, file;
	cluster_dir(dir);
	if (now - s_master_window_roster >= 2000)
	{
		s_master_window_roster = now;
		xr_vector<SConsolePlayer> players;
		console_players(players);
		xr_string text;
		for (SConsolePlayer& p : players)
		{
			if (!p.online) continue;
			master_window_clean(p.login); master_window_clean(p.name); master_window_clean(p.faction);
			string512 line;
			xr_sprintf(line, "%s|%s|%u|%s|%s|%u\n", p.login, p.name, p.slot, p.faction,
				p.admin ? "admin" : p.leader ? "leader" : "player", p.ping);
			text += line;
		}
		xr_sprintf(file, "%splayers_%u.txt", dir, cluster_port());
		cluster_write_line(file, text.c_str(), false);
	}
	if (now - s_master_window_commands < 1000) return;
	s_master_window_commands = now;
	xr_sprintf(file, "%scommand_%u.txt", dir, cluster_port());
	if (GetFileAttributesA(file) == INVALID_FILE_ATTRIBUTES) return;
	// Taken at once: a command the window writes meanwhile waits for the next turn.
	string_path work;
	xr_sprintf(work, "%s.%u.work", file, GetCurrentProcessId());
	if (!MoveFileExA(file, work, MOVEFILE_REPLACE_EXISTING)) return;
	FILE* f = fopen(work, "rb");
	if (f)
	{
		char line[512];
		for (int n = 0; n < 32 && fgets(line, sizeof(line), f); ++n)
		{
			xr_string command = line;
			while (!command.empty() && (command.back() == '\n' || command.back() == '\r' || command.back() == ' ')) command.pop_back();
			if (!master_window_allowed(command))
			{
				if (!command.empty()) Msg("! [Lost Zone][master window] refused: %s", command.c_str());
				continue;
			}
			Msg("[Lost Zone][master window] %s", command.c_str());
			Console->Execute(command.c_str());
		}
		fclose(f);
	}
	DeleteFileA(work);
}
