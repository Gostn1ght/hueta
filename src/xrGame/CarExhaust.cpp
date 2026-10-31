#include "stdafx.h"
#ifdef DEBUG

#include "PHDebug.h"
#endif
#include "alife_space.h"
#include "hit.h"
#include "PHDestroyable.h"
#include "car.h"
#include "../Include/xrRender/Kinematics.h"
#include "../xrphysics/IPHWorld.h"
//#include "PHWorld.h"
//extern CPHWorld*	ph_world;

/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
CCar::SExhaust::~SExhaust()
{
	CParticlesObject::Destroy(p_pgobject);
}

void CCar::SExhaust::Init()
{
	VERIFY(!physics_world()->Processing());
	const auto exhaust_bone = bone_map.find(bone_id);
	if (exhaust_bone == bone_map.end() || !exhaust_bone->second.element) {
		Msg("! [diag][vehicle] section=%s exhaust bone=%u has no physics element; exhaust disabled", pcar->cNameSect().c_str(), bone_id);
		return;
	}
	pelement = exhaust_bone->second.element;
	IKinematics* K = smart_cast<IKinematics*>(pcar->Visual());
	CBoneData& bone_data = K->LL_GetData(u16(bone_id));
	transform.set(bone_data.bind_transform);
	///transform.mulA(pcar->XFORM());
	//Fmatrix element_transform;
	//pelement->InterpolateGlobalTransform(&element_transform);
	//element_transform.invert();
	//transform.mulA(element_transform);
	LPCSTR effect = *pcar->m_exhaust_particles;
	if (!CParticlesObject::IsAvailable(effect))
	{
		if (g_dedicated_server) return;
		Msg("! [diag][vehicle] section=%s missing exhaust=%s; checking default exhaust", pcar->cNameSect().c_str(), effect ? effect : "<empty>");
		effect = "vehiclefx\\exhaust_1";
		if (!CParticlesObject::IsAvailable(effect)) return;
	}
	p_pgobject = CParticlesObject::Create(effect,FALSE);
	Fvector zero_vector;
	zero_vector.set(0.f, 0.f, 0.f);
	p_pgobject->UpdateParent(pcar->XFORM(), zero_vector);
}

void CCar::SExhaust::Update()
{
	if (!p_pgobject) return;
	VERIFY(!physics_world()->Processing());
	Fmatrix global_transform;
	pelement->InterpolateGlobalTransform(&global_transform);
	global_transform.mulB_43(transform);

	//dVector3 res;
	//Fvector	 res_vel;
	//dBodyGetPointVel(pelement->get_body(),global_transform.c.x,global_transform.c.y,global_transform.c.z,res);
	//CopyMemory (&res_vel,res,sizeof(Fvector));
	Fvector res_vel;
	pelement->GetPointVel(res_vel, global_transform.c);
	//velocity.mul(0.95f);
	//res_vel.mul(0.05f);
	//velocity.add(res_vel);
	p_pgobject->UpdateParent(global_transform, res_vel);
}

void CCar::SExhaust::Clear()
{
	CParticlesObject::Destroy(p_pgobject);
}

void CCar::SExhaust::Play()
{
	if (!p_pgobject) return;
	VERIFY(!physics_world()->Processing());
	p_pgobject->Play(false);
	Update();
}

void CCar::SExhaust::Stop()
{
	if (!p_pgobject) return;
	VERIFY(!physics_world()->Processing());
	p_pgobject->Stop();
}
