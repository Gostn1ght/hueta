#pragma once
#include <algorithm>
#include <cmath>

// Explicit -k*w torque reverses tiny bodies within one step and injects
// energy. Bound the coefficient by a lower bound on the inertia eigenvalues.
// I uses ODE's padded 3x4 body-space layout; isotropic torque is basis invariant.
template<class Real>
Real stable_angular_drag(Real requested, const Real* inertia, Real step)
{
    if (!std::isfinite(requested) || !std::isfinite(step) || requested <= 0 || step <= 0) return Real(0);
    const double a=inertia[0], b=inertia[1], c=inertia[2];
    const double d=inertia[5], e=inertia[6], f=inertia[10];
    const double determinant=a*(d*f-e*e)-b*(b*f-c*e)+c*(b*e-c*d);
    const double trace=a+d+f;
    if (!std::isfinite(determinant) || !std::isfinite(trace) || a<=0 || a*d-b*b<=0 || determinant<=0) return Real(0);
    const double gersh=std::min({a-std::abs(b)-std::abs(c),d-std::abs(b)-std::abs(e),f-std::abs(c)-std::abs(e)});
    // det(I)/tr(I)^2 is positive and below the smallest eigenvalue for SPD I.
    const double lower=std::max(gersh,determinant/(trace*trace));
    const double coefficient=double(requested)*lower/(lower+double(step)*double(requested));
    return std::isfinite(coefficient) ? Real(coefficient) : Real(0);
}
