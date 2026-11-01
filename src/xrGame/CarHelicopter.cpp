// Lost Zone (owner 2026-10-20, doc 151): helicopters apart from cars. A car
// section with netcoop_heli = true flies; the flight, rotors and crash are
// here, the ground vehicle stays in Car.cpp.
#include "stdafx.h"
#include "car.h"
#include "ParticlesObject.h"
#include "PHDestroyable.h"
#include "cameralook.h"
#include "camerafirsteye.h"
#include "Actor.h"
#include "ActorEffector.h"
#include "math.h"
#include "script_entity_action.h"
#include "inventory.h"
#include "xrserver_objects_alife_items.h"
#include "../Include/xrRender/Kinematics.h"
#include "level.h"
#include "ui/UIMainIngameWnd.h"
#include "CarWeapon.h"
#include "game_object_space.h"
#include "../xrEngine/gamemtllib.h"
#include "CharacterPhysicsSupport.h"
#include "car_memory.h"
#include "../xrphysics/IPHWorld.h"
#include "script_game_object.h"
#include "script_hit.h"
#include "netcoop.h"
#include "../xrEngine/IGame_Persistent.h"
#include "../xrEngine/Environment.h"
#include "../xrphysics/Geometry.h"
#include "../xrEngine/bone.h"

// ---------------------------------------------------------------------------
// Lost Zone helicopters (doc 137)
// ---------------------------------------------------------------------------
void CCar::netcoop_heli_load()
{
	NetcoopHeli& h = m_netcoop_heli;
	h = NetcoopHeli();
	LPCSTR section = cNameSect().c_str();
	if (!READ_IF_EXISTS(pSettings, r_bool, section, "netcoop_heli", false))
		return;
	IKinematics* K = smart_cast<IKinematics*>(Visual());
	if (!K)
		return;
	h.on = true;
	h.auto_collective = READ_IF_EXISTS(pSettings, r_bool, section, "heli_auto_collective", true);
	h.auto_level = READ_IF_EXISTS(pSettings, r_bool, section, "heli_auto_level", true);
	h.ground_clearance = READ_IF_EXISTS(pSettings, r_float, section, "heli_ground_clearance", 0.f);
	h.lift_ratio = READ_IF_EXISTS(pSettings, r_float, section, "heli_lift_ratio", h.lift_ratio);
	h.max_pitch = deg2rad(READ_IF_EXISTS(pSettings, r_float, section, "heli_max_pitch", rad2deg(h.max_pitch)));
	h.max_roll = deg2rad(READ_IF_EXISTS(pSettings, r_float, section, "heli_max_roll", rad2deg(h.max_roll)));
	h.attitude_gain = READ_IF_EXISTS(pSettings, r_float, section, "heli_attitude_gain", h.attitude_gain);
	h.bank_turn = READ_IF_EXISTS(pSettings, r_float, section, "heli_bank_turn", h.bank_turn);
	h.pitch_rate = READ_IF_EXISTS(pSettings, r_float, section, "heli_pitch_rate", h.pitch_rate);
	h.roll_rate = READ_IF_EXISTS(pSettings, r_float, section, "heli_roll_rate", h.roll_rate);
	h.yaw_rate = READ_IF_EXISTS(pSettings, r_float, section, "heli_yaw_rate", h.yaw_rate);
	h.rate_gain = READ_IF_EXISTS(pSettings, r_float, section, "heli_rate_gain", h.rate_gain);
	h.drag = READ_IF_EXISTS(pSettings, r_float, section, "heli_drag", h.drag);
	h.vertical_damping = READ_IF_EXISTS(pSettings, r_float, section, "heli_vertical_damping", h.vertical_damping);
	h.ground_effect = READ_IF_EXISTS(pSettings, r_float, section, "heli_ground_effect", h.ground_effect);
	h.rotor_diameter = READ_IF_EXISTS(pSettings, r_float, section, "heli_rotor_diameter", h.rotor_diameter);
	h.spool_up = READ_IF_EXISTS(pSettings, r_float, section, "heli_spool_up", h.spool_up);
	h.spool_down = READ_IF_EXISTS(pSettings, r_float, section, "heli_spool_down", h.spool_down);
	h.collective_rate = READ_IF_EXISTS(pSettings, r_float, section, "heli_collective_rate", h.collective_rate);
	h.climb_rate = READ_IF_EXISTS(pSettings, r_float, section, "heli_climb_rate", h.climb_rate);
	h.sink_rate = READ_IF_EXISTS(pSettings, r_float, section, "heli_sink_rate", h.sink_rate);
	h.climb_gain = READ_IF_EXISTS(pSettings, r_float, section, "heli_climb_gain", h.climb_gain);
	h.crash_speed = READ_IF_EXISTS(pSettings, r_float, section, "heli_crash_speed", h.crash_speed);
	// A new helicopter is pushed out of the ground and settles: no impact.
	h.crash_armed = Device.dwTimeGlobal + 5000;
	h.rotor_anim_speed = READ_IF_EXISTS(pSettings, r_float, section, "heli_rotor_anim_speed", h.rotor_anim_speed);
	// The model's own "idle" turns the rotors (the AI helicopter plays it at
	// full speed); here it runs as fast as the rotor and stands still parked.
	if (IKinematicsAnimated* animated = smart_cast<IKinematicsAnimated*>(Visual()))
	{
		const MotionID idle = animated->ID_Cycle_Safe("idle");
		if (idle.valid())
		{
			// A whole-body cycle plays once per partition and PlayCycle then
			// returns no blend (the owner saw the rotor turn with the engine
			// off): the speed is set on every blend of the model instead.
			animated->PlayCycle(idle, FALSE);
			h.rotor_anim = true;
			netcoop_heli_rotor_speed(0.f);
		}
	}
	xr_vector<Fmatrix> rest;K->LL_GetBindTransform(rest);
	const u16 root=K->LL_BoneID("root");
	const LPCSTR names[]={"gear_left","gear_right","gear_nose"};
	const Fvector travel[]={{0.65f,1.35f,0.f},{-0.65f,1.35f,0.f},{0.f,1.15f,-0.5f}};
	if(root<rest.size()) for(u32 i=0;i<3;++i) {
		NetcoopHeli::Gear& gear=h.gears[i];gear.bone=K->LL_BoneID(names[i]);
		if(gear.bone==BI_NONE) continue;
		gear.geom=PPhysicsShell() ? PPhysicsShell()->get_GeomByID(gear.bone):nullptr;
		if(!gear.geom || !gear.geom->geometry_transform()) {gear.bone=BI_NONE;gear.geom=nullptr;continue;}
		gear.geom->get_local_form_bt(gear.rest);
		Fmatrix inverse;inverse.invert(rest[root]);inverse.transform_dir(gear.travel,travel[i]);
		K->LL_GetBoneInstance(gear.bone).set_callback(bctCustom,netcoop_heli_gear_bone,this);
		h.gear_supported=true;
	}
}

void CCar::netcoop_heli_gear_bone(CBoneInstance* bone)
{
	CCar* car=static_cast<CCar*>(bone->callback_param());
	IKinematics* model=smart_cast<IKinematics*>(car->Visual());
	const Fvector travel[]={{0.65f,1.35f,0.f},{-0.65f,1.35f,0.f},{0.f,1.15f,-0.5f}};
	for(u32 i=0;model && i<3;++i) {
		const auto& gear=car->m_netcoop_heli.gears[i];
		if(gear.bone!=BI_NONE && &model->LL_GetBoneInstance(gear.bone)==bone)
			bone->mTransform.c.mad(travel[i],1.f-car->m_netcoop_heli.gear_position);
	}
}

void CCar::netcoop_heli_gear_step(float dt)
{
	NetcoopHeli& h=m_netcoop_heli;
	if(!h.gear_supported || !_valid(dt) || dt<=0.f) return;
	const float before=h.gear_position;
	const float step=_min(dt,0.05f)*0.25f; // four seconds, including hydraulic travel
	h.gear_position=h.gear_down ? _min(1.f,before+step):_max(0.f,before-step);
	if(h.gear_position==before) return;
	for(auto& gear:h.gears) if(gear.geom) {
		Fmatrix form=gear.rest;form.c.mad(gear.travel,1.f-h.gear_position);
		gear.geom->set_local_form_bt(form);gear.geom->clear_cashed_tries();gear.geom->clear_motion_history(true);
	}
	if(IKinematics* model=smart_cast<IKinematics*>(Visual())) model->CalculateBones_Invalidate();
	if(h.gear_position==0.f || h.gear_position==1.f)
		Msg("[diag][heli] id=%u gear=%s locked=1",ID(),h.gear_down ? "down":"up");
}

void CCar::netcoop_heli_toggle_gear()
{
	NetcoopHeli& h=m_netcoop_heli;
	if(!h.on || !h.gear_supported || !h.pilot || netcoop::pure_client()) return;
	// Weight-on-wheels lock and hydraulic power. Extension remains available
	// with a stopped engine as an emergency gravity-assisted extension.
	if(h.gear_down && (h.ground_height<2.f || !b_engine_on || h.rotor<0.7f)) {
		Msg("[diag][heli] id=%u gear retraction refused: clearance=%.2f rotor=%.2f engine=%u",ID(),h.ground_height,h.rotor,b_engine_on ? 1u:0u);return;
	}
	h.gear_down=!h.gear_down;
	PPhysicsShell()->Enable();
	Msg("[diag][heli] id=%u gear target=%s",ID(),h.gear_down ? "down":"up");
}

void CCar::netcoop_heli_gear_replica(bool down,float position)
{
	if(!_valid(position) || position<0.f || position>1.f) return;
	m_netcoop_heli.gear_down=down;m_netcoop_heli.gear_position=position;
	for(auto& gear:m_netcoop_heli.gears) if(gear.geom) {
		Fmatrix form=gear.rest;form.c.mad(gear.travel,1.f-position);
		gear.geom->set_local_form_bt(form);gear.geom->clear_cashed_tries();gear.geom->clear_motion_history(true);
	}
	if(IKinematics* model=smart_cast<IKinematics*>(Visual())) model->CalculateBones_Invalidate();
}

void CCar::netcoop_heli_rotor_speed(float speed)
{
	struct SetSpeed : IterateBlendsCallback
	{
		float speed;
		void operator()(CBlend& B) override { B.speed = speed; }
	} set;
	set.speed = speed;
	if (IKinematicsAnimated* animated = smart_cast<IKinematicsAnimated*>(Visual()))
		animated->LL_IterateBlends(set);
}

// Both sides, every frame: the rotor animation follows the rotor speed (on a
// client from the replicated rpm).
void CCar::netcoop_heli_rotors()
{
	NetcoopHeli& h = m_netcoop_heli;
	if (!h.on || !h.rotor_anim)
		return;
	float spool = h.rotor;
	if (netcoop::pure_client())
		spool = m_max_rpm > m_min_rpm && b_engine_on ? _max(0.f, _min(1.f, (m_netcoop_rpm - m_min_rpm) / (m_max_rpm - m_min_rpm))) : 0.f;
	netcoop_heli_rotor_speed(spool * h.rotor_anim_speed);
}

void CCar::netcoop_heli_weather()
{
	NetcoopHeli& h=m_netcoop_heli;
	if(Device.dwTimeGlobal<h.weather_probe) return;
	h.weather_probe=Device.dwTimeGlobal+500;
	h.wind.set(0.f,0.f,0.f);h.rain=0.f;
	if(!g_pGamePersistent || !g_pGamePersistent->pEnvironment || !g_pGamePersistent->Environment().CurrentEnv) return;
	const CEnvDescriptorMixer& env=*g_pGamePersistent->Environment().CurrentEnv;
	const float strength=_valid(env.wind_velocity) ? _max(0.f,_min(30.f,env.wind_velocity)):0.f;
	const float direction=_valid(env.wind_direction) ? env.wind_direction:0.f;
	h.wind.set(sinf(direction)*strength,0.f,cosf(direction)*strength);
	h.rain=_valid(env.rain_density) ? _max(0.f,_min(1.f,env.rain_density)):0.f;
}

void CCar::netcoop_heli_step(float dt)
{
	NetcoopHeli& h = m_netcoop_heli;
	CPhysicsShell* shell = PPhysicsShell();
	IKinematics* K = smart_cast<IKinematics*>(Visual());
	if (!shell || !K || !_valid(dt) || dt <= 0.f || !shell->get_ElementsNumber())
		return;
	// bone_map is static construction scratch, overwritten by the next car's
	// spawn. Flight must only ever apply forces to this helicopter's shell.
	CPhysicsElement* body = shell->get_ElementByStoreOrder(0);
	if (!body)
		return;
	// Physics can catch up after a long host frame; bounded controls must not
	// jump an entire rotor/collective range in a single call.
	dt=_min(dt,0.05f);
	netcoop_heli_weather();
	netcoop_heli_gear_step(dt);
	const u8 keys = m_netcoop_keys;
	// Rotor spool and collective. An empty tank spools the rotor down.
	const float spool_target = b_engine_on && m_fuel > 0.f ? 1.f : 0.f;
	if (h.rotor < spool_target)
		h.rotor = _min(spool_target, h.rotor + h.spool_up * dt);
	else
		h.rotor = _max(spool_target, h.rotor - h.spool_down * dt);
	m_current_rpm = m_min_rpm + h.rotor * (m_max_rpm - m_min_rpm); // engine sound, replication
	if (b_engine_on)
		m_fuel = _max(0.f, m_fuel - dt * m_current_rpm * m_fuel_consumption);
	// An impact (owner 2026-10-17: a falling helicopter must crash): the
	// speed of the last moments, decaying 30 m/s per second, against now.
	// Braking by drag or a landing never loses crash_speed that fast.
	Fvector velocity;
	shell->get_LinearVel(velocity);
	const float speed = _valid(velocity) ? velocity.magnitude() : 0.f;
	if (Device.dwTimeGlobal < h.crash_armed)
		h.recent_speed = 0.f;
	else if (!h.crashed && h.recent_speed - speed > h.crash_speed)
	{
		h.crashed = true;
		netcoop_heli_crash();
		return;
	}
	h.recent_speed = _max(speed, h.recent_speed - 30.f * dt);
	if (h.rotor < 0.01f && !keys)
		return; // parked: no forces, the body may sleep
	shell->Enable();

	Fmatrix xform;
	body->GetGlobalTransformDynamic(&xform);
	const float mass = shell->getMass();
	const float g = physics_world()->Gravity();
	// Ground effect: within one rotor diameter of the ground the lift grows by up to ground_effect.
	if (Device.dwTimeGlobal >= h.ground_probe)
	{
		h.ground_probe = Device.dwTimeGlobal + 100;
		collide::rq_result hit;
		Fvector start = xform.c, down;
		down.set(0.f, -1.f, 0.f);
		start.y += 0.5f;
		const float clearance=h.ground_clearance+(h.gear_supported ? h.gear_position*0.95f:0.f);
		h.ground_height = Level().ObjectSpace.RayPick(start, down, h.rotor_diameter+clearance, collide::rqtStatic, hit, this)
			? _max(0.f,hit.range - 0.5f-clearance) : 100.f;
	}
	h.recent_sink=_max(-velocity.y,h.recent_sink-3.f*dt);
	if(h.gear_supported) {
		if(h.ground_height>1.f) h.airborne=true;
		else if(h.airborne && h.ground_height<0.15f) {
			const bool locked=h.gear_down && h.gear_position>=0.99f;
			const float damage=_max(0.f,h.recent_sink-(locked ? 2.8f:0.6f))*0.12f+(locked ? 0.f:0.35f);
			if(damage>0.f) ChangeCondition(-_min(1.f,damage));
			if(!locked) StopEngine();
			Msg("[diag][heli] id=%u touchdown sink=%.2f gear_locked=%u damage=%.3f",ID(),h.recent_sink,locked ? 1u:0u,damage);
			h.airborne=false;h.recent_sink=0.f;
		}
	}
	const float near_ground = h.ground_height < h.rotor_diameter ? 1.f - _max(0.f, h.ground_height) / h.rotor_diameter : 0.f;
	const float lift_factor = h.lift_ratio * h.rotor * h.rotor * (1.f + h.ground_effect * near_ground);

	// Collective with a vertical speed hold: Space climbs, Ctrl sinks (slower
	// close to the ground), neither holds the height. Standing on the ground
	// without Space it stays down.
	const bool landed = h.ground_height < 0.4f && _abs(velocity.y) < 1.f;
	float collective = 0.f;
	// Nobody at the controls (the pilot jumped out): no collective, it falls.
	if(!h.auto_collective)
	{
		const float input=(keys & netcoop_key_handbrake ? 1.f:0.f)-(keys & netcoop_key_down ? 1.f:0.f);
		if(h.pilot && b_engine_on) h.manual_collective=_max(0.f,_min(1.f,h.manual_collective+input*h.collective_rate*dt));
		else h.manual_collective=_max(0.f,h.manual_collective-h.collective_rate*dt);
		collective=h.pilot ? h.manual_collective:0.f;
	}
	else if (h.pilot && (!landed || (keys & netcoop_key_handbrake)))
	{
		float want_climb = 0.f;
		if (keys & netcoop_key_handbrake)
			want_climb = h.climb_rate;
		else if (keys & netcoop_key_down)
			want_climb = -_max(1.5f, _min(h.sink_rate, h.ground_height * 0.8f));
		const float hover = xform.j.y > 0.2f && lift_factor > EPS ? 1.f / (lift_factor * xform.j.y) : 1.f;
		collective = hover + h.climb_gain * (want_climb - velocity.y) / g;
	}
	collective = _max(0.f, _min(1.f, collective));
	if (h.collective < collective)
		h.collective = _min(collective, h.collective + h.collective_rate * dt);
	else
		h.collective = _max(collective, h.collective - h.collective_rate * dt);
	const float lift = mass * g * h.collective * lift_factor;
	body->applyForce(xform.j.x * lift, xform.j.y * lift, xform.j.z * lift);
	// Contact support is measured at the wheel plane, not at the body's
	// elevated origin. It supplies friction only for the supported weight.
	// A parked rotor must not make an on-ground helicopter drift backwards.
	if(h.ground_height<0.3f && xform.j.y>0.85f && _abs(velocity.y)<1.f)
	{
		const float support=_max(0.f,g-lift*xform.j.y/mass);
		const float horizontal=sqrtf(velocity.x*velocity.x+velocity.z*velocity.z);
		const float brake=horizontal>EPS_L ? _min(6.f,support*0.8f/horizontal):0.f;
		body->applyForce(-velocity.x*mass*brake,0.f,-velocity.z*mass*brake);
	}

	// Quadratic air drag on the whole body.
	Fvector air;air.sub(velocity,h.wind);
	const float airspeed=air.magnitude();
	if (airspeed > EPS_L)
	{
		const float drag = h.drag * 1e-3f * mass * airspeed;
		body->applyForce(-air.x * drag, -air.y * drag, -air.z * drag);
	}
	// One server-owned, smooth disturbance: clients never invent their own
	// gusts. Rain and wind increase it, and ground support attenuates it.
	const float weather=(h.rain*0.6f+_min(1.f,h.wind.magnitude()/6.f))*_min(1.f,_max(0.f,h.ground_height)/3.f);
	const float phase=float(Device.dwTimeGlobal%600000)*0.001f;
	body->applyForce(mass*weather*0.45f*sinf(phase*1.7f),mass*weather*0.2f*sinf(phase*2.3f),mass*weather*0.35f*cosf(phase*1.3f));
	// The rotor disc resists climbing and sinking: a steady climb rate for a
	// held collective, no stone-like drop when it is lowered.
	body->applyForce(0.f, -velocity.y * h.vertical_damping * mass * h.rotor, 0.f);

	// Attitude command: W/S and A/D hold a pitch and a bank angle, released
	// the body levels; Q/E set the turn rate. The body's angular velocity is
	// steered to that (body axes: x right, y up, z forward; +x pitches the
	// nose down, +y turns right, +z banks left).
	Fvector angular, local;
	shell->get_AngularVel(angular);
	local.set(angular.dotproduct(xform.i), angular.dotproduct(xform.j), angular.dotproduct(xform.k));
	const float nose_down = -asinf(_max(-1.f, _min(1.f, xform.k.y)));
	const float bank_left = asinf(_max(-1.f, _min(1.f, xform.i.y)));
	const float want_nose_down = (keys & netcoop_key_forward ? h.max_pitch : 0.f) - (keys & netcoop_key_back ? h.max_pitch : 0.f);
	const float want_bank_left = (keys & netcoop_key_left ? h.max_roll : 0.f) - (keys & netcoop_key_right ? h.max_roll : 0.f);
	const float forward_speed = velocity.dotproduct(xform.k);
	Fvector target;
	const float pitch_error=(h.auto_level || (keys & (netcoop_key_forward|netcoop_key_back))) ? want_nose_down-nose_down:0.f;
	const float roll_error=(h.auto_level || (keys & (netcoop_key_left|netcoop_key_right))) ? want_bank_left-bank_left:0.f;
	target.x = _max(-h.pitch_rate, _min(h.pitch_rate, h.attitude_gain*pitch_error));
	target.z = _max(-h.roll_rate, _min(h.roll_rate, h.attitude_gain*roll_error));
	target.y = (keys & netcoop_key_yaw_right ? h.yaw_rate : 0.f) - (keys & netcoop_key_yaw_left ? h.yaw_rate : 0.f);
	// A bank in forward flight turns the nose the same way.
	target.y -= bank_left * h.bank_turn * _max(0.f, _min(1.f, forward_speed / 15.f));
	target.y = _max(-h.yaw_rate, _min(h.yaw_rate, target.y));
	// Cyclic authority builds with rotor speed and stays limited on the
	// ground. Starting an engine cannot tip its body from a stray held key.
	const float authority=h.ground_height<0.3f && h.collective*lift_factor<0.95f ? 0.f:h.rotor*h.rotor;
	target.x*=authority;target.y*=authority;target.z*=authority;
	target.x+=weather*0.035f*sinf(phase*1.1f);target.z+=weather*0.045f*cosf(phase*1.4f);
	Fvector error;
	error.sub(target, local);
	const float gain = h.rate_gain * mass * h.rotor;
	Fvector torque;
	torque.set(0.f, 0.f, 0.f);
	torque.mad(xform.i, error.x * gain);
	torque.mad(xform.j, error.y * gain);
	torque.mad(xform.k, error.z * gain);
	if (_valid(torque))
		body->applyTorque(torque.x, torque.y, torque.z);
	if(h.pilot && Device.dwTimeGlobal>=h.diagnostic_at) {
		h.diagnostic_at=Device.dwTimeGlobal+5000;
		Msg("[diag][heli-flight] id=%u keys=%u rotor=%.3f collective=%.3f manual=%.3f height=%.2f velocity=%.2f,%.2f,%.2f pitch=%.3f roll=%.3f gear=%.3f wind=%.2f,%.2f rain=%.2f mass=%.0f",
			ID(),u32(keys),h.rotor,h.collective,h.manual_collective,h.ground_height,velocity.x,velocity.y,velocity.z,nose_down,bank_left,h.gear_position,h.wind.x,h.wind.z,h.rain,mass);
	}
}

// Server: a helicopter that hit the ground or a wall hard enough dies like a
// car shot to pieces - the death goes to every client and it explodes there.
void CCar::netcoop_heli_crash()
{
	if (b_exploded || !g_Alive())
		return;
	Msg("[Lost Zone][heli] %s (%u) crashed", cName().c_str(), ID());
	ChangeCondition(-1.f);
}
