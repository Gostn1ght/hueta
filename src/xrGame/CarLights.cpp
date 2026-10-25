#include "stdafx.h"
#include "CarLights.h"
#ifdef DEBUG

#include "PHDebug.h"
#endif
#include "alife_space.h"
#include "hit.h"
#include "PHDestroyable.h"
#include "Car.h"
#include "../Include/xrRender/Kinematics.h"
//#include "PHWorld.h"
//extern CPHWorld*	ph_world;
#include "../xrphysics/IPHWorld.h"

SCarLight::SCarLight()
{
	light_render = NULL;
	glow_render = NULL;
	bone_id = BI_NONE;
	offset.set(0.f, 0.f, 0.f);
	m_holder = NULL;
}

SCarLight::~SCarLight()
{
	light_render.destroy();
	glow_render.destroy();
	bone_id = BI_NONE;
}

void SCarLight::Init(CCarLights* holder)
{
	m_holder = holder;
}

void SCarLight::ParseDefinitions(LPCSTR section)
{
	// set bone id
	IKinematics* pKinematics = smart_cast<IKinematics*>(m_holder->PCar()->Visual());
	CInifile* ini = pKinematics->LL_UserData();

	// Definitive Car Pack lights (owner 2026-10-25: spawning one crashed every
	// client): type 1 point, 2 spot, 3 omnipart (other types: point); only a
	// spot has a cone, projector texture or glow. Without type: the old spot.
	const int type = READ_IF_EXISTS(ini, r_s32, section, "type", int(IRender_Light::SPOT));
	const bool spot = type == IRender_Light::SPOT;
	light_render = ::Render->light_create();
	light_render->set_type(spot ? IRender_Light::SPOT : type == IRender_Light::OMNIPART ? IRender_Light::OMNIPART : IRender_Light::POINT);
	light_render->set_shadow(spot);
	if (ini->line_exist(section, "glow_texture")) glow_render = ::Render->glow_create();
	offset = READ_IF_EXISTS(ini, r_fvector3, section, "position", Fvector().set(0.f, 0.f, 0.f));
	//	lanim					= 0;
	//	time2hide				= 0;

	Fcolor clr;
	clr.set(ini->r_fcolor(section, "color"));
	//clr.mul_rgb				(torch->spot_brightness);
	//fBrightness				= torch->spot_brightness;
	light_render->set_range(ini->r_float(section, "range"));
	light_render->set_color(clr);
	// Anomaly/GAMMA vehicles use spot_angle; older car models use cone_angle.
	const LPCSTR angle_key = ini->line_exist(section, "cone_angle") ? "cone_angle" : "spot_angle";
	if (spot) light_render->set_cone(deg2rad(ini->r_float(section, angle_key)));  // a spot needs its angle
	if (ini->line_exist(section, "spot_texture")) light_render->set_texture(ini->r_string(section, "spot_texture"));

	if (glow_render)
	{
		glow_render->set_texture(ini->r_string(section, "glow_texture"));
		glow_render->set_color(clr);
		glow_render->set_radius(READ_IF_EXISTS(ini, r_float, section, "glow_radius", 0.1f));
		glow_render->set_active(false);
	}

	bone_id = pKinematics->LL_BoneID(ini->r_string(section, "bone"));
	light_render->set_active(false);
	pKinematics->LL_SetBoneVisible(bone_id,FALSE,TRUE);

	//lanim					= LALib.FindItem(ini->r_string(section,"animator"));
}

void SCarLight::Switch()
{
	VERIFY(!physics_world()->Processing());
	if (isOn())TurnOff();
	else TurnOn();
}

void SCarLight::TurnOn()
{
	VERIFY(!physics_world()->Processing());
	if (isOn()) return;
	IKinematics* K = smart_cast<IKinematics*>(m_holder->PCar()->Visual());
	K->LL_SetBoneVisible(bone_id,TRUE,TRUE);
	K->CalculateBones_Invalidate();
	K->CalculateBones(TRUE);
	if (glow_render) glow_render->set_active(true);
	light_render->set_active(true);
	Update();
}

void SCarLight::TurnOff()
{
	VERIFY(!physics_world()->Processing());
	if (!isOn()) return;
	if (glow_render) glow_render->set_active(false);
	light_render->set_active(false);
	smart_cast<IKinematics*>(m_holder->PCar()->Visual())->LL_SetBoneVisible(bone_id,FALSE,TRUE);
}

bool SCarLight::isOn()
{
	VERIFY(!physics_world()->Processing());
	VERIFY(!glow_render || light_render->get_active()==glow_render->get_active());
	return light_render->get_active();
}

void SCarLight::Update()
{
	VERIFY(!physics_world()->Processing());
	if (!isOn()) return;
	CCar* pcar = m_holder->PCar();
	CBoneInstance& BI = smart_cast<IKinematics*>(pcar->Visual())->LL_GetBoneInstance(bone_id);
	Fmatrix M;
	M.mul(pcar->XFORM(), BI.mTransform);
	Fvector at;
	M.transform_tiny(at, offset);
	M.c.set(at);
	light_render->set_rotation(M.k, M.i);
	if (glow_render)
	{
		glow_render->set_direction(M.k);
		glow_render->set_position(M.c);
	}
	light_render->set_position(M.c);
}


CCarLights::CCarLights()
{
	m_pcar = NULL;
}

void CCarLights::Init(CCar* pcar)
{
	m_pcar = pcar;
	m_lights.clear();
}

void CCarLights::ParseDefinitions()
{
	CInifile* ini = smart_cast<IKinematics*>(m_pcar->Visual())->LL_UserData();
	if (!ini->section_exist("lights")) return;
	LPCSTR S = READ_IF_EXISTS(ini, r_string, "lights", "headlights", "");  // veh_lada_dead: [lights] without any
	string64 S1;
	int count = _GetItemCount(S);
	for (int i = 0; i < count; ++i)
	{
		_GetItem(S, i, S1);
		m_lights.push_back(xr_new<SCarLight>());
		m_lights.back()->Init(this);
		m_lights.back()->ParseDefinitions(S1);
	}
}

void CCarLights::Update()
{
	VERIFY(!physics_world()->Processing());
	LIGHTS_I i = m_lights.begin(), e = m_lights.end();
	for (; i != e; ++i) (*i)->Update();
}

void CCarLights::SwitchHeadLights()
{
	VERIFY(!physics_world()->Processing());
	LIGHTS_I i = m_lights.begin(), e = m_lights.end();
	for (; i != e; ++i) (*i)->Switch();
}

void CCarLights::TurnOnHeadLights()
{
	VERIFY(!physics_world()->Processing());
	LIGHTS_I i = m_lights.begin(), e = m_lights.end();
	for (; i != e; ++i) (*i)->TurnOn();
}

void CCarLights::TurnOffHeadLights()
{
	VERIFY(!physics_world()->Processing());
	LIGHTS_I i = m_lights.begin(), e = m_lights.end();
	for (; i != e; ++i) (*i)->TurnOff();
}

bool CCarLights::IsLight(u16 bone_id)
{
	SCarLight* light = NULL;
	return findLight(bone_id, light);
}

bool CCarLights::findLight(u16 bone_id, SCarLight* & light)
{
	LIGHTS_I i, e = m_lights.end();
	SCarLight find_light;
	find_light.bone_id = bone_id;
	i = std::find_if(m_lights.begin(), e, SFindLightPredicate(&find_light));
	light = i != e ? *i : nullptr;
	return i != e;
}

CCarLights::~CCarLights()
{
	LIGHTS_I i = m_lights.begin(), e = m_lights.end();
	for (; i != e; ++i) xr_delete(*i);
	m_lights.clear();
}
