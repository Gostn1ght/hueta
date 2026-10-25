// Included in netcoop.cpp after netcoop_vehicle_server.inc (namespace netcoop).
// Vehicles, client side: state from the server, entering, trunk, keys, the
// gunner's view and shots, the use prompt (doc 100, doc 151).

// ---------------------------------------------------------------------------
// client
// ---------------------------------------------------------------------------
static xr_map<u16, xr_vector<u16>> s_vehicles_cl; // car id -> seat occupants
static u8 s_vehicle_keys = 0;
static u32 s_vehicle_keys_sent = 0;

static void vehicle_send(u8 op, u16 car, int value)
{
	NET_Packet P;
	P.w_begin(M_NETCOOP_VEHICLE);
	P.w_u8(op);
	if (op != vehicle_op_exit)
	{
		P.w_u16(car);
		if (value >= 0)
			P.w_u8(u8(value));
	}
	Level().Send(P, net_flags(TRUE, TRUE));
}

static u16 s_trunk_pending = 0xffff;
static u32 s_trunk_pending_until = 0;

void vehicles_reset()
{
	s_box_anchor.clear();
	s_vehicle_seats.clear();
	s_vehicles_sv.clear();
	s_vehicles_cl.clear();
	s_vehicle_arrivals.clear();
	s_vehicle_conditions.clear();
	s_vehicle_inbox_check = 0;
	s_vehicle_keys = 0;
	s_vehicle_keys_sent = 0;
	s_trunk_pending = 0xffff;
	s_trunk_pending_until = 0;
}

static void client_trunk_open(NET_Packet& P)
{
	// The box is deliberately below the map. Distance checks must use the
	// car granted by the server, rather than immediately closing its menu.
	if (P.r_elapsed() != 2 && P.r_elapsed() != 4) return;
	const u16 box = P.r_u16();
	const u16 anchor = P.r_elapsed() == 2 ? P.r_u16() : 0xffff;
	if (box == 0xffff || box == anchor) return;
	s_box_anchor.erase(box);
	if (anchor != 0xffff) s_box_anchor[box] = anchor;
	s_trunk_pending = box;
	s_trunk_pending_until = Device.dwTimeGlobal + 3000;
}

void client_on_vehicle(NET_Packet& P)
{
	if (!pure_client() || P.r_elapsed() < 1)
		return;
	const u8 op = P.r_u8();
	if (op == vehicle_op_trunk_open)
	{
		// A new box arrives a moment later: opened by script_vehicle_prompt.
		client_trunk_open(P);
		return;
	}
	if (op == vehicle_op_gun)
	{
		if (P.r_elapsed() < 26)
			return;
		const u16 car_id = P.r_u16();
		Fvector muzzle, dir;
		P.r_vec3(muzzle);
		P.r_vec3(dir);
		client_gun_shot(car_id, muzzle, dir);
		return;
	}
	if (op != vehicle_op_state || P.r_elapsed() < 13)
		return;
	const u16 car_id = P.r_u16();
	const u8 flags = P.r_u8();
	const u8 keys = P.r_u8();
	const float rpm = P.r_float();
	const float steer = P.r_float();
	const u8 count = P.r_u8();
	if (count > vehicle_max_seats || P.r_elapsed() != u32(count) * 2 || !_valid(rpm) || !_valid(steer))
		return;
	xr_vector<u16> seats(count);
	for (u16& id : seats)
		id = P.r_u16();
	CCar* car = smart_cast<CCar*>(Level().Objects.net_Find(car_id));
	if (!car)
		return; // it comes again while the car is in use
	car->netcoop_replica_state(!!(flags & 1), !!(flags & 2), rpm, steer);
	car->m_netcoop_keys = keys; // the driver's steering animation
	const VehicleSeats* poses = vehicle_seats(car);
	if (!poses)
		return;
	xr_vector<u16>& known = s_vehicles_cl[car_id];
	for (u32 i = 0; i < known.size(); ++i)
	{
		if (known[i] == vehicle_seat_free || std::find(seats.begin(), seats.end(), known[i]) != seats.end())
			continue;
		CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(known[i]));
		if (actor && actor->m_netcoop_seat_car == car_id && i < poses->seats.size())
			actor->netcoop_seat_leave(vehicle_exit_position(car, *poses, poses->seats[i]));
	}
	for (u32 i = 0; i < seats.size() && i < poses->seats.size(); ++i)
	{
		if (seats[i] == vehicle_seat_free)
			continue;
		CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(seats[i]));
		if (actor && (actor->m_netcoop_seat_car != car_id || actor->m_netcoop_seat != i))
			actor->netcoop_seat_enter(car_id, u8(i), poses->seats[i].driver, poses->seats[i].local, poses->seats[i].eye);
	}
	known = seats;
	if (Level().CurrentControlEntity())
		if (CActor* self = smart_cast<CActor*>(Level().CurrentControlEntity()))
			if (!self->netcoop_seated() || !self->m_netcoop_seat_driver)
				s_vehicle_keys = 0;
}

// F on a car: the seat behind the door the player looks at, or the trunk.
bool vehicle_use(CActor* actor, CObject* object, const Fvector& aim)
{
	CCar* car = smart_cast<CCar*>(object);
	if (!car || !enabled())
		return false;
	if (!pure_client() || car->netcoop_destroyed())
		return true;
	const VehicleSeats* poses = vehicle_seats(car);
	if (!poses)
		return true;
	Fmatrix inverse;
	inverse.invert(car->XFORM());
	Fvector local;
	inverse.transform_tiny(local, aim);
	const int seat = vehicle_aim(*poses, local);
	if (seat == -2)
	{
		vehicle_send(vehicle_op_trunk, car->ID(), -1);
		return true;
	}
	if (seat < 0)
		return true;
	auto known = s_vehicles_cl.find(car->ID());
	if (known != s_vehicles_cl.end() && u32(seat) < known->second.size() && known->second[seat] != vehicle_seat_free)
	{
		client_on_server_text(*CStringTable().translate("st_netcoop_seat_taken"));
		return true;
	}
	vehicle_send(vehicle_op_enter, car->ID(), seat);
	return true;
}

static bool s_gun_view = false, s_gun_fire = false;
static u32 s_gun_next = 0;

// This player sits at his car's gun: the car's seats, or null.
static const VehicleSeats* vehicle_gun_seat(CActor* actor)
{
	if (!actor || !actor->netcoop_seated())
		return nullptr;
	CCar* car = smart_cast<CCar*>(Level().Objects.net_Find(actor->m_netcoop_seat_car));
	const VehicleSeats* poses = car ? vehicle_seats(car) : nullptr;
	return poses && poses->gun_seat >= 0 && actor->m_netcoop_seat == u8(poses->gun_seat) ? poses : nullptr;
}

// The camera of the gun view: the gun's sight (netcoop_gun_eye).
bool vehicle_gun_view_point(CActor* actor, Fvector& point)
{
	if (!pure_client() || !s_gun_view || actor != Level().CurrentControlEntity())
		return false;
	const VehicleSeats* poses = vehicle_gun_seat(actor);
	CCar* car = poses ? smart_cast<CCar*>(Level().Objects.net_Find(actor->m_netcoop_seat_car)) : nullptr;
	if (!car)
	{
		s_gun_view = s_gun_fire = false;
		return false;
	}
	car->XFORM().transform_tiny(point, poses->gun_eye);
	return true;
}

static xr_map<u16, ref_sound> s_vehicle_gun_sounds;

// A shot of a car's gun (any client): the tracer, the flash and the sound.
// The server's bullet does the damage; this one only shows it.
static void client_gun_shot(u16 car_id, const Fvector& muzzle, const Fvector& dir)
{
	CCar* car = smart_cast<CCar*>(Level().Objects.net_Find(car_id));
	const VehicleSeats* poses = car ? vehicle_seats(car) : nullptr;
	if (!poses || poses->gun_seat < 0 || !_valid(muzzle) || !_valid(dir))
		return;
	CCartridge cartridge;
	cartridge.Load(poses->gun_ammo.c_str(), 0);
	cartridge.m_flags.set(CCartridge::cfTracer, TRUE);
	Level().BulletManager().AddBullet(muzzle, dir, poses->gun_speed, 0.f, 0.f, u16(-1), car_id,
		ALife::eHitTypeFireWound, poses->gun_distance, cartridge, poses->gun_air, false);
	if (poses->gun_flame.size())
	{
		CParticlesObject* flame = CParticlesObject::Create(poses->gun_flame.c_str(), TRUE);
		Fmatrix xf;
		xf.identity();
		xf.k.set(dir);
		Fvector::generate_orthonormal_basis(xf.k, xf.j, xf.i);
		xf.c.set(muzzle);
		flame->UpdateParent(xf, zero_vel);
		flame->Play(false);
	}
	if (poses->gun_sound.size())
	{
		ref_sound& snd = s_vehicle_gun_sounds[car_id];
		if (!snd._handle())
			snd.create(poses->gun_sound.c_str(), st_Effect, sg_SourceType);
		Fvector at = muzzle;
		if (snd._handle())
			snd.play_no_feedback(car, 0, 0.f, &at);
	}
}

void client_vehicle_sounds_reset()
{
	for (auto& kv : s_vehicle_gun_sounds)
		kv.second.destroy();
	s_vehicle_gun_sounds.clear();
	s_gun_view = false;
	s_gun_fire = false;
	s_gun_next = 0;
	s_run_over_last.clear();
}

// Keys of a seated player: the driver's pedals and wheel go to the server,
// F gets out, the camera keys switch the view; everything else waits.
void vehicle_key(CActor* actor, int cmd, bool pressed)
{
	if (!pure_client() || !actor->netcoop_seated())
		return;
	// The gunner's seat: RMB switches between the seat and the gun, LMB
	// fires, from the gun view only.
	if (vehicle_gun_seat(actor))
	{
		if (cmd == kWPN_ZOOM && pressed)
		{
			s_gun_view = !s_gun_view;
			s_gun_fire = false;
			return;
		}
		if (cmd == kWPN_FIRE)
		{
			s_gun_fire = pressed && s_gun_view;
			return;
		}
	}
	u8 bit = 0;
	switch (cmd)
	{
	case kFWD: bit = CCar::netcoop_key_forward; break;
	case kBACK: bit = CCar::netcoop_key_back; break;
	case kL_STRAFE: bit = CCar::netcoop_key_left; break;
	case kR_STRAFE: bit = CCar::netcoop_key_right; break;
	case kJUMP: bit = CCar::netcoop_key_handbrake; break;
	case kCROUCH: bit = CCar::netcoop_key_down; break;
	case kL_LOOKOUT: bit = CCar::netcoop_key_yaw_left; break;
	case kR_LOOKOUT: bit = CCar::netcoop_key_yaw_right; break;
	}
	if (bit)
	{
		if (!actor->m_netcoop_seat_driver)
			return;
		const u8 keys = pressed ? u8(s_vehicle_keys | bit) : u8(s_vehicle_keys & ~bit);
		if (keys != s_vehicle_keys)
		{
			s_vehicle_keys = keys;
			s_vehicle_keys_sent = Device.dwTimeGlobal;
			vehicle_send(vehicle_op_input, actor->m_netcoop_seat_car, keys);
		}
		return;
	}
	if (!pressed)
		return;
	switch (cmd)
	{
	case kUSE:
		s_vehicle_keys = 0;
		vehicle_send(vehicle_op_exit, 0, -1);
		break;
	case kTORCH:
		if (actor->m_netcoop_seat_driver) vehicle_send(vehicle_op_toggle, actor->m_netcoop_seat_car, 1);
		break;
	case kDETECTOR:
		if (actor->m_netcoop_seat_driver) vehicle_send(vehicle_op_toggle, actor->m_netcoop_seat_car, 0);
		break;
	case kCAM_1: actor->cam_Set(eacFirstEye); break;
	case kCAM_2: actor->cam_Set(eacLookAt); break;

	}
}

// Lua (netcoop_vehicle_client, 10 Hz): what F would do at the car under the
// crosshair - "driver", "passenger", "taken", "trunk" - or "seated_driver" /
// "seated" in a car; "" otherwise. Also opens a trunk the server granted.
static Fvector s_vehicle_prompt_point = {0.f, 0.f, 0.f};

Fvector script_vehicle_prompt_point()
{
	return s_vehicle_prompt_point;
}

LPCSTR script_vehicle_prompt()
{
	if (!pure_client() || !g_pGameLevel)
		return "";
	CActor* actor = smart_cast<CActor*>(Level().CurrentControlEntity());
	if (!actor || !actor->g_Alive())
		return "";
	if (s_trunk_pending != 0xffff)
	{
		if (CInventoryBox* box = smart_cast<CInventoryBox*>(Level().Objects.net_Find(s_trunk_pending)))
		{
			s_trunk_pending = 0xffff;
			if (CUIGameSP* game = smart_cast<CUIGameSP*>(CurrentGameUI()))
				game->StartCarBody(actor, box);
		}
		else if (Device.dwTimeGlobal > s_trunk_pending_until)
			s_trunk_pending = 0xffff;
	}
	if (actor->netcoop_seated())
	{
		if (!actor->m_netcoop_seat_driver)
			return "seated";
		CCar* seat_car = smart_cast<CCar*>(Level().Objects.net_Find(actor->m_netcoop_seat_car));
		return seat_car && seat_car->netcoop_is_heli() ? "seated_pilot" : "seated_driver";
	}
	collide::rq_result& RQ = HUD().GetRQ();
	CCar* car = smart_cast<CCar*>(RQ.O);
	if (!car || RQ.range >= 3.5f || car->netcoop_destroyed())
		return "";
	const VehicleSeats* poses = vehicle_seats(car);
	if (!poses)
		return "";
	Fvector aim, local;
	aim.mad(Device.vCameraPosition, Device.vCameraDirection, RQ.range);
	Fmatrix inverse;
	inverse.invert(car->XFORM());
	inverse.transform_tiny(local, aim);
	const int seat = vehicle_aim(*poses, local);
	if (seat == -1 || seat < -2)
		return "";
	// The prompt stands on the car's side by the seat (its door), or at
	// the back for the trunk, a little above the seat.
	Fvector point;
	if (seat == -2)
		point.set(poses->center_x, local.y, poses->rear_z);
	else
	{
		const Fvector& at = poses->seats[seat].local.c;
		point.set(poses->center_x + (at.x < poses->center_x ? -poses->half_width : poses->half_width), at.y + 0.6f, at.z);
	}
	car->XFORM().transform_tiny(s_vehicle_prompt_point, point);
	if (seat == -2)
		return "trunk";
	auto known = s_vehicles_cl.find(car->ID());
	if (known != s_vehicles_cl.end() && u32(seat) < known->second.size() && known->second[seat] != vehicle_seat_free)
		return "taken";
	return poses->seats[seat].driver ? "driver" : "passenger";
}

// Held pedals are repeated: the server lets go after 2 s of silence.
void vehicle_input_tick(CActor* actor)
{
	if (s_gun_fire && pure_client())
	{
		const VehicleSeats* poses = vehicle_gun_seat(actor);
		if (!poses || !s_gun_view)
			s_gun_fire = false;
		else if (Device.dwTimeGlobal >= s_gun_next)
		{
			s_gun_next = Device.dwTimeGlobal + u32(poses->gun_interval_ms);
			NET_Packet P;
			P.w_begin(M_NETCOOP_VEHICLE);
			P.w_u8(vehicle_op_fire);
			P.w_u16(actor->m_netcoop_seat_car);
			P.w_vec3(Device.vCameraDirection);
			Level().Send(P, net_flags(FALSE, TRUE));
		}
	}
	if (!actor->m_netcoop_seat_driver || !s_vehicle_keys)
		return;
	if (Device.dwTimeGlobal - s_vehicle_keys_sent >= 400)
	{
		s_vehicle_keys_sent = Device.dwTimeGlobal;
		vehicle_send(vehicle_op_input, actor->m_netcoop_seat_car, s_vehicle_keys);
	}
}
} // namespace netcoop

