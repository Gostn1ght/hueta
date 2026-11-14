#include "stdafx.h"
#include "../../../netcoop.h"
#include "base_monster.h"

#include "../../../ai_object_location.h"
#include "../../../game_graph.h"
#include "../../../ai_space.h"
#include "../../../hit.h"
#include "../../../PHDestroyable.h"
#include "../../../CharacterPhysicsSupport.h"
#include "../../../Level.h"
#include "../control_manager.h"
#include "../control_animation.h"
#include "../../../../Include/xrRender/KinematicsAnimated.h"

void CBaseMonster::net_Save(NET_Packet& P)
{
	inherited::net_Save(P);
	m_pPhysics_support->in_NetSave(P);
}

BOOL CBaseMonster::net_SaveRelevant()
{
	return (inherited::net_SaveRelevant() || BOOL(PPhysicsShell() != NULL));
}

void CBaseMonster::net_Export(NET_Packet& P)
{
	R_ASSERT(Local());

	// export last known packet
	R_ASSERT(!NET.empty());
	net_update& N = NET.back();
	P.w_float(GetfHealth());
	// Netcoop: current state and time instead of the AI schedule's last record
	// (see CAI_Stalker::net_Export).
	if (netcoop::smooth())
	{
		float h, p, b;
		XFORM().getHPB(h, p, b);
		P.w_u32(Level().timeServer());
		P.w_u8(0);
		P.w_vec3(Position());
		P.w_float(angle_normalize(-h));
	}
	else
	{
		P.w_u32(N.dwTimeStamp);
		P.w_u8(0);
		P.w_vec3(N.p_pos);
		P.w_float /*w_angle8*/(N.o_model);
	}
	P.w_float /*w_angle8*/(N.o_torso.yaw);
	P.w_float /*w_angle8*/(N.o_torso.pitch);
	P.w_float /*w_angle8*/(N.o_torso.roll);
	P.w_u8(u8(g_Team()));
	P.w_u8(u8(g_Squad()));
	P.w_u8(u8(g_Group()));

	GameGraph::_GRAPH_ID l_game_vertex_id = ai_location().game_vertex_id();
	P.w(&l_game_vertex_id, sizeof(l_game_vertex_id));
	P.w(&l_game_vertex_id, sizeof(l_game_vertex_id));
	//	P.w						(&m_fGoingSpeed,			sizeof(m_fGoingSpeed));
	//	P.w						(&m_fGoingSpeed,			sizeof(m_fGoingSpeed));
	float f1 = 0;
	if (ai().valid_game_vertex(l_game_vertex_id))
	{
		f1 = Position().distance_to(ai().game_graph().vertex(l_game_vertex_id)->level_point());
		P.w(&f1, sizeof(f1));
		f1 = Position().distance_to(ai().game_graph().vertex(l_game_vertex_id)->level_point());
		P.w(&f1, sizeof(f1));
	}
	else
	{
		P.w(&f1, sizeof(f1));
		P.w(&f1, sizeof(f1));
	}

	u32 motion = u32(-1);
	float motion_speed = 1.f;
	if (netcoop::enabled() && m_control_manager && control().animation_com())
	{
		const MotionID m = control().animation_com()->netcoop_global_motion(motion_speed);
		if (m.valid())
			motion = m.val;
		if (!_valid(motion_speed))
			motion_speed = 1.f;
	}
	P.w_u32(motion);
	P.w_float(motion_speed);
	P.w_float(netcoop::enabled() && m_control_manager && control().animation_com() ?
		control().animation_com()->netcoop_global_phase() : 0.f);
}

// Snapshot MotionID values are local indexes. A missing/different library
// must never index the renderer's slots or motion definitions unchecked.
static bool netcoop_monster_motion_valid(IKinematicsAnimated* model, const MotionID& motion)
{
    if (!model || !motion.valid() || motion.slot >= model->LL_MotionsSlotCount()) return false;
    shared_motions motions = model->LL_MotionsSlot(motion.slot);
    return motion.idx < motions.motion_defs()->size();
}

void CBaseMonster::netcoop_play_motion()
{
    IKinematicsAnimated* K = smart_cast<IKinematicsAnimated*>(Visual());
    if (!K || m_netcoop_motion == u32(-1)) return;
    MotionID motion; motion.val = m_netcoop_motion;
    if (!netcoop_monster_motion_valid(K, motion) ||
        !_valid(m_netcoop_motion_speed) || !_valid(m_netcoop_phase)) return;
    struct Synchronize : IterateBlendsCallback
    {
        MotionID motion; float phase, speed; bool restart, found = false;
        Synchronize(MotionID m, float p, float s, bool r) : motion(m), phase(p), speed(s), restart(r) {}
        void operator()(CBlend& blend) override
        {
            if (blend.motionID.val != motion.val || blend.blend_state() == CBlend::eFalloff) return;
            found = true;
            const float duration = _max(EPS, blend.timeTotal - SAMPLE_SPF - EPS);
            const float target = _max(0.f, _min(phase, duration));
            float difference = target - blend.timeCurrent;
            if (!blend.stop_at_end)
            {
                if (difference > duration * .5f) difference -= duration;
                if (difference < -duration * .5f) difference += duration;
            }
            else if (restart)
            {
                blend.timeCurrent = target;
                blend.playing = TRUE;
                difference = 0.f;
            }
            // Continuous rate correction retains smooth motion across snapshot boundaries.
            blend.speed = _max(.01f, speed + _max(-.2f, _min(.2f, difference * 2.f)));
        }
    } sync(motion, m_netcoop_phase, m_netcoop_motion_speed,
        m_netcoop_phase + .05f < m_netcoop_phase_played);
    if (m_netcoop_motion == m_netcoop_motion_played) K->LL_IterateBlends(sync);
    if (!sync.found)
    {
        u16 part = K->LL_GetMotionDef(motion)->bone_or_part;
        if (part == u16(-1)) part = K->LL_PartID("default");
        if (CBlend* blend = K->LL_PlayCycle(part, motion, TRUE, 0, 0))
        {
            blend->speed = _max(.01f, m_netcoop_motion_speed);
            blend->timeCurrent = _max(0.f, _min(m_netcoop_phase, _max(0.f, blend->timeTotal - SAMPLE_SPF - EPS)));
        }
        m_netcoop_motion_played = m_netcoop_motion;
    }
    m_netcoop_phase_played = m_netcoop_phase;
    K->UpdateTracks();
}

void CBaseMonster::net_Import(NET_Packet& P)
{
	R_ASSERT(Remote());
	// A late datagram must not roll back health/equipment, restart a corpse's
	// live state or replace the interpolation history before it is rejected.
	if (netcoop::pure_client() && Remote() && !NET.empty() &&
		netcoop::snapshot_packet_stale(P, NET.back().dwTimeStamp)) return;

	net_update N;

	u8 flags;

	float health;
	P.r_float(health);
	SetfHealth(health);

	P.r_u32(N.dwTimeStamp);
	P.r_u8(flags);
	P.r_vec3(N.p_pos);
	P.r_float /*r_angle8*/(N.o_model);
	P.r_float /*r_angle8*/(N.o_torso.yaw);
	P.r_float /*r_angle8*/(N.o_torso.pitch);
	P.r_float /*r_angle8*/(N.o_torso.roll);
	{
		const u8 team = P.r_u8();
		const u8 squad = P.r_u8();
		const u8 group = P.r_u8();
		// A monster puppet stays registered (seniority, monster squad) under
		// its spawn team; changing ids here would leave dangling entries.
		if (!(Remote() && netcoop::pure_client() && g_Alive()))
		{
			id_Team = team;
			id_Squad = squad;
			id_Group = group;
		}
	}

	GameGraph::_GRAPH_ID l_game_vertex_id = ai_location().game_vertex_id();
	P.r(&l_game_vertex_id, sizeof(l_game_vertex_id));
	P.r(&l_game_vertex_id, sizeof(l_game_vertex_id));

	const bool puppet = Remote() && netcoop::pure_client();

	//	P.r						(&m_fGoingSpeed,			sizeof(m_fGoingSpeed));
	//	P.r						(&m_fGoingSpeed,			sizeof(m_fGoingSpeed));
	float f1 = 0;
	if (ai().valid_game_vertex(l_game_vertex_id))
	{
		f1 = Position().distance_to(ai().game_graph().vertex(l_game_vertex_id)->level_point());
		P.r(&f1, sizeof(f1));
		f1 = Position().distance_to(ai().game_graph().vertex(l_game_vertex_id)->level_point());
		P.r(&f1, sizeof(f1));
	}
	else
	{
		P.r(&f1, sizeof(f1));
		P.r(&f1, sizeof(f1));
	}
	if (P.r_elapsed() >= sizeof(u32) + sizeof(float))
	{
		P.r_u32(N.monster_motion);
		P.r_float(N.monster_motion_speed);
		N.pose_valid = true;
		if (P.r_elapsed() >= sizeof(float)) P.r_float(N.monster_motion_phase);
	}

	if (NET.empty() || (NET.back().dwTimeStamp < N.dwTimeStamp))
	{
		if (puppet && !NET.empty())
			netcoop::metric_snapshot(N.dwTimeStamp - NET.back().dwTimeStamp);
		if (puppet)
			netcoop::snapshot_sample(N.dwTimeStamp);
		NET.push_back(N);
		NET_WasInterpolating = TRUE;
	}
	else if (puppet)
		netcoop::metric_snapshot_duplicate();

	setVisible(TRUE);
	setEnabled(TRUE);
}
