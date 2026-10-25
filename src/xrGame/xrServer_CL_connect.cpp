#include "stdafx.h"
#include "xrserver.h"
#include "xrmessages.h"
#include "xrserver_objects.h"
#include "xrServer_Objects_Alife_Monsters.h"
#include "Level.h"
#include "Actor.h"
#include "netcoop.h"

// Join admission (doc 43 M05). Every joining player gets the whole world
// (about 1700 spawn messages) at once; 60+ players joining together queued
// so much reliable data that the server froze for seconds and SteamNet
// dropped every connection (128-player test, 2026-10-06). At most
// join_slots players receive the world at the same time; the others wait
// in order. A slot is free when that player's Actor exists, or after 20 s.
static const u32 join_slots = 4, join_slot_ms = 20000;
static xr_vector<u32> s_join_queue;          // client ids waiting
static xr_map<u32, u32> s_join_started;       // client id -> time it got the world

static bool server_host_ready(xrServer* server)
{
	if (!strstr(Core.Params, "-netcoop"))
		return true;
	xrClientData* host = server->GetServerClient();
	return host && host->net_Accepted && host->owner && g_pGameLevel && Actor() && !netcoop::world_store_cleanup_pending();
}

static u32 joins_in_progress(xrServer* server)
{
	const u32 now = Device.dwTimeGlobal;
	for (auto it = s_join_started.begin(); it != s_join_started.end();)
	{
		ClientID id;
		id.set(it->first);
		xrClientData* CL = static_cast<xrClientData*>(server->ID_to_client(id));
		if (!CL || CL->owner || now < it->second || now - it->second > join_slot_ms) it = s_join_started.erase(it);
		else ++it;
	}
	return u32(s_join_started.size());
}

// xrServer::Update: the next waiting players get the world when slots free up.
void netcoop_join_pump(xrServer* server)
{
	if (!server_host_ready(server))
		return;
	while (!s_join_queue.empty() && joins_in_progress(server) < join_slots)
	{
		ClientID id;
		id.set(s_join_queue.front());
		s_join_queue.erase(s_join_queue.begin());
		xrClientData* CL = static_cast<xrClientData*>(server->ID_to_client(id));
		if (CL && CL->ps && CL->net_ConnectionDataRequested && !CL->net_Accepted)
			server->OnCL_Connected(CL);
	}
}


void xrServer::Perform_connect_spawn(CSE_Abstract* E, xrClientData* CL, NET_Packet& P)
{
	P.B.count = 0;
	xr_vector<u16>::iterator it = std::find(conn_spawned_ids.begin(), conn_spawned_ids.end(), E->ID);
	if (it != conn_spawned_ids.end())
	{
		//.		Msg("Rejecting redundant SPAWN data [%d]", E->ID);
		return;
	}

	conn_spawned_ids.push_back(E->ID);

	if (E->net_Processed) return;
	if (E->s_flags.is(M_SPAWN_OBJECT_PHANTOM)) return;

	//.	Msg("Perform connect spawn [%d][%s]", E->ID, E->s_name.c_str());

	// Connectivity order
	CSE_Abstract* Parent = ID_to_entity(E->ID_Parent);
	if (Parent) Perform_connect_spawn(Parent, CL, P);

	// Process
	Flags16 save = E->s_flags;
	//-------------------------------------------------
	E->s_flags.set(M_SPAWN_UPDATE,TRUE);
	if (0 == E->owner && (!strstr(Core.Params, "-netcoop") || CL == SV_Client))
	{
		// PROCESS NAME; Name this entity
		if (E->s_flags.is(M_SPAWN_OBJECT_ASPLAYER))
		{
			if (CL->owner != E)
				CL->ClearInputState();
			CL->owner = E;
			if (CL->ps) E->set_name_replace(CL->ps->getName()); //netcoop: player state may not exist yet
		}

		// Associate
		E->owner = CL;
		E->Spawn_Write(P,TRUE);
		E->UPDATE_Write(P);

		CSE_ALifeObject* object = smart_cast<CSE_ALifeObject*>(E);
		if (object && !object->keep_saved_data_anyway()) //netcoop: guard non-alife entities
			object->client_data.clear();
	}
	else
	{
		E->Spawn_Write(P, FALSE);
		E->UPDATE_Write(P);
		//		CSE_ALifeObject*	object = smart_cast<CSE_ALifeObject*>(E);
		//		VERIFY				(object);
		//		VERIFY				(object->client_data.empty());
	}
	//-----------------------------------------------------
	E->s_flags = save;
	SendTo(CL->ID, P, net_flags(TRUE,TRUE));
	E->net_Processed = TRUE;
}

void xrServer::SendConfigFinished(ClientID const& clientId)
{
	NET_Packet P;
	P.w_begin(M_SV_CONFIG_FINISHED);
	SendTo(clientId, P, net_flags(TRUE,TRUE));
}

void xrServer::SendConnectionData(IClient* _CL)
{
	conn_spawned_ids.clear();
	xrClientData* CL = (xrClientData*)_CL;
	NET_Packet P;
	// Replicate current entities on to this client
	xrS_entities::iterator I = entities.begin(), E = entities.end();
	for (; I != E; ++I) I->second->net_Processed = FALSE;
	for (I = entities.begin(); I != E; ++I) Perform_connect_spawn(I->second, CL, P);

	SendConfigFinished(CL->ID);

	/*
		Msg("--- Our sended SPAWN IDs:");
		xr_vector<u16>::iterator it = conn_spawned_ids.begin();
		for (; it != conn_spawned_ids.end(); ++it)
		{
			Msg("%d", *it);
		}
		Msg("---- Our sended SPAWN END");
	*/
};

void xrServer::OnCL_Connected(IClient* _CL)
{
	xrClientData* CL = (xrClientData*)_CL;
	if (!CL->ps)
	{
		Msg("[Lost Zone] waiting for player state before connection data for 0x%08x", CL->ID.value());
		return;
	}
	if (strstr(Core.Params, "-netcoop") && CL != GetServerClient())
	{
		if (!server_host_ready(this) || joins_in_progress(this) >= join_slots)
		{
			if (std::find(s_join_queue.begin(), s_join_queue.end(), CL->ID.value()) == s_join_queue.end())
			{
				s_join_queue.push_back(CL->ID.value());
				Msg("[Lost Zone] join queued for 0x%08x (%u waiting)", CL->ID.value(), u32(s_join_queue.size()));
			}
			return;
		}
		s_join_started[CL->ID.value()] = Device.dwTimeGlobal;
	}
	CL->net_Accepted = TRUE;
	if (strstr(Core.Params, "-netcoop"))
	{
		Msg("[Lost Zone] OnCL_Connected 0x%08x pid %u ps=%s", CL->ID.value(), CL->process_id, CL->ps ? "yes" : "no");
		FlushLog();
	}
	///	Server_Client_Check(CL);
	//csPlayers.Enter					();	//sychronized by a parent call
	Export_game_type(CL);
	Perform_game_export();
	CTimer join_timer;
	join_timer.Start();
	SendConnectionData(CL);
	if (strstr(Core.Params, "-netcoop"))
		Msg("[Lost Zone] connection data for 0x%08x: %u of %u objects in %u ms", CL->ID.value(),
		    u32(conn_spawned_ids.size()), u32(entities.size()), join_timer.GetElapsed_ms());

	VERIFY2(CL->ps, "Player state not created");
	if (!CL->ps)
	{
		Msg("! ERROR: Player state not created - incorect message sequence!");
		return;
	}

	game->OnPlayerConnect(CL->ID);
}

void xrServer::SendConnectResult(IClient* CL, u8 res, u8 res1, char* ResultStr)
{
	NET_Packet P;
	P.w_begin(M_CLIENT_CONNECT_RESULT);
	P.w_u8(res);
	P.w_u8(res1);
	P.w_stringZ(ResultStr);
	P.w_clientID(CL->ID);

	if (SV_Client && SV_Client == CL)
		P.w_u8(1);
	else
		P.w_u8(0);
	P.w_stringZ(Level().m_caServerOptions);

	SendTo(CL->ID, P);

	if (strstr(Core.Params, "-netcoop"))
	{
		Msg("[Lost Zone] connect result -> 0x%08x res=%d res1=%d [%s]", CL->ID.value(), int(res), int(res1), ResultStr);
		FlushLog();
	}

	if (!res) //need disconnect 
	{
#ifdef MP_LOGGING
		Msg("* Server disconnecting client, resaon: %s", ResultStr);
#endif
		Flush_Clients_Buffers();
		DisconnectClient(CL, ResultStr);
	}

};

// Client validation on connect (CLevel::net_start_client2): the build
// version, then the access check of Check_BuildVersion_Success.
// WARNING: the M_AUTH_CHALLENGE handler continues this sequence.
void xrServer::Check_ClientVersion(IClient* CL)
{
	if (NeedToCheckClient_BuildVersion(CL))
		return;
	Check_BuildVersion_Success(CL);
};

BOOL g_SV_Disable_Auth_Check = FALSE;

bool xrServer::NeedToCheckClient_BuildVersion(IClient* CL)
{
	/*#ifdef DEBUG
	
		return false; 
	
	#endif*/
	xrClientData* tmp_client = smart_cast<xrClientData*>(CL);
	VERIFY(tmp_client);
	PerformSecretKeysSync(tmp_client);


	if (g_SV_Disable_Auth_Check) return false;
	//netcoop: the single gametype server never calls FS.auth_generate, so a
	//remote client can never satisfy the digest challenge and just waits in
	//Connect2Server until the 60s timeout, which it reports to the user as
	//"different versions". Skip the challenge for out-of-process clients.
	if (strstr(Core.Params, "-netcoop") && CL->process_id != GetCurrentProcessId())
	{
		Msg("[Lost Zone] auth challenge skipped for client 0x%08x (pid %u)", CL->ID.value(), CL->process_id);
		FlushLog();
		return false;
	}
	CL->flags.bVerified = FALSE;
	NET_Packet P;
	P.w_begin(M_AUTH_CHALLENGE);
	SendTo(CL->ID, P);
	return true;
};

void xrServer::OnBuildVersionRespond(IClient* CL, NET_Packet& P)
{
	u16 Type;
	P.r_begin(Type);
	u64 _our = FS.auth_get();
	u64 _him = P.r_u64();

#ifdef USE_DEBUG_AUTH
	Msg("_our = %d", _our);
	Msg("_him = %d", _him);
	_our = MP_DEBUG_AUTH;
#endif // USE_DEBUG_AUTH

	if (_our != _him && !strstr(Core.Params, "-netcoop")) //netcoop: never reject on data checksum
	{
		SendConnectResult(CL, 0, ecr_data_verification_failed, "Data verification failed. Cheater?");
	}
	else
	{
		bool bAccessUser = false;
		string512 res_check;

		if (!CL->flags.bLocal)
		{
			bAccessUser = Check_ServerAccess(CL, res_check);
		}

		if (CL->flags.bLocal || bAccessUser)
		{
			Check_BuildVersion_Success(CL);
		}
		else
		{
			Msg("* Client 0x%08x has an incorrect password", CL->ID.value());
			xr_strcat(res_check, "Invalid password.");
			SendConnectResult(CL, 0, ecr_password_verification_failed, res_check);
		}
	}
};

void xrServer::Check_BuildVersion_Success(IClient* CL)
{
	CL->flags.bVerified = TRUE;
	SendConnectResult(CL, 1, 0, "All Ok");
};
