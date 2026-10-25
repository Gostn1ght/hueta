// Included in netcoop.cpp (namespace netcoop) - server: authentication and admission of players.
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// server: authentication
// ---------------------------------------------------------------------------
struct LoginInUse
{
	xr_string login;
	xrClientData* self;
	bool operator()(IClient* client) const
	{
		xrClientData* other = static_cast<xrClientData*>(client);
		if (other == self || !other->netcoop_login.size())
			return false;
		xr_string name = other->netcoop_login.c_str();
		to_lower(name);
		return name == login;
	}
};

static void send_auth_result(xrServer* server, xrClientData* CL, bool ok, u8 role, LPCSTR message, LPCSTR storage=nullptr)
{
	NET_Packet P;
	P.w_begin(M_NETCOOP_AUTH_RESULT);
	P.w_u8(ok ? 1 : 0);
	P.w_u8(role);
	P.w_stringZ(message);
    if (ok)
    {
        xr_string names;
        for (u8 slot = 1; slot <= (role == role_admin ? 10 : 1); ++slot)
        {
            Character* character = character_load(CL->netcoop_login.c_str(), slot);
            if (slot > 1) names += "|";
            if (character) names += character->name;
        }
        P.w_stringZ(names.c_str());
        xr_string previews;
        for (u8 slot = 1; slot <= (role == role_admin ? 10 : 1); ++slot)
        {
            Character* character = character_load(CL->netcoop_login.c_str(), slot);
            xr_string visual = "actors\\stalker_neutral\\stalker_neutral_1.ogf", items;
            if (character)
                for (const auto& item : character->items)
                {
                    SInvItemPlace place; place.value = item.place;
                    if (!item.parent && place.type == eItemPlaceSlot && place.slot_id == OUTFIT_SLOT && pSettings->line_exist(item.section.c_str(), "actor_visual"))
                        visual = pSettings->r_string(item.section.c_str(), "actor_visual");
                    if (items.size() + item.section.size() < 1100) { if (!items.empty()) items += ","; items += item.section; }
                }
            previews += visual + "|" + (character ? character->faction : "stalker") + "|" + items + "\n";
        }
        // Storage snapshots occupy a separate bounded payload. Full account
        // previews can approach the packet limit and are omitted in that case.
        P.w_stringZ(storage ? "" : previews.c_str());
        if (storage) P.w_stringZ(storage);
    }
	server->SendTo(CL->ID, P, net_flags(TRUE, TRUE));
}

static void reject(xrServer* server, xrClientData* CL, LPCSTR message)
{
	Msg("! [Lost Zone] login rejected for 0x%08x: %s", CL->ID.value(), message);
	send_auth_result(server, CL, false, role_none, message);
	string512 reason;
	xr_sprintf(reason, "@%s", message);
	server->DisconnectClient(CL, reason);
}

#include "netcoop_cluster.inc"
#include "netcoop_shared_store.inc"
#include "netcoop_console.inc"
#include "netcoop_admission.inc"

// The server's PBKDF2 (60000 rounds) took ~100 ms of a frame for every
// login; with many players joining the world stuttered for everyone. It runs
// on a worker thread; the result is applied on the main thread by
// server_auth_update, and the client's player state waits for it.
struct PendingAuth
{
    bool firebase = false;
    xr_string firebase_api, firebase_uid, description, history;
	xr_string device;
	ClientID client;
	xr_string login;
	xr_string key;
	xr_string salt;
	bool create;
	xr_string legacy_key, legacy_hash; // verified old password, never device-only recovery
    StorageRequest storage;
	u8 slot = 1, economy = 1;
	xr_string character_name, faction = "stalker", loadout;
	xr_string hash;
	bool hashed;
	volatile LONG done;
	NET_Packet* player_state; // M_CREATE_PLAYER_STATE that arrived meanwhile
};
static xr_vector<PendingAuth*> s_pending_auth;
// Logins waiting for the world master's admission (doc 135); still unauthenticated.
struct PendingAdmission { PendingAuth* pending = nullptr; u64 ticket = 0; bool token = false; };
static xr_vector<PendingAdmission> s_pending_admission;

// The front-end's slot list comes from the character files, not from this
// process's copies: another location of the cluster saved the account since
// (owner 2026-10-23: the character list changed with the port). A character
// playing on this server keeps its live copy.
static void characters_refresh_for_list(LPCSTR account)
{
	// a login of this account waiting for the master uses its loaded copy
	for (const PendingAdmission& waiting : s_pending_admission)
		if (waiting.pending && !_stricmp(waiting.pending->login.c_str(), account)) return;
	character_commits_flush_account(account);
	xr_string prefix = account;
	to_lower(prefix);
	prefix += ":";
	xr_set<xr_string> live;
	for (const auto& entry : s_actor_character) live.insert(entry.second);
	for (auto it = s_characters.begin(); it != s_characters.end();)
		if (!it->first.compare(0, prefix.size(), prefix) && !live.count(it->first)) it = s_characters.erase(it);
		else ++it;
}

static void auth_worker(void* data)
{
	PendingAuth* pending = static_cast<PendingAuth*>(data);
    if (pending->firebase)
    {
        FirebaseSession identity; std::string error;
        pending->hashed = firebase_lookup(pending->key.c_str(), pending->firebase_api.c_str(), identity, error) &&
            identity.verified && identity.username == pending->login.c_str() && identity.uid.size() <= 128 &&
            identity.uid.find_first_of("|\r\n") == std::string::npos;
        if (pending->hashed) pending->firebase_uid = identity.uid.c_str();
		if (pending->hashed && !pending->legacy_key.empty())
			server_hash(pending->legacy_key.c_str(), pending->salt, pending->legacy_hash);
    }
    else pending->hashed = server_hash(pending->key.c_str(), pending->salt, pending->hash);
	InterlockedExchange(&pending->done, 1);
}

static PendingAuth* pending_auth_of(ClientID id)
{
	for (PendingAuth* pending : s_pending_auth)
		if (pending->client == id)
			return pending;
	for (const PendingAdmission& waiting : s_pending_admission)
		if (waiting.pending->client == id)
			return waiting.pending;
	return NULL;
}

// Optional proof from a remembered local password. Leave the following
// storage request untouched for old clients and for packets without proof.
static bool read_account_link(NET_Packet& P, xr_string& key)
{
	const u32 start = P.r_tell();
	if (P.r_elapsed() < 4 || P.r_u32() != 0x4b4c5a4c)
	{
		P.r_seek(start);
		return true;
	}
	char legacy[65];
	if (!read_string(P, legacy, sizeof(legacy)) || !key_valid(legacy)) return false;
	key = legacy;
	SecureZeroMemory(legacy, sizeof(legacy));
	return true;
}

void server_on_auth(xrServer* server, xrClientData* CL, NET_Packet& P)
{
	if (!enabled() || !CL || CL->flags.bLocal || CL == server->GetServerClient())
		return;
	if (CL->netcoop_role != role_none || pending_auth_of(CL->ID))
		return; // already authenticated or being checked on this connection

	if (P.r_elapsed() < 1)
	{
		reject(server, CL, "Malformed login request");
		return;
	}
	const u8 mode = P.r_u8();
	char login[64];
	char key[4097];
	if (!read_string(P, login, sizeof(login)) || !read_string(P, key, sizeof(key)) || !login_valid(login) ||
		(mode == 3 ? !firebase_enabled() || xr_strlen(key) < 100 : !key_valid(key)))
	{
		reject(server, CL, "Invalid login or password");
		return;
	}

	LoginInUse in_use;
	in_use.login = login;
	to_lower(in_use.login);
	in_use.self = CL;
	if (server->FindClient(in_use))
	{
		reject(server, CL, "This account is already online");
		return;
	}

	PendingAuth* pending = xr_new<PendingAuth>();
    pending->firebase = mode == 3;
    pending->firebase_api = s_firebase_api;
	pending->client = CL->ID;
	pending->login = login;
	pending->key = key;
	pending->hashed = false;
	pending->done = 0;
	pending->player_state = NULL;
    if (P.r_elapsed())
    {
        char name[64], faction[32], loadout[4097];
        pending->slot = P.r_u8();
        if (!read_string(P, name, sizeof(name)) || !read_string(P, faction, sizeof(faction)) || P.r_elapsed() < 1)
        { xr_delete(pending); reject(server, CL, "Invalid character request"); return; }
        pending->economy = P.r_u8();
        if (!read_string(P, loadout, sizeof(loadout)))
        { xr_delete(pending); reject(server, CL, "Invalid character loadout"); return; }
        pending->character_name = name; pending->faction = faction; pending->loadout = loadout;
        if (P.r_elapsed())
        {
            char device[65];
            if (!read_string(P, device, sizeof(device)) || !key_valid(device))
            { xr_delete(pending); reject(server, CL, "Device identity unavailable"); return; }
            pending->device = device;
            if (pending->firebase)
            {
                char description[513], history[1537];
                if (!read_string(P, description, sizeof(description)) || !read_string(P, history, sizeof(history)))
                { xr_delete(pending); reject(server, CL, "Invalid character profile"); return; }
                pending->description = description; pending->history = history;
				if (!read_account_link(P, pending->legacy_key))
				{ xr_delete(pending); reject(server, CL, "Invalid account linking proof"); return; }
            }
            if (P.r_elapsed())
            {
                char id[33];
                if (pending->slot!=0 || P.r_elapsed()<13 || P.r_u32()!=0x54535a4c)
                { xr_delete(pending); reject(server,CL,"Invalid storage request"); return; }
                pending->storage.active=true; pending->storage.op=P.r_u8(); pending->storage.slot=P.r_u8();
                pending->storage.index=P.r_u16(); pending->storage.revision=P.r_u32();
                if (!read_string(P,id,sizeof(id)) || xr_strlen(id)!=32 || P.r_elapsed() || pending->storage.op>2)
                { xr_delete(pending); reject(server,CL,"Invalid storage request"); return; }
                pending->storage.id=id;
            }
        }
    }
    else
    {
        // Older clients and headless test bots keep the first slot.
        pending->character_name = login;
        pending->loadout = "device_pda_1";
    }

	if (!accounts_available())
	{
		xr_delete(pending);
		reject(server, CL, "The world master is unavailable; try again in a minute");
		return;
	}
	Account* a = account_find(login);
	pending->create = mode == auth_register || ((mode == auth_auto || pending->firebase) && !a);
	if (pending->create)
	{
		if (a)
		{
			xr_delete(pending);
			reject(server, CL, "Account already exists, use Login");
			return;
		}
		u8 salt[salt_bytes];
		if (!random_bytes(salt, salt_bytes))
		{
			xr_delete(pending);
			reject(server, CL, "Server error: no random source");
			return;
		}
		pending->salt = to_hex(salt, salt_bytes);
	}
	else
	{
		if (a && !pending->firebase && a->hash == "firebase")
		{
			// A computer identifier cannot authorize replacing a password.
			xr_delete(pending);
			reject(server, CL, "This account uses Google sign-in; reset its password on the Google sign-in screen");
			return;
		}
		if (!a)
		{
			xr_delete(pending);
			reject(server, CL, "Unknown account, use Register");
			return;
		}
		const u32 now = GetTickCount();
		if (a->locked_until && now < a->locked_until)
		{
			xr_delete(pending);
			reject(server, CL, "Too many failed logins, try again in a minute");
			return;
		}
		pending->salt = a->salt;
	}
	s_pending_auth.push_back(pending);
	thread_spawn(auth_worker, "netcoop-auth", 0, pending);
}

static void finish_login(xrServer* server, xrClientData* CL, Account* a, PendingAuth* pending)
{
	CL->netcoop_role = a->role;
	CL->name = a->login.c_str();

	string256 message;
	xr_sprintf(message, "Logged in as %s (%s)", a->login.c_str(), role_name(a->role));
	Msg("[Lost Zone] client 0x%08x %s", CL->ID.value(), message);
	send_auth_result(server, CL, true, a->role, message);

	if (pending->player_state)
		server->game->AddDelayedEvent(*pending->player_state, GAME_EVENT_CREATE_PLAYER_STATE, 0, CL->ID);
}

// true: the login waits for the world master (the pending entry is kept).
static bool finish_auth(xrServer* server, PendingAuth* pending)
{
	xrClientData* CL = static_cast<xrClientData*>(server->ID_to_client(pending->client));
	if (!CL)
		return false; // disconnected meanwhile

	LoginInUse in_use;
	in_use.login = pending->login;
	to_lower(in_use.login);
	in_use.self = CL;
	if (server->FindClient(in_use))
	{
		reject(server, CL, "This account is already online");
		return false;
	}
	if (!pending->hashed)
	{
		reject(server, CL, pending->firebase ? "Firebase identity or verified email could not be confirmed" : "Server error: cannot hash password");
		return false;
	}

	if (!accounts_available())
	{
		reject(server, CL, "The world master is unavailable; try again in a minute");
		return false;
	}
	Account* a = account_find(pending->login.c_str());
	bool link_firebase = false;
	if (pending->create)
	{
		if (a)
		{
			reject(server, CL, "Account already exists, use Login");
			return false;
		}
		Account created;
        created.firebase_uid = pending->firebase_uid;
		created.login = pending->login;
		created.role = role_player; // only the server console grants admin
		created.approval = 1; // all authenticated registrations can join immediately
		created.device = pending->device;
		created.salt = pending->salt;
		created.hash = pending->firebase ? "firebase" : pending->hash;
		created.has_money = false;
		created.money = 0;
		created.failures = 0;
		created.locked_until = 0;
		created.touched = true;
		s_accounts[in_use.login] = created;
		s_accounts_dirty = true;
		accounts_save();
		a = &s_accounts[in_use.login];
		Msg("[Lost Zone] account '%s' registered", pending->login.c_str());
	}
	else
	{
		if (!a || a->salt != pending->salt)
		{
			reject(server, CL, "Unknown account, use Register");
			return false;
		}
		link_firebase = pending->firebase && a->firebase_uid.empty() && !pending->firebase_uid.empty() &&
			!pending->legacy_hash.empty() && constant_time_equal(a->hash, pending->legacy_hash);
		if (pending->firebase ? (!link_firebase && (a->firebase_uid.empty() || a->firebase_uid != pending->firebase_uid)) : !constant_time_equal(pending->hash, a->hash))
		{
			if (++a->failures >= 5)
			{
				a->failures = 0;
				a->locked_until = GetTickCount() + 60000;
			}
			reject(server, CL, "Wrong password");
			return false;
		}
		a->failures = 0;
		a->locked_until = 0;
	}

    if (!a->device.empty() && !constant_time_equal(a->device, pending->device))
    {
        reject(server, CL, "Account is bound to another device; contact the server administrator");
        return false;
    }
    // Hardware ban (server console): this login or this computer.
    if (server_banned(a->login, pending->device))
    {
        reject(server, CL, "You are banned on this server");
        return false;
    }
	if (link_firebase)
	{
		a->firebase_uid = pending->firebase_uid;
		a->touched = true;
		s_accounts_dirty = true;
		accounts_save();
		Msg("[Lost Zone] account '%s' linked to Google after password proof", a->login.c_str());
	}
    if (a->device.empty() && !pending->device.empty())
    { a->device = pending->device; a->touched = true; s_accounts_dirty = true; accounts_save(); }
    // Retain the old column for save-format compatibility, but it is no
    // longer an admission gate. Migrate only AFTER credentials, device and
    // explicit bans have been checked; failed logins cannot edit accounts.
    if (a->approval != 1)
    { a->approval = 1; a->touched = true; s_accounts_dirty = true; accounts_save(); }
	CL->netcoop_login = a->login.c_str();
    CL->netcoop_role = a->role;
    // Slot zero authenticates the front-end and fetches slots without creating
    // an Actor or touching an existing character's inventory.
    if (pending->slot == 0)
    {
        if (pending->storage.active)
        {
            // A detached inventory on this process may still be a live Actor
            // on another map. Own the account and refresh its disk cache for
            // the entire front-end transaction, just as a gameplay login does.
            xr_string storage_error;
            if (!cluster_on_login(CL, a->login.c_str(), 0, storage_error))
            {
                CL->netcoop_login = NULL;
                reject(server, CL, storage_error.c_str());
                return false;
            }
            const xr_string result=storage_execute(server,CL,pending->storage);
            cluster_lease_release(a->login.c_str());
            send_auth_result(server,CL,true,a->role,"Account verified",result.c_str());
        }
        else
        {
            characters_refresh_for_list(a->login.c_str());
            send_auth_result(server, CL, true, a->role, "Account verified");
        }
        server->DisconnectClient(CL, "@Account verified");
        return false;
    }
    xr_string cluster_error;
    if (!cluster_on_login(CL, a->login.c_str(), pending->slot, cluster_error))
    {
        CL->netcoop_login = NULL;
        reject(server, CL, cluster_error.c_str());
        return false;
    }
    xr_string redirect;
    bool location_starting = false;
    // With the world master the master's location decides (the answer
    // ELSEWHERE redirects): following the local file as well sent a player
    // back and forth between two maps when they disagreed after a crash.
    if (!admission_active() && cluster_route(server, a->login.c_str(), pending->slot, redirect, &location_starting))
    {
        cluster_lease_release(a->login.c_str());
        cluster_send_redirect(server, CL, redirect.c_str());
        CL->netcoop_login = NULL;
        return false;
    }
    if (location_starting)
    {
        cluster_lease_release(a->login.c_str());
        CL->netcoop_login = NULL;
        reject(server, CL, "Your character's location is starting; log in again in 1-2 minutes");
        return false;
    }
    if (!character_select(CL, pending->slot, pending->character_name.c_str(), pending->faction.c_str(), pending->economy, pending->loadout.c_str()))
    {
        cluster_lease_release(a->login.c_str());
        CL->netcoop_login = NULL;
        reject(server, CL, "Character unavailable or starting items exceed the point budget");
        return false;
    }
    if (Character* character = character_load(CL->netcoop_login.c_str(), pending->slot))
        if (!character->initialized && pending->firebase)
        { character->description = pending->description; character->history = pending->history; character_save(*character); }
	// M2b: the world master admits the character (create / resume /
	// transfer claim) and may hold a newer save than this machine's file.
	if (admission_active())
	{
		string_path path;
		character_path(CL->netcoop_login.c_str(), pending->slot, path);
		character_commits_flush(path);
		xr_vector<u8> local;
		admission_read_file(path, local, 20u * 1024 * 1024);
		const xr_string token = admission_token(CL->netcoop_login.c_str(), pending->slot);
		const u64 ticket = s_admission.admit(CL->netcoop_login.c_str(), pending->slot, local.empty() ? nullptr : local.data(),
			local.size(), token.empty() ? nullptr : token.c_str());
		if (!ticket)
		{
			cluster_lease_release(a->login.c_str());
			CL->netcoop_login = NULL;
			reject(server, CL, "The location cannot reach the world master; try again in a minute");
			return false;
		}
		CL->netcoop_role = role_none; // not admitted yet: player state messages wait
		PendingAdmission waiting; waiting.pending = pending; waiting.ticket = ticket; waiting.token = !token.empty();
		s_pending_admission.push_back(waiting);
		return true;
	}
	finish_login(server, CL, a, pending);
	return false;
}

static void free_pending(PendingAuth* pending)
{
	SecureZeroMemory(&pending->key[0], pending->key.size());
	if (!pending->legacy_key.empty()) SecureZeroMemory(&pending->legacy_key[0], pending->legacy_key.size());
	xr_delete(pending->player_state);
	xr_delete(pending);
}

static void admission_logins_update(xrServer* server)
{
	for (u32 i = 0; i < s_pending_admission.size();)
	{
		const PendingAdmission waiting = s_pending_admission[i];
		netcoop_world::AdmissionResult result;
		std::vector<unsigned char> bytes;
		if (!s_admission.poll_admission(waiting.ticket, result, bytes)) { ++i; continue; }
		s_pending_admission.erase(s_pending_admission.begin() + i);
		PendingAuth* pending = waiting.pending;
		xrClientData* CL = static_cast<xrClientData*>(server->ID_to_client(pending->client));
		Account* a = account_find(pending->login.c_str());
		const xr_string login = a ? a->login : pending->login;
		if (!CL || !a || !CL->netcoop_login.size())
		{
			// Gone while waiting: the master session closes again.
			if (result.state == netcoop_world::AdmissionState::Admitted) s_admission.leave(login.c_str(), pending->slot);
			cluster_lease_release(login.c_str());
			free_pending(pending);
			continue;
		}
		// The master keeps the character on another map (a crash mid-passage
		// left this machine's file naming this one): play there.
		string256 elsewhere;
		if (result.state == netcoop_world::AdmissionState::Elsewhere)
		{
			xr_string host; u32 port = 0;
			const LPCSTR home = result.home;
			LPCSTR problem = "";
			if (!cluster_location(home, host, port) || port == cluster_port())
				problem = "no server of this cluster runs it";
			else if (cluster_target_problem(port)[0])
				problem = cluster_target_problem(port);
			if (!problem[0])
			{
				string256 redirect;
				xr_sprintf(redirect, "redirect|%s|%u|%s", cluster_client_host(host), port, home);
				Msg("[Lost Zone][master] %s slot %u lives on %s: sent there", login.c_str(), pending->slot, home);
				cluster_lease_release(login.c_str());
				cluster_send_redirect(server, CL, redirect);
				CL->netcoop_login = NULL;
				free_pending(pending);
				continue;
			}
			if (strstr(problem, "offline") && cluster_on_demand(home))
			{
				cluster_wake(home);
				xr_sprintf(elsewhere, "Your character is on %s; its server is starting, log in again in 1-2 minutes", home);
			}
			else
				xr_sprintf(elsewhere, "Your character is on %s; that location is not available (%s)", home, problem);
			result.state = netcoop_world::AdmissionState::Refused;
			strncpy_s(result.reason, sizeof(result.reason), elsewhere, _TRUNCATE);
		}
		if (waiting.token && result.stale_token)
		{
			// A finished, aborted or expired passage: its token goes.
			string_path path; admission_token_path(login.c_str(), pending->slot, path); DeleteFileA(path);
			Msg("[Lost Zone][master] %s slot %u: an old passage token was dropped", login.c_str(), pending->slot);
		}
		bool ok = result.state != netcoop_world::AdmissionState::Refused;
		LPCSTR reason = result.reason[0] ? result.reason : "The world master refused this character";
		if (ok && result.state == netcoop_world::AdmissionState::Admitted && result.master_bytes &&
			!admission_apply_master_bytes(login.c_str(), pending->slot, bytes))
		{
			ok = false; reason = "The world master's save of this character could not be loaded here";
			s_admission.leave(login.c_str(), pending->slot);
		}
		if (!ok)
		{
			Msg("! [Lost Zone][master] login of %s slot %u refused: %s", login.c_str(), pending->slot, reason);
			cluster_lease_release(login.c_str());
			CL->netcoop_login = NULL;
			reject(server, CL, reason);
			free_pending(pending);
			continue;
		}
		if (result.state == netcoop_world::AdmissionState::Admitted)
		{
			if (waiting.token) { string_path path; admission_token_path(login.c_str(), pending->slot, path); DeleteFileA(path); }
			// A character the master has no save of yet: its local file is the first.
			if (!result.revision && !result.master_bytes)
				if (Character* character = character_load(login.c_str(), pending->slot))
					character_save(*character, true);
			Msg("[Lost Zone][master] %s slot %u admitted by the world master%s", login.c_str(), pending->slot,
				result.master_bytes ? " (its newer save is used)" : "");
		}
		else
		{
			Msg("! [Lost Zone][master] %s slot %u: %s - local save only", login.c_str(), pending->slot, reason);
			// No master answer: the local file's map decides, as without one.
			xr_string redirect;
			if (cluster_route(server, login.c_str(), pending->slot, redirect))
			{
				cluster_lease_release(login.c_str());
				cluster_send_redirect(server, CL, redirect.c_str());
				CL->netcoop_login = NULL;
				free_pending(pending);
				continue;
			}
		}
		finish_login(server, CL, a, pending);
		free_pending(pending);
	}
}

void server_auth_update(xrServer* server)
{
	for (u32 i = 0; i < s_pending_auth.size();)
	{
		PendingAuth* pending = s_pending_auth[i];
		if (!InterlockedCompareExchange(&pending->done, 0, 0))
		{
			++i;
			continue;
		}
		s_pending_auth.erase(s_pending_auth.begin() + i);
		if (finish_auth(server, pending)) continue; // waits for the world master
		free_pending(pending);
	}
	admission_logins_update(server);
}

bool server_defer_player_state(xrClientData* CL, NET_Packet& P)
{
	PendingAuth* pending = CL ? pending_auth_of(CL->ID) : NULL;
	if (!pending)
		return false;
	if (!pending->player_state)
		pending->player_state = xr_new<NET_Packet>();
	CopyMemory(pending->player_state, &P, sizeof(NET_Packet));
	return true;
}

bool server_requires_login(xrServer* server, xrClientData* CL)
{
	return enabled() && CL && !CL->flags.bLocal && CL != server->GetServerClient() && CL->netcoop_role == role_none;
}

static xrCriticalSection s_pending_lock;
static xr_vector<u16> s_pending_actor_destroy;
static xr_map<u16, u32> s_actor_destroy_retry;
static void server_release_task_manager(u16 actor_id);

static void store_money(xrClientData* CL)
{
	if (!CL || server_client_leaving(CL) || !CL->netcoop_login.size() || !CL->owner || CL->netcoop_character_slot != 1)
		return;
	if (s_character_restore.find(CL->owner->ID) != s_character_restore.end()) return;
	CSE_ALifeTraderAbstract* trader = smart_cast<CSE_ALifeTraderAbstract*>(CL->owner);
	if (!trader)
		return;
	Account* a = account_find(CL->netcoop_login.c_str());
	if (!a)
		return;
	if (!a->has_money || a->money != trader->m_dwMoney)
	{
		a->has_money = true;
		a->money = trader->m_dwMoney;
		a->touched = true;
		s_accounts_dirty = true;
	}
}

void server_on_client_disconnect(xrClientData* CL)
{
	if (!enabled() || !CL)
		return;
	if (CL->owner) server_voice_forget(CL->owner->ID);
	// Remove the player's Actor instead of migrating it to the server, so a
	// reconnect does not leave an abandoned body in the world. This runs on
	// the transport thread; the game object is destroyed from server_update.
	if (!CL->flags.bLocal && CL->owner && smart_cast<CSE_ALifeCreatureActor*>(CL->owner))
	{
		s_pending_lock.Enter();
		s_pending_actor_destroy.push_back(CL->owner->ID);
		s_pending_lock.Leave();
	}
}

// Only main-thread cleanup may read character restore/account maps. The
// transport callback queues an Actor ID; it must not capture a half-restored
// wallet or race the character/account caches while disconnecting.
static bool character_account_money_commit(xrServer* server, u16 actor_id)
{
	Character* character = character_tracked_for_save(actor_id);
	if (!character) return false;
	if (character->slot != 1) return true;
	CSE_ALifeTraderAbstract* trader = smart_cast<CSE_ALifeTraderAbstract*>(server->game->get_entity_from_eid(actor_id));
	Account* account_record = account_find(character->account.c_str());
	if (!trader || !account_record) return false;
	if (!account_record->has_money || account_record->money != trader->m_dwMoney)
	{
		account_record->has_money = true;
		account_record->money = trader->m_dwMoney;
		account_record->touched = true;
		s_accounts_dirty = true;
	}
	return accounts_save();
}

// The disconnected client no longer exists, so the server takes over the
// Actor and everything it carries before destroying it.
static void give_to_server(xrServer* server, CSE_Abstract* entity, u32 depth)
{
	if (!entity || depth > 9)
		return;
	entity->owner = static_cast<xrClientData*>(server->GetServerClient());
	for (u32 i = 0; i < entity->children.size(); ++i)
		give_to_server(server, server->game->get_entity_from_eid(entity->children[i]), depth + 1);
}

static void destroy_pending_actors(xrServer* server)
{
	xr_vector<u16> ids;
	s_pending_lock.Enter();
	ids.swap(s_pending_actor_destroy);
	s_pending_lock.Leave();

	for (u32 i = 0; i < ids.size() && g_pGameLevel; ++i)
	{
		// Transport may report the same disconnect twice. Keep only one retry
		// for that Actor, without releasing its state or account ownership.
		if (std::find(ids.begin(), ids.begin() + i, ids[i]) != ids.begin() + i) continue;
		CGameObject* actor_object = smart_cast<CGameObject*>(Level().Objects.net_Find(ids[i]));
		if (actor_object && smart_cast<CActor*>(actor_object) && server->GetServerClient())
		{
            // Synchronous: another location server may load this file as
            // soon as the lease is gone. A player who left through a level
            // changer was saved at the destination already and is not saved
            // here again; the target server owns the lease.
            const bool moved = cluster_actor_leaving(ids[i]);
            const auto key = s_actor_character.find(ids[i]);
            const xr_string login = key != s_actor_character.end() ? key->second.substr(0, key->second.rfind(':')) : xr_string();
            if (!moved && !login.empty())
            {
                const auto retry = s_actor_destroy_retry.find(ids[i]);
                if (retry != s_actor_destroy_retry.end() && u32(real_time_ms() - retry->second) < 1000)
                {
                    s_pending_lock.Enter();
                    s_pending_actor_destroy.push_back(ids[i]);
                    s_pending_lock.Leave();
                    continue;
                }
                if (!character_save_actor(ids[i], nullptr, false) || !character_account_money_commit(server, ids[i]))
                {
                    // Disk/capture failure must not turn logout into inventory
                    // loss. Retain the tracked Actor and account ownership,
                    // migrate it off the disconnected client, and retry from
                    // a later main-thread update. A fresh login remains held;
                    // retry backoff avoids repeated disk I/O every frame.
                    give_to_server(server, server->game->get_entity_from_eid(ids[i]), 0);
                    s_actor_destroy_retry[ids[i]] = real_time_ms();
                    s_pending_lock.Enter();
                    s_pending_actor_destroy.push_back(ids[i]);
                    s_pending_lock.Leave();
                    continue;
                }
                admission_leave(key->second); // the master session closes after the last save is durable
                cluster_lease_release(login.c_str());
            }
            s_actor_destroy_retry.erase(ids[i]);
            s_actor_character.erase(ids[i]);
            for (auto it = s_cluster_leaving.begin(); it != s_cluster_leaving.end();)
                if (it->second.actor == ids[i]) it = s_cluster_leaving.erase(it); else ++it;
			give_to_server(server, server->game->get_entity_from_eid(ids[i]), 0);
            // A dead body keeps its loot; a moved player's items went along.
            if (!moved && !smart_cast<CActor*>(actor_object)->g_Alive()) continue;
			Msg("[Lost Zone] removing Actor %u of a disconnected player", ids[i]);
			// An NPC still talking to this Actor would keep a dangling partner.
			CActor* leaving = smart_cast<CActor*>(actor_object);
			if (leaving && leaving->IsTalking())
			{
				if (CInventoryOwner* partner = leaving->GetTalkPartner())
					partner->StopTalk();
				leaving->StopTalk();
			}
			server_release_task_manager(ids[i]);
			actor_object->DestroyObject();
		}
		else s_actor_destroy_retry.erase(ids[i]);
	}
}

struct StoreMoney
{
	void operator()(IClient* client) const { store_money(static_cast<xrClientData*>(client)); }
};

void server_talk_prune(xrServer* server);

void server_update(xrServer* server)
{
	if (!enabled())
		return;
	// The runtime god mode (cutscenes) is cleared by showing the game UI; a
	// dedicated server has none, and the flag also stopped condition damage
	// (UpdateCondition, CanBeHarmed). Keep it off here.
	psActorFlags.set(AF_GODMODE_RT, FALSE);
	destroy_pending_actors(server);
	world_store_update(server);
	server_world_bridge_update();
	admission_update();
	admission_departures_update(server);
	server_talk_prune(server);
	characters_update(server);
	if (!s_accounts_loaded)
		return;
	StoreMoney store;
	server->ForEachClientDo(store);
	accounts_save();
}

// Every server frame. These ran from server_update, which xrServer calls
// once per 100 frames: item and corpse poses left ~1 s apart instead of
// every 50 ms, and clients glided items between them ("sliding on ice");
// bullet marks arrived late. Each has its own rate limit.
static xr_vector<Fvector> s_player_positions;

static void cache_player_positions()
{
	static u32 previous = 0;
	const u32 now = real_time_ms();
	if (previous && now - previous < 100) return;
	previous = now;
	s_player_positions.clear();
	for (u32 n = 0; n < Level().Objects.o_count(); ++n)
	{
		CActor* actor = smart_cast<CActor*>(Level().Objects.o_get_by_iterator(n));
		if (actor && actor->g_Alive() && !actor->getDestroy() && server_player_copy(actor))
			s_player_positions.push_back(actor->Position());
	}
}

// NPC AI by distance to the nearest player (doc 43 E03/E04), set on the
// server's command line (metres):
//   -netcoop_ai_far=<m>     the think interval grows to its longest at it (200)
//   -netcoop_ai_combat=<m>  an NPC fighting within it thinks at the shortest (100)
//   -netcoop_ai_path=<m>    paths are built at once within it, not in pieces (80)
float server_ai_distance(u32 kind)
{
	static float distances[ai_distance_count] = {};
	static bool read = false;
	if (!read)
	{
		read = true;
		const LPCSTR options[ai_distance_count] = {"-netcoop_ai_far=", "-netcoop_ai_combat=", "-netcoop_ai_path="};
		const float defaults[ai_distance_count] = {200.f, 100.f, 80.f};
		for (u32 i = 0; i < ai_distance_count; ++i)
		{
			LPCSTR option = strstr(Core.Params, options[i]);
			const float value = option ? float(atof(option + xr_strlen(options[i]))) : 0.f;
			distances[i] = value > 0.f ? value : defaults[i];
		}
		if (!pure_client())
			Msg("[Lost Zone][ai] NPC AI by distance to the nearest player: longest think interval at %.0f m, fights within %.0f m and "
				"paths within %.0f m at full rate", distances[ai_distance_far], distances[ai_distance_combat], distances[ai_distance_path]);
	}
	return kind < ai_distance_count ? distances[kind] : 200.f;
}

float server_nearest_player_distance(const Fvector& position)
{
	float best = 100000.f;
	for (const Fvector& player : s_player_positions)
		best = _min(best, player.distance_to(position));
	return best;
}

bool is_player(const CObject* object)
{
	return object && (object == Actor() || server_player_copy(object));
}

bool server_player_sees(const CObject* player, const CObject* object)
{
	const CActor* actor = smart_cast<const CActor*>(player);
	if (!actor || !object || !actor->g_Alive()) return false;
	Fvector to; to.sub(object->Position(), actor->Position());
	const float distance = to.magnitude();
	if (distance > 70.f) return false;
	if (distance < 2.f) return true;
	to.div(distance);
	Fvector forward; forward.setHP(-const_cast<CActor*>(actor)->netcoop_model_yaw(), 0.f);
	return forward.dotproduct(to) > 0.5f; // 120 degree view cone
}

float script_prop_shell_mass(u16 id)
{
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server) return 0.f;
	CPhysicObject* object = smart_cast<CPhysicObject*>(Level().Objects.net_Find(id));
	if (!object || object->getDestroy() || object->H_Parent() || !object->Visual()) return 0.f;
	const auto kind = netcoop_prop_mass::classify(object->cNameVisual().c_str());
	if (kind == netcoop_prop_mass::Kind::other) return 0.f;
	Fvector center, half;
	object->Visual()->getVisData().box.get_CD(center, half);
	return netcoop_prop_mass::shell(kind, 2.f * half.x, 2.f * half.y, 2.f * half.z);
}

LPCSTR script_mass_props()
{
	static xr_string ids;
	ids.clear();
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server) return "";
	for (u32 n = 0; n < Level().Objects.o_count(); ++n)
	{
		CObject* object = Level().Objects.o_get_by_iterator(n);
		if (script_prop_shell_mass(object->ID()) <= 0.f) continue;
		string16 id; xr_sprintf(id, "%u ", object->ID());
		ids += id;
	}
	return ids.c_str();
}

bool script_prop_set_mass(u16 id, float total)
{
	const float base = script_prop_shell_mass(id);
	if (!netcoop_prop_mass::valid_total(base, total)) return false;
	CPhysicObject* object = smart_cast<CPhysicObject*>(Level().Objects.net_Find(id));
	auto* entity = smart_cast<CSE_ALifeObjectPhysic*>(Level().Server->ID_to_entity(id));
	if (!object || !entity || !object->netcoop_set_content_mass(total)) return false;
	// Use the stock ALife field; no extra INI footer can conflict with saved
	// destroyable health or the map author's logic. Reapply from Lua's saved
	// contents on load because skeleton models use their authored bone masses.
	entity->mass = total;
	return true;
}

bool script_explode_as(u16 id, u16 initiator)
{
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server) return false;
	CGameObject* object = smart_cast<CGameObject*>(Level().Objects.net_Find(id));
	CExplosive* explosive = smart_cast<CExplosive*>(object);
	if (!object || !explosive || object->getDestroy() || object->H_Parent() || explosive->IsExploding()) return false;
	CObject* owner = Level().Objects.net_Find(initiator);
	Fvector normal; explosive->FindNormal(normal);
	explosive->SetInitiator(owner && !owner->getDestroy() ? initiator : id);
	explosive->GenExplodeEvent(object->Position(), normal);
	return true;
}

bool script_mine_contact(u16 id)
{
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server) return false;
	CObject* mine = Level().Objects.net_Find(id);
	if (!mine || mine->getDestroy()) return false;
	xr_vector<ISpatial*> nearby;
	g_SpatialSpace->q_sphere(nearby, 0, STYPE_COLLIDEABLE, mine->Position(), 2.5f);
	for (ISpatial* spatial : nearby)
	{
		CEntityAlive* creature = smart_cast<CEntityAlive*>(spatial->dcast_CObject());
		if (creature && creature->ID() != 0 && creature->g_Alive() && !creature->getDestroy() &&
			creature->Position().distance_to_sqr(mine->Position()) <= 2.5f * 2.5f) return true;
	}
	return false;
}

float server_luminocity(const CObject* object, float rendered)
{
	float light = 0.5f;
	CEnvDescriptorMixer* env = g_pGamePersistent && g_pGamePersistent->pEnvironment ? g_pGamePersistent->Environment().CurrentEnv : nullptr;
	if (env)
	{
		const float sun = _max(env->sun_color.x, _max(env->sun_color.y, env->sun_color.z));
		const float sky = _max(env->hemi_color.x, _max(env->hemi_color.y, env->hemi_color.z));
		const float ambient = _max(env->ambient.x, _max(env->ambient.y, env->ambient.z));
		light = sun * 0.6f + sky * 0.6f + ambient;
		clamp(light, 0.05f, 1.f);
	}
	if (const CActor* actor = smart_cast<const CActor*>(object))
		for (PIItem item : const_cast<CActor*>(actor)->inventory().m_all)
			if (const CTorch* torch = smart_cast<const CTorch*>(item))
				if (torch->torch_active()) { light = _max(light, 0.8f); break; }
	return _max(rendered, light);
}

// Memory of a location server (owner 2026-10-06, doc 49 stage 6): the DLTX
// cache keeps a parsed copy of every config file read while loading (~80 MB
// with GAMMA) for a faster second read. A dedicated server reads them once:
// a minute into the level the cache is dropped; files read later are
// cached again as usual.
static void server_drop_config_cache()
{
	static u32 level_start = 0;
	static bool dropped = false;
	if (dropped || !g_dedicated_server) return;
	const u32 now = real_time_ms();
	if (!level_start) level_start = now;
	if (now - level_start < 60000) return;
	dropped = true;
	u64 files = 0, bytes = 0, sections = 0;
	CInifile::GetCacheStats(files, bytes, sections);
	CInifile::InvalidateCache();
	Memory.mem_compact();
	Msg("[Lost Zone][memory] config cache dropped: %llu files, %.1f MB", files, double(bytes) / 1024.0 / 1024.0);
}

void server_frame_update(xrServer* server)
{
	if (!enabled() || !g_pGameLevel) return;
	server_drop_config_cache();
	world_store_cleanup_loaded();
	cache_player_positions();
	server_campfires_update(server);
	server_zones_update(server);
	server_physics_update(server);
	server_pda_update(server);
	server_marks_update(server);
	cluster_update(server);
}
