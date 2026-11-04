#pragma once
#include <algorithm>
#include <cmath>

namespace netcoop_vehicle_dynamics
{
// Automatic launch clutch for manual gears without a separate clutch pedal.
// Retains the donor torque curve and gear ratio; supplies no external force.
inline float clutch_rpm(float wheel_rpm, bool pulling, float idle, float peak, float maximum)
{
    if (!pulling || !std::isfinite(wheel_rpm) || !std::isfinite(idle) ||
        !std::isfinite(peak) || !std::isfinite(maximum) || idle <= 0.f || maximum < idle)
        return wheel_rpm;
    const float launch = std::min(maximum, std::max(idle * 1.25f, peak * .75f));
    return std::max(wheel_rpm, launch);
}

inline float engine_torque(float power, float rpm)
{
    if (!std::isfinite(power) || !std::isfinite(rpm) || rpm <= .0001f || power <= 0.f)
        return 0.f;
    return power / rpm;
}

// A single solver step below idle is not a stalled engine. Only a sustained
// heavily loaded clutch can stall it; a long rendered frame adds no more
// than one bounded physics interval. Fuel/overload shutoffs remain separate.
inline bool stall_due(bool multiplayer, bool engine, bool starting, bool governed,
    bool clutch, bool neutral, float rpm, float idle, float step, float& low_seconds)
{
    const bool below = engine && !starting && !governed && rpm < idle;
    if (!multiplayer) { low_seconds = 0.f; return below; }
    if (!below || !clutch || neutral || !std::isfinite(rpm) || !std::isfinite(idle) ||
        idle <= 0.f || rpm >= idle * .65f || !std::isfinite(step) || step <= 0.f)
    {
        low_seconds = 0.f;
        return false;
    }
    low_seconds += std::min(step, .1f);
    return low_seconds >= .75f;
}

// The stock donor torque is not scaled for a loaded truck. M*g*r / N is a
// conservative holding torque per braking wheel, in N m. It brakes the real
// wheel joint; it never fixes a shell, cancels velocity or adds a ground force.
inline float parking_torque(bool multiplayer, float configured, float mass,
    float gravity, float radius, unsigned wheels)
{
    if (!multiplayer || !wheels || !std::isfinite(mass) || mass <= 0.f ||
        !std::isfinite(gravity) || gravity <= 0.f || !std::isfinite(radius) || radius <= 0.f)
        return configured;
    const double holding = double(mass) * gravity * radius / wheels;
    if (!std::isfinite(holding) || holding > 1.e8) return configured;
    return std::max(configured, float(holding));
}
}
