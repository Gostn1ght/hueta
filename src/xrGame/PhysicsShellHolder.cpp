#include "pch_script.h"
#include "PhysicsShellHolder.h"
#include "../xrphysics/PhysicsShell.h"
#include "xrMessages.h"
#include "ph_shell_interface.h"
#include "../Include/xrRender/Kinematics.h"
#include "script_callback_ex.h"
#include "Level.h"
#include "PHCommander.h"
#include "PHScriptCall.h"
#include "CustomRocket.h"
#include "Grenade.h"
#include "netcoop.h"
#include "entity_alive.h"
#include "../xrServerEntities/PHSynchronize.h"
#include "inventory_item.h"
#include "Weapon.h"
#include "WeaponAmmo.h"
#include "CustomOutfit.h"
#include "ActorHelmet.h"
#include "eatable_item.h"
#include "Artefact.h"
#include "WeaponPistol.h"
#include "WeaponKnife.h"
#include "CustomDevice.h"
#include "Torch.h"
#include "PDA.h"

//#include "phactivationshape.h"
#include "../xrphysics/iphworld.h"
#include "../xrphysics/iActivationShape.h"
//#include "../xrphysics/phvalide.h"
#include "characterphysicssupport.h"
#include "phmovementcontrol.h"
#include "physics_shell_animated.h"
#include "phcollisiondamagereceiver.h"
#include "../xrEngine/iphysicsshell.h"
#ifdef	DEBUG
#include "../xrengine/objectdump.h"
#endif
CPhysicsShellHolder::CPhysicsShellHolder()
{
	init();
	PHRegisterShellHolder(this);
}

// Item physics profiles on the server (gameplay plan, stage 6). One rule
// for every item made a rifle, a bottle and a bag slide and bounce alike.
// Coulomb friction: the solver limits tangential impulse to mu * normal
// impulse; applied only on static ground, keeping collision shape, mass,
// slopes and the material callbacks. "angular" scales rolling resistance.
// A section can name its profile: netcoop_physics_profile = weapon.
struct NetcoopPhysicsProfile { LPCSTR name; float mu, bounce, angular; };
static const NetcoopPhysicsProfile s_netcoop_profiles[] = {
	{"small", 0.8f, 0.08f, 2.f}, // anything not listed below
	{"weapon", 1.0f, 0.04f, 6.f}, // rifles, shotguns: long and heavy, must not roll or skate
	{"bottle", 0.55f, 0.15f, 1.f}, // glass, cans: roll and clink
	{"metal", 0.65f, 0.12f, 2.f}, // knives, tools, parts, devices
	{"soft", 1.3f, 0.02f, 8.f}, // outfits
	{"pistol", 0.9f, 0.06f, 4.f}, // pistols
	{"helmet", 0.7f, 0.10f, 3.f}, // helmets, gas masks: hard shell, rock a little
	{"ammo", 0.9f, 0.05f, 5.f}, // ammunition boxes: flat, slide a little, do not roll
	{"food", 0.9f, 0.05f, 4.f}, // packaged food, bread, meat
	{"medicine", 0.8f, 0.06f, 3.f}, // medkits, bandages, pills
	{"artefact", 0.5f, 0.20f, 1.f}, // rounded, roll furthest
	{"grenade", 0.6f, 0.15f, 1.f}, // round, bounce
	{"bag", 1.2f, 0.02f, 8.f}, // backpacks and sacks
};
enum { netcoop_profile_small, netcoop_profile_weapon, netcoop_profile_bottle, netcoop_profile_metal, netcoop_profile_soft,
	netcoop_profile_pistol, netcoop_profile_helmet, netcoop_profile_ammo, netcoop_profile_food, netcoop_profile_medicine,
	netcoop_profile_artefact, netcoop_profile_grenade, netcoop_profile_bag, netcoop_profile_count };

template <int Profile>
static void netcoop_item_ground_contact(bool& collide, bool, dContact& contact, SGameMtl*, SGameMtl*)
{
	if (!collide || (dGeomGetBody(contact.geom.g1) && dGeomGetBody(contact.geom.g2)) ||
		_abs(contact.geom.normal[1]) < 0.5f) return;
	const NetcoopPhysicsProfile& profile = s_netcoop_profiles[Profile];
	contact.surface.mu = _max(contact.surface.mu, profile.mu);
	contact.surface.mu2 = _max(contact.surface.mu2, profile.mu);
	contact.surface.mode &= ~(dContactSlip1 | dContactSlip2);
	contact.surface.mode |= dContactApprox1;
	contact.surface.slip1 = contact.surface.slip2 = 0.f;
	contact.surface.bounce = _min(contact.surface.bounce, profile.bounce);
	contact.surface.bounce_vel = _max(contact.surface.bounce_vel, 1.5f);
}

static ObjectContactCallbackFun* const s_netcoop_profile_contacts[netcoop_profile_count] = {
	netcoop_item_ground_contact<0>, netcoop_item_ground_contact<1>, netcoop_item_ground_contact<2>,
	netcoop_item_ground_contact<3>, netcoop_item_ground_contact<4>, netcoop_item_ground_contact<5>,
	netcoop_item_ground_contact<6>, netcoop_item_ground_contact<7>, netcoop_item_ground_contact<8>,
	netcoop_item_ground_contact<9>, netcoop_item_ground_contact<10>, netcoop_item_ground_contact<11>,
	netcoop_item_ground_contact<12>,
};
static_assert(sizeof(s_netcoop_profiles) / sizeof(s_netcoop_profiles[0]) == netcoop_profile_count, "one row per profile");

static bool netcoop_section_has(LPCSTR section, LPCSTR const* words, u32 count)
{
	for (u32 i = 0; i < count; ++i)
		if (strstr(section, words[i])) return true;
	return false;
}

static int netcoop_item_profile(CPhysicsShellHolder* holder)
{
	LPCSTR section = holder->cNameSect().c_str();
	if (pSettings->line_exist(section, "netcoop_physics_profile"))
	{
		LPCSTR name = pSettings->r_string(section, "netcoop_physics_profile");
		for (int i = 0; i < netcoop_profile_count; ++i)
			if (!xr_strcmp(name, s_netcoop_profiles[i].name)) return i;
	}
	static LPCSTR const bags[] = {"backpack", "sack", "bag"};
	static LPCSTR const containers[] = {"bottle", "vodka", "water", "beer", "drink", "energy", "juice", "flask", "can"};
	static LPCSTR const medicine[] = {"medkit", "bandage", "antirad", "drug", "stimpack", "pill", "morphine", "adrenalin",
		"vinca", "salicidic", "rad_", "survival_kit", "akvatab"};
	if (smart_cast<CWeaponAmmo*>(holder)) return netcoop_profile_ammo;
	if (smart_cast<CGrenade*>(holder)) return netcoop_profile_grenade;
	if (smart_cast<CWeaponKnife*>(holder)) return netcoop_profile_metal;
	if (smart_cast<CWeaponPistol*>(holder)) return netcoop_profile_pistol;
	if (smart_cast<CWeapon*>(holder)) return netcoop_profile_weapon;
	if (smart_cast<CHelmet*>(holder)) return netcoop_profile_helmet;
	if (smart_cast<CCustomOutfit*>(holder)) return netcoop_profile_soft;
	if (smart_cast<CArtefact*>(holder)) return netcoop_profile_artefact;
	if (smart_cast<CCustomDevice*>(holder) || smart_cast<CTorch*>(holder) || smart_cast<CPda*>(holder))
		return netcoop_profile_metal;
	if (smart_cast<CEatableItem*>(holder))
	{
		if (netcoop_section_has(section, containers, sizeof(containers) / sizeof(containers[0]))) return netcoop_profile_bottle;
		if (netcoop_section_has(section, medicine, sizeof(medicine) / sizeof(medicine[0]))) return netcoop_profile_medicine;
		return netcoop_profile_food;
	}
	if (netcoop_section_has(section, bags, sizeof(bags) / sizeof(bags[0]))) return netcoop_profile_bag;
	// Tools, parts, repair kits and other hardware are metal; the rest small.
	if (strstr(section, "tool") || strstr(section, "part") || strstr(section, "kit") || strstr(section, "prt_"))
		return netcoop_profile_metal;
	return netcoop_profile_small;
}

static void netcoop_apply_item_profile(CPhysicsShellHolder* holder, CPhysicsShell* shell)
{
	const int index = netcoop_item_profile(holder);
	shell->add_ObjectContactCallback(s_netcoop_profile_contacts[index]);
	float linear = 0.f, angular = 0.f;
	shell->GetAirResistance(linear, angular);
	shell->SetAirResistance(linear, angular * s_netcoop_profiles[index].angular);
}

CPhysicsShellHolder::~CPhysicsShellHolder()
{
	// Contact metadata can survive its game object during a death/drop cycle.
	// Retire the pointer before any destructor clears the object's vtable.
	PHUnregisterShellHolder(this);
	VERIFY(!m_pPhysicsShell);
	//#ifndef MASTER_GOLD
	//R_ASSERT( !m_pPhysicsShell );
	//#endif
	destroy_physics_shell(m_pPhysicsShell);
}

const IObjectPhysicsCollision* CPhysicsShellHolder::physics_collision()
{
	CCharacterPhysicsSupport* char_support = character_physics_support();
	if (char_support)
		char_support->create_animation_collision();
	return this;
}

const IPhysicsShell* CPhysicsShellHolder::physics_shell() const
{
	if (m_pPhysicsShell)
		return m_pPhysicsShell;
	const CCharacterPhysicsSupport* char_support = character_physics_support();
	if (!char_support || !char_support->animation_collision())
		return 0;
	return char_support->animation_collision()->shell();
}

IPhysicsShell* CPhysicsShellHolder::physics_shell()
{
	return m_pPhysicsShell;
}

const IPhysicsElement* CPhysicsShellHolder::physics_character() const
{
	const CCharacterPhysicsSupport* char_support = character_physics_support();
	if (!char_support)
		return 0;
	const CPHMovementControl* mov = character_physics_support()->movement();
	VERIFY(mov);
	return mov->IElement();
}

void CPhysicsShellHolder::netcoop_physics_reset()
{
	if (!netcoop::pure_client()) return;
	m_netcoop_physics.clear();
	m_netcoop_replica_shell = nullptr;
	if (m_netcoop_physics_processing) processing_deactivate();
	m_netcoop_physics_processing = false;
	m_netcoop_render_time = m_netcoop_render_frame = 0;
	m_netcoop_render_delay = 0.f;
}

void CPhysicsShellHolder::net_Destroy()
{
	m_netcoop_physics.clear();
	if (m_netcoop_physics_processing) processing_deactivate();
	m_netcoop_physics_processing = false;
	m_netcoop_replica_shell = nullptr;
	//remove calls
	CPHSriptReqGObjComparer cmpr(this);
	Level().ph_commander_scripts().remove_calls(&cmpr);
	//удалить партиклы из ParticlePlayer
	CParticlesPlayer::net_DestroyParticles();
	CCharacterPhysicsSupport* char_support = character_physics_support();
	if (char_support)
		char_support->destroy_imotion();
	inherited::net_Destroy();
	b_sheduled = false;
	
	deactivate_physics_shell();
	xr_delete(m_pPhysicsShell);
}

static enum EEnableState
{
	stEnable =0,
	stDisable,
	stNotDefitnite
};

static u8 st_enable_state = (u8)stNotDefitnite;

BOOL CPhysicsShellHolder::net_Spawn(CSE_Abstract* DC)
{
	CParticlesPlayer::net_SpawnParticles();
	st_enable_state = (u8)stNotDefitnite;
	b_sheduled = true;
	BOOL ret = inherited::net_Spawn(DC); //load
	//create_physic_shell			();
	if (PPhysicsShell() && PPhysicsShell()->isFullActive())
	{
		PPhysicsShell()->GetGlobalTransformDynamic(&XFORM());
		PPhysicsShell()->mXFORM = XFORM();
		switch (EEnableState(st_enable_state))
		{
		case stEnable: PPhysicsShell()->Enable();
			break;
		case stDisable: PPhysicsShell()->Disable();
			break;
		case stNotDefitnite: ;
			break;
		}
		ApplySpawnIniToPhysicShell(pSettings, PPhysicsShell(), false);


		st_enable_state = (u8)stNotDefitnite;
	}

#if 1
	m_ignore_collision_flag = 0;
	if (pSettings->line_exist(cNameSect_str(), "ignore_collision"))
	{
		LPCSTR tmp = pSettings->r_string(cNameSect_str(), "ignore_collision");
		if (strstr(tmp, "map"))
		{
			m_ignore_collision_flag = m_ignore_collision_flag | ICmap;
		}
		if (strstr(tmp, "obj"))
		{
			m_ignore_collision_flag = m_ignore_collision_flag | ICobj;
		}
		if (strstr(tmp, "npc"))
		{
			m_ignore_collision_flag = m_ignore_collision_flag | ICnpc;
		}
	}
#endif

	return ret;
}

void CPhysicsShellHolder::PHHit(SHit& H)
{
	float impulse = H.phys_impulse();
	if (netcoop::enabled() && !netcoop::pure_client() && m_pPhysicsShell &&
		H.type() == ALife::eHitTypeFireWound && !smart_cast<CEntityAlive*>(this) && !smart_cast<CMissile*>(this))
	{
		// Bullet momentum, not a mass increase: a 7.62 mm shot cannot launch
		// a barrel like a rocket. Explosion impulses and thrown missiles stay stock.
		impulse = _min(impulse, _min(8.f, m_pPhysicsShell->getMass() * 0.6f));
	}
	if (impulse > 0)
		if (m_pPhysicsShell) m_pPhysicsShell->applyHit(H.bone_space_position(), H.direction(), impulse,
		                                               H.bone(), H.type());
}

//void	CPhysicsShellHolder::Hit(float P, Fvector &dir, CObject* who, s16 element,
//						 Fvector p_in_object_space, float impulse, ALife::EHitType hit_type)
void CPhysicsShellHolder::Hit(SHit* pHDS)
{
	bool const is_special_burn_hit_2_self = (pHDS->who == this) && (pHDS->boneID == BI_NONE) &&
		((pHDS->hit_type == ALife::eHitTypeBurn) || (pHDS->hit_type == ALife::eHitTypeLightBurn));
	if (!is_special_burn_hit_2_self)
	{
		PHHit(*pHDS);
	}
}

void CPhysicsShellHolder::create_physic_shell()
{
	VERIFY(!m_pPhysicsShell);
	IPhysicShellCreator* shell_creator = smart_cast<IPhysicShellCreator*>(this);
	if (shell_creator)
		shell_creator->CreatePhysicsShell();
}

void CPhysicsShellHolder::init()
{
	m_pPhysicsShell = NULL;
	b_sheduled = false;

#if 1
	m_ignore_collision_flag = 0;
#endif
}

bool CPhysicsShellHolder::has_shell_collision_place(const CPhysicsShellHolder* obj) const
{
	if (character_physics_support())
		return character_physics_support()->has_shell_collision_place(obj);
	return false;
}

void CPhysicsShellHolder::on_child_shell_activate(CPhysicsShellHolder* obj)
{
	if (character_physics_support())
		character_physics_support()->on_child_shell_activate(obj);
}


void CPhysicsShellHolder::correct_spawn_pos()
{
	VERIFY(PPhysicsShell());

	if (H_Parent())
	{
		CPhysicsShellHolder* P = smart_cast<CPhysicsShellHolder*>(H_Parent());
		if (P && P->has_shell_collision_place(this))
			return;
	}

	Fvector size;
	Fvector c;
	get_box(PPhysicsShell(), XFORM(), size, c);

	// An object with a broken transform or shell box (owner 2026-10-24: a
	// player's decor poster, decor_poster246352 / dynamics\decor\poster2)
	// took the client down here. Pushing it out of the geometry needs a valid
	// box: without one it stays where it is.
	if (!_valid(c) || !_valid(size) || !_valid(XFORM()))
	{
		Msg("! [physics] %s (%s): invalid transform or shell box, spawn position not corrected",
			cName().c_str(), cNameVisual().c_str());
		return;
	}
	PPhysicsShell()->DisableCollision();

	Fvector ap = Fvector().set(0, 0, 0);
	ActivateShapePhysShellHolder(this, XFORM(), size, c, ap);

	////	VERIFY								(valid_pos(activation_shape.Position(),phBoundaries));
	//	if (!valid_pos(activation_shape.Position(),phBoundaries)) {
	//		CPHActivationShape				activation_shape;
	//		activation_shape.Create			(c,size,this);
	//		activation_shape.set_rotation	(XFORM());
	//		activation_shape.Activate		(size,1,1.f,M_PI/8.f);
	////		VERIFY							(valid_pos(activation_shape.Position(),phBoundaries));
	//	}

	PPhysicsShell()->EnableCollision();


	Fmatrix trans;
	trans.identity();
	trans.c.sub(ap, c);
	PPhysicsShell()->TransformPosition(trans, mh_clear);
	PPhysicsShell()->GetGlobalTransformDynamic(&XFORM());
}

void CPhysicsShellHolder::activate_physic_shell()
{
	VERIFY(!m_pPhysicsShell);
	const bool netcoop_throw = m_netcoop_throw;
	m_netcoop_throw = false;
	if (netcoop_throw)
		XFORM().set(m_netcoop_throw_start);
	create_physic_shell();
	if (netcoop::enabled() && !netcoop::pure_client() && smart_cast<CInventoryItem*>(this))
		netcoop_apply_item_profile(this, m_pPhysicsShell);
	Fvector l_fw, l_up;
	l_fw.set(XFORM().k);
	l_up.set(XFORM().j);
	l_fw.mul(2.f);
	l_up.mul(2.f);

	Fmatrix l_p1, l_p2;
	l_p1.set(XFORM());
	l_p2.set(XFORM());
	l_fw.mul(2.f);
	l_p2.c.add(l_fw);

	// setMass changes the cached inertia. Activate builds the ODE bodies from
	// that cache; changing it afterwards leaves the solver at the model mass.
	if (netcoop::enabled() && !netcoop::pure_client())
		if (CInventoryItem* item = smart_cast<CInventoryItem*>(this))
			m_pPhysicsShell->setMass(_max(0.05f, item->Weight()));
	m_pPhysicsShell->Activate(l_p1, 0, l_p2);
	if (H_Parent() && H_Parent()->Visual())
	{
		smart_cast<IKinematics*>(H_Parent()->Visual())->CalculateBones_Invalidate();
		smart_cast<IKinematics*>(H_Parent()->Visual())->CalculateBones(TRUE);
	}
	smart_cast<IKinematics*>(Visual())->CalculateBones_Invalidate();
	smart_cast<IKinematics*>(Visual())->CalculateBones(TRUE);
	//	XFORM().set					(l_p1);
	correct_spawn_pos();

	Fvector overriden_vel;
	if (netcoop_throw)
	{
		ActivationSpeedOverriden(overriden_vel, true); // drop a stale override
		m_pPhysicsShell->set_LinearVel(m_netcoop_throw_velocity);
		Fvector spin; spin.set(0.12f, 0.06f, 0.18f);
		m_pPhysicsShell->set_AngularVel(spin);
	}
	else if (ActivationSpeedOverriden(overriden_vel, true))
	{
		m_pPhysicsShell->set_LinearVel(overriden_vel);
	}
	else
	{
		m_pPhysicsShell->set_LinearVel(l_fw);
	}
	m_pPhysicsShell->GetGlobalTransformDynamic(&XFORM());

	if (H_Parent() && H_Parent()->Visual())
	{
		smart_cast<IKinematics*>(H_Parent()->Visual())->CalculateBones_Invalidate();
		smart_cast<IKinematics*>(H_Parent()->Visual())->CalculateBones(TRUE);
	}
	CPhysicsShellHolder* P = smart_cast<CPhysicsShellHolder*>(H_Parent());
	if (P)
		P->on_child_shell_activate(this);
}

void CPhysicsShellHolder::setup_physic_shell()
{
	VERIFY(!m_pPhysicsShell);
	create_physic_shell();
	if (netcoop::enabled() && !netcoop::pure_client() && smart_cast<CInventoryItem*>(this))
		netcoop_apply_item_profile(this, m_pPhysicsShell);
	if (netcoop::enabled() && !netcoop::pure_client())
		if (CInventoryItem* item = smart_cast<CInventoryItem*>(this))
			m_pPhysicsShell->setMass(_max(0.05f, item->Weight()));
	m_pPhysicsShell->Activate(XFORM(), 0, XFORM());
	smart_cast<IKinematics*>(Visual())->CalculateBones_Invalidate();
	smart_cast<IKinematics*>(Visual())->CalculateBones(TRUE);

	ApplySpawnIniToPhysicShell(spawn_ini(), PPhysicsShell(), false);
	correct_spawn_pos();
	m_pPhysicsShell->GetGlobalTransformDynamic(&XFORM());
}

void CPhysicsShellHolder::deactivate_physics_shell()
{
	// A later drop may allocate its new shell at the same address. Old floor
	// snapshots and replica identity must not survive pickup/shell destruction.
	netcoop_physics_reset();
	destroy_physics_shell(m_pPhysicsShell);
}

void CPhysicsShellHolder::PHSetMaterial(u16 m)
{
	if (m_pPhysicsShell)
		m_pPhysicsShell->SetMaterial(m);
}

void CPhysicsShellHolder::PHSetMaterial(LPCSTR m)
{
	if (m_pPhysicsShell)
		m_pPhysicsShell->SetMaterial(m);
}

void CPhysicsShellHolder::PHGetLinearVell(Fvector& velocity)
{
	if (!m_pPhysicsShell)
	{
		velocity.set(0, 0, 0);
		return;
	}
	m_pPhysicsShell->get_LinearVel(velocity);
}

void CPhysicsShellHolder::PHSetLinearVell(Fvector& velocity)
{
	if (!m_pPhysicsShell)
	{
		return;
	}
	m_pPhysicsShell->set_LinearVel(velocity);
}


f32 CPhysicsShellHolder::GetMass()
{
	return m_pPhysicsShell ? m_pPhysicsShell->getMass() : 0;
}

u16 CPhysicsShellHolder::PHGetSyncItemsNumber()
{
	if (m_pPhysicsShell) return m_pPhysicsShell->get_ElementsNumber();
	else return 0;
}

CPHSynchronize* CPhysicsShellHolder::PHGetSyncItem(u16 item)
{
	if (m_pPhysicsShell) return m_pPhysicsShell->get_ElementSync(item);
	else return 0;
}

void CPhysicsShellHolder::PHUnFreeze()
{
	if (m_pPhysicsShell) m_pPhysicsShell->UnFreeze();
}


void CPhysicsShellHolder::PHFreeze()
{
	if (m_pPhysicsShell) m_pPhysicsShell->Freeze();
}

void CPhysicsShellHolder::OnChangeVisual()
{
	inherited::OnChangeVisual();

	if (0 == renderable.visual)
	{
		CCharacterPhysicsSupport* char_support = character_physics_support();
		if (char_support)
			char_support->destroy_imotion();

		VERIFY(!character_physics_support() || !character_physics_support()->interactive_motion());
		netcoop_physics_reset();
		if (m_pPhysicsShell)m_pPhysicsShell->Deactivate();

		xr_delete(m_pPhysicsShell);
		VERIFY(0==m_pPhysicsShell);
	}
}

void CPhysicsShellHolder::UpdateCL()
{
	inherited::UpdateCL();
	//обновить присоединенные партиклы
	UpdateParticles();
	netcoop_physics_update();
}

static bool netcoop_physics_discontinuous(const SPHNetState& before, const SPHNetState& after, u32 elapsed)
{
	// Displacement alone is not a teleport: an RPG can travel many metres
	// between ordinary snapshots. Compare with its mean-velocity trajectory.
	const float seconds = float(elapsed) / 1000.f;
	const float x = after.position.x - before.position.x - (before.linear_vel.x + after.linear_vel.x) * .5f * seconds;
	const float y = after.position.y - before.position.y - (before.linear_vel.y + after.linear_vel.y) * .5f * seconds;
	const float z = after.position.z - before.position.z - (before.linear_vel.z + after.linear_vel.z) * .5f * seconds;
	return x*x + y*y + z*z > 9.f;
}

void CPhysicsShellHolder::netcoop_physics_import(NET_Packet& P)
{
	NetcoopPhysicsSnapshot snapshot;
	snapshot.stamp = P.r_u32();
	const u16 count = P.r_u16();
	// 41 bytes per body: enabled, position, rotation, linear velocity.
	if (!count || count > 128 || P.r_elapsed() != u32(count) * 41)
		return;
	snapshot.states.resize(count);
	for (SPHNetState& state : snapshot.states)
	{
		state.enabled = P.r_u8() != 0;
		P.r_vec3(state.position);
		P.r_float(state.quaternion.x);
		P.r_float(state.quaternion.y);
		P.r_float(state.quaternion.z);
		P.r_float(state.quaternion.w);
		P.r_vec3(state.linear_vel);
		const float norm = state.quaternion.magnitude();
		if (!_valid(state.position) || !_valid(state.quaternion) || !_valid(state.linear_vel) || norm < 0.0001f)
			return;
		state.quaternion.normalize();
		state.previous_position = state.position;
		state.previous_quaternion = state.quaternion;
		state.angular_vel.set(0.f, 0.f, 0.f);
		state.force.set(0.f, 0.f, 0.f);
		state.torque.set(0.f, 0.f, 0.f);
	}
	if (H_Parent()) return;
	if (!m_netcoop_physics.empty())
	{
		if (s32(snapshot.stamp - m_netcoop_physics.back().stamp) <= 0) return;
		// A sleeping body is sent once and then every 10 s (stage 6); after
		// such a gap the old samples would stretch the interpolation delay.
		if (snapshot.states.size() != m_netcoop_physics.back().states.size() ||
			netcoop_physics_discontinuous(m_netcoop_physics.back().states[0], snapshot.states[0], snapshot.stamp - m_netcoop_physics.back().stamp) ||
			s32(snapshot.stamp - m_netcoop_physics.back().stamp) > 500)
			m_netcoop_physics.clear();
	}
	netcoop::snapshot_sample(snapshot.stamp);
	m_netcoop_physics.push_back(std::move(snapshot));
	while (m_netcoop_physics.size() > 24) m_netcoop_physics.pop_front();
	if (!m_netcoop_physics_processing)
	{
		processing_activate();
		m_netcoop_physics_processing = true;
	}
	netcoop_physics_update();
}

u32 CPhysicsShellHolder::netcoop_interpolation_time(u32 interval)
{
    const u32 now = netcoop::snapshot_now();
    if (!netcoop::pure_client())
    {
        const u32 delay = netcoop::remote_interp_delay(interval);
        return now > delay ? now - delay : 0;
    }
    // A packet gap must not move the displayed pose backward in time.
    // Slew delay per object, since distant replicas have a different rate.
    if (!m_netcoop_render_frame || Device.dwFrame != m_netcoop_render_frame)
    {
        const float target = float(netcoop::remote_interp_delay(interval));
        if (!m_netcoop_render_frame) m_netcoop_render_delay = target;
        else
        {
            const float step = _min(Device.fTimeDelta, 0.1f) * 100.f;
            m_netcoop_render_delay += _max(-step, _min(target - m_netcoop_render_delay, step));
        }
        m_netcoop_render_frame = Device.dwFrame;
        const u32 delay = u32(m_netcoop_render_delay);
        const u32 time = now > delay ? now - delay : 0;
        if (!m_netcoop_render_time || s32(time - m_netcoop_render_time) >= 0) m_netcoop_render_time = time;
    }
    return m_netcoop_render_time;
}

static float netcoop_physics_coordinate(float a, float b, float va, float vb, float seconds, float t)
{
    const float distance = b - a;
    if (seconds <= 0.f || _abs(distance) < EPS_S) return a + distance * t;
    float ta = va * seconds, tb = vb * seconds;
    if (ta * distance < 0.f) ta = 0.f;
    if (tb * distance < 0.f) tb = 0.f;
    const float limit = 3.f * _abs(distance);
    clamp(ta, -limit, limit); clamp(tb, -limit, limit);
    const float alpha = ta / distance, beta = tb / distance;
    const float length = alpha * alpha + beta * beta;
    if (length > 9.f) { const float scale = 3.f / _sqrt(length); ta *= scale; tb *= scale; }
    const float t2 = t * t, t3 = t2 * t;
    return (2.f*t3-3.f*t2+1.f)*a + (t3-2.f*t2+t)*ta + (-2.f*t3+3.f*t2)*b + (t3-t2)*tb;
}

void CPhysicsShellHolder::netcoop_physics_update()
{
	if (!netcoop::pure_client() || m_netcoop_physics.empty()) return;
	if (H_Parent())
	{
		m_netcoop_physics.clear();
		if (PPhysicsShell() && PPhysicsShell() == m_netcoop_replica_shell)
			for (u16 i = 0; i < PHGetSyncItemsNumber(); ++i) PPhysicsShell()->get_ElementByStoreOrder(i)->ReleaseFixed();
		m_netcoop_replica_shell = nullptr;
		if (m_netcoop_physics_processing) processing_deactivate();
		m_netcoop_physics_processing = false;
		return;
	}
	CPhysicsShell* shell = PPhysicsShell();
	if (!shell || PHGetSyncItemsNumber() != m_netcoop_physics.back().states.size()) return;
	if (shell != m_netcoop_replica_shell)
	{
		// Bridge from the visible local pose to the first authoritative pose.
		// Without this sample the first death/drop packet snaps every bone.
		if (m_netcoop_physics.size() == 1)
		{
			NetcoopPhysicsSnapshot seed;
			seed.stamp = _min(m_netcoop_physics.front().stamp - 1, netcoop_interpolation_time(50));
			seed.states.resize(PHGetSyncItemsNumber());
			for (u16 i = 0; i < PHGetSyncItemsNumber(); ++i) PHGetSyncItem(i)->get_State(seed.states[i]);
			if (seed.states[0].position.distance_to(m_netcoop_physics.front().states[0].position) < 0.75f)
				m_netcoop_physics.push_front(std::move(seed));
		}
		for (u16 i = 0; i < PHGetSyncItemsNumber(); ++i) shell->get_ElementByStoreOrder(i)->Fix();
		shell->EnableCollision();
		// A replica stands where the server puts it. Touching the ground or
		// small, ragdoll and animated bodies here only made contacts: a fixed
		// body (mass 1e8) pushed them every frame, and dust and impact sounds
		// repeated forever (owner 2026-10-17). Characters must still bump into
		// it - and a character is also of the dynamic class (InitObject), so
		// "not with dynamic" let players walk through every car and helicopter
		// (owner 2026-10-18). CPHCollideValidator: cbNCStatic, cbNCClassSmall,
		// cbNCClassRagDoll, cbNCClassAnimated.
		shell->collide_class_bits().set(CLClassBits(1 << 3), FALSE);
		shell->collide_class_bits().set(CLClassBits((1 << 1) | (1 << 7) | (1 << 9) | (1 << 11)), TRUE);
		// A fixed body weighs 1e8: an item on the floor stopped the player like
		// a wall. Players walk into items and the server kicks them aside.
		if (smart_cast<CInventoryItem*>(this))
			shell->collide_class_bits().set(CLClassBits(1) << 5, TRUE); // CPHCollideValidator::cbNCClassCharacter
		m_netcoop_replica_shell = shell;
	}
	shell->Enable(); // fixed replica bodies remain solid to the local player
	const u32 interval = m_netcoop_physics.size() > 1 ?
		m_netcoop_physics.back().stamp - m_netcoop_physics[m_netcoop_physics.size() - 2].stamp : 50;
	const u32 time = netcoop_interpolation_time(interval);
	while (m_netcoop_physics.size() > 2 && s32(time - m_netcoop_physics[1].stamp) >= 0)
		m_netcoop_physics.pop_front();
	const NetcoopPhysicsSnapshot& first = m_netcoop_physics.front();
	const NetcoopPhysicsSnapshot& last = m_netcoop_physics.size() > 1 ? m_netcoop_physics[1] : first;
	const s32 span = s32(last.stamp - first.stamp);
	const float factor = span > 0 ? _max(0.f, _min(1.f, float(s32(time - first.stamp)) / span)) : 0.f;
	const bool ballistic = smart_cast<CMissile*>(this) || smart_cast<CCustomRocket*>(this);
	const s32 late=s32(time-last.stamp);
	const float predict=ballistic && late>0 ? float(_min(late,150))*.001f:0.f;
	for (u16 i = 0; i < first.states.size(); ++i)
	{
		SPHNetState state = first.states[i];
		const auto& a = first.states[i]; const auto& b = last.states[i];
		const float seconds = _max(0.f, float(span) / 1000.f);
		state.position.set(
		    netcoop_physics_coordinate(a.position.x,b.position.x,a.linear_vel.x,b.linear_vel.x,seconds,factor),
		    netcoop_physics_coordinate(a.position.y,b.position.y,a.linear_vel.y,b.linear_vel.y,seconds,factor),
		    netcoop_physics_coordinate(a.position.z,b.position.z,a.linear_vel.z,b.linear_vel.z,seconds,factor));
		state.quaternion.slerp(first.states[i].quaternion, last.states[i].quaternion, factor);
		if(predict>0.f && b.enabled && b.linear_vel.square_magnitude()<2000.f*2000.f) {
			// A 100 ms server frame must not freeze an airborne grenade at
			// every packet. Predict a short physical segment, stopping at static
			// geometry; collisions/explosions remain exclusively authoritative.
			Fvector projected;projected.mad(b.position,b.linear_vel,predict);
			if(smart_cast<CMissile*>(this)) projected.y-=.5f*physics_world()->Gravity()*predict*predict;
			Fvector path;path.sub(projected,b.position);
			const float distance=path.magnitude();
			if(distance>EPS_S && _valid(projected)) {
				path.div(distance);collide::rq_result hit;
				if(Level().ObjectSpace.RayPick(b.position,path,distance,collide::rqtStatic,hit,this))
					projected.mad(b.position,path,_max(0.f,hit.range-.01f));
				state.position=projected;
			}
		}
		state.previous_position = state.position;
		state.previous_quaternion = state.quaternion;
		state.enabled = true;
		state.linear_vel.set(0.f, 0.f, 0.f);
		// The replica follows interpolated poses. FixBody clears these too;
		// restoring server dynamics would spin/force the fixed ODE body locally.
		state.angular_vel.set(0.f, 0.f, 0.f);
		state.force.set(0.f, 0.f, 0.f);
		state.torque.set(0.f, 0.f, 0.f);
		PHGetSyncItem(i)->set_State(state);
	}
	// Ordinary replicas are interpolated only; ballistic prediction above is
	// bounded to 150 ms and swept against walls/floors before applying the pose.
	shell->GetGlobalTransformDynamic(&XFORM());
	if (Visual())
		if (IKinematics* K = Visual()->dcast_PKinematics())
		{
			K->CalculateBones_Invalidate();
			K->CalculateBones(TRUE);
		}
	spatial_move();
}

float CPhysicsShellHolder::EffectiveGravity()
{
	return physics_world()->Gravity();
}

void CPhysicsShellHolder::save(NET_Packet& output_packet)
{
	inherited::save(output_packet);
	u8 enable_state = (u8)stNotDefitnite;
	if (PPhysicsShell() && PPhysicsShell()->isActive())
	{
		enable_state = u8(PPhysicsShell()->isEnabled() ? stEnable : stDisable);
	}
	output_packet.w_u8(enable_state);
}

void CPhysicsShellHolder::load(IReader& input_packet)
{
	inherited::load(input_packet);
	st_enable_state = input_packet.r_u8();
}

void CPhysicsShellHolder::PHSaveState(NET_Packet& P)
{
	//CPhysicsShell* pPhysicsShell=PPhysicsShell();
	IKinematics* K = smart_cast<IKinematics*>(Visual());
	//Flags8 lflags;
	//if(pPhysicsShell&&pPhysicsShell->isActive())			lflags.set(CSE_PHSkeleton::flActive,pPhysicsShell->isEnabled());

	//	P.w_u8 (lflags.get());
	if (K)
	{
		P.w_u64(K->LL_GetBonesVisible());
		P.w_u16(K->LL_GetBoneRoot());
	}
	else
	{
		P.w_u64(u64(-1));
		P.w_u16(0);
	}
	/////////////////////////////
	Fvector min, max;

	min.set(flt_max,flt_max,flt_max);
	max.set(-flt_max, -flt_max, -flt_max);
	/////////////////////////////////////

	u16 bones_number = PHGetSyncItemsNumber();
	for (u16 i = 0; i < bones_number; i++)
	{
		SPHNetState state;
		PHGetSyncItem(i)->get_State(state);
		Fvector& p = state.position;
		if (p.x < min.x)min.x = p.x;
		if (p.y < min.y)min.y = p.y;
		if (p.z < min.z)min.z = p.z;

		if (p.x > max.x)max.x = p.x;
		if (p.y > max.y)max.y = p.y;
		if (p.z > max.z)max.z = p.z;
	}

	min.sub(2.f * EPS_L);
	max.add(2.f * EPS_L);

	VERIFY(!min.similar(max));
	P.w_vec3(min);
	P.w_vec3(max);

	P.w_u16(bones_number);

	for (u16 i = 0; i < bones_number; i++)
	{
		SPHNetState state;
		PHGetSyncItem(i)->get_State(state);
		state.net_Save(P, min, max);
	}
}

void
CPhysicsShellHolder::PHLoadState(IReader& P)
{
	//	Flags8 lflags;
	IKinematics* K = smart_cast<IKinematics*>(Visual());
	//	P.r_u8 (lflags.flags);
	if (K)
	{
		K->LL_SetBonesVisible(P.r_u64());
		K->LL_SetBoneRoot(P.r_u16());
	}

	Fvector min = P.r_vec3();
	Fvector max = P.r_vec3();

	VERIFY(!min.similar(max));

	u16 bones_number = P.r_u16();
	for (u16 i = 0; i < bones_number; i++)
	{
		SPHNetState state;
		state.net_Load(P, min, max);
		PHGetSyncItem(i)->set_State(state);
	}
}

bool CPhysicsShellHolder::register_schedule() const
{
	return (b_sheduled);
}

void CPhysicsShellHolder::on_physics_disable()
{
	// A shell went to sleep. Clients learn frozen physics from the server's
	// updates; nothing is sent from here.
}


Fmatrix& CPhysicsShellHolder::ObjectXFORM()
{
	return XFORM();
}

Fvector& CPhysicsShellHolder::ObjectPosition()
{
	return Position();
}

LPCSTR CPhysicsShellHolder::ObjectName() const
{
	return cName().c_str();
}

LPCSTR CPhysicsShellHolder::ObjectNameVisual() const
{
	return cNameVisual().c_str();
}

LPCSTR CPhysicsShellHolder::ObjectNameSect() const
{
	return cNameSect().c_str();
}

bool CPhysicsShellHolder::ObjectGetDestroy() const
{
	return !!getDestroy();
}

ICollisionHitCallback* CPhysicsShellHolder::ObjectGetCollisionHitCallback()
{
	return get_collision_hit_callback();
}

u16 CPhysicsShellHolder::ObjectID() const
{
	return ID();
}

ICollisionForm* CPhysicsShellHolder::ObjectCollisionModel()
{
	return collidable.model;
}

IKinematics* CPhysicsShellHolder::ObjectKinematics()
{
	VERIFY(Visual());
	return Visual()->dcast_PKinematics();
}

IDamageSource* CPhysicsShellHolder::ObjectCastIDamageSource()
{
	return cast_IDamageSource();
}

void CPhysicsShellHolder::ObjectProcessingDeactivate()
{
	processing_deactivate();
}

void CPhysicsShellHolder::ObjectProcessingActivate()
{
	processing_activate();
}

void CPhysicsShellHolder::ObjectSpatialMove()
{
	spatial_move();
}

CPhysicsShell*& CPhysicsShellHolder::ObjectPPhysicsShell()
{
	return PPhysicsShell();
}

//void CPhysicsShellHolder::enable_notificate()
//{
//	
//}
bool CPhysicsShellHolder::has_parent_object()
{
	return !!H_Parent();
}

//void CPhysicsShellHolder::on_physics_disable()
//{
//
//}
IPHCapture* CPhysicsShellHolder::PHCapture()
{
	CCharacterPhysicsSupport* ph_sup = character_physics_support();
	if (!ph_sup)
		return 0;
	CPHMovementControl* mov = ph_sup->movement();
	if (!mov)
		return 0;
	return mov->PHCapture();
}

bool CPhysicsShellHolder::IsInventoryItem()
{
	return !!cast_inventory_item();
}

bool CPhysicsShellHolder::IsActor()
{
	return !!cast_actor();
}

bool CPhysicsShellHolder::IsStalker()
{
	return !!cast_stalker();
}

//void						SetWeaponHideState( u16 State, bool bSet )
void CPhysicsShellHolder::HideAllWeapons(bool v)
{
}

void CPhysicsShellHolder::MovementCollisionEnable(bool enable)
{
	VERIFY(character_physics_support());
	VERIFY(character_physics_support()->movement());
	character_physics_support()->movement()->CollisionEnable(enable);
}

ICollisionDamageReceiver* CPhysicsShellHolder::ObjectPhCollisionDamageReceiver()
{
	return PHCollisionDamageReceiver();
}

void CPhysicsShellHolder::BonceDamagerCallback(float& damage_factor)
{
	//CCharacterPhysicsSupport* phs=static_cast<CPhysicsShellHolder*>(o_damager)->character_physics_support();
	//if(phs->IsSpecificDamager())damager_material_factor=phs->BonceDamageFactor();
	CCharacterPhysicsSupport* phs = character_physics_support();
	if (phs->IsSpecificDamager())
		damage_factor = phs->BonceDamageFactor();
}

#ifdef	DEBUG
std::string	CPhysicsShellHolder::dump(EDumpType type) const
{
	switch(type)
	{
	case	base:				return dbg_object_base_dump_string( this );						break;   
	case	poses:				return dbg_object_poses_dump_string( this );					break;
	case	vis_geom:			return dbg_object_visual_geom_dump_string( this );				break;
	case	props:				return dbg_object_props_dump_string( this );					break;
	case	full:				return dbg_object_full_dump_string( this);						break;
	case	full_capped:		return dbg_object_full_capped_dump_string( this );				break;
	default: NODEFAULT;			return std::string("fail!");
	}

}
#endif

#if 1
void CPhysicsShellHolder::IgnoreCollisionCallback(bool &do_colide, bool bo1, dContact &c, SGameMtl *material_1, SGameMtl *material_2)
{
	if (do_colide == false)
	{
		return;
	}

	dxGeomUserData *gd1 = bo1 ? PHRetrieveGeomUserData(c.geom.g1) : PHRetrieveGeomUserData(c.geom.g2);
	dxGeomUserData *gd2 = bo1 ? PHRetrieveGeomUserData(c.geom.g2) : PHRetrieveGeomUserData(c.geom.g1);
	CGameObject *obj = (gd1) ? smart_cast<CGameObject *>(gd1->ph_ref_object) : NULL;
	CGameObject *who = (gd2) ? smart_cast<CGameObject *>(gd2->ph_ref_object) : NULL;

	if (obj == NULL)
	{
		return;
	}

	CPhysicsShellHolder *a = (obj) ? smart_cast<CPhysicsShellHolder *>(obj) : NULL;
	if (a == NULL)
	{
		return;
	}

	if (who == NULL)
	{
		if (a->m_ignore_collision_flag & CPhysicsShellHolder::ICmap)
		{
			do_colide = false;
		}
		return;
	}

	CPhysicsShellHolder *b = smart_cast<CPhysicsShellHolder *>(who);
	if (b)
	{
		if (who->cast_actor() || who->cast_stalker() || who->cast_base_monster())
		{
			if (a->m_ignore_collision_flag & CPhysicsShellHolder::ICnpc)
			{
				do_colide = false;
				return;
			}
		}
		else
		{
			if (a->m_ignore_collision_flag & CPhysicsShellHolder::ICobj)
			{
				if (b->m_ignore_collision_flag & CPhysicsShellHolder::ICobj)
				{
					do_colide = false;
					return;
				}
			}
		}
	}
}

void CPhysicsShellHolder::active_ignore_collision()
{
	R_ASSERT(PPhysicsShell());
	PPhysicsShell()->add_ObjectContactCallback(IgnoreCollisionCallback);
}
#endif
