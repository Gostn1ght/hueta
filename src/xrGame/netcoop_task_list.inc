// Included in netcoop.cpp (namespace netcoop) - task list replication (server and client).
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// task list replication
// ---------------------------------------------------------------------------
static const u32 tasks_update_interval = 500; // ms
static const u32 tasks_packet_budget = 12000;
static xr_map<u32, u32> s_sent_tasks_crc; // client id -> crc of the last list sent
static lua_State* s_task_update_lua = NULL;
static ::luabind::functor<void>* s_task_update_fn = NULL;

static void reset_task_update_functor(lua_State* current_lua)
{
	if (s_task_update_fn)
	{
		if (current_lua && current_lua == s_task_update_lua)
			xr_delete(s_task_update_fn);
		else
		{
			void* raw = s_task_update_fn;
			xr_free(raw);
			s_task_update_fn = NULL;
		}
	}
	s_task_update_lua = NULL;
}

void lua_functors_reset()
{
	lua_State* current_lua = g_ai_space ? ai().script_engine().lua() : NULL;
	reset_bind_actor_functor(current_lua);
	reset_task_update_functor(current_lua);
}


struct TaskPlayer
{
	ClientID client;
	u16 actor;
};

struct CollectTaskPlayers
{
	xr_vector<TaskPlayer>* players;
	void operator()(IClient* client) const
	{
		xrClientData* CL = static_cast<xrClientData*>(client);
		if (!CL || CL->flags.bLocal || CL->netcoop_role == role_none || !CL->owner)
			return;
		if (s_character_restore.find(CL->owner->ID) != s_character_restore.end()) return;
		if (!smart_cast<CSE_ALifeCreatureActor*>(CL->owner))
			return;
		TaskPlayer p;
		p.client = CL->ID;
		p.actor = CL->owner->ID;
		players->push_back(p);
	}
};

static void write_tasks(CGameTaskManager* manager, NET_Packet& P)
{
	P.w_begin(M_NETCOOP_TASKS);
	const u32 count_pos = P.w_tell();
	P.w_u16(0);
	u16 count = 0;
	vGameTasks& tasks = manager->GetGameTasks();
	// Tasks in progress first, then finished ones while they fit.
	for (int pass = 0; pass < 2; ++pass)
	{
		for (u32 i = 0; i < tasks.size(); ++i)
		{
			CGameTask* t = tasks[i].game_task;
			if (!t || (t->GetTaskState() == eTaskStateInProgress) != (pass == 0))
				continue;
			CMemoryWriter w;
			t->save_task(w);
			const u32 size = tasks[i].task_id.size() + 1 + 2 + w.size();
			if (w.size() > 0xffff || P.w_tell() + size > tasks_packet_budget)
				continue;
			P.w_stringZ(tasks[i].task_id.c_str());
			P.w_u16(u16(w.size()));
			P.w(w.pointer(), w.size());
			++count;
		}
	}
	P.w_seek(count_pos, &count, sizeof(count));
}

// Where a task's target is now (owner 2026-10-06): an item a player picked
// up is where that player is, an item put into a stash is at the stash. The
// owner of the task gets the positions of targets that are not on their
// client (far, offline); the client shows the task spot there and it moves
// with the holder. Every 2 s, only when something moved.
static bool world_object_position(xrServer* server, u16 id, Fvector& position, shared_str& level)
{
	if (id == 0xffff) return false;
	CSE_Abstract* entity = server->ID_to_entity(id);
	for (int depth = 0; entity && entity->ID_Parent != 0xffff && depth < 4; ++depth)
	{
		CSE_Abstract* parent = server->ID_to_entity(entity->ID_Parent);
		if (!parent) break;
		entity = parent;
	}
	if (entity && entity->ID_Parent == 0xffff)
	{
		position = entity->o_Position;
		level = Level().name();
		return true;
	}
	if (!ai().get_alife()) return false;
	CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
	for (int depth = 0; object && object->ID_Parent != 0xffff && depth < 4; ++depth)
		object = ai().alife().objects().object(object->ID_Parent, true);
	if (!object || !ai().get_game_graph() || !ai().game_graph().valid_vertex_id(object->m_tGraphID)) return false;
	position = object->o_Position;
	level = ai().game_graph().header().level(ai().game_graph().vertex(object->m_tGraphID)->level_id()).name();
	return true;
}

static xr_map<u16, xr_string> s_sent_task_positions; // Actor id -> last "taskpos" data
static u32 s_task_positions_next = 0;

static void send_task_positions(xrServer* server, u16 actor_id, CGameTaskManager* manager)
{
	string4096 data = "";
	vGameTasks& tasks = manager->GetGameTasks();
	for (u32 i = 0; i < tasks.size(); ++i)
	{
		CGameTask* t = tasks[i].game_task;
		if (!t || t->GetTaskState() != eTaskStateInProgress) continue;
		Fvector position;
		shared_str level;
		if (!world_object_position(server, t->m_map_object_id, position, level)) continue;
		string256 entry;
		xr_sprintf(entry, "%u %.1f %.1f %.1f %s;", t->m_map_object_id, position.x, position.y, position.z, level.c_str());
		if (xr_strlen(data) + xr_strlen(entry) >= sizeof(data) - 1) break;
		xr_strcat(data, entry);
	}
	xr_string& sent = s_sent_task_positions[actor_id];
	if (sent == data) return;
	sent = data;
	script_send_to_actor(actor_id, "taskpos", data);
}

void server_tasks_update(xrServer* server)
{
	if (!enabled() || !g_pGameLevel || !Level().Server)
		return;
	static u32 next_update = 0;
	const u32 now = Device.dwTimeGlobal;
	if (now < next_update)
		return;
	next_update = now + tasks_update_interval;

	// Managers of Actors that no longer exist (death, disconnect).
	xr_vector<u16> gone;
	for (TaskManagers::iterator it = s_task_managers.begin(); it != s_task_managers.end(); ++it)
		if (!smart_cast<CActor*>(Level().Objects.net_Find(it->first)))
			gone.push_back(it->first);
	for (u32 i = 0; i < gone.size(); ++i)
	{
		server_release_task_manager(gone[i]);
		s_sent_task_positions.erase(gone[i]);
	}

	xr_vector<TaskPlayer> players;
	CollectTaskPlayers collect;
	collect.players = &players;
	server->ForEachClientDo(collect);

	lua_State* lua = ai().script_engine().lua();
	if (!lua)
	{
		reset_task_update_functor(NULL);
	}
	else if (s_task_update_lua != lua)
	{
		reset_task_update_functor(NULL);
		s_task_update_lua = lua;
		::luabind::functor<void> resolved;
		if (ai().script_engine().functor("netcoop_server_compat.update_player_tasks", resolved))
			s_task_update_fn = xr_new<::luabind::functor<void>>(resolved);
	}

	for (u32 i = 0; i < players.size(); ++i)
	{
		CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(players[i].actor));
		if (!actor || actor->getDestroy())
			continue;

		bind_script_actor(actor);
		CGameTaskManager* manager = Level().GameTaskManagerPtr();
		if (manager)
		{
			manager->UpdateTasks();
			if (s_task_update_fn)
			{
				try
				{
					(*s_task_update_fn)();
				}
				catch (...)
				{
					Msg("! [Lost Zone] task update script failed for Actor %u", players[i].actor);
				}
			}
		}
		manager = Level().GameTaskManagerPtr();
		NET_Packet P;
		if (manager)
			write_tasks(manager, P);
		if (manager && now >= s_task_positions_next)
			send_task_positions(server, players[i].actor, manager);
		bind_script_actor(NULL);
		if (!manager)
			continue;

		const u32 crc = crc32(P.B.data, P.B.count);
		u32& sent = s_sent_tasks_crc[players[i].client.value()];
		if (sent == crc)
			continue;
		sent = crc;
		server->SendTo(players[i].client, P, net_flags(TRUE, TRUE));
	}
	if (now >= s_task_positions_next) s_task_positions_next = now + 2000;
}
