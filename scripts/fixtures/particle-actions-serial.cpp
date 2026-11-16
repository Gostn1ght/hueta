// Frozen pre-parallel Execute bodies from5e94308d9; CI reference only.
void PACopyVertexB::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	u32 i;

	if (copy_pos)
	{
		for (i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];
			m.posB = m.pos;
		}
	}
	/*	
		if(copy_vel)
		{
			for(i = 0; i < effect->p_count; i++)
			{
				Particle &m = effect->particles[i];
				m.velB = m.vel;
			}
		}
	*/
}

void PADamping::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	// This is important if dt is != 1.
	pVector one(1, 1, 1);
	pVector scale(one - ((one - damping) * dt));

	for (u32 i = 0; i < effect->p_count; i++)
	{
		Particle& m = effect->particles[i];
		float vSqr = m.vel.length2();

		if (vSqr >= vlowSqr && vSqr <= vhighSqr)
		{
			m.vel.x *= scale.x;
			m.vel.y *= scale.y;
			m.vel.z *= scale.z;
		}
	}
}

void PAExplosion::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float radius = velocity * age;
	float magdt = magnitude * dt;
	float oneOverSigma = 1.0f / stdev;
	float inexp = -0.5f * _sqr(oneOverSigma);
	float outexp = ONEOVERSQRT2PI * oneOverSigma;

	for (u32 i = 0; i < effect->p_count; i++)
	{
		Particle& m = effect->particles[i];

		// Figure direction to particle.
		pVector dir(m.pos - center);
		float distSqr = dir.length2();
		float dist = _sqrt(distSqr);
		float DistFromWaveSqr = _sqr(radius - dist);

		float Gd = expf(DistFromWaveSqr * inexp) * outexp;

		m.vel += dir * (Gd * magdt / ((dist + EPS) * (distSqr + epsilon)));
	}

	age += dt;
}

void PAGravity::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	pVector ddir(direction * dt);

	for (u32 i = 0; i < effect->p_count; i++)
	{
		// Step velocity with acceleration
		effect->particles[i].vel += ddir;
	}
}

void PAScatter::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float magdt = magnitude * dt;
	float max_radiusSqr = max_radius * max_radius;

	if (max_radiusSqr < P_MAXFLOAT)
	{
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Figure direction to particle.
			pVector dir(m.pos - center);

			// Distance to jet (force drops as 1/r^2)
			// Soften by epsilon to avoid tight encounters to infinity
			float rSqr = dir.length2();

			if (rSqr < max_radiusSqr)
			{
				pVector accel;
				accel = dir / _sqrt(rSqr);

				//				acc.Generate(accel);

				// Step velocity with acceleration
				m.vel += accel * (magdt / (rSqr + epsilon));
			}
		}
	}
	else
	{
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Figure direction to particle.
			pVector dir(m.pos - center);

			// Distance to jet (force drops as 1/r^2)
			// Soften by epsilon to avoid tight encounters to infinity
			float rSqr = dir.length2();

			pVector accel;
			accel = dir / _sqrt(rSqr);

			// Step velocity with acceleration
			m.vel += accel * (magdt / (rSqr + epsilon));
		}
	}
}

void PAMove::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	// Step particle positions forward by dt, and age the particles.
	for (u32 i = 0; i < effect->p_count; i++)
	{
		Particle& m = effect->particles[i];
		// move
		m.age += dt;
		m.posB = m.pos;
		//        m.velB 	= m.vel;
		m.pos += m.vel * dt;
	}
}

void PAOrbitLine::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float magdt = magnitude * dt;
	float max_radiusSqr = max_radius * max_radius;

	if (max_radiusSqr < P_MAXFLOAT)
	{
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Figure direction to particle from base of line.
			pVector f(m.pos - p);

			pVector w(axis * (f * axis));

			// Direction from particle to nearest point on line.
			pVector into = w - f;

			// Distance to line (force drops as 1/r^2, normalize by 1/r)
			// Soften by epsilon to avoid tight encounters to infinity
			float rSqr = into.length2();

			if (rSqr < max_radiusSqr)
				// Step velocity with acceleration
				m.vel += into * (magdt / (_sqrt(rSqr) + (rSqr + epsilon)));
		}
	}
	else
	{
		// Removed because it causes pipeline stalls.
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Figure direction to particle from base of line.
			pVector f(m.pos - p);

			pVector w(axis * (f * axis));

			// Direction from particle to nearest point on line.
			pVector into = w - f;

			// Distance to line (force drops as 1/r^2, normalize by 1/r)
			// Soften by epsilon to avoid tight encounters to infinity
			float rSqr = into.length2();

			// Step velocity with acceleration
			m.vel += into * (magdt / (_sqrt(rSqr) + (rSqr + epsilon)));
		}
	}
}

void PAOrbitPoint::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float magdt = magnitude * dt;
	float max_radiusSqr = max_radius * max_radius;

	if (max_radiusSqr < P_MAXFLOAT)
	{
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Figure direction to particle.
			pVector dir(center - m.pos);

			// Distance to gravity well (force drops as 1/r^2, normalize by 1/r)
			// Soften by epsilon to avoid tight encounters to infinity
			float rSqr = dir.length2();

			// Step velocity with acceleration
			if (rSqr < max_radiusSqr)
				m.vel += dir * (magdt / (_sqrt(rSqr) + (rSqr + epsilon)));
		}
	}
	else
	{
		// Avoids pipeline stalls.
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Figure direction to particle.
			pVector dir(center - m.pos);

			// Distance to gravity well (force drops as 1/r^2, normalize by 1/r)
			// Soften by epsilon to avoid tight encounters to infinity
			float rSqr = dir.length2();

			// Step velocity with acceleration
			m.vel += dir * (magdt / (_sqrt(rSqr) + (rSqr + epsilon)));
		}
	}
}

void PARestore::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	if (time_left <= 0)
	{
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Already constrained, keep it there.
			m.pos = m.posB;
			m.vel = pVector(0, 0, 0);
		}
	}
	else
	{
		float t = time_left;
		float dtSqr = dt * dt;
		float tSqrInv2dt = dt * 2.0f / (t * t);
		float tCubInv3dtSqr = dtSqr * 3.0f / (t * t * t);

		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Solve for a desired-behavior velocity function in each axis
			// _pconstrain(m.pos.x, m.vel.x, m.posB.x, 0., timeLeft, &a, &b, &c);

			// Figure new velocity at next timestep
			// m.vel.x = a * dtSqr + b * dt + c;

			float b = (-2 * t * m.vel.x + 3 * m.posB.x - 3 * m.pos.x) * tSqrInv2dt;
			float a = (t * m.vel.x - m.posB.x - m.posB.x + m.pos.x + m.pos.x) * tCubInv3dtSqr;

			// Figure new velocity at next timestep
			m.vel.x += a + b;

			b = (-2 * t * m.vel.y + 3 * m.posB.y - 3 * m.pos.y) * tSqrInv2dt;
			a = (t * m.vel.y - m.posB.y - m.posB.y + m.pos.y + m.pos.y) * tCubInv3dtSqr;

			// Figure new velocity at next timestep
			m.vel.y += a + b;

			b = (-2 * t * m.vel.z + 3 * m.posB.z - 3 * m.pos.z) * tSqrInv2dt;
			a = (t * m.vel.z - m.posB.z - m.posB.z + m.pos.z + m.pos.z) * tCubInv3dtSqr;

			// Figure new velocity at next timestep
			m.vel.z += a + b;
		}
	}

	time_left -= dt;
}

void PASpeedLimit::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float min_sqr = min_speed * min_speed;
	float max_sqr = max_speed * max_speed;

	for (u32 i = 0; i < effect->p_count; i++)
	{
		Particle& m = effect->particles[i];
		float sSqr = m.vel.length2();
		if (sSqr < min_sqr && sSqr)
		{
			float s = _sqrt(sSqr);
			m.vel *= (min_speed / s);
		}
		else if (sSqr > max_sqr)
		{
			float s = _sqrt(sSqr);
			m.vel *= (max_speed / s);
		}
	}
}

void PATargetColor::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{	

	float COEFF = STEP_DEFAULT / dt;
	float scaleFac = scale * STEP_DEFAULT;
	Fcolor c_p, c_t, c_n;

	for (u32 i = 0; i < effect->p_count; i++)
	{
		Particle& m = effect->particles[i];
		if (m.age < timeFrom * tm_max || m.age > timeTo * tm_max) continue;

		c_p.set(m.colorR, m.colorG, m.colorB, m.colorA);
		c_t.set(color.x, color.y, color.z, alpha);
		c_n.lerp(c_p, c_t, scaleFac);
		c_n.set(c_n.get());

		m.colorR -= (m.colorR - c_n.r) / COEFF;
		m.colorG -= (m.colorG - c_n.g) / COEFF;
		m.colorB -= (m.colorB - c_n.b) / COEFF;
		m.colorA -= (m.colorA - c_n.a) / COEFF;
	}
}

void PATargetSize::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float scaleFac_x = scale.x * dt;
	float scaleFac_y = scale.y * dt;
	float scaleFac_z = scale.z * dt;

	for (u32 i = 0; i < effect->p_count; i++)
	{
		Particle& m = effect->particles[i];
		pVector dif(size - m.size);
		dif.x *= scaleFac_x;
		dif.y *= scaleFac_y;
		dif.z *= scaleFac_z;
		m.size += dif;
	}
}

void PATargetRotate::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float scaleFac = scale * dt;

	float r = _abs(rot.x);

	for (u32 i = 0; i < effect->p_count; i++)
	{
		Particle& m = effect->particles[i];
		float sign = m.rot.x >= 0.f ? scaleFac : -scaleFac;
		float dif = (r - _abs(m.rot.x)) * sign;
		m.rot.x += dif;
	}
}

void PATargetVelocity::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float scaleFac = scale * dt;

	for (u32 i = 0; i < effect->p_count; i++)
	{
		Particle& m = effect->particles[i];
		m.vel += (velocity - m.vel) * scaleFac;
	}
}

void PAVortex::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
	float magdt = magnitude * dt;
	float max_radiusSqr = max_radius * max_radius;

	if (max_radiusSqr < P_MAXFLOAT)
	{
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Vector from tip of vortex
			pVector offset(m.pos - center);

			// Compute distance from particle to tip of vortex.
			float rSqr = offset.length2();

			// Don't do anything to particle if too close or too far.
			if (rSqr > max_radiusSqr)
				continue;

			float r = _sqrt(rSqr);

			// Compute normalized offset vector3.
			pVector offnorm(offset / r);

			// Construct orthogonal vector3 frame in which to rotate
			// transformed point around origin
			float axisProj = offnorm * axis; // offnorm . axis

			// Components of offset perpendicular and parallel to axis
			pVector w(axis * axisProj); // parallel component
			pVector u(offnorm - w); // perpendicular component

			// Perpendicular component completing frame:
			pVector v(axis ^ u);

			// Figure amount of rotation
			// Resultant is (cos theta) u + (sin theta) v
			float theta = magdt / (rSqr + epsilon);
			float s = _sin(theta);
			float c = _cos(theta);

			offset = (u * c + v * s + w) * r;

			// Translate back to object space
			m.pos = offset + center;
		}
	}
	else
	{
		for (u32 i = 0; i < effect->p_count; i++)
		{
			Particle& m = effect->particles[i];

			// Vector from tip of vortex
			pVector offset(m.pos - center);

			// Compute distance from particle to tip of vortex.
			float rSqr = offset.length2();

			float r = _sqrt(rSqr);

			// Compute normalized offset vector3.
			pVector offnorm(offset / r);

			// Construct orthogonal vector3 frame in which to rotate
			// transformed point around origin
			float axisProj = offnorm * axis; // offnorm . axis

			// Components of offset perpendicular and parallel to axis
			pVector w(axis * axisProj); // parallel component
			pVector u(offnorm - w); // perpendicular component

			// Perpendicular component completing frame:
			pVector v(axis ^ u);

			// Figure amount of rotation
			// Resultant is (cos theta) u + (sin theta) v
			float theta = magdt / (rSqr + epsilon);
			float s = _sin(theta);
			float c = _cos(theta);

			offset = (u * c + v * s + w) * r;

			// Translate back to object space
			m.pos = offset + center;
		}
	}
}

void PATurbulence::Execute(ParticleEffect* effect, const float dt, float& tm_max)
{
#ifdef _GPA_ENABLED
		TAL_SCOPED_TASK_NAMED( "PATurbulence::Execute()" );
#endif // _GPA_ENABLED

	if (noise_start)
	{
		noise_start = 0;
		noise3Init();
	};

	age += dt;

	u32 p_cnt = effect->p_count;

	if (! p_cnt)
		return;

	pVector pV;
	pVector vX;
	pVector vY;
	pVector vZ;

	for (u32 i = 0; i != p_cnt; ++i)
	{
		Particle& m = effect->particles[i];

		pV.mad(m.pos, offset, age);
		vX.set(pV.x + epsilon, pV.y, pV.z);
		vY.set(pV.x, pV.y + epsilon, pV.z);
		vZ.set(pV.x, pV.y, pV.z + epsilon);

		const float d = fractalsum3(pV, frequency, octaves);

		pVector D;
		D.x = fractalsum3(vX, frequency, octaves);
		D.y = fractalsum3(vY, frequency, octaves);
		D.z = fractalsum3(vZ, frequency, octaves);

		__m128 _D = _mm_load_fvector(D);
		__m128 _d = _mm_set1_ps(d);
		__m128 _magnitude = _mm_set1_ps(magnitude * ps_particle_update_coeff);
		__m128 _mvel = _mm_load_fvector(m.vel);
		_D = _mm_sub_ps(_D, _d);
		_D = _mm_mul_ps(_D, _magnitude);

		__m128 _vmo = _mm_mul_ps(_mvel, _mvel); // _vmo = 00 | zz | yy | xx
		__m128 _tmp = _mm_movehl_ps(_vmo, _vmo); // _tmp = 00 | zz | 00 | zz 
		_vmo = _mm_add_ss(_vmo, _tmp); // _vmo = 00 | zz | yy | xx + zz
		_tmp = _mm_unpacklo_ps(_vmo, _vmo); // _tmp = yy | yy | xx + zz | xx + zz
		_tmp = _mm_movehl_ps(_tmp, _tmp); // _tmp = yy | yy | yy | yy 
		_vmo = _mm_add_ss(_vmo, _tmp); // _vmo = 00 | zz | yy | xx + yy + zz
		_vmo = _mm_sqrt_ss(_vmo); // _vmo = 00 | zz | yy | vmo

		_mvel = _mm_add_ps(_mvel, _D);

		__m128 _vmn = _mm_mul_ps(_mvel, _mvel); // _vmn = 00 | zz | yy | xx
		_tmp = _mm_movehl_ps(_vmn, _vmn); // _tmp = 00 | zz | 00 | zz 
		_vmn = _mm_add_ss(_vmn, _tmp); // _vmn = 00 | zz | yy | xx + zz
		_tmp = _mm_unpacklo_ps(_vmn, _vmn); // _tmp = yy | yy | xx + zz | xx + zz
		_tmp = _mm_movehl_ps(_tmp, _tmp); // _tmp = yy | yy | yy | yy 
		_vmn = _mm_add_ss(_vmn, _tmp); // _vmn = 00 | zz | yy | xx + yy + zz
		_vmn = _mm_sqrt_ss(_vmn); // _vmn = 00 | zz | yy | vmn

		_vmo = _mm_div_ss(_vmo, _vmn); // _vmo = 00 | zz | yy | scale

		_vmo = _mm_shuffle_ps(_vmo, _vmo, _MM_SHUFFLE(0, 0, 0, 0)); // _vmo = scale | scale | scale | scale
		_mvel = _mm_mul_ps(_mvel, _vmo);

		_mm_store_fvector(m.vel, _mvel);
	}
}
