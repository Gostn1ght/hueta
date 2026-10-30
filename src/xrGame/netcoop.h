#pragma once

// NetAnomaly co-op: accounts, roles, server-owned money and trade.
//
// Passwords never leave the client. The client derives a per-server key with
// PBKDF2-SHA256(password, login) and sends that key once per connection. The
// server stores only PBKDF2-SHA256(key, random salt). The game transport is
// not encrypted, so the key is a password equivalent for this server only;
// a network observer on the path could replay it, but cannot recover the
// password for reuse on other services.

class NET_Packet;
class CObject;
class xrClientData;
class xrServer;
struct GAME_NEWS_DATA;
class CWeapon;
class CActor;
namespace netcoop { void client_entry_stop(); }
class CSE_Abstract;
class CZoneCampfire;
class CCustomZone;
class CCustomDevice;
struct SConsolePlayer;
class CCar;

// Console: netcoop_smooth (0 = old network presentation, 1 = doc 38 stage 1),
// netcoop_interp_ms (interpolation delay for remote objects on a client),
// netcoop_metrics (10 s network summary in the log).
extern int g_netcoop_smooth;
extern int g_netcoop_interp_ms;
extern int g_netcoop_metrics;
// Other players shown at the present moment (prediction from the newest
// snapshot and the owner's velocity) instead of ~0.1 s in the past.
extern int g_netcoop_player_predict;

namespace netcoop
{
LPCSTR script_inventory_slots();
bool server_inventory_can_take(xrServer* server,u16 owner_id,u16 item_id);
LPCSTR server_inventory_take_failure(xrServer* server,u16 owner_id,u16 item_id);
// A pickup from the ground the server refused: the player is told why (at
// most every 2 s), instead of the item silently staying where it lies.
bool server_inventory_pickup_allowed(xrServer* server,ClientID sender,u16 owner_id,u16 item_id);
bool server_reset_device(LPCSTR login);
void client_capture_pda();
void server_on_pda_screen(xrServer* server, xrClientData* client, NET_Packet& packet);
void client_on_pda_screen(NET_Packet& packet);
void pda_forget(u16 id);
void replicate_mark(CObject* object, u32 element, const Fvector& position, const Fvector& direction, float size, LPCSTR textures);
void client_on_mark(NET_Packet& packet);
void client_marks_update();
void client_marks_reset();
enum ERole : u8
{
	role_none = 0,
	role_player = 1,
	role_admin = 2,
};

enum EAuthMode : u8
{
	auth_login = 0,
	auth_register = 1,
	auth_auto = 2, // log in, or register when the account does not exist (load-test bots)
};

enum ETradeDirection : u8
{
	trade_actor_buys = 0,
	trade_actor_sells = 1,
};

bool enabled(); // -netcoop on the command line
// -netcoop_corpse_drop: a released corpse drops its inventory on the ground
// (off: the corpse goes with its loot, as in freeplay; owner 2026-10-06).
bool corpse_loot_drops();
bool pure_client(); // netcoop process without a local server
// Map spots on a pure client (no ALife there): a spot is shown when its object
// is on the client, or at a position the scripts gave for its id (the
// player's own PDA pins, far task targets, stashes).
void client_map_position_set(u16 id, const Fvector& position, LPCSTR level);
void client_map_position_clear(u16 id);
bool client_map_position(u16 id, Fvector& position, shared_str& level);
LPCSTR role_name(u8 role);

// Reads a zero-terminated string without asserting on malformed packets.
bool read_string(NET_Packet& P, LPSTR dest, u32 dest_size);

// ---- client ------------------------------------------------------------
// Derives the connection key and remembers it for the next connection.
bool client_set_credentials(LPCSTR login, LPCSTR password, bool register_account);
// The per-server key sent at login: hex PBKDF2-SHA256(password, "NetAnomaly/" + lower(login)).
bool derive_client_key(LPCSTR login, LPCSTR password, xr_string& key_hex);
bool client_has_credentials();
LPCSTR client_login();
// Client: an account login can be sent (password key or cloud session).
bool client_can_login();
u8 client_role();
void client_write_auth(NET_Packet& P);
void client_on_auth_result(NET_Packet& P);
void client_on_trade_result(NET_Packet& P);
bool client_take_trade_refresh(); // true once after a server trade result
void client_on_server_text(LPCSTR text);
void client_send_command(LPCSTR text);

// Server-driven dialogue: the client talk window only shows what the server's
// dialogue run produced and sends the chosen phrase back.
struct TalkLine
{
	bool npc;
	shared_str text;
};

struct TalkChoice
{
	shared_str id;
	shared_str text;
	bool finalizer;
};

struct TalkState
{
	u16 npc;
	bool open;
	bool trade;
	xr_vector<TalkLine> lines;
	xr_vector<TalkChoice> choices;
};

void client_talk_start(u16 npc_id);
void client_talk_choose(LPCSTR id);
void client_talk_stop();
void client_on_talk_state(NET_Packet& P);
bool client_take_talk_state(TalkState& out); // oldest unapplied state

// HUD items (weapons, PDA, food, devices) held by the locally controlled Actor
// switch state on the owning client; the server does not drive their animations.
bool client_owns_hud_item(const CObject* item);

// Lua: netcoop_login(login, password, register), netcoop_role(),
// netcoop_account(), netcoop_command(text), netcoop_pure_client()
bool script_login(LPCSTR login, LPCSTR password, bool register_account);
bool client_admin_authorized();
bool server_actor_god(const CActor* actor);
void server_actor_god_rebind(xrClientData* client, u16 previous_actor, u16 actor_id);
bool script_admin_god_enabled(u16 actor_id);
bool script_admin_god_set(u16 actor_id, bool enabled);
// Admin unlimited ammo, per player on the server (the actor flag is global).
bool server_actor_unlimited_ammo(const CActor* actor);
bool script_admin_ammo_enabled(u16 actor_id);
bool script_admin_ammo_set(u16 actor_id, bool enabled);
bool script_admin_teleport(u16 actor_id, const Fvector& position);
int script_role();
LPCSTR script_account();
int script_account_state();
bool script_registration_decide(LPCSTR login, bool accept);
void script_preview_clear();
bool script_preview_model(LPCSTR model, int pose);
void script_preview_draw();
void script_command(LPCSTR text);
bool script_pure_client();

// ---- server ------------------------------------------------------------
void server_on_auth(xrServer* server, xrClientData* CL, NET_Packet& P);
// Every frame: applies logins whose password hash finished on a worker.
void server_auth_update(xrServer* server);
// True (and the packet kept) while the client's login is being checked.
bool server_defer_player_state(xrClientData* CL, NET_Packet& P);
bool server_requires_login(xrServer* server, xrClientData* CL);
void server_on_trade(xrServer* server, xrClientData* CL, NET_Packet& P);
// Remote clients may not change money, other players' inventories or living
// NPC inventories through raw events. P is left at its read position.
bool server_remote_event_allowed(xrServer* server, xrClientData* CL, NET_Packet& P, u16 type, u16 destination);
void server_on_talk(xrServer* server, xrClientData* CL, NET_Packet& P);
// An NPC answer produced during a server dialogue run; false outside a run.
bool talk_capture_answer(LPCSTR text);
// NPC/monster logic on the server refers to db.actor. For one binder update,
// bind it to the nearest player; false when no player is connected.
// Nested binds keep the outermost player until the outermost unbind.
bool server_bind_nearest_actor(CObject* npc);
void server_unbind_actor();

// For the whole update or event of a server NPC or monster: its AI planner,
// evaluators and callbacks run GAMMA scripts that use db.actor too.
struct ServerActorScope
{
	bool bound;
	explicit ServerActorScope(CObject* object);
	~ServerActorScope();
};

// While a player's Actor on the server is hit: db.actor is that player, so
// GAMMA's hit scripts (armour, body parts, damage) hurt the right Actor.
// They zeroed the hit and took health from whatever db.actor was bound
// (the NPC's nearest player or the host Actor), s98.
struct ServerVictimScope
{
	bool active;
	CActor* previous;
	explicit ServerVictimScope(CActor* victim);
	~ServerVictimScope();
};
void server_on_client_disconnect(xrClientData* CL);
void server_update(xrServer* server); // periodic money persistence
void server_world_bridge_stop(); // join the optional read-only loopback worker
void server_admission_stop(); // join the world master admission coordinator (doc 135)
bool server_account_money(LPCSTR login, u32& money);
// Per-player tasks: updates each player's tasks and sends changed lists.
void server_tasks_update(xrServer* server);
bool server_task_taken_by_other(u16 actor_id, LPCSTR task_id);
void client_on_tasks(NET_Packet& P);
// PDA news the server scripts give a player's Actor, shown on that player's client.
void server_forward_news(u16 actor_id, const GAME_NEWS_DATA& news);
void client_on_news(NET_Packet& P);

// Server Lua -> client Lua: netcoop_broadcast(channel, data) on the server
// calls netcoop_client_compat.on_script_message(channel, data) on every
// logged-in client.
void script_broadcast(LPCSTR channel, LPCSTR data);
// Same message to the client that owns one player Actor; false when the
// Actor is not a remote player's.
bool script_send_to_actor(u16 actor_id, LPCSTR channel, LPCSTR data);
// Server scripts open NPC trade/upgrade windows for a player: the player's
// client opens them (on_script_message "open_ui"). True when sent.
bool server_open_ui(u16 actor_id, LPCSTR kind, u16 partner_id);
// Lua: request a server-executed trade (see netcoop.cpp).
bool script_trade(u16 partner_id, bool actor_sells, LPCSTR ids);
// Starts the thread that reports and aborts a script call hanging a frame.
void script_watchdog_start();
// Main thread: bracket a level lifetime before Lua/object teardown begins.
void script_watchdog_level_begin();
void script_watchdog_level_end();
void client_on_script(NET_Packet& P);
bool server_set_role(LPCSTR login, u8 role, xr_string& message);
void server_list_accounts(xr_string& out);
// Hardware bans (the account's device digest) and the dedicated console's
// Players tab (netcoop_console.inc).
bool server_ban(LPCSTR login, xr_string& message);
bool server_unban(LPCSTR login, xr_string& message);
bool server_apply_role_online(LPCSTR login, u8 role);
void server_list_bans(xr_string& out);
bool server_leader(LPCSTR login, u8 slot, LPCSTR faction, xr_string& message);
void console_players(xr_vector<SConsolePlayer>& out);
// Vehicles (netcoop_vehicles.inc, doc 100).
void server_on_vehicle(xrServer* server, xrClientData* CL, NET_Packet& P);
void client_on_vehicle(NET_Packet& P);
void vehicle_server_update(xrServer* server);
bool vehicle_use(CActor* actor, CObject* object, const Fvector& aim);
void vehicle_key(CActor* actor, int cmd, bool pressed);
void vehicle_input_tick(CActor* actor);
// The gunner's gun view (a helicopter's gun seat): the camera point, or false.
bool vehicle_gun_view_point(CActor* actor, Fvector& point);
LPCSTR script_vehicle_prompt();
Fvector script_vehicle_prompt_point(); // where the last prompt stands (Dot Marks style)
// A box kept away from its anchor (a car's trunk): reachable next to the anchor.
void script_box_anchor(u16 box, u16 anchor);
bool box_anchor_within_reach(u16 box, const Fvector& from);
void vehicles_reset(); // object IDs, anchors and pending opens belong to one level

// Network smoothness (doc 38, stages 0 and 1).
bool smooth();
bool script_character(int slot, LPCSTR name, LPCSTR faction, int economy, LPCSTR loadout);
bool server_character_load_actor(xrClientData* CL, CSE_Abstract* actor);
void server_character_spawn_items(xrClientData* CL);
bool server_character_accepts(xrClientData* CL, u16 type);
bool server_stopping();
void server_character_save_actor(u16 actor_id);
void server_physics_update(xrServer* server);
// Every server frame: physics poses, PDA screens, bullet marks (own rates).
void server_frame_update(xrServer* server);
// W1 (doc 41): with -netcoop_world=<name> the server saves the world every
// 5 minutes and when the last player leaves, and starts from the newest save.
// Called by the ALife constructor; true when it switched the start to a load.
bool world_store_choose_start(LPSTR game_or_spawn, u32 game_size, LPSTR new_or_load, u32 mode_size);
// Lua (server): netcoop_world_save(reason) - save the world now.
bool world_store_save_now(LPCSTR reason);
// Campfires (netcoop_campfire.inc): the server lights and puts them out and
// sends the state; clients ask (matches) and show it.
void server_campfire_changed(u16 id, bool on);
void campfires_reset(); // clear state after the level/network session stops
void server_on_campfire(xrServer* server, xrClientData* CL, NET_Packet& P);
void client_campfire_request(u16 id, bool on);
void client_on_campfire(NET_Packet& P);
// Voice chat and walkie-talkies (netcoop_voice.inc).
bool client_voice_key(int action, bool pressed);
bool client_device_talking(CCustomDevice* device);
void client_voice_update();
void client_voice_render();
void client_voice_reset();
void client_on_voice(NET_Packet& P);
void server_on_voice(xrServer* server, xrClientData* CL, NET_Packet& P);
void server_voice_forget(u16 actor);
void script_voice_radio_local(int freq, bool on, bool have);
LPCSTR script_voice_status();
// PDA dictaphone and voice messages (netcoop_voice_record.inc)
bool script_record_start(int max_seconds);
bool script_record_active();
float script_record_seconds();
LPCSTR script_record_stop();
float script_play_start(LPCSTR data, float from_seconds);
void script_play_seek(float seconds);
void script_play_pause(bool paused);
void script_play_stop();
float script_play_pos();
bool script_play_paused();
LPCSTR script_keyboard_layout();
// PDA photos (netcoop_photo.inc): photo mode, gallery, photos in chats
bool script_photo_take(LPCSTR name);
bool script_photo_exists(LPCSTR name);
int script_photo_size(LPCSTR name);
LPCSTR script_photo_read(LPCSTR name);
bool script_photo_write(LPCSTR name, LPCSTR base64);
bool script_photo_delete(LPCSTR name);
void script_photo_zoom(float zoom);
extern float g_netcoop_photo_zoom;
void script_voice_radio_set(u16 actor, int freq, bool on);
void client_campfire_spawned(CZoneCampfire* campfire);
// Anomalies off on the server (netcoop_zones.inc): a client that comes later
// gets them; an anomaly it spawns later takes that state.
void zones_reset();
void client_zone_spawned(CCustomZone* zone);
// Server: how lit an object is for NPC vision. The renderer lights only what
// it draws; this takes the current weather's sun, sky and ambient light and
// a switched-on torch of a player (stage 8). rendered = the ROS value.
float server_luminocity(const CObject* object, float rendered);
// Authority-only crate/barrel shell estimate and contents mass application.
float script_prop_shell_mass(u16 id);
LPCSTR script_mass_props();
bool script_prop_set_mass(u16 id, float total);
bool script_explode_as(u16 id, u16 initiator);
bool script_mine_contact(u16 id);
// Server: distance to the nearest living player (positions cached each
// frame); a large value when no player is online.
float server_nearest_player_distance(const Fvector& position);
enum { ai_distance_far, ai_distance_combat, ai_distance_path, ai_distance_count };
float server_ai_distance(u32 kind);
// The local Actor or, on the server, a player's Actor.
bool is_player(const CObject* object);
// Server: whether a player looks at an object (view cone, distance), for
// monster logic written for the single local Actor.
bool server_player_sees(const CObject* player, const CObject* object);
// Item instance state (netcoop_items.inc, gameplay plan stage 1): the server
// versions each item's condition/charge, portions, magazine, addons and box
// count and sends changed fields; carriers report their own wear and drain.
void server_items_update(xrServer* server);
void server_on_item_report(xrServer* server, xrClientData* CL, NET_Packet& P);
// A server-authored change of a carried item (trade, repair): its owner gets
// the predicted fields too.
void server_item_touch(u16 id);
// Server: a player's item was used (eaten, applied). GAMMA's use scripts made
// items/money only where they ran, on the client, which cannot; the server's
// share runs here for that player (netcoop_item_use.used).
void server_item_used(CActor* actor, u16 item, LPCSTR section);
void item_destroyed(u16 id); // both sides, from CInventoryItem::net_Destroy
void client_on_item_state(NET_Packet& P);
// An upgrade the server installed on an item (workshop): every client's copy
// of the item gets it too (netcoop_items.inc).
void server_item_upgraded(xrServer* server, u16 item, LPCSTR upgrade);
void client_on_item_upgrade(NET_Packet& P);
// Every frame (rate-limited); flush = report own item changes now, before an
// event that moves an item to someone else.
void client_items_update(bool flush = false);
void client_item_forget(u16 id);
void client_items_reset(); // item IDs/versions belong to one location connection
void client_flush_player_state();
LPCSTR script_item_info(u16 id);
LPCSTR script_item_uid(u16 id);
LPCSTR script_master_state(); // world master schedules for the server Lua
// World orders carried out by the master for every location (false: no master writer here).
bool script_world_order(LPCSTR account, LPCSTR order, LPCSTR source, LPCSTR target, float a, float b, float c, float d);
bool world_time_advance(double game_seconds);
bool master_required();
bool master_ready();
// Atomic transfer of one item between the player and a corpse or a box
// (netcoop_transfer.inc, stage 2). Client: false outside a pure client.
bool client_transfer(u16 from, u16 to, u16 item);
// TransactionID for trade and transfer requests of this client.
u32 client_next_txid();
void client_on_transfer_result(NET_Packet& P);
void server_on_transfer(xrServer* server, xrClientData* CL, NET_Packet& P);
// Lua (client): netcoop_item_action(kind, item, target, action) - the server
// runs an item action (stage 3): kind 0 = menu functor "module.function",
// kind 1 = item dropped on item ("battery_swap"). Target 65535 = none.
bool script_item_action(int kind, u16 item, u16 target, LPCSTR action);
// Lua (server): netcoop_actor_login(actor_id) -> account login of that player's Actor, "" otherwise.
LPCSTR script_actor_login(u16 actor_id);
// Lua (server): netcoop_players() -> "id id ..." of logged-in players' Actors.
LPCSTR script_players();
// Lua (server, location cluster): "map map ..." served by other servers of
// the cluster; empty without netcoop_cluster.ltx.
LPCSTR script_cluster_maps();
// Client-only map presentation; contacts are supplied by the location server.
bool script_map_friend(int actor_id, LPCSTR name);
bool map_player_visible(u16 id, bool actor_spot = false);
void map_players_reset();
void map_player_forget(u16 id);
// Lua (server): shared cluster records (netcoop_shared_store.inc, doc 47).
LPCSTR script_store_read(LPCSTR bucket, LPCSTR key);
bool script_store_swap(LPCSTR bucket, LPCSTR key, LPCSTR expected, LPCSTR value);
LPCSTR script_store_keys(LPCSTR bucket);
LPCSTR script_actor_character(u16 actor_id);
bool script_set_character_faction(u16 actor_id, LPCSTR faction);
// Lua (server): NPC transit records (netcoop_transit.script) for a map's
// server. Publish only after the source checkpoint. Reads are nondestructive;
// acknowledge only after the target checkpoint includes its durable receipt.
LPCSTR script_transit_id();
bool script_transit_put(LPCSTR level, LPCSTR id, LPCSTR content);
LPCSTR script_transit_take(LPCSTR level);
// Round-robin nondestructive selection after an ID, wrapping at the end.
// Corrupt files return "id\n" so a held record cannot strand later squads.
LPCSTR script_transit_next(LPCSTR level, LPCSTR after_id);
bool script_transit_ack(LPCSTR level, LPCSTR id);
// Server: may this player's account use the box/placed object (owner and access
// list kept by netcoop_server_compat.can_access); true for anything unowned.
bool server_object_access(u16 object_id, xrClientData* CL);
void server_on_item_action(xrServer* server, xrClientData* CL, NET_Packet& P);
// Location cluster (netcoop_cluster.inc): M_CHANGE_LEVEL of a remote player
// moves the character to the server of the target map; a leaving player's
// further packets are ignored until the disconnect.
void server_on_change_level(xrServer* server, xrClientData* CL, NET_Packet& P);
bool server_client_leaving(xrClientData* CL);
// Server: a player's Actor died; Lua netcoop_ranks.on_player_death(victim, killer).
void server_on_player_death(CObject* victim, CObject* killer);
// A task given on this map, or one without a recorded map (single server).
bool server_task_here(const char* origin);
// Server: cancels a task (task_manager set_task_cancelled) whose target is a
// non-story object on another map; once per task.
void server_task_check_target(const char* task_id, unsigned short object_id);
void client_on_physics(NET_Packet& P);
// Server: the object is the Actor of a remote player. Local() is not used
// for this: on the dedicated server it did not tell these copies apart
// (s96: players' shots never reached FireStart).
bool server_player_copy(const CObject* object);
// A real-time millisecond clock of this process: never paused or scaled
// (the engine's global timer stops in menus and follows time_factor).
u32 real_time_ms();
// Interpolation clock of a pure client. Server time is not estimated from
// pings (that estimate moved by hundreds of ms and the engine timer drifted
// ~2 % against the server): it follows the newest server snapshots, the upper
// envelope of (snapshot time - real time), decaying 5 % so that a slower
// server clock is followed too. Falls back to Level().timeServer().
void snapshot_sample(u32 server_stamp);
u32 snapshot_now();
// How far behind the estimated server time a client shows remote objects.
u32 remote_interp_delay();
// Same, but at least 1.5 times the object's own last snapshot interval
// (area of interest sends far objects less often).
u32 remote_interp_delay(u32 last_interval);
// Metrics, summarised in the log every 10 s.
void metric_snapshot(u32 interval_ms);
void metric_snapshot_duplicate();
// lead_ms: estimated server time minus the newest snapshot's time; above the
// interpolation delay the object is extrapolated.
void metric_puppet_frame(u16 id, const Fvector& pos, bool extrapolating, s32 lead_ms);
// The same for other players only (logged separately on the [clock] line).
void metric_player_frame(bool extrapolating, s32 lead_ms, float step);
// Client: another player's Actor this frame (why it is or is not shown).
void metric_remote_actor(u16 id, bool remote, bool alive, u32 net_size, s32 age_ms);
void metric_actor_error(float error, bool applied);
void metric_owner_step_rejected(float step);
void metric_weapon_fire(CWeapon* weapon);
// Server: an NPC/monster took a player as its enemy; the time since it saw
// that player (metric_ai_notice) is the reaction, or "not by sight".
void metric_ai_reaction(u16 npc, u16 player);
// Server: a player became visible to an NPC/monster after notice_ms in view.
void metric_ai_notice(u16 npc, u16 player, u32 notice_ms, float distance);
// Server time profile (plan section 36), summarised every 10 s: AI thinking
// with the real update interval of each NPC/monster, snapshot replication,
// item state and per-frame tasks.
// prof_io: world snapshot writes on the main thread (characters are written
// by their own worker thread). Physics frame steps come from xrPhysics.
enum EProfileSlot { prof_ai, prof_replication, prof_items, prof_io, prof_count };
struct ProfileScope
{
	u32 slot;
	u64 start;
	explicit ProfileScope(u32 profile_slot);
	~ProfileScope();
};
void metric_ai_update(u16 npc);
// Server: bytes of object updates sent this tick and objects serialised.
void metric_server_sent(u32 bytes, u32 objects);
// Server: a client's snapshot skipped because its send queue was late.
void metric_snapshot_blocked();
void metrics_update();

// Death and respawn of this client's player: after death the camera stays at
// the body with a blinking countdown (10 s), then SPACE asks the server for
// a new Actor ("respawn" command). The body stays in the world as a corpse.
void client_on_own_death();
void client_death_frame();
bool client_death_key(int key); // true when the key was used
// Lua (server): netcoop_respawn(actor_id) - a new Actor for a dead player.
bool script_respawn(u16 actor_id);

// Load test: bots connect to a server as players and walk (netcoop_bots.cpp).
// Console: netcoop_bots <count> [address]; command line -netcoop_bots <count>
// [-netcoop_bots_addr <address>]. Pumped every frame by the game.
void bots_set(u32 count, LPCSTR address);
void bots_frame();

// RP animations (player emotes) from configs/netcoop/rp_anims.ltx (stock
// stalker motions).
struct RpAnim
{
	shared_str name;
	shared_str title;
	xr_vector<shared_str> in, mid, out;
	bool loop = true;
	bool once = false; // a gesture: the chains play once and the animation ends by itself
	// New Way's walking poses (owner 2026-10-24): the legs follow the movement
	// (forward, back, left, right, standing), the torso holds its pose
	// (walking, standing); no chains.
	bool walk = false;
	xr_vector<shared_str> legs, torso;
	u8 slot = 0; // a weapon pose: this slot's item in the hands (it must be there)
	u8 weapon = 0; // 1: long firearm, 2: pistol; slot is only a preference
	xr_vector<shared_str> items; // any listed item must be present, including in the rucksack
};
const xr_vector<RpAnim>& rp_anims();
// Lua: netcoop_rp_list() -> "name=title;...", netcoop_rp_play(name),
// netcoop_rp_stop(), netcoop_rp_active() -> name or "".
LPCSTR script_rp_list();
// false: not started (a weapon pose without the weapon)
bool script_rp_play(LPCSTR name);
void script_rp_stop();
LPCSTR script_rp_active();
} // namespace netcoop
