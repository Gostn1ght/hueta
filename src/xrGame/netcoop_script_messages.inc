// Included in netcoop.cpp (namespace netcoop) - server Lua -> client Lua messages.
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// server Lua -> client Lua messages
// ---------------------------------------------------------------------------
struct CollectLoggedIn
{
	xr_vector<ClientID>* ids;
	void operator()(IClient* client) const
	{
		xrClientData* CL = static_cast<xrClientData*>(client);
		if (CL && !CL->flags.bLocal && CL->netcoop_role != role_none)
			ids->push_back(CL->ID);
	}
};

void script_broadcast(LPCSTR channel, LPCSTR data)
{
	if (!enabled() || !g_pGameLevel || !Level().Server || !channel || !channel[0])
		return;
	if (!data)
		data = "";
	if (xr_strlen(channel) >= 64 || xr_strlen(data) >= 8000)
	{
		Msg("! [Lost Zone] script message '%s' is too large", channel);
		return;
	}
	xr_vector<ClientID> ids;
	CollectLoggedIn collect;
	collect.ids = &ids;
	Level().Server->ForEachClientDo(collect);
	for (u32 i = 0; i < ids.size(); ++i)
	{
		NET_Packet P;
		P.w_begin(M_NETCOOP_SCRIPT);
		P.w_stringZ(channel);
		P.w_stringZ(data);
		Level().Server->SendTo(ids[i], P, net_flags(TRUE, TRUE));
	}
}

void client_on_script(NET_Packet& P)
{
	if (!pure_client())
		return;
	string64 channel;
	static char data[8192];
	if (!read_string(P, channel, sizeof(channel)) || !read_string(P, data, sizeof(data)))
		return;
	if (!xr_strcmp(channel, "netcoop_transfer")) return client_cluster_transfer(data);
	if (!xr_strcmp(channel, "netcoop_zones")) return client_on_zones(data);
	if (!xr_strcmp(channel,"netcoop_life_ended")) {
		::luabind::functor<void> ended;
		if(ai().script_engine().functor("netcoop_login_ui.on_life_ended",ended)) {
			try {ended();}catch(...) {Msg("! [diag][character] life-ended menu callback failed");}
		}
		Engine.Event.Defer("KERNEL:disconnect");
		return;
	}
	if (!xr_strcmp(channel,"netcoop_admin_state")) {
		unsigned god=0,ammo=0;
		if(sscanf(data,"%u|%u",&god,&ammo)!=2 || god>1 || ammo>1) return;
		psActorFlags.set(AF_GODMODE,client_admin_authorized() && god);
		psActorFlags.set(AF_UNLIMITEDAMMO,client_admin_authorized() && ammo);
		return;
	}
	if(!xr_strcmp(channel,"netcoop_noclip")) {
		CActor* actor=smart_cast<CActor*>(Level().CurrentControlEntity());
		if(actor)actor->netcoop_set_noclip(client_admin_authorized() && !xr_strcmp(data,"1"));
		return;
	}
	if (!xr_strcmp(channel, "netcoop_actor_faction"))
	{
		// A player's faction or disguise changed on the server (netcoop_factions,
		// owner 2026-10-24 spec 7.1-7.2): a client has no ALife, so a script's
		// set_character_community does nothing here; the server's word does.
		unsigned id = 0;
		string128 name = {};
		if (sscanf(data, "%u|%127s", &id, name) != 2 || id >= 0xffff) return;
		const COMMUNITY_DATA* known = CHARACTER_COMMUNITY::GetById(shared_str(name), true);
		CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(u16(id)));
		if (known && actor) actor->netcoop_show_community(known->index);
		return;
	}
	if (!xr_strcmp(channel, "netcoop_consumption"))
	{
		unsigned id=0, kind=0;
		LPCSTR name=nullptr, section=nullptr;
		if (!netcoop_consumption::parse(data,id,kind,name,section)) return;
		CActor* actor=smart_cast<CActor*>(Level().Objects.net_Find(u16(id)));
		// Delayed messages must not animate a different incarnation of this ID.
		if (actor && !xr_strcmp(actor->cName().c_str(),name)) actor->netcoop_play_consumption(u8(kind),section);
		return;
	}
	if (!xr_strcmp(channel, "netcoop_role"))
	{
		// The server console changed this account's role while it is online.
		const bool admin = !xr_strcmp(data, "admin");
		s_client_role = admin ? role_admin : role_player;
		s_client_role_verified = true;
		if (!admin) {
			psActorFlags.set(AF_GODMODE, FALSE);
			psActorFlags.set(AF_UNLIMITEDAMMO, FALSE);
			if(CActor* actor=smart_cast<CActor*>(Level().CurrentControlEntity()))actor->netcoop_set_noclip(false);
		}
		// The admin's debug/spawn menu keys were registered only at login
		// (owner 2026-10-18: admin given from the master window needed a relog).
		call_lua("netcoop_client_compat.on_role_changed", true, s_client_role, "");
		return client_on_server_text(*CStringTable().translate(admin ? "st_netcoop_role_admin" : "st_netcoop_role_player"));
	}
	if (!xr_strcmp(channel, "netcoop_transfer_refused"))
	{
		// The server names the reason in English; the player reads it in the
		// game's language (st_netcoop.xml).
		static const struct { LPCSTR reason, key; } reasons[] = {
			{"not inside", "st_netcoop_passage_not_inside"}, {"passage is closed", "st_netcoop_passage_closed"},
			{"no server runs", "st_netcoop_passage_no_server"}, {"is offline", "st_netcoop_passage_offline"},
			{"is full", "st_netcoop_passage_full"}, {"is starting", "st_netcoop_passage_starting"}, {"still loading", "st_netcoop_passage_loading"},
			{"could not be saved", "st_netcoop_passage_save_failed"},
		};
		LPCSTR key = "st_netcoop_passage_unavailable";
		for (const auto& r : reasons)
			if (strstr(data, r.reason)) { key = r.key; break; }
		Msg("[Lost Zone][cluster] passage refused: %s", data);
		return client_on_server_text(*CStringTable().translate(key));
	}
	::luabind::functor<void> f;
	if (!ai().script_engine().functor("netcoop_client_compat.on_script_message", f))
		return;
	try
	{
		f((LPCSTR)channel, (LPCSTR)data);
	}
	catch (...)
	{
	}
}

bool script_send_to_actor(u16 actor_id, LPCSTR channel, LPCSTR data)
{
	if (!enabled() || !g_pGameLevel || !Level().Server || !channel || !channel[0])
		return false;
	if (!data)
		data = "";
	if (xr_strlen(channel) >= 64 || xr_strlen(data) >= 8000)
		return false;
	FindActorOwner find;
	find.actor_id = actor_id;
	xrClientData* CL = static_cast<xrClientData*>(Level().Server->FindClient(find));
	if (!CL)
		return false;
	NET_Packet P;
	P.w_begin(M_NETCOOP_SCRIPT);
	P.w_stringZ(channel);
	P.w_stringZ(data);
	Level().Server->SendTo(CL->ID, P, net_flags(TRUE, TRUE));
	return true;
}

bool server_open_ui(u16 actor_id, LPCSTR kind, u16 partner_id)
{
	const bool dialog_trade = kind && !xr_strcmp(kind, "trade");
	const xr_string refusal = prepare_trade(partner_id, dialog_trade);
	// A trade the server would refuse item by item does not open: the
	// player hears why at once (owner 2026-10-18: "Buy does nothing").
	if (dialog_trade && !refusal.empty() && enabled() && g_pGameLevel && Level().Server)
	{
		FindActorOwner find;
		find.actor_id = actor_id;
		if (xrClientData* CL = static_cast<xrClientData*>(Level().Server->FindClient(find)))
		{
			send_trade_result(Level().Server, CL, false, refusal.c_str());
			Msg("[Lost Zone] open trade with %u for Actor %u refused: %s", partner_id, actor_id, refusal.c_str());
			return true;
		}
	}
	string128 data;
	xr_sprintf(data, "%s %u", kind, partner_id);
	const bool sent = script_send_to_actor(actor_id, "open_ui", data);
	if (sent && dialog_trade)
		s_dialog_trade[actor_id] = DialogTrade{partner_id, Device.dwTimeGlobal};
	if (enabled() && g_pGameLevel && Level().Server)
		Msg("[Lost Zone] open %s with %u for Actor %u: %s", kind, partner_id, actor_id, sent ? "sent" : "no remote owner");
	return sent;
}

// Script hang watchdog. A mod script that never returns freezes the whole
// process (window, input, network). A watcher thread notices a frame that
// takes over 20 s and arms a Lua count hook: the hook logs the Lua stack of
// the running script and, after 60 s, aborts that script call with an error.
// No hook is installed while frames advance, so normal play costs nothing.
namespace
{
volatile LONG wd_armed = 0;
volatile LONG wd_quiescent = 0;
SRWLOCK wd_hook_guard = SRWLOCK_INIT;
volatile u32 wd_frame = 0;
volatile u32 wd_since = 0;
volatile bool wd_logged = false;

void wd_disarm(lua_State* L)
{
	lua_sethook(L, 0, 0, 0);
	InterlockedExchange(&wd_armed, 0);
}

void wd_pause(lua_State* (*state)())
{
	// Serialize hook installation with level teardown. Lua is still alive here.
	AcquireSRWLockExclusive(&wd_hook_guard);
	InterlockedExchange(&wd_quiescent, 1);
	if (wd_armed) wd_disarm(state());
	ReleaseSRWLockExclusive(&wd_hook_guard);
}

void wd_resume()
{
	AcquireSRWLockExclusive(&wd_hook_guard);
	wd_frame = 0;
	InterlockedExchange(&wd_quiescent, 0);
	ReleaseSRWLockExclusive(&wd_hook_guard);
}

void wd_hook(lua_State* L, lua_Debug*)
{
	if (InterlockedCompareExchange(&wd_quiescent, 0, 0) || Device.dwFrame != wd_frame)
	{
		wd_disarm(L);
		return;
	}
	const u32 stuck = GetTickCount() - wd_since;
	if (!wd_logged)
	{
		wd_logged = true;
		Msg("! [Lost Zone] script hang: frame %u has run for %u s, Lua stack:", wd_frame, stuck / 1000);
		lua_Debug ar;
		for (int level = 0; level < 24 && lua_getstack(L, level, &ar); ++level)
		{
			if (!lua_getinfo(L, "nSl", &ar))
				break;
			Msg("! [Lost Zone]   %2d: %s:%d %s", level, ar.short_src, ar.currentline, ar.name ? ar.name : "?");
		}
		FlushLog();
	}
	// GAMMA loading can include minutes of legitimate callbacks and shader work.
	// Keep diagnostics, but give loading a bounded budget before aborting Lua.
	const u32 abort_after = (!g_loading_events.empty() || (!g_dedicated_server && Device.dwPrecacheFrame)) ?
		20 * 60 * 1000 : 60000;
	if (stuck > abort_after)
	{
		wd_disarm(L);
		wd_frame = 0; // re-arm if the script catches the error and goes on
		Msg("! [Lost Zone] script hang: aborting the script call");
		FlushLog();
		luaL_error(L, "netcoop: script hung for %u s", stuck / 1000);
	}
}

bool wd_try_arm(u32 frame, u32 since, u32 now, lua_State* (*state)())
{
	AcquireSRWLockExclusive(&wd_hook_guard);
	bool armed = false;
	if (!wd_quiescent && !wd_armed && wd_frame != frame)
	{
		// Fetch Lua only under the same guard used before its level is destroyed.
		lua_State* L = state();
		if (L)
		{
			wd_frame = frame; wd_since = since; wd_logged = false;
			InterlockedExchange(&wd_armed, 1);
			Msg("! [Lost Zone] frame %u stuck for %u s, watching scripts", frame, (now - since) / 1000);
			lua_sethook(L, wd_hook, LUA_MASKCOUNT, 10000);
			armed = true;
		}
	}
	ReleaseSRWLockExclusive(&wd_hook_guard);
	return armed;
}

// Hitch sampling: a frame over 100 ms gets the main thread's native stack
// logged (at most once a second), so stutter can be attributed to a system
// or a script callback. The thread is suspended only while its stack is
// unwound, without allocations or locks.
HANDLE wd_main_thread = 0;

u32 sample_stack(HANDLE thread, DWORD64* pcs, u32 max_pcs)
{
	if (!thread || SuspendThread(thread) == DWORD(-1))
		return 0;
	u32 count = 0;
	CONTEXT ctx;
	ZeroMemory(&ctx, sizeof(ctx));
	ctx.ContextFlags = CONTEXT_FULL;
	if (GetThreadContext(thread, &ctx))
	{
		while (count < max_pcs && ctx.Rip)
		{
			pcs[count++] = ctx.Rip;
			DWORD64 image_base = 0;
			PRUNTIME_FUNCTION fn = RtlLookupFunctionEntry(ctx.Rip, &image_base, 0);
			if (!fn)
				break; // generated code (LuaJIT traces) has no unwind data
			void* handler_data = 0;
			DWORD64 establisher = 0;
			RtlVirtualUnwind(UNW_FLAG_NHANDLER, image_base, ctx.Rip, fn, &ctx, &handler_data, &establisher, 0);
		}
	}
	ResumeThread(thread);
	return count;
}
u32 sample_main_stack(DWORD64* pcs, u32 max_pcs) { return sample_stack(wd_main_thread, pcs, max_pcs); }

// Frames are written as module+offset (the game exe as a plain address at
// its fixed base); scratchpad symhitch.py resolves them with the PDB. No
// dbghelp in the process: its state is the crash handler's.
void log_hitch(u32 frame, u32 ms, const DWORD64* pcs, u32 count, LPCSTR tag = "hitch")
{
	string4096 line;
	xr_sprintf(line, "[Lost Zone][%s] frame %u at %u ms:", tag, frame, ms);
	const HMODULE exe = GetModuleHandle(0);
	for (u32 i = 0; i < count; ++i)
	{
		string128 part;
		HMODULE module = 0;
		GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
		                   (LPCSTR)pcs[i], &module);
		if (!module || module == exe)
			xr_sprintf(part, " < %llx", pcs[i]);
		else
		{
			string_path path;
			GetModuleFileNameA(module, path, sizeof(path));
			LPCSTR name = strrchr(path, '\\');
			xr_sprintf(part, " < %s+%llx", name ? name + 1 : path, pcs[i] - DWORD64(module));
		}
		xr_strcat(line, part);
	}
	Msg("%s", line);
}

// -netcoop_sample_profile: where the main thread spends its time. Every 10 ms
// its stack is sampled; every 30 s the addresses seen most (inclusive: once
// per sample at any depth, and self: top of stack) are logged as
// [sample-profile] lines; tools/symaddr.py names them from the PDB.
struct SampleProfile
{
	xr_unordered_map<DWORD64, u32> inclusive, self;
	u32 samples = 0, started = 0;
};

void sample_profile_step(SampleProfile& profile, u32 now)
{
	DWORD64 pcs[32];
	const u32 count = sample_main_stack(pcs, 32);
	if (!count) return;
	++profile.samples;
	++profile.self[pcs[0]];
	for (u32 i = 0; i < count; ++i)
	{
		bool seen = false;
		for (u32 j = 0; j < i && !seen; ++j) seen = pcs[j] == pcs[i];
		if (!seen) ++profile.inclusive[pcs[i]];
	}
	if (!profile.started) profile.started = now;
	if (now - profile.started < 30000) return;
	auto dump = [&](LPCSTR kind, xr_unordered_map<DWORD64, u32>& counts, u32 top)
	{
		xr_vector<std::pair<u32, DWORD64>> sorted;
		for (const auto& entry : counts) sorted.push_back({entry.second, entry.first});
		std::sort(sorted.begin(), sorted.end(), [](const std::pair<u32, DWORD64>& a, const std::pair<u32, DWORD64>& b) { return a.first > b.first; });
		for (u32 i = 0; i < sorted.size() && i < top; ++i)
		{
			DWORD64 pc = sorted[i].second;
			string256 line;
			HMODULE module = 0;
			GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)pc, &module);
			if (!module || module == GetModuleHandle(0))
				xr_sprintf(line, "%llx", pc);
			else
			{
				string_path path;
				GetModuleFileNameA(module, path, sizeof(path));
				LPCSTR name = strrchr(path, '\\');
				xr_sprintf(line, "%s+%llx", name ? name + 1 : path, pc - DWORD64(module));
			}
			Msg("[Lost Zone][sample-profile] %s %5.1f%% %s", kind, 100.f * sorted[i].first / profile.samples, line);
		}
	};
	Msg("[Lost Zone][sample-profile] %u samples of the main thread in %u s", profile.samples, (now - profile.started) / 1000);
	dump("self", profile.self, 40);
	dump("incl", profile.inclusive, 80);
	profile.inclusive.clear();
	profile.self.clear();
	profile.samples = 0;
	profile.started = now;
}

DWORD WINAPI wd_thread(void*)
{
	u32 last_frame = Device.dwFrame;
	u32 since = GetTickCount();
	u32 sampled_frame = 0;
	u32 next_sample = 0;
	const bool sampling = strstr(Core.Params, "-netcoop_sample_profile") != nullptr;
	// Stack traces of slow frames are a developer tool (owner 2026-10-12: no
	// stack traces in the consoles): only with -netcoop_hitch_trace.
	const bool hitch_trace = strstr(Core.Params, "-netcoop_hitch_trace") != nullptr;
	SampleProfile profile;
	for (;;)
	{
		Sleep(10);
		const u32 frame = Device.dwFrame;
		const u32 now = GetTickCount();
		if (InterlockedCompareExchange(&wd_quiescent, 0, 0))
		{
			last_frame = frame; since = now;
			continue; // Unloading objects is not a gameplay frame.
		}
		if (sampling && g_pGameLevel) sample_profile_step(profile, now);
		if (frame != last_frame)
		{
			last_frame = frame;
			since = now;
			continue;
		}
		if (hitch_trace && g_pGameLevel && now - since >= 100 && sampled_frame != frame && now >= next_sample)
		{
			sampled_frame = frame;
			next_sample = now + 1000;
			DWORD64 pcs[24];
			const u32 count = sample_main_stack(pcs, 24);
			if (count && Device.dwFrame == frame)
			{
				log_hitch(frame, now - since, pcs, count);
				// The main thread may be waiting for the secondary one.
				const u32 mt_count = sample_stack(::g_mt_thread_handle, pcs, 24);
				if (mt_count) log_hitch(frame, now - since, pcs, mt_count, "hitch-mt");
			}
		}
		if (now - since < 20000 || wd_armed || !g_pGameLevel || wd_frame == frame)
			continue;
		wd_try_arm(frame, since, now, []() -> lua_State* { return ai().script_engine().lua(); });
	}
}
} // namespace

void script_watchdog_level_begin()
{
	if (enabled()) wd_resume();
}

void script_watchdog_level_end()
{
	if (enabled()) wd_pause([]() -> lua_State* { return ai().script_engine().lua(); });
}

void script_watchdog_start()
{
	static bool started = false;
	if (started || !enabled())
		return;
	started = true;
	DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &wd_main_thread,
	                THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, 0);
	HANDLE h = CreateThread(0, 0, wd_thread, 0, 0, 0);
	if (h)
		CloseHandle(h);
}

} // namespace netcoop
