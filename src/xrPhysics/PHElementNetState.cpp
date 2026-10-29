#include "StdAfx.h"
#include "physicsshell.h"
#include "phinterpolation.h"
#include "phelement.h"
#include "phobject.h"
#include "phworld.h"
#include "phshell.h"
#include "../Include/xrRender/Kinematics.h"

void CPHElement::get_State(SPHNetState& state)
{
	if (!isActive())
	{
		// ClosingToClosed destroys a door body. Export its current animated
		// pose, never stale interpolation buffers or uninitialised packet data.
		Fmatrix form;
		IKinematics* K = m_shell ? m_shell->PKinematics() : nullptr;
		if (K)
			form.mul_43(m_shell->mXFORM, K->LL_GetTransform(m_SelfID));
		else
			form.set(mXFORM);
		form.transform_tiny(state.position, m_mass_center);
		state.quaternion.set(form);
		state.previous_position = state.position;
		state.previous_quaternion = state.quaternion;
		state.linear_vel.set(0.f, 0.f, 0.f);
		state.angular_vel.set(0.f, 0.f, 0.f);
		state.force.set(0.f, 0.f, 0.f);
		state.torque.set(0.f, 0.f, 0.f);
		state.enabled = false;
		return;
	}
	GetGlobalPositionDynamic(&state.position);
	getQuaternion(state.quaternion);
	m_body_interpolation.GetPosition(state.previous_position, 0);
	m_body_interpolation.GetRotation(state.previous_quaternion, 0);
	get_LinearVel(state.linear_vel);
	get_AngularVel(state.angular_vel);
	getForce(state.force);
	getTorque(state.torque);
	state.enabled = !!dBodyIsEnabled(m_body);
}

void CPHElement::set_State(const SPHNetState& state)
{
	// The skeleton owns inactive parts; their interpolation still points at
	// the body destroyed on closing. Reopening creates fresh interpolation.
	if (!isActive()) return;
	//bUpdate=true;
	m_flags.set(flUpdate,TRUE);
	SetGlobalPositionDynamic(state.position);
	setQuaternion(state.quaternion);
	m_body_interpolation.SetPosition(state.previous_position, 0);
	m_body_interpolation.SetRotation(state.previous_quaternion, 0);
	m_body_interpolation.SetPosition(state.position, 1);
	m_body_interpolation.SetRotation(state.quaternion, 1);
	set_LinearVel(state.linear_vel);
	set_AngularVel(state.angular_vel);
	setForce(state.force);
	setTorque(state.torque);
	if (!isActive()) return;
#if 1
	if (state.enabled && !dBodyIsEnabled(m_body))
	{
		dBodyEnable(m_body);
		m_shell->EnableObject(0);
	}
	if (!state.enabled && dBodyIsEnabled(m_body))
	{
		m_shell->DisableObject();
		Disable();
	}
#endif
	CPHDisablingFull::Reinit();
	m_flags.set(flUpdate,TRUE);
}

void CPHElement::net_Export(NET_Packet& P)
{
	SPHNetState state;
	get_State(state);
	state.net_Export(P);
}

void CPHElement::net_Import(NET_Packet& P)
{
	SPHNetState state;
	state.net_Import(P);
	set_State(state);
}
