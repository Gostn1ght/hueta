#pragma once

#include "rocketlauncher.h"
#include "weaponShotgun.h"
#include "script_export_space.h"

class CWeaponRG6 : public CRocketLauncher,
                   public CWeaponShotgun
{
	typedef CRocketLauncher inheritedRL;
	typedef CWeaponShotgun inheritedSG;

public:
	virtual ~CWeaponRG6();
	virtual BOOL net_Spawn(CSE_Abstract* DC);
	virtual void Load(LPCSTR section);
	virtual void OnEvent(NET_Packet& P, u16 type);

#ifdef CROCKETLAUNCHER_CHANGE
	virtual void UnloadRocket();
#endif

	// Netcoop (owner 2026-10-17: the Bulldog and similar launchers did not
	// work): the owner sends the shot, the server launches the grenade.
	bool netcoop_fire_shot(u8 kind, const Fvector& pos, const Fvector& dir) override;
	void netcoop_shot_effect(u8 kind) override;

protected:
	bool m_netcoop_launch_pending = false;
	u32 m_netcoop_rockets_spawning = 0;
	u16 m_netcoop_launch_owner = u16(-1);
	Fvector m_netcoop_launch_pos, m_netcoop_launch_dir;
	float m_netcoop_launch_speed = 0.f;
	bool netcoop_launch_grenade(const Fvector& pos, const Fvector& dir, float speed);
	void netcoop_finish_pending_launch();
	virtual void FireStart();
	virtual void FireTrace(const Fvector& P, const Fvector& D);
	virtual u8 AddCartridge(u8 cnt);

DECLARE_SCRIPT_REGISTER_FUNCTION
};
