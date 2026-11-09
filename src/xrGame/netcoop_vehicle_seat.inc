#include "netcoop_vehicle_dynamics.h"
// Included in netcoop.cpp after netcoop_vehicle_client.inc (it closes and
// reopens namespace netcoop): CActor seated in a vehicle (doc 100, doc 151).

// ---------------------------------------------------------------------------
// CActor: sitting in a vehicle (all sides)
// ---------------------------------------------------------------------------
void CActor::netcoop_seat_enter(u16 car, u8 seat, bool driver, const Fmatrix& local, const Fvector& eye)
{
	netcoop_platform_detach(false);
	if(m_netcoop_noclip)netcoop_set_noclip(false);
	const bool was_seated = netcoop_seated();
	m_netcoop_seat_car = car;
	m_netcoop_seat = seat;
	m_netcoop_seat_driver = driver;
	m_netcoop_seat_local.set(local);
	m_netcoop_seat_eye.set(eye);
	m_netcoop_seat_yaw_valid = false;
	m_netcoop_seat_motion.invalidate();
	m_netcoop_seat_phase=0;m_netcoop_seat_phase_start=0;m_netcoop_seat_door=BI_NONE;
	for(auto& blend:m_netcoop_seat_blends) blend=nullptr;
	CCar* vehicle=smart_cast<CCar*>(Level().Objects.net_Find(car));
	m_netcoop_passenger_pose=vehicle ? READ_IF_EXISTS(pSettings,r_string,vehicle->cNameSect(),"netcoop_passenger_pose","animpoint_sit_high_idle_1"):"animpoint_sit_high_idle_1";
	m_netcoop_driver_fit.set(0.f, 0.f, 0.f);
	m_netcoop_driver_fit_at = 0; // the seat anchors the pelvis; never move it to fit the hands
	inventory().netcoop_holster_in_vehicle(); // every replica/authority, including seat switches
	if (CTorch* torch = smart_cast<CTorch*>(inventory().ItemFromSlot(TORCH_SLOT))) torch->Switch(false);
	if (!was_seated)
	{
		CPHMovementControl* movement = character_physics_support() ? character_physics_support()->movement() : nullptr;
		m_netcoop_seat_character = movement && movement->CharacterExist();
		if (m_netcoop_seat_character)
			movement->DestroyCharacter();
		mstate_wishful = 0;
		if (this == Level().CurrentControlEntity())
			SetWeaponHideState(INV_STATE_BLOCK_ALL, true);
		m_current_legs.invalidate();
		m_current_torso.invalidate();
	}
	netcoop_seat_place();
}

void CActor::netcoop_set_noclip(bool enabled)
{
	if(enabled==m_netcoop_noclip || (enabled && netcoop_seated()))return;
	CPHMovementControl* movement=character_physics_support() ? character_physics_support()->movement():nullptr;
	m_netcoop_noclip=enabled;
	if(movement) {
		if(enabled && movement->CharacterExist())movement->DestroyCharacter();
		if(!enabled && !movement->CharacterExist()) {
			movement->CreateCharacter();movement->SetPosition(Position());movement->SetVelocity(0.f,0.f,0.f);
		}
	}
	m_client_prediction_history.clear();
}

void CActor::netcoop_seat_leave(const Fvector& exit)
{
	if (!netcoop_seated())
		return;
	m_netcoop_seat_car = 0xffff;
	m_netcoop_seat_phase=0;
	for(auto& blend:m_netcoop_seat_blends) blend=nullptr;
	m_netcoop_seat_driver = false;
	m_netcoop_seat_motion.invalidate();
	if (this == Level().CurrentControlEntity())
	{
		SetWeaponHideState(INV_STATE_BLOCK_ALL, false);
		m_client_prediction_history.clear();
	}
	CPHMovementControl* movement = character_physics_support() ? character_physics_support()->movement() : nullptr;
	if (movement && m_netcoop_seat_character && !movement->CharacterExist())
	{
		movement->SetPosition(exit); // updates vPosition even while the capsule is absent
		movement->CreateCharacter();
		movement->SetPosition(exit);
		movement->SetVelocity(0.f, 0.f, 0.f);
	}
	m_netcoop_seat_character = false;
	// Upright again, facing where the car faced.
	Fvector xyz;
	XFORM().getXYZi(xyz);
	XFORM().setXYZi(0.f, xyz.y, 0.f);
	Position().set(exit);
	m_current_legs.invalidate();
	m_current_torso.invalidate();
}

void CActor::netcoop_seat_place()
{
	CCar* car = smart_cast<CCar*>(Level().Objects.net_Find(m_netcoop_seat_car));
	if (!car)
		return;
	// The car's replica pose of this frame, not the last one: objects update
	// in no fixed order, so the body and the view shook while driving.
	if (netcoop::pure_client())
		car->netcoop_physics_follow();
	Fmatrix world;
	Fmatrix local = m_netcoop_seat_local;
	Fvector eye=m_netcoop_seat_eye;
	if(m_netcoop_seat_phase) {
		float t=_max(0.f,_min(1.f,float(s32(Level().timeServer()-m_netcoop_seat_phase_start))/1800.f));
		t=t*t*(3.f-2.f*t);
		if(m_netcoop_seat_phase==2) t=1.f-t;
		local.c.lerp(m_netcoop_seat_outside,local.c,t);
		Fvector outside_eye=m_netcoop_seat_outside;outside_eye.y+=1.6f;
		eye.lerp(outside_eye,eye,t);
	}
	world.mul_43(car->XFORM(), local);
	XFORM().set(world);
	car->XFORM().transform_tiny(m_netcoop_seat_eye_world, eye);
	if (netcoop::pure_client() && this == Level().CurrentControlEntity())
	{
		// The view turns with the car.
		Fvector xyz;
		car->XFORM().getXYZi(xyz);
		if (m_netcoop_seat_yaw_valid)
		{
			const float delta = angle_difference_signed(xyz.y, m_netcoop_seat_car_yaw);
			for (int i = 0; i < eacMaxCam; ++i)
				if (cameras[i])
					cameras[i]->yaw += delta;
		}
		m_netcoop_seat_car_yaw = xyz.y;
		m_netcoop_seat_yaw_valid = true;
		netcoop::vehicle_input_tick(this);
	}
	spatial_move();
}

bool CActor::netcoop_seat_animation()
{
	IKinematicsAnimated* k=smart_cast<IKinematicsAnimated*>(Visual());
	if(!k) return false;
	CCar* car=smart_cast<CCar*>(Level().Objects.net_Find(m_netcoop_seat_car));
	MotionID motion;bool freeze=false;float progress=0.f;
	if(m_netcoop_seat_phase) {
		string128 name;xr_sprintf(name,"lz_vehicle_%s_%s",m_netcoop_seat_phase==1 ? "enter":"exit",m_netcoop_seat_driver ? "driver":"passenger");
		motion=k->ID_Cycle_Safe(name);freeze=motion.valid();
		progress=_max(0.f,_min(.999f,float(s32(Level().timeServer()-m_netcoop_seat_phase_start))/1800.f));
	}
	if(!motion.valid() && m_netcoop_seat_driver) {
		u16 type=car ? car->DriverAnimationType():0;
		if(type>=SActorVehicleAnims::TYPES_NUMBER) type=0;
		SVehicleAnimCollection& anims=m_vehicle_anims->m_vehicles_type_collections[type];
		const float steering=car ? car->netcoop_steer():0.f;
		const LPCSTR key=steering<-.015f ? "netcoop_driver_steer_left":steering>.015f ? "netcoop_driver_steer_right":"netcoop_driver_pose";
		const LPCSTR fitted=car ? READ_IF_EXISTS(pSettings,r_string,car->cNameSect(),key,""):"";
		if(fitted && *fitted) motion=k->ID_Cycle_Safe(fitted);
		if(!motion.valid()) motion=steering<-.015f ? anims.steer_left:steering>.015f ? anims.steer_right:anims.idles[0];
		freeze=_abs(steering)>.015f;progress=_min(.999f,_abs(steering)/.6f);
	} else if(!motion.valid()) motion=k->ID_Cycle_Safe(m_netcoop_passenger_pose.c_str());
	if(!motion.valid()) return false;
	if(motion!=m_netcoop_seat_motion) {
		CMotionDef* def=k->LL_GetMotionDef(motion);if(!def) return false;
		const LPCSTR names[]={"legs","torso","head"};
		for(u32 i=0;i<3;++i) {
			const u16 part=k->LL_PartID(names[i]);
			m_netcoop_seat_blends[i]=part!=BI_NONE ? k->LL_PlayCycle(part,motion,TRUE,5.f,5.f,def->Speed(),FALSE,nullptr,nullptr,0):nullptr;
		}
		m_netcoop_seat_motion=motion;
	}
	for(auto* blend:m_netcoop_seat_blends) if(blend) {
		blend->speed=freeze ? 0.f:1.f;
		if(freeze) blend->timeCurrent=netcoop_vehicle_dynamics::frozen_motion_time(progress,blend->timeTotal);
	}
	return true;
}

namespace netcoop
{
