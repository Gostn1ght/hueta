// xrServer.cpp: implementation of the xrServer class.
//
//////////////////////////////////////////////////////////////////////

#include "pch_script.h"
#include "netcoop.h"
#include "xrServer.h"
#include "netcoop_simulation_lod.h"
#include "netcoop_replication_index.h"
#include "actor_defs.h"
#include "actor.h"
#include "Inventory.h"
#include "inventory_item.h"

#include "xrMessages.h"
#include "xrServer_Objects_ALife_All.h"
#include "level.h"
#include "game_cl_base.h"
#include "ai_space.h"
#include "script_engine.h"
#include "../xrEngine/IGame_Persistent.h"
#include "../xrEngine/Stats.h"
#include "string_table.h"
#include "object_broker.h"

#include "../xrEngine/XR_IOConsole.h"
#include "ui/UIInventoryUtilities.h"
#include <functional>
#include <chrono>
#include "../xrNetServer/GammaNetPolicy.h"

#pragma warning(push)
#pragma warning(disable:4995)
#include <malloc.h>
#pragma warning(pop)

u32 g_sv_traffic_optimization_level = eto_none;

// Keep template-rich diagnostics private to this translation unit. Putting
// them in xrServer.h duplicates optimizer/debug metadata across the huge
// static xrGame archive and can exceed the COFF library size limit.
struct NetcoopChunkShadow
{
	netcoop_world::SpatialGrid grid{100};
	netcoop_world::SimulationLodPlanner lod;
	struct Observer { netcoop_world::SpatialPoint position; u64 real_ms = 0; };
	std::map<u16,Observer> observers;
};

xrClientData::xrClientData() :
	IClient(Device.GetTimerGlobal())
{
	ps = NULL;
	Clear();
}

void xrClientData::Clear()
{
	owner = NULL;
	ClearInputState();
	net_Ready = FALSE;
	net_Accepted = FALSE;
	net_ConnectionDataRequested = FALSE;
	netcoop_login = NULL;
	netcoop_role = 0;
	netcoop_admin_god = false;
	netcoop_character_slot = 1;
	netcoop_character_name = NULL;
	gamma_snapshot_ready = false;
	net_PassUpdates = TRUE;
	m_ping_warn.m_maxPingWarnings = 0;
	m_ping_warn.m_dwLastMaxPingWarningTime = 0;
};

void xrClientData::ClearInputState()
{
	m_pending_inputs.clear();
	m_last_received_sequence = 0;
	m_last_processed_sequence = 0;
	m_has_processed_input = false;
	m_pending_jump_edge = false;
	m_current_intent = {};
	m_last_input_receive_time = 0;
};


xrClientData::~xrClientData()
{
	xr_delete(ps);
}


xrServer::xrServer() : IPureServer(Device.GetTimerGlobal(), g_dedicated_server)
{
	m_aDelayedPackets.clear();
	m_netcoop_main_thread = GetCurrentThreadId();
	m_last_updates_size = 0;
	m_last_update_time = 0;
}

xrServer::~xrServer()
{
	netcoop::server_admission_stop();
	netcoop::server_world_bridge_stop();
	struct ClientDestroyer
	{
		static bool true_generator(IClient*)
		{
			return true;
		}
	};
	IClient* tmp_client = net_players.GetFoundClient(&ClientDestroyer::true_generator);
	while (tmp_client)
	{
		client_Destroy(tmp_client);
		tmp_client = net_players.GetFoundClient(&ClientDestroyer::true_generator);
	}
	m_aDelayedPackets.clear();
	entities.clear();
}

//--------------------------------------------------------------------

CSE_Abstract* xrServer::ID_to_entity(u16 ID)
{
	// #pragma todo("??? to all : ID_to_entity - must be replaced to 'game->entity_from_eid()'")	
	if (0xffff == ID) return 0;
	xrS_entities::iterator I = entities.find(ID);
	if (entities.end() != I) return I->second;
	else return 0;
}

//--------------------------------------------------------------------
IClient* xrServer::client_Create()
{
	return xr_new<xrClientData>();
}

void xrServer::client_Replicate()
{
}

IClient* xrServer::client_Find_Get(ClientID ID)
{
	DWORD dwPort = 0;
	ip_address tmp_ip_address;


	if (!psNET_direct_connect)
		GetClientAddress(ID, tmp_ip_address, &dwPort);
	else
		tmp_ip_address.set("127.0.0.1");

	IClient* newCL = client_Create();
	newCL->ID = ID;
	if (!psNET_direct_connect)
	{
		newCL->m_cAddress = tmp_ip_address;
		newCL->m_dwPort = dwPort;
	}

	newCL->server = this;
	net_players.AddNewClient(newCL);

#ifndef MASTER_GOLD
	Msg		("# New player created.");
#endif // #ifndef MASTER_GOLD
	return newCL;
};

u32 g_sv_Client_Reconnect_Time = 3;

void xrServer::client_Destroy(IClient* C)
{
	xrClientData* CL = (xrClientData*)C;
	CL->ClearInputState(); // Disconnect cleanup
	// Delete assosiated entity
	// xrClientData*	D = (xrClientData*)C;
	// CSE_Abstract* E = D->owner;
	IClient* alife_client = net_players.FindAndEraseClient(
		[C](IClient* client) { return client == C; }
	);
	//VERIFY(alife_client);
	if (alife_client)
	{
		CSE_Abstract* pOwner = static_cast<xrClientData*>(alife_client)->owner;
		CSE_Spectator* pS = smart_cast<CSE_Spectator*>(pOwner);
		if (pS)
		{
			NET_Packet P;
			P.w_begin(M_EVENT);
			P.w_u32(Level().timeServer()); //Device.TimerAsync());
			P.w_u16(GE_DESTROY);
			P.w_u16(pS->ID);
			SendBroadcast(C->ID, P, net_flags(TRUE,TRUE));
		};

		DelayedPacket pp;
		pp.SenderID = alife_client->ID;
		xr_deque<DelayedPacket>::iterator it;
		do
		{
			it = std::find(m_aDelayedPackets.begin(), m_aDelayedPackets.end(), pp);
			if (it != m_aDelayedPackets.end())
			{
				m_aDelayedPackets.erase(it);
				Msg("removing packet from delayed event storage");
			}
			else
				break;
		}
		while (true);

		if (pOwner)
		{
			game->CleanDelayedEventFor(pOwner->ID);
		}

		//.		if (!alife_client->flags.bVerified)
		xrClientData* xr_client = static_cast<xrClientData*>(alife_client);
		m_disconnected_clients.Add(xr_client); //xr_delete(alife_client);				
	}
}

void xrServer::GetPooledState(xrClientData* xrCL)
{
	xrClientData* pooled_client = m_disconnected_clients.Get(xrCL);
	if (!pooled_client)
		return;

	NET_Packet tmp_packet;
	u16 tmp_fake;
	tmp_packet.w_begin(M_SPAWN);
	pooled_client->ps->net_Export(tmp_packet, TRUE);
	tmp_packet.r_begin(tmp_fake);
	xrCL->ps->net_Import(tmp_packet);
	xrCL->flags.bReconnect = TRUE;
	xr_delete(pooled_client);
}

//--------------------------------------------------------------------
int g_Dump_Update_Write = 0;

#ifdef DEBUG
INT g_sv_SendUpdate = 0;
#endif

void netcoop_join_pump(xrServer* server); // xrServer_CL_connect.cpp

void xrServer::Update()
{
	NET_Packet Packet;
#ifdef DEBUG
	VERIFY(verify_entities());
#endif
	netcoop_process_packets();
	netcoop::server_auth_update(this);
	netcoop_join_pump(this);
	ProceedDelayedPackets();
	// game update
	game->ProcessDelayedEvent();
	game->Update();
	netcoop::server_tasks_update(this);

	// spawn queue
	u32 svT = Device.TimerAsync();
	while (!(q_respawn.empty() || (svT < q_respawn.begin()->timestamp)))
	{
		// get
		svs_respawn R = *q_respawn.begin();
		q_respawn.erase(q_respawn.begin());

		// 
		CSE_Abstract* E = ID_to_entity(R.phantom);
		if (!E)
			continue;
		E->Spawn_Write(Packet,FALSE);
		u16 ID;
		Packet.r_begin(ID);
		R_ASSERT(M_SPAWN==ID);
		ClientID clientID;
		clientID.set(SV_Client ? SV_Client->ID.value() : 0xffff);
		Process_spawn(Packet, clientID);
	}


	{
		netcoop::ProfileScope profile(netcoop::prof_replication);
		SendUpdatesToAll();
	}
	{
		netcoop::ProfileScope profile(netcoop::prof_items);
		netcoop::server_items_update(this);
		netcoop::server_frame_update(this);
	}


	if (game->sv_force_sync) Perform_game_export();
#ifdef DEBUG
	VERIFY(verify_entities());
#endif
	//-----------------------------------------------------

	PerformCheckClientsForMaxPing();
	Flush_Clients_Buffers();

	if (0 == (Device.dwFrame % 100)) //once per 100 frames
	{
		UpdateBannedList();
		netcoop::server_update(this);

		// NetAnomaly: publish the real number of connected clients for the
		// external server console (appdata/netanomaly_console_net.txt).
		// Only when it changes: rewriting the file every 100 frames showed as
		// ~110 ms server frames on those frames (s125 [hitch] log).
		static int na_published = -1;
		if (na_published != (int)GetClientsCount())
		{
			na_published = (int)GetClientsCount();
			string_path na_fn;
			FS.update_path(na_fn, "$app_data_root$", "netanomaly_console_net.txt");
			IWriter* na_w = FS.w_open(na_fn);
			if (na_w)
			{
				string256 na_line;
				xr_sprintf(na_line, sizeof(na_line), "clients=%d", (int)GetClientsCount());
				na_w->w_string(na_line);
				FS.w_close(na_w);
			}
		}
	}
}

void _stdcall xrServer::SendGameUpdateTo(IClient* client)
{
	xrClientData* xr_client = static_cast<xrClientData*>(client);
	VERIFY(xr_client);
	xr_client->gamma_snapshot_ready = false;
	if (!xr_client->net_Ready || !xr_client->ps)
	{
		return;
	}

	// Netcoop: SendUpdatesToAll already runs at the update rate. HasBandwidth
	// has its own 33 ms timer (skipping a tick whenever the two drift apart)
	// and drops the snapshot while more than 3 messages are queued, which a
	// single tick of update packets exceeds.
	const bool has_room = netcoop::smooth() ? !!HasSendQueueRoom(client, 64) : !!HasBandwidth(client);
	if (!has_room && client != GetServerClient())
		netcoop::metric_snapshot_blocked();
	if (!has_room
#ifdef DEBUG
			&& !g_sv_SendUpdate
#endif
	)
	{
		return;
	}

	xr_client->gamma_snapshot_ready = true;
	NET_Packet Packet;
	u16 PacketType = M_UPDATE;
	Packet.w_begin(PacketType);
	game->net_Export_Update(Packet, xr_client->ID, xr_client->ID);
	SendTo(xr_client->ID, Packet, net_flags(FALSE,TRUE));
}

void xrServer::MakeUpdatePackets()
{
	NET_Packet tmpPacket;
	u32 position;

	m_updator.begin_updates();

	xrS_entities::iterator I = entities.begin();
	xrS_entities::iterator E = entities.end();
	for (; I != E; ++I)
	{
		//all entities
		CSE_Abstract& Test = *(I->second);

		if (0 == Test.owner) continue;
		if (!Test.net_Ready) continue;
		if (Test.s_flags.is(M_SPAWN_OBJECT_PHANTOM)) continue; // Surely: phantom
		if (!Test.Net_Relevant()) continue;

		tmpPacket.B.count = 0;
		// write specific data
		{
			tmpPacket.w_u16(Test.ID);
			tmpPacket.w_chunk_open8(position);
			Test.UPDATE_Write(tmpPacket);
			u32 ObjectSize = u32(tmpPacket.w_tell() - position) - sizeof(u8);
			tmpPacket.w_chunk_close8(position);

			if (ObjectSize == 0) continue;
#ifdef DEBUG
			if (g_Dump_Update_Write) Msg("* %s : %d", Test.name(), ObjectSize);
#endif
			m_updator.write_update_for(Test.ID, tmpPacket);
		}
	} //all entities

	m_updator.end_updates(m_update_begin, m_update_end);
}

void xrServer::SendUpdatePacketsToAll()
{
	m_last_updates_size = 0;
	for (update_iterator_t i = m_update_begin; i != m_update_end; ++i)
	{
		NET_Packet& to_send = **i;
		if (to_send.B.count > 2)
		{
			m_last_updates_size += to_send.B.count;
            struct SnapshotSender
            {
                xrServer* server;
                NET_Packet* packet;
                void operator()(IClient* client)
                {
                    xrClientData* peer = static_cast<xrClientData*>(client);
                    if (client == server->GetServerClient() || !client->flags.bConnected || !peer->gamma_snapshot_ready)
                        return;
                    server->SendTo(client->ID, *packet, net_flags(FALSE, TRUE));
                }
            } send = {this, &to_send};
            ForEachClientDo(send);
		}
	}
}

// Netcoop area of interest. Every object is serialised once per tick; each
// client gets creatures/players every tick at every distance. Other world
// objects retain staggered distance tiers. Items held by someone use the
// holder's position and inherit the creature's full-rate protection.
// Overload policy (doc 43 M04/D05/D06): the server's own frame time, smoothed;
// a slow server sends distant non-creature objects less often, and
// every client has a byte budget per tick that only far objects give way to.
static float s_aoi_frame_ms = 16.f;
static const u32 aoi_client_budget = 16 * 1024; // bytes per client per tick (~480 KB/s at 30 Hz)

// Unchanged state is not sent again (doc 43 D06): a resting item, a backpack
// in another player's inventory or an idle object repeats the same bytes
// every tick. Each client remembers what it got per object; the same bytes
// go out again only as a keep-alive, at the far-tier rate. Updates are
// unreliable, so a lost change is repaired by that keep-alive at the latest.
static const u32 aoi_keepalive_ms = 500;
struct AoiSent
{
	u32 hash;
	u32 time;
};
struct AoiClientState
{
	xr_unordered_map<u16, AoiSent> sent;
	u32 seen_tick = 0;
};
static xr_unordered_map<u32, AoiClientState> s_aoi_clients;
static u32 s_aoi_unchanged = 0; // chunks not resent since the last log line
static u32 s_aoi_log = 0;

static u32 aoi_hash(const u8* data, u32 size)
{
	u32 h = 2166136261u;
	for (u32 i = 0; i < size; ++i)
		h = (h ^ data[i]) * 16777619u;
	return h;
}

void xrServer::SendUpdatesAOI()
{
	s_aoi_frame_ms = s_aoi_frame_ms * 0.95f + Device.fTimeDelta * 1000.f * 0.05f;
	// 1 below ~30 fps, 2 below ~20 fps, 4 below ~12 fps.
	const u32 far_scale = s_aoi_frame_ms > 80.f ? 4 : s_aoi_frame_ms > 50.f ? 2 : s_aoi_frame_ms > 33.f ? 2 : 1;
	struct Chunk
	{
		u32 offset;
		u16 size;
		u16 id;
		bool player;
		bool full_rate; // creature root, including held items; never distance/overload throttled
		u16 owner_only; // a player's Actor id: only that client gets it; 0xffff: everyone
		Fvector position;
	};
	static xr_vector<u8> data;
	static xr_vector<Chunk> chunks;
	static xr_vector<netcoop_world::ReplicationRecord> index_records;
	// Chunk stage 1 (doc 49): the spatial index picks each client's candidates
	// (same set as the full scan, fixture check-netcoop-replication-index.py).
	// Opt-in for now: it rebuilds its grid every tick and sorts per client, so
	// with ~1700 objects and 64 players in one spot the server frame was
	// 43-48 ms with it and 21-23 ms without (2026-10-06). Speed it up first.
	const bool use_index = strstr(Core.Params, "-netcoop_chunk_index") != nullptr;
	data.clear();
	chunks.clear();
	index_records.clear();
	++m_aoi_tick;

	NET_Packet tmp;
	u32 position;
	for (xrS_entities::iterator I = entities.begin(), E = entities.end(); I != E; ++I)
	{
		CSE_Abstract& Test = *(I->second);
		if (0 == Test.owner || !Test.net_Ready || Test.s_flags.is(M_SPAWN_OBJECT_PHANTOM) || !Test.Net_Relevant())
			continue;
		tmp.B.count = 0;
		tmp.w_u16(Test.ID);
		tmp.w_chunk_open8(position);
		Test.UPDATE_Write(tmp);
		const u32 object_size = u32(tmp.w_tell() - position) - sizeof(u8);
		tmp.w_chunk_close8(position);
		if (object_size == 0)
			continue;
		CSE_Abstract* root = &Test;
		CSE_Abstract* top = &Test; // the root's direct child on the way
		for (int depth = 0; depth < 4 && root->ID_Parent != 0xffff; ++depth)
		{
			CSE_Abstract* parent = ID_to_entity(root->ID_Parent);
			if (!parent)
				break;
			top = root;
			root = parent;
		}
		// Chunk stage 1 / doc 43 D02: what lies in a player's inventory is that
		// player's business; others get only the item in hands (and what is
		// inside it).
		u16 owner_only = 0xffff;
		if (root != &Test && root->owner != GetServerClient() && smart_cast<CSE_ALifeCreatureActor*>(root))
		{
			CActor* holder = smart_cast<CActor*>(Level().Objects.net_Find(root->ID));
			PIItem active = holder ? holder->inventory().ActiveItem() : nullptr;
			if (!active || active->object_id() != top->ID)
				owner_only = root->ID;
		}
		Chunk c;
		c.offset = u32(data.size());
		c.size = u16(tmp.B.count);
		c.id = Test.ID;
		c.player = Test.owner != GetServerClient() && smart_cast<CSE_ALifeCreatureActor*>(&Test) != NULL;
		// Do not thin moving/animated characters at maximum visibility or on
		// heavy frames. Root protection also covers their displayed equipment.
		c.full_rate = c.player || smart_cast<CSE_ALifeCreatureAbstract*>(root) != NULL;
		c.owner_only = owner_only;
		c.position = root->o_Position;
		data.insert(data.end(), tmp.B.data, tmp.B.data + tmp.B.count);
		chunks.push_back(c);
		if (use_index) index_records.push_back({c.id,c.full_rate,c.position.x,c.position.y,c.position.z});
	}

	const u32 packet_limit = 8 * 1024;
	// W4 shadow rollout. Compare spatial query with the existing serialized
	// set before using it to affect relevance. These IDs are temporary engine
	// handles for diagnostics, not the future durable entity registry.
	const u64 shadow_now = GetTickCount64();
	if (strstr(Core.Params, "-netcoop_chunk_shadow") && !m_chunk_shadow_failed &&
		(!m_chunk_shadow_last || shadow_now - m_chunk_shadow_last >= 200))
	{
		m_chunk_shadow_last = shadow_now;
		try
		{
			if (!m_chunk_shadow) m_chunk_shadow.reset(new NetcoopChunkShadow());
			m_chunk_shadow->grid.clear();
			for (const Chunk& c : chunks)
				m_chunk_shadow->grid.upsert({0, u64(c.id) + 1}, 1, {c.position.x, c.position.y, c.position.z});
			struct ShadowProbe
			{
				xrServer* server;
				u32 clients = 0, mismatches = 0;
				netcoop_world::SpatialQueryStats stats;
				u64 full_scan = 0;
				std::vector<netcoop_world::PlayerInterest> observers;
				void operator()(IClient* client)
				{
					xrClientData* peer = static_cast<xrClientData*>(client);
					if (client == server->GetServerClient() || !client->flags.bConnected ||
						!peer->gamma_snapshot_ready || !peer->owner) return;
					const Fvector& eye = peer->owner->o_Position;
					const netcoop_world::SpatialPoint center{eye.x, eye.y, eye.z};
					netcoop_world::SpatialPoint velocity;
					const u64 now = server->m_chunk_shadow_last;
					auto old = server->m_chunk_shadow->observers.find(peer->owner->ID);
					if (old != server->m_chunk_shadow->observers.end() && now > old->second.real_ms && now-old->second.real_ms < 2000)
					{
						const double seconds = double(now-old->second.real_ms)/1000.;
						velocity = {(center.x-old->second.position.x)/seconds,
							(center.y-old->second.position.y)/seconds,(center.z-old->second.position.z)/seconds};
					}
					server->m_chunk_shadow->observers[peer->owner->ID] = {center,now};
					observers.push_back({{0,u64(peer->owner->ID)+1},1,center,velocity});
					const auto actual = server->m_chunk_shadow->grid.query(1, center, 1000, &stats);
					std::vector<netcoop_world::SpatialId> expected;
					for (const Chunk& c : chunks)
					{
						++full_scan;
						if (netcoop_world::point_distance_squared(center, {c.position.x,c.position.y,c.position.z}) <= 1000000.)
							expected.push_back({0,u64(c.id)+1});
					}
					std::sort(expected.begin(),expected.end());
					if (actual != expected) ++mismatches;
					++clients;
				}
			} probe = {this};
			const auto started = std::chrono::steady_clock::now();
			ForEachClientDo(probe);
			for (auto it=m_chunk_shadow->observers.begin();it!=m_chunk_shadow->observers.end();)
				if (it->second.real_ms != shadow_now) it=m_chunk_shadow->observers.erase(it); else ++it;
			std::map<netcoop_world::CellId, bool, netcoop_world::CellOrder> occupied;
			for (const Chunk& c : chunks)
				occupied.emplace(m_chunk_shadow->grid.cell(1,{c.position.x,c.position.y,c.position.z}),true);
			std::vector<netcoop_world::LodDemand> demands;
			for (const auto& entry : occupied)
				demands.push_back(m_chunk_shadow->lod.observer_demand(m_chunk_shadow->grid,entry.first,probe.observers));
			const auto lod_changes = m_chunk_shadow->lod.update(demands,shadow_now);
			u32 lod_counts[4] = {};
			for (const auto& entry : occupied) ++lod_counts[unsigned(m_chunk_shadow->lod.level(entry.first))];
			m_chunk_shadow->lod.prune_dormant();
			const u64 query_us = u64(std::chrono::duration_cast<std::chrono::microseconds>(
				std::chrono::steady_clock::now()-started).count());
			if (!m_chunk_shadow_log || shadow_now - m_chunk_shadow_log >= 10000)
			{
				m_chunk_shadow_log = shadow_now;
				Msg("[chunk-shadow] objects=%u cells=%u clients=%u candidates=%llu full_scan=%llu mismatches=%u compare_us=%llu",
					u32(m_chunk_shadow->grid.size()),u32(m_chunk_shadow->grid.cell_count()),probe.clients,
					probe.stats.candidates,probe.full_scan,probe.mismatches,query_us);
				Msg("[lod-shadow] full_cells=%u reduced_cells=%u abstract_cells=%u dormant_cells=%u changes=%u (policy only)",
					lod_counts[3],lod_counts[2],lod_counts[1],lod_counts[0],u32(lod_changes.size()));
			}
		}
		catch (const std::exception&)
		{
			m_chunk_shadow_failed = true;
			m_chunk_shadow.reset();
			Msg("! [chunk-shadow] invalid state/configuration; diagnostics disabled, legacy replication continues");
		}
	}
	bool indexed = false;
	if (use_index)
	{
		if (!m_replication_index) m_replication_index.reset(new netcoop_world::ReplicationIndex());
		indexed = m_replication_index->prepare(index_records.data(),index_records.size());
	}
	u64 candidate_checks = 0, full_checks = 0, grid_checks = 0;
	u32 indexed_clients = 0, fallback_clients = 0;
	u32 sent_bytes = 0;
	struct Sender
	{
		xrServer* server;
		u32* sent;
		bool indexed;
		u64 *candidate_checks, *full_checks, *grid_checks;
		u32 *indexed_clients, *fallback_clients;
		u32 far_scale;
		u32* unchanged_skipped;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (client == server->GetServerClient() || !client->flags.bConnected || !CL->gamma_snapshot_ready ||
				!CL->owner)
				return;
			const Fvector& eye = CL->owner->o_Position;
			u32 client_bytes = 0;
			AoiClientState& memory = s_aoi_clients[CL->ID.value()];
			memory.seen_tick = server->m_aoi_tick;
			const u32 now = Device.dwTimeGlobal;
			NET_Packet P;
			P.w_begin(M_UPDATE_OBJECTS);
			netcoop_world::ReplicationSelection selection;
			if (indexed)
				selection = server->m_replication_index->select(CL->owner->ID,eye.x,eye.y,eye.z,server->m_aoi_tick);
			const std::size_t count = selection.valid ? selection.count : chunks.size();
			*candidate_checks += count; *full_checks += chunks.size(); *grid_checks += selection.spatial_candidates;
			if (selection.valid) ++*indexed_clients; else ++*fallback_clients;
			for (std::size_t cursor = 0; cursor < count; ++cursor)
			{
				const std::size_t i = selection.valid ? selection.indices[cursor] : cursor;
				const Chunk& c = chunks[i];
				if (c.owner_only != 0xffff && c.owner_only != CL->owner->ID)
					continue;
				const float d = c.full_rate || c.id == CL->owner->ID ? 0.f : eye.distance_to(c.position);
				u32 every = c.full_rate ? 1 : d < 50.f ? 1 : d < 150.f ? 2 : d < 300.f ? 4 : 16;
				// Overload/budget never defer characters, their equipment or nearby objects.
				const bool close_by = c.full_rate || d < 50.f;
				if (!close_by) every *= far_scale;
				if ((server->m_aoi_tick + c.id) % every)
					continue;
				if (!close_by && client_bytes > aoi_client_budget)
					continue; // staggered by id and tick, it goes out on a later tick
				// Full-rate states must repair packet loss next tick. Hash equality
				// cannot safely suppress creature updates for the 500 ms keep-alive.
				if (!c.full_rate)
				{
					const u32 hash = aoi_hash(&data[c.offset], c.size);
					AoiSent& last = memory.sent[c.id];
					if (last.hash == hash && last.time && now - last.time < aoi_keepalive_ms)
					{
						++*unchanged_skipped;
						continue;
					}
					last.hash = hash;
					last.time = now ? now : 1;
				}
				client_bytes += c.size;
				if (P.B.count + c.size > packet_limit)
				{
					server->SendTo(CL->ID, P, net_flags(FALSE, TRUE));
					*sent += P.B.count;
					P.w_begin(M_UPDATE_OBJECTS);
				}
				P.w(&data[c.offset], c.size);
			}
			if (P.B.count > 2)
			{
				server->SendTo(CL->ID, P, net_flags(FALSE, TRUE));
				*sent += P.B.count;
			}
		}
	} send = {this, &sent_bytes, indexed, &candidate_checks, &full_checks, &grid_checks, &indexed_clients, &fallback_clients, far_scale,
		&s_aoi_unchanged};
	ForEachClientDo(send);
	// Forget clients that left (not served for ~10 s).
	if (m_aoi_tick % 300 == 0)
		for (auto it = s_aoi_clients.begin(); it != s_aoi_clients.end();)
			it = m_aoi_tick - it->second.seen_tick > 300 ? s_aoi_clients.erase(it) : std::next(it);
	if (Device.dwTimeGlobal - s_aoi_log >= 10000)
	{
		Msg("[Lost Zone][replication] unchanged not resent %.0f/s, frame %.1f ms, far x%u", float(s_aoi_unchanged) / 10.f,
			s_aoi_frame_ms, far_scale);
		s_aoi_unchanged = 0;
		s_aoi_log = Device.dwTimeGlobal;
	}
	if (use_index && (!m_replication_index_log || shadow_now-m_replication_index_log>=10000))
	{
		m_replication_index_log = shadow_now;
		Msg("[replication-index] objects=%u clients=%u fallback=%u selected=%llu full_scan=%llu grid_candidates=%llu (full-rate creatures; world tiers)",
			u32(chunks.size()),indexed_clients,fallback_clients,candidate_checks,full_checks,grid_checks);
	}
	m_last_updates_size = sent_bytes;
	netcoop::metric_server_sent(sent_bytes, u32(chunks.size()));
}

void xrServer::SendUpdatesToAll()
{
	if (IsGameTypeSingle() && !strstr(Core.Params, "-netcoop"))
		return;
	if (!GetServerClient()) return;

	KickCheaters();


	//sending game_update 
	fastdelegate::FastDelegate1<IClient*, void> sendtofd;
	sendtofd.bind(this, &xrServer::SendGameUpdateTo);

	if ((Device.dwTimeGlobal - m_last_update_time) >= u32(1000 / (psNET_ServerUpdate > 0 ? psNET_ServerUpdate : 30)))
	{
		ForEachClientDoSender(sendtofd);
		if (netcoop::smooth())
			SendUpdatesAOI();
		else
		{
			MakeUpdatePackets();
			SendUpdatePacketsToAll();
		}

#ifdef DEBUG
		g_sv_SendUpdate = 0;
#endif
		if (game->sv_force_sync) Perform_game_export();
#ifdef DEBUG
		VERIFY(verify_entities());
#endif
		// Netcoop: a fixed tick (catching up at most one interval) instead of
		// "at least 33 ms since the frame that sent", which averages 36+ ms.
		const u32 interval = u32(1000 / (psNET_ServerUpdate > 0 ? psNET_ServerUpdate : 30));
		if (netcoop::smooth() && Device.dwTimeGlobal - m_last_update_time < 2 * interval)
			m_last_update_time += interval;
		else
			m_last_update_time = Device.dwTimeGlobal;
	}
}

u32 xrServer::OnDelayedMessage(NET_Packet& P, ClientID sender) // Non-Zero means broadcasting with "flags" as returned
{
	if (P.B.count < sizeof(u16) || !ID_to_client(sender)) return 0;
	u16 type;
	P.r_begin(type);

	//csPlayers.Enter			();
#ifdef DEBUG
	VERIFY(verify_entities());
#endif
	xrClientData* CL = ID_to_client(sender);
	//R_ASSERT2						(CL, make_string("packet type [%d]",type).c_str());

	switch (type)
	{
	case M_CLIENT_REQUEST_CONNECTION_DATA:
		{
			IClient* tmp_client = net_players.GetFoundClient(
				ClientIdSearchPredicate(sender));
			VERIFY(tmp_client);
			xrClientData* joining_client = static_cast<xrClientData*>(tmp_client);
			joining_client->net_ConnectionDataRequested = TRUE;
			if (joining_client->ps && !joining_client->net_Accepted)
				OnCL_Connected(joining_client);
			//OnCL_Connected				(CL);
		}
		break;
	}
#ifdef DEBUG
	VERIFY(verify_entities());
#endif
	//csPlayers.Leave					();
	return 0;
}

u32 xrServer::OnMessageSync(NET_Packet& P, ClientID sender)
{
	csMessage.Enter();
	u32 ret = OnMessage(P, sender);
	csMessage.Leave();
	return ret;
}

extern float g_fCatchObjectTime;

u32 xrServer::OnMessage(NET_Packet& P, ClientID sender) // Non-Zero means broadcasting with "flags" as returned
{
	if (P.B.count < sizeof(u16)) return 0;
	u16 type;
	P.r_begin(type);
#ifdef DEBUG
	VERIFY(verify_entities());
#endif
	xrClientData* CL = ID_to_client(sender);
    if (!CL) return 0;
    if (!CL->flags.bLocal && netcoop::enabled() && GetCurrentThreadId() != m_netcoop_main_thread)
    {
        const u32 header[3] = {sender.value(), P.timeReceive, P.B.count};
        m_netcoop_packets_cs.Enter();
        const size_t at = m_netcoop_packets.size();
        m_netcoop_packets.resize(at + sizeof(header) + P.B.count);
        CopyMemory(&m_netcoop_packets[at], header, sizeof(header));
        CopyMemory(&m_netcoop_packets[at + sizeof(header)], P.B.data, P.B.count);
        m_netcoop_packets_cs.Leave();
        return 0;
    }
    if (strstr(Core.Params, "-netcoop"))
    {
        switch (type)
        {
        case M_SAVE_GAME: case M_SAVE_PACKET: case M_LOAD_GAME: case M_RELOAD_GAME:
            Msg("! [GAMMA NetAnomaly] Single-player save/load packet rejected");
            return 0; // Also reject the internal host: SP snapshots cannot persist multiplayer accounts.
        default: break;
        }
    }
    if (!CL->flags.bLocal && netcoop::enabled())
    {
        if (netcoop::server_client_leaving(CL)) return 0; // frozen until it reconnects elsewhere
        // Input still validates/advances its sequence while restore is pending.
        // Otherwise a long restore exceeds the forward window and locks out movement.
        if (type != M_CL_INPUT && !netcoop::server_character_accepts(CL, type)) return 0;
        if (type == M_CHANGE_LEVEL && CL->netcoop_role != netcoop::role_none)
        {
            netcoop::server_on_change_level(this, CL, P);
            return 0;
        }
    }
    if (!CL->flags.bLocal)
    {
        switch (type)
        {
	case M_UPDATE: case M_SPAWN: case M_SAVE_GAME: case M_SAVE_PACKET:
        case M_LOAD_GAME: case M_RELOAD_GAME: case M_CHANGE_LEVEL:
        case M_CHANGE_LEVEL_GAME: case M_SWITCH_DISTANCE:
            return 0; // Only the authoritative ALife host can mutate global world state.
        default: break;
        }
    }

	switch (type)
	{
	case M_CL_INPUT:
	{
		if (!CL || !CL->owner || !smart_cast<CSE_ALifeCreatureActor*>(CL->owner)) break;
		if (P.B.count - P.r_tell() != M_CL_INPUT_WIRE_SIZE) break;
		
		ActorInputCommand cmd;
		P.r_u32(cmd.sequence);
		P.r_u16(cmd.mstate);
		P.r_float(cmd.yaw);
		P.r_float(cmd.pitch);
		
		// Finite validation
		if (!_valid(cmd.yaw) || !_valid(cmd.pitch)) break;
		// angle_normalize_signed converts whole turns through a 32-bit integer.
		// Bound finite values before normalization to reject extreme input.
		if (_abs(cmd.yaw) > PI_MUL_2 * 4 || _abs(cmd.pitch) > PI_MUL_2 * 2) break;
		// Yaw/Pitch Limits
		cmd.yaw = angle_normalize_signed(cmd.yaw);
		cmd.pitch = angle_normalize_signed(cmd.pitch);
		clamp(cmd.pitch, -PI_DIV_2, PI_DIV_2);
		
		// Symbolic MState flags
		if (cmd.mstate & ~ACTOR_DEFS::kM1InputIntentFlags) break;
		
		// Sequence logic
		if (is_sequence_newer(cmd.sequence, CL->m_last_received_sequence) && 
		    is_sequence_in_forward_window(cmd.sequence, CL->m_last_received_sequence)) {
			CL->m_last_received_sequence = cmd.sequence;
			if (!netcoop::server_character_accepts(CL, M_CL_INPUT)) break;
			CL->m_last_input_receive_time = Device.dwTimeGlobal;
			if (cmd.mstate & ACTOR_DEFS::mcJump)
				CL->m_pending_jump_edge = true;
			if (CL->m_pending_inputs.size() >= 64) {
				CL->m_pending_inputs.pop_front(); // DROP OLDEST to avoid infinite lag
			}
			CL->m_pending_inputs.push_back(cmd);
		}
	}
	break;
	case M_UPDATE:
		{
			Process_update(P, sender); // No broadcast
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_SPAWN:
		{
			if (CL->flags.bLocal)
				Process_spawn(P, sender);
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_EVENT:
		{
			Process_event(P, sender);
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_EVENT_PACK:
		{
			NET_Packet tmpP;
			while (!P.r_eof())
			{
                tmpP.B.count = P.r_u8();
                if (tmpP.B.count < sizeof(u16) || tmpP.B.count > P.B.count - P.r_tell()) break;
                P.r(&tmpP.B.data, tmpP.B.count);
                u16 nested_type;
                CopyMemory(&nested_type, tmpP.B.data, sizeof(nested_type));
                if (nested_type == M_EVENT_PACK) break; // No recursive packs / stack exhaustion.

				OnMessage(tmpP, sender);
			};
		}
		break;
	case M_CL_UPDATE:
		{
			xrClientData* CL = ID_to_client(sender);
			if (!CL) break;
			CL->net_Ready = TRUE;

            if (!CL->net_PassUpdates || !CL->owner || P.B.count < 8) break;
            u16 object_id;
            CopyMemory(&object_id, P.B.data + 2, sizeof(object_id));
            if (object_id != CL->owner->ID) break; // A client may update only its own actor.
            if (IsGameTypeSingle() && strstr(Core.Params, "-netcoop") &&
                !gamma_net::valid_coop_actor(P.B.data + 8, P.B.count - 8)) break;
			//-------------------------------------------------------------------
			u32 ClientPing = CL->stats.getPing();
			P.w_seek(P.r_tell() + 2, &ClientPing, 4);
			//-------------------------------------------------------------------
			if (SV_Client)
				SendTo(SV_Client->ID, P, net_flags(FALSE, TRUE));
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_MOVE_PLAYERS_RESPOND:
		{
			xrClientData* CL = ID_to_client(sender);
			if (!CL) break;
			CL->net_Ready = TRUE;
			CL->net_PassUpdates = TRUE;
		}
		break;
		//-------------------------------------------------------------------
	case M_GAMEMESSAGE:
		// Game messages (chat lines, kill and server notices) go from the
		// server to clients; no client sends one, so it is not passed on.
		Msg("! game message from client 0x%08x dropped", sender.value());
		break;
	case M_CLIENTREADY:
		{
			game->OnPlayerConnectFinished(sender);
			//game->signal_Syncronize	();
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_SWITCH_DISTANCE:
		{
			game->switch_distance(P, sender);
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_CHANGE_LEVEL:
		{
			if (game->change_level(P, sender))
			{
				SendBroadcast(BroadcastCID, P, net_flags(TRUE,TRUE));
			}
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_SAVE_GAME:
		{
			game->save_game(P, sender);
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_LOAD_GAME:
		{
			game->load_game(P, sender);
			SendBroadcast(BroadcastCID, P, net_flags(TRUE,TRUE));
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_RELOAD_GAME:
		{
			SendBroadcast(BroadcastCID, P, net_flags(TRUE,TRUE));
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_SAVE_PACKET:
		{
			Process_save(P, sender);
#ifdef DEBUG
			VERIFY(verify_entities());
#endif
		}
		break;
	case M_CLIENT_REQUEST_CONNECTION_DATA:
		{
			AddDelayedPacket(P, sender);
		}
		break;
	case M_NETCOOP_AUTH:
		{
			netcoop::server_on_auth(this, CL, P);
		}
		break;
	case M_NETCOOP_PDA_SCREEN:
		netcoop::server_on_pda_screen(this, CL, P);
		break;
	case M_NETCOOP_TRADE:
		{
			if (!CL->flags.bLocal && CL->netcoop_role != netcoop::role_none)
				netcoop::server_on_trade(this, CL, P);
		}
		break;
	case M_NETCOOP_CAMPFIRE:
		if (!CL->flags.bLocal && CL->netcoop_role != netcoop::role_none)
			netcoop::server_on_campfire(this, CL, P);
		break;
	case M_NETCOOP_VOICE:
		if (!CL->flags.bLocal && CL->netcoop_role != netcoop::role_none)
			netcoop::server_on_voice(this, CL, P);
		break;
	case M_NETCOOP_VEHICLE:
		if (!CL->flags.bLocal && CL->netcoop_role != netcoop::role_none)
			netcoop::server_on_vehicle(this, CL, P);
		break;
	case M_NETCOOP_ITEM_ACTION:
		if (!CL->flags.bLocal && CL->netcoop_role != netcoop::role_none)
			netcoop::server_on_item_action(this, CL, P);
		break;
	case M_NETCOOP_TRANSFER:
		if (!CL->flags.bLocal && CL->netcoop_role != netcoop::role_none)
			netcoop::server_on_transfer(this, CL, P);
		break;
	case M_NETCOOP_ITEM_REPORT:
		if (!CL->flags.bLocal && CL->netcoop_role != netcoop::role_none)
			netcoop::server_on_item_report(this, CL, P);
		break;
	case M_NETCOOP_TALK:
		{
			if (!CL->flags.bLocal && CL->netcoop_role != netcoop::role_none)
				netcoop::server_on_talk(this, CL, P);
		}
		break;
	case M_NETANOMALY_CMD:
		{
			// Remote clients need a logged-in account; the Lua handler checks the role.
			if (!CL->flags.bLocal && CL->netcoop_role == netcoop::role_none) break;
			if (P.B.count < 3 || P.B.count > 4098 || !memchr(P.B.data + 2, 0, P.B.count - 2)) break;
			//netanomaly: text command channel client -> server, handled in lua
			string4096 na_text;
			na_text[0] = 0;
			P.r_stringZ(na_text);
			xrClientData* na_cl = ID_to_client(sender);
			LPCSTR na_name = (na_cl && na_cl->netcoop_login.size()) ? na_cl->netcoop_login.c_str()
				: (na_cl && na_cl->name.size()) ? na_cl->name.c_str() : "unknown";
			LPCSTR na_role = CL->flags.bLocal ? "admin" : netcoop::role_name(CL->netcoop_role);
			int na_eid = (na_cl && na_cl->owner) ? int(na_cl->owner->ID) : int(65535);
			string64 na_cid;
			xr_sprintf(na_cid, "%08x", sender.value());
			// Clients report their player state every 30 s: not worth a log line each.
			if (strncmp(na_text, "player_state ", 13))
				Msg("[Lost Zone] command from [%s] (%s) eid=%d", na_name, na_role, na_eid);
			string4096 na_reply;
			na_reply[0] = 0;
			::luabind::functor<LPCSTR> na_f;
			if (ai().script_engine().functor<LPCSTR>("netanomaly_server.on_client_command", na_f))
			{
				try
				{
					// The PDA task board runs GAMMA task scripts: db.actor, the
					// engine Actor and the task list are the asking player's.
					CActor* na_actor = !strncmp(na_text, "taskboard ", 10) && na_eid != 65535 ?
						smart_cast<CActor*>(Level().Objects.net_Find(u16(na_eid))) : NULL;
					netcoop::ServerVictimScope na_scope(na_actor && na_actor->g_Alive() ? na_actor : NULL);
					LPCSTR na_res = na_f((LPCSTR)na_cid, na_name, na_eid, (LPCSTR)na_text, na_role);
					if (na_res) strncpy_s(na_reply, sizeof(na_reply), na_res, _TRUNCATE);
				}
				catch (...)
				{
					xr_strcpy(na_reply, "! server script error");
				}
			}
			else
			{
				xr_strcpy(na_reply, "! netanomaly_server.script is not loaded on the server");
			}
			if (xr_strlen(na_reply))
			{
				Msg("[Lost Zone] cmd reply -> %s", na_reply);
				NET_Packet na_p;
				na_p.w_begin(M_NETANOMALY_MSG);
				na_p.w_stringZ(na_reply);
				SendTo(sender, na_p, net_flags(TRUE, TRUE));
			}
		}
		break;
	case M_SV_MAP_NAME:
		{
			xrClientData* l_pC = ID_to_client(sender);
			OnProcessClientMapData(P, l_pC->ID);
		}
		break;
	case M_CHANGE_LEVEL_GAME:
		{
			ClientID CID;
			CID.set(0xffffffff);
			SendBroadcast(CID, P, net_flags(TRUE,TRUE));
		}
		break;
	case M_CL_AUTH:
		{
			game->AddDelayedEvent(P, GAME_EVENT_PLAYER_AUTH, 0, sender);
		}
		break;
	case M_CREATE_PLAYER_STATE:
		{
			game->AddDelayedEvent(P, GAME_EVENT_CREATE_PLAYER_STATE, 0, sender);
		}
		break;
	case M_SECURE_KEY_SYNC:
		{
			PerformSecretKeysSyncAck(CL, P);
		}
		break;
	case M_SECURE_MESSAGE:
		{
			OnSecureMessage(P, CL);
		}
		break;
	}
#ifdef DEBUG
	VERIFY(verify_entities());
#endif
	return IPureServer::OnMessage(P, sender);
}

void xrServer::SendTo_LL(ClientID ID, void* data, u32 size, u32 dwFlags, u32 dwTimeout)
{
	if ((SV_Client && SV_Client->ID == ID) || (psNET_direct_connect))
	{
		// optimize local traffic
		Level().OnMessage(data, size);
	}
	else
	{
		IClient* pClient = ID_to_client(ID);
		VERIFY2(pClient && pClient->flags.bConnected, "trying to send packet to disconnected client");
		if (!pClient || !pClient->flags.bConnected)
			return;

		IPureServer::SendTo_Buf(ID, data, size, dwFlags, dwTimeout);
	}
}

void xrServer::SendBroadcast(ClientID exclude, NET_Packet& P, u32 dwFlags)
{
	struct ClientExcluderPredicate
	{
		ClientID id_to_exclude;

		ClientExcluderPredicate(ClientID exclude) :
			id_to_exclude(exclude)
		{
		}

		bool operator()(IClient* client)
		{
			xrClientData* tmp_client = static_cast<xrClientData*>(client);
			if (client->ID == id_to_exclude)
				return false;
			if (!client->flags.bConnected)
				return false;
			if (!tmp_client->net_Accepted)
				return false;
			return true;
		}
	};
	struct ClientSenderFunctor
	{
		xrServer* m_owner;
		void* m_data;
		u32 m_size;
		u32 m_dwFlags;

		ClientSenderFunctor(xrServer* owner, void* data, u32 size, u32 dwFlags) :
			m_owner(owner), m_data(data), m_size(size), m_dwFlags(dwFlags)
		{
		}

		void operator()(IClient* client)
		{
			m_owner->SendTo_LL(client->ID, m_data, m_size, m_dwFlags);
		}
	};
	ClientSenderFunctor temp_functor(this, P.B.data, P.B.count, dwFlags);
	net_players.ForFoundClientsDo(ClientExcluderPredicate(exclude), temp_functor);
}

//--------------------------------------------------------------------
CSE_Abstract* xrServer::entity_Create(LPCSTR name)
{
	return F_entity_Create(name);
}

void xrServer::entity_Destroy(CSE_Abstract*& P)
{
#ifdef DEBUG
if( dbg_net_Draw_Flags.test( dbg_destroy ) )
		Msg	("xrServer::entity_Destroy : [%d][%s][%s]",P->ID,P->name(),P->name_replace());
#endif
	R_ASSERT(P);
	entities.erase(P->ID);
	m_tID_Generator.vfFreeID(P->ID, Device.TimerAsync());

	if (P->owner && P->owner->owner == P)
		P->owner->owner = NULL;

	P->owner = NULL;
	if (!ai().get_alife() || !P->m_bALifeControl)
	{
		F_entity_Destroy(P);
	}
}

//--------------------------------------------------------------------
void xrServer::Server_Client_Check(IClient* CL)
{
	if (SV_Client && SV_Client->ID == CL->ID)
	{
		if (!CL->flags.bConnected)
		{
			SV_Client = NULL;
		};
		return;
	};

	if (SV_Client && SV_Client->ID != CL->ID)
	{
		return;
	};


	if (!CL->flags.bConnected)
	{
		return;
	};

	// The transport admits the server's process id only for the server's own
	// local connection (its client ID is not known to the level yet here).
	if (CL->process_id == GetCurrentProcessId())
	{
		CL->flags.bLocal = 1;
		SV_Client = (xrClientData*)CL;
		Msg("New SV client 0x%08x", SV_Client->ID.value());
	}
	else
	{
		CL->flags.bLocal = 0;
	}
};

bool xrServer::OnCL_QueryHost()
{
	if (game->Type() == eGameIDSingle) return false;
	return (GetClientsCount() != 0);
};

CSE_Abstract* xrServer::GetEntity(u32 Num)
{
	xrS_entities::iterator I = entities.begin(), E = entities.end();
	for (u32 C = 0; I != E; ++I, ++C)
	{
		if (C == Num) return I->second;
	};
	return NULL;
};


#ifdef DEBUG

static	BOOL	_ve_initialized			= FALSE;
static	BOOL	_ve_use					= TRUE;

bool xrServer::verify_entities				() const
{
	if (!_ve_initialized)	{
		_ve_initialized					= TRUE;
		if (strstr(Core.Params,"-~ve"))	_ve_use=FALSE;
	}
	if (!_ve_use)						return true;

	xrS_entities::const_iterator		I = entities.begin();
	xrS_entities::const_iterator		E = entities.end();
	for ( ; I != E; ++I) {
		VERIFY2							((*I).first != 0xffff,"SERVER : Invalid entity id as a map key - 0xffff");
		VERIFY2							((*I).second,"SERVER : Null entity object in the map");
		VERIFY3							((*I).first == (*I).second->ID,"SERVER : ID mismatch - map key doesn't correspond to the real entity ID",(*I).second->name_replace());
		verify_entity					((*I).second);
	}
	return								(true);
}

void xrServer::verify_entity				(const CSE_Abstract *entity) const
{
	VERIFY(entity->m_wVersion!=0);
	if (entity->ID_Parent != 0xffff) {
		xrS_entities::const_iterator	J = entities.find(entity->ID_Parent);
		VERIFY2							(J != entities.end(),
			make_string("SERVER : Cannot find parent in the map [%s][%s]",entity->name_replace(),
			entity->name()).c_str());
		VERIFY3							((*J).second,"SERVER : Null entity object in the map",entity->name_replace());
		VERIFY3							((*J).first == (*J).second->ID,"SERVER : ID mismatch - map key doesn't correspond to the real entity ID",(*J).second->name_replace());
		VERIFY3							(std::find((*J).second->children.begin(),(*J).second->children.end(),entity->ID) != (*J).second->children.end(),"SERVER : Parent/Children relationship mismatch - Object has parent, but corresponding parent doesn't have children",(*J).second->name_replace());
	}

	xr_vector<u16>::const_iterator		I = entity->children.begin();
	xr_vector<u16>::const_iterator		E = entity->children.end();
	for ( ; I != E; ++I) {
		VERIFY3							(*I != 0xffff,"SERVER : Invalid entity children id - 0xffff",entity->name_replace());
		xrS_entities::const_iterator	J = entities.find(*I);
		VERIFY3							(J != entities.end(),"SERVER : Cannot find children in the map",entity->name_replace());
		VERIFY3							((*J).second,"SERVER : Null entity object in the map",entity->name_replace());
		VERIFY3							((*J).first == (*J).second->ID,"SERVER : ID mismatch - map key doesn't correspond to the real entity ID",(*J).second->name_replace());
		VERIFY3							((*J).second->ID_Parent == entity->ID,"SERVER : Parent/Children relationship mismatch - Object has children, but children doesn't have parent",(*J).second->name_replace());
	}
}

#endif // DEBUG

shared_str xrServer::level_name(const shared_str& server_options) const
{
	return (game->level_name(server_options));
}

shared_str xrServer::level_version(const shared_str& server_options) const
{
	return (game_sv_GameState::parse_level_version(server_options));
}

void xrServer::create_direct_client()
{
	SClientConnectData cl_data;
	cl_data.clientID.set(1);
	xr_strcpy(cl_data.name, "single_player");
	cl_data.process_id = GetCurrentProcessId();

	new_client(&cl_data);
}


void xrServer::ProceedDelayedPackets()
{
	DelayedPackestCS.Enter();
	while (!m_aDelayedPackets.empty())
	{
		DelayedPacket& DPacket = *m_aDelayedPackets.begin();
		OnDelayedMessage(DPacket.Packet, DPacket.SenderID);
		//		OnMessage(DPacket.Packet, DPacket.SenderID);
		m_aDelayedPackets.pop_front();
	}
	DelayedPackestCS.Leave();
};

void xrServer::netcoop_process_packets()
{
	xr_vector<u8>& work = m_netcoop_packets_work;
	work.clear();
	m_netcoop_packets_cs.Enter();
	work.swap(m_netcoop_packets);
	m_netcoop_packets_cs.Leave();
	if (work.empty())
		return;

	// Only a client's newest position update matters (they are unreliable
	// and carry their own time); older ones in the same batch are skipped.
	static xr_map<u32, size_t> newest_update;
	newest_update.clear();
	const size_t header = 3 * sizeof(u32);
	for (size_t at = 0; at + header <= work.size();)
	{
		u32 h[3];
		CopyMemory(h, &work[at], header);
		if (h[2] >= sizeof(u16) && *(const u16*)&work[at + header] == M_CL_UPDATE)
			newest_update[h[0]] = at;
		at += header + h[2];
	}

	NET_Packet P;
	for (size_t at = 0; at + header <= work.size();)
	{
		u32 h[3];
		CopyMemory(h, &work[at], header);
		const size_t record = at;
		at += header + h[2];
		if (h[2] > NET_PacketSizeLimit)
			continue;
		if (h[2] >= sizeof(u16) && *(const u16*)&work[record + header] == M_CL_UPDATE &&
			newest_update[h[0]] != record)
			continue;
		ClientID sender;
		sender.set(h[0]);
		P.construct(&work[record + header], h[2]);
		P.timeReceive = h[1];
		csMessage.Enter();
		u32 result = OnMessage(P, sender);
		csMessage.Leave();
		if (result)
			SendBroadcast(sender, P, result);
	}
	// Keep the buffers' capacity, but not a burst's worth forever.
	if (work.capacity() > 4 * 1024 * 1024)
		xr_vector<u8>().swap(work);
}

void xrServer::AddDelayedPacket(NET_Packet& Packet, ClientID Sender)
{
	DelayedPackestCS.Enter();

	m_aDelayedPackets.push_back(DelayedPacket());
	DelayedPacket* NewPacket = &(m_aDelayedPackets.back());
	NewPacket->SenderID = Sender;
	CopyMemory(&(NewPacket->Packet), &Packet, sizeof(NET_Packet));

	DelayedPackestCS.Leave();
}

u32 g_sv_dwMaxClientPing = 2000;
u32 g_sv_time_for_ping_check = 15000; // 15 sec
u8 g_sv_maxPingWarningsCount = 5;

void xrServer::PerformCheckClientsForMaxPing()
{
	struct MaxPingClientDisconnector
	{
		xrServer* m_owner;

		MaxPingClientDisconnector(xrServer* owner) :
			m_owner(owner)
		{
		}

		void operator()(IClient* client)
		{
			xrClientData* Client = static_cast<xrClientData*>(client);
			game_PlayerState* ps = Client->ps;
			if (!ps)
				return;

			if (client == m_owner->GetServerClient())
				return;

			if (ps->ping > g_sv_dwMaxClientPing &&
				Client->m_ping_warn.m_dwLastMaxPingWarningTime + g_sv_time_for_ping_check < Device.dwTimeGlobal)
			{
				++Client->m_ping_warn.m_maxPingWarnings;
				Client->m_ping_warn.m_dwLastMaxPingWarningTime = Device.dwTimeGlobal;

				if (Client->m_ping_warn.m_maxPingWarnings >= g_sv_maxPingWarningsCount)
				{
					//kick
					LPSTR reason;
					STRCONCAT(reason, CStringTable().translate("st_kicked_by_server").c_str());
					Level().Server->DisconnectClient(Client, reason);
				}
				else
				{
					Msg("! client 0x%08x ping %u ms over %u: warning %u of %u", Client->ID.value(), ps->ping,
						g_sv_dwMaxClientPing, Client->m_ping_warn.m_maxPingWarnings, g_sv_maxPingWarningsCount);
				}
			}
		}
	};
	MaxPingClientDisconnector temp_functor(this);
	ForEachClientDoSender(temp_functor);
}


//xr_token game_types[];
LPCSTR GameTypeToString(EGameIDs gt, bool bShort);

void xrServer::GetServerInfo(CServerInfo* si)
{
	string32 tmp;
	string256 tmp256;
	struct ConsoleClients
	{
		u32 connected = 0;
		u32 ready_players = 0;
		u32 queued_inputs = 0;
		u32 last_received = 0;
		u32 last_processed = 0;
		u32 input_age_ms = 0;
		u16 input_flags = 0;
		u32 actor_state = 0;
		Fvector actor_position = {};
		bool has_actor_position = false;
		bool has_remote_actor = false;
		void operator()(IClient* client)
		{
			xrClientData* data = static_cast<xrClientData*>(client);
			++connected;
			if (data->net_Ready && smart_cast<CSE_ALifeCreatureActor*>(data->owner))
				++ready_players;
			queued_inputs += (u32)data->m_pending_inputs.size();
			if (!has_remote_actor && !data->flags.bLocal && smart_cast<CSE_ALifeCreatureActor*>(data->owner))
			{
				has_remote_actor = true;
				last_received = data->m_last_received_sequence;
				last_processed = data->m_last_processed_sequence;
				input_age_ms = Device.dwTimeGlobal - data->m_last_input_receive_time;
				input_flags = data->m_current_intent.mstate;
				if (g_pGameLevel)
				{
					CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(data->owner->ID));
					if (actor)
					{
						actor_state = actor->MovingState();
						actor_position = actor->Position();
						has_actor_position = true;
					}
				}
			}
		}
	} clients;
	ForEachClientDo(clients);

	si->AddItem("Server name", Core.CompName, RGB(130, 160, 255));
	shared_str level_name = g_pGameLevel ? Level().name() : shared_str();
	si->AddItem("Map", level_name.size() ? level_name.c_str() : "loading", RGB(255, 100, 190));
	xr_sprintf(tmp, sizeof(tmp), "%u / %u", clients.ready_players, gamma_net::player_limit(*connect_options));
	si->AddItem("Players", tmp, RGB(210, 150, 255));
	xr_sprintf(tmp, sizeof(tmp), "%u", clients.connected);
	si->AddItem("Connections", tmp, RGB(150, 220, 255));
	xr_sprintf(tmp, sizeof(tmp), "%u", GetEntitiesNum());
	si->AddItem("Server entities", tmp, RGB(155, 235, 180));
	if (g_pGameLevel)
	{
		xr_sprintf(tmp, sizeof(tmp), "%u", Level().Objects.o_count());
		si->AddItem("Online objects", tmp, RGB(155, 235, 180));
	}
	si->AddItem("Game version", "AnomalyMP M1", RGB(130, 220, 255));
	si->AddItem("Access", strstr(*connect_options, "psw=") ? "Password" : "Open", RGB(240, 190, 170));

	si->AddItem("Server port", itoa(GetPort(), tmp, 10), RGB(128, 128, 255));
	LPCSTR time = InventoryUtilities::GetTimeAsString(Device.dwTimeGlobal, InventoryUtilities::etpTimeToSecondsAndDay).
		c_str();
	si->AddItem("Uptime", time, RGB(255, 228, 0));
	// Show a rolling minimum alongside the current dedicated simulation FPS.
	static u32 fps_window_start = 0;
	static float fps_minimum = 0.f;
	const u32 fps_now = GetTickCount();
	const float fps = Device.Statistic->fFPS;
	if (!fps_window_start || fps_now - fps_window_start >= 60000)
	{
		fps_window_start = fps_now;
		fps_minimum = fps;
	}
	else if (fps > 0.f && (fps_minimum <= 0.f || fps < fps_minimum))
		fps_minimum = fps;
	xr_sprintf(tmp, sizeof(tmp), "%.1f / min %.1f", fps, fps_minimum);
	si->AddItem("FPS", tmp, RGB(210, 240, 255));
	xr_sprintf(tmp, sizeof(tmp), "%u", clients.queued_inputs);
	si->AddItem("M1 input queue", tmp, RGB(155, 235, 180));
	if (clients.has_remote_actor)
	{
		xr_sprintf(tmp256, sizeof(tmp256), "received %u / processed %u", clients.last_received, clients.last_processed);
		si->AddItem("M1 input sequence", tmp256, RGB(155, 235, 180));
		xr_sprintf(tmp, sizeof(tmp), "%u ms", clients.input_age_ms);
		si->AddItem("M1 input age", tmp, clients.input_age_ms > 500 ? RGB(255, 120, 120) : RGB(155, 235, 180));
		xr_sprintf(tmp, sizeof(tmp), "intent 0x%04x / simulated 0x%04x", clients.input_flags, clients.actor_state & 0xffff);
		si->AddItem("M1 movement flags", tmp, RGB(155, 235, 180));
		if (clients.has_actor_position)
		{
			xr_sprintf(tmp, sizeof(tmp), "%.2f %.2f %.2f", clients.actor_position.x, clients.actor_position.y, clients.actor_position.z);
			si->AddItem("M1 server position", tmp, RGB(155, 235, 180));
		}
	}

	//	xr_strcpy( tmp256, get_token_name(game_types, game->Type() ) );
	xr_strcpy(tmp256, GameTypeToString(game->Type(), true));
	si->AddItem("Game type", tmp256, RGB(128, 255, 255));

	if (g_pGameLevel)
	{
		time = InventoryUtilities::GetGameTimeAsString(InventoryUtilities::etpTimeToMinutes).c_str();

		xr_strcpy(tmp256, time);
		si->AddItem("Game time", tmp256, RGB(205, 228, 178));
		si->AddItem("Game date", InventoryUtilities::GetGameDateAsString(InventoryUtilities::edpDateToDay, '.').c_str(),
			RGB(205, 228, 178));
		const shared_str weather = g_pGamePersistent ? g_pGamePersistent->Environment().GetWeather() : shared_str();
		si->AddItem("Weather", weather.size() ? weather.c_str() : "loading", RGB(194, 217, 255));
	}
}

void xrServer::AddCheater(shared_str const& reason, ClientID const& cheaterID)
{
	CheaterToKick new_cheater;
	new_cheater.reason = reason;
	new_cheater.cheater_id = cheaterID;
	m_cheaters.push_back(new_cheater);
}

void xrServer::KickCheaters()
{
	for (cheaters_t::iterator i = m_cheaters.begin(),
	                          ie = m_cheaters.end(); i != ie; ++i)
	{
		IClient* tmp_client = GetClientByID(i->cheater_id);
		if (!tmp_client)
		{
			Msg("! ERROR: KickCheaters: client [%u] not found", i->cheater_id);
			continue;
		}
		ClientID tmp_client_id = tmp_client->ID;
		DisconnectClient(tmp_client, i->reason.c_str());

		NET_Packet P;
		P.w_begin(M_GAMEMESSAGE);
		P.w_u32(GAME_EVENT_SERVER_STRING_MESSAGE);
		P.w_stringZ(i->reason.c_str() + 2);
		Level().Server->SendBroadcast(tmp_client_id, P);
	}
	m_cheaters.clear();
}

