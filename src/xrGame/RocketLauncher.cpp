//////////////////////////////////////////////////////////////////////
// RocketLauncher.cpp:	интерфейс для семейства объектов 
//						стреляющих гранатами и ракетами
//////////////////////////////////////////////////////////////////////

#include "stdafx.h"
#include "RocketLauncher.h"
#include "CustomRocket.h"
#include "xrserver_objects_alife_items.h"
#include "level.h"
#include "ai_object_location.h"
#include "../xrEngine/IGame_Persistent.h"

CRocketLauncher::CRocketLauncher()
{
	//	m_pRocket =  NULL;
}

CRocketLauncher::~CRocketLauncher()
{
}

void CRocketLauncher::Load(LPCSTR section)
{
	m_fLaunchSpeed = pSettings->r_float(section, "launch_speed");
}

void CRocketLauncher::SpawnRocket(const shared_str& rocket_section, CGameObject* parent_rocket_launcher)
{
	if (OnClient()) return;

	CSE_Abstract* D = F_entity_Create(rocket_section.c_str());
	R_ASSERT(D);
	CSE_Temporary* l_tpTemporary = smart_cast<CSE_Temporary*>(D);
	R_ASSERT(l_tpTemporary);
	l_tpTemporary->m_tNodeID = (g_dedicated_server) ? u32(-1) : parent_rocket_launcher->ai_location().level_vertex_id();
	D->s_name = rocket_section;
	D->set_name_replace("");

	//.	D->s_gameid			=	u8(GameID());
	D->s_RP = 0xff;
	D->ID = 0xffff;
	D->ID_Parent = parent_rocket_launcher->ID();
	D->ID_Phantom = 0xffff;
	D->s_flags.assign(M_SPAWN_OBJECT_LOCAL);
	D->RespawnTime = 0;

	NET_Packet P;
	D->Spawn_Write(P,TRUE);
	Level().Send(P, net_flags(TRUE));
	F_entity_Destroy(D);
}

void CRocketLauncher::AttachRocket(u16 rocket_id, CGameObject* parent_rocket_launcher)
{
	CCustomRocket* pRocket = smart_cast<CCustomRocket*>(Level().Objects.net_Find(rocket_id));
	if (!pRocket || !parent_rocket_launcher || pRocket->getDestroy())
	{
		Msg("! [diag][projectile] attach missing rocket=%u", rocket_id);
		return;
	}
	pRocket->m_pOwner = smart_cast<CGameObject*>(parent_rocket_launcher->H_Root());
	VERIFY(pRocket->m_pOwner);
	pRocket->H_SetParent(parent_rocket_launcher);
	if (std::find(m_rockets.begin(), m_rockets.end(), pRocket) == m_rockets.end()) m_rockets.push_back(pRocket);
}

void CRocketLauncher::DetachRocket(u16 rocket_id, bool bLaunch)
{
	CCustomRocket* pRocket = smart_cast<CCustomRocket*>(Level().Objects.net_Find(rocket_id));
	if (!pRocket) return;
	ROCKETIT It = std::find(m_rockets.begin(), m_rockets.end(), pRocket);
	ROCKETIT It_l = std::find(m_launched_rockets.begin(), m_launched_rockets.end(), pRocket);

	if (It == m_rockets.end() && It_l == m_launched_rockets.end()) return;
	// LaunchRocket places the same pointer in both lists. Detach once, before
	// erasing either iterator; the loaded iterator may already be end/invalid.
	pRocket->m_bLaunched = bLaunch;
	if (pRocket->H_Parent()) pRocket->H_SetParent(NULL);
	if (It != m_rockets.end()) m_rockets.erase(It);
	if (It_l != m_launched_rockets.end()) m_launched_rockets.erase(It_l);
}


void CRocketLauncher::LaunchRocket(const Fmatrix& xform,
                                   const Fvector& vel,
                                   const Fvector& angular_vel)
{
	VERIFY2(_valid(xform), "CRocketLauncher::LaunchRocket. Invalid xform argument!");
	getCurrentRocket()->SetLaunchParams(xform, vel, angular_vel);

	m_launched_rockets.push_back(getCurrentRocket());
}

void CRocketLauncher::netcoop_write_launch(NET_Packet& P, CCustomRocket* rocket)
{
	if (!rocket) return;
	P.w_vec3(rocket->netcoop_launch_xform().c);
	P.w_vec3(rocket->netcoop_launch_xform().k);
	P.w_vec3(rocket->netcoop_launch_velocity());
}

void CRocketLauncher::netcoop_read_launch(NET_Packet& P, u16 rocket_id)
{
	// Older servers send the id only; the server launched its copy itself.
	if (!OnClient() || P.r_elapsed() < 3 * sizeof(Fvector)) return;
	Fvector position, direction, velocity;
	P.r_vec3(position);
	P.r_vec3(direction);
	P.r_vec3(velocity);
	CCustomRocket* rocket = smart_cast<CCustomRocket*>(Level().Objects.net_Find(rocket_id));
	if (!rocket || std::find(m_rockets.begin(), m_rockets.end(), rocket) == m_rockets.end()) return;
	if (!_valid(position) || !_valid(direction) || !_valid(velocity) || direction.square_magnitude() < EPS) return;
	Fmatrix launch;
	launch.identity();
	launch.k.set(direction).normalize();
	Fvector::generate_orthonormal_basis(launch.k, launch.j, launch.i);
	launch.c.set(position);
	rocket->SetLaunchParams(launch, velocity, Fvector().set(0.f, 0.f, 0.f));
}

CCustomRocket* CRocketLauncher::getCurrentRocket()
{
	if (m_rockets.size())
		return m_rockets.back();
	else
		return (CCustomRocket*)0;
}

void CRocketLauncher::dropCurrentRocket()
{
	m_rockets.pop_back();
}

u32 CRocketLauncher::getRocketCount()
{
	return m_rockets.size();
}
