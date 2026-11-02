#include "stdafx.h"
#include "xrServer.h"
#include "game_sv_single.h"
#include "alife_simulator.h"
#include "xrserver_objects.h"
#include "game_base.h"
#include "game_cl_base.h"
#include "ai_space.h"
#include "alife_object_registry.h"
#include "xrServer_Objects_ALife_Monsters.h"
#include "netcoop.h"
#include "netcoop_corpse_inventory.h"
#include "netcoop_destroy_tree.h"

xr_string xrServer::ent_name_safe(u16 eid)
{
	string1024 buff;
	CSE_Abstract* e_dest = game->get_entity_from_eid(eid);
	if (e_dest)
		xr_sprintf(buff, "[%d][%s:%s]", eid, e_dest->name(), e_dest->name_replace());
	else
		xr_sprintf(buff, "[%d][%s]", eid, "NOTFOUND");

	return buff;
}

void xrServer::Process_event_destroy(NET_Packet& P, ClientID sender, u32 time, u16 ID, NET_Packet* pEPack)
{
	u32 MODE = net_flags(TRUE,TRUE);
	// Parse message
	u16 id_dest = ID;
#ifdef DEBUG
	if( dbg_net_Draw_Flags.test( dbg_destroy ) )
		Msg								("sv destroy object %s [%d]", ent_name_safe(id_dest).c_str(), Device.dwFrame);
#endif

	CSE_Abstract* e_dest = game->get_entity_from_eid(id_dest); // кто должен быть уничтожен
	if (!e_dest)
	{
#ifndef MASTER_GOLD
		Msg							("!SV:ge_destroy: [%d] not found on server",id_dest);
#endif // #ifndef MASTER_GOLD
		return;
	};

	R_ASSERT(e_dest);
	xrClientData* c_dest = e_dest->owner; // клиент, чей юнит
	xrClientData* c_from = ID_to_client(sender); // клиент, кто прислал
	// A client may only destroy its own objects; a forged or stale event must
	// not stop the server (it used to be an assertion).
	if (!netcoop::destroy_authorized(pEPack != nullptr, c_from && c_from->flags.bLocal, c_dest && c_dest == c_from))
	{
		Msg("! [Lost Zone] GE_DESTROY for entity %u rejected: not owned by the sender", id_dest);
		return;
	}
	// Validate the graph before releasing any object or emitting a partial pack.
    if (!pEPack && !netcoop::destroy_tree_valid(id_dest,
        [&](unsigned id) -> const xr_vector<u16>* {
            const auto* object=game->get_entity_from_eid(u16(id));
            return object ? &object->children:nullptr;
        },
        [&](unsigned parent,unsigned child) {
            const auto* object=game->get_entity_from_eid(u16(child));
            return object && object->ID_Parent==parent;
        })) {
        Msg("! [diag][destroy] root=%u retained: invalid child graph",id_dest);return;
    }
    u16 parent_id = e_dest->ID_Parent;

#ifdef MP_LOGGING
	Msg("--- SV: Process destroy: parent [%d] item [%d][%s]", 
		parent_id, id_dest, e_dest->name());
#endif //#ifdef MP_LOGGING

	//---------------------------------------------
	NET_Packet P2, *pEventPack = pEPack;
	P2.w_begin(M_EVENT_PACK);
	//---------------------------------------------
	// Body cleanup must not recursively destroy its loot. Actors retain their
	// separate death/disconnect path; this rule is for finite NPC/mutant bodies.
	const auto creature = smart_cast<CSE_ALifeCreatureAbstract*>(e_dest);
	if (netcoop::enabled() && netcoop::corpse_loot_drops() && creature && creature->get_health() <= 0.f &&
		!smart_cast<CSE_ALifeCreatureActor*>(e_dest) && !e_dest->children.empty())
	{
		if (!ai().get_alife()) return;
		const bool preserved = netcoop::preserve_corpse_inventory(e_dest->children,
			[&](u16 child_id)
			{
				auto child = game->get_entity_from_eid(child_id);
				return child && child->ID_Parent == id_dest &&
					smart_cast<CSE_ALifeInventoryItem*>(child) &&
					ai().alife().objects().object(child_id, true);
			},
			[&](u16 child_id)
			{
				// Use the ordinary detach path to update both ALife registries
				// and client inventory/physics before the body's destroy event.
				NET_Packet drop;
				// Match the destroy timestamp. A newer generated timestamp can
				// make a client's ordered event queue destroy the parent first.
				drop.w_begin(M_EVENT);
				drop.w_u32(time);
				drop.w_u16(GE_OWNERSHIP_REJECT);
				drop.w_u16(id_dest);
				drop.w_u16(child_id);
				return Process_event_reject(drop, sender, time, id_dest, child_id, true);
			});
		if (!preserved)
		{
			Msg("! [Lost Zone] Body %u retained: inventory detach is incomplete", id_dest);
			return;
		}
	}
	// check if we have children 
	if (!e_dest->children.empty())
	{
		if (!pEventPack) pEventPack = &P2;

		if (!netcoop::destroy_children(e_dest->children,[&](u16 child) {
            Process_event_destroy(P,sender,time,child,pEventPack);
        })) {
            Msg("! [diag][destroy] root=%u retained: child destroy made no progress",id_dest);
            if (!pEPack && pEventPack->B.count>sizeof(u16)) SendBroadcast(BroadcastCID,*pEventPack,MODE);
            return;
        }
	};

	if (0xffff == parent_id && NULL == pEventPack)
	{
		SendBroadcast(BroadcastCID, P, MODE);
	}
	else
	{
		NET_Packet tmpP;
		if (0xffff != parent_id && Process_event_reject(P, sender, time, parent_id, ID, false))
		{
			// A packed child detach must have the same time as its parent's
			// destroy. Generating "now" sorts it AFTER an older destroy event.
			tmpP.w_begin(M_EVENT); tmpP.w_u32(time);
			tmpP.w_u16(GE_OWNERSHIP_REJECT); tmpP.w_u16(parent_id);
			tmpP.w_u16(id_dest);
			tmpP.w_u8(1);

			if (!pEventPack) pEventPack = &P2;

			pEventPack->w_u8(u8(tmpP.B.count));
			pEventPack->w(&tmpP.B.data, tmpP.B.count);
		};

		tmpP.w_begin(M_EVENT); tmpP.w_u32(time);
		tmpP.w_u16(GE_DESTROY); tmpP.w_u16(id_dest);

		pEventPack->w_u8(u8(tmpP.B.count));
		pEventPack->w(&tmpP.B.data, tmpP.B.count);
	};

	if (NULL == pEPack && NULL != pEventPack)
	{
		SendBroadcast(BroadcastCID, *pEventPack, MODE);
	}

	// Everything OK, so perform entity-destroy
	if (e_dest->m_bALifeControl && ai().get_alife())
	{
		game_sv_Single* _game = smart_cast<game_sv_Single*>(game);
		VERIFY(_game);
		if (ai().alife().objects().object(id_dest, true))
			_game->alife().release(e_dest, false);
	}

	if (game)
		game->OnDestroyObject(e_dest->ID);

	entity_Destroy(e_dest);
}
