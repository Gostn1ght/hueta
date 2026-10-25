// Included in netcoop.cpp (namespace netcoop) - client side: connection, login state, replicas.
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// client
// ---------------------------------------------------------------------------
static xr_string s_client_login;
static xr_string s_client_key;
static bool s_client_register = false;
static bool s_client_loaded = false;
static bool s_client_approved = false;
static bool s_client_remembered = false;
static u8 s_client_role = role_none;
static bool s_client_role_verified = false;
static u8 s_client_character_slot = 1;
static xr_string s_client_character_name, s_client_character_faction = "stalker", s_client_character_loadout;
static xr_string s_client_description, s_client_history;
static bool firebase_enabled();
static u8 s_client_character_economy = 1;

static void client_credentials_path(string_path& path)
{
	FS.update_path(path, "$app_data_root$", "netcoop_login.txt");
}

static void client_store_credentials()
{
    xr_string plain = s_client_login + "|" + s_client_key + (s_client_approved ? "|1|" : "|0|") + role_name(s_client_role);
    DATA_BLOB input = {u32(plain.size()), (BYTE*)plain.data()}, output = {};
    // DPAPI encrypts for this Windows user on this computer. Copying the
    // remembered file to a different machine does not grant an account.
    if (!CryptProtectData(&input, L"NetAnomaly remembered account", NULL, NULL, NULL, CRYPTPROTECT_UI_FORBIDDEN, &output)) return;
    string_path path, temp;
    client_credentials_path(path); xr_sprintf(temp, "%s.tmp", path);
    FILE* f = fopen(temp, "wb");
    if (f)
    {
        const u32 magic = 0x324c434e;
        fwrite(&magic, 4, 1, f); fwrite(output.pbData, 1, output.cbData, f);
        const bool ok = !ferror(f); fclose(f);
        if (ok && MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) s_client_remembered = true;
    }
    SecureZeroMemory(output.pbData, output.cbData); LocalFree(output.pbData);
    SecureZeroMemory(&plain[0], plain.size());
}

static void client_load_credentials()
{
    if (s_client_loaded) return;
    s_client_loaded = true;
    string_path path; client_credentials_path(path);
    FILE* f = fopen(path, "rb");
    if (!f) return;
    u8 data[8192]; const u32 size = u32(fread(data, 1, sizeof(data), f)); fclose(f);
    xr_string plain;
    bool migrate = false;
    u32 magic = 0; if (size >= 4) CopyMemory(&magic, data, 4);
    if (magic == 0x324c434e)
    {
        DATA_BLOB input = {size - 4, data + 4}, output = {};
        if (!CryptUnprotectData(&input, NULL, NULL, NULL, NULL, CRYPTPROTECT_UI_FORBIDDEN, &output)) return;
        plain.assign((char*)output.pbData, output.cbData);
        SecureZeroMemory(output.pbData, output.cbData); LocalFree(output.pbData);
    }
    else
    {
        // Upgrade the old derived-key file once, without losing the login.
        plain.assign((char*)data, size); migrate = true;
    }
    const size_t separator = plain.find('|');
    if (separator != xr_string::npos)
    {
        xr_string login = plain.substr(0, separator), key = plain.substr(separator + 1);
        const size_t state = key.find('|');
        // Remembered accounts written before moderation remain approved.
        s_client_approved = state == xr_string::npos || key.substr(state + 1, 1) == "1";
        if (state != xr_string::npos)
        {
            s_client_role = key.substr(state + 3) == "admin" ? role_admin : role_none;
            key.resize(state);
        }
        const size_t end = key.find_first_of("\r\n"); if (end != xr_string::npos) key.resize(end);
        if (login_valid(login.c_str()) && key_valid(key.c_str()))
        { s_client_login = login; s_client_key = key; s_client_remembered = true; if (migrate) client_store_credentials(); }
        if (!key.empty()) SecureZeroMemory(&key[0], key.size());
    }
    if (!plain.empty()) SecureZeroMemory(&plain[0], plain.size());
    SecureZeroMemory(data, sizeof(data));
}

bool derive_client_key(LPCSTR login, LPCSTR password, xr_string& key_hex)
{
	xr_string lower = login;
	to_lower(lower);
	xr_string salt = "NetAnomaly/";
	salt += lower;

	u8 key[key_bytes];
	if (!pbkdf2(password, xr_strlen(password), salt.c_str(), (u32)salt.size(), client_key_iterations, key, key_bytes))
		return false;
	key_hex = to_hex(key, key_bytes);
	SecureZeroMemory(key, sizeof(key));
	return true;
}

bool client_set_credentials(LPCSTR login, LPCSTR password, bool register_account)
{
	if (!login || !password || !login_valid(login))
	{
		Msg("! [Lost Zone] login must be 3-20 characters: letters, digits, _ - .");
		return false;
	}
	const u32 password_length = xr_strlen(password);
	if (password_length < 4 || password_length > 64)
	{
		Msg("! [Lost Zone] password must be 4-64 characters");
		return false;
	}

	xr_string key_hex;
	if (!derive_client_key(login, password, key_hex))
	{
		Msg("! [Lost Zone] cannot derive the account key");
		return false;
	}

	s_client_loaded = true;
	s_client_login = login;
	s_client_key = key_hex;
	s_client_register = register_account;
	s_client_approved = false;
	s_client_remembered = false;
	// Persist only when the server confirms the account. A mistyped password,
	// occupied nickname or offline server must not lock the registration form.
	return true;
}

bool client_has_credentials()
{
	client_load_credentials();
	return !s_client_login.empty() && !s_client_key.empty();
}

LPCSTR client_login()
{
	client_load_credentials();
	return s_client_login.c_str();
}

u8 client_role()
{
	if (firebase_enabled()) return s_client_role;
	client_load_credentials();
	return s_client_role;
}

static xr_string client_device_key()
{
    // Prefer the firmware system UUID. Never send SMBIOS data or serials.
    xr_string identity;
    const DWORD provider = 0x52534d42; // 'RSMB'
    const UINT size = GetSystemFirmwareTable(provider, 0, nullptr, 0);
    if (size >= 8 && size <= 1024 * 1024)
    {
        xr_vector<u8> firmware(size);
        if (GetSystemFirmwareTable(provider, 0, firmware.data(), size) == size)
        {
            for (u32 at = 8; at + 4 <= size;)
            {
                const u32 length = firmware[at + 1];
                if (length < 4 || at + length > size) break;
                if (firmware[at] == 1 && length >= 25)
                {
                    bool all_zero = true, all_ff = true;
                    for (u32 n = 8; n < 24; ++n) { all_zero &= firmware[at + n] == 0; all_ff &= firmware[at + n] == 255; }
                    if (!all_zero && !all_ff) identity = to_hex(&firmware[at + 8], 16);
                    break;
                }
                at += length;
                while (at + 1 < size && (firmware[at] || firmware[at + 1])) ++at;
                at += 2;
            }
        }
    }
    // Virtual machines / missing UUID: bind to the Windows installation.
    if (identity.empty())
    {
        HKEY key = nullptr;
        if (RegOpenKeyExA(HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Cryptography", 0,
            KEY_QUERY_VALUE | KEY_WOW64_64KEY, &key) == ERROR_SUCCESS)
        {
            char guid[128] = {}; DWORD size = sizeof(guid), type = 0;
            if (RegQueryValueExA(key, "MachineGuid", nullptr, &type, (BYTE*)guid, &size) == ERROR_SUCCESS &&
                type == REG_SZ && size > 1 && size <= sizeof(guid) && guid[size - 1] == 0) identity = guid;
            RegCloseKey(key);
        }
    }
    if (identity.empty()) return xr_string();
    u8 digest[32];
    const char salt[] = "NetAnomaly device binding v1";
    if (!pbkdf2(identity.data(), u32(identity.size()), salt, sizeof(salt) - 1, 1000, digest, sizeof(digest))) return xr_string();
    return to_hex(digest, sizeof(digest));
}

#include "netcoop_firebase.inc"
#include "netcoop_world_bridge.inc"

struct StorageRequest
{
    bool active=false; u8 op=0,slot=1; u16 index=0; u32 revision=0; xr_string id;
};
static StorageRequest s_storage_request;
void storage_write_auth(NET_Packet& P)
{
    if (!s_storage_request.active || s_client_character_slot) return;
    P.w_u32(0x54535a4c); P.w_u8(s_storage_request.op); P.w_u8(s_storage_request.slot);
    P.w_u16(s_storage_request.index); P.w_u32(s_storage_request.revision); P.w_stringZ(s_storage_request.id.c_str());
    s_storage_request.active=false;
}
bool script_storage_prepare(int op,int slot,int index,int revision)
{
    if (g_pGameLevel || op<0 || op>2 || slot<1 || slot>10 || index<0 || index>511) return false;
    u8 nonce[16]; if (BCryptGenRandom(nullptr,nonce,sizeof(nonce),BCRYPT_USE_SYSTEM_PREFERRED_RNG)!=0) return false;
    s_storage_request.active=true; s_storage_request.op=u8(op); s_storage_request.slot=u8(slot);
    s_storage_request.index=u16(index); s_storage_request.revision=u32(revision); s_storage_request.id=to_hex(nonce,sizeof(nonce));
    return true;
}
// A remembered password key or a signed-in cloud (Firebase) session: the
// cloud sign-in leaves no password key, and joining a world was refused.
bool client_can_login()
{
	if (firebase_enabled() && !s_firebase_session.id.empty()) return true;
	return client_has_credentials();
}

void client_write_auth(NET_Packet& P)
{
	client_load_credentials();
    const bool cloud = firebase_enabled() && !s_firebase_session.id.empty();
	P.w_u8(cloud ? 3 : s_client_register ? auth_register : auth_login);
	P.w_stringZ(cloud ? s_firebase_session.username.c_str() : s_client_login.c_str());
	P.w_stringZ(cloud ? s_firebase_session.id.c_str() : s_client_key.c_str());
    P.w_u8(s_client_character_slot);
    P.w_stringZ(s_client_character_name.empty() ? s_client_login.c_str() : s_client_character_name.c_str());
    P.w_stringZ(s_client_character_faction.c_str());
    P.w_u8(s_client_character_economy);
    P.w_stringZ(s_client_character_name.empty() ? "device_pda_1" : s_client_character_loadout.c_str());
    P.w_stringZ(client_device_key().c_str());
    if (cloud) { P.w_stringZ(s_client_description.c_str()); P.w_stringZ(s_client_history.c_str()); }
	// Proof of the old server password when linking a migrated account back
	// to Firebase. A client-supplied device digest is not an authentication key.
	if (cloud && !stricmp(s_client_login.c_str(), s_firebase_session.username.c_str()) && key_valid(s_client_key.c_str()))
	{
		P.w_u32(0x4b4c5a4c); // LZLK, followed by the remembered password key
		P.w_stringZ(s_client_key.c_str());
	}
	storage_write_auth(P);
	s_client_register = false;
	s_client_role = role_none;
    s_client_role_verified = false;
}

static void client_cluster_transfer(LPCSTR data); // netcoop_cluster.inc

void client_on_auth_result(NET_Packet& P)
{
	client_marks_reset();
	const u8 ok = P.r_u8();
	const u8 role = P.r_u8();
	string512 message;
	if (!read_string(P, message, sizeof(message)))
		xr_strcpy(message, "");
	// The character is on another map of the cluster: go there, same login.
	if (!ok && !strncmp(message, "redirect|", 9)) return client_cluster_transfer(message + 9);

	s_client_role = ok ? role : u8(role_none);
    psActorFlags.set(AF_GODMODE, FALSE); // new/revoked auth is not an inherited god session
    s_client_role_verified = !!ok;
    const bool cloud = firebase_enabled() && !s_firebase_session.id.empty();
	if (ok) { s_client_approved = true; if (!cloud) client_store_credentials(); }
    else if (!xr_strcmp(message, "Registration pending administrator approval") || !xr_strcmp(message, "Registration rejected by administrator"))
    { s_client_approved = false; if (!cloud) client_store_credentials(); }
    else if (!cloud && !s_client_remembered)
    {
        s_client_login.clear(); s_client_key.clear();
        s_client_loaded = false; client_load_credentials();
    }
	Msg("%s [Lost Zone] %s", ok ? "*" : "!", message);
    if (ok && P.r_elapsed())
    {
        char names[1024];
        if (read_string(P, names, sizeof(names)))
        {
            ::luabind::functor<void> cache;
            if (ai().script_engine().functor("netcoop_login_ui.cache_characters", cache)) cache(names);
            char previews[14336];
            if (P.r_elapsed() && read_string(P, previews, sizeof(previews)) && previews[0] && ai().script_engine().functor("netcoop_login_ui.cache_previews", cache)) cache(previews);
        }
    }
    xr_string storage_reply;
    char storage[14336];
    if (ok && P.r_elapsed() && read_string(P,storage,sizeof(storage))) storage_reply=storage;
	call_lua("netcoop_client_compat.on_auth_result", !!ok, s_client_role, message);
    if (!storage_reply.empty())
    {
        ::luabind::functor<void> callback;
        if (ai().script_engine().functor("netcoop_login_ui.on_storage_result",callback)) callback(storage_reply.c_str());
    }
}

static bool s_trade_refresh = false;

void client_on_trade_result(NET_Packet& P)
{
	const u8 ok = P.r_u8();
	string512 message;
	if (!read_string(P, message, sizeof(message)))
		xr_strcpy(message, "");
	Msg("%s [Lost Zone] trade: %s", ok ? "*" : "!", message);
	s_trade_refresh = true;
	call_lua("netcoop_client_compat.on_trade_result", !!ok, s_client_role, message);
}

bool client_take_trade_refresh()
{
	const bool refresh = s_trade_refresh;
	s_trade_refresh = false;
	return refresh;
}

void client_on_server_text(LPCSTR text)
{
	if (pure_client() && client_admin_authorized() && text)
	{
		if (!xr_strcmp(text, "* god mode ON")) psActorFlags.set(AF_GODMODE, TRUE);
		else if (!xr_strcmp(text, "* god mode OFF")) psActorFlags.set(AF_GODMODE, FALSE);
	}
	::luabind::functor<void> f;
	if (ai().script_engine().functor("netcoop_client_compat.on_server_text", f))
	{
		try
		{
			f(text);
		}
		catch (...)
		{
		}
	}
}

void client_send_command(LPCSTR text)
{
	if (!text || !xr_strlen(text) || xr_strlen(text) > 4000 || !g_pGameLevel)
		return;
	NET_Packet P;
	P.w_begin(M_NETANOMALY_CMD);
	P.w_stringZ(text);
	Level().Send(P, net_flags(TRUE, TRUE));
}

// Lua entry points.
bool script_login(LPCSTR login, LPCSTR password, bool register_account)
{
	if (!register_account && password && !password[0])
    {
        client_load_credentials();
        return login && s_client_login == login && key_valid(s_client_key.c_str());
    }
    return client_set_credentials(login, password, register_account);
}

bool client_admin_authorized() { return s_client_role_verified && s_client_role == role_admin; }
int script_role() { return client_role(); }
LPCSTR script_account() { return client_login(); }

// Owner 2026-10-17: players enter only the world master's address. Its public
// entry (TCP, port 5446 by default - owner 2026-10-25) names the location to
// connect to: for the account and
// slot (owner 2026-10-24) the map the character was on last, Cordon for a new
// one. "" when no master answers there (a location address, an older host):
// the address is then used as it is. At most ~1.5 s, on a button press only.
LPCSTR script_master_entry(LPCSTR address, LPCSTR account, int slot)
{
	static string256 answer;
	answer[0] = 0;
	if (!address || xr_strlen(address) > 200) return answer;
	xr_string text = address, host;
	u32 port = 5446;
	const size_t colon = text.rfind(':');
	if (colon != xr_string::npos)
	{
		host = text.substr(0, colon);
		port = u32(atoi(text.c_str() + colon + 1));
	}
	else host = text;
	auto valid_host = [](const xr_string& value)
	{
		if (value.empty() || value.size() > 253) return false;
		for (char c : value)
			if (!isalnum(u8(c)) && c != '.' && c != '-') return false;
		return true;
	};
	if (!valid_host(host) || port < 1 || port > 65535) return answer;
	std::wstring wide(host.begin(), host.end());
	HINTERNET session = WinHttpOpen(L"LostZone/1.0", WINHTTP_ACCESS_TYPE_NO_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
	if (!session) return answer;
	WinHttpSetTimeouts(session, 1500, 1500, 1500, 1500);
	HINTERNET connection = WinHttpConnect(session, wide.c_str(), INTERNET_PORT(port), 0);
	// The login is a public name (letters, digits, _ . -): no escaping needed.
	std::wstring path = L"/v1/entry";
	if (account && login_valid(account) && slot >= 0 && slot <= 10)
	{
		path += L"?account=";
		for (const char* c = account; *c; ++c) path += wchar_t(*c);
		path += L"&slot=" + std::to_wstring(slot);
	}
	HINTERNET request = connection ? WinHttpOpenRequest(connection, L"GET", path.c_str(), nullptr,
		WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0) : nullptr;
	std::string body;
	DWORD status = 0, size = sizeof(status);
	if (request && WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
		WinHttpReceiveResponse(request, nullptr) &&
		WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX,
			&status, &size, WINHTTP_NO_HEADER_INDEX) && status == 200)
	{
		char buffer[1024];
		DWORD read = 0;
		while (body.size() < 4096 && WinHttpReadData(request, buffer, sizeof(buffer), &read) && read)
			body.append(buffer, read);
	}
	if (request) WinHttpCloseHandle(request);
	if (connection) WinHttpCloseHandle(connection);
	WinHttpCloseHandle(session);
	if (body.empty() || body.size() >= 4096) return answer;
	try
	{
		const auto entry = nlohmann::json::parse(body);
		if (!entry.is_object() || entry.value("schema", 0) != 1) return answer;
		const xr_string target = entry.value("host", std::string()).c_str();
		const int target_port = entry.value("port", 0);
		const xr_string location = entry.value("location", std::string()).c_str();
		if (target_port < 1 || target_port > 65535 || (!target.empty() && !valid_host(target))) return answer;
		// No host of its own: the location runs on the master's machine.
		xr_sprintf(answer, "%s:%d", target.empty() ? host.c_str() : target.c_str(), target_port);
		Msg("[Lost Zone] the world master at %s sends players to %s (%s)", address, answer, location.c_str());
	}
	catch (...) { answer[0] = 0; }
	return answer;
}
int script_account_state() { return !client_has_credentials() || !s_client_remembered ? 0 : s_client_approved ? 2 : 1; }
static IRenderVisual* s_preview_visual = nullptr;
static xr_string s_preview_name, s_preview_motion, s_preview_item_name;
static IRenderVisual* s_preview_item = nullptr;
static Fmatrix s_preview_item_offset;
static bool s_preview_armed = false;
static u32 s_preview_torso_restart = 0;
static xr_string s_preview_torso_motion;
static float s_preview_heading = 0.f;
static int s_preview_facing_axis = 0;
static bool s_preview_facing_ready = false;
static u32 s_preview_restart = 0;
static bool s_preview_seated=false;
static u32 s_preview_idle_change=0,s_preview_frame=0;
static xr_vector<shared_str> s_preview_seated_motions;
static u32 s_preview_idle_seed=0x31415926;
static u32 preview_random() { s_preview_idle_seed=1664525u*s_preview_idle_seed+1013904223u; return s_preview_idle_seed; }
// Preview tracks are advanced by the continual menu clock in draw(), once.
// CalculateBones must not advance them again using the world clock.
static struct PreviewTracks : IUpdateTracksCallback
{
    bool operator()(float,IKinematicsAnimated&) override { return true; }
} s_preview_tracks;
static void preview_loop(IKinematicsAnimated* skeleton,MotionID motion,float speed)
{
    struct Loop : IterateBlendsCallback
    {
        MotionID id; float rate;
        Loop(MotionID motion,float speed):id(motion),rate(speed) {}
        void operator()(CBlend& blend) override
        {
            if (blend.motionID.slot!=id.slot || blend.motionID.idx!=id.idx) return;
            blend.stop_at_end=FALSE; blend.fall_at_end=FALSE;
            blend.stop_at_end_callback=FALSE; blend.playing=TRUE; blend.speed=rate;
        }
    } callback(motion,speed);
    skeleton->LL_IterateBlends(callback);
}

void script_preview_clear()
{
    menu_room::reset();
    // Input and Lua callbacks can occur during rendering. Defer through the pool.
    if (s_preview_item) Render->model_Delete(s_preview_item, FALSE);
    if (s_preview_visual) Render->model_Delete(s_preview_visual, FALSE);
    s_preview_item_name.clear(); s_preview_armed = false;
    s_preview_torso_motion.clear(); s_preview_torso_restart = 0; s_preview_facing_ready = false;
    s_preview_name.clear(); s_preview_motion.clear(); s_preview_restart = 0;
    s_preview_seated=false; s_preview_idle_change=s_preview_frame=0; s_preview_seated_motions.clear();
}

bool script_preview_model(LPCSTR model, int pose)
{
    if (g_pGameLevel || !model || !Render->models_Exists(model)) return false;
    if (s_preview_name != model)
    {
        script_preview_clear();
        s_preview_visual = Render->model_Create(model);
        if (!Render->PrepareUIModel(s_preview_visual)) { script_preview_clear(); return false; }
        s_preview_name = model;
    }
    auto k = s_preview_visual->dcast_PKinematicsAnimated();
    if (!k) return true;
    LPCSTR motion = "norm_idle_0";

    s_preview_seated=pose==-2;
    k->SetUpdateTracksCalback(s_preview_seated ? &s_preview_tracks : nullptr);
    s_preview_armed = pose == -1 && s_preview_item;
    if (s_preview_seated)
    {
        s_preview_seated_motions.clear();
        for (LPCSTR candidate:{"animpoint_sit_low_idle_1","animpoint_sit_low_idle_rnd_1","animpoint_sit_low_idle_rnd_2","animpoint_sit_low_idle_rnd_3","animpoint_sit_low_idle_rnd_4"})
            if (k->ID_Cycle_Safe(candidate).valid()) s_preview_seated_motions.push_back(candidate);
        if (s_preview_seated_motions.empty())
            for (LPCSTR candidate:{"animpoint_sit_high_idle_1","jup_b15_zulus_sit_idle"})
                if(k->ID_Cycle_Safe(candidate).valid()) { s_preview_seated_motions.push_back(candidate); break; }
        if(s_preview_seated_motions.empty()) { script_preview_clear(); return false; }
        motion=s_preview_seated_motions.front().c_str();
        s_preview_idle_seed=Device.dwTimeContinual|1; s_preview_idle_change=Device.dwTimeContinual+12000;
        Msg("[Lost Zone] sofa preview: %s, %u available idle motions",motion,u32(s_preview_seated_motions.size()));
    }
    if (pose >= 0 && pose < int(rp_anims().size()))
        for (const auto& candidate : rp_anims()[pose].mid)
            if (k->ID_Cycle_Safe(candidate.c_str()).valid()) { motion = candidate.c_str(); break; }
    const MotionID id = k->ID_Cycle_Safe(motion);
    if (!id.valid()) return false;
    // Cancel previous RP tracks before starting the selected preview.
    k->PlayCycle("norm_idle_0", FALSE);
    k->UpdateTracks();
    auto bones = s_preview_visual->dcast_PKinematics();
    if (bones && !s_preview_facing_ready)
    {
        bones->CalculateBones_Invalidate(); bones->CalculateBones(TRUE);
        const u16 root = bones->LL_BoneID("bip01");
        if (root != BI_NONE)
        {
            const auto& transform = bones->LL_GetTransform(root);
            const Fvector axes[] = {transform.i,transform.j,transform.k};
            float largest = 0.f;
            for(int axis=0;axis<3;++axis)
            {
                const float length = axes[axis].x*axes[axis].x+axes[axis].z*axes[axis].z;
                if(length>largest) { largest=length;s_preview_facing_axis=axis; }
            }
            const auto& forward=axes[s_preview_facing_axis];
            s_preview_heading=atan2f(forward.x,forward.z);s_preview_facing_ready=true;
        }
    }
    s_preview_torso_motion.clear(); s_preview_torso_restart=0;
    s_preview_motion = motion;
    CBlend* blend = k->PlayCycle(id, FALSE);
    if (s_preview_seated) preview_loop(k,id,.94f);
    if (blend) { blend->speed = _min(blend->speed, 1.f); s_preview_restart = Device.dwTimeGlobal + u32(blend->timeTotal / _max(.1f, blend->speed) * 1000.f); }
    if (pose == -1)
    {
        LPCSTR torso = "norm_torso_0_aim_0";
        string128 armed;
        if (s_preview_item && pSettings->line_exist(s_preview_item_name.c_str(),"animation_slot"))
        {
            // Actor's slot zero uses animation set one.
            xr_sprintf(armed,"norm_torso_%u_aim_1",pSettings->r_u32(s_preview_item_name.c_str(),"animation_slot")+1);
            if(k->ID_Cycle_Safe(armed).valid()) torso=armed;
        }
        if(k->ID_Cycle_Safe(torso).valid())
        {
            s_preview_torso_motion=torso;
            if(auto torsoBlend=k->PlayCycle(torso,FALSE))
                s_preview_torso_restart=Device.dwTimeGlobal+u32(torsoBlend->timeTotal/_max(.1f,torsoBlend->speed)*1000.f);
        }
        if(k->ID_Cycle_Safe("head_idle_0").valid()) k->PlayCycle("head_idle_0",FALSE);
    }
    return true;
}

bool script_preview_weapon(LPCSTR section)
{
    if (s_preview_item) Render->model_Delete(s_preview_item, FALSE);
    s_preview_item_name.clear(); s_preview_armed = false;
    if (!section || !section[0]) return true;
    if (g_pGameLevel || !pSettings->section_exist(section) || !pSettings->line_exist(section, "visual")) return false;
    LPCSTR model = pSettings->r_string(section, "visual");
    if (!Render->models_Exists(model)) return false;
    s_preview_item = Render->model_Create(model);
    if (!Render->PrepareUIModel(s_preview_item)) { Render->model_Delete(s_preview_item, FALSE); return false; }
    Fvector position, orientation; position.set(0, 0, 0); orientation.set(0, 0, 0);
    if (pSettings->line_exist(section, "position")) position = pSettings->r_fvector3(section, "position");
    if (pSettings->line_exist(section, "orientation")) orientation = pSettings->r_fvector3(section, "orientation");
    orientation.mul(PI / 180.f); s_preview_item_offset.setHPB(orientation.x, orientation.y, orientation.z);
    s_preview_item_offset.translate_over(position); s_preview_item_name = section;
    return true;
}
// Project the actual room interaction points into the 1024 x 768 UI space.
Fvector2 script_preview_point(int object)
{
    Fvector point=menu_room::interaction(object);
    Fmatrix view, projection, combined;
    menu_room::matrices(view,projection);
    Fvector local; view.transform_tiny(local,point);
    Fvector2 result; result.set(-10000,-10000);
    if (local.z<=.08f) return result;
    combined.mul(projection, view); combined.transform(point);
    result.set((point.x + 1.f) * 512.f, (1.f - point.y) * 384.f); return result;
}

void script_preview_focus(int object) { menu_room::focus(object); }
// Room object under a UI point (1024 x 768), -1 when none; hover(-1) clears.
int script_preview_pick(float x, float y) { return menu_room::pick(x, y); }
void script_preview_hover(int object) { menu_room::hover(object); }
bool script_preview_ready() { return menu_room::ready(); }
bool script_preview_visible() { return s_preview_visual && menu_room::visible(); }

void script_preview_draw()
{
    if (!s_preview_visual || g_pGameLevel) return;
    if (auto k = s_preview_visual->dcast_PKinematicsAnimated())
    {
        if (s_preview_seated)
        {
            const u32 now=Device.dwTimeContinual;
            if(now>=s_preview_idle_change)
            {
                s_preview_motion=s_preview_seated_motions[preview_random()%s_preview_seated_motions.size()].c_str();
                const MotionID id=k->ID_Cycle_Safe(s_preview_motion.c_str());
                if (k->PlayCycle(id,TRUE)) preview_loop(k,id,.90f+float(preview_random()%15)*.01f);
                s_preview_idle_change=now+12000+preview_random()%10000;
            }
            // The menu runs on a continual clock, independently of a paused game.
            k->LL_UpdateTracks(s_preview_frame ? _min(.066f,float(now-s_preview_frame)/1000.f) : 0.f,true,false);
            s_preview_frame=now;
        }
        if (!s_preview_seated && s_preview_restart && Device.dwTimeGlobal >= s_preview_restart)
        {
            CBlend* blend = k->PlayCycle(s_preview_motion.c_str(), FALSE);
            if (blend) { blend->speed = _min(blend->speed, 1.f); s_preview_restart = Device.dwTimeGlobal + u32(blend->timeTotal / _max(.1f, blend->speed) * 1000.f); }
        }
        if (s_preview_torso_restart && Device.dwTimeGlobal >= s_preview_torso_restart)
            if (auto blend=k->PlayCycle(s_preview_torso_motion.c_str(),FALSE))
                s_preview_torso_restart=Device.dwTimeGlobal+u32(blend->timeTotal/_max(.1f,blend->speed)*1000.f);
        if(!s_preview_seated) k->UpdateTracks();
    }
    float heading=menu_room::seat_heading();
    if (auto k = s_preview_visual->dcast_PKinematics())
    {
        k->CalculateBones_Invalidate();
        k->CalculateBones(TRUE);
        const u16 root=k->LL_BoneID("bip01");
        if(s_preview_facing_ready && root!=BI_NONE)
        {
            const auto& transform=k->LL_GetTransform(root);
            const Fvector axes[]={transform.i,transform.j,transform.k};
            const auto& forward=axes[s_preview_facing_axis];
            if(forward.x*forward.x+forward.z*forward.z>EPS_S)
                heading+=s_preview_heading-atan2f(forward.x,forward.z);
        }
    }
    Fmatrix world; world.rotateY(heading);
    // The preview's lowest bound rests on the room's y=0 floor.
    world.c.y=_max(-.25f,_min(.25f,-s_preview_visual->getVisData().box.min.y));
    if(s_preview_seated)
    {
        if(auto skeleton=s_preview_visual->dcast_PKinematics())
        {
            const u16 pelvis=skeleton->LL_BoneID("bip01_pelvis");
            if(pelvis!=BI_NONE)
            {
                Fvector local; world.transform_dir(local,skeleton->LL_GetTransform(pelvis).c);
                world.c.sub(menu_room::seat_position(),local);
            }
        }
    }
    Fmatrix itemWorld;
    IRenderVisual* item = nullptr;
    if (s_preview_item && s_preview_armed)
    {
        auto skeleton = s_preview_visual->dcast_PKinematics();
        const u16 right = skeleton ? skeleton->LL_BoneID("bip01_r_finger1") : BI_NONE;
        const u16 left = skeleton ? skeleton->LL_BoneID("bip01_l_finger1") : BI_NONE;
        if (right != BI_NONE && left != BI_NONE)
        {
            const Fmatrix& r = skeleton->LL_GetTransform(right);
            const Fmatrix& l = skeleton->LL_GetTransform(left);
            Fvector direction, axis, normal;
            direction.sub(l.c, r.c);
            Fmatrix grip = r;
            if (direction.square_magnitude() > EPS_S)
            {
                direction.normalize(); axis.crossproduct(r.j, direction);
                if (axis.square_magnitude() < EPS_S) axis.crossproduct(r.i, direction);
                if (axis.square_magnitude() > EPS_S)
                {
                    axis.normalize(); normal.crossproduct(direction, axis); normal.normalize();
                    grip.set(axis, normal, direction, r.c);
                }
            }
            Fmatrix local; local.mul_43(grip, s_preview_item_offset); itemWorld.mul_43(world, local);
            if (auto animated = s_preview_item->dcast_PKinematicsAnimated()) animated->UpdateTracks();
            if (auto bones = s_preview_item->dcast_PKinematics()) bones->CalculateBones(TRUE);
            item = s_preview_item;
        }
    }
    if(s_preview_seated && s_preview_item)
    {
        item=s_preview_item; itemWorld.setHPB(PI*.6f,0,PI*.5f);
        itemWorld.c.set(.3f,.70f,.57f);
        if (auto k=item->dcast_PKinematicsAnimated()) k->UpdateTracks();
        if (auto k=item->dcast_PKinematics()) k->CalculateBones(TRUE);
    }
    Render->DrawUIModel(s_preview_visual, world, item, item ? &itemWorld : nullptr);
}
void script_command(LPCSTR text) { client_send_command(text); }

// Lua trade UIs (GAMMA ui_inventory) ask the server for a deal: the items
// (space separated ids) the actor sells to or buys from the partner. The
// server prices and executes it; M_NETCOOP_TRADE_RESULT reports back.
// Transaction ids of this client: a random start, then sequential.
u32 client_next_txid()
{
	static u32 next = 0;
	if (!next)
	{
		u8 bytes[4] = {};
		random_bytes(bytes, sizeof(bytes));
		next = (u32(bytes[0]) << 24 | u32(bytes[1]) << 16 | u32(bytes[2]) << 8) | 1;
	}
	return next++;
}

bool script_trade(u16 partner_id, bool actor_sells, LPCSTR ids)
{
	if (!pure_client() || !ids)
		return false;
	xr_vector<u16> list;
	for (LPCSTR p = ids; *p;)
	{
		char* end = 0;
		const unsigned long id = strtoul(p, &end, 10);
		if (end == p)
		{
			++p;
			continue;
		}
		if (id < 0xffff)
			list.push_back(u16(id));
		p = end;
	}
	if (list.empty() || list.size() > 256)
		return false;
	// The server prices and moves the items with their latest state.
	client_items_update(true);
	NET_Packet P;
	P.w_begin(M_NETCOOP_TRADE);
	P.w_u32(client_next_txid());
	P.w_u16(partner_id);
	P.w_u8(actor_sells ? trade_actor_sells : trade_actor_buys);
	P.w_u16(u16(list.size()));
	for (u32 i = 0; i < list.size(); ++i)
		P.w_u16(list[i]);
	Level().Send(P, net_flags(TRUE, TRUE));
	return true;
}
bool script_pure_client() { return pure_client(); }
