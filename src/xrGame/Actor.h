#pragma once

#include "../xrEngine/feel_touch.h"
#include "../xrEngine/feel_sound.h"
#include "../xrEngine/iinputreceiver.h"
#include "../Include/xrRender/KinematicsAnimated.h"
#include "actor_flags.h"
#include "actor_defs.h"
#include "fire_disp_controller.h"
#include "entity_alive.h"
#include "PHMovementControl.h"
#include "../xrphysics/PhysicsShell.h"
#include "InventoryOwner.h"
#include "../xrEngine/StatGraph.h"
#include "PhraseDialogManager.h"
#include "ui_defs.h"
#include "HUDManager.h"

#include "step_manager.h"
#include "script_export_space.h"

#include "player_hud_legs.h"
#include "xrmessages.h"

#ifdef STATIONARYMGUN_NEW
#include "WeaponStatMgun.h"
#endif

using namespace ACTOR_DEFS;

class CInfoPortion;
struct GAME_NEWS_DATA;
namespace netcoop { struct RpAnim; }
class CActorCondition;
class CCustomOutfit;
class CGameTaskRegistryWrapper;
class CGameNewsRegistryWrapper;
class CCharacterPhysicsSupport;
class CActorCameraManager;
// refs
class ENGINE_API CCameraBase;
class ENGINE_API CBoneInstance;
class ENGINE_API CBlend;
class CWeaponList;
class CEffectorBobbing;
class CHolderCustom;
class CUsableScriptObject;

struct SShootingEffector;
struct SSleepEffector;
class CSleepEffectorPP;
class CInventoryBox;

class CHudItem;
class CArtefact;

struct SActorMotions;
struct SActorVehicleAnims;
class CActorCondition;
class SndShockEffector;
class CActorFollowerMngr;

struct CameraRecoil;
class CCameraShotEffector;
class CActorInputHandler;

class CActorMemory;
class CActorStatisticMgr;

class CLocationManager;

class CNightVisionEffector;
class CFPCamEffector;

class CActor :
	public CEntityAlive,
	public IInputReceiver,
	public Feel::Touch,
	public CInventoryOwner,
	public CPhraseDialogManager,
	public CStepManager,
	public Feel::Sound
#ifdef DEBUG
    ,public pureRender
#endif
{
	friend class CActorCondition;
private:
	typedef CEntityAlive inherited;
public:
	CActor();
	virtual ~CActor();

// demonized: First Person Death
public:
	CFPCamEffector* m_FPCam;

public:
	void initFPCam();
	void removeFPCam();

public:
	virtual BOOL AlwaysTheCrow() { return TRUE; }

	virtual CAttachmentOwner* cast_attachment_owner() { return this; }
	virtual CInventoryOwner* cast_inventory_owner() { return this; }
	virtual CActor* cast_actor() { return this; }
	virtual CGameObject* cast_game_object() { return this; }
	virtual IInputReceiver* cast_input_receiver() { return this; }
	virtual CCharacterPhysicsSupport* character_physics_support() { return m_pPhysics_support; }
	virtual CCharacterPhysicsSupport* character_physics_support() const { return m_pPhysics_support; }
	virtual CPHDestroyable* ph_destroyable();
	CHolderCustom* Holder() { return m_holder; }

public:
    Fmatrix XFORMShadow;
    player_legs_controller m_legs_controller;

public:

	virtual void Load(LPCSTR section);
	virtual void RenderCamAttached();

	virtual void shedule_Update(u32 T);
	virtual void UpdateCL();

	virtual void OnEvent(NET_Packet& P, u16 type);

	// Render
	virtual void renderable_Render();
	virtual BOOL renderable_ShadowGenerate();
	virtual bool AllowActorShadow();
	virtual void feel_sound_new(CObject* who, int type, CSound_UserDataPtr user_data, const Fvector& Position,
	                            float power);
	virtual Feel::Sound* dcast_FeelSound() { return this; }
	float m_snd_noise;
#ifdef DEBUG
    virtual void						OnRender			();

#endif


public:
	virtual bool OnReceiveInfo(shared_str info_id) const;
	virtual void OnDisableInfo(shared_str info_id) const;

	virtual void NewPdaContact(CInventoryOwner*);
	virtual void LostPdaContact(CInventoryOwner*);

#ifdef DEBUG
    void			 DumpTasks();
#endif

	struct SDefNewsMsg
	{
		GAME_NEWS_DATA* news_data;
		u32 time;
		bool operator <(const SDefNewsMsg& other) const { return time > other.time; }
	};

	xr_vector<SDefNewsMsg> m_defferedMessages;
	void UpdateDefferedMessages();
public:
	void AddGameNews_deffered(GAME_NEWS_DATA& news_data, u32 delay);
	virtual void AddGameNews(GAME_NEWS_DATA& news_data);
protected:
	CActorStatisticMgr* m_statistic_manager;
public:
	virtual void StartTalk(CInventoryOwner* talk_partner);
	void RunTalkDialog(CInventoryOwner* talk_partner, bool disable_break);
	CActorStatisticMgr& StatisticMgr() { return *m_statistic_manager; }
	CGameNewsRegistryWrapper* game_news_registry;
	CCharacterPhysicsSupport* m_pPhysics_support;

	virtual LPCSTR Name() const { return CInventoryOwner::Name(); }

public:
	//PhraseDialogManager
	virtual void ReceivePhrase(DIALOG_SHARED_PTR& phrase_dialog);
	virtual void UpdateAvailableDialogs(CPhraseDialogManager* partner);
	virtual void TryToTalk();
	bool OnDialogSoundHandlerStart(CInventoryOwner* inv_owner, LPCSTR phrase);
	bool OnDialogSoundHandlerStop(CInventoryOwner* inv_owner);


	virtual void reinit();
	virtual void reload(LPCSTR section);
	virtual bool use_bolts() const;

	virtual void OnItemTake(CInventoryItem* inventory_item);

	virtual void OnItemRuck(CInventoryItem* inventory_item, const SInvItemPlace& previous_place);
	virtual void OnItemBelt(CInventoryItem* inventory_item, const SInvItemPlace& previous_place);

	virtual void OnItemDrop(CInventoryItem* inventory_item, bool just_before_destroy);
	virtual void OnItemDropUpdate();

	virtual void OnPlayHeadShotParticle(NET_Packet P);

	virtual void set_actor_box_y_offset(u32 box_num, float offset);
	virtual void Die(CObject* who);
	virtual void Hit(SHit* pHDS);
	virtual void PHHit(SHit& H);
	virtual void HitSignal(float P, Fvector& vLocalDir, CObject* who, s16 element);
	void HitSector(CObject* who, CObject* weapon);
	void HitMark(float P, Fvector dir, CObject* who, s16 element, Fvector position_in_bone_space, float impulse,
	             ALife::EHitType hit_type);

    void Feel_Grenade_Update( float rad );

	virtual float GetMass();
	virtual float Radius() const;
	virtual void g_PerformDrop();

	virtual bool use_default_throw_force();
	virtual float missile_throw_force();

	virtual bool unlimited_ammo();

public:

	//свойства артефактов
	virtual void UpdateArtefactsOnBeltAndOutfit();
	float HitArtefactsOnBelt(float hit_power, ALife::EHitType hit_type);
	float GetProtection_ArtefactsOnBelt(ALife::EHitType hit_type);

protected:
	//звук тяжелого дыхания
	ref_sound m_HeavyBreathSnd;
	ref_sound m_BloodSnd;
	ref_sound m_DangerSnd;

protected:
	// Death
	float m_hit_slowmo;
	float m_hit_probability;
	s8 m_block_sprint_counter;

	// media
	SndShockEffector* m_sndShockEffector;
	xr_vector<ref_sound> sndHit[ALife::eHitTypeMax];
	ref_sound sndDie[SND_DIE_COUNT];


	float m_fLandingTime;
	float m_fJumpTime;
	float m_fFallTime;
	float m_fCamHeightFactor;

	// Dropping
	BOOL b_DropActivated;
	float f_DropPower;

	//random seed для Zoom mode
	s32 m_ZoomRndSeed;
	//random seed для Weapon Effector Shot
	s32 m_ShotRndSeed;

	bool m_bOutBorder;
	//сохраняет счетчик объектов в feel_touch, для которых необходимо обновлять размер колижена с актером
	u32 m_feel_touch_characters;
private:
	void SwitchOutBorder(bool new_border_state);
public:
	bool m_bAllowDeathRemove;

	void SetZoomRndSeed(s32 Seed = 0);
	s32 GetZoomRndSeed() { return m_ZoomRndSeed; };
	void SetShotRndSeed(s32 Seed = 0);
	s32 GetShotRndSeed() { return m_ShotRndSeed; };

public:
#ifdef HOLDERCUSTOM_NEW
	void detach_Vehicle(bool bForce);
	void steer_Vehicle(float angle);
	bool attach_Vehicle(CHolderCustom *object, bool bForce);
#else
	void detach_Vehicle();
	void steer_Vehicle(float angle);
	void attach_Vehicle(CHolderCustom* vehicle);
#endif
	bool use_HolderEx(CHolderCustom* object, bool bForce);

	virtual bool can_attach(const CInventoryItem* inventory_item) const;
protected:
	CHolderCustom* m_holder;
	u16 m_holderID;
	bool use_Holder(CHolderCustom* holder);
	void ActorUse();

protected:
	BOOL m_bAnimTorsoPlayed;
	u32 m_netcoop_consumption_until = 0;
	// New Way's third-person item use (owner 2026-10-24): the item in the hand
	// while the consumption motion plays (mod_system_zzzz_lz_third_person.ltx).
	IRenderVisual* m_netcoop_tp_item = nullptr;
	u16 m_netcoop_tp_bone = BI_NONE;
	Fmatrix m_netcoop_tp_offset;
	// New Way's per-frame track instead of the offset (cigarettes: the pack,
	// the cigarette and the lighter each in a hand or hidden, frame by frame).
	struct NetcoopTpTrack;
	const NetcoopTpTrack* m_netcoop_tp_track = nullptr;
	xr_vector<u16> m_netcoop_tp_track_bones; // the item's bone of each track bone
	u16 m_netcoop_tp_hands[2] = {BI_NONE, BI_NONE}; // right, left
	static const NetcoopTpTrack* netcoop_tp_track_load(LPCSTR file);
	void netcoop_tp_item_release();
	void netcoop_tp_item_render();
	LPCSTR netcoop_tp_motion(LPCSTR item);
	void netcoop_tp_item_attach(LPCSTR item);
	static void netcoop_consumption_end(CBlend* blend);
	static void AnimTorsoPlayCallBack(CBlend* B);

	// Rotation
	SRotation r_torso;
	float r_torso_tgt_roll;
	//положение торса без воздействия эффекта отдачи оружия
	SRotation unaffected_r_torso;

	//ориентация модели
	float r_model_yaw_dest;
	float r_model_yaw; // orientation of model
	float r_model_yaw_delta; // effect on multiple "strafe"+"something"


public:
	SActorMotions* m_anims;
#ifdef ENABLE_CAR
	SActorVehicleAnims* m_vehicle_anims;
#endif

	CBlend* m_current_legs_blend;
	CBlend* m_current_torso_blend;
	CBlend* m_current_jump_blend;
	MotionID m_current_legs;
	MotionID m_current_torso;
	MotionID m_current_head;
	void netcoop_play_consumption(u8 kind, LPCSTR section);
	void netcoop_expire_consumption();

	// callback на анимации модели актера
	void SetCallbacks();
	void ResetCallbacks();
	static void _BCL Spin0Callback(CBoneInstance*);
	static void _BCL Spin1Callback(CBoneInstance*);
	static void _BCL ShoulderCallback(CBoneInstance*);
	static void _BCL HeadCallback(CBoneInstance*);
	static void _BCL VehicleHeadCallback(CBoneInstance*);

	virtual const SRotation Orientation() const { return r_torso; };
	SRotation& Orientation() { return r_torso; };

	void g_SetAnimation(u32 mstate_rl);
	void g_SetSprintAnimation(u32 mstate_rl, MotionID& head, MotionID& torso, MotionID& legs);
public:
	virtual void OnHUDDraw(CCustomHUD* hud);
	BOOL HUDview() const;

	//visiblity
	virtual float ffGetFov() const { return 90.f; }
	virtual float ffGetRange() const { return 500.f; }


public:
	CActorCameraManager& Cameras()
	{
		VERIFY(m_pActorEffector);
		return *m_pActorEffector;
	}

	IC CCameraBase* cam_Active() { return cameras[cam_active]; }
	IC CCameraBase* cam_FirstEye() { return cameras[eacFirstEye]; }
	//Swartz: actor shadow
	IC EActorCameras active_cam() { return cam_active; } //KD: need to know which cam active outside actor methods
	virtual void cam_Set(EActorCameras style); //Alundaio: made public
	//-Swartz

	// Rezy - Freelook
	u8 cam_freelook;
	float freelook_cam_control;
	float old_torso_yaw;

protected:
	//virtual	void			cam_Set					(EActorCameras style);
	void cam_Update(float dt, float fFOV);
	void cam_Lookout(const Fmatrix& xform, float camera_height);
	void camUpdateLadder(float dt);
	void cam_SetLadder();
	void cam_UnsetLadder();
	void camUpdateFreelook(float dt);
	void cam_SetFreelook();
	void cam_UnsetFreelook();
	bool CanUseFreelook();
	float currentFOV();

	// Cameras
	CCameraBase* cameras[eacMaxCam];
	EActorCameras cam_active;
	float fPrevCamPos;
	float current_ik_cam_shift;
	Fvector vPrevCamDir;
	float fCurAVelocity;
	CEffectorBobbing* pCamBobbing;


	//менеджер эффекторов, есть у каждого актрера
	CActorCameraManager* m_pActorEffector;
	static float f_Ladder_cam_limit;
public: //--#SM+#--
	float fFPCamYawMagnitude;
	float fFPCamPitchMagnitude;
public:
	virtual void feel_touch_new(CObject* O);
	virtual void feel_touch_delete(CObject* O);
	virtual bool feel_touch_contact(CObject* O);
	virtual bool feel_touch_on_contact(CObject* O);

	CGameObject* ObjectWeLookingAt() { return m_pObjectWeLookingAt; }
	CInventoryOwner* PersonWeLookingAt() { return m_pPersonWeLookingAt; }
	LPCSTR GetDefaultActionForObject() { return *m_sDefaultObjAction; }
protected:
	CUsableScriptObject* m_pUsableObject;
	// Person we're looking at
	CInventoryOwner* m_pPersonWeLookingAt;
	CHolderCustom* m_pVehicleWeLookingAt;
	CGameObject* m_pObjectWeLookingAt;
	CInventoryBox* m_pInvBoxWeLookingAt;

	// Tip for action for object we're looking at
	shared_str m_sDefaultObjAction;
	shared_str m_sCharacterUseAction;
	shared_str m_sDeadCharacterUseAction;
	shared_str m_sDeadCharacterUseOrDragAction;
	shared_str m_sDeadCharacterDontUseAction;
	shared_str m_sCarCharacterUseAction;
	shared_str m_sInventoryItemUseAction;
	shared_str m_sInventoryBoxUseAction;

	bool m_bPickupMode;

    float					m_fFeelGrenadeRadius;
    float					m_fFeelGrenadeTime;
	float m_fPickupInfoRadius;
protected:
	struct pickup_result_t
	{
		bool allow_pickup;
		bool callback_handled;
	};
	pickup_result_t PickupModeUpdate();
	void PickupInfoDraw(CObject* object);
	void PickupModeUpdate_COD(pickup_result_t pickup_state);

public:
	void DrawPickupItems();
	bool m_bDelayDrawPickupItems;

	//////////////////////////////////////////////////////////////////////////
	// Motions (передвижения актрера)
	//////////////////////////////////////////////////////////////////////////
public:
	void g_cl_CheckControls(u32 mstate_wf, Fvector& vControlAccel, float& Jump, float dt);
	void g_cl_ValidateMState(float dt, u32 mstate_wf);
	void g_cl_Orientate(u32 mstate_rl, float dt);
	void g_sv_Orientate(u32 mstate_rl, float dt);
	void g_Orientate(u32 mstate_rl, float dt);
	bool g_LadderOrient();
	//	void					UpdateMotionIcon		(u32 mstate_rl);

	bool CanAccelerate();
	bool CanJump();
	bool CanMove();
	float CameraHeight();

	// Alex ADD: for smooth crouch fix
	float CurrentHeight;

	bool CanSprint();
	bool CanRun();
	void StopAnyMove();
	void StopSprint() { mstate_wishful &= ~mcSprint; }

	bool AnyAction() { return (mstate_real & mcAnyAction) != 0; };
	bool AnyMove() { return (mstate_real & mcAnyMove) != 0; };

	bool is_jump();
	u32 MovingState() const { return mstate_real; }
protected:
	u32 mstate_wishful;
	u32 mstate_old;
	u32 mstate_real;

	BOOL m_bJumpKeyPressed;

public:
	float m_fWalkAccel;
	float m_fJumpSpeed;
	float m_fRunFactor;
	float m_fRunBackFactor;
	float m_fWalkBackFactor;
	float m_fCrouchFactor;
	float m_fClimbFactor;
	float m_fSprintFactor;

	float m_fWalk_StrafeFactor;
	float m_fRun_StrafeFactor;
	float m_fSprint_StrafeFactor;

	// demonized: lookout modifier
	float m_fLookoutFactor = 1;

    // verdatim: damage stagger time factor
    float DamageStaggerTimeFactor = 1;

public:
	Fvector GetMovementSpeed() { return NET_SavedAccel; };
	//////////////////////////////////////////////////////////////////////////
	// User input/output
	//////////////////////////////////////////////////////////////////////////
public:
	virtual void IR_OnMouseMove(int x, int y);
	virtual void IR_OnKeyboardPress(int dik);
	virtual void IR_OnKeyboardRelease(int dik);
	virtual void IR_OnKeyboardHold(int dik);
	virtual void IR_OnMouseWheel(int direction);
	virtual float GetLookFactor();

public:
	SPickParam& GetPick();

	virtual void g_WeaponBones(int& L, int& R1, int& R2);
	virtual void g_fireParams(const CHudItem* pHudItem, Fvector& P, Fvector& D);
	virtual bool g_stateFire() { return true; }

	virtual BOOL g_State(SEntityState& state) const;
	virtual float GetWeaponAccuracy() const;
	float GetFireDispertion() const { return m_fdisp_controller.GetCurrentDispertion(); }
	bool IsZoomAimingMode() const { return m_bZoomAimingMode; }
	virtual float MaxCarryWeight() const;
	float MaxWalkWeight() const;
	float get_additional_weight() const;

#ifdef STATIONARYMGUN_NEW
	float GetWeaponAccuracyStm();
#endif

protected:
	CFireDispertionController m_fdisp_controller;
	//если актер целится в прицел
	void SetZoomAimingMode(bool val) { m_bZoomAimingMode = val; }
	bool m_bZoomAimingMode;

	//настройки аккуратности стрельбы
	//базовая дисперсия (когда игрок стоит на месте)
	float m_fDispBase;
	float m_fDispAim;
	//коэффициенты на сколько процентов увеличится базовая дисперсия
	//учитывает скорость актера
	float m_fDispVelFactor;
	//если актер бежит
	float m_fDispAccelFactor;
	//если актер сидит
	float m_fDispCrouchFactor;
	//crouch+no acceleration
	float m_fDispCrouchNoAccelFactor;
	Fvector m_vMissileOffset;
public:
	// Получение, и запись смещения для гранат
	Fvector GetMissileOffset() const;
	void SetMissileOffset(const Fvector& vNewOffset);

	int m_head;
protected:
	//косточки используемые при стрельбе
	int m_r_hand;
	int m_l_finger1;
	int m_r_finger2;
	int m_eye_left;
	int m_eye_right;

	int m_l_clavicle;
	int m_r_clavicle;
	int m_spine2;
	int m_spine1;
	int m_spine;
	int m_neck;


	//////////////////////////////////////////////////////////////////////////
	// Network
	//////////////////////////////////////////////////////////////////////////
	void ConvState(u32 mstate_rl, string128* buf);
public:
	virtual BOOL net_Spawn(CSE_Abstract* DC);
	public:
	virtual void net_Export(NET_Packet& P); // export to server
	void net_ExportInput(NET_Packet& P, const ActorInputCommand& cmd);
	void net_ImportInputAck(NET_Packet& P);
	// Netcoop server: take a player's position and presentation (facing,
	// look, movement state) from the owning client's update.
	void netcoop_follow_owner(NET_Packet& P);
	void netcoop_export_weapon_slots(NET_Packet& P);
	void netcoop_import_weapon_slots(NET_Packet& P);
	// Owner's real-time clock of the last accepted update, and its offset to
	// server time (lower envelope of receive time - owner time).
	u32 m_netcoop_owner_time = 0;
	// Server time when the newest owner update arrived: the time stamp of
	// this player's snapshots (the owner-clock mapping jumped, s102).
	u32 m_netcoop_owner_received = 0;
	// Server: metres the owner may still move (refilled at 12 m/s).
	float m_netcoop_move_budget = 13.f;
	u32 m_netcoop_move_budget_time = 0;
	// The owner's active slot from its updates (what other players see in
	// its hands); 0xff until the first update.
	u8 m_netcoop_owner_slot = 0xff;
	u16 m_netcoop_owner_item = 0xffff;
	// Server: the velocity the owner reports. The copy is placed at the
	// owner's positions, so its capsule's own velocity is not the player's.
	Fvector m_netcoop_owner_velocity{};
	const Fvector& netcoop_owner_velocity() const { return m_netcoop_owner_velocity; }
	float netcoop_model_yaw() const { return r_model_yaw; }

	// Netcoop RP animation (emote): index into netcoop::rp_anims(), -1 none.
	// Phase 0 plays "in" once, 1 repeats "mid" while looping, 2 plays "out".
	int m_rp_index = -1;
	// Owner 2026-10-24: a player looks from the second or third person only
	// during an RP animation; an administrator always.
	bool netcoop_outside_view_allowed() const;
	u8 m_rp_phase = 0;
	u8 m_rp_step = 0;
	bool m_rp_stopping = false;
	bool m_rp_motion_done = true;
	u32 m_rp_motion_deadline = 0;
	u32 m_rp_resend = 0;
	u32 m_rp_started = 0;
	bool m_rp_camera_switched = false;
	// own: this client's player (sends it and moves its camera)
	bool rp_start(int index, bool own);
	void rp_request_stop(bool own);
	bool rp_update(u32 mstate_rl);
	// a walking pose plays (the movement keys work, the body turns with the view)
	bool rp_walking() const;
	MotionID m_rp_walk_legs, m_rp_walk_torso;
	void rp_walk(const netcoop::RpAnim& a, u32 mstate_rl);
	void rp_finish();
	bool rp_play_motion(const shared_str& name);
	void rp_send(u8 index);
	void rp_attach_item(const netcoop::RpAnim& a);

	// Netcoop vehicle seat (netcoop_vehicles.inc, doc 100): on the server, the
	// own client and every other client the seated player is placed at the
	// car's pose times the seat; no character capsule, no own movement.
	u16 m_netcoop_seat_car = 0xffff;
	u8 m_netcoop_seat = 0;
	bool m_netcoop_seat_driver = false;
	Fmatrix m_netcoop_seat_local; // seat root in the car's space
	Fvector m_netcoop_seat_eye; // eye in the car's space
	Fvector m_netcoop_seat_eye_world;
	float m_netcoop_seat_car_yaw = 0.f;
	bool m_netcoop_seat_yaw_valid = false;
	bool m_netcoop_seat_character = false; // had a character capsule before sitting down
	MotionID m_netcoop_seat_motion;
	// The driver is moved (in the car's space) until the hands of the steering
	// pose meet the model's steering wheel bone; measured once per sitting down.
	Fvector m_netcoop_driver_fit;
	u32 m_netcoop_driver_fit_at = 0; // 0: measured; else the time to measure
	bool netcoop_seated() const { return m_netcoop_seat_car != 0xffff; }
	void netcoop_seat_enter(u16 car, u8 seat, bool driver, const Fmatrix& local, const Fvector& eye);
	void netcoop_seat_leave(const Fvector& exit);
	void netcoop_seat_place();
	bool netcoop_seat_animation();
	// Offset = the least delay seen in the current and the previous second:
	// the first updates after a join arrive seconds late, and a minimum over
	// all time made the player's snapshot times jump back by those seconds.
	double m_netcoop_owner_offset = 0.0;
	double m_netcoop_owner_offset_now = 0.0;
	double m_netcoop_owner_offset_prev = 0.0;
	u32 m_netcoop_owner_offset_time = 0;
	bool m_netcoop_owner_offset_valid = false;
	bool m_netcoop_owner_offset_prev_valid = false;
	// Netcoop client: another player, shown from the server's snapshots
	// (position, facing, look, movement state) interpolated each frame.
	void netcoop_update_remote();
	// Prediction mode: the shown position is the prediction plus an error
	// that fades out, so a new snapshot never makes the player jump.
	Fvector m_netcoop_shown_pos;
	Fvector m_netcoop_shown_error;
	u32 m_netcoop_shown_stamp = 0;
	bool m_netcoop_shown_valid = false;
	// Another player's reload: the torso animation played for this state
	// entry of the weapon (it looped the start while the reload lasted).
	u32 m_netcoop_reload_done_serial = 0;
	float m_netcoop_shown_model_yaw = 0.f;
	SRotation m_netcoop_shown_torso;
	
	u32 m_next_input_sequence = 1;
	bool m_jump_input_pending = false;
	struct ClientPredictionFrame {
		u32 associated_sequence;
		float dt;
		u16 mstate;
		Fvector accel;
		float jump;
		Fvector position; // predicted position after this frame's physics
	};
	xr_deque<ClientPredictionFrame> m_client_prediction_history;
	xr_deque<ActorInputCommand> m_client_pending_inputs;
	bool m_bReplayMode = false;
	float m_prediction_error = 0.0f;
	
	void ReplayPendingInputs();
	void ResetPredictionState();
	u32 m_last_applied_server_ack = 0;
	bool ServerProcessInputs(float server_dt);
	virtual void net_Import(NET_Packet& P); // import from server
	virtual void net_Destroy();
	virtual BOOL net_Relevant(); //	{ return getSVU() | getLocal(); };		// relevant for export to server
	virtual void net_Relcase(CObject* O); //
	virtual void xr_stdcall on_requested_spawn(CObject* object);
	//object serialization
	virtual void save(NET_Packet& output_packet);
	virtual void load(IReader& input_packet);
	virtual void net_Save(NET_Packet& P);
	virtual BOOL net_SaveRelevant();
protected:
	xr_deque<net_update> NET;
	Fvector NET_SavedAccel;
	net_update NET_Last;
	BOOL NET_WasInterpolating; // previous update was by interpolation or by extrapolation
	u32 gamma_net_trace_time;
	u32 NET_Time; // server time of last update

	//---------------------------------------------
	void net_Import_Base(NET_Packet& P);
	void net_Import_Physic(NET_Packet& P);
	void net_Import_Base_proceed();
	void net_Import_Physic_proceed();
	//---------------------------------------------


	////////////////////////////////////////////////////////////////////////////
	virtual bool can_validate_position_on_spawn() { return false; }
	///////////////////////////////////////////////////////
	// апдайт с данными физики
	xr_deque<net_update_A> NET_A;

	//---------------------------------------------
	//	bool					m_bHasUpdate;
	/// spline coeff /////////////////////
	float SCoeff[3][4]; //коэффициэнты для сплайна Бизье
	float HCoeff[3][4]; //коэффициэнты для сплайна Эрмита
	Fvector IPosS, IPosH, IPosL; //положение актера после интерполяции Бизье, Эрмита, линейной

#ifdef DEBUG
    DEF_DEQUE		(VIS_POSITION, Fvector);

    VIS_POSITION	LastPosS;
    VIS_POSITION	LastPosH;
    VIS_POSITION	LastPosL;
#endif


	SPHNetState LastState;
	SPHNetState RecalculatedState;
	SPHNetState PredictedState;

	InterpData IStart;
	InterpData IRec;
	InterpData IEnd;

	bool m_bInInterpolation;
	bool m_bInterpolate;
	u32 m_dwIStartTime;
	u32 m_dwIEndTime;
	u32 m_dwILastUpdateTime;

	//---------------------------------------------
	DEF_DEQUE(PH_STATES, SPHNetState);
	PH_STATES m_States;
	u16 m_u16NumBones;
	//---------------------------------------------
	void CalculateInterpolationParams();
	//---------------------------------------------
	virtual void make_Interpolation();
#ifdef DEBUG
    //---------------------------------------------
    virtual void			OnRender_Network();
    //---------------------------------------------
#endif

	// Igor	ref_geom 				hFriendlyIndicator;
	//////////////////////////////////////////////////////////////////////////
	// Actor physics
	//////////////////////////////////////////////////////////////////////////
public:
	void g_Physics(Fvector& accel, float jump, float dt);
	virtual void ForceTransform(const Fmatrix& m);
	void SetPhPosition(const Fmatrix& pos);
	virtual void PH_B_CrPr(); // actions & operations before physic correction-prediction steps
	virtual void PH_I_CrPr(); // actions & operations after correction before prediction steps
	virtual void PH_A_CrPr(); // actions & operations after phisic correction-prediction steps
	//	virtual void			UpdatePosStack	( u32 Time0, u32 Time1 );
	virtual void MoveActor(Fvector NewPos, Fvector NewDir);

	virtual void SpawnAmmoForWeapon(CInventoryItem* pIItem);
	virtual void RemoveAmmoForWeapon(CInventoryItem* pIItem);
	virtual void spawn_supplies();

	virtual bool human_being() const
	{
		return (true);
	}

	virtual shared_str GetDefaultVisualOutfit() const { return m_DefaultVisualOutfit; };
	virtual void SetDefaultVisualOutfit(shared_str DefaultOutfit) { m_DefaultVisualOutfit = DefaultOutfit; };
	virtual void UpdateAnimation() { g_SetAnimation(mstate_real); };

	virtual void ChangeVisual(shared_str NewVisual);
	virtual void OnChangeVisual();

	virtual void RenderIndicator(Fvector dpos, float r1, float r2, const ui_shader& IndShader);
	virtual void RenderText(LPCSTR Text, Fvector dpos, float* pdup, u32 color);

	//////////////////////////////////////////////////////////////////////////
	// Controlled Routines
	//////////////////////////////////////////////////////////////////////////

	void set_input_external_handler(CActorInputHandler* handler);
	bool input_external_handler_installed() const { return (m_input_external_handler != 0); }

	IC void lock_accel_for(u32 time) { m_time_lock_accel = Device.dwTimeGlobal + time; }

private:
	CActorInputHandler* m_input_external_handler;
	u32 m_time_lock_accel;

	/////////////////////////////////////////
	// DEBUG INFO
protected:
	CStatGraph* pStatGraph;

	shared_str m_DefaultVisualOutfit;

	LPCSTR invincibility_fire_shield_3rd;
	LPCSTR invincibility_fire_shield_1st;
	shared_str m_sHeadShotParticle;
	u32 last_hit_frame;
#ifdef DEBUG
        friend class CLevelGraph;
#endif
public:
	void SetWeaponHideState(u16 State, bool bSet);
private: //IPhysicsShellHolder

	virtual void _BCL HideAllWeapons(bool v) { SetWeaponHideState(INV_STATE_BLOCK_ALL, v); }

public:
	void SetCantRunState(bool bSet);
private:
	CActorCondition* m_entity_condition;

protected:
	virtual CEntityConditionSimple* create_entity_condition(CEntityConditionSimple* ec);

public:
	IC CActorCondition& conditions() const;
	virtual DLL_Pure* _construct();
	virtual bool natural_weapon() const { return false; }
	virtual bool natural_detector() const { return false; }
	virtual bool use_center_to_aim() const;
protected:
	u16 m_iLastHitterID;
	u16 m_iLastHittingWeaponID;
	s16 m_s16LastHittedElement;
	Fvector m_vLastHitDir;
	Fvector m_vLastHitPos;
	float m_fLastHealth;
	bool m_bWasHitted;
	bool m_bWasBackStabbed;

	virtual bool Check_for_BackStab_Bone(u16 element);
public:
	virtual void SetHitInfo(CObject* who, CObject* weapon, s16 element, Fvector Pos, Fvector Dir);

	virtual bool InventoryAllowSprint();
	virtual void OnNextWeaponSlot();
	virtual void OnPrevWeaponSlot();
	void SwitchNightVision();
	void SwitchTorch();
#ifdef DEBUG
            void				NoClipFly						(int cmd);
#endif //DEBUG

public:

	virtual void on_weapon_shot_start(CWeapon* weapon);
	virtual void on_weapon_shot_update();
	virtual void on_weapon_shot_stop();
	virtual void on_weapon_shot_remove(CWeapon* weapon);
	virtual void on_weapon_hide(CWeapon* weapon);
	Fvector weapon_recoil_delta_angle();
	Fvector weapon_recoil_last_delta();
protected:
	virtual void update_camera(CCameraShotEffector* effector);
	//step manager
	virtual bool is_on_ground();

private:
	CActorMemory* m_memory;

public:
	IC CActorMemory& memory() const
	{
		VERIFY(m_memory);
		return (*m_memory);
	};

	void OnDifficultyChanged();

	IC float HitProbability() { return m_hit_probability; }
	virtual CVisualMemoryManager* visual_memory() const;

	virtual void On_B_NotCurrentEntity();

private:
	collide::rq_results RQR;
	BOOL CanPickItem(const CFrustum& frustum, const Fvector& from, CObject* item);
	xr_vector<ISpatial*> ISpatialResult;

private:
	CLocationManager* m_location_manager;

public:
	IC const CLocationManager& locations() const
	{
		VERIFY(m_location_manager);
		return (*m_location_manager);
	}

private:
	ALife::_OBJECT_ID m_holder_id;

public:
	virtual bool register_schedule() const { return false; }
	virtual bool is_ai_obstacle() const;

	float GetRestoreSpeed(ALife::EConditionRestoreType const& type);

public:
	virtual void On_SetEntity();

	virtual void On_LostEntity()
	{
	};

	void DisableHitMarks(bool disable) { m_disabled_hitmarks = disable; };
	bool DisableHitMarks() { return m_disabled_hitmarks; };

	void set_inventory_disabled(bool is_disabled) { m_inventory_disabled = is_disabled; }
	// The driver of a car has no inventory and uses no items (owner
	// 2026-10-24, spec 3.2); passengers keep theirs.
	bool inventory_disabled() const { return m_inventory_disabled || (netcoop_seated() && m_netcoop_seat_driver); }
private:
	void set_state_box(u32 mstate);
private:
	bool m_disabled_hitmarks;
	bool m_inventory_disabled;
	//static CPhysicsShell		*actor_camera_shell;

	IC u32 get_state() const
	{
		return this->mstate_real;
	}

	IC void set_state(u32 state)
	{
		mstate_real = state;
	}

	IC u32 get_state_wishful() const
	{
		return this->mstate_wishful;
	}

	IC void set_state_wishful(u32 state)
	{
		mstate_wishful = state;
	}

public:
	void SwitchNightVision(bool light_on, bool use_sounds = true, bool send_event = true);

	bool GetNightVisionStatus() { return m_bNightVisionOn; }
	void SetNightVisionAllowed(bool bAllow) { m_bNightVisionAllow = bAllow; }
	CNightVisionEffector* GetNightVision() { return m_night_vision; }
protected:
	bool m_bNightVisionOn;
	bool m_bNightVisionAllow;
	bool m_bSafemode;
public:
	bool is_safemode() { return m_bSafemode; }
	void set_safemode(bool status);

	void RPC_UpdateFaction();
	void RPC_UpdateRank();
	void RPC_UpdateReputation();

	CNightVisionEffector* m_night_vision;

private:
    struct npc_visibility
    {
        u16 id;
        float value;

        bool operator ==(const u16& _id)
        {
            return id == _id;
        }

        bool operator <(const npc_visibility& m) const
        {
            return (value < m.value);
        }
    };

    xr_vector<npc_visibility> m_npc_visibility;
    float m_visibility_tgt = 0.0f;
    float m_visibility_cur = 0.0f;
    bool m_visibility_changed = false;

public:
    float GetVisibility();
    void SetVisibilityValue(float value);
    void SetVisibilityFromObject(u16 who_id, float value);

public:
    DECLARE_SCRIPT_REGISTER_FUNCTION
};

extern bool isActorAccelerated(u32 mstate, bool ZoomMode);

IC CActorCondition& CActor::conditions() const
{
	VERIFY(m_entity_condition);
	return (*m_entity_condition);
}

extern CActor* g_actor;
CActor* Actor();
extern const float s_fFallTime;
