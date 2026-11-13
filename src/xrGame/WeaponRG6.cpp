#include "stdafx.h"
#include "WeaponRG6.h"

extern BOOL g_launcher_dynamic_range_zoom;
#include "entity.h"
#include "explosiveRocket.h"
#include "level.h"
#include "../xrphysics/MathUtils.h"
#include "actor.h"
#include "netcoop.h"

#ifdef DEBUG
#	include "phdebug.h"
#endif


CWeaponRG6::~CWeaponRG6()
{
}

BOOL CWeaponRG6::net_Spawn(CSE_Abstract* DC)
{
	m_netcoop_launch_pending = false;
	m_netcoop_rockets_spawning = 0;
	BOOL l_res = inheritedSG::net_Spawn(DC);
	if (!l_res) return l_res;

	if (iAmmoElapsed && !getCurrentRocket() && !m_netcoop_rockets_spawning)
	{
		// Restored cylinders can contain different grenade types. Recreate
		// each projectile from its cartridge, not the first supported ammo.
		for (const auto& cartridge : m_magazine)
		{
			shared_str fake = pSettings->r_string(cartridge.m_ammoSect, "fake_grenade_name");
			if (fake.size())
			{
				if (netcoop::enabled() && OnServer()) ++m_netcoop_rockets_spawning;
				inheritedRL::SpawnRocket(fake, this);
			}
		}
	}


	return l_res;
};

void CWeaponRG6::Load(LPCSTR section)
{
	inheritedRL::Load(section);
	inheritedSG::Load(section);
}

#include "inventory.h"
#include "inventoryOwner.h"

void CWeaponRG6::FireStart()
{
	const bool network_player = netcoop::enabled() && ParentIsActor() &&
		(netcoop::pure_client() || netcoop::server_player_copy(H_Parent()));
	// A client's launcher may not have received its child projectile yet.
	// The round in the magazine, not that replica, permits requesting a shot.
	if (GetState() == eIdle && iAmmoElapsed && (network_player || getRocketCount()))
	{
		inheritedSG::FireStart();
		// A player's grenade: the owner sends the shot (FireTrace), the server
		// launches it (netcoop_fire_shot); here only the shot animation plays.
		if (network_player)
			return;
#ifdef CROCKETLAUNCHER_CHANGE
		LPCSTR ammo_name = m_ammoTypes[m_ammoType].c_str();
		float launch_speed = READ_IF_EXISTS(pSettings, r_float, ammo_name, "ammo_grenade_vel", CRocketLauncher::m_fLaunchSpeed);
#endif

		Fvector p1, d;
		p1.set(get_LastFP());
		d.set(get_LastFD());

		CEntity* E = smart_cast<CEntity*>(H_Parent());
		if (E)
		{
			CInventoryOwner* io = smart_cast<CInventoryOwner*>(H_Parent());
			if (NULL == io->inventory().ActiveItem())
			{
				Log("current_state", GetState());
				Log("next_state", GetNextState());
				Log("item_sect", cNameSect().c_str());
				Log("H_Parent", H_Parent()->cNameSect().c_str());
			}
			E->g_fireParams(this, p1, d);
		}

		Fmatrix launch_matrix;
		launch_matrix.identity();
		launch_matrix.k.set(d);
		Fvector::generate_orthonormal_basis(launch_matrix.k,
		                                    launch_matrix.j, launch_matrix.i);
		launch_matrix.c.set(p1);

		if (IsZoomed() && smart_cast<CActor*>(H_Parent()) && g_launcher_dynamic_range_zoom)
		{
			H_Parent()->setEnabled(FALSE);
			setEnabled(FALSE);

			collide::rq_result RQ;
			BOOL HasPick = Level().ObjectSpace.RayPick(p1, d, 300.0f, collide::rqtStatic, RQ, this);

			setEnabled(TRUE);
			H_Parent()->setEnabled(TRUE);

			if (HasPick)
			{
				//			collide::rq_result& RQ = HUD().GetCurrentRayQuery();
				Fvector Transference;
				//Transference.add(p1, Fvector().mul(d, RQ.range));				
				Transference.mul(d, RQ.range);
				Fvector res[2];
				/*#ifdef		DEBUG
								DBG_OpenCashedDraw();
								DBG_DrawLine(p1,Fvector().add(p1,d),D3DCOLOR_XRGB(255,0,0));
				#endif*/
#ifdef CROCKETLAUNCHER_CHANGE
				u8 canfire0 = TransferenceAndThrowVelToThrowDir(Transference, launch_speed, EffectiveGravity(), res);
#else
				u8 canfire0 = TransferenceAndThrowVelToThrowDir(Transference, CRocketLauncher::m_fLaunchSpeed,
				                                                EffectiveGravity(), res);
#endif
				/*#ifdef DEBUG
								if(canfire0>0)DBG_DrawLine(p1,Fvector().add(p1,res[0]),D3DCOLOR_XRGB(0,255,0));
								if(canfire0>1)DBG_DrawLine(p1,Fvector().add(p1,res[1]),D3DCOLOR_XRGB(0,0,255));
								DBG_ClosedCashedDraw(30000);
				#endif*/
				if (canfire0 != 0)
				{
					//					Msg ("d[%f,%f,%f] - res [%f,%f,%f]", d.x, d.y, d.z, res[0].x, res[0].y, res[0].z);
					d = res[0];
				};
			}
		};

		d.normalize();
#ifdef CROCKETLAUNCHER_CHANGE
		d.mul(launch_speed);
#else
		d.mul(m_fLaunchSpeed);
#endif
		VERIFY2(_valid(launch_matrix), "CWeaponRG6::FireStart. Invalid launch_matrix");
		CRocketLauncher::LaunchRocket(launch_matrix, d, zero_vel);

		CExplosiveRocket* pGrenade = smart_cast<CExplosiveRocket*>(getCurrentRocket());
		VERIFY(pGrenade);
		pGrenade->SetInitiator(H_Parent()->ID());

		if (OnServer())
		{
			NET_Packet P;
			u_EventGen(P, GE_LAUNCH_ROCKET, ID());
			P.w_u16(u16(getCurrentRocket()->ID()));
			netcoop_write_launch(P, getCurrentRocket());
			u_EventSend(P);
		}
		dropCurrentRocket();
	}
}

void CWeaponRG6::FireTrace(const Fvector& P, const Fvector& D)
{
	if (netcoop::enabled() && ParentIsActor())
	{
		// The server launches the grenade; no invisible hitscan shell as well.
		if (netcoop::pure_client() && iAmmoElapsed && !m_magazine.empty())
		{
			netcoop_send_shot(P, D, 1);
			netcoop_consume_projectile();
		}
		return;
	}
	inheritedSG::FireTrace(P, D);
}

bool CWeaponRG6::netcoop_fire_shot(u8 kind, const Fvector& pos, const Fvector& dir)
{
	if (kind != 1 || !OnServer() || !H_Parent() || !iAmmoElapsed || m_magazine.empty() || m_netcoop_launch_pending) return false;
#ifdef CROCKETLAUNCHER_CHANGE
	LPCSTR ammo_name = m_ammoTypes[m_ammoType].c_str();
	const float launch_speed = READ_IF_EXISTS(pSettings, r_float, ammo_name, "ammo_grenade_vel", CRocketLauncher::m_fLaunchSpeed);
#else
	const float launch_speed = m_fLaunchSpeed;
#endif
	if (!getRocketCount())
	{
		// Reload/spawn ownership arrives asynchronously. Reserve this shot,
		// rather than consuming the client's predicted shot without launching.
		m_netcoop_launch_pending = true;
		m_netcoop_launch_owner = H_Parent()->ID();
		m_netcoop_launch_pos = pos; m_netcoop_launch_dir = dir;
		m_netcoop_launch_speed = launch_speed;
		if (!m_netcoop_rockets_spawning)
		{
			shared_str fake = pSettings->r_string(m_magazine.back().m_ammoSect, "fake_grenade_name");
			++m_netcoop_rockets_spawning;
			inheritedRL::SpawnRocket(fake, this);
		}
	}
	else if (!netcoop_launch_grenade(pos, dir, launch_speed)) return false;
	OnShot();
	netcoop_consume_projectile();
	return true;
}

bool CWeaponRG6::netcoop_launch_grenade(const Fvector& pos, const Fvector& dir, float speed)
{
	if (!getRocketCount() || !H_Parent()) return false;
	Fvector velocity;
	velocity.set(dir).normalize_safe();
	Fmatrix launch;
	launch.identity();
	launch.k.set(velocity);
	Fvector::generate_orthonormal_basis(launch.k, launch.j, launch.i);
	launch.c.set(pos);
	velocity.mul(speed);
	CRocketLauncher::LaunchRocket(launch, velocity, zero_vel);
	if (CExplosiveRocket* grenade = smart_cast<CExplosiveRocket*>(getCurrentRocket()))
		grenade->SetInitiator(H_Parent()->ID());
	NET_Packet P;
	u_EventGen(P, GE_LAUNCH_ROCKET, ID());
	P.w_u16(u16(getCurrentRocket()->ID()));
	netcoop_write_launch(P, getCurrentRocket());
	u_EventSend(P);
	dropCurrentRocket();
	return true;
}

void CWeaponRG6::netcoop_finish_pending_launch()
{
	if (!m_netcoop_launch_pending || !getRocketCount()) return;
	m_netcoop_launch_pending = false;
	// A late ownership event must not fire from a different player's weapon.
	if (!OnServer() || !H_Parent() || H_Parent()->ID() != m_netcoop_launch_owner || getDestroy()) return;
	netcoop_launch_grenade(m_netcoop_launch_pos, m_netcoop_launch_dir, m_netcoop_launch_speed);
}

void CWeaponRG6::netcoop_shot_effect(u8 kind)
{
	if (kind == 1) OnShot();
}

u8 CWeaponRG6::AddCartridge(u8 cnt)
{
	u8 t = inheritedSG::AddCartridge(cnt);
	u8 k = cnt - t;
	shared_str fake_grenade_name = pSettings->r_string(m_ammoTypes[m_ammoType].c_str(), "fake_grenade_name");
	while (k)
	{
		--k;
		if (netcoop::enabled() && OnServer()) ++m_netcoop_rockets_spawning;
		inheritedRL::SpawnRocket(*fake_grenade_name, this);
	}
	return t;
}

void CWeaponRG6::OnEvent(NET_Packet& P, u16 type)
{
	inheritedSG::OnEvent(P, type);

	u16 id;
	switch (type)
	{
	case GE_OWNERSHIP_TAKE:
		{
			P.r_u16(id);
			const u32 count = getRocketCount();
			inheritedRL::AttachRocket(id, this);
			if (getRocketCount() > count)
			{
				if (m_netcoop_rockets_spawning) --m_netcoop_rockets_spawning;
				netcoop_finish_pending_launch();
			}
		}
		break;
	case GE_OWNERSHIP_REJECT:
	case GE_LAUNCH_ROCKET:
		{
			bool bLaunch = (type == GE_LAUNCH_ROCKET);
			P.r_u16(id);
			if (bLaunch) netcoop_read_launch(P, id);
			inheritedRL::DetachRocket(id, bLaunch);
		}
		break;
	}
}

#ifdef CROCKETLAUNCHER_CHANGE
void CWeaponRG6::UnloadRocket()
{
	while (getRocketCount() > 0)
	{
		Msg("%s:%d [%d]-[%s]", __FUNCTION__, __LINE__, getRocketCount(), getCurrentRocket()->cNameSect_str());
		NET_Packet P;
		u_EventGen(P, GE_OWNERSHIP_REJECT, ID());
		P.w_u16(u16(getCurrentRocket()->ID()));
		u_EventSend(P);
        dropCurrentRocket();
	}
}
#endif
