#include "stdafx.h"
#include "Actor.h"
#include "ActorAnimation.h"
#include "actor_anim_defs.h"
#include "weapon.h"
#include "inventory.h"
#include "missile.h"
#include "level.h"
#include "netcoop.h"
#ifdef DEBUG
#include "PHDebug.h"
#include "ui_base.h"
#endif
#include "hit.h"
#include "PHDestroyable.h"
#include "Car.h"
#include "../Include/xrRender/Kinematics.h"
#include "ai_object_location.h"
#include "game_cl_base.h"
#include "../xrEngine/motion.h"
#include "netcoop_consumption.h"
#include "artefact.h"
#include "IKLimbsController.h"
#include "player_hud.h"
#include "WeaponKnife.h"
#include "Pda.h"
#include "CustomDevice.h"
#include "Flashlight.h"
#include "../xrEngine/SkeletonMotions.h"
#include "../xrEngine/bone.h"
#include "xrMessages.h"

static const float y_spin0_factor = 0.0f;
static const float y_spin1_factor = 0.4f;
static const float y_shoulder_factor = 0.4f;
static const float y_head_factor = 0.2f;
static const float p_spin0_factor = 0.0f;
static const float p_spin1_factor = 0.2f;
static const float p_shoulder_factor = 0.7f;
static const float p_head_factor = 0.1f;
static const float r_spin0_factor = 0.3f;
static const float r_spin1_factor = 0.3f;
static const float r_shoulder_factor = 0.2f;
static const float r_head_factor = 0.2f;

CBlend* PlayMotionByParts(IKinematicsAnimated* sa, MotionID motion_ID, BOOL bMixIn, PlayCallback Callback,
                          LPVOID CallbackParam);

void CActor::Spin0Callback(CBoneInstance* B)
{
	CActor* A = static_cast<CActor*>(B->callback_param());
	VERIFY(A);

	Fmatrix spin;
	float bone_yaw = angle_normalize_signed(A->r_torso.yaw - A->r_model_yaw - A->r_model_yaw_delta) * y_spin0_factor;
	float bone_pitch = angle_normalize_signed(A->r_torso.pitch) * p_spin0_factor;
	float bone_roll = angle_normalize_signed(A->r_torso.roll) * r_spin0_factor;
	Fvector c = B->mTransform.c;
	spin.setXYZ(-bone_pitch, bone_yaw, bone_roll);
	B->mTransform.mulA_43(spin);
	B->mTransform.c = c;
}

void CActor::Spin1Callback(CBoneInstance* B)
{
	CActor* A = static_cast<CActor*>(B->callback_param());
	VERIFY(A);

	Fmatrix spin;
	float bone_yaw = angle_normalize_signed(A->r_torso.yaw - A->r_model_yaw - A->r_model_yaw_delta) * y_spin1_factor;
	float bone_pitch = angle_normalize_signed(A->r_torso.pitch) * p_spin1_factor;
	float bone_roll = angle_normalize_signed(A->r_torso.roll) * r_spin1_factor;
	Fvector c = B->mTransform.c;
	spin.setXYZ(-bone_pitch, bone_yaw, bone_roll);
	B->mTransform.mulA_43(spin);
	B->mTransform.c = c;
}

void CActor::ShoulderCallback(CBoneInstance* B)
{
	CActor* A = static_cast<CActor*>(B->callback_param());
	VERIFY(A);
	Fmatrix spin;
	float bone_yaw = angle_normalize_signed(A->r_torso.yaw - A->r_model_yaw - A->r_model_yaw_delta) * y_shoulder_factor;
	float bone_pitch = angle_normalize_signed(A->r_torso.pitch) * p_shoulder_factor;
	float bone_roll = angle_normalize_signed(A->r_torso.roll) * r_shoulder_factor;
	Fvector c = B->mTransform.c;
	spin.setXYZ(-bone_pitch, bone_yaw, bone_roll);
	B->mTransform.mulA_43(spin);
	B->mTransform.c = c;
}

#include "../xrEngine/CameraBase.h"

void CActor::HeadCallback(CBoneInstance* B)
{
	CActor* A = static_cast<CActor*>(B->callback_param());
	VERIFY(A);
	Fmatrix spin;
	float bone_yaw;

	if (A->cam_freelook != eflDisabled)
		bone_yaw = angle_normalize_signed(-A->cam_FirstEye()->yaw - A->r_model_yaw - A->r_model_yaw_delta) * .35f;
	else
		bone_yaw = angle_normalize_signed(A->r_torso.yaw - A->r_model_yaw - A->r_model_yaw_delta) * y_head_factor;

	float bone_pitch = angle_normalize_signed(A->r_torso.pitch) * p_head_factor;
	float bone_roll = angle_normalize_signed(A->r_torso.roll) * r_head_factor;
	Fvector c = B->mTransform.c;
	spin.setXYZ(-bone_pitch, bone_yaw, bone_roll);
	B->mTransform.mulA_43(spin);
	B->mTransform.c = c;
}

void CActor::VehicleHeadCallback(CBoneInstance* B)
{
	CActor* A = static_cast<CActor*>(B->callback_param());
	VERIFY(A);
	Fmatrix spin;
	float bone_yaw = angle_normalize_signed(A->r_torso.yaw) * 0.75f;
	float bone_pitch = angle_normalize_signed(A->r_torso.pitch) * 0.75f;
	float bone_roll = angle_normalize_signed(A->r_torso.roll) * r_head_factor;
	Fvector c = B->mTransform.c;
	spin.setHPB(bone_yaw, bone_pitch, -bone_roll);
	B->mTransform.mulA_43(spin);
	B->mTransform.c = c;
}

void STorsoWpn::Create(IKinematicsAnimated* K, LPCSTR base0, LPCSTR base1)
{
	char buf[128];
	moving[eIdle] = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_aim_1"));
	moving[eWalk] = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_aim_2"));
	moving[eRun] = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_aim_3"));
	moving[eSprint] = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_escape_0"));
	zoom = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_aim_0"));
	holster = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_holster_0"));
	draw = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_draw_0"));
	reload = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_reload_0"));
	reload_1 = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_reload_1"));
	reload_2 = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_reload_2"));
	drop = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_drop_0"));
	attack = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_attack_1"));
	attack_zoom = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_attack_0"));
	fire_idle = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_attack_1"));
	fire_end = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_attack_2"));
	all_attack_0 = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_all", base1, "_attack_0"));
	all_attack_1 = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_all", base1, "_attack_1"));
	all_attack_2 = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_all", base1, "_attack_2"));
	safemode = K->ID_Cycle_Safe(strconcat(sizeof(buf), buf, base0, "_torso", base1, "_idle_1"));
}

void SAnimState::Create(IKinematicsAnimated* K, LPCSTR base0, LPCSTR base1)
{
	char buf[128];
	legs_fwd = K->ID_Cycle(strconcat(sizeof(buf), buf, base0, base1, "_fwd_0"));
	legs_back = K->ID_Cycle(strconcat(sizeof(buf), buf, base0, base1, "_back_0"));
	legs_ls = K->ID_Cycle(strconcat(sizeof(buf), buf, base0, base1, "_ls_0"));
	legs_rs = K->ID_Cycle(strconcat(sizeof(buf), buf, base0, base1, "_rs_0"));
}


void SActorState::CreateClimb(IKinematicsAnimated* K)
{
	string128 buf, buf1;
	string16 base;

	//climb anims
	xr_strcpy(base, "cl");
	legs_idle = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_idle_1"));
	m_torso_idle = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_torso_0_aim_0"));
	m_walk.Create(K, base, "_run");
	m_run.Create(K, base, "_run");

	//norm anims
	xr_strcpy(base, "norm");
	legs_turn = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_turn"));
	death = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_death_0"));
	m_torso[0].Create(K, base, "_1");
	m_torso[1].Create(K, base, "_2");
	m_torso[2].Create(K, base, "_3");
	m_torso[3].Create(K, base, "_4");
	m_torso[4].Create(K, base, "_5");
	m_torso[5].Create(K, base, "_6");
	m_torso[6].Create(K, base, "_7");
	m_torso[7].Create(K, base, "_8");
	m_torso[8].Create(K, base, "_9");
	m_torso[9].Create(K, base, "_10");
	m_torso[10].Create(K, base, "_11");
	m_torso[11].Create(K, base, "_12");
	m_torso[12].Create(K, base, "_13");


	m_head_idle.invalidate(); ///K->ID_Cycle("head_idle_0");
	jump_begin = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_jump_begin"));
	jump_idle = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_jump_idle"));
	landing[0] = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_jump_end"));
	landing[1] = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_jump_end_1"));

	for (int k = 0; k < 12; ++k)
		m_damage[k] = K->ID_FX(strconcat(sizeof(buf), buf, base, "_damage_", itoa(k, buf1, 10)));
}


void SActorState::Create(IKinematicsAnimated* K, LPCSTR base)
{
	string128 buf, buf1;
	legs_turn = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_turn"));
	legs_idle = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_idle_0"));
	death = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_death_0"));

	m_walk.Create(K, base, "_walk");
	m_run.Create(K, base, "_run");

	m_torso[0].Create(K, base, "_1");
	m_torso[1].Create(K, base, "_2");
	m_torso[2].Create(K, base, "_3");
	m_torso[3].Create(K, base, "_4");
	m_torso[4].Create(K, base, "_5");
	m_torso[5].Create(K, base, "_6");
	m_torso[6].Create(K, base, "_7");
	m_torso[7].Create(K, base, "_8");
	m_torso[8].Create(K, base, "_9");
	m_torso[9].Create(K, base, "_10");
	m_torso[10].Create(K, base, "_11");
	m_torso[11].Create(K, base, "_12");
	m_torso[12].Create(K, base, "_13");

	m_torso_idle = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_torso_0_aim_0"));
	m_head_idle = K->ID_Cycle("head_idle_0");
	jump_begin = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_jump_begin"));
	jump_idle = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_jump_idle"));
	landing[0] = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_jump_end"));
	landing[1] = K->ID_Cycle(strconcat(sizeof(buf), buf, base, "_jump_end_1"));

	for (int k = 0; k < 12; ++k)
		m_damage[k] = K->ID_FX(strconcat(sizeof(buf), buf, base, "_damage_", itoa(k, buf1, 10)));
}

void SActorSprintState::Create(IKinematicsAnimated* K)
{
	//leg anims
	legs_fwd = K->ID_Cycle("norm_escape_00");
	legs_ls = K->ID_Cycle("norm_escape_ls_00");
	legs_rs = K->ID_Cycle("norm_escape_rs_00");

	legs_jump_fwd = K->ID_Cycle("norm_escape_jump_00");
	legs_jump_ls = K->ID_Cycle("norm_escape_ls_jump_00");
	legs_jump_rs = K->ID_Cycle("norm_escape_rs_jump_00");
}

void SActorMotions::Create(IKinematicsAnimated* V)
{
	m_dead_stop = V->ID_Cycle("norm_dead_stop_0");

	m_normal.Create(V, "norm");
	m_crouch.Create(V, "cr");
	//m_climb.Create	(V,"cr");
	m_climb.CreateClimb(V);
	m_sprint.Create(V);
}

SActorVehicleAnims::SActorVehicleAnims()
{
}

void SActorVehicleAnims::Create(IKinematicsAnimated* V)
{
	for (u16 i = 0; TYPES_NUMBER > i; ++i) m_vehicles_type_collections[i].Create(V, i);
}

SVehicleAnimCollection::SVehicleAnimCollection()
{
	for (u16 i = 0; MAX_IDLES > i; ++i) idles[i].invalidate();
	idles_num = 0;
	steer_left.invalidate();
	steer_right.invalidate();
}

void SVehicleAnimCollection::Create(IKinematicsAnimated* V, u16 num)
{
	string128 buf, buff1, buff2;
	strconcat(sizeof(buff1), buff1, itoa(num, buf, 10), "_");
	steer_left = V->ID_Cycle(strconcat(sizeof(buf), buf, "steering_idle_", buff1, "ls"));
	steer_right = V->ID_Cycle(strconcat(sizeof(buf), buf, "steering_idle_", buff1, "rs"));

	for (int i = 0; MAX_IDLES > i; ++i)
	{
		idles[i] = V->ID_Cycle_Safe(strconcat(sizeof(buf), buf, "steering_idle_", buff1, itoa(i, buff2, 10)));
		if (idles[i]) idles_num++;
		else break;
	}
}

void CActor::steer_Vehicle(float angle)
{
	if (!m_holder) return;
	//Alundaio: Re-enable Car
#ifdef	ENABLE_CAR
	CCar* car = smart_cast<CCar*>(m_holder);
	if (!car)
		return;

	u16 anim_type = car->DriverAnimationType();
	SVehicleAnimCollection& anims = m_vehicle_anims->m_vehicles_type_collections[anim_type];
	if (angle == 0.f) smart_cast<IKinematicsAnimated*>(Visual())->PlayCycle(anims.idles[0]);
	else if (angle > 0.f) smart_cast<IKinematicsAnimated*>(Visual())->PlayCycle(anims.steer_right);
	else smart_cast<IKinematicsAnimated*>(Visual())->PlayCycle(anims.steer_left);
#endif
	//-Alundaio
}

void legs_play_callback(CBlend* blend)
{
	CActor* object = (CActor*)blend->CallbackParam;
	VERIFY(object);
	object->m_current_legs.invalidate();
}

void CActor::g_SetSprintAnimation(u32 mstate_rl, MotionID& head, MotionID& torso, MotionID& legs)
{
	SActorSprintState& sprint = m_anims->m_sprint;

	bool jump = (mstate_rl & mcFall) ||
		(mstate_rl & mcLanding) ||
		//(mstate_rl&mcLanding)	||
		(mstate_rl & mcLanding2) ||
		(mstate_rl & mcJump);

	if (mstate_rl & mcFwd) legs = (!jump) ? sprint.legs_fwd : sprint.legs_jump_fwd;
	else if (mstate_rl & mcLStrafe) legs = (!jump) ? sprint.legs_ls : sprint.legs_jump_ls;
	else if (mstate_rl & mcRStrafe) legs = (!jump) ? sprint.legs_rs : sprint.legs_jump_rs;
}

CMotion* FindMotionKeys(MotionID motion_ID, IRenderVisual* V)
{
	IKinematicsAnimated* VA = smart_cast<IKinematicsAnimated*>(V);
	return (VA && motion_ID.valid()) ? VA->LL_GetRootMotion(motion_ID) : 0;
}

#ifdef DEBUG
BOOL	g_ShowAnimationInfo = TRUE;
#endif // DEBUG
char* mov_state[] = {
	"idle",
	"walk",
	"run",
	"sprint",
};

// These combined torso motions are supplied by Anomaly's stalker_animation.omf.
// A secondary HUD device is not the active inventory slot: select its pose
// explicitly, without changing the active weapon or the actor's leg animation.
static CCustomDevice* netcoop_drawn_device(CActor* actor)
{
	if (!netcoop::pure_client())
		return nullptr;
	for (CInventoryItem* item : actor->inventory().m_all)
		if (CCustomDevice* device = smart_cast<CCustomDevice*>(item))
			if (!device->IsHidden())
				return device;
	return nullptr;
}

static MotionID netcoop_device_torso(CActor* actor, CCustomDevice* device, u32 movement,
                                    STorsoWpn::eMovingState moving)
{
	IKinematicsAnimated* model = smart_cast<IKinematicsAnimated*>(actor->Visual());
	if (!model || !netcoop::pure_client() || (movement & mcClimb))
		return MotionID();
	CInventoryItem* active = actor->inventory().ActiveItem();
	CPda* pda = smart_cast<CPda*>(active);
	if (!device && !pda)
		return MotionID();

	LPCSTR family = "pda";
	LPCSTR base = "0"; // xrRazom/xrMPE device poses: xrr_<posture>_torso_<base>_<kind>_<action>
	LPCSTR action = "aim_1";
	CHudItem* item = pda;
	if (device)
	{
		item = device;
		family = "0+detector";
		if (smart_cast<CWeaponKnife*>(active))
			family = "knife+detector", base = "knife";
		else if (smart_cast<CMissile*>(active))
			family = "6+detector", base = "6";
		else if (CWeapon* weapon = smart_cast<CWeapon*>(active))
		{
			if (weapon->animation_slot() != 1)
				return MotionID(); // no combined two-handed weapon pose in the asset
			family = "pistol+detector", base = "pistol";
			if (weapon->GetState() == CWeapon::eReload)
				action = "reload_0";
			else if (weapon->GetState() == CWeapon::eFire)
				action = weapon->IsZoomed() ? "attack_0" : "attack_1";
			else if (weapon->IsZoomed())
				action = "aim_0";
		}
		else if (!active && (device->GetState() == CCustomDevice::eIdleZoom || device->GetState() == CCustomDevice::eIdleZoomIn))
			action = "aim_0"; // a walkie-talkie raised to talk (the device's zoom pose)
	}
	else if (pda->m_bZoomed)
		action = "aim_0";

	if (moving == STorsoWpn::eSprint)
		action = "escape_0";
	else if (moving == STorsoWpn::eRun && xr_strcmp(action, "aim_1") == 0)
		action = "aim_3";
	else if (moving == STorsoWpn::eWalk && xr_strcmp(action, "aim_1") == 0)
		action = "aim_2";
	if (!device)
	{
		if (item->GetState() == CHUDState::eShowing)
			action = "draw_0";
		else if (item->GetState() == CHUDState::eHiding)
			action = "holster_0";
	}
	else
	{
		// Switching with the device in the left hand: the device, the right
		// hand's item (pistol, knife, grenade/bolt), or both at once.
		CHudItem* hand = active ? active->cast_hud_item() : nullptr;
		const u32 hand_state = hand ? hand->GetState() : u32(CHUDState::eHidden);
		const bool device_show = device->GetState() == CHUDState::eShowing;
		const bool device_hide = device->GetState() == CHUDState::eHiding;
		if (device_show && hand_state == CHUDState::eShowing)
			action = "drawall_0";
		else if (device_hide && hand_state == CHUDState::eHiding)
			action = "holsterall_0";
		else if (device_show)
			action = "drawdevice_0";
		else if (device_hide)
			action = "holsterdevice_0";
		else if (hand && hand_state == CHUDState::eShowing)
			action = "draw_0";
		else if (hand && hand_state == CHUDState::eHiding)
			action = "holster_0";
		else if (CWeaponKnife* knife = smart_cast<CWeaponKnife*>(active))
		{
			if (knife->GetState() == CWeapon::eFire)
				action = "attack_0";
			else if (knife->GetState() == CWeapon::eFire2)
				action = "attack_1";
		}
		else if (smart_cast<CMissile*>(active))
		{
			// a grenade or a bolt: the swing, holding it ready, the throw
			if (hand_state == CMissile::eThrowStart)
				action = "attack_0";
			else if (hand_state == CMissile::eReady)
				action = "attack_1";
			else if (hand_state == CMissile::eThrow || hand_state == CMissile::eThrowEnd)
				action = "attack_2";
		}
	}

	string128 name;
	MotionID motion;
	if (device)
	{
		// The pose that matches first person (xrRazom's xrMPE device poses,
		// meshes/actors/modded_stalker_animations): a hand flashlight or a
		// glow stick is held up ("torchelo"), a detector or a walkie-talkie
		// in front ("detector"). Standing poses stand in for missing crouch ones.
		LPCSTR kind = smart_cast<CFlashlight*>(device) ? "torchelo" : "detector";
		// their cycles for a lowered hand: idle_1 / walk_1 / run_1 (ours: aim_1 / aim_2 / aim_3)
		LPCSTR cycle = !xr_strcmp(action, "aim_1") ? "idle_1" : !xr_strcmp(action, "aim_2") ? "walk_1" :
			!xr_strcmp(action, "aim_3") ? "run_1" : action;
		LPCSTR tries[2] = {cycle, action};
		for (LPCSTR a : tries)
		{
			// crouching with a pistol is their slot "1" pose
			const bool crouch = (movement & mcCrouch) != 0;
			xr_sprintf(name, "xrr_%s_torso_%s_%s_%s", crouch ? "cr" : "norm", crouch && !xr_strcmp(base, "pistol") ? "1" : base, kind, a);
			motion = model->ID_Cycle_Safe(name);
			if (!motion.valid())
			{
				xr_sprintf(name, "xrr_norm_torso_%s_%s_%s", base, kind, a);
				motion = model->ID_Cycle_Safe(name);
			}
			if (motion.valid())
				return motion;
		}
	}
	xr_sprintf(name, "%s_torso_%s_%s", (movement & mcCrouch) ? "cr" : "norm", family, action);
	motion = model->ID_Cycle_Safe(name);
	if (!motion.valid())
	{
		// Some Anomaly models only provide standing device motions.
		xr_sprintf(name, "norm_torso_%s_%s", family, action);
		motion = model->ID_Cycle_Safe(name);
	}
	return motion;
}

void CActor::netcoop_tp_item_release()
{
	if (m_netcoop_tp_item)
		::Render->model_Delete(m_netcoop_tp_item);
	m_netcoop_tp_item = nullptr;
	m_netcoop_tp_bone = BI_NONE;
	m_netcoop_tp_track = nullptr;
	m_netcoop_tp_track_bones.clear();
}

struct CActor::NetcoopTpTrack
{
	u32 frames = 0;
	xr_vector<shared_str> bones;
	xr_vector<u8> flags; // [bone * frames + frame]: bit 1 hidden, bit 0 left hand (else right)
	xr_vector<Fmatrix> poses; // [bone * frames + frame]: the item's bone in that hand's space
};

// New Way's track (anims\tp_items\*.trk, "NWT3"): u32 bones, u32 frames twice;
// per bone a NUL-ended name, then per frame u8 flags and 12 floats (rows i, j,
// k and the position). Read once per file; nullptr when missing or broken.
const CActor::NetcoopTpTrack* CActor::netcoop_tp_track_load(LPCSTR file)
{
	static xr_map<shared_str, NetcoopTpTrack*> loaded;
	const shared_str key(file);
	auto known = loaded.find(key);
	if (known != loaded.end()) return known->second;
	NetcoopTpTrack* track = nullptr;
	string_path path;
	IReader* F = FS.exist(path, "$game_anims$", file) ? FS.r_open(path) : nullptr;
	if (F && F->length() >= 16 && !memcmp(F->pointer(), "NWT3", 4))
	{
		F->advance(4);
		const u32 bones = F->r_u32(), frames = F->r_u32(), again = F->r_u32();
		bool good = bones && bones <= 64 && frames && frames <= 20000 && again == frames;
		track = good ? xr_new<NetcoopTpTrack>() : nullptr;
		if (track) track->frames = frames;
		for (u32 b = 0; good && b < bones; ++b)
		{
			xr_string name;
			while (good && F->elapsed() > 0)
			{
				const char c = char(F->r_u8());
				if (!c) break;
				name += c;
				good = name.size() < 64;
			}
			good = good && !name.empty() && F->elapsed() >= int(frames * 49);
			if (!good) break;
			track->bones.push_back(shared_str(name.c_str()));
			for (u32 f = 0; f < frames; ++f)
			{
				track->flags.push_back(F->r_u8());
				float v[12];
				F->r(v, sizeof(v));
				for (float x : v) good = good && _valid(x) && _abs(x) < 100.f;
				Fmatrix pose;
				pose.i.set(v[0], v[1], v[2]); pose._14_ = 0.f;
				pose.j.set(v[3], v[4], v[5]); pose._24_ = 0.f;
				pose.k.set(v[6], v[7], v[8]); pose._34_ = 0.f;
				pose.c.set(v[9], v[10], v[11]); pose._44_ = 1.f;
				track->poses.push_back(pose);
			}
		}
		if (!good) xr_delete(track);
	}
	if (F) FS.r_close(F);
	if (!track) Msg("! [Lost Zone] third-person track %s missing or broken", file);
	loaded[key] = track;
	return track;
}

// The item in the hand, at the bone with New Way's offset, or each bone of
// it where New Way's track puts it at this point of the motion.
void CActor::netcoop_tp_item_render()
{
	if (!m_netcoop_tp_item || m_netcoop_tp_bone == BI_NONE || !m_netcoop_consumption_until) return;
	IKinematics* body = smart_cast<IKinematics*>(Visual());
	if (!body) return;
	IKinematics* model = smart_cast<IKinematics*>(m_netcoop_tp_item);
	if (m_netcoop_tp_track && model)
	{
		const NetcoopTpTrack& track = *m_netcoop_tp_track;
		const CBlend* blend = m_current_torso_blend;
		const float phase = blend && blend->timeTotal > EPS ? clampr(blend->timeCurrent / blend->timeTotal, 0.f, 1.f) : 0.f;
		const u32 frame = _min(track.frames - 1, u32(iFloor(phase * float(track.frames - 1) + 0.5f)));
		model->CalculateBones(TRUE);
		for (u32 b = 0; b < m_netcoop_tp_track_bones.size(); ++b)
		{
			const u16 id = m_netcoop_tp_track_bones[b];
			if (id == BI_NONE) continue;
			const u32 at = b * track.frames + frame;
			const u16 hand = m_netcoop_tp_hands[track.flags[at] & 1];
			CBoneInstance& bone = model->LL_GetBoneInstance(id);
			if ((track.flags[at] & 2) || hand == BI_NONE) bone.mTransform.scale(0.f, 0.f, 0.f);
			else bone.mTransform.mul_43(body->LL_GetTransform(hand), track.poses[at]);
			bone.mRenderTransform.mul_43(bone.mTransform, model->LL_GetData(id).m2b_transform);
		}
		Fmatrix root = XFORM();
		::Render->set_Transform(&root);
		::Render->add_Visual(m_netcoop_tp_item);
		return;
	}
	Fmatrix hand, item;
	hand.mul_43(XFORM(), body->LL_GetTransform(m_netcoop_tp_bone));
	item.mul_43(hand, m_netcoop_tp_offset);
	if (model)
	{
		// The model's own rest pose: an animated item with no motion playing
		// gets zero rotations from the engine (owner 2026-10-25: food and
		// medicine showed nothing, the water bottle hung off the hand).
		model->CalculateBones(TRUE);
		static xr_vector<Fmatrix> rest;
		model->LL_GetBindTransform(rest);
		for (u16 id = 0; id < model->LL_BoneCount(); ++id)
		{
			CBoneInstance& bone = model->LL_GetBoneInstance(id);
			bone.mTransform = rest[id];
			bone.mRenderTransform.mul_43(bone.mTransform, model->LL_GetData(id).m2b_transform);
		}
	}
	::Render->set_Transform(&item);
	::Render->add_Visual(m_netcoop_tp_item);
}

// New Way's third-person data of an item: its Enhanced Animations section
// (items\items\anims_list.ltx: anm -> <anm>_hud) with third_person_motion.
static shared_str netcoop_tp_section(LPCSTR item)
{
	static CInifile* list = []() -> CInifile*
	{
		string_path path;
		return FS.exist(path, "$game_config$", "items\\items\\anims_list.ltx") ? xr_new<CInifile>(path, TRUE, TRUE, FALSE) : nullptr;
	}();
	if (!item || !item[0] || xr_strlen(item) > 200) return shared_str();
	string256 ea;
	if (list && list->section_exist(item) && list->line_exist(item, "anm"))
		xr_sprintf(ea, "%s_hud", list->r_string(item, "anm"));
	else
		xr_sprintf(ea, "%s_hud", item); // a gesture: anim_door_open -> anim_door_open_hud
	if (!pSettings->section_exist(ea) || !pSettings->line_exist(ea, "third_person_motion")) return shared_str();
	return shared_str(ea);
}

// New Way's motion for an item (nullptr: none).
LPCSTR CActor::netcoop_tp_motion(LPCSTR item)
{
	const shared_str tp = netcoop_tp_section(item);
	return tp.size() ? pSettings->r_string(tp, "third_person_motion") : nullptr;
}

// The item in the hand while New Way's motion plays: only a model this
// client has (a missing one would not load).
// Once per item section: what the other players see of its use (owner
// 2026-10-24: "nothing in the hands" - the log says why).
static void netcoop_tp_note(LPCSTR item, LPCSTR what)
{
	static xr_set<shared_str> noted;
	if (noted.size() < 512 && noted.insert(shared_str(item ? item : "")).second)
		Msg("[Lost Zone][3p] %s: %s", item ? item : "?", what);
}

void CActor::netcoop_tp_item_attach(LPCSTR item)
{
	netcoop_tp_item_release();
	const shared_str tp = netcoop_tp_section(item);
	if (!m_netcoop_consumption_until) return;
	if (!tp.size()) return netcoop_tp_note(item, "no New Way data (generic motion)");
	// a gesture (a door, a campfire) has no item
	LPCSTR visual = READ_IF_EXISTS(pSettings, r_string, tp, "third_person_item_visual", nullptr);
	if (!visual || !visual[0]) return netcoop_tp_note(item, "gesture, no item");
	string_path file;
	xr_strcpy(file, visual);
	if (!strext(file)) xr_strcat(file, ".ogf");
	IKinematics* body = smart_cast<IKinematics*>(Visual());
	const u16 bone = body ? body->LL_BoneID(pSettings->r_string(tp, "third_person_attach_bone")) : BI_NONE;
	if (bone == BI_NONE) return netcoop_tp_note(item, "the body has no attach bone");
	if (!FS.exist("$game_meshes$", file)) return netcoop_tp_note(item, make_string("model %s missing", file).c_str());
	m_netcoop_tp_item = ::Render->model_Create(visual);
	if (!m_netcoop_tp_item) return netcoop_tp_note(item, "model failed to load");
	netcoop_tp_note(item, make_string("%s in the hand (%s)", visual, tp.c_str()).c_str());
	m_netcoop_tp_bone = bone;
	const Fvector position = pSettings->r_fvector3(tp, "third_person_attach_position");
	const Fvector rotation = pSettings->r_fvector3(tp, "third_person_attach_rotation");
	m_netcoop_tp_offset.setHPB(rotation.x, rotation.y, rotation.z);
	m_netcoop_tp_offset.translate_over(position);
	IKinematics* model = smart_cast<IKinematics*>(m_netcoop_tp_item);
	if (!model || !pSettings->line_exist(tp, "third_person_track")) return;
	m_netcoop_tp_track = netcoop_tp_track_load(pSettings->r_string(tp, "third_person_track"));
	if (!m_netcoop_tp_track) return;
	m_netcoop_tp_hands[0] = body->LL_BoneID("bip01_r_hand");
	m_netcoop_tp_hands[1] = body->LL_BoneID("bip01_l_hand");
	for (const shared_str& name : m_netcoop_tp_track->bones)
		m_netcoop_tp_track_bones.push_back(model->LL_BoneID(name));
}

void CActor::netcoop_consumption_end(CBlend* blend)
{
	CActor* actor = static_cast<CActor*>(blend->CallbackParam);
	if (actor && actor->m_netcoop_consumption_until && actor->m_current_torso_blend == blend)
	{
		actor->m_netcoop_consumption_until = 0;
		actor->m_bAnimTorsoPlayed = FALSE;
		actor->m_current_torso.invalidate();
		actor->netcoop_tp_item_release();
	}
}

void CActor::netcoop_play_consumption(u8 kind, LPCSTR section)
{
	if (!netcoop::pure_client() || this == Level().CurrentControlEntity() || !g_Alive() ||
		netcoop_seated() || m_rp_index >= 0) return;
	// New Way's motion for this item when it has one, else the kind's
	LPCSTR name = netcoop_tp_motion(section);
	if (!name) name = netcoop_consumption::motion(kind);
	IKinematicsAnimated* model = smart_cast<IKinematicsAnimated*>(Visual());
	if (!name || !model) return;
	const MotionID motion = model->ID_Cycle_Safe(name);
	const u16 torso = model->LL_PartID("torso");
	if (!motion.valid() || torso == u16(-1)) return;
	CMotionDef* def = model->LL_GetMotionDef(motion);
	if (!def || !_valid(def->Speed()) || def->Speed() <= 0.f) return;
	CBlend* blend = model->LL_PlayCycle(torso, motion, TRUE, def->Accrue(), def->Falloff(), def->Speed(),
		TRUE, netcoop_consumption_end, this, 0);
	if (!blend) return;
	m_current_torso_blend = blend;
	m_current_torso = motion;
	m_bAnimTorsoPlayed = TRUE;
	const float duration = _valid(blend->timeTotal) ? blend->timeTotal / def->Speed() * 1000.f : 1000.f;
	m_netcoop_consumption_until = (Device.dwTimeGlobal + u32(_max(100.f, _min(10000.f, duration)))) | 1u;
	netcoop_tp_item_attach(section);
}

void CActor::netcoop_expire_consumption()
{
	if (m_netcoop_consumption_until && (!g_Alive() || netcoop_seated() || m_rp_index >= 0 ||
		s32(Device.dwTimeGlobal - m_netcoop_consumption_until) >= 0))
	{
		m_netcoop_consumption_until = 0;
		m_bAnimTorsoPlayed = FALSE;
		m_current_torso.invalidate();
		netcoop_tp_item_release();
	}
}

void CActor::g_SetAnimation(u32 mstate_rl)
{
	netcoop_expire_consumption();
	// A netcoop RP animation drives the whole body while it plays.
	if (m_rp_index >= 0 && rp_update(mstate_rl))
		return;
	// Sitting in a car (doc 100): the steering or passenger pose.
	if (netcoop_seated() && g_Alive() && netcoop_seat_animation())
		return;
	if (!g_Alive())
	{
		if (m_current_legs || m_current_torso)
		{
			SActorState* ST = 0;
			if (mstate_rl & mcCrouch) ST = &m_anims->m_crouch;
			else ST = &m_anims->m_normal;
			mstate_real = 0;
			m_current_legs.invalidate();
			m_current_torso.invalidate();

			//smart_cast<IKinematicsAnimated*>(Visual())->PlayCycle(m_anims->m_dead_stop);
		}

		return;
	}
	STorsoWpn::eMovingState moving_idx = STorsoWpn::eIdle;
	CCustomDevice* drawn_device = netcoop_drawn_device(this);
	SActorState* ST = 0;
	SAnimState* AS = 0;

	if (mstate_rl & mcCrouch)
		ST = &m_anims->m_crouch;
	else if (mstate_rl & mcClimb)
		ST = &m_anims->m_climb;
	else
		ST = &m_anims->m_normal;

	bool bAccelerated = isActorAccelerated(mstate_rl, IsZoomAimingMode());
	if (bAccelerated)
	{
		AS = &ST->m_run;
	}
	else
	{
		AS = &ST->m_walk;
	}
	if (mstate_rl & mcAnyMove)
	{
		if (bAccelerated)
			moving_idx = STorsoWpn::eRun;
		else
			moving_idx = STorsoWpn::eWalk;
	}
	// анимации
	MotionID M_legs;
	MotionID M_torso;
	MotionID M_head;

	//если мы просто стоим на месте
	bool is_standing = false;

	// Legs
	if (mstate_rl & mcLanding) M_legs = ST->landing[0];
	else if (mstate_rl & mcLanding2) M_legs = ST->landing[1];
	else if ((mstate_rl & mcTurn) &&
		!(mstate_rl & mcClimb))
		M_legs = ST->legs_turn;
	else if (mstate_rl & mcFall) M_legs = ST->jump_idle;
	else if (mstate_rl & mcJump) M_legs = ST->jump_begin;
	else if (mstate_rl & mcFwd) M_legs = AS->legs_fwd;
	else if (mstate_rl & mcBack) M_legs = AS->legs_back;
	else if (mstate_rl & mcLStrafe) M_legs = AS->legs_ls;
	else if (mstate_rl & mcRStrafe) M_legs = AS->legs_rs;
	else is_standing = true;
	if (g_player_hud && is_standing && IsFocused() && m_legs_controller.is_active()) {
		is_standing = false;
	}

	if (mstate_rl & mcSprint)
	{
		g_SetSprintAnimation(mstate_rl, M_head, M_torso, M_legs);
		moving_idx = STorsoWpn::eSprint;
	}

	if (this == Level().CurrentViewEntity())
	{
		if (mstate_rl & mcAnyMove)
		{
			if ((mstate_rl & mcSprint) != (mstate_old & mcSprint))
			{
				g_player_hud->OnMovementChanged(mcSprint);
			}
			else if ((mstate_rl & mcCrouch) != (mstate_old & mcCrouch))
			{
				g_player_hud->OnMovementChanged(mcCrouch);
			}
			else if ((mstate_rl & mcAccel) != (mstate_old & mcAccel) && !Actor()->IsZoomAimingMode())
			{
				g_player_hud->OnMovementChanged(mcAccel);
			}
		}

		if (!(mstate_old & mcAnyMove) && (mstate_rl & mcAnyMove) || (mstate_old & mcAnyMove) && !(mstate_rl & mcAnyMove))
			g_player_hud->OnMovementChanged(mcAnyMove);
	};

	//-----------------------------------------------------------------------
	// Torso
	if (mstate_rl & mcClimb)
	{
		if (mstate_rl & mcFwd) M_torso = AS->legs_fwd;
		else if (mstate_rl & mcBack) M_torso = AS->legs_back;
		else if (mstate_rl & mcLStrafe) M_torso = AS->legs_ls;
		else if (mstate_rl & mcRStrafe) M_torso = AS->legs_rs;
	}

	if (!M_torso)
	{
		CInventoryItem* _i = inventory().ActiveItem();
		CHudItem* H = smart_cast<CHudItem*>(_i);

		if (H)
		{
			VERIFY(H->animation_slot() <= _total_anim_slots_);
			// Melee items with a firearm slot (GAMMA axes keep the rifle slot 2)
			// take the knife grip and the knife's swings (owner 2026-10-18: the
			// axe played the rifle's animations).
			const u32 slot = netcoop::pure_client() && smart_cast<CWeaponKnife*>(_i) &&
				H->animation_slot() != 5 ? 5 : H->animation_slot();
			STorsoWpn* TW = &ST->m_torso[slot - 1];
			if (!b_DropActivated && !fis_zero(f_DropPower))
			{
				M_torso = TW->drop;
				if (!M_torso)
				{
					Msg("! drop animation for %s", *(H->object().cName()));
					M_torso = ST->m_torso_idle;
				};
				m_bAnimTorsoPlayed = TRUE;
			}
			else
			{
				if (!m_bAnimTorsoPlayed)
				{
					CWeapon* W = smart_cast<CWeapon*>(_i);
					CPda* P = smart_cast<CPda*>(_i);
					CMissile* M = smart_cast<CMissile*>(_i);
					CArtefact* A = smart_cast<CArtefact*>(_i);

					if (W)
					{
						bool R3 = W->IsTriStateReload();

						if (smart_cast<CWeaponKnife*>(W))
						{
							switch (W->GetState())
							{
							case CWeapon::eIdle: M_torso = TW->moving[moving_idx];
								break;

							case CWeapon::eFire:
								if (is_standing && !drawn_device)
									M_torso = M_legs = M_head = TW->all_attack_0;
								else
									M_torso = TW->attack_zoom;
								break;

							case CWeapon::eFire2:
								if (is_standing && !drawn_device)
									M_torso = M_legs = M_head = TW->all_attack_1;
								else
									M_torso = TW->fire_idle;
								break;

							case CWeapon::eReload: M_torso = TW->reload;
								break;
							case CWeapon::eShowing: M_torso = TW->draw;
								break;
							case CWeapon::eHiding: M_torso = TW->holster;
								break;
							default: M_torso = TW->moving[moving_idx];
								break;
							}
						}
						else
						{
							switch (W->GetState())
							{
							case CWeapon::eIdle: M_torso = W->IsZoomed() ? TW->zoom : (m_bSafemode && moving_idx != STorsoWpn::eSprint) ? TW->safemode : TW->moving[moving_idx];
								break;
							case CWeapon::eFire: M_torso = W->IsZoomed() ? TW->attack_zoom : TW->attack;
								break;
							case CWeapon::eFire2: M_torso = W->IsZoomed() ? TW->attack_zoom : TW->attack;
								break;
							case CWeapon::eReload:
								if (!R3)
								{
									M_torso = TW->reload;
									// Netcoop: another player's reload plays once per
									// reload; then the torso holds the weapon.
									if (netcoop::pure_client() && Remote())
									{
										const u32 serial = W->GetStateSerial();
										if (m_netcoop_reload_done_serial == serial)
											M_torso = TW->moving[moving_idx];
										else if (m_current_torso == TW->reload && m_current_torso_blend &&
											m_current_torso_blend->timeCurrent + Device.fTimeDelta >= m_current_torso_blend->timeTotal)
										{
											m_netcoop_reload_done_serial = serial;
											M_torso = TW->moving[moving_idx];
										}
									}
								}
								else
								{
									CWeapon::EWeaponSubStates sub_st = W->GetReloadState();
									switch (sub_st)
									{
									case CWeapon::eSubstateReloadBegin: M_torso = TW->reload;
										break;
									case CWeapon::eSubstateReloadInProcess: M_torso = TW->reload_1;
										break;
									case CWeapon::eSubstateReloadEnd: M_torso = TW->reload_2;
										break;
									default: M_torso = TW->reload;
										break;
									}
								}
								break;

							case CWeapon::eShowing: M_torso = TW->draw;
								break;
							case CWeapon::eHiding: M_torso = TW->holster;
								break;
							default: M_torso = TW->moving[moving_idx];
								break;
							}
						}
						if (!M_torso)
							M_torso = ST->m_torso[4].moving[moving_idx]; //Alundaio: Fix torso animations for binoc
					}
					else if (M)
					{
						if (is_standing)
						{
							switch (M->GetState())
							{
							case CMissile::eShowing: M_torso = TW->draw;
								break;
							case CMissile::eHiding: M_torso = TW->holster;
								break;
							case CMissile::eIdle: M_torso = TW->moving[moving_idx];
								break;
							case CMissile::eThrowStart: M_torso = M_legs = M_head = TW->all_attack_0;
								break;
							case CMissile::eReady: M_torso = M_legs = M_head = TW->all_attack_1;
								break;
							case CMissile::eThrow: M_torso = M_legs = M_head = TW->all_attack_2;
								break;
							case CMissile::eThrowEnd: M_torso = M_legs = M_head = TW->all_attack_2;
								break;
							default: M_torso = TW->draw;
								break;
							}
						}
						else
						{
							switch (M->GetState())
							{
							case CMissile::eShowing: M_torso = TW->draw;
								break;
							case CMissile::eHiding: M_torso = TW->holster;
								break;
							case CMissile::eIdle: M_torso = TW->moving[moving_idx];
								break;
							case CMissile::eThrowStart: M_torso = TW->attack_zoom;
								break;
							case CMissile::eReady: M_torso = TW->fire_idle;
								break;
							case CMissile::eThrow: M_torso = TW->fire_end;
								break;
							case CMissile::eThrowEnd: M_torso = TW->fire_end;
								break;
							default: M_torso = TW->draw;
								break;
							}
						}
					}
					else if (A)
					{
						switch (A->GetState())
						{
						case CArtefact::eIdle: M_torso = TW->moving[moving_idx];
							break;
						case CArtefact::eShowing: M_torso = TW->draw;
							break;
						case CArtefact::eHiding: M_torso = TW->holster;
							break;
						case CArtefact::eActivating: M_torso = TW->zoom;
							break;
						default: M_torso = TW->moving[moving_idx];
						}
					}
					else if (P)
					{
						switch (P->GetState())
						{
						case CPda::eIdle: M_torso = P->m_bZoomed ? TW->zoom : (moving_idx == STorsoWpn::eSprint ? ST->m_torso[0].moving[moving_idx] : ST->m_torso[4].moving[moving_idx]);
							break;
						case CPda::eShowing: M_torso = TW->draw;
							break;
						case CPda::eHiding: M_torso = TW->holster;
							break;
						default: M_torso = ST->m_torso[4].moving[moving_idx];
							break;
						}
					}
				}
			}
		}
		else if (!m_bAnimTorsoPlayed)
		{
			if (moving_idx == STorsoWpn::eSprint)
				M_torso = ST->m_torso[0].moving[moving_idx];
			else
				M_torso = ST->m_torso[4].moving[moving_idx]; //Alundaio: Fix torso animations for no weapon
		}
	}
	if (!m_bAnimTorsoPlayed)
	{
		const MotionID device_motion = netcoop_device_torso(this, drawn_device, mstate_rl, moving_idx);
		if (device_motion.valid())
			M_torso = device_motion;
	}
	MotionID mid = smart_cast<IKinematicsAnimated*>(Visual())->ID_Cycle("norm_idle_0");

	if (!M_legs)
	{
		if ((mstate_rl & mcCrouch) && !isActorAccelerated(mstate_rl, IsZoomAimingMode())) //!(mstate_rl&mcAccel))
		{
			M_legs = smart_cast<IKinematicsAnimated*>(Visual())->ID_Cycle("cr_idle_1");
		}
		else
			M_legs = ST->legs_idle;
	}
	if (!M_head)
		M_head = ST->m_head_idle;

	if (!M_torso)
	{
		if (m_bAnimTorsoPlayed)
			M_torso = m_current_torso;
		else
			M_torso = ST->m_torso_idle;
	}

	// есть анимация для всего - запустим / иначе запустим анимацию по частям
	if (m_current_torso != M_torso)
	{
		if (m_bAnimTorsoPlayed)
			m_current_torso_blend = smart_cast<IKinematicsAnimated*>(Visual())->PlayCycle(
				M_torso,TRUE, AnimTorsoPlayCallBack, this);
		else
			m_current_torso_blend = smart_cast<IKinematicsAnimated*>(Visual())->PlayCycle(M_torso);

		m_current_torso = M_torso;
	}

	if (m_current_head != M_head)
	{
		if (M_head)
			smart_cast<IKinematicsAnimated*>(Visual())->PlayCycle(M_head);

		m_current_head = M_head;
	}

	if (m_current_legs != M_legs)
	{
		float pos = 0.f;
		VERIFY(!m_current_legs_blend || !fis_zero(m_current_legs_blend->timeTotal));
		if ((mstate_real & mcAnyMove) && (mstate_old & mcAnyMove) && m_current_legs_blend)
			pos = fmod(m_current_legs_blend->timeCurrent, m_current_legs_blend->timeTotal) / m_current_legs_blend->
				timeTotal;


		IKinematicsAnimated* ka = smart_cast<IKinematicsAnimated*>(Visual());
		m_current_legs_blend = PlayMotionByParts(ka, M_legs, TRUE, legs_play_callback, this);
		//		m_current_legs_blend		= smart_cast<IKinematicsAnimated*>(Visual())->PlayCycle(M_legs,TRUE,legs_play_callback,this);


		if ((!(mstate_old & mcAnyMove)) && (mstate_real & mcAnyMove))
		{
			pos = 0.5f; //0.5f*Random.randI(2);
		}
		if (m_current_legs_blend)
			m_current_legs_blend->timeCurrent = m_current_legs_blend->timeTotal * pos;

		m_current_legs = M_legs;

		CStepManager::on_animation_start(M_legs, m_current_legs_blend);
	}


#ifdef DEBUG
	if(bDebug && g_ShowAnimationInfo)
	{
		UI().Font().pFontStat->OutSetI	(0,0);
		UI().Font().pFontStat->OutNext("[%s]",mov_state[moving_idx]);
		IKinematicsAnimated* KA = smart_cast<IKinematicsAnimated*>(Visual());
		if(M_torso)
			UI().Font().pFontStat->OutNext("torso [%s]",KA->LL_MotionDefName_dbg(M_torso).first);
		if(M_head)
			UI().Font().pFontStat->OutNext("head [%s]",KA->LL_MotionDefName_dbg(M_head).first);
		if(M_legs)
			UI().Font().pFontStat->OutNext("legs [%s]",KA->LL_MotionDefName_dbg(M_legs).first);
	}
#endif

#ifdef DEBUG
	if ((Level().CurrentControlEntity() == this) && g_ShowAnimationInfo) {
		string128 buf;
		xr_strcpy(buf,"");
		if (isActorAccelerated(mstate_rl, IsZoomAimingMode()))		xr_strcat(buf,"Accel ");
		if (mstate_rl&mcCrouch)		xr_strcat(buf,"Crouch ");
		if (mstate_rl&mcFwd)		xr_strcat(buf,"Fwd ");
		if (mstate_rl&mcBack)		xr_strcat(buf,"Back ");
		if (mstate_rl&mcLStrafe)	xr_strcat(buf,"LStrafe ");
		if (mstate_rl&mcRStrafe)	xr_strcat(buf,"RStrafe ");
		if (mstate_rl&mcJump)		xr_strcat(buf,"Jump ");
		if (mstate_rl&mcFall)		xr_strcat(buf,"Fall ");
		if (mstate_rl&mcTurn)		xr_strcat(buf,"Turn ");
		if (mstate_rl&mcLanding)	xr_strcat(buf,"Landing ");
		if (mstate_rl&mcLLookout)	xr_strcat(buf,"LLookout ");
		if (mstate_rl&mcRLookout)	xr_strcat(buf,"RLookout ");
		if (m_bJumpKeyPressed)		xr_strcat(buf,"+Jumping ");
		UI().Font().pFontStat->OutNext	("MSTATE:     [%s]",buf);
/*
		switch (m_PhysicMovementControl->Environment())
		{
		case CPHMovementControl::peOnGround:	xr_strcpy(buf,"ground");			break;
		case CPHMovementControl::peInAir:		xr_strcpy(buf,"air");				break;
		case CPHMovementControl::peAtWall:		xr_strcpy(buf,"wall");				break;
		}
		UI().Font().pFontStat->OutNext	(buf);
		UI().Font().pFontStat->OutNext	("Accel     [%3.2f, %3.2f, %3.2f]",VPUSH(NET_SavedAccel));
		UI().Font().pFontStat->OutNext	("V         [%3.2f, %3.2f, %3.2f]",VPUSH(m_PhysicMovementControl->GetVelocity()));
		UI().Font().pFontStat->OutNext	("vertex ID   %d",ai_location().level_vertex_id());
		*/
	};
#endif

	if (!m_current_torso_blend)
		return;

	IKinematicsAnimated* skeleton_animated = smart_cast<IKinematicsAnimated*>(Visual());

	CMotionDef* motion0 = skeleton_animated->LL_GetMotionDef(m_current_torso);
	VERIFY(motion0);
	if (!(motion0->flags & esmSyncPart))
		return;

	if (!m_current_legs_blend)
		return;

	CMotionDef* motion1 = skeleton_animated->LL_GetMotionDef(m_current_legs);
	VERIFY(motion1);
	if (!(motion1->flags & esmSyncPart))
		return;


	m_current_torso_blend->timeCurrent = m_current_legs_blend->timeCurrent / m_current_legs_blend->timeTotal *
		m_current_torso_blend->timeTotal;
}

// ---------------------------------------------------------------------------
// Netcoop RP animations (emotes). The owner's client starts and stops them and
// tells the others (GE_NETCOOP_RP: list index, 0xff = stop); every client plays
// the chain on its own copy of the body, so only the index goes on the wire.
// While one plays, the normal torso and legs animations are paused.
// ---------------------------------------------------------------------------
static void rp_motion_end(CBlend* blend)
{
	if (CActor* actor = static_cast<CActor*>(blend->CallbackParam))
		actor->m_rp_motion_done = true;
}

bool CActor::rp_play_motion(const shared_str& name)
{
	IKinematicsAnimated* k = smart_cast<IKinematicsAnimated*>(Visual());
	if (!k)
		return false;
	const MotionID motion = k->ID_Cycle_Safe(name.c_str());
	if (!motion.valid())
	{
		Msg("~ [Lost Zone] rp: no motion '%s' on %s", name.c_str(), cName().c_str());
		return false;
	}
	CMotionDef* def = k->LL_GetMotionDef(motion);
	if (!def)
		return false;
	m_rp_motion_done = false;
	m_rp_motion_deadline = Device.dwTimeGlobal + 20000;
	k->LL_PlayCycle(def->bone_or_part, motion, TRUE, def->Accrue(), def->Falloff(), _min(def->Speed(), 1.f), TRUE,
	                rp_motion_end, this, 0);
	return true;
}

void CActor::rp_send(u8 index)
{
	NET_Packet P;
	u_EventGen(P, GE_NETCOOP_RP, ID());
	P.w_u8(index);
	u_EventSend(P, net_flags(TRUE, TRUE));
}

bool CActor::rp_start(int index, bool own)
{
	if (index < 0 || index >= int(netcoop::rp_anims().size()) || !g_Alive())
		return false;
	if (m_rp_index == index && !m_rp_stopping)
		return true;
	const netcoop::RpAnim& a = netcoop::rp_anims()[index];
	// A weapon pose needs that slot's item; the owner's client decides, the
	// others show the weapon it took.
	if (own && a.slot && !inventory().ItemFromSlot(a.slot))
	{
		Msg("[Lost Zone] rp: %s needs an item in slot %u", a.name.c_str(), u32(a.slot));
		return false;
	}
	if (m_rp_index >= 0)
		rp_finish();
	m_rp_index = index;
	m_rp_started = Device.dwTimeGlobal;
	Msg("[Lost Zone] rp: %s starts %s on %s", netcoop::rp_anims()[index].name.c_str(), own ? "(own)" : "(remote)", cName().c_str());
	m_rp_phase = 0;
	m_rp_step = 0;
	m_rp_stopping = false;
	m_rp_motion_done = true;
	m_rp_walk_legs.invalidate();
	m_rp_walk_torso.invalidate();
	if (own)
	{
		// Keep the player in first person; gameplay input is locked until stop.
		inventory().Action(kWPN_FIRE, CMD_STOP);
		mstate_wishful &= ~(mcAnyMove | mcJump | mcSprint | mcCrouch | mcLookout);
		m_jump_input_pending = false;
		inventory().Activate(a.slot ? u16(a.slot) : NO_ACTIVE_SLOT);
		cam_Set(eacFirstEye);
		rp_send(u8(index));
		m_rp_resend = Device.dwTimeGlobal + 2000;
	}
	return true;
}

bool CActor::rp_walking() const
{
	const xr_vector<netcoop::RpAnim>& anims = netcoop::rp_anims();
	return m_rp_index >= 0 && m_rp_index < int(anims.size()) && anims[m_rp_index].walk && !m_rp_stopping;
}

// A walking pose (New Way): the legs by the movement, the torso its pose.
void CActor::rp_walk(const netcoop::RpAnim& a, u32 mstate_rl)
{
	IKinematicsAnimated* k = smart_cast<IKinematicsAnimated*>(Visual());
	if (!k)
		return;
	const u32 leg = (mstate_rl & mcFwd) ? 0 : (mstate_rl & mcBack) ? 1 : (mstate_rl & mcLStrafe) ? 2 :
		(mstate_rl & mcRStrafe) ? 3 : 4;
	const MotionID legs = k->ID_Cycle_Safe(a.legs[leg].c_str());
	const MotionID torso = k->ID_Cycle_Safe(a.torso[leg < 4 ? 0 : 1].c_str());
	const u16 legs_part = k->LL_PartID("legs"), torso_part = k->LL_PartID("torso");
	if (legs.valid() && legs != m_rp_walk_legs && legs_part != BI_NONE)
	{
		k->PlayCycle(legs_part, legs, TRUE);
		m_rp_walk_legs = legs;
	}
	if (torso.valid() && torso != m_rp_walk_torso && torso_part != BI_NONE)
	{
		k->PlayCycle(torso_part, torso, TRUE);
		m_rp_walk_torso = torso;
	}
}

void CActor::rp_request_stop(bool own)
{
	if (m_rp_index < 0)
		return;
	if (own && !m_rp_stopping)
		rp_send(0xff);
	m_rp_stopping = true;
	if (m_rp_phase <= 1)
	{
		// Leave now, also from the "in" chain (it waited for the intro clip,
		// up to 20 s, owner 2026-10-09): the "out" chain starts from here.
		m_rp_phase = 2;
		m_rp_step = 0;
		m_rp_motion_done = true;
	}
}

void CActor::rp_finish()
{
	if (m_rp_index < 0)
		return;
	Msg("[Lost Zone] rp: %s finished on %s", netcoop::rp_anims()[m_rp_index].name.c_str(), cName().c_str());
	m_rp_index = -1;
	m_rp_stopping = false;
	m_rp_motion_done = true;
	m_rp_walk_legs.invalidate();
	m_rp_walk_torso.invalidate();
	m_bAnimTorsoPlayed = FALSE;
	m_current_torso.invalidate();
	m_current_legs.invalidate();
	m_current_head.invalidate();
	if (m_rp_camera_switched)
	{
		m_rp_camera_switched = false;
		if (cam_active == eacLookAt)
			cam_Set(eacFirstEye);
	}
}

bool CActor::rp_update(u32 mstate_rl)
{
	if (m_rp_index < 0)
		return false;
	const xr_vector<netcoop::RpAnim>& anims = netcoop::rp_anims();
	if (!g_Alive() || m_rp_index >= int(anims.size()))
	{
		rp_finish();
		return false;
	}
	const bool own = this == Level().CurrentControlEntity();
	if (own && !m_rp_stopping)
	{
		if (Device.dwTimeGlobal >= m_rp_resend)
		{
			rp_send(u8(m_rp_index));
			m_rp_resend = Device.dwTimeGlobal + 2000;
		}
	}
	const netcoop::RpAnim& a = anims[m_rp_index];
	if (a.walk)
	{
		// Leaving a walking pose has no "out" chain.
		if (m_rp_stopping)
		{
			rp_finish();
			return false;
		}
		rp_walk(a, mstate_rl);
		return true;
	}
	if (!m_rp_motion_done && Device.dwTimeGlobal < m_rp_motion_deadline)
		return true;
	for (int guard = 0; guard < 64; ++guard)
	{
		const xr_vector<shared_str>& chain = m_rp_phase == 0 ? a.in : m_rp_phase == 1 ? a.mid : a.out;
		if (m_rp_step < chain.size())
		{
			if (rp_play_motion(chain[m_rp_step++]))
				return true;
			continue;
		}
		if (m_rp_phase == 0)
		{
			m_rp_phase = m_rp_stopping ? 2 : 1;
			m_rp_step = 0;
			continue;
		}
		if (m_rp_phase == 1)
		{
			if (a.loop && !m_rp_stopping && !a.mid.empty())
			{
				m_rp_step = 0;
				if (guard > 0 && m_rp_motion_done)
					break; // no mid motion resolves on this body
				continue;
			}
			if (a.once)
			{
				m_rp_phase = 2;
				m_rp_step = 0;
				continue;
			}
			if (!a.loop && !m_rp_stopping)
			{
				// Hold the terminal pose until the wheel's stop button is used.
				return true;
			}
			m_rp_phase = 2;
			m_rp_step = 0;
			continue;
		}
		break;
	}
	rp_finish();
	return false;
}
