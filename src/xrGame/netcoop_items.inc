// Authoritative item instance state (gameplay plan, stage 1).
//
// Before: an item's condition (durability or device charge), portions left,
// magazine and box count were set on each client once, at spawn, and never
// again. A drained PDA dropped by one player was full for the next one;
// a drink used on the server kept all its portions on the client.
//
// Now the server keeps one record per item instance (object ID): a persistent
// uid, a version and the state last sent. Every 50 ms it compares a budgeted
// slice of world items with their records and sends the changed fields:
// - items carried by a player (private) go to that player only;
// - everything else (ground, NPCs, corpses, traders, stashes) goes to all;
// - a change of owner sends a full snapshot to the new recipients;
// - a joining client receives full snapshots of all items, in slices.
// The carrier's client simulates wear, drain and its own shots; it reports
// them (M_NETCOOP_ITEM_REPORT) and the server validates and stores them.
// Portions are used on the server (GEG_PLAYER_ITEM_EAT) and replicated back.

static const u32 item_scan_period_ms = 50;
static const u32 item_scan_budget = 2048; // objects examined per scan
static const u32 item_resync_budget = 384; // snapshots per joining client per scan
static const u32 item_min_send_ms = 100; // one delta per item per 100 ms at most
static const u32 item_held_send_ms = 500; // public items held in an inventory
static const u32 item_packet_limit = 8192;

struct ItemRecord
{
	u32 incarnation = 0; // a reused object ID starts a new incarnation
	u16 version = 0;
	u16 owner = 0xffff; // player Actor carrying it, 0xffff = everyone
	u32 forced_until = 0; // server-authored change: predicted fields go to the owner too, briefly
	u32 last_send = 0;
	item_state::State sent;
};
static xr_map<u16, ItemRecord> s_item_records;
static u32 s_item_incarnation = 0;
static u32 s_item_uid_counter = 0;
static u64 s_item_uid_base = 0;
static u32 s_item_cursor = 0;
// Saved state of a character's items, applied when they appear on the server.
static xr_map<u16, item_state::State> s_item_restore;
// Items that went offline (ALife keeps their server entity and ID): the
// instance keeps its uid when it comes back online.
struct ItemOffline { u64 uid; shared_str section; };
static xr_map<u16, ItemOffline> s_item_offline;
struct ItemResync { u16 actor; u32 next; };
static xr_map<u32, ItemResync> s_item_resync; // ClientID -> next record key
static u32 s_item_log_budget = 0, s_item_log_window = 0;

static bool item_log_allowed()
{
	const u32 now = real_time_ms();
	if (now - s_item_log_window > 10000) { s_item_log_window = now; s_item_log_budget = 0; }
	return ++s_item_log_budget <= 60;
}

static u64 item_new_uid()
{
	// A random 40-bit run prefix: uids from different server runs never meet.
	while (!s_item_uid_base)
	{
		u8 bytes[5] = {};
		if (!random_bytes(bytes, sizeof(bytes))) bytes[0] = u8(real_time_ms() | 1);
		for (u8 b : bytes) s_item_uid_base = (s_item_uid_base << 8) | b;
		s_item_uid_base <<= 24;
	}
	return s_item_uid_base + (++s_item_uid_counter & 0xffffff);
}

static bool item_capture(CObject* object, item_state::State& s)
{
	CInventoryItem* item = smart_cast<CInventoryItem*>(object);
	if (!item) return false;
	s.condition = item_state::quantize(item->GetCondition());
	if (CEatableItem* eatable = smart_cast<CEatableItem*>(object))
	{ s.has_uses = true; s.uses = eatable->GetRemainingUses(); s.max_uses = eatable->GetMaxUses(); }
	if (CWeapon* weapon = smart_cast<CWeapon*>(object))
	{
		s.weapon = true; s.ammo_type = weapon->GetAmmoType(); s.addons = weapon->GetAddonsState();
		const auto& magazine = weapon->GetMagazine();
		item_state::set_magazine(s, u32(magazine.size()), [&magazine](u32 i) { return magazine[i].m_LocalAmmoType; });
	}
	if (CWeaponAmmo* ammo = smart_cast<CWeaponAmmo*>(object)) { s.stack = true; s.stack_count = ammo->m_boxCurr; }
	return true;
}

// Applies the masked fields to the object (server restore or client replica).
static void item_apply(CObject* object, const item_state::State& s, u16 mask)
{
	CInventoryItem* item = smart_cast<CInventoryItem*>(object);
	if (!item) return;
	if (mask & item_state::f_condition) item->SetCondition(item_state::dequantize(s.condition));
	if (mask & item_state::f_uses)
		if (CEatableItem* eatable = smart_cast<CEatableItem*>(object))
			if (s.has_uses) eatable->SetRemainingUses(s.uses);
	if (CWeapon* weapon = smart_cast<CWeapon*>(object))
	{
		if ((mask & item_state::f_ammo) && s.weapon) weapon->netcoop_set_magazine(s.ammo_type, s.run_type, s.run_count, s.runs);
		if ((mask & item_state::f_addons) && s.weapon) weapon->netcoop_set_addons(s.addons);
	}
	if (mask & item_state::f_stack)
		if (CWeaponAmmo* ammo = smart_cast<CWeaponAmmo*>(object))
			if (s.stack) ammo->m_boxCurr = _min(s.stack_count, ammo->m_boxSize);
}

// Wire entry: u16 id, u32 incarnation, u16 version, u16 mask (f_full = snapshot), fields.
static void item_write_entry(NET_Packet& P, u16 id, const ItemRecord& record, u16 mask)
{
	P.w_u16(id); P.w_u32(record.incarnation); P.w_u16(record.version); P.w_u16(mask);
	item_state::write(P, record.sent, mask & item_state::f_all);
}

struct ItemOutbox
{
	NET_Packet packet;
	u32 count_pos = 0;
	u16 count = 0;
	bool open = false;
};

static void item_outbox_add(ItemOutbox& box, u16 id, const ItemRecord& record, u16 mask)
{
	if (!box.open)
	{
		box.packet.w_begin(M_NETCOOP_ITEM_STATE);
		box.count_pos = box.packet.w_tell(); box.packet.w_u16(0);
		box.count = 0; box.open = true;
	}
	item_write_entry(box.packet, id, record, mask);
	++box.count;
}

static void item_outbox_send(xrServer* server, ItemOutbox& box, xrClientData* only)
{
	if (!box.open || !box.count) { box.open = false; return; }
	box.packet.w_seek(box.count_pos, &box.count, sizeof(box.count));
	struct Send
	{
		xrServer* server; NET_Packet* packet; xrClientData* only;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (CL == server->GetServerClient() || !CL->flags.bConnected || !CL->gamma_snapshot_ready || !CL->owner) return;
			if (only && CL != only) return;
			server->SendTo(CL->ID, *packet, net_flags(TRUE, TRUE));
		}
	} send = {server, &box.packet, only};
	server->ForEachClientDo(send);
	box.open = false;
}

static u16 item_root(xrServer* server, u16 id)
{
	CSE_Abstract* entity = server->game->get_entity_from_eid(id);
	for (u32 depth = 0; entity && entity->ID_Parent != 0xffff && depth < 16; ++depth)
	{
		CSE_Abstract* parent = server->game->get_entity_from_eid(entity->ID_Parent);
		if (!parent) break;
		entity = parent;
	}
	return entity ? entity->ID : 0xffff;
}

struct ItemPlayers
{
	xr_map<u16, xrClientData*> by_actor;
	void collect(xrServer* server)
	{
		by_actor.clear();
		struct Collect
		{
			xrServer* server; xr_map<u16, xrClientData*>* out;
			void operator()(IClient* client)
			{
				xrClientData* CL = static_cast<xrClientData*>(client);
				if (CL == server->GetServerClient() || !CL->owner) return;
				// A dead player's body is a corpse: its items are everyone's to loot.
				CEntityAlive* actor = smart_cast<CEntityAlive*>(Level().Objects.net_Find(CL->owner->ID));
				if (!actor || !actor->g_Alive()) return;
				(*out)[CL->owner->ID] = CL;
			}
		} collect = {server, &by_actor};
		server->ForEachClientDo(collect);
	}
	xrClientData* client_of(u16 actor) const
	{
		auto it = by_actor.find(actor);
		return it == by_actor.end() ? nullptr : it->second;
	}
};

static LPCSTR item_owner_name(const ItemPlayers& players, u16 owner)
{
	if (owner == 0xffff) return "world";
	xrClientData* CL = players.client_of(owner);
	return CL && CL->netcoop_login.size() ? CL->netcoop_login.c_str() : "player";
}

// Server: a record for an object seen for the first time (or after its ID
// was reused). Restored character items get their saved uid and state.
static ItemRecord& item_record_create(CObject* object, const item_state::State& captured, u16 owner, bool& restored)
{
	ItemRecord& record = s_item_records[object->ID()];
	record = ItemRecord();
	record.incarnation = ++s_item_incarnation;
	record.version = 1;
	record.owner = owner;
	record.sent = captured;
	record.sent.uid = item_new_uid();
	restored = false;
	auto offline = s_item_offline.find(object->ID());
	if (offline != s_item_offline.end())
	{
		if (offline->second.section == object->cNameSect()) record.sent.uid = offline->second.uid;
		s_item_offline.erase(offline);
	}
	auto saved = s_item_restore.find(object->ID());
	if (saved != s_item_restore.end())
	{
		// The spawn packet restored condition and the magazine size; the
		// saved record adds the uid, portions and the cartridge sequence.
		const u16 mask = item_state::applicable(captured) & item_state::applicable(saved->second);
		item_apply(object, saved->second, u16(mask & ~item_state::f_uid));
		item_capture(object, record.sent);
		record.sent.uid = saved->second.uid ? saved->second.uid : record.sent.uid;
		s_item_restore.erase(saved);
		restored = true;
	}
	return record;
}

static bool item_pristine(const item_state::State& s)
{
	return s.condition == 65535 && (!s.has_uses || s.uses == s.max_uses) && !s.weapon && !s.stack;
}

void server_items_update(xrServer* server)
{
	if (!g_pGameLevel || pure_client() || !server) return;
	static u32 previous = 0;
	const u32 now = real_time_ms();
	if (previous && now - previous < item_scan_period_ms) return;
	previous = now;

	ItemPlayers players;
	players.collect(server);
	ItemOutbox to_all;
	xr_map<u16, ItemOutbox> to_owner;
	auto queue = [&](u16 owner, u16 id, const ItemRecord& record, u16 mask)
	{
		if (owner == 0xffff) item_outbox_add(to_all, id, record, mask);
		else if (players.client_of(owner)) item_outbox_add(to_owner[owner], id, record, mask);
		if (to_all.open && to_all.packet.B.count > item_packet_limit) item_outbox_send(server, to_all, nullptr);
		auto box = to_owner.find(owner);
		if (box != to_owner.end() && box->second.open && box->second.packet.B.count > item_packet_limit)
			item_outbox_send(server, box->second, players.client_of(owner));
	};

	// Characters that gave or got an item this scan: saved at once. Saves
	// run every 20 s otherwise, and a crash between the giver's and the
	// taker's save left the item in both files (duplication).
	xr_vector<u16> save_actors;
	const u32 count = Level().Objects.o_count();
	const u32 budget = _min(count, item_scan_budget);
	for (u32 step = 0; step < budget; ++step)
	{
		if (s_item_cursor >= count) s_item_cursor = 0;
		CObject* object = Level().Objects.o_get_by_iterator(s_item_cursor++);
		if (!object || object->getDestroy() || !smart_cast<CInventoryItem*>(object)) continue;
		item_state::State current;
		if (!item_capture(object, current)) continue;
		const u16 root = item_root(server, object->ID());
		const u16 owner = players.client_of(root) ? root : 0xffff;
		const u16 id = object->ID();
		auto found = s_item_records.find(id);
		if (found == s_item_records.end())
		{
			bool restored = false;
			ItemRecord& record = item_record_create(object, current, owner, restored);
			record.last_send = now;
			// The client spawned it from the spawn packet; scripts that changed
			// it right after (NPC loot condition, partial portions) need a snapshot.
			// Items appearing in a player's inventory always get one: the
			// client reports only items it has a server snapshot of.
			if (restored || owner != 0xffff || !item_pristine(record.sent))
				queue(owner, id, record, item_state::applicable(record.sent) | item_state::f_full);
			continue;
		}
		ItemRecord& record = found->second;
		current.uid = record.sent.uid;
		if (record.owner != owner)
		{
			if (item_log_allowed())
				Msg("[NetAnomaly][item] owner id=%u uid=%llu %s -> %s v=%u cond=%.3f", id, record.sent.uid,
					item_owner_name(players, record.owner), item_owner_name(players, owner), record.version + 1,
					item_state::dequantize(current.condition));
			if (record.owner != 0xffff) save_actors.push_back(record.owner);
			if (owner != 0xffff) save_actors.push_back(owner);
			// From the ground, a box or a body into a player's inventory.
			if (record.owner == 0xffff && owner != 0xffff) world_store_note_taken(owner);
			record.owner = owner;
			record.sent = current;
			++record.version;
			record.forced_until = 0;
			record.last_send = now;
			queue(owner, id, record, item_state::applicable(current) | item_state::f_full);
			continue;
		}
		u16 mask = item_state::diff(record.sent, current) & ~item_state::f_uid;
		// The carrier predicts these fields itself; the server's duplicate
		// simulation of the same shots and wear is not echoed back to it.
		const bool forced = now < record.forced_until;
		if (owner != 0xffff && !forced) mask &= ~item_state::f_owner_predicted;
		// Items inside an NPC, corpse or container change with every shot of
		// their holder; others see them only when looting, so 2 Hz is enough
		// (the final state still goes out on the next scan).
		const u32 interval = owner == 0xffff && root != id ? item_held_send_ms : item_min_send_ms;
		if (!mask || now - record.last_send < interval) continue;
		item_state::merge(record.sent, current, mask);
		++record.version;
		// A server-authored change is applied by the carrier even to the
		// fields it predicts (the client drops those from ordinary deltas).
		const u16 flags = forced && owner != 0xffff ? item_state::f_full : 0;
		record.forced_until = 0;
		record.last_send = now;
		queue(owner, id, record, u16(mask | flags));
	}

	// Joining clients (and respawned players): full snapshots of the world's
	// items and their own, a slice per scan.
	static xr_map<u32, u16> resynced; // ClientID -> Actor the snapshots were for
	for (auto it = resynced.begin(); it != resynced.end();)
	{
		xrClientData* CL = players.client_of(it->second);
		if (!CL || CL->ID.value() != it->first) it = resynced.erase(it);
		else ++it;
	}
	for (const auto& player : players.by_actor)
	{
		xrClientData* CL = player.second;
		if (!CL->flags.bConnected || !CL->gamma_snapshot_ready) continue;
		auto done = resynced.find(CL->ID.value());
		if (done != resynced.end() && done->second == player.first) continue;
		resynced[CL->ID.value()] = player.first;
		ItemResync resync; resync.actor = player.first; resync.next = 0;
		s_item_resync[CL->ID.value()] = resync;
	}
	for (auto resync = s_item_resync.begin(); resync != s_item_resync.end();)
	{
		xrClientData* CL = players.client_of(resync->second.actor);
		if (!CL || !CL->gamma_snapshot_ready) { resync = s_item_resync.erase(resync); continue; }
		ItemOutbox box;
		u32 sent = 0;
		auto it = s_item_records.lower_bound(u16(_min(resync->second.next, u32(0xffff))));
		if (resync->second.next > 0xffff) it = s_item_records.end();
		for (; it != s_item_records.end() && sent < item_resync_budget; ++it)
		{
			if (it->second.owner != 0xffff && it->second.owner != resync->second.actor) continue;
			item_outbox_add(box, it->first, it->second, item_state::applicable(it->second.sent) | item_state::f_full);
			++sent;
			if (box.packet.B.count > item_packet_limit) item_outbox_send(server, box, CL);
		}
		item_outbox_send(server, box, CL);
		if (it == s_item_records.end())
		{
			Msg("[NetAnomaly][item] resync done for %s (%u records)", CL->netcoop_login.c_str(), u32(s_item_records.size()));
			resync = s_item_resync.erase(resync);
			continue;
		}
		resync->second.next = u32(it->first);
		++resync;
	}

	item_outbox_send(server, to_all, nullptr);
	for (auto& box : to_owner) item_outbox_send(server, box.second, players.client_of(box.first));

	std::sort(save_actors.begin(), save_actors.end());
	save_actors.erase(std::unique(save_actors.begin(), save_actors.end()), save_actors.end());
	for (u16 actor : save_actors) server_character_save_actor(actor);
}

// Server: a server-authored change (trade, repair, eat) of a carried item;
// its predicted fields go to the carrier too.
void server_item_touch(u16 id)
{
	auto found = s_item_records.find(id);
	if (found != s_item_records.end()) found->second.forced_until = real_time_ms() + 2000;
}

void item_destroyed(u16 id)
{
	if (pure_client())
	{
		client_item_forget(id);
		return;
	}
	auto found = s_item_records.find(id);
	if (found != s_item_records.end())
	{
		// Still a server entity: switched offline, not destroyed.
		CObject* object = Level().Objects.net_Find(id);
		if (object && Level().Server && Level().Server->game && Level().Server->game->get_entity_from_eid(id))
		{
			ItemOffline offline; offline.uid = found->second.sent.uid; offline.section = object->cNameSect();
			s_item_offline[id] = offline;
		}
		else s_item_offline.erase(id);
		s_item_records.erase(found);
	}
	s_item_restore.erase(id);
}

// ---- owner reports -------------------------------------------------------
// M_NETCOOP_ITEM_REPORT: u16 n, n x (u16 id, u16 mask, fields)
void server_on_item_report(xrServer* server, xrClientData* CL, NET_Packet& P)
{
	if (!CL || !CL->owner || P.r_elapsed() < 2) return;
	u16 count = 0; P.r_u16(count);
	if (count > 256) return;
	for (u16 n = 0; n < count; ++n)
	{
		if (P.r_elapsed() < 4) return;
		u16 id = 0, mask = 0; P.r_u16(id); P.r_u16(mask);
		item_state::State proposed;
		if ((mask & ~item_state::f_owner_predicted) || !item_state::read(P, proposed, mask)) return;
		CObject* object = Level().Objects.net_Find(id);
		CInventoryItem* item = smart_cast<CInventoryItem*>(object);
		LPCSTR failure = nullptr;
		if (!item || object->getDestroy()) failure = "no item";
		else if (item_root(server, id) != CL->owner->ID) failure = "not carried by reporter";
		item_state::State stored;
		if (!failure) item_capture(object, stored);
		u16 accepted = 0;
		bool raised = false;
		if (!failure && (mask & item_state::f_condition))
		{
			const item_state::Verdict verdict = item_state::judge_condition(stored.condition, proposed.condition);
			if (verdict == item_state::verdict_raise || verdict == item_state::verdict_wear) accepted |= item_state::f_condition;
			raised |= verdict == item_state::verdict_raise;
		}
		if (!failure && (mask & item_state::f_ammo))
		{
			CWeapon* weapon = smart_cast<CWeapon*>(object);
			const item_state::Verdict verdict = weapon ?
				item_state::judge_ammo(stored, proposed, u32(weapon->GetAmmoMagSize()) + 1, u32(weapon->m_ammoTypes.size())) :
				item_state::verdict_reject;
			if (verdict == item_state::verdict_reject) failure = "bad magazine";
			else if (verdict != item_state::verdict_unchanged) accepted |= item_state::f_ammo;
			raised |= verdict == item_state::verdict_raise;
		}
		if (!failure && (mask & item_state::f_stack))
		{
			CWeaponAmmo* ammo = smart_cast<CWeaponAmmo*>(object);
			const item_state::Verdict verdict = ammo && proposed.stack ?
				item_state::judge_stack(stored.stack_count, proposed.stack_count, ammo->m_boxSize) : item_state::verdict_reject;
			if (verdict == item_state::verdict_reject) failure = "bad box count";
			else if (verdict != item_state::verdict_unchanged) accepted |= item_state::f_stack;
			raised |= verdict == item_state::verdict_raise;
		}
		if (failure)
		{
			if (item_log_allowed())
				Msg("! [NetAnomaly][item] report rejected id=%u player=%s mask=%u: %s", id, CL->netcoop_login.c_str(), mask, failure);
			continue;
		}
		if (!accepted) continue;
		item_apply(object, proposed, accepted);
		auto found = s_item_records.find(id);
		if (found != s_item_records.end())
		{
			ItemRecord& record = found->second;
			item_state::State current; item_capture(object, current); current.uid = record.sent.uid;
			item_state::merge(record.sent, current, accepted);
			++record.version;
			// Raises (repair kits, battery charging, reloads) are run by the
			// owner's GAMMA scripts until they become server transactions (stage 3).
			if (raised && item_log_allowed())
				Msg("[NetAnomaly][item] owner raise id=%u uid=%llu %s player=%s v=%u cond=%.3f ammo=%u box=%u", id, record.sent.uid,
					object->cNameSect().c_str(), CL->netcoop_login.c_str(), record.version,
					item_state::dequantize(record.sent.condition), item_state::ammo_total(record.sent), record.sent.stack_count);
		}
	}
}

// ---- persistence ------------------------------------------------------------
// Character saves keep the uid, portions and the cartridge sequence next to
// the spawn packet of each item.
static bool item_state_ready_for_save(u16 id)
{
	const auto found = s_item_records.find(id);
	return found != s_item_records.end() && found->second.sent.uid != 0 &&
		s_item_restore.find(id) == s_item_restore.end();
}

static void item_state_for_save(u16 id, xr_vector<u8>& out)
{
	out.clear();
	CObject* object = Level().Objects.net_Find(id);
	item_state::State s;
	if (!object || !item_capture(object, s)) return;
	auto found = s_item_records.find(id);
	s.uid = found != s_item_records.end() ? found->second.sent.uid : 0;
	NET_Packet P; P.w_begin(0);
	const u16 mask = item_state::applicable(s);
	P.w_u16(mask);
	item_state::write(P, s, mask);
	out.assign(P.B.data + 2, P.B.data + P.B.count);
}

static void item_state_restore(u16 id, const xr_vector<u8>& saved)
{
	if (saved.size() < 2 || saved.size() > 512) return;
	NET_Packet P; P.w_begin(0);
	P.w(saved.data(), u32(saved.size()));
	P.r_pos = 2;
	u16 mask = 0; P.r_u16(mask);
	item_state::State s;
	if (item_state::read(P, s, mask & item_state::f_all)) s_item_restore[id] = s;
}

// ---- client -------------------------------------------------------------------
struct ClientItemKnown
{
	u32 incarnation = 0;
	u16 version = 0;
};
struct ClientItemPending
{
	u32 incarnation = 0, received = 0;
	u16 version = 0, mask = 0;
	item_state::State state;
};
struct ClientItemReport
{
	item_state::State state;
	u32 time = 0;
	// A server snapshot of this item reached us while we carry it: before
	// that our copy may be stale (picked up from another player) and must not
	// be reported as the item's state.
	bool confirmed = false;
};
static xr_map<u16, ClientItemKnown> s_client_items;
static xr_map<u16, ClientItemPending> s_client_item_pending;
static xr_map<u16, ClientItemReport> s_client_item_reports; // last reported state of own items
static u32 s_client_item_stale = 0, s_client_item_applied = 0;

void client_item_forget(u16 id)
{
	s_client_items.erase(id);
	s_client_item_pending.erase(id);
	s_client_item_reports.erase(id);
}

void items_reset()
{
	s_client_items.clear();
	s_client_item_pending.clear();
	s_client_item_reports.clear();
	s_client_item_stale = 0;
	s_client_item_applied = 0;
	s_item_records.clear();
	s_item_restore.clear();
	s_item_offline.clear();
	s_item_resync.clear();
	s_item_cursor = 0;
}

static bool client_own_item(CObject* object)
{
	CActor* actor = Actor();
	return actor && object && object->H_Root() == actor;
}

static void client_item_apply(CObject* object, const item_state::State& s, u16 mask)
{
	const bool full = (mask & item_state::f_full) != 0;
	mask &= item_state::f_all;
	const bool own = client_own_item(object);
	if (own && !full) mask &= ~item_state::f_owner_predicted;
	item_apply(object, s, mask);
	++s_client_item_applied;
	// A snapshot may arrive before this client moves the item into its
	// inventory (ownership events wait in the game event queue), so the copy
	// counts as synchronised whether or not we carry it yet. The baseline
	// keeps the server's own value from being reported back to it.
	if (own || full)
	{
		ClientItemReport& report = s_client_item_reports[object->ID()];
		item_capture(object, report.state);
		report.time = real_time_ms();
		report.confirmed |= full;
	}
}

// ---- upgrades installed by the server (workshop) --------------------------
// A client has no ALife, so CScriptGameObject::InstallUpgrade does nothing
// there; the server installs (netcoop_workshop runs GAMMA's upgrade window)
// and the GE_INSTALL_UPGRADE it raises reaches the server entity
// (xrServer_process_event) and, from here, every client's copy of the item:
// the same property changes, recorded as installed without a new event.
void server_item_upgraded(xrServer* server, u16 item, LPCSTR upgrade)
{
	if (!enabled() || pure_client() || !server || !upgrade || !upgrade[0]) return;
	NET_Packet P;
	P.w_begin(M_NETCOOP_ITEM_UPGRADE);
	P.w_u16(item);
	P.w_stringZ(upgrade);
	struct Send
	{
		xrServer* server; NET_Packet* packet;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (CL == server->GetServerClient() || !CL->flags.bConnected) return;
			server->SendTo(CL->ID, *packet, net_flags(TRUE, TRUE));
		}
	} send = {server, &P};
	server->ForEachClientDo(send);
}

void client_on_item_upgrade(NET_Packet& P)
{
	if (!pure_client() || P.r_elapsed() < 3) return;
	const u16 id = P.r_u16();
	string256 upgrade;
	if (!read_string(P, upgrade, sizeof(upgrade)) || !pSettings->section_exist(upgrade)) return;
	CInventoryItem* item = smart_cast<CInventoryItem*>(Level().Objects.net_Find(id));
	if (!item || item->has_upgrade(upgrade) || !pSettings->line_exist(upgrade, "section")) return;
	// As Manager::upgrade_install: the upgrade's property section, then the id.
	// No pre_install_upgrade here: the server already unloaded the magazine and
	// the magazine comes with the item state; unloading again would ask for ammo.
	LPCSTR properties = pSettings->r_string(upgrade, "section");
	if (!properties || !pSettings->section_exist(properties)) return;
	item->install_upgrade(properties);
	item->add_upgrade(upgrade, true); // loading: no event back
	Msg("[NetAnomaly][item] upgrade %s on %u", upgrade, id);
}

void client_on_item_state(NET_Packet& P)
{
	if (P.r_elapsed() < 2) return;
	u16 count = 0; P.r_u16(count);
	for (u16 n = 0; n < count; ++n)
	{
		if (P.r_elapsed() < 10) return;
		u16 id = 0, version = 0, mask = 0; u32 incarnation = 0;
		P.r_u16(id); P.r_u32(incarnation); P.r_u16(version); P.r_u16(mask);
		item_state::State s;
		if (!item_state::read(P, s, mask & item_state::f_all)) { Msg("! [NetAnomaly][item] malformed state for %u", id); return; }
		ClientItemKnown& known = s_client_items[id];
		if (known.incarnation == incarnation && !item_state::newer(version, known.version)) { ++s_client_item_stale; continue; }
		known.incarnation = incarnation; known.version = version;
		CObject* object = Level().Objects.net_Find(id);
		if (!object || object->getDestroy() || !smart_cast<CInventoryItem*>(object))
		{
			// Arrived before the object's spawn: applied once it exists.
			if (s_client_item_pending.size() >= 8192) continue;
			ClientItemPending& pending = s_client_item_pending[id];
			if (pending.incarnation != incarnation) pending = ClientItemPending();
			item_state::merge(pending.state, s, mask & item_state::f_all);
			pending.mask |= mask; pending.incarnation = incarnation; pending.version = version;
			pending.received = real_time_ms();
			continue;
		}
		client_item_apply(object, s, mask);
	}
}

void client_items_update(bool flush)
{
	if (!pure_client() || !g_pGameLevel) return;
	static u32 previous = 0;
	const u32 now = real_time_ms();
	if (!flush && previous && now - previous < 100) return;
	previous = now;

	for (auto it = s_client_item_pending.begin(); it != s_client_item_pending.end();)
	{
		CObject* object = Level().Objects.net_Find(it->first);
		if (object && !object->getDestroy() && smart_cast<CInventoryItem*>(object))
		{
			client_item_apply(object, it->second.state, it->second.mask);
			it = s_client_item_pending.erase(it);
		}
		else if (now - it->second.received > 60000) it = s_client_item_pending.erase(it);
		else ++it;
	}

	CActor* actor = Actor();
	if (!actor || !actor->g_Alive()) return;
	NET_Packet P;
	P.w_begin(M_NETCOOP_ITEM_REPORT);
	const u32 count_pos = P.w_tell();
	u16 count = 0;
	P.w_u16(0);
	for (PIItem item : actor->inventory().m_all)
	{
		CObject* object = item ? &item->object() : nullptr;
		if (!object || object->getDestroy() || count >= 256) continue;
		item_state::State current;
		if (!item_capture(object, current)) continue;
		auto found = s_client_item_reports.find(object->ID());
		if (found == s_client_item_reports.end())
		{
			// First sight: the server already has this (spawn or snapshot).
			ClientItemReport& report = s_client_item_reports[object->ID()];
			report.state = current; report.time = now;
			continue;
		}
		ClientItemReport& report = found->second;
		if (!report.confirmed) { report.state = current; continue; }
		const u16 mask = item_state::diff(report.state, current) & item_state::f_owner_predicted;
		if (!mask) continue;
		// Drain moves the condition every frame: small steps at most once a
		// second, 0.1 % steps, shots and anything before a transfer at once.
		const bool big = (mask & (item_state::f_ammo | item_state::f_stack)) ||
			abs(int(report.state.condition) - int(current.condition)) >= 66;
		if (!flush && !big && now - report.time < 1000) continue;
		if (!flush && now - report.time < 100) continue;
		P.w_u16(object->ID()); P.w_u16(mask);
		item_state::write(P, current, mask);
		report.state = current; report.time = now;
		++count;
	}
	if (!count) return;
	P.w_seek(count_pos, &count, sizeof(count));
	Level().Send(P, net_flags(TRUE, TRUE));
}

// Lua (both sides): netcoop_item_info(id) -> "uid=.. v=.. owner=.. cond=.. uses=a/b ammo=n box=n"
LPCSTR script_item_info(u16 id)
{
	static string512 text;
	text[0] = 0;
	if (!g_pGameLevel) return text;
	CObject* object = Level().Objects.net_Find(id);
	item_state::State s;
	const bool live = object && item_capture(object, s);
	if (pure_client())
	{
		auto known = s_client_items.find(id);
		xr_sprintf(text, "client inc=%u v=%u cond=%.3f uses=%u/%u ammo=%u box=%u%s", known != s_client_items.end() ? known->second.incarnation : 0,
			known != s_client_items.end() ? known->second.version : 0, live ? item_state::dequantize(s.condition) : -1.f, s.uses, s.max_uses,
			item_state::ammo_total(s), s.stack_count, live ? "" : " (no object)");
		return text;
	}
	auto found = s_item_records.find(id);
	if (found == s_item_records.end()) { xr_sprintf(text, "server: no record%s", live ? "" : " (no object)"); return text; }
	const ItemRecord& r = found->second;
	xr_sprintf(text, "server uid=%llu inc=%u v=%u owner=%u cond=%.3f uses=%u/%u ammo=%u box=%u", r.sent.uid, r.incarnation, r.version,
		r.owner, live ? item_state::dequantize(s.condition) : -1.f, s.uses, s.max_uses, item_state::ammo_total(s), s.stack_count);
	return text;
}

// Server: the item's persistent instance id (survives saves, stashes,
// transfers and other servers of the cluster) as text, "" if none yet. Lua
// keys per-instance data by it (weapon parts, netcoop_weapon_parts).
LPCSTR script_item_uid(u16 id)
{
	static string32 text;
	text[0] = 0;
	if (!g_pGameLevel || pure_client()) return text;
	auto found = s_item_records.find(id);
	if (found == s_item_records.end() || !found->second.sent.uid) return text;
	xr_sprintf(text, "%llu", (unsigned long long)found->second.sent.uid);
	return text;
}

// ---- server-executed item actions (stage 3) -----------------------------------
// GAMMA's item scripts (battery swap, unpacking, kits) create and release
// items through alife(), which does not exist on a client: there the device
// was charged and the battery kept (charging for free). The client now asks
// the server to run the action; the server checks that the items are in the
// player's inventory and that the action is one it performs
// (netcoop_server_compat.item_action keeps that list as data), then runs the
// same GAMMA function for that player. Results replicate as usual; the
// carrier also receives the fields it normally predicts itself.
// M_NETCOOP_ITEM_ACTION: u8 kind (0 menu functor, 1 item dropped on item or
// another action with the player's item, 2 action on a placed object nearby),
// u16 item, u16 target (0xffff none), stringZ action.

bool script_item_action(int kind, u16 item, u16 target, LPCSTR action)
{
	if (!pure_client() || kind < 0 || kind > 2 || !action || xr_strlen(action) > 63) return false;
	client_items_update(true);
	NET_Packet P;
	P.w_begin(M_NETCOOP_ITEM_ACTION);
	P.w_u8(u8(kind)); P.w_u16(item); P.w_u16(target); P.w_stringZ(action);
	Level().Send(P, net_flags(TRUE, TRUE));
	return true;
}

void server_item_used(CActor* actor, u16 item, LPCSTR section)
{
	if (!enabled() || pure_client() || !actor || !section || !section[0]) return;
	// Called after the authoritative UseBy succeeds, before an empty item is
	// removed. Presentation cannot apply effects or consume the item again.
	LPCSTR category=pSettings->line_exist(section,"kind") ? pSettings->r_string(section,"kind") : "";
	const unsigned kind=netcoop_consumption::kind(section,category);
	// Every use: the clients play New Way's motion and item for the section
	// when they have one, else the generic motion of the kind (255: none).
	const auto message=make_string("%u|%u|%s|%s",actor->ID(),kind,actor->cName().c_str(),section);
	script_broadcast("netcoop_consumption",message.c_str());
	::luabind::functor<void> run;
	if (!ai().script_engine().functor("netcoop_item_use.used", run)) return;
	ServerVictimScope scope(actor);
	try { run(int(actor->ID()), int(item), section); }
	catch (...) { Msg("! [NetAnomaly][item] use effects of %s for player %u failed", section, actor->ID()); }
}

void server_on_item_action(xrServer* server, xrClientData* CL, NET_Packet& P)
{
	if (!enabled() || !CL || !CL->owner || P.r_elapsed() < 6) return;
	const u8 kind = P.r_u8();
	const u16 item = P.r_u16(), target = P.r_u16();
	string64 action;
	if (kind > 2 || !read_string(P, action, sizeof(action))) return;
	CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(CL->owner->ID));
	auto carried = [&](u16 id) { return smart_cast<CInventoryItem*>(Level().Objects.net_Find(id)) && item_root(server, id) == CL->owner->ID; };
	xr_string failure;
	if (!actor || !actor->g_Alive()) failure = "player is dead";
	else if (actor->netcoop_seated()) failure = "only consumption is allowed in a vehicle";
	else if (kind == 2)
	{
		// A placed object in the world (furniture): within reach of the player.
		CObject* object = Level().Objects.net_Find(item);
		if (!object || object->getDestroy()) failure = "object is not available";
		else if (actor->Position().distance_to(object->Position()) > 5.f) failure = "too far away";
	}
	else if (!carried(item)) failure = "item is not in your inventory";
	else if (target != 0xffff && !carried(target)) failure = "target is not in your inventory";
	if (failure.empty())
	{
		::luabind::functor<LPCSTR> run;
		if (!ai().script_engine().functor("netcoop_server_compat.item_action", run)) failure = "server item actions are not loaded";
		else
		{
			ServerVictimScope scope(actor);
			try
			{
				LPCSTR result = run(int(CL->owner->ID), int(kind), int(item), int(target), (LPCSTR)action,
					CL->netcoop_login.c_str());
				failure = result ? result : "";
			}
			catch (...) { failure = "server script error"; }
		}
	}
	if (failure.empty())
	{
		server_item_touch(item);
		if (target != 0xffff) server_item_touch(target);
	}
	Msg("%s[NetAnomaly][item] action %s kind=%u item=%u target=%u player=%s %s%s", failure.empty() ? "" : "! ", action, kind, item,
		target, CL->netcoop_login.c_str(), failure.empty() ? "ok" : "failed: ", failure.c_str());
	if (!failure.empty())
	{
		NET_Packet reply;
		reply.w_begin(M_NETANOMALY_MSG);
		reply.w_stringZ(make_string("! %s", failure.c_str()).c_str());
		server->SendTo(CL->ID, reply, net_flags(TRUE, TRUE));
	}
}

LPCSTR script_actor_login(u16 actor_id)
{
	static string128 login;
	login[0] = 0;
	if (!g_pGameLevel || !Level().Server || pure_client()) return login;
	struct Find
	{
		u16 actor; LPSTR out;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (CL->owner && CL->owner->ID == actor && CL->netcoop_login.size()) xr_strcpy(out, sizeof(login), CL->netcoop_login.c_str());
		}
	} find = {actor_id, login};
	Level().Server->ForEachClientDo(find);
	return login;
}

bool server_object_access(u16 object_id, xrClientData* CL)
{
	if (!CL || pure_client()) return true;
	::luabind::functor<bool> check;
	if (!ai().script_engine().functor("netcoop_server_compat.can_access", check)) return true;
	try { return check(int(object_id), CL->netcoop_login.c_str()); }
	catch (...) { return false; }
}

// Lua (server): netcoop_players() -> "id id ..." of the logged-in players' Actors.
LPCSTR script_players()
{
	static xr_string list;
	list.clear();
	if (!g_pGameLevel || !Level().Server || pure_client()) return list.c_str();
	struct Collect
	{
		xrServer* server; xr_string* out;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (CL == server->GetServerClient() || !CL->owner || !CL->netcoop_login.size()) return;
			string16 id; xr_sprintf(id, "%u ", CL->owner->ID);
			*out += id;
		}
	} collect = {Level().Server, &list};
	Level().Server->ForEachClientDo(collect);
	return list.c_str();
}
