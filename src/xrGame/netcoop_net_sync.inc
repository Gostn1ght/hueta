// Included in netcoop.cpp (namespace netcoop) - network smoothness, physics replication, metrics.
// Split out of netcoop.cpp in the same order (doc 151); see the file list there.

// ---------------------------------------------------------------------------
// Network smoothness and metrics (doc 38, stages 0 and 1)
// ---------------------------------------------------------------------------
#include "Weapon.h"
#include "ai/stalker/ai_stalker.h"
#include "CustomMonster.h"
#include "memory_manager.h"
#include "enemy_manager.h"
#include "visual_memory_manager.h"
#include "Car.h"
#include "CustomRocket.h"
#include "actor_anim_defs.h"
#include "../xrEngine/CameraBase.h"
#include "HUDManager.h"
#include "UIGameSP.h"
#include "CharacterPhysicsSupport.h"
#include "PHMovementControl.h"

int g_netcoop_smooth = 1;
int g_netcoop_interp_ms = 100;
int g_netcoop_metrics = 1;
int g_netcoop_player_predict = 0;

namespace netcoop
{
void client_on_physics(NET_Packet& P)
{
	if (!pure_client() || P.r_elapsed() < 8) return;
	const u16 id = P.r_u16();
	CPhysicsShellHolder* holder = smart_cast<CPhysicsShellHolder*>(Level().Objects.net_Find(id));
	if (holder) holder->netcoop_physics_import(P);
}

struct PhysicsSent { bool sleeping = false; u32 last = 0; };
static xr_map<u16, PhysicsSent> s_physics_sent;

void vehicle_server_update(xrServer* server);

void server_physics_update(xrServer* server)
{
	if (!g_pGameLevel || pure_client()) return;
	// Seated players follow their seats every frame (doc 100).
	vehicle_server_update(server);
	server_corpse_drag_update(server);
	static u32 previous = 0;
	static u32 tick = 0;
	const u32 now = real_time_ms();
	if (previous && now - previous < 50) return;
	previous = now;
	++tick;
	static u32 level_started = 0; // props settle on the ground while the level starts
	if (!level_started) level_started = now;
	const bool settling = now - level_started < 30000;
	if (tick % 200 == 0)
		for (auto it = s_physics_sent.begin(); it != s_physics_sent.end();)
			it = Level().Objects.net_Find(it->first) ? std::next(it) : s_physics_sent.erase(it);
	struct FootContact { Fvector position, direction; };
	xr_vector<FootContact> feet;
	for (u32 n = 0; n < Level().Objects.o_count(); ++n)
	{
		CActor* actor = smart_cast<CActor*>(Level().Objects.o_get_by_iterator(n));
		if (!actor || actor->ID() == 0 || !actor->g_Alive() || actor->getDestroy()) continue;
		const u32 move = actor->MovingState();
		if (!(move & (mcFwd | mcBack | mcLStrafe | mcRStrafe)) || (move & (mcJump | mcClimb))) continue;
		FootContact contact; contact.position = actor->Position(); contact.direction.set(0.f, 0.f, 0.f);
		Fmatrix facing; facing.rotateY(-actor->netcoop_model_yaw());
		if (move & mcFwd) contact.direction.add(facing.k);
		if (move & mcBack) contact.direction.sub(facing.k);
		if (move & mcRStrafe) contact.direction.add(facing.i);
		if (move & mcLStrafe) contact.direction.sub(facing.i);
		contact.direction.y = 0.f;
		if (contact.direction.square_magnitude() < EPS_S) continue;
		contact.direction.normalize(); feet.push_back(contact);
	}
	for (u32 n = 0; n < Level().Objects.o_count(); ++n)
	{
		CObject* object = Level().Objects.o_get_by_iterator(n);
		CPhysicsShellHolder* holder = smart_cast<CPhysicsShellHolder*>(object);
		CEntityAlive* creature = smart_cast<CEntityAlive*>(object);
		if (!holder || holder->getDestroy() || holder->H_Parent() || !holder->PPhysicsShell()) continue;
		// Doors, barrels, crates and other physics props (CPhysicObject) were
		// never sent: a door opened on the server stayed closed and solid on
		// every client, and players ran into it and were pulled back
		// (2026-10-07). A prop is followed once it has moved on the server;
		// the hundreds that never move are left alone.
		const bool item_or_corpse = smart_cast<CInventoryItem*>(object) || (creature && !creature->g_Alive());
		// Broken boxes/barrels spawn CPhysicsSkeletonObject, not CPhysicObject.
		// Their bodies must follow the authority just like their source props.
		const bool prop = !item_or_corpse && !creature &&
			(smart_cast<CPhysicObject*>(object) || smart_cast<CPhysicsSkeletonObject*>(object));
		// Cars (doc 100): the server drives them; clients show replicas.
		const bool vehicle = !item_or_corpse && smart_cast<CCar*>(object) != nullptr;
		const bool projectile = smart_cast<CMissile*>(object) || smart_cast<CCustomRocket*>(object);
		if (!item_or_corpse && !prop && !vehicle) continue;
		if (prop && s_physics_sent.find(holder->ID()) == s_physics_sent.end())
		{
			if (settling) continue;
		}
		const u16 count = holder->PHGetSyncItemsNumber();
		if (!count || count > 128) continue;
		// Client replica colliders are fixed; only the authority integrates
		// contact pushes. Walking against a body gives a small, mass-scaled
		// impulse, never a position correction or an unvalidated client force.
		// The remote Actor's position is accepted directly rather than driven
		// by the ordinary movement solver. Apply the same validated
		// movement contact to props/fragments, including sleeping ones.
		for (const FootContact& foot : feet)
		{
			if (vehicle || projectile || (creature && server_corpse_dragging(object))) break;
			for (u16 i = 0; i < count; ++i)
			{
				SPHNetState body; holder->PHGetSyncItem(i)->get_State(body);
				Fvector gap; gap.sub(body.position, foot.position);
				if (gap.y < -0.2f || gap.y > 0.8f) continue;
				gap.y = 0.f;
				if (gap.square_magnitude() > 0.36f || gap.dotproduct(foot.direction) < -0.05f) continue;
				// Small item drops must not shoot away under the player's feet.
				// A corpse needs a whole-body nudge: pushing one light limb at
				// 0.28 m/s could not overcome the ground friction of the full body.
				const float target = creature ? 0.65f : item_or_corpse ? 0.75f : 0.5f;
				const float gain = _max(0.f, target - body.linear_vel.dotproduct(foot.direction));
				if (gain > 0.f)
				{
					if (creature && holder->PPhysicsShell()->getMass() > 200.f) break;
					holder->PPhysicsShell()->Enable();
					for (u16 j = 0; j < (creature ? count : 1); ++j)
					{
						const u16 part = creature ? j : i;
						SPHNetState state; holder->PHGetSyncItem(part)->get_State(state);
						const float change = _max(0.f, _min(target, target - state.linear_vel.dotproduct(foot.direction)));
						CPhysicsElement* element = holder->PPhysicsShell()->get_ElementByStoreOrder(part);
						element->applyImpulse(foot.direction, _min(element->getMass(), 30.f) * change);
					}
				}
				break;
			}
		}
		// Stage 6: only moving bodies are sent at the full rate. A body that
		// fell asleep sends its final pose once to every client, then a
		// refresh every 10 s; a push or a hit wakes it and sending resumes.
		const bool awake = holder->PPhysicsShell()->isEnabled();
		if ((prop || vehicle) && s_physics_sent.find(holder->ID()) == s_physics_sent.end())
		{
			if (!awake) continue; // untouched props still consume no pose traffic
			Msg("[Lost Zone][physics] prop %s (%u) moved: its pose goes to the players", holder->cName().c_str(), holder->ID());
		}
		if (awake && !creature && !vehicle && !projectile)
		{
			// Loose props/debris are limited. Launcher rockets derive from
			// CCustomRocket, not CMissile; all projectiles keep their ballistics.
			for (u16 i = 0; i < count; ++i)
			{
				SPHNetState state; holder->PHGetSyncItem(i)->get_State(state);
				Fvector velocity = state.linear_vel;
				const float speed = velocity.magnitude();
				if (speed > 12.f)
				{
					velocity.mul(12.f / speed);
					holder->PPhysicsShell()->get_ElementByStoreOrder(i)->set_LinearVel(velocity);
				}
			}
		}
		PhysicsSent& sent = s_physics_sent[holder->ID()];
		if (!awake)
		{
			if (sent.sleeping && now - sent.last < (prop ? 60000u : 10000u)) continue;
			sent.sleeping = true;
		}
		else sent.sleeping = false;
		sent.last = now;
		NET_Packet P;
		P.w_begin(M_NETCOOP_PHYSICS);
		P.w_u16(holder->ID());
		P.w_u32(Level().timeServer());
		P.w_u16(count);
		for (u16 i = 0; i < count; ++i)
		{
			SPHNetState state;
			holder->PHGetSyncItem(i)->get_State(state);
			P.w_u8(state.enabled ? 1 : 0);
			P.w_vec3(state.position);
			P.w_float(state.quaternion.x);
			P.w_float(state.quaternion.y);
			P.w_float(state.quaternion.z);
			P.w_float(state.quaternion.w);
			P.w_vec3(state.linear_vel);
		}
		struct SendPhysics
		{
			xrServer* server;
			CPhysicsShellHolder* holder;
			NET_Packet* packet;
			u32 tick;
			bool settled; // asleep: final or refresh pose, sent to everyone at once
			void operator()(IClient* client)
			{
				xrClientData* CL = static_cast<xrClientData*>(client);
				if (CL == server->GetServerClient() || !CL->flags.bConnected || !CL->gamma_snapshot_ready || !CL->owner) return;
				const float distance = CL->owner->o_Position.distance_to(holder->Position());
				const u32 every = distance < 50.f ? 1 : distance < 150.f ? 2 : distance < 300.f ? 5 : 20;
				// The final pose of a body that fell asleep is sent once, reliably:
				// skipping it for a busy queue left the item hovering where the
				// last moving pose put it until the next refresh (10 s, props 60 s).
				if (!settled && ((tick + holder->ID()) % every || !server->HasSendQueueRoom(CL, 64))) return;
				server->SendTo(CL->ID, *packet, net_flags(settled ? TRUE : FALSE, TRUE));
			}
		} send = {server, holder, &P, tick, !awake};
		server->ForEachClientDo(send);
	}
}
#include "netcoop_vehicles.inc"
#include "netcoop_vehicle_server.inc"
#include "netcoop_vehicle_client.inc"
#include "netcoop_vehicle_seat.inc"
} // namespace netcoop

namespace netcoop
{
bool smooth()
{
	return enabled() && g_netcoop_smooth != 0;
}

// Snapshot timing seen by this client (exponential averages, ms): the
// interpolation delay covers the usual interval plus three deviations so a
// late snapshot still arrives before it is needed.
static float s_snap_interval = 33.f;
static float s_snap_jitter = 5.f;
// Real-time length of this client's frames: snapshots are applied once a
// frame, so an object's newest snapshot can be a frame older than it is.
static float s_frame_ema = 33.f;
static u32 s_frame_last = 0;

namespace
{
CTimer& real_timer()
{
	static CTimer timer;
	static bool started = false;
	if (!started)
	{
		timer.Start();
		started = true;
	}
	return timer;
}

// Server time minus real time, from the freshest snapshots of the current
// and previous second (a window, so a wrong estimate lasts at most 2 s; the
// old maximum-with-decay held one stamp from the future for tens of seconds,
// s96). A jump ahead by more than 250 ms needs 5 confirming snapshots. The
// clock shown moves toward the estimate at most 10 % faster or slower than
// real time, so the timeline never jumps.
bool s_snapshot_clock_valid = false;
double s_clock_now_max = 0.0, s_clock_prev_max = 0.0;
bool s_clock_prev_valid = false;
u32 s_clock_bucket_time = 0;
double s_clock_candidate = 0.0;
u32 s_clock_candidates = 0;
double s_clock_applied = 0.0;
u32 s_clock_applied_time = 0;

double snapshot_clock_target()
{
	return s_clock_prev_valid ? _max(s_clock_now_max, s_clock_prev_max) : s_clock_now_max;
}

void snapshot_clock_advance(u32 now)
{
	const double target = snapshot_clock_target();
	const double elapsed = now > s_clock_applied_time ? double(now - s_clock_applied_time) : 0.0;
	s_clock_applied_time = now;
	const double diff = target - s_clock_applied;
	if (_abs(diff) > 500.0)
		s_clock_applied = target;
	else
	{
		const double step = 0.1 * elapsed;
		s_clock_applied += diff > 0.0 ? _min(diff, step) : _max(diff, -step);
	}
}
} // namespace

} // namespace netcoop
bool netcoop_is_player_actor(u16 id); // game_sv_single.cpp
namespace netcoop
{
void server_on_player_death(CObject* victim, CObject* killer)
{
	if (!victim || !server_player_copy(victim)) return;
	if(Character* character=character_tracked_for_save(victim->ID())) {
		::luabind::functor<bool> prepare;
		if(ai().script_engine().functor("netcoop_survival.prepare",prepare)) {
			try {prepare(smart_cast<CActor*>(victim)->lua_game_object(),int(character->lives_remaining ? character->lives_remaining-1:0));}
			catch(...){Msg("! [diag][survival] death draw pending for actor=%u",victim->ID());}
		}
	}
	::luabind::functor<void> handler;
	if (!ai().script_engine().functor("netcoop_ranks.on_player_death", handler)) return;
	try { handler(int(victim->ID()), int(killer ? killer->ID() : 65535)); }
	catch (...) { Msg("! [Lost Zone] netcoop_ranks.on_player_death failed"); }
}

bool server_player_copy(const CObject* object)
{
	return object && enabled() && !pure_client() && g_pGameLevel && Level().Server && object->ID() != 0 &&
		netcoop_is_player_actor(object->ID());
}

u32 real_time_ms()
{
	return real_timer().GetElapsed_ms();
}

void snapshot_sample(u32 server_stamp)
{
	if (!pure_client())
		return;
	const u32 now = real_time_ms();
	const double offset = double(server_stamp) - double(now);
	if (!s_snapshot_clock_valid)
	{
		s_clock_now_max = s_clock_applied = offset;
		s_clock_bucket_time = s_clock_applied_time = now;
		s_snapshot_clock_valid = true;
		return;
	}
	if (now - s_clock_bucket_time >= 1000)
	{
		s_clock_prev_max = s_clock_now_max;
		s_clock_prev_valid = true;
		s_clock_now_max = offset;
		s_clock_bucket_time = now;
		s_clock_candidates = 0;
	}
	if (offset > snapshot_clock_target() + 250.0)
	{
		// Far ahead of the others: wait for confirmation.
		s_clock_candidate = s_clock_candidates ? _min(s_clock_candidate, offset) : offset;
		if (++s_clock_candidates < 5)
			return;
		s_clock_now_max = s_clock_candidate;
		s_clock_prev_valid = false;
		s_clock_candidates = 0;
		return;
	}
	if (offset > s_clock_now_max)
		s_clock_now_max = offset;
}

u32 snapshot_now()
{
	if (!s_snapshot_clock_valid || !pure_client())
		return g_pGameLevel ? Level().timeServer() : 0;
	const u32 now = real_time_ms();
	snapshot_clock_advance(now);
	return u32(s64(now) + s64(s_clock_applied));
}

u32 remote_interp_delay()
{
	if (!(pure_client() && g_netcoop_smooth))
		return NET_Latency;
	const float adaptive = s_snap_interval + 3.f * s_snap_jitter;
	const float delay = _max(float(g_netcoop_interp_ms), _min(adaptive, 250.f));
	return u32(delay);
}

u32 remote_interp_delay(u32 last_interval)
{
	const u32 base = remote_interp_delay();
	if (!(pure_client() && g_netcoop_smooth))
		return base;
	// The object's own snapshot interval (far ones are sent less often) plus
	// two client frames and a margin: s93 extrapolated 14-22 % of frames
	// with 1.5 x interval at 40-60 ms client frames.
	const u32 frames = u32(2.f * _min(s_frame_ema, 100.f));
	return _max(base, _min(last_interval + frames + 30, 800u));
}

namespace
{
struct Metrics
{
	u32 frames, frame_ms_sum, frame_ms_max, frames_over_33, frames_over_100;
	u32 snaps, snap_ms_sum, snap_ms_max, snaps_over_100, dups;
	u32 puppet_frames, extrap_frames, jumps;
	float jump_max;
	s64 lead_sum;
	s32 lead_min, lead_max;
	u32 pl_frames, pl_extrap;
	s64 pl_lead_sum;
	s32 pl_lead_max;
	float pl_step_max;
	u32 acks, fixes;
	float err_sum, err_max;
	u32 owner_rejects;
	float owner_reject_max;
	u32 shots;
	u32 sv_bytes, sv_ticks, sv_objects;
	u32 sv_blocked;
};
Metrics m;
u32 next_print = 0;

struct PuppetTrack
{
	Fvector pos;
	u32 time;
};
xr_map<u16, PuppetTrack> puppets;
xr_map<u16, u32> shot_log_time;
} // namespace

void metric_snapshot(u32 interval_ms)
{
	if (interval_ms < 1000)
	{
		// Far objects are sent every 2-16 ticks on purpose; only near-rate
		// intervals measure network jitter.
		const float x = float(_min(interval_ms, 90u));
		s_snap_interval += (x - s_snap_interval) * 0.02f;
		s_snap_jitter += (_abs(x - s_snap_interval) - s_snap_jitter) * 0.02f;
	}
	++m.snaps;
	m.snap_ms_sum += interval_ms;
	m.snap_ms_max = _max(m.snap_ms_max, interval_ms);
	if (interval_ms > 100)
		++m.snaps_over_100;
}

void metric_snapshot_duplicate()
{
	++m.dups;
}

// A jump is a frame step longer than a running NPC can cover (10 m/s) plus
// 0.25 m: the object was teleported, not moved.
void metric_puppet_frame(u16 id, const Fvector& pos, bool extrapolating, s32 lead_ms)
{
	if (!m.puppet_frames || lead_ms < m.lead_min)
		m.lead_min = lead_ms;
	if (!m.puppet_frames || lead_ms > m.lead_max)
		m.lead_max = lead_ms;
	m.lead_sum += lead_ms;
	++m.puppet_frames;
	if (extrapolating)
		++m.extrap_frames;
	PuppetTrack& t = puppets[id];
	const u32 now = Device.dwTimeGlobal;
	if (t.time && now - t.time < 500)
	{
		const float step = t.pos.distance_to(pos);
		const float allowed = 0.25f + 10.f * float(now - t.time) / 1000.f;
		if (step > allowed)
		{
			++m.jumps;
			m.jump_max = _max(m.jump_max, step);
		}
	}
	t.pos = pos;
	t.time = now;
}

void metric_player_frame(bool extrapolating, s32 lead_ms, float step)
{
	++m.pl_frames;
	if (extrapolating)
		++m.pl_extrap;
	m.pl_lead_sum += lead_ms;
	m.pl_lead_max = _max(m.pl_lead_max, lead_ms);
	m.pl_step_max = _max(m.pl_step_max, step);
}

namespace
{
struct RemoteActorStat
{
	u32 frames;
	bool remote;
	bool alive;
	u32 net_size;
	s32 age;
};
xr_map<u16, RemoteActorStat> s_remote_actors;
u32 s_remote_actors_next = 0;
}

void metric_remote_actor(u16 id, bool remote, bool alive, u32 net_size, s32 age_ms)
{
	RemoteActorStat& s = s_remote_actors[id];
	++s.frames;
	s.remote = remote;
	s.alive = alive;
	s.net_size = net_size;
	s.age = age_ms;
	const u32 now = real_time_ms();
	if (now < s_remote_actors_next)
		return;
	s_remote_actors_next = now + 10000;
	for (auto& it : s_remote_actors)
	{
		if (it.second.frames)
			Msg("[Lost Zone][player] %u: %u frames, remote %d alive %d, %u snapshots, newest %d ms old", it.first,
			    it.second.frames, it.second.remote ? 1 : 0, it.second.alive ? 1 : 0, it.second.net_size, it.second.age);
		it.second.frames = 0;
	}
}

void metric_actor_error(float error, bool applied)
{
	++m.acks;
	m.err_sum += error;
	m.err_max = _max(m.err_max, error);
	if (applied)
		++m.fixes;
}

void metric_snapshot_blocked()
{
	++m.sv_blocked;
}

void metric_server_sent(u32 bytes, u32 objects)
{
	m.sv_bytes += bytes;
	++m.sv_ticks;
	m.sv_objects = objects;
}

void metric_owner_step_rejected(float step)
{
	++m.owner_rejects;
	m.owner_reject_max = _max(m.owner_reject_max, step);
}

// Server: who an NPC shoots at and whether it sees the target. Client: a
// puppet's weapon must never start firing on its own.
void metric_weapon_fire(CWeapon* weapon)
{
	if (!enabled() || !g_pGameLevel || !weapon || !weapon->H_Parent())
		return;
	CAI_Stalker* stalker = smart_cast<CAI_Stalker*>(weapon->H_Parent());
	if (!stalker)
	{
		// Server: a player's weapon fires; is the owner's aim there?
		CActor* player = smart_cast<CActor*>(weapon->H_Parent());
		if (player && server_player_copy(player))
		{
			const u32 now = Device.dwTimeGlobal;
			u32& last = shot_log_time[player->ID()];
			if (last && now - last < 1000)
				return;
			last = now;
			Fvector pos, dir;
			const bool aim = weapon->netcoop_aim(pos, dir);
			Msg("[Lost Zone][shot] player %s fires %s, owner aim %s", player->cName().c_str(),
			    weapon->cNameSect().c_str(), aim ? "fresh" : "missing");
		}
		return;
	}
	++m.shots;
	const u32 now = Device.dwTimeGlobal;
	u32& last = shot_log_time[stalker->ID()];
	if (last && now - last < 3000)
		return;
	last = now;
	if (pure_client())
	{
		Msg("[Lost Zone][shot] client puppet %s (%u) started firing %s", stalker->cName().c_str(), stalker->ID(),
		    weapon->cNameSect().c_str());
		return;
	}
	const CEntityAlive* enemy = stalker->g_Alive() ? stalker->memory().enemy().selected() : 0;
	Msg("[Lost Zone][shot] %s (%u) fires %s at %s (%u) dist %.1f visible %d", stalker->cName().c_str(), stalker->ID(),
	    weapon->cNameSect().c_str(), enemy ? enemy->cName().c_str() : "no enemy", enemy ? enemy->ID() : 0,
	    enemy ? enemy->Position().distance_to(stalker->Position()) : 0.f,
	    enemy ? int(stalker->memory().visual().visible_now(enemy)) : 0);
}

namespace
{
bool s_own_dead = false;
bool s_respawn_sent = false;
u32 s_death_time = 0;
u32 s_respawn_sent_time = 0;
const u32 respawn_delay_ms = 1500;
}

void client_on_own_death()
{
	s_own_dead = true;
	s_respawn_sent = false;
	s_death_time = real_time_ms();
	Msg("[Lost Zone] player died, respawn in %u s", respawn_delay_ms / 1000);
}

void client_death_frame()
{
	if (!s_own_dead || !pure_client() || !g_pGameLevel)
		return;
	CActor* own = smart_cast<CActor*>(Level().CurrentControlEntity());
	if (own && own->g_Alive())
	{
		s_own_dead = false; // the server gave a new Actor
		return;
	}
	const u32 now = real_time_ms();
	if (s_respawn_sent && now - s_respawn_sent_time > 5000)
		s_respawn_sent = false; // ask again if nothing came
	if (!s_respawn_sent && now-s_death_time>=respawn_delay_ms) {
		s_respawn_sent=true;s_respawn_sent_time=now;
		client_send_command("respawn"); // server persists death, then returns to the account room
	}
	if ((now / 500) % 2)
		return; // blink
	CGameFont* font = UI().Font().pFontGraffiti22Russian;
	if (!font)
		return;
	const u32 elapsed = now - s_death_time;
	string256 text;
	if (elapsed < respawn_delay_ms)
		xr_sprintf(text, "%s %u", CStringTable().translate("st_netcoop_respawn_in").c_str(),
		           (respawn_delay_ms - elapsed + 999) / 1000);
	else
		xr_strcpy(text, CStringTable().translate("st_netcoop_respawn_press").c_str());
	font->SetAligment(CGameFont::alCenter);
	font->SetColor(0xffffffff);
	font->OutSetI(0.f, -0.25f);
	font->OutNext("%s", text);
}

bool client_death_key(int key)
{
	if (!s_own_dead || !pure_client())
		return false;
	if (real_time_ms() - s_death_time < respawn_delay_ms || s_respawn_sent)
		return true;
	if (get_binded_action(key) != kJUMP)
		return true;
	s_respawn_sent = true;
	s_respawn_sent_time = real_time_ms();
	client_send_command("respawn");
	return true;
}

static u32 s_ai_reactions = 0, s_ai_reaction_sum = 0, s_ai_reaction_max = 0, s_ai_unseen = 0, s_ai_log_time = 0;

static u64 s_prof_ticks[prof_count] = {};
static u32 s_prof_calls[prof_count] = {};
static xr_map<u16, u32> s_ai_last_update;
static u32 s_ai_updates = 0, s_ai_interval_sum = 0, s_ai_interval_max = 0;

ProfileScope::ProfileScope(u32 profile_slot) : slot(profile_slot), start(CPU::QPC()) {}
ProfileScope::~ProfileScope()
{
	if (slot >= prof_count) return;
	s_prof_ticks[slot] += CPU::QPC() - start;
	++s_prof_calls[slot];
}

void metric_ai_update(u16 npc)
{
	const u32 now = real_time_ms();
	u32& last = s_ai_last_update[npc];
	if (last && now > last && now - last < 10000)
	{
		const u32 interval = now - last;
		++s_ai_updates;
		s_ai_interval_sum += interval;
		s_ai_interval_max = _max(s_ai_interval_max, interval);
	}
	last = now;
}

static u32 s_ai_notices = 0, s_ai_notice_sum = 0, s_ai_notice_max = 0, s_ai_notice_log = 0;

static xr_map<u32, u32> s_ai_seen; // npc << 16 | player -> real time it saw the player

void metric_ai_notice(u16 npc, u16 player, u32 notice_ms, float distance)
{
	if (s_ai_seen.size() > 8192) s_ai_seen.clear();
	s_ai_seen[u32(npc) << 16 | player] = real_time_ms();
	++s_ai_notices;
	s_ai_notice_sum += notice_ms;
	s_ai_notice_max = _max(s_ai_notice_max, notice_ms);
	const u32 now = real_time_ms();
	if (now - s_ai_notice_log < 250) return;
	s_ai_notice_log = now;
	CObject* object = Level().Objects.net_Find(npc);
	Msg("[NetAnomaly][ai] %s (%u) saw player %u at %.0f m after %u ms in view", object ? object->cName().c_str() : "?", npc, player,
		distance, notice_ms);
}

void metric_ai_reaction(u16 npc, u16 player)
{
	auto seen = s_ai_seen.find(u32(npc) << 16 | player);
	// Seen more than a minute ago (or never): the enemy came from a hit,
	// a sound or the squad, not from this sight.
	const s32 reaction_ms = seen != s_ai_seen.end() && real_time_ms() - seen->second < 60000 ? s32(real_time_ms() - seen->second) : -1;
	if (reaction_ms < 0) ++s_ai_unseen;
	else
	{
		++s_ai_reactions;
		s_ai_reaction_sum += u32(reaction_ms);
		s_ai_reaction_max = _max(s_ai_reaction_max, u32(reaction_ms));
	}
	const u32 now = real_time_ms();
	if (now - s_ai_log_time < 250) return;
	s_ai_log_time = now;
	CObject* object = Level().Objects.net_Find(npc);
	Msg("[NetAnomaly][ai] %s (%u) took player %u as enemy: %s %d ms after first sight", object ? object->cName().c_str() : "?", npc,
		player, reaction_ms < 0 ? "not seen," : "", reaction_ms);
}

// Frame time distribution of the 10 s metrics window (doc 43 M01): 1 ms
// buckets, the last one is 250 ms and more.
static u32 s_frame_hist[251] = {};

static u32 frame_percentile(u32 total, float share)
{
	const u32 wanted = u32(ceilf(float(total) * share));
	u32 seen = 0;
	for (u32 i = 0; i < 251; ++i)
	{
		seen += s_frame_hist[i];
		if (seen >= wanted && seen)
			return i;
	}
	return 250;
}

// What the server keeps online and in ALife (doc 43 M02), once per window:
// online stalkers / mutants / players, items lying in the world, physics
// props, all online objects; ALife objects and how many of them are online.
static void metric_world_counts()
{
	if (!g_pGameLevel) return;
	u32 stalkers = 0, mutants = 0, players = 0, ground = 0, props = 0;
	const u32 total = Level().Objects.o_count();
	for (u32 i = 0; i < total; ++i)
	{
		CObject* object = Level().Objects.o_get_by_iterator(i);
		if (!object || object->getDestroy()) continue;
		if (smart_cast<CActor*>(object)) ++players;
		else if (smart_cast<CAI_Stalker*>(object)) ++stalkers;
		else if (smart_cast<CCustomMonster*>(object)) ++mutants;
		else if (smart_cast<CInventoryItem*>(object)) { if (!object->H_Parent()) ++ground; }
		else if (smart_cast<CPhysicObject*>(object)) ++props;
	}
	u32 alife_total = 0, alife_online = 0;
	if (ai().get_alife())
		for (const auto& entry : ai().alife().objects().objects())
		{
			++alife_total;
			if (entry.second && entry.second->m_bOnline) ++alife_online;
		}
	Msg("[Lost Zone][world] online: %u objects, %u stalkers, %u mutants, %u players, %u items on the ground, %u props"
		" | ALife %u objects, %u online", total, stalkers, mutants, players, ground, props, alife_total, alife_online);
}

void metrics_update()
{
	client_death_frame();
	if (!enabled())
		return;
	const u32 dt = Device.dwTimeDelta;
	const u32 real_now = real_time_ms();
	if (s_frame_last && real_now > s_frame_last)
		s_frame_ema += (float(_min(real_now - s_frame_last, 250u)) - s_frame_ema) * 0.05f;
	s_frame_last = real_now;
	++m.frames;
	++s_frame_hist[_min(dt, 250u)];
	m.frame_ms_sum += dt;
	m.frame_ms_max = _max(m.frame_ms_max, dt);
	if (dt > 33)
		++m.frames_over_33;
	if (dt > 100)
		++m.frames_over_100;

	const u32 now = GetTickCount();
	if (!next_print)
		next_print = now + 10000;
	if (now < next_print)
		return;
	next_print = now + 10000;
	if (g_netcoop_metrics)
	{
		const float day_sec = g_pGameLevel ? Level().GetGameDayTimeSec() : 0.f;
		Msg("[Lost Zone][clock] %s game %02u:%02u factor %.1f | net delta %d ms ping %u ms | snapshot lead avg %d min %d max %d ms"
		    " | players: frames %u extrap %.1f%% lead avg %d max %d ms, largest frame step %.2f m",
		    pure_client() ? "client" : "server", u32(day_sec / 3600.f) % 24, u32(day_sec / 60.f) % 60,
		    g_pGameLevel ? Level().GetGameTimeFactor() : 0.f, g_pGameLevel ? Level().timeServer_Delta() : 0,
		    g_pGameLevel ? Level().GetStatistic().getPing() : 0u,
		    m.puppet_frames ? s32(m.lead_sum / s64(m.puppet_frames)) : 0, m.lead_min, m.lead_max,
		    m.pl_frames, m.pl_frames ? 100.f * m.pl_extrap / m.pl_frames : 0.f,
		    m.pl_frames ? s32(m.pl_lead_sum / s64(m.pl_frames)) : 0, m.pl_lead_max, m.pl_step_max);
		Msg("[Lost Zone][metrics] %s smooth=%d delay=%u | frame avg %.1f max %u >33ms %u >100ms %u"
		    " | snaps %u avg %.0f max %u >100ms %u dup %u | puppets %u extrap %.1f%% jumps %u max %.2f"
		    " | actor acks %u fixes %u err avg %.2f max %.2f | owner rejects %u max %.1f | shots %u"
		    " | sent %.1f KB/s objects %u blocked %u",
		    pure_client() ? "client" : "server", g_netcoop_smooth, remote_interp_delay(),
		    m.frames ? float(m.frame_ms_sum) / m.frames : 0.f, m.frame_ms_max, m.frames_over_33, m.frames_over_100,
		    m.snaps, m.snaps ? float(m.snap_ms_sum) / m.snaps : 0.f, m.snap_ms_max, m.snaps_over_100, m.dups,
		    m.puppet_frames, m.puppet_frames ? 100.f * m.extrap_frames / m.puppet_frames : 0.f, m.jumps, m.jump_max,
		    m.acks, m.fixes, m.acks ? m.err_sum / m.acks : 0.f, m.err_max, m.owner_rejects, m.owner_reject_max,
		    m.shots, m.sv_bytes / 1024.f / 10.f, m.sv_objects, m.sv_blocked);
		if (m.frames)
			Msg("[Lost Zone][frames] %s %u frames: p50 %u p95 %u p99 %u max %u ms", pure_client() ? "client" : "server", m.frames,
				frame_percentile(m.frames, 0.5f), frame_percentile(m.frames, 0.95f), frame_percentile(m.frames, 0.99f),
				m.frame_ms_max);
		if (!pure_client())
		{
			const double to_ms = 1000.0 / double(CPU::qpc_freq) / 10.0; // per second of the 10 s window
			static u64 physics_seen = 0;
			const u64 physics_now = g_ph_frame_ticks;
			const u64 physics_ticks = physics_now >= physics_seen ? physics_now - physics_seen : physics_now;
			physics_seen = physics_now;
			Msg("[Lost Zone][profile] ai %.1f ms/s (%u thinks, NPC update every avg %u max %u ms, %u NPCs) | replication %.1f ms/s"
				" | items %.1f ms/s | physics %.1f ms/s | io %.1f ms/s (%u world saves)",
				double(s_prof_ticks[prof_ai]) * to_ms, s_prof_calls[prof_ai], s_ai_updates ? s_ai_interval_sum / s_ai_updates : 0,
				s_ai_interval_max, u32(s_ai_last_update.size()), double(s_prof_ticks[prof_replication]) * to_ms,
				double(s_prof_ticks[prof_items]) * to_ms, double(physics_ticks) * to_ms, double(s_prof_ticks[prof_io]) * to_ms,
				s_prof_calls[prof_io]);
			metric_world_counts();
		}
		if (s_ai_notices)
			Msg("[Lost Zone][metrics] ai noticed players %u avg %u max %u ms in view", s_ai_notices,
				s_ai_notice_sum / s_ai_notices, s_ai_notice_max);
		if (s_ai_reactions || s_ai_unseen)
			Msg("[Lost Zone][metrics] ai reactions to players %u avg %u max %u ms, without sight %u",
				s_ai_reactions, s_ai_reactions ? s_ai_reaction_sum / s_ai_reactions : 0, s_ai_reaction_max, s_ai_unseen);
	}
	s_ai_reactions = s_ai_reaction_sum = s_ai_reaction_max = s_ai_unseen = 0;
	s_ai_notices = s_ai_notice_sum = s_ai_notice_max = 0;
	memset(s_frame_hist, 0, sizeof(s_frame_hist));
	for (u32 i = 0; i < prof_count; ++i) { s_prof_ticks[i] = 0; s_prof_calls[i] = 0; }
	s_ai_updates = s_ai_interval_sum = s_ai_interval_max = 0;
	if (s_ai_last_update.size() > 4096) s_ai_last_update.clear();
	ZeroMemory(&m, sizeof(m));
	if (puppets.size() > 4096)
		puppets.clear();
	if (shot_log_time.size() > 4096)
		shot_log_time.clear();
}
} // namespace netcoop

void netcoop_respawn_spawn(ClientID id); // game_sv_single.cpp
namespace netcoop
{
static xr_set<u16> s_admin_god_actors;

void server_actor_god_rebind(xrClientData* client, u16 previous_actor, u16 actor_id)
{
	if (!enabled() || pure_client()) return;
	s_admin_god_actors.erase(previous_actor);
	if (client && !client->flags.bLocal && client->netcoop_role == role_admin &&
		client->netcoop_admin_god && actor_id != u16(-1)) s_admin_god_actors.insert(actor_id);
}

bool server_actor_god(const CActor* actor)
{
	if (!actor || !enabled() || pure_client() || !g_pGameLevel || !Level().Server)
		return false;
	// Ordinary players never scan the client pool during condition updates.
	if (s_admin_god_actors.find(actor->ID()) == s_admin_god_actors.end()) return false;
	FindActorOwner find;
	find.actor_id = actor->ID();
	xrClientData* CL = static_cast<xrClientData*>(Level().Server->FindClient(find));
	const bool active = CL && CL->netcoop_role == role_admin && CL->netcoop_admin_god;
	if (!active) s_admin_god_actors.erase(actor->ID());
	return active;
}

bool script_admin_god_enabled(u16 actor_id)
{
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server) return false;
	return server_actor_god(smart_cast<CActor*>(Level().Objects.net_Find(actor_id)));
}

bool script_admin_god_set(u16 actor_id, bool value)
{
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server) return false;
	FindActorOwner find;
	find.actor_id = actor_id;
	xrClientData* CL = static_cast<xrClientData*>(Level().Server->FindClient(find));
	CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(actor_id));
	if (!CL || CL->netcoop_role != role_admin || !actor || !actor->g_Alive()) return false;
	CL->netcoop_admin_god = value;
	if (value) s_admin_god_actors.insert(actor_id);
	else s_admin_god_actors.erase(actor_id);
	return true;
}

// Admin unlimited ammo (owner 2026-10-18: the F7 toggle did nothing online):
// the player's server copy of a weapon keeps its magazine; the client keeps
// its own with the actor flag. Only while the account is an admin.
static xr_set<u16> s_admin_ammo_actors;

bool server_actor_unlimited_ammo(const CActor* actor)
{
	if (!actor || !enabled() || pure_client() || !g_pGameLevel || !Level().Server)
		return false;
	if (s_admin_ammo_actors.find(actor->ID()) == s_admin_ammo_actors.end()) return false;
	FindActorOwner find;
	find.actor_id = actor->ID();
	xrClientData* CL = static_cast<xrClientData*>(Level().Server->FindClient(find));
	const bool active = CL && CL->netcoop_role == role_admin;
	if (!active) s_admin_ammo_actors.erase(actor->ID());
	return active;
}

bool script_admin_ammo_enabled(u16 actor_id)
{
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server) return false;
	return server_actor_unlimited_ammo(smart_cast<CActor*>(Level().Objects.net_Find(actor_id)));
}

bool script_admin_ammo_set(u16 actor_id, bool value)
{
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server) return false;
	FindActorOwner find;
	find.actor_id = actor_id;
	xrClientData* CL = static_cast<xrClientData*>(Level().Server->FindClient(find));
	CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(actor_id));
	if (!CL || CL->netcoop_role != role_admin || !actor || !actor->g_Alive()) return false;
	if (value) s_admin_ammo_actors.insert(actor_id);
	else s_admin_ammo_actors.erase(actor_id);
	return true;
}

bool script_admin_teleport(u16 actor_id, const Fvector& position)
{
	if (!enabled() || pure_client() || !g_pGameLevel || !Level().Server || !_valid(position)) return false;
	FindActorOwner find;
	find.actor_id = actor_id;
	xrClientData* CL = static_cast<xrClientData*>(Level().Server->FindClient(find));
	CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(actor_id));
	if (!CL || CL->netcoop_role != role_admin || !actor || !actor->g_Alive() ||
		!server_character_accepts(CL, M_NETANOMALY_CMD) ||
		!Level().ObjectSpace.GetBoundingVolume().contains(position)) return false;
	Fvector rotation;
	rotation.set(-CL->m_current_intent.pitch, CL->m_current_intent.yaw, 0.f);
	actor->MoveActor(position, rotation);
	CL->owner->o_Position.set(actor->Position());
	CL->m_pending_inputs.clear();
	CL->m_pending_jump_edge = false;
	CL->m_current_intent.mstate = 0;
	// Keep input/ACK sequence numbers monotonic across the teleport.
	NET_Packet packet;
	CGameObject::u_EventGen(packet, GE_MOVE_ACTOR, actor_id);
	packet.w_vec3(actor->Position());
	packet.w_vec3(rotation);
	Level().Server->SendTo(CL->ID, packet, net_flags(TRUE, TRUE));
	return true;
}

bool script_admin_noclip(u16 actor_id, bool value)
{
	if(!enabled() || pure_client() || !g_pGameLevel || !Level().Server)return false;
	FindActorOwner find;find.actor_id=actor_id;
	auto* client=static_cast<xrClientData*>(Level().Server->FindClient(find));
	auto* actor=smart_cast<CActor*>(Level().Objects.net_Find(actor_id));
	if(!client || client->netcoop_role!=role_admin || !actor || !actor->g_Alive() || actor->netcoop_seated() || !server_character_accepts(client,M_NETANOMALY_CMD))return false;
	actor->netcoop_set_noclip(value);
	script_send_to_actor(actor_id,"netcoop_noclip",value ? "1":"0");
	Msg("[diag][admin] actor=%u noclip=%u",actor_id,u32(value));
	return true;
}

bool script_respawn(u16 actor_id)
{
	if (!enabled() || !g_pGameLevel || !Level().Server)
		return false;
	xrServer* server = Level().Server;
	FindActorOwner find;
	find.actor_id = actor_id;
	xrClientData* CL = static_cast<xrClientData*>(server->FindClient(find));
	if (!CL || !CL->owner)
		return false;
	CActor* body = smart_cast<CActor*>(Level().Objects.net_Find(actor_id));
	if (!body || body->g_Alive())
		return false;
	// Keep the dead checkpoint and corpse. A new life is created only after
	// account authentication and a different Russian call sign in the room.
	if (!character_save_actor(actor_id,nullptr,false)) return false;
	Character* character=character_load(CL->netcoop_login.c_str(),CL->netcoop_character_slot);
	if(!character)return false;
	if(character->lives_remaining) {
		s_actor_character.erase(actor_id);
		server_release_task_manager(actor_id);
		give_to_server(server,CL->owner,0);
		CL->owner=nullptr;
		netcoop_respawn_spawn(CL->ID);
		Msg("[diag][respawn] client=%u corpse=%u lives_remaining=%u",CL->ID.value(),actor_id,u32(character->lives_remaining));
		return CL->owner!=nullptr;
	}
	Msg("[diag][character] life ended actor=%u; returning to account room",actor_id);
	return script_send_to_actor(actor_id,"netcoop_life_ended","");
}
} // namespace netcoop
