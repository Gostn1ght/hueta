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
	m_netcoop_driver_fit_at = driver && netcoop::pure_client() ? Device.dwTimeGlobal + 400 : 0;
	inventory().netcoop_holster_in_vehicle(); // every replica/authority, including seat switches
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
	if (m_netcoop_seat_driver)
		local.c.add(m_netcoop_driver_fit);
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
	// Hands on the wheel (owner 2026-10-13): once the steering pose plays,
	// the gap between the middle of the hands and the wheel bone moves the
	// driver, within 35 cm each way, in the car's space.
	if (!m_netcoop_seat_phase && m_netcoop_driver_fit_at && Device.dwTimeGlobal >= m_netcoop_driver_fit_at && m_netcoop_seat_motion.valid())
	{
		m_netcoop_driver_fit_at = 0;
		IKinematics* body = smart_cast<IKinematics*>(Visual());
		IKinematics* model = smart_cast<IKinematics*>(car->Visual());
		const u16 wheel = car->netcoop_steer_bone();
		const u16 left = body ? body->LL_BoneID("bip01_l_hand") : BI_NONE;
		const u16 right = body ? body->LL_BoneID("bip01_r_hand") : BI_NONE;
		if (model && wheel != BI_NONE && left != BI_NONE && right != BI_NONE)
		{
			body->CalculateBones_Invalidate();
			body->CalculateBones(TRUE);
			model->CalculateBones(TRUE);
			Fvector hands, grip;
			hands.add(body->LL_GetTransform(left).c, body->LL_GetTransform(right).c).mul(0.5f);
			XFORM().transform_tiny(hands); // world
			car->XFORM().transform_tiny(grip, model->LL_GetTransform(wheel).c);
			Fmatrix to_car;
			to_car.invert(car->XFORM());
			to_car.transform_tiny(hands);
			to_car.transform_tiny(grip);
			Fvector fit;
			fit.sub(grip, hands);
			clamp(fit.x, -0.35f, 0.35f); clamp(fit.y, -0.35f, 0.35f); clamp(fit.z, -0.35f, 0.35f);
			if (_valid(fit))
			{
				m_netcoop_driver_fit.set(fit);
				Msg("[Lost Zone][vehicle] %s: driver moved %.2f %.2f %.2f to the wheel", car->cNameSect().c_str(), fit.x, fit.y, fit.z);
			}
		}
	}
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
		motion=steering<-.015f ? anims.steer_left:steering>.015f ? anims.steer_right:anims.idles[0];
		freeze=motion!=anims.idles[0];progress=_min(.999f,_abs(steering)/.6f);
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
		if(freeze) blend->timeCurrent=progress*blend->timeTotal;
	}
	return true;
}

namespace netcoop
{
