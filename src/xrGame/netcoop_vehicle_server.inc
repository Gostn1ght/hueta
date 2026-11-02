// Included in netcoop.cpp after netcoop_vehicles.inc (namespace netcoop).
// Vehicles, server side: seats, the driver's input, state to the clients,
// the gunner's gun, transit to another map, speed limit (doc 100, doc 151).

void server_on_vehicle(xrServer* server, xrClientData* CL, NET_Packet& P)
{
	if (!g_pGameLevel || pure_client() || !CL->owner || P.r_elapsed() < 1)
		return;
	CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(CL->owner->ID));
	if (!actor || !actor->g_Alive())
		return;
	const u8 op = P.r_u8();
	if(actor->m_netcoop_seat_phase) return;
	if (op == vehicle_op_exit)
	{
		if (!actor->netcoop_seated())
			return;
		auto it = s_vehicles_sv.find(actor->m_netcoop_seat_car);
		if (it == s_vehicles_sv.end())
			return;
		for (u8 i = 0; i < it->second.seats.size(); ++i)
			if (it->second.seats[i] == actor->ID())
				if (CCar* current=smart_cast<CCar*>(Level().Objects.net_Find(it->first)))
					if(const VehicleSeats* config=vehicle_seats(current))
					if (!vehicle_transition(current,it->second,*config,i,actor,true))
					cluster_refuse(server, CL, "There is no room to leave the vehicle; move it away from the obstacle");
		return;
	}
	if (P.r_elapsed() < 2)
		return;
	const u16 car_id = P.r_u16();
	// enter, input and toggle carry one more byte
	if (op != vehicle_op_trunk && P.r_elapsed() < 1)
		return;
	CCar* car = smart_cast<CCar*>(Level().Objects.net_Find(car_id));
	if (!car || car->getDestroy() || car->netcoop_destroyed())
		return;
	VehicleSeats* poses = vehicle_seats(car);
	if (!poses)
		return;
	VehicleRuntime& v = *vehicle_runtime(car, *poses);
	const u32 now = Level().timeServer();
	switch (op)
	{
	case vehicle_op_door:
		if(P.r_elapsed()==2 && !actor->netcoop_seated() && actor->Position().distance_to(car->Position())<=car->Radius()+2.5f) {
			const u16 bone=P.r_u16();
			if(car->netcoop_door_bone(bone)==bone) {car->DoorSwitch(bone);v.dirty=true;}
		}
		break;
	case vehicle_op_enter:
		{
			const u8 seat = P.r_u8();
			if (actor->netcoop_seated() || seat >= v.seats.size() || v.seats[seat] != vehicle_seat_free)
			{
				v.dirty = true; // the client learns who sits there
				return;
			}
			// Next to the car: its size plus an arm's length.
			if (actor->Position().distance_to(car->Position()) > car->Radius() + 2.5f)
				return;
			vehicle_transition(car, v, *poses, seat, actor, false);
		}
		break;
	case vehicle_op_input:
		{
			// Helicopters also take collective down and the pedals (doc 137).
			const u8 keys = P.r_u8() & (car->netcoop_is_heli() ? 255 : 31);
			if (v.seats.empty() || v.seats[0] != actor->ID())
				return;
			v.keys_time = now;
			if (keys != v.keys)
			{
				car->netcoop_drive(keys);
				v.keys = keys;
				v.dirty = true;
			}
		}
		break;
	case vehicle_op_fire:
		{
			if (P.r_elapsed() < 12)
				return;
			Fvector dir;
			P.r_vec3(dir);
			if (poses->gun_seat < 0 || u32(poses->gun_seat) >= v.seats.size() || v.seats[poses->gun_seat] != actor->ID() ||
				!_valid(dir) || dir.square_magnitude() < EPS)
				return;
			vehicle_gun_fire(server, car, *poses, v, actor, dir.normalize());
		}
		break;
	case vehicle_op_toggle:
		{
			const u8 what = P.r_u8();
			if (v.seats.empty() || v.seats[0] != actor->ID() || what > 2)
				return;
			car->netcoop_toggle(what);
			if(what==0) car->netcoop_drive(v.keys); // recompute held pedals after ignition/stall
			v.dirty = true;
		}
		break;
	case vehicle_op_trunk:
		{
			// From outside, next to the car. The trunk is a hidden box the
			// server Lua keeps for the car (netcoop_vehicles.trunk_box).
			if (actor->netcoop_seated() || !poses->trunk ||
				actor->Position().distance_to(car->Position()) > car->Radius() + 2.5f)
				return;
			::luabind::functor<int> trunk_box;
			int box = 0;
			if (ai().script_engine().functor("netcoop_vehicles.trunk_box", trunk_box))
			{
				try { box = trunk_box(int(car->ID())); }
				catch (...) { Msg("! [Lost Zone][vehicle] trunk_box failed"); }
			}
			if (box <= 0 || box >= 0xffff)
				return;
			if(IKinematics* model=smart_cast<IKinematics*>(car->Visual())) {
				for(u16 bone=0;bone<model->LL_BoneCount();++bone) {
					LPCSTR name=model->LL_GetData(bone).name.c_str();
					if((strstr(name,"trunk") || strstr(name,"back_door") || strstr(name,"door_back")) && car->netcoop_door_bone(bone)==bone)
						car->DoorOpen(bone);
				}
			}
			NET_Packet answer;
			answer.w_begin(M_NETCOOP_VEHICLE);
			answer.w_u8(vehicle_op_trunk_open);
			answer.w_u16(u16(box));
			answer.w_u16(car->ID());
			server->SendTo(CL->ID, answer, net_flags(TRUE, TRUE));
		}
		break;
	}
}

static void vehicle_send_state(xrServer* server, CCar* car, const VehicleRuntime& v, bool reliable)
{
	NET_Packet P;
	P.w_begin(M_NETCOOP_VEHICLE);
	P.w_u8(vehicle_op_state);
	P.w_u16(car->ID());
	P.w_u8(u8((car->netcoop_engine_on() ? 1 : 0) | (car->m_netcoop_lights ? 2 : 0) | (car->netcoop_aux_lights()<<2) |
		(car->netcoop_is_heli() ? 64:0) | (car->netcoop_is_heli() && car->netcoop_heli_gear_down() ? 32:0) |
		(car->netcoop_is_heli() && car->netcoop_heli_gear_position()>0.01f && car->netcoop_heli_gear_position()<0.99f ? 128:0)));
	P.w_u8(v.keys);
	P.w_float(car->netcoop_rpm());
	P.w_float(car->netcoop_steer());
	P.w_u8(u8(v.seats.size()));
	for (u16 id : v.seats)
		P.w_u16(id);
	Fvector velocity;velocity.set(0,0,0);if(car->PPhysicsShell())car->PPhysicsShell()->get_LinearVel(velocity);
	P.w_float(_valid(velocity) ? velocity.magnitude()*3.6f:0.f);
	P.w_float(car->netcoop_fuel());P.w_float(car->netcoop_fuel_capacity());P.w_float(car->GetfHealth());
	P.w_u16(car->netcoop_gear());P.w_u64(car->netcoop_broken_glass());
	P.w_float(car->netcoop_heli_gear_position());
	struct Send
	{
		xrServer* server;
		NET_Packet* packet;
		Fvector position;
		bool reliable;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (CL == server->GetServerClient() || !CL->flags.bConnected || !CL->gamma_snapshot_ready || !CL->owner)
				return;
			if (CL->owner->o_Position.distance_to(position) > 500.f)
				return;
			server->SendTo(CL->ID, *packet, net_flags(reliable ? TRUE : FALSE, TRUE));
		}
	} send = {server, &P, car->Position(), reliable};
	server->ForEachClientDo(send);
	// Separate op preserves legacy state packet compatibility. One batched
	// message also reaches observers who joined during a transition.
	NET_Packet animation;animation.w_begin(M_NETCOOP_VEHICLE);
	animation.w_u8(vehicle_op_animation);animation.w_u16(car->ID());animation.w_u8(u8(v.seats.size()));
	bool active=false;
	for(u16 id:v.seats) {
		CActor* actor=smart_cast<CActor*>(Level().Objects.net_Find(id));
		animation.w_u16(id);animation.w_u8(actor ? actor->m_netcoop_seat_phase:0);
		animation.w_u32(actor ? actor->m_netcoop_seat_phase_start:0);
		Fvector outside;outside.set(0,0,0);if(actor) outside=actor->m_netcoop_seat_outside;
		animation.w_vec3(outside);if(actor && actor->m_netcoop_seat_phase) active=true;
	}
	if(active || reliable) {send.packet=&animation;server->ForEachClientDo(send);}
}

// Owner and observers use the same car frame, even though their car/actor
// snapshot interpolation delays differ. One small packet per moving owner.
void platform_publish(CActor* actor)
{
 if(pure_client() || !g_pGameLevel || !Level().Server || !actor) return;
 const u16 car=actor->m_netcoop_platform_car;
 if(car==vehicle_seat_free && actor->m_netcoop_platform_sent_car==vehicle_seat_free) return;
 const u32 now=Level().timeServer();
 if(car==actor->m_netcoop_platform_sent_car && now-actor->m_netcoop_platform_sent<50) return;
 actor->m_netcoop_platform_sent=now;actor->m_netcoop_platform_sent_car=car;
 NET_Packet packet;packet.w_begin(M_NETCOOP_VEHICLE);packet.w_u8(vehicle_op_platform);
 packet.w_u16(actor->ID());packet.w_u16(car);packet.w_vec3(actor->m_netcoop_platform_local);
 struct Send {
  xrServer* server;NET_Packet* packet;CActor* actor;
  void operator()(IClient* client) {
   auto* CL=static_cast<xrClientData*>(client);
   if(CL==server->GetServerClient() || !CL->flags.bConnected || !CL->gamma_snapshot_ready || !CL->owner || CL->owner->ID==actor->ID()) return;
   if(CL->owner->o_Position.distance_to(actor->Position())<500.f) server->SendTo(CL->ID,*packet,net_flags(actor->m_netcoop_platform_car==vehicle_seat_free ? TRUE:FALSE,TRUE));
  }
 } send={Level().Server,&packet,actor};
 Level().Server->ForEachClientDo(send);
}

// ---------------------------------------------------------------------------
// Through a passage with the passengers (doc 100, V6)
// ---------------------------------------------------------------------------
// The driver takes the car into a level changer: the car (with its trunk, the
// Lua record of netcoop_vehicles.capture) goes to the cluster folder as
// car_<target map>_*.txt, everybody in it goes through the passage the
// player's way (cluster_move), and the car leaves this map. The target map's
// server picks the file up, puts the car down at the arrival point and seats
// each player in their seat as they arrive.
struct VehicleArrival
{
	xr_string login; // lower case
	u8 slot = 1;
	u16 car = 0xffff;
	u8 seat = 0;
	u32 until = 0;
};
static xr_vector<VehicleArrival> s_vehicle_arrivals;
struct VehicleCondition { u16 car; float health; float fuel; u32 until; };
static xr_vector<VehicleCondition> s_vehicle_conditions; // applied once the car is online
static u32 s_vehicle_inbox_check = 0;

static xrClientData* vehicle_client_of(xrServer* server, u16 actor_id)
{
	struct Find
	{
		u16 id;
		xrClientData* found;
		void operator()(IClient* client)
		{
			xrClientData* CL = static_cast<xrClientData*>(client);
			if (!found && CL && CL->owner && CL->owner->ID == id && CL->netcoop_login.size()) found = CL;
		}
	} find = {actor_id, nullptr};
	server->ForEachClientDo(find);
	return find.found;
}

static bool vehicle_write_file(LPCSTR path, const xr_string& text)
{
	string_path temp;
	xr_sprintf(temp, "%s.%u.tmp", path, GetCurrentProcessId());
	FILE* f = fopen(temp, "wb");
	if (!f) return false;
	const bool ok = fwrite(text.data(), 1, text.size(), f) == text.size() && fflush(f) == 0 && _commit(_fileno(f)) == 0;
	fclose(f);
	if (ok && MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) return true;
	DeleteFileA(temp);
	return false;
}

static void vehicle_transit(xrServer* server, CCar* car, VehicleRuntime& v, CLevelChanger* changer, CActor* driver)
{
	const u32 now = Level().timeServer();
	xrClientData* driver_client = vehicle_client_of(server, driver->ID());
	v.transit_refused = now + 5000; // one try per 5 s, and none while this one runs
	auto refuse = [&](LPCSTR text)
	{
		if (driver_client) cluster_refuse(server, driver_client, text);
	};
	if (!changer->IsLevelChangerEnabled()) return refuse("this passage is closed");
	const GameGraph::_GRAPH_ID game_vertex = changer->next_game_vertex();
	if (!ai().game_graph().valid_vertex_id(game_vertex)) return;
	const LPCSTR level = *ai().game_graph().header().level(ai().game_graph().vertex(game_vertex)->level_id()).name();
	xr_string host;
	u32 port = 0;
	if (!xr_strcmp(level, cluster_current_level()) || !cluster_location(level, host, port) || port == cluster_port())
		return refuse("no server runs that map yet");
	if (LPCSTR problem = cluster_target_problem(port))
		if (problem[0])
		{
			if (strstr(problem, "offline") && cluster_on_demand(level))
			{
				cluster_wake(level);
				return refuse("the server of that map is starting");
			}
			return refuse(problem);
		}
	// Everybody aboard must be able to go now.
	string1024 seats = "";
	for (u8 i = 0; i < v.seats.size(); ++i)
	{
		if (v.seats[i] == vehicle_seat_free) continue;
		xrClientData* CL = vehicle_client_of(server, v.seats[i]);
		if (!CL || s_character_restore.find(v.seats[i]) != s_character_restore.end())
			return refuse("the character is still loading");
		string128 entry;
		xr_sprintf(entry, "%s%s:%u:%u", seats[0] ? "," : "", CL->netcoop_login.c_str(), CL->netcoop_character_slot, i);
		xr_strcat(seats, entry);
	}
	::luabind::functor<LPCSTR> capture;
	xr_string record;
	if (ai().script_engine().functor("netcoop_vehicles.capture", capture))
	{
		try { LPCSTR text = capture(int(car->ID())); record = text ? text : ""; }
		catch (...) { record.clear(); }
	}
	if (record.empty())
		return refuse("the car could not be saved");
	// The car comes down a few metres past the arrival point.
	Fvector arrival = changer->next_position(), ahead;
	ahead.setHP(changer->next_angles().y, 0.f);
	arrival.mad(ahead, 5.f);
	arrival.y += 0.5f;
	xr_string text = "lostzone-car 1\n";
	string512 line;
	xr_sprintf(line, "%s\n%.3f %.3f %.3f %u %.4f %.4f\n%s\n", level, arrival.x, arrival.y, arrival.z, u32(game_vertex),
		car->GetfHealth(), car->netcoop_fuel(), seats);
	text += line;
	text += record;
	string_path dir, path;
	cluster_dir(dir);
	xr_sprintf(path, "%scar_%s_%llu_%u.txt", dir, level, cluster_unix_ms(), car->ID());
	if (!vehicle_write_file(path, text))
		return refuse("the car could not be saved");
	Msg("[Lost Zone][vehicle] %s (%u) leaves for %s with %s", car->cName().c_str(), car->ID(), level, seats);
	for (u8 i = 0; i < v.seats.size(); ++i)
	{
		if (v.seats[i] == vehicle_seat_free) continue;
		const u16 actor_id = v.seats[i];
		vehicle_unseat_server(car, v, i);
		if (xrClientData* CL = vehicle_client_of(server, actor_id))
			cluster_move(server, CL, changer);
	}
	::luabind::functor<void> release;
	if (ai().script_engine().functor("netcoop_vehicles.release", release))
	{
		try { release(int(car->ID())); }
		catch (...) { Msg("! [Lost Zone][vehicle] release failed"); }
	}
}

// The target map: cars that came through a passage.
static void vehicle_inbox(xrServer* server)
{
	string_path dir, pattern;
	cluster_dir(dir);
	xr_sprintf(pattern, "%scar_%s_*.txt", dir, cluster_current_level());
	WIN32_FIND_DATAA found;
	HANDLE search = FindFirstFileA(pattern, &found);
	if (search == INVALID_HANDLE_VALUE) return;
	xr_vector<xr_string> names;
	do names.push_back(found.cFileName); while (FindNextFileA(search, &found));
	FindClose(search);
	for (const xr_string& name : names)
	{
		string_path path, claimed;
		xr_sprintf(path, "%s%s", dir, name.c_str());
		xr_sprintf(claimed, "%s.claim%u", path, GetCurrentProcessId());
		if (!MoveFileA(path, claimed)) continue; // another server took it
		xr_string text;
		if (FILE* f = fopen(claimed, "rb"))
		{
			char buffer[4096];
			size_t n;
			while ((n = fread(buffer, 1, sizeof(buffer), f)) > 0 && text.size() < 4 * 1024 * 1024) text.append(buffer, n);
			fclose(f);
		}
		// lostzone-car 1 / level / x y z gv health fuel / seats / record
		size_t lines[4] = {};
		size_t at = 0;
		bool ok = true;
		for (int i = 0; i < 4 && ok; ++i)
		{
			at = text.find('\n', at);
			ok = at != xr_string::npos;
			if (ok) lines[i] = at++;
		}
		float x = 0, y = 0, z = 0, health = 1, fuel = 0;
		unsigned gv = 0;
		ok = ok && !text.compare(0, 14, "lostzone-car 1") &&
			sscanf(text.c_str() + lines[1] + 1, "%f %f %f %u %f %f", &x, &y, &z, &gv, &health, &fuel) == 6;
		int car_id = 0;
		if (ok)
		{
			::luabind::functor<int> restore;
			if (ai().script_engine().functor("netcoop_vehicles.restore", restore))
			{
				try { car_id = restore(text.c_str() + lines[3] + 1, x, y, z, int(gv)); }
				catch (...) { car_id = 0; }
			}
		}
		if (car_id <= 0 || car_id >= 0xffff)
		{
			string_path failed;
			xr_sprintf(failed, "%s.failed", path);
			MoveFileA(claimed, failed);
			Msg("! [Lost Zone][vehicle] a car from %s could not be put down", name.c_str());
			continue;
		}
		const xr_string seats = text.substr(lines[2] + 1, lines[3] - lines[2] - 1);
		for (u32 i = 0, count = _GetItemCount(seats.c_str()); i < count; ++i)
		{
			string128 item, login, value;
			_GetItem(seats.c_str(), i, item);
			if (_GetItemCount(item, ':') != 3) continue;
			VehicleArrival arrival;
			arrival.login = _GetItem(item, 0, login, ':');
			to_lower(arrival.login);
			arrival.slot = u8(atoi(_GetItem(item, 1, value, ':')));
			arrival.seat = u8(atoi(_GetItem(item, 2, value, ':')));
			arrival.car = u16(car_id);
			arrival.until = Level().timeServer() + 180000;
			s_vehicle_arrivals.push_back(arrival);
		}
		VehicleCondition condition = {u16(car_id), health, fuel, Level().timeServer() + 60000};
		s_vehicle_conditions.push_back(condition);
		DeleteFileA(claimed);
		Msg("[Lost Zone][vehicle] a car arrived (%u) for %s", car_id, seats.c_str());
	}
}

static void vehicle_arrivals(xrServer* server)
{
	const u32 now = Level().timeServer();
	for (auto it = s_vehicle_conditions.begin(); it != s_vehicle_conditions.end();)
	{
		CCar* car = smart_cast<CCar*>(Level().Objects.net_Find(it->car));
		if (car)
		{
			car->SetfHealth(it->health);
			car->netcoop_set_fuel(it->fuel);
		}
		if (car || now > it->until) it = s_vehicle_conditions.erase(it);
		else ++it;
	}
	for (auto it = s_vehicle_arrivals.begin(); it != s_vehicle_arrivals.end();)
	{
		if (now > it->until) { it = s_vehicle_arrivals.erase(it); continue; }
		struct Find
		{
			const VehicleArrival* arrival;
			xrClientData* found;
			void operator()(IClient* client)
			{
				xrClientData* CL = static_cast<xrClientData*>(client);
				if (found || !CL || !CL->owner || !CL->netcoop_login.size() || CL->netcoop_character_slot != arrival->slot) return;
				xr_string name = CL->netcoop_login.c_str();
				to_lower(name);
				if (name == arrival->login) found = CL;
			}
		} find = {&*it, nullptr};
		server->ForEachClientDo(find);
		CCar* car = smart_cast<CCar*>(Level().Objects.net_Find(it->car));
		CActor* actor = find.found ? smart_cast<CActor*>(Level().Objects.net_Find(find.found->owner->ID)) : nullptr;
		const VehicleSeats* poses = car ? vehicle_seats(car) : nullptr;
		if (!actor || !actor->g_Alive() || !poses || s_character_restore.find(actor->ID()) != s_character_restore.end())
		{
			++it;
			continue;
		}
		VehicleRuntime& v = *vehicle_runtime(car, *poses);
		if (!actor->netcoop_seated() && it->seat < v.seats.size() && v.seats[it->seat] == vehicle_seat_free)
			vehicle_seat_server(car, v, *poses, it->seat, actor);
		it = s_vehicle_arrivals.erase(it);
	}
}

// Every server frame: seated players follow their seats, drivers that went
// silent stop, and the state goes out (10 Hz while used, 0.5 Hz parked).
// Owner 2026-10-17: every vehicle was far too fast. The authority caps the
// horizontal speed: netcoop_max_speed_kmh of the car's section, 70 km/h for
// cars and 120 km/h for helicopters by default. Falling is not limited.
static void vehicle_speed_limit(CCar* car)
{
	static xr_map<shared_str, float> limits; // section -> m/s
	auto found = limits.find(car->cNameSect());
	if (found == limits.end())
	{
		const float kmh = READ_IF_EXISTS(pSettings, r_float, car->cNameSect(), "netcoop_max_speed_kmh",
			car->netcoop_is_heli() ? 120.f : 70.f);
		found = limits.insert(std::make_pair(car->cNameSect(), _max(5.f, kmh) / 3.6f)).first;
	}
	CPhysicsShell* shell = car->PPhysicsShell();
	if (!shell || !shell->isActive()) return;
	Fvector velocity;
	shell->get_LinearVel(velocity);
	const float horizontal = _sqrt(velocity.x * velocity.x + velocity.z * velocity.z);
	if (!_valid(horizontal) || horizontal <= found->second) return;
	const float k = found->second / horizontal;
	for (u16 i = 0; i < shell->get_ElementsNumber(); ++i)
	{
		CPhysicsElement* element = shell->get_ElementByStoreOrder(i);
		Fvector own;
		element->get_LinearVel(own);
		own.x *= k;
		own.z *= k;
		element->set_LinearVel(own);
	}
}

// A moving car hits the players in its way (owner 2026-10-24, spec 2.3:
// "cars drive through players and hurt nobody"). Players' capsules are their
// clients'; on the server nothing stopped the car or hurt the player. Every
// 100 ms a car going faster than RUN_OVER_SPEED hits each player whose body is
// inside its box: a strike that grows with the speed, pushing along the car's
// way, once per RUN_OVER_REPEAT ms per player.
static const float RUN_OVER_SPEED = 3.f; // m/s
static const u32 RUN_OVER_REPEAT = 800;
static xr_map<u32, u32> s_run_over_last; // car id << 16 | player id -> time

static bool vehicle_swept_hit(const Fbox& box, const Fvector& point, const Fvector& travel)
{
	float enter=0.f,leave=1.f;
	for(u32 axis=0;axis<3;++axis) {
		const float p=point[axis],d=travel[axis];
		if(_abs(d)<.00001f) {if(p<box.min[axis] || p>box.max[axis])return false;continue;}
		float a=(box.min[axis]-p)/d,b=(box.max[axis]-p)/d;
		if(a>b)std::swap(a,b);
		enter=_max(enter,a);leave=_min(leave,b);
		if(enter>leave)return false;
	}
	return true;
}

static void vehicle_run_over(CCar* car, VehicleRuntime& v, u32 now)
{
	if (now - v.run_over_check < 100) return;
	const float elapsed=v.run_over_check ? _min(.25f,float(now-v.run_over_check)/1000.f):.1f;
	v.run_over_check = now;
	CPhysicsShell* shell = car->PPhysicsShell();
	if (!shell || !shell->isActive() || !car->Visual()) return;
	Fvector velocity;
	shell->get_LinearVel(velocity);
	const float speed = velocity.magnitude();
	if (!_valid(speed) || speed < RUN_OVER_SPEED) return;
	Fbox box = car->Visual()->getVisData().box;
	box.grow(0.65f); // player capsule, including the contact solver's separation
	Fmatrix to_car;
	to_car.invert(car->XFORM());
	Fvector world_travel,travel;world_travel.mul(velocity,elapsed);to_car.transform_dir(travel,world_travel);
	Fvector way = velocity;
	way.normalize_safe();
	CActor* driver = !v.seats.empty() && v.seats[0] != vehicle_seat_free ?
		smart_cast<CActor*>(Level().Objects.net_Find(v.seats[0])) : nullptr;
	for (u32 n = 0; n < Level().Objects.o_count(); ++n)
	{
		CActor* player = smart_cast<CActor*>(Level().Objects.o_get_by_iterator(n));
		if (!player || player->ID() == 0 || !player->g_Alive() || player->getDestroy() ||
			player->m_netcoop_seat_car == car->ID() ||
            (player->m_netcoop_platform_car == car->ID() && now-player->m_netcoop_platform_time<1000)) continue;
		Fvector local, centre = player->Position();
		centre.y += 0.9f;
		to_car.transform_tiny(local, centre);
		if (!vehicle_swept_hit(box,local,travel)) continue;
		u32& last = s_run_over_last[(u32(car->ID()) << 16) | player->ID()];
		if (last && now - last < RUN_OVER_REPEAT) continue;
		last = now;
		const float power = _min(2.f, (speed - RUN_OVER_SPEED) * 0.06f + 0.1f);
		NET_Packet P;
		SHit hit(power, way, driver ? static_cast<CObject*>(driver) : car, 0, Fvector().set(0.f, 0.f, 0.f),
			speed * 60.f, ALife::eHitTypeStrike, 0.f, false);
		hit.GenHeader(GE_HIT, player->ID());
		hit.whoID = driver ? driver->ID() : car->ID();
		hit.weaponID = car->ID();
		hit.Write_Packet(P);
		car->u_EventSend(P);
		Msg("[Lost Zone][vehicle] %s hit %s at %.1f m/s (%.2f)", car->cName().c_str(), player->cName().c_str(), speed, power);
	}
}

void vehicle_server_update(xrServer* server)
{
	if (!g_pGameLevel || pure_client())
		return;
	const u32 now = Level().timeServer();
	if (cluster_config_present() && now - s_vehicle_inbox_check >= 2000)
	{
		s_vehicle_inbox_check = now;
		vehicle_inbox(server);
	}
	if (!s_vehicle_arrivals.empty() || !s_vehicle_conditions.empty())
		vehicle_arrivals(server);
	if (s_vehicles_sv.empty())
		return;
	for (auto it = s_vehicles_sv.begin(); it != s_vehicles_sv.end();)
	{
		VehicleRuntime& v = it->second;
		CCar* car = smart_cast<CCar*>(Level().Objects.net_Find(it->first));
		const bool usable = car && !car->getDestroy() && !car->netcoop_destroyed() && vehicle_seats(car);
		bool occupied = false;
		for (u8 i = 0; i < v.seats.size(); ++i)
		{
			if (v.seats[i] == vehicle_seat_free)
				continue;
			CActor* actor = smart_cast<CActor*>(Level().Objects.net_Find(v.seats[i]));
			if (!usable || !actor || !actor->g_Alive() || actor->getDestroy() || actor->m_netcoop_seat_car != it->first)
			{
				vehicle_unseat_server(usable ? car : nullptr, v, i);
				continue;
			}
			if(actor->m_netcoop_seat_phase && now-actor->m_netcoop_seat_phase_start>=1800) {
				const bool leaving=actor->m_netcoop_seat_phase==2;
				if(actor->m_netcoop_seat_door!=BI_NONE) car->DoorClose(actor->m_netcoop_seat_door);
				actor->m_netcoop_seat_phase=0;actor->m_netcoop_seat_motion.invalidate();v.dirty=true;
				if(leaving && vehicle_unseat_server(car,v,i,false)) continue;
			}
			actor->netcoop_seat_place();
			occupied = true;
		}
		if (!usable)
		{
			s_vehicle_seats.erase(it->first);
			it = s_vehicles_sv.erase(it);
			continue;
		}
		// The driver takes the car into a passage.
		if (!v.seats.empty() && v.seats[0] != vehicle_seat_free && now - v.transit_check >= 250 && now >= v.transit_refused)
		{
			v.transit_check = now;
			if (CActor* driver = smart_cast<CActor*>(Level().Objects.net_Find(v.seats[0])))
				for (CLevelChanger* changer : g_lchangers)
					if (changer->feel_touch_contact(driver))
					{
						vehicle_transit(server, car, v, changer, driver);
						break;
					}
		}
		vehicle_speed_limit(car);
		if (occupied) vehicle_run_over(car, v, now);
		// A driver whose client stopped sending lets go of the pedals.
		if (v.keys && now - v.keys_time > 2000)
		{
			car->netcoop_drive(0);
			v.keys = 0;
			v.dirty = true;
		}
		const u32 period = occupied || car->netcoop_engine_on() ? 100u : 2000u;
		if (v.dirty || now - v.sent >= period)
		{
			vehicle_send_state(server, car, v, v.dirty);
			v.sent = now;
			v.dirty = false;
		}
		++it;
	}
}

