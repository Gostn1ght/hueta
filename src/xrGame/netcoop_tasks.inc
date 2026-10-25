// Included in netcoop.cpp (namespace netcoop) - server: per-player tasks.
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// server: per-player tasks
// ---------------------------------------------------------------------------
// The engine keeps one task list per level. A netcoop server keeps one per
// player Actor (stored in the ALife registry under that Actor's id) and makes
// it the level's list while that player is served.
typedef xr_map<u16, CGameTaskManager*> TaskManagers;
static TaskManagers s_task_managers;

static CGameTaskManager* server_task_manager(u16 actor_id)
{
	TaskManagers::iterator it = s_task_managers.find(actor_id);
	if (it != s_task_managers.end())
		return it->second;
	CGameTaskManager* manager = xr_new<CGameTaskManager>(actor_id);
	s_task_managers.insert(std::make_pair(actor_id, manager));
	return manager;
}

static void clear_tasks(CGameTaskManager* manager)
{
	// Removing a task's map spot searches the level's task list for the
	// spot's task; with the list still in place it met the tasks destroyed
	// before (client crash in release_task_location, owner 2026-10-18).
	vGameTasks tasks;
	tasks.swap(manager->GetGameTasks());
	for (u32 i = 0; i < tasks.size(); ++i)
	{
		if (tasks[i].game_task)
			tasks[i].game_task->RemoveMapLocations(false);
		tasks[i].destroy();
	}
	tasks.clear();
	manager->MarkChanged();
}

static void server_release_task_manager(u16 actor_id)
{
	TaskManagers::iterator it = s_task_managers.find(actor_id);
	if (it == s_task_managers.end())
		return;
	CGameTaskManager* manager = it->second;
	s_task_managers.erase(it);
	if (g_pGameLevel && Level().GameTaskManagerPtr() == manager)
		Level().SetGameTaskManager(NULL);
	clear_tasks(manager);
	xr_delete(manager);
}

// True when a player other than actor_id has this task in progress.
bool server_task_taken_by_other(u16 actor_id, LPCSTR task_id)
{
	if (!task_id || !task_id[0])
		return false;
	const shared_str id = task_id;
	// Only another character's live Actor counts: a corpse left by a respawn
	// still held its tasks and refused them to its own new body.
	const auto own = s_actor_character.find(actor_id);
	for (TaskManagers::iterator it = s_task_managers.begin(); it != s_task_managers.end(); ++it)
	{
		if (it->first == actor_id || !it->second->HasGameTask(id, true))
			continue;
		const auto other = s_actor_character.find(it->first);
		if (other == s_actor_character.end() || (own != s_actor_character.end() && own->second == other->second))
			continue;
		return true;
	}
	return false;
}

// Server scripts use db.actor and the engine uses Actor() and the level task
// list; while one player is served all three refer to that player.
static bool s_actor_bound = false;
static CActor* s_bound_previous_actor = NULL;
static CGameTaskManager* s_bound_previous_tasks = NULL;

static void bind_engine_actor(CActor* actor)
{
	if (!g_pGameLevel || !Level().Server)
		return;
	if (actor)
	{
		if (!s_actor_bound)
		{
			s_actor_bound = true;
			s_bound_previous_actor = g_actor;
			s_bound_previous_tasks = Level().GameTaskManagerPtr();
		}
		g_actor = actor;
		Level().SetGameTaskManager(server_task_manager(actor->ID()));
	}
	else if (s_actor_bound)
	{
		s_actor_bound = false;
		g_actor = s_bound_previous_actor;
		Level().SetGameTaskManager(s_bound_previous_tasks);
		s_bound_previous_actor = NULL;
		s_bound_previous_tasks = NULL;
	}
}

// GAMMA dialogue scripts use db.actor; point it at the player being served.
static CActor* s_bound_actor = NULL;
static lua_State* s_bind_actor_lua = NULL;
static ::luabind::functor<void>* s_bind_actor_fn = NULL;

static void reset_bind_actor_functor(lua_State* current_lua)
{
	if (s_bind_actor_fn)
	{
		if (current_lua && current_lua == s_bind_actor_lua)
			xr_delete(s_bind_actor_fn);
		else
		{
			void* raw = s_bind_actor_fn;
			xr_free(raw);
			s_bind_actor_fn = NULL;
		}
	}
	s_bind_actor_lua = NULL;
}

static void bind_script_actor(CActor* actor)
{
	s_bound_actor = actor;
	bind_engine_actor(actor);
	// Called for every server-side object script update; resolve once per Lua state.
	lua_State* lua = ai().script_engine().lua();
	if (!lua)
	{
		reset_bind_actor_functor(NULL);
		return;
	}
	if (s_bind_actor_lua != lua)
	{
		reset_bind_actor_functor(NULL);
		s_bind_actor_lua = lua;
		::luabind::functor<void> resolved;
		if (ai().script_engine().functor("netcoop_server_compat.bind_actor", resolved))
			s_bind_actor_fn = xr_new<::luabind::functor<void>>(resolved);
	}
	if (!s_bind_actor_fn)
		return;
	try
	{
		if (actor)
			(*s_bind_actor_fn)(actor->lua_game_object());
		else
			(*s_bind_actor_fn)();
	}
	catch (...)
	{
		Msg("! [Lost Zone] netcoop_server_compat.bind_actor failed");
	}
}

static void talk_say(TalkSession& session, CPhraseDialogManager* our, const shared_str& phrase_id)
{
	capture_line(false, session.current->GetPhraseText(phrase_id));
	our->SayPhrase(session.current, phrase_id);
	if (session.current && session.current->IsFinished())
		session.current = DIALOG_SHARED_PTR((CPhraseDialog*)NULL);
}

// Mirrors CUITalkWnd::UpdateQuestions for a server-side dialogue run.
static void talk_build_choices(TalkSession& session, CPhraseDialogManager* our, CPhraseDialogManager* other,
                               TalkState& state)
{
	for (u32 guard = 0; guard < 16; ++guard)
	{
		state.choices.clear();
		if (!session.current)
		{
			our->UpdateAvailableDialogs(other);
			const CPhraseDialogManager::DIALOG_VECTOR& dialogs = our->AvailableDialogs();
			for (u32 i = 0; i < dialogs.size() && state.choices.size() < talk_max_entries; ++i)
			{
				TalkChoice choice;
				choice.id = dialogs[i]->GetDialogID();
				choice.text = dialogs[i]->DialogCaption();
				choice.finalizer = dialogs[i]->GetPhrase("0")->IsFinalizer();
				state.choices.push_back(choice);
			}
			return;
		}

		if (!session.current->IsWeSpeaking(our))
			return;

		const PHRASE_VECTOR& phrases = session.current->PhraseList();
		if (!phrases.empty() && session.current->allIsDummy())
		{
			// Only placeholder phrases: say one and continue, as the UI does.
			CPhrase* phrase = phrases[Random.randI(phrases.size())];
			talk_say(session, our, phrase->GetID());
			continue;
		}

		for (u32 i = 0; i < phrases.size() && state.choices.size() < talk_max_entries; ++i)
		{
			TalkChoice choice;
			choice.id = phrases[i]->GetID();
			choice.text = session.current->GetPhraseText(choice.id);
			choice.finalizer = phrases[i]->IsFinalizer();
			state.choices.push_back(choice);
		}
		return;
	}
}

static void send_talk_state(xrServer* server, xrClientData* CL, const TalkState& state)
{
	// Keep the packet well inside the transport size limit.
	u32 budget = 12000;
	xr_vector<const TalkLine*> lines;
	for (u32 i = 0; i < state.lines.size(); ++i)
	{
		const u32 size = state.lines[i].text.size() + 8;
		if (state.lines[i].text.size() < talk_max_text && budget > size)
		{
			budget -= size;
			lines.push_back(&state.lines[i]);
		}
	}
	xr_vector<const TalkChoice*> choices;
	for (u32 i = 0; i < state.choices.size(); ++i)
	{
		const TalkChoice& c = state.choices[i];
		const u32 size = c.id.size() + c.text.size() + 8;
		if (c.id.size() < 256 && c.text.size() < talk_max_text && budget > size)
		{
			budget -= size;
			choices.push_back(&c);
		}
	}

	NET_Packet P;
	P.w_begin(M_NETCOOP_TALK_STATE);
	P.w_u16(state.npc);
	P.w_u8(u8((state.open ? talk_flag_open : 0) | (state.trade ? talk_flag_trade : 0)));
	P.w_u16((u16)lines.size());
	for (u32 i = 0; i < lines.size(); ++i)
	{
		P.w_u8(lines[i]->npc ? 1 : 0);
		P.w_stringZ(lines[i]->text.c_str());
	}
	P.w_u16((u16)choices.size());
	for (u32 i = 0; i < choices.size(); ++i)
	{
		P.w_stringZ(choices[i]->id.c_str());
		P.w_stringZ(choices[i]->text.c_str());
		P.w_u8(choices[i]->finalizer ? 1 : 0);
	}
	server->SendTo(CL->ID, P, net_flags(TRUE, TRUE));
}

static void talk_close(xrClientData* CL, CActor* actor, CInventoryOwner* npc)
{
	s_talk_sessions.erase(CL->ID.value());
	if (actor && actor->IsTalking())
		actor->StopTalk();
	if (npc && npc->IsTalking())
		npc->StopTalk();
}

// The NPC a player talks with, for GAMMA's get_speaker (used_npc_id): its
// dialogues and task offers looked for the talk window's partner, a server
// has none, and the fetch task offer took the server down (owner 2026-10-18,
// tasks_fetch.script:567 "table index is nil").
static void talk_speaker(u16 npc_id)
{
	::luabind::functor<void> f;
	if (!ai().script_engine().functor("netcoop_server_compat.talk_speaker", f)) return;
	try { f(int(npc_id)); }
	catch (...) { Msg("! [Lost Zone] netcoop_server_compat.talk_speaker failed"); }
}

static void server_on_talk_dialogue(xrServer* server, xrClientData* CL, NET_Packet& P);

void server_on_talk(xrServer* server, xrClientData* CL, NET_Packet& P)
{
	// A dialogue or task script error must not take the server down: the
	// conversation ends and the error is logged.
	try { server_on_talk_dialogue(server, CL, P); }
	catch (...)
	{
		Msg("! [Lost Zone] dialogue script error for '%s': the conversation is closed", CL ? CL->netcoop_login.c_str() : "?");
		s_talk_capture = NULL;
		talk_speaker(0xffff);
		bind_script_actor(NULL);
		if (CL && CL->owner)
			if (CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(CL->owner->ID)))
			{
				TalkSessions::iterator found = s_talk_sessions.find(CL->ID.value());
				CInventoryOwner* npc = found != s_talk_sessions.end() ?
					smart_cast<CInventoryOwner*>(Level().Objects.net_Find(found->second.npc)) : nullptr;
				TalkState state;
				state.npc = found != s_talk_sessions.end() ? found->second.npc : u16(0xffff);
				talk_close(CL, actor, npc);
				state.open = false;
				state.trade = false;
				send_talk_state(server, CL, state);
			}
	}
}

static void server_on_talk_dialogue(xrServer* server, xrClientData* CL, NET_Packet& P)
{
	if (!enabled() || !CL || !CL->owner || !g_pGameLevel || P.r_elapsed() < 1)
		return;

	CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(CL->owner->ID));
	if (!actor)
		return;

	const u8 op = P.r_u8();
	TalkSessions::iterator found = s_talk_sessions.find(CL->ID.value());

	u16 npc_id = found != s_talk_sessions.end() ? found->second.npc : u16(0xffff);
	if (op == talk_start)
	{
		if (P.r_elapsed() < 2)
			return;
		npc_id = P.r_u16();
	}

	CObject* npc_object = npc_id != 0xffff ? Level().Objects.net_Find(npc_id) : NULL;
	CInventoryOwner* npc = smart_cast<CInventoryOwner*>(npc_object);
	CEntityAlive* npc_alive = smart_cast<CEntityAlive*>(npc_object);
	CPhraseDialogManager* our = smart_cast<CPhraseDialogManager*>(actor);
	CPhraseDialogManager* other = smart_cast<CPhraseDialogManager*>(npc_object);

	if (op == talk_stop)
	{
		talk_close(CL, actor, npc);
		return;
	}

	TalkState state;
	state.npc = npc_id;
	state.open = false;
	state.trade = false;

	const bool valid = npc && npc_alive && npc_alive->g_Alive() && actor->g_Alive() && our && other &&
		!smart_cast<CActor*>(npc_object) &&
		actor->Position().distance_to(npc_object->Position()) <= talk_max_distance;
	if (!valid || (op == talk_choose && found == s_talk_sessions.end()) || op > talk_stop)
	{
		Msg("! [Lost Zone] talk op %u with %u from '%s' rejected: npc=%d alive=%d distance=%.1f session=%d",
			op, npc_id, CL->netcoop_login.c_str(), npc ? 1 : 0, npc_alive && npc_alive->g_Alive() ? 1 : 0,
			npc_object ? actor->Position().distance_to(npc_object->Position()) : -1.f,
			found != s_talk_sessions.end() ? 1 : 0);
		talk_close(CL, actor, npc);
		send_talk_state(server, CL, state);
		return;
	}

	s_talk_capture = &state;
	bind_script_actor(actor);
	talk_speaker(npc_id);

	if (op == talk_start)
	{
		if (actor->IsTalking())
			actor->StopTalk();
		prepare_trade(npc_id);
		s_talk_sessions.erase(CL->ID.value());

		const bool offered = npc->OfferTalk(actor);
		Msg("[Lost Zone] talk '%s' -> %s: offer=%d talk_enabled=%d", CL->netcoop_login.c_str(),
			npc_object->cName().c_str(), offered ? 1 : 0, npc->IsTalkEnabled() ? 1 : 0);
		if (offered)
		{
			actor->StartTalk(npc);

			TalkSession& session = s_talk_sessions[CL->ID.value()];
			session.npc = npc_id;
			session.current = DIALOG_SHARED_PTR((CPhraseDialog*)NULL);

			// Mirrors CUITalkWnd::InitOthersStartDialog.
			other->UpdateAvailableDialogs(our);
			if (!other->AvailableDialogs().empty())
			{
				session.current = other->AvailableDialogs().front();
				other->InitDialog(our, session.current);
				capture_line(true, session.current->GetPhraseText("0"));
				other->SayPhrase(session.current, "0");
				if (!session.current || session.current->IsFinished())
					session.current = DIALOG_SHARED_PTR((CPhraseDialog*)NULL);
			}
			talk_build_choices(session, our, other, state);
		}
	}
	else
	{
		char id[256];
		TalkSession& session = found->second;
		bool accepted = false;
		if (read_string(P, id, sizeof(id)))
		{
			if (!session.current)
			{
				if (our->HaveAvailableDialog(id))
				{
					session.current = our->GetDialogByID(id);
					our->InitDialog(other, session.current);
					talk_say(session, our, "0");
					accepted = true;
				}
			}
			else if (session.current->IsWeSpeaking(our))
			{
				const shared_str wanted = id;
				const PHRASE_VECTOR& phrases = session.current->PhraseList();
				for (u32 i = 0; i < phrases.size(); ++i)
				{
					if (phrases[i]->GetID() == wanted)
					{
						const shared_str phrase_id = phrases[i]->GetID();
						talk_say(session, our, phrase_id);
						accepted = true;
						break;
					}
				}
			}
		}
		if (!accepted)
			Msg("! [Lost Zone] rejected dialogue choice from '%s'", CL->netcoop_login.c_str());
		talk_build_choices(session, our, other, state);
	}

	talk_speaker(0xffff);
	bind_script_actor(NULL);
	s_talk_capture = NULL;

	// A dialogue script may have ended the conversation (break_dialog).
	state.open = actor->IsTalking() && npc->IsTalking();
	state.trade = actor->IsTradeEnabled() && npc->IsTradeEnabled();
	if (!state.open)
		talk_close(CL, actor, npc);
	send_talk_state(server, CL, state);
}

// Drops sessions of connections that no longer exist (main thread).
void server_talk_prune(xrServer* server)
{
	for (auto it = s_dialog_trade.begin(); it != s_dialog_trade.end();)
	{
		CObject* actor = Level().Objects.net_Find(it->first);
		if (!actor || actor->getDestroy() || Device.dwTimeGlobal - it->second.since >= 30 * 60 * 1000)
			it = s_dialog_trade.erase(it);
		else ++it;
	}
	for (TalkSessions::iterator it = s_talk_sessions.begin(); it != s_talk_sessions.end();)
	{
		ClientID id;
		id.set(it->first);
		if (!server->ID_to_client(id))
			it = s_talk_sessions.erase(it);
		else
			++it;
	}
}
} // namespace netcoop

namespace netcoop
{
bool client_owns_hud_item(const CObject* item)
{
	if (!item || !pure_client())
		return false;
	const CObject* parent = item->H_Parent();
	return parent && parent == Level().CurrentControlEntity();
}
} // namespace netcoop

namespace netcoop
{
static int s_nearest_bind_depth = 0;

bool server_bind_nearest_actor(CObject* npc)
{
	if (s_nearest_bind_depth > 0)
	{
		++s_nearest_bind_depth;
		return true;
	}
	if (!npc || !g_pGameLevel)
		return false;
	const u16 id = netcoop_nearest_player_actor(npc->Position());
	CActor* actor = id != 0xffff ? smart_cast<CActor*>(Level().Objects.net_Find(id)) : NULL;
	if (!actor || actor->getDestroy())
		return false;
	bind_script_actor(actor);
	s_nearest_bind_depth = 1;
	return true;
}

void server_unbind_actor()
{
	if (s_nearest_bind_depth <= 0)
		return;
	if (--s_nearest_bind_depth == 0)
		bind_script_actor(NULL);
}

ServerActorScope::ServerActorScope(CObject* object) : bound(false)
{
	if (enabled() && g_pGameLevel && Level().Server && object && !smart_cast<CActor*>(object))
		bound = server_bind_nearest_actor(object);
}

ServerActorScope::~ServerActorScope()
{
	if (bound)
		server_unbind_actor();
}

ServerVictimScope::ServerVictimScope(CActor* victim) : active(false), previous(NULL)
{
	if (!server_player_copy(victim))
		return;
	active = true;
	previous = s_bound_actor;
	bind_script_actor(victim);
}

ServerVictimScope::~ServerVictimScope()
{
	if (active)
		bind_script_actor(previous);
}

static const u32 task_origin_marker = 0x524f434e; // "NCOR"

static bool character_capture_progress(Character& character, CActor* actor)
{
	ServerVictimScope scope(actor);
	CMemoryWriter writer;
	vGameTasks& tasks = server_task_manager(actor->ID())->GetGameTasks();
	if (tasks.size() > 512) { Msg("! [Lost Zone] character task count exceeds restore limit for %u", actor->ID()); return false; }
	writer.w_u32(u32(tasks.size()));
	for (SGameTaskKey& task : tasks)
	{
		task.save(writer);
		if (writer.size() > 1048576) return false;
	}
	save_data(actor->m_known_info_registry->registry().objects(), writer);
	if (writer.size() > 1048576) return false;
	::luabind::functor<luabind::internal_string> capture;
	if (!ai().script_engine().functor("netcoop_server_compat.capture_character_state", capture))
	{
		Msg("! [Lost Zone] character script capture is unavailable for %u", actor->ID());
		return false;
	}
	luabind::internal_string state;
	try { state = capture(actor->lua_game_object()); }
	catch (...) { Msg("! [Lost Zone] cannot serialize character script state for %u", actor->ID()); return false; }
	if (state.size() > 1048576 || writer.size() + 4 + state.size() > 1048576) return false;
	writer.w_u32(u32(state.size()));
	if (!state.empty()) writer.w(state.data(), state.size());
	// Map that gave each task (netcoop_cluster.inc, server_task_here).
	writer.w_u32(task_origin_marker);
	writer.w_u32(u32(tasks.size()));
	for (SGameTaskKey& task : tasks)
	{
		if (task.game_task && !task.game_task->m_netcoop_origin.size()) task.game_task->m_netcoop_origin = cluster_current_level();
		writer.w_stringZ(task.task_id);
		writer.w_stringZ(task.game_task ? task.game_task->m_netcoop_origin : shared_str(""));
		if (writer.size() > 1048576) return false;
	}
	if (writer.size() > 1048576) { Msg("! [Lost Zone] character progress exceeds save limit for %u", actor->ID()); return false; }
	const u8* data = static_cast<const u8*>(writer.pointer());
	character.progress.assign(data, data + writer.size());
	return true;
}

static bool character_restore_progress(Character& character, CActor* actor)
{
	if (character.progress.empty()) return true;
	if (character.progress.size() < 4 || character.progress.size() > 1048576) return false;
	ServerVictimScope scope(actor);
	::luabind::functor<void> restore;
	if (!ai().script_engine().functor("netcoop_server_compat.restore_character_state", restore)) return false;
	IReader reader(character.progress.data(), character.progress.size());
	const u32 count = reader.r_u32();
	if (count > 512) return false;
	if (reader.elapsed() < 8) return false;
	CGameTaskManager* manager = server_task_manager(actor->ID());
	clear_tasks(manager);
	vGameTasks& tasks = manager->GetGameTasks();
	for (u32 i = 0; i < count; ++i) { SGameTaskKey task; task.load(reader); tasks.push_back(task); }
	if (reader.elapsed() < 8) return false;
	load_data(actor->m_known_info_registry->registry().objects(), reader);
	if (reader.elapsed() < 4) return false;
	const u32 size = reader.r_u32();
	if (size > reader.elapsed()) return false;
	luabind::internal_string state(reinterpret_cast<const char*>(reader.pointer()), size);
	reader.advance(size);
	if (reader.elapsed())
	{
		if (reader.elapsed() < 8 || reader.r_u32() != task_origin_marker) return false;
		const u32 origins = reader.r_u32();
		if (origins != count) return false;
		for (u32 i = 0; i < origins; ++i)
		{
			shared_str id, origin;
			if (!memchr(reader.pointer(), 0, reader.elapsed())) return false;
			reader.r_stringZ(id);
			if (!memchr(reader.pointer(), 0, reader.elapsed())) return false;
			reader.r_stringZ(origin);
			for (SGameTaskKey& task : tasks)
				if (task.task_id == id && task.game_task) task.game_task->m_netcoop_origin = origin;
		}
		if (reader.elapsed()) return false;
	}
	try { restore(actor->lua_game_object(), state, character.respawn); }
	catch (...) { Msg("! [Lost Zone] cannot restore character script state for %u", actor->ID()); return false; }
	manager->MarkChanged();
	return true;
}
