// Included in netcoop.cpp after server_physics_update (namespace netcoop).
// Vehicles in multiplayer (owner 2026-10-12, doc 100).
//
// The server owns the car: it runs the CCar physics with the driver's keys
// (M_NETCOOP_VEHICLE input) and sends the poses on the physics channel and
// the car's state (engine, lights, rpm, steering, who sits where) here. A
// client's car is a replica (CCar::netcoop_replica_state).
//
// Seats come from the car's section (netcoop_seats = bone[:x:y:z], ...; the
// first one drives) or default to the model's driver_place, seat_right and
// seat_back. A player picks the seat by the door they look at; a taken seat
// says so. A seated player is placed at the car's pose times the seat on the
// server, on their own client and on every other client, with no character
// capsule and no own movement; the driver's keys go to the server.

enum
{
	vehicle_op_state = 1, // server -> client: u16 car, u8 flags, u8 keys, float rpm, float steer, u8 n, n x u16 actor
	vehicle_op_enter, // client -> server: u16 car, u8 seat
	vehicle_op_exit, // client -> server
	vehicle_op_input, // client -> server: u16 car, u8 keys
	vehicle_op_toggle, // client -> server: u16 car, u8 what (0 engine, 1 head lights)
	vehicle_op_trunk, // client -> server: u16 car
	vehicle_op_trunk_open, // server -> client: u16 box, u16 car (legacy: box only)
	vehicle_op_fire, // client -> server: u16 car, vec3 aim direction (the gunner's seat, gun view)
	vehicle_op_gun, // server -> client: u16 car, vec3 muzzle, vec3 direction (a shot to see and hear)
	vehicle_op_door, // client -> server: u16 car, u16 physical door/hood/trunk bone
};

// ---------------------------------------------------------------------------
// Boxes kept away from what they belong to (a car's trunk under the map):
// a player may move items with such a box while next to its anchor.
// ---------------------------------------------------------------------------
static xr_map<u16, u16> s_box_anchor; // box id -> anchor object id

void script_box_anchor(u16 box, u16 anchor)
{
	if (!pure_client() && box != anchor)
		s_box_anchor[box] = anchor;
}

bool box_anchor_within_reach(u16 box, const Fvector& from)
{
	auto found = s_box_anchor.find(box);
	if (found == s_box_anchor.end())
		return false;
	CObject* anchor = Level().Objects.net_Find(found->second);
	if (!anchor || anchor->getDestroy())
		return false;
	return from.distance_to(anchor->Position()) <= anchor->Radius() + 2.5f;
}
static const u16 vehicle_seat_free = 0xffff;
static const u8 vehicle_max_seats = 8;

struct VehicleSeatPose
{
	Fmatrix local; // seat root (the body's root bone) in the car's space
	Fvector eye; // the eye of a player in this seat, car's space
	bool driver;
};

struct VehicleSeats
{
	xr_vector<VehicleSeatPose> seats;
	float half_width = 1.f; // from the centre line to the side
	float center_x = 0.f; // the centre line (a model off the axis, a helicopter)
	float front_z = 0.f; // the front row of seats (aim: rear seats lie behind it)
	float rear_z = 0.f; // the back of the car
	bool trunk = true;
	// A gunner's machine gun (owner 2026-10-18, the Mi-24): its seat, the
	// muzzle in the car's space, the shot from a weapon section, the cone it
	// turns in (degrees from straight ahead).
	int gun_seat = -1;
	Fvector gun_pos = {0.f, 0.f, 0.f}, gun_eye = {0.f, 0.f, 0.f};
	float gun_interval_ms = 100.f, gun_speed = 800.f, gun_power = 0.5f, gun_impulse = 100.f, gun_distance = 1000.f;
	float gun_air = 1.f, gun_yaw = 70.f, gun_up = 15.f, gun_down = 60.f;
	shared_str gun_ammo, gun_sound, gun_flame;
};
static xr_map<u16, VehicleSeats> s_vehicle_seats; // car id -> seats (server and client)
static void client_gun_shot(u16 car_id, const Fvector& muzzle, const Fvector& dir);

static VehicleSeats* vehicle_seats(CCar* car)
{
	if (!car || !car->Visual())
		return nullptr;
	auto found = s_vehicle_seats.find(car->ID());
	if (found != s_vehicle_seats.end())
		return found->second.seats.empty() ? nullptr : &found->second;
	VehicleSeats& v = s_vehicle_seats[car->ID()];
	IKinematics* K = smart_cast<IKinematics*>(car->Visual());
	if (!K)
		return nullptr;
	K->CalculateBones_Invalidate();
	K->CalculateBones(TRUE);
	CInifile* model = K->LL_UserData();
	LPCSTR section = car->cNameSect().c_str();
	LPCSTR driver_bone = model && model->line_exist("car_definition", "driver_place") ?
		model->r_string("car_definition", "driver_place") : "seat_left";
	string1024 list;
	if (pSettings->line_exist(section, "netcoop_seats"))
		xr_strcpy(list, pSettings->r_string(section, "netcoop_seats"));
	else
		xr_sprintf(list, "%s,seat_right,seat_back", driver_bone);
	// Optional model-space eyes for cabins with different seat heights.
	// Body roots follow their sitting animations; an eye is not that root.
	string1024 eyes = "";
	if (pSettings->line_exist(section, "netcoop_seat_eyes"))
		xr_strcpy(eyes, pSettings->r_string(section, "netcoop_seat_eyes"));
	// The passenger pose (sitting on a chair) has its root on the floor, the
	// driver's steering pose on the seat itself.
	const float drop = READ_IF_EXISTS(pSettings, r_float, section, "netcoop_passenger_drop", 0.45f);
	// Eye: the single-player driver camera relative to the driver's seat.
	Fvector eye_offset;
	eye_offset.set(0.f, 0.65f, 0.05f);
	const u16 driver_id = K->LL_BoneID(driver_bone);
	if (driver_id != BI_NONE)
	{
		Fvector offset;
		offset.sub(car->netcoop_camera_position(), K->LL_GetTransform(driver_id).c);
		if (offset.y > 0.3f && offset.y < 1.2f && offset.magnitude() < 1.5f)
			eye_offset.set(offset);
	}
	const u32 count = _GetItemCount(list);
	for (u32 i = 0; i < count && v.seats.size() < vehicle_max_seats; ++i)
	{
		string128 item;
		_GetItem(list, i, item);
		// bone[:x:y:z]: an offset in the car's space from that bone.
		string128 bone_name;
		Fvector offset;
		offset.set(0.f, 0.f, 0.f);
		_GetItem(item, 0, bone_name, ':');
		if (_GetItemCount(item, ':') == 4)
		{
			string32 value;
			offset.x = float(atof(_GetItem(item, 1, value, ':')));
			offset.y = float(atof(_GetItem(item, 2, value, ':')));
			offset.z = float(atof(_GetItem(item, 3, value, ':')));
		}
		const u16 bone = K->LL_BoneID(_Trim(bone_name));
		if (bone == BI_NONE)
			continue;
		VehicleSeatPose seat;
		seat.local.set(K->LL_GetTransform(bone));
		seat.local.c.add(offset);
		seat.driver = v.seats.empty();
		seat.eye.add(seat.local.c, eye_offset);
		if (eyes[0] && i < _GetItemCount(eyes))
		{
			string128 eye;
			_GetItem(eyes, i, eye);
			if (_GetItemCount(eye, ':') == 3)
			{
				string32 value;
				Fvector point;
				point.x = float(atof(_GetItem(eye, 0, value, ':')));
				point.y = float(atof(_GetItem(eye, 1, value, ':')));
				point.z = float(atof(_GetItem(eye, 2, value, ':')));
				if (_valid(point)) seat.eye.set(point);
			}
		}
		if (!seat.driver)
			seat.local.c.y -= drop;
		v.seats.push_back(seat);
	}
	if (v.seats.empty())
	{
		Msg("! [Lost Zone][vehicle] %s (%s) has no seats", car->cName().c_str(), section);
		return nullptr;
	}
	const Fbox& box = car->Visual()->getVisData().box;
	v.half_width = _max(_abs(box.min.x), _abs(box.max.x));
	v.rear_z = box.min.z;
	// A helicopter's box holds the rotor disc and the tail boom: its section
	// gives the fuselage instead.
	v.center_x = READ_IF_EXISTS(pSettings, r_float, section, "netcoop_center_x", 0.f);
	v.half_width = READ_IF_EXISTS(pSettings, r_float, section, "netcoop_half_width", v.half_width);
	v.rear_z = READ_IF_EXISTS(pSettings, r_float, section, "netcoop_rear_z", v.rear_z);
	v.front_z = v.seats[0].local.c.z;
	v.trunk = !!READ_IF_EXISTS(pSettings, r_bool, section, "netcoop_trunk", TRUE);
	const int gun_seat = READ_IF_EXISTS(pSettings, r_s32, section, "netcoop_gun_seat", -1);
	LPCSTR gun_weapon = READ_IF_EXISTS(pSettings, r_string, section, "netcoop_gun_weapon", "wpn_pkm");
	if (gun_seat >= 0 && u32(gun_seat) < v.seats.size() && pSettings->line_exist(section, "netcoop_gun_pos") &&
		pSettings->section_exist(gun_weapon))
	{
		string256 first;
		v.gun_seat = gun_seat;
		v.gun_pos = pSettings->r_fvector3(section, "netcoop_gun_pos");
		v.gun_eye = READ_IF_EXISTS(pSettings, r_fvector3, section, "netcoop_gun_eye", v.gun_pos);
		const float rpm = READ_IF_EXISTS(pSettings, r_float, section, "netcoop_gun_rpm",
			READ_IF_EXISTS(pSettings, r_float, gun_weapon, "rpm", 600.f));
		v.gun_interval_ms = 60000.f / _max(60.f, rpm);
		v.gun_speed = READ_IF_EXISTS(pSettings, r_float, gun_weapon, "bullet_speed", 800.f);
		LPCSTR power = READ_IF_EXISTS(pSettings, r_string, gun_weapon, "hit_power", "0.5");
		v.gun_power = float(atof(_GetItem(power, 0, first))) * READ_IF_EXISTS(pSettings, r_float, section, "netcoop_gun_power_k", 1.f);
		v.gun_impulse = READ_IF_EXISTS(pSettings, r_float, gun_weapon, "hit_impulse", 100.f);
		v.gun_distance = READ_IF_EXISTS(pSettings, r_float, gun_weapon, "fire_distance", 1000.f);
		v.gun_air = READ_IF_EXISTS(pSettings, r_float, gun_weapon, "air_resistance_factor", 1.f);
		v.gun_yaw = READ_IF_EXISTS(pSettings, r_float, section, "netcoop_gun_yaw", 70.f);
		v.gun_up = READ_IF_EXISTS(pSettings, r_float, section, "netcoop_gun_up", 15.f);
		v.gun_down = READ_IF_EXISTS(pSettings, r_float, section, "netcoop_gun_down", 60.f);
		v.gun_ammo = _GetItem(READ_IF_EXISTS(pSettings, r_string, gun_weapon, "ammo_class", "ammo_7.62x54_7h1"), 0, first);
		v.gun_sound = _GetItem(READ_IF_EXISTS(pSettings, r_string, gun_weapon, "snd_shoot", ""), 0, first);
		v.gun_flame = READ_IF_EXISTS(pSettings, r_string, gun_weapon, "flame_particles", "");
		if (!pSettings->section_exist(v.gun_ammo))
			v.gun_seat = -1;
	}
	return &v;
}

// Test the standing controller's volume before creating it. A ground ray
// alone accepted points inside walls, parked cars and other players.
static bool vehicle_exit_clear(CCar* car, const Fvector& feet)
{
	Fvector center = feet, forward, up, size;
	center.y += 1.f;
	forward.set(0.f, 0.f, 1.f); up.set(0.f, 1.f, 0.f); size.set(0.8f, 1.7f, 0.8f);
	if (Level().ObjectSpace.BoxQuery(center, forward, up, size, nullptr)) return false;
	xr_vector<CObject*> nearby;
	Level().ObjectSpace.GetNearest(nearby, center, 1.5f, car);
	Fbox standing;
	standing.set(feet.x-0.4f, feet.y+0.15f, feet.z-0.4f, feet.x+0.4f, feet.y+1.85f, feet.z+0.4f);
	for (CObject* object : nearby)
	{
		if (!object || object->getDestroy() || !object->Visual()) continue;
		Fmatrix inverse; inverse.invert(object->XFORM());
		Fbox local; local.xform(standing, inverse);
		if (local.intersect(object->Visual()->getVisData().box)) return false;
	}
	return true;
}

// Prefer the seat's side, then try the opposite side and clear points along
// the body. The optional result lets a normal exit stay seated if blocked.
static Fvector vehicle_exit_position(CCar* car, const VehicleSeats& v, const VehicleSeatPose& seat, bool* clear = nullptr)
{
	if (clear) *clear = false;
	const float side = seat.local.c.x < v.center_x ? -1.f : 1.f;
	Fvector fallback = car->Position();
	for (int along = 0; along < 5; ++along)
		for (int opposite = 0; opposite < 2; ++opposite)
		{
			Fvector local = seat.local.c;
			local.x = v.center_x + side * (opposite ? -1.f : 1.f) * (v.half_width + 0.9f);
			local.z += along == 0 ? 0.f : (along % 2 ? -1.f : 1.f) * float((along+1)/2) * 1.2f;
			local.y += 0.5f;
			Fvector world; car->XFORM().transform_tiny(world, local);
			collide::rq_result hit;
			Fvector start = world, down;
			start.y += 1.5f; down.set(0.f, -1.f, 0.f);
			if (Level().ObjectSpace.RayPick(start, down, 8.f, collide::rqtStatic, hit, car))
				world.y = start.y - hit.range + 0.08f;
			if (along == 0 && opposite == 0) fallback = world;
			if (vehicle_exit_clear(car, world))
			{
				if (clear) *clear = true;
				return world;
			}
		}
	return fallback; // forced removal (destroyed car/disconnect) must still release the seat
}

// Which seat the aim point (car's space) asks for: the nearest seat on that
// side; behind the rear seats the trunk (-2); -1 nothing.
static int vehicle_aim(const VehicleSeats& v, const Fvector& local)
{
	float rearmost = v.front_z;
	for (const VehicleSeatPose& seat : v.seats)
		rearmost = _min(rearmost, seat.local.c.z);
	if (v.trunk && local.z < rearmost - 0.7f)
		return -2;
	int best = -1;
	float best_distance = flt_max;
	for (u32 i = 0; i < v.seats.size(); ++i)
	{
		const Fvector& p = v.seats[i].local.c;
		const float distance = _sqr(p.x - local.x) + _sqr(p.z - local.z);
		if (distance < best_distance)
		{
			best_distance = distance;
			best = int(i);
		}
	}
	return best;
}

// ---------------------------------------------------------------------------
// server
// ---------------------------------------------------------------------------
struct VehicleRuntime
{
	xr_vector<u16> seats;
	u8 keys = 0;
	u32 keys_time = 0;
	u32 sent = 0;
	bool dirty = true;
	u32 transit_check = 0; // driving into a passage (V6)
	u32 transit_refused = 0;
	u32 gun_last = 0;
	float gun_budget = 3.f;
	u32 run_over_check = 0; // players in the car's way (spec 2.3)
};
static xr_map<u16, VehicleRuntime> s_vehicles_sv;

// The gun turns within its cone: a direction outside it is brought to its edge.
static Fvector vehicle_gun_direction(CCar* car, const VehicleSeats& poses, Fvector dir)
{
	Fmatrix inverse;
	inverse.invert(car->XFORM());
	Fvector local;
	inverse.transform_dir(local, dir);
	local.normalize_safe();
	float yaw = atan2f(local.x, local.z), pitch = asinf(_max(-1.f, _min(1.f, local.y)));
	clamp(yaw, -deg2rad(poses.gun_yaw), deg2rad(poses.gun_yaw));
	clamp(pitch, -deg2rad(poses.gun_down), deg2rad(poses.gun_up));
	local.set(_sin(yaw) * _cos(pitch), _sin(pitch), _cos(yaw) * _cos(pitch));
	car->XFORM().transform_dir(dir, local);
	return dir.normalize_safe();
}

// The server fires the gunner's shot and lets the players near see it.
static void vehicle_gun_fire(xrServer* server, CCar* car, VehicleSeats& poses, VehicleRuntime& v, CActor* gunner, Fvector dir)
{
	const u32 now = Device.dwTimeGlobal;
	// as fast as the gun fires, a few shots of slack for the network
	v.gun_budget = _min(3.f, v.gun_budget + float(now - v.gun_last) / poses.gun_interval_ms);
	v.gun_last = now;
	if (v.gun_budget < 1.f)
		return;
	v.gun_budget -= 1.f;
	dir = vehicle_gun_direction(car, poses, dir);
	Fvector muzzle;
	car->XFORM().transform_tiny(muzzle, poses.gun_pos);
	muzzle.mad(dir, 0.6f); // out of the gun's own body
	CCartridge cartridge;
	cartridge.Load(poses.gun_ammo.c_str(), 0);
	Level().BulletManager().AddBullet(muzzle, dir, poses.gun_speed, poses.gun_power, poses.gun_impulse, gunner->ID(), car->ID(),
		ALife::eHitTypeFireWound, poses.gun_distance, cartridge, poses.gun_air, true);
	NET_Packet P;
	P.w_begin(M_NETCOOP_VEHICLE);
	P.w_u8(vehicle_op_gun);
	P.w_u16(car->ID());
	P.w_vec3(muzzle);
	P.w_vec3(dir);
	struct Send
	{
		xrServer* server;
		NET_Packet* packet;
		Fvector position;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (CL == server->GetServerClient() || !CL->flags.bConnected || !CL->gamma_snapshot_ready || !CL->owner)
				return;
			if (CL->owner->o_Position.distance_to(position) > 600.f)
				return;
			server->SendTo(CL->ID, *packet, net_flags(FALSE, TRUE));
		}
	} send = {server, &P, muzzle};
	server->ForEachClientDo(send);
}

static void vehicle_seat_server(CCar* car, VehicleRuntime& v, const VehicleSeats& poses, u8 index, CActor* actor)
{
	const VehicleSeatPose& seat = poses.seats[index];
	v.seats[index] = actor->ID();
	v.dirty = true;
	actor->netcoop_seat_enter(car->ID(), index, seat.driver, seat.local, seat.eye);
	if (seat.driver)
		car->netcoop_engage(true);
	Msg("[Lost Zone][vehicle] %s sits in %s (%u), seat %u%s", actor->cName().c_str(), car->cName().c_str(), car->ID(),
		index, seat.driver ? ", driving" : "");
}

static bool vehicle_unseat_server(CCar* car, VehicleRuntime& v, u8 index, bool force = true)
{
	CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(v.seats[index]));
	const VehicleSeats* poses = car ? vehicle_seats(car) : nullptr;
	if (actor && actor->netcoop_seated())
	{
		bool clear = true;
		const Fvector exit = car && poses && index < poses->seats.size() ?
			vehicle_exit_position(car, *poses, poses->seats[index], &clear) : actor->Position();
		if (!clear && !force)
		{
			Msg("[diag][vehicle] id=%u actor=%u exit refused: standing volume blocked", car->ID(), actor->ID());
			return false;
		}
		actor->netcoop_seat_leave(exit);
		Msg("[Lost Zone][vehicle] %s leaves seat %u", actor->cName().c_str(), index);
	}
	if (car && poses && index < poses->seats.size() && poses->seats[index].driver)
	{
		car->netcoop_engage(false);
		v.keys = 0;
	}
	v.seats[index] = vehicle_seat_free;
	v.dirty = true;
	return true;
}

static VehicleRuntime* vehicle_runtime(CCar* car, const VehicleSeats& poses)
{
	VehicleRuntime& v = s_vehicles_sv[car->ID()];
	if (v.seats.size() != poses.seats.size())
		v.seats.assign(poses.seats.size(), vehicle_seat_free);
	return &v;
}

