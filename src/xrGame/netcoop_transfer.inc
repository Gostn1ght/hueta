// Atomic inventory transfers (gameplay plan, stage 2).
//
// Before: moving an item between a player and a corpse or a box was two
// independent client events, GE_TRADE_SELL from the source and GE_TRADE_BUY
// into the target. When the second was refused (full inventory, the player
// died, another player took the item between them) the item was left on the
// ground without a physics shell, and nothing told the player why.
//
// Now the client sends one request (M_NETCOOP_TRANSFER: u32 txid, u16 item,
// u16 from, u16 to). The server validates everything first, then performs
// both steps in the same frame and checks the result; a failed take returns
// the item to its source. Every request gets one answer
// (M_NETCOOP_TRANSFER_RESULT: u32 txid, u8 ok, stringZ reason). A repeated
// txid (resend, double delivery) gets the stored answer and is not executed
// twice.

static const float transfer_reach = 4.f;
static const u32 transfer_remembered = 128;

struct TransferAnswer { u32 txid; bool ok; shared_str reason; };
static xr_map<u32, xr_deque<TransferAnswer>> s_transfer_answers; // ClientID -> recent answers

enum ETransferEnd
{
	transfer_end_none,
	transfer_end_self, // the requesting player's own Actor
	transfer_end_corpse, // a dead NPC or player within reach
	transfer_end_box, // an inventory box (stash, container) within reach
};

static LPCSTR transfer_end_name(ETransferEnd end)
{
	switch (end)
	{
	case transfer_end_self: return "self";
	case transfer_end_corpse: return "corpse";
	case transfer_end_box: return "box";
	default: return "invalid";
	}
}

static ETransferEnd transfer_end(xrServer* server, xrClientData* CL, u16 id, CActor* actor)
{
	if (CL->owner && id == CL->owner->ID) return actor && actor->g_Alive() ? transfer_end_self : transfer_end_none;
	CSE_Abstract* entity = server->game->get_entity_from_eid(id);
	if (!entity) return transfer_end_none;
	if (accessible_corpse(CL, entity)) return transfer_end_corpse;
	CInventoryBox* box = smart_cast<CInventoryBox*>(Level().Objects.net_Find(id));
	// Player-made stashes and storage furniture open only for their owner
	// and the players on its access list (netcoop_server_compat.can_access).
	if (box && actor && !box->closed() && server_object_access(id, CL) &&
		(actor->Position().distance_to(box->Position()) <= transfer_reach || box_anchor_within_reach(id, actor->Position())))
		return transfer_end_box;
	return transfer_end_none;
}

static void send_transfer_result(xrServer* server, xrClientData* CL, u32 txid, bool ok, LPCSTR reason)
{
	NET_Packet P;
	P.w_begin(M_NETCOOP_TRANSFER_RESULT);
	P.w_u32(txid); P.w_u8(ok ? 1 : 0); P.w_stringZ(reason);
	server->SendTo(CL->ID, P, net_flags(TRUE, TRUE));
}

// One server-side ownership step, processed as if the server's own client
// had sent it (the same path and broadcast as a client event).
static void transfer_step(xrServer* server, u16 type, u16 holder, u16 item)
{
	NET_Packet P;
	CGameObject::u_EventGen(P, type, holder);
	P.w_u16(item);
	const ClientID self = server->GetServerClient()->ID;
	if (type == GE_TRADE_SELL)
		server->Process_event_reject(P, self, Level().timeServer(), holder, item);
	else
	{
		P.r_pos = 10; // M_EVENT u16, time u32, type u16, destination u16
		server->Process_event_ownership(P, self, Level().timeServer(), holder);
	}
}

void server_on_transfer(xrServer* server, xrClientData* CL, NET_Packet& P)
{
	if (!enabled() || !CL || !CL->owner || !g_pGameLevel || !server->GetServerClient()) return;
	if (P.r_elapsed() != 4 + 2 + 2 + 2) return;
	const u32 txid = P.r_u32();
	const u16 item_id = P.r_u16(), from = P.r_u16(), to = P.r_u16();

	xr_deque<TransferAnswer>& answers = s_transfer_answers[CL->ID.value()];
	for (const TransferAnswer& answer : answers)
		if (answer.txid == txid)
		{
			Msg("[NetAnomaly][inv] tx=%08x player=%s duplicate request, answered again: %s", txid, CL->netcoop_login.c_str(),
				answer.ok ? "ok" : answer.reason.c_str());
			send_transfer_result(server, CL, txid, answer.ok, answer.reason.c_str());
			return;
		}

	CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(CL->owner->ID));
	CSE_Abstract* item = server->game->get_entity_from_eid(item_id);
	const ETransferEnd source = transfer_end(server, CL, from, actor);
	const ETransferEnd target = transfer_end(server, CL, to, actor);
	LPCSTR failure = nullptr;
	if (!actor || !actor->g_Alive()) failure = "player is dead";
	else if (!item || !smart_cast<CInventoryItem*>(Level().Objects.net_Find(item_id))) failure = "item does not exist";
	else if (item->ID_Parent != from) failure = "item is no longer there"; // the lock: someone else moved it first
	else if (from == to) failure = "same place";
	else if (source == transfer_end_none) failure = "source is out of reach";
	else if (target == transfer_end_none) failure = "target is out of reach";
	else if (source != transfer_end_self && target != transfer_end_self) failure = "player is not part of the transfer";
	else if (target == transfer_end_self) failure = server_inventory_take_failure(server, to, item_id);

	bool ok = false;
	if (!failure)
	{
		// Latest owner-reported state travels with the item (stage 1 record).
		transfer_step(server, GE_TRADE_SELL, from, item_id);
		transfer_step(server, GE_TRADE_BUY, to, item_id);
		ok = item->ID_Parent == to;
		if (!ok)
		{
			// Roll back: the item must never stay on the ground in between.
			if (item->ID_Parent == 0xffff) transfer_step(server, GE_TRADE_BUY, from, item_id);
			failure = item->ID_Parent == from ? "target refused the item, returned" : "target refused the item, rollback failed";
		}
	}

	auto record = s_item_records.find(item_id);
	Msg("%s[NetAnomaly][inv] tx=%08x player=%s item=%u %s uid=%llu v=%u from=%u(%s) to=%u(%s) %s%s", ok ? "" : "! ", txid,
		CL->netcoop_login.c_str(), item_id, item ? item->s_name.c_str() : "?", record != s_item_records.end() ? record->second.sent.uid : 0,
		record != s_item_records.end() ? record->second.version : 0, from, transfer_end_name(source), to, transfer_end_name(target),
		ok ? "ok" : "failed: ", ok ? "" : failure);

	// A player's backpack stash that was emptied turns back into its item.
	if (ok && source == transfer_end_box)
	{
		::luabind::functor<void> changed;
		if (ai().script_engine().functor("netcoop_server_compat.on_box_changed", changed))
		{
			ServerVictimScope scope(actor);
			try { changed(int(from), int(CL->owner->ID)); }
			catch (...) { Msg("! [NetAnomaly][inv] box %u change script failed", from); }
		}
	}

	TransferAnswer answer; answer.txid = txid; answer.ok = ok; answer.reason = ok ? "" : failure;
	answers.push_back(answer);
	while (answers.size() > transfer_remembered) answers.pop_front();
	send_transfer_result(server, CL, txid, ok, ok ? "" : failure);
}

// ---- client -------------------------------------------------------------------
static u32 s_transfer_pending = 0;

void client_session_reset()
{
	s_transfer_pending = 0;
	s_trade_refresh = false;
}

bool client_transfer(u16 from, u16 to, u16 item)
{
	if (!pure_client()) return false;
	// The server moves the item with the state this client last reported.
	client_items_update(true);
	NET_Packet P;
	P.w_begin(M_NETCOOP_TRANSFER);
	P.w_u32(client_next_txid());
	P.w_u16(item); P.w_u16(from); P.w_u16(to);
	Level().Send(P, net_flags(TRUE, TRUE));
	++s_transfer_pending;
	return true;
}

void client_on_transfer_result(NET_Packet& P)
{
	if (P.r_elapsed() < 6) return;
	const u32 txid = P.r_u32();
	const bool ok = P.r_u8() != 0;
	string256 reason;
	if (!read_string(P, reason, sizeof(reason))) reason[0] = 0;
	if (s_transfer_pending) --s_transfer_pending;
	if (ok) return;
	Msg("! [NetAnomaly][inv] transfer %08x refused: %s", txid, reason);
	// The inventory windows rebuild from the server's events; tell the player why.
	string512 text;
	xr_sprintf(text, "Transfer refused: %s", reason);
	client_on_server_text(text);
}
