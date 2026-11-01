// Included in netcoop.cpp (namespace netcoop) - server: validation of client game events.
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// server: event validation
// ---------------------------------------------------------------------------
static bool living_npc(CSE_Abstract* entity)
{
	if (!entity || smart_cast<CSE_ALifeCreatureActor*>(entity))
		return false;
	CSE_ALifeCreatureAbstract* creature = smart_cast<CSE_ALifeCreatureAbstract*>(entity);
	return creature && creature->g_Alive();
}

static bool accessible_corpse(xrClientData* CL, CSE_Abstract* entity)
{
	if (!CL || !CL->owner || !entity) return false;
	CEntityAlive* body = smart_cast<CEntityAlive*>(Level().Objects.net_Find(entity->ID));
	CEntityAlive* actor = smart_cast<CEntityAlive*>(Level().Objects.net_Find(CL->owner->ID));
	CInventoryOwner* inventory = smart_cast<CInventoryOwner*>(body);
	::luabind::functor<bool> reserved;
	if(body && ai().script_engine().functor("netcoop_survival.protected_body",reserved)) {
		try {if(reserved(int(entity->ID)))return false;}catch(...){return false;}
	}
	return body && !body->g_Alive() && actor && actor->g_Alive() && inventory &&
		!inventory->deadbody_closed_status() && actor->Position().distance_to(body->Position()) <= 3.f;
}

bool server_inventory_pickup_allowed(xrServer* server,ClientID sender,u16 owner_id,u16 item_id)
{
	LPCSTR failure=server_inventory_take_failure(server,owner_id,item_id);
	if (!failure) return true;
	static xr_map<u32,u32> told;
	const u32 now=Device.dwTimeGlobal;
	u32& last=told[sender.value()];
	if (!last || now-last>=2000)
	{
		last=now;
		Msg("! [NetAnomaly][inv] pickup of %u by %u refused: %s",item_id,owner_id,failure);
		NET_Packet reply;
		reply.w_begin(M_NETANOMALY_MSG);
		reply.w_stringZ(make_string("! Pickup refused: %s",failure).c_str());
		server->SendTo(sender,reply,net_flags(TRUE,TRUE));
	}
	return false;
}

// A player's own landing (CActor::g_Physics, owner 2026-10-17: no damage
// jumping out of a helicopter). Movement is the owner's, so only the owner's
// client sees the ground contact; it sends a strike hit on its own actor by
// itself. Only that is accepted: the sender's actor, from and with itself,
// a strike of bounded power, at most one per 250 ms. It can only hurt the
// sender.
static bool remote_fall_hit_allowed(xrClientData* CL, NET_Packet& P, u16 type, u16 destination)
{
	if (type != GE_HIT || !CL->owner || destination != CL->owner->ID)
		return false;
	// who, weapon, dir, power, bone, position, impulse, [aim], type
	const u32 needed = 2 + 2 + 2 + 4 + 2 + 12 + 4 + (IsGameTypeSingle() ? 2 : 0) + 2;
	if (P.r_elapsed() < needed)
		return false;
	const u32 pos = P.r_pos;
	u16 who = 0, weapon = 0, bone = 0;
	Fvector dir, in_bone;
	float power = 0.f, impulse = 0.f;
	P.r_u16(who);
	P.r_u16(weapon);
	P.r_dir(dir);
	P.r_float(power);
	P.r_u16(bone);
	P.r_vec3(in_bone);
	P.r_float(impulse);
	if (IsGameTypeSingle())
		P.r_u16();
	const u16 hit_type = P.r_u16();
	P.r_pos = pos;
	if (who != destination || weapon != destination || hit_type != ALife::eHitTypeStrike)
		return false;
	if (!_valid(power) || power < 0.f || power > 2.f || !_valid(impulse) || _abs(impulse) > 1000.f)
		return false;
	static xr_map<u32, u32> last;
	const u32 now = Device.dwTimeGlobal;
	u32& previous = last[CL->ID.value()];
	if (previous && now - previous < 250)
		return false;
	previous = now;
	return true;
}

static bool remote_hud_state_allowed(xrServer* server, xrClientData* CL, NET_Packet& P, u16 destination)
{
	CSE_Abstract* item = server->game->get_entity_from_eid(destination);
	if (!item || !CL->owner || item->ID_Parent != CL->owner->ID) return false;
	// Weapons consume five bytes; other HUD items consume one. Reject a
	// truncated packet before the persistent entity or runtime reads it.
	const u32 bytes = smart_cast<CSE_ALifeItemWeapon*>(item) ? 5 : 1;
	if (P.r_elapsed() != bytes) return false;
	if (bytes == 1) return true;
	CWeapon* weapon = smart_cast<CWeapon*>(Level().Objects.net_Find(destination));
	if (!weapon) return false;
	const u32 pos = P.r_pos;
	P.r_u8(); // state
	P.r_u8(); // substate
	const u8 ammo_type = P.r_u8();
	const u8 count = P.r_u8();
	const u8 next_ammo = P.r_u8();
	P.r_pos = pos;
	const auto types = weapon->m_ammoTypes.size();
	// Empty-ammo weapons (knife/binoculars) cannot allocate cartridges;
	// invalid next-ammo indexes otherwise crash when reload starts.
	// Match item reports: a loaded chamber may add one round to the magazine.
	const u32 capacity = u32(weapon->GetAmmoMagSize()) + (types ? 1 : 0);
	return count <= capacity && (!count || types > 0) &&
		(types ? ammo_type < types : ammo_type == 0) &&
		(next_ammo == u8(-1) || next_ammo < types);
}

bool server_remote_event_allowed(xrServer* server, xrClientData* CL, NET_Packet& P, u16 type, u16 destination)
{
	if (!enabled() || !CL || CL->flags.bLocal)
		return true;
	if (CL->owner && (type == GE_WPN_STATE_CHANGE || type == GE_NETCOOP_WPN_AIM || type == GEG_PLAYER_ACTIVATE_SLOT))
		if (CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(CL->owner->ID)))
			if (actor->netcoop_seated()) return false;

	switch (type)
	{
	case GE_WPN_STATE_CHANGE:
		return remote_hud_state_allowed(server, CL, P, destination);
	case GE_MONEY:
		return false; // money changes only on the server

	// Damage, deaths, kills, game events, teleports, visuals, restrictions
	// and frozen physics are the server's (doc 43 A11): a player's bullets are
	// simulated on the server and the client's are visual only, so an honest
	// client never sends these. A forged GE_HIT killed any NPC, GE_GAME_EVENT
	// carried GAME_EVENT_ON_HIT past that, GE_DIE/GE_ASSIGN_KILLER named any
	// killer (run-cheat-test.ps1).
	case GE_HIT:
		return remote_fall_hit_allowed(CL, P, type, destination);
	case GE_GRENADE_EXPLODE:
	case GE_LAUNCH_ROCKET:
	case GE_DIE:
	case GE_ASSIGN_KILLER:
	case GE_GAME_EVENT:
	case GE_TELEPORT_OBJECT:
	case GE_CHANGE_VISUAL:
	case GE_FREEZE_OBJECT:
	case GE_ADD_RESTRICTION:
	case GE_REMOVE_RESTRICTION:
	case GE_REMOVE_ALL_RESTRICTIONS:
		return false;

	case GE_TRANSFER_AMMO:
		{
			// The handler asserts that the taker belongs to the sender: a
			// forged one took the whole server down.
			CSE_Abstract* dest = server->game->get_entity_from_eid(destination);
			return dest && dest->owner == CL;
		}

	// Upgrades are installed by the server (workshop, netcoop_workshop); a
	// client cannot install one (no ALife) and a forged event wrote a free
	// upgrade into the item.
	case GE_INSTALL_UPGRADE:
		return false;

	case GE_DESTROY:
	case GE_ADDON_ATTACH:
	case GE_ADDON_DETACH:
		{
			// Only an item the sender's own Actor carries.
			CSE_Abstract* item = server->game->get_entity_from_eid(destination);
			return item && CL->owner && item->ID_Parent == CL->owner->ID;
		}

	case GE_INFO_TRANSFER:
	case GE_TRADER_FLAGS:
		{
			// Only to the sender's own Actor (never another player or an NPC);
			// trader flags carry the player's night vision state.
			CSE_Abstract* dest = server->game->get_entity_from_eid(destination);
			return dest && dest == CL->owner;
		}

	case GE_CHANGE_POS:
		{
			// A script dropping an item at a spot (DropItemAndTeleport): only
			// the sender's own or just dropped item, next to the sender.
			CSE_Abstract* item = server->game->get_entity_from_eid(destination);
			CObject* actor = CL->owner ? Level().Objects.net_Find(CL->owner->ID) : NULL;
			if (!item || !actor || P.r_elapsed() < sizeof(Fvector))
				return false;
			if (item->ID_Parent != 0xffff && item->ID_Parent != CL->owner->ID)
				return false;
			const u32 pos = P.r_pos;
			Fvector target;
			P.r_vec3(target);
			P.r_pos = pos;
			const Fvector& from = item->ID_Parent == 0xffff ? item->o_Position : actor->Position();
			return _valid(target) && actor->Position().distance_to(target) <= 5.f && actor->Position().distance_to(from) <= 5.f;
		}

	case GEG_PLAYER_ITEM_EAT:
	case GEG_PLAYER_ITEM2SLOT:
	case GEG_PLAYER_ITEM2BELT:
	case GEG_PLAYER_ITEM2RUCK:
	case GEG_PLAYER_ACTIVATEARTEFACT:
	case GEG_PLAYER_ACTIVATE_SLOT:
		{
			// Players use and arrange items only in their own inventory.
			CSE_Abstract* dest = server->game->get_entity_from_eid(destination);
			return dest && dest == CL->owner;
		}

	case GE_NETCOOP_RP:
		{
			// Only for the sender's own Actor.
			CSE_Abstract* dest = server->game->get_entity_from_eid(destination);
			return dest && dest == CL->owner;
		}

	case GE_NETCOOP_ITEM_STATE:
	case GE_NETCOOP_WPN_AIM:
		{
			// Only for an item the sender's own Actor holds.
			CSE_Abstract* weapon = server->game->get_entity_from_eid(destination);
			return weapon && CL->owner && weapon->ID_Parent == CL->owner->ID;
		}

	case GE_TRADE_BUY:
	case GE_TRADE_SELL:
	case GE_OWNERSHIP_TAKE:
	case GE_OWNERSHIP_REJECT:
		{
			CSE_Abstract* dest = server->game->get_entity_from_eid(destination);
			if (!dest)
				return true; // the normal handler reports it

			if (smart_cast<CSE_ALifeCreatureActor*>(dest) && dest != CL->owner && !accessible_corpse(CL, dest))
				return false; // another player's inventory
			if (living_npc(dest))
				return false; // living NPC inventories change through server trade

			if (P.r_elapsed() >= sizeof(u16))
			{
				const u32 pos = P.r_pos;
				const u16 item_id = P.r_u16();
				P.r_pos = pos;
				CSE_Abstract* item = server->game->get_entity_from_eid(item_id);
				CSE_Abstract* holder = item && item->ID_Parent != 0xffff
					? server->game->get_entity_from_eid(item->ID_Parent)
					: NULL;
				if (holder && holder != dest)
				{
					if (smart_cast<CSE_ALifeCreatureActor*>(holder) && holder != CL->owner && !accessible_corpse(CL, holder))
						return false;
					if (living_npc(holder))
						return false;
				}
				// Owned boxes (player stashes, storage furniture) also through raw events.
				if (smart_cast<CInventoryBox*>(Level().Objects.net_Find(destination)) && !server_object_access(destination, CL))
					return false;
				if (holder && smart_cast<CInventoryBox*>(Level().Objects.net_Find(holder->ID)) && !server_object_access(holder->ID, CL))
					return false;
				// Picking up from the ground: only what lies within reach of the
				// player's Actor on the server (stage 2 validation).
				if (item && !holder && dest == CL->owner && type == GE_OWNERSHIP_TAKE)
				{
					CObject* actor = Level().Objects.net_Find(CL->owner->ID);
					CObject* thing = Level().Objects.net_Find(item_id);
					const float distance = actor && thing ? actor->Position().distance_to(thing->Position()) : 0.f;
					if (distance > 6.f)
					{
						Msg("! [NetAnomaly][inv] player=%s pickup of %u refused: %.1f m away", CL->netcoop_login.c_str(), item_id, distance);
						return false;
					}
				}
			}
			return true;
		}
	default:
		return true;
	}
}

#include "netcoop_transfer.inc"
