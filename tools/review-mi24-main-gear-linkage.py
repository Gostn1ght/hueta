"""Offline linkage study, not a replacement model or a released gear animation.

Coordinates match reference_main_gear_171 in Blender metres. The pyramid
rotates about BOTH fuselage attachments. The shock has a fixed upper end and
a moving axle end; it must telescope independently, never rotate with the
whole pyramid. Requires only Python; does not start Blender or the game.
"""
import argparse
import json
import math
from pathlib import Path


def add(a, b): return tuple(x + y for x, y in zip(a, b))
def sub(a, b): return tuple(x - y for x, y in zip(a, b))
def scale(a, s): return tuple(x * s for x in a)
def dot(a, b): return sum(x * y for x, y in zip(a, b))
def length(a): return math.sqrt(dot(a, a))
def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def rotate(point, pivot, axis, angle):
    v = sub(point, pivot)
    axis = scale(axis, 1 / length(axis))
    co, si = math.cos(angle), math.sin(angle)
    return add(pivot, add(add(scale(v, co), scale(cross(axis, v), si)),
                          scale(axis, dot(axis, v) * (1-co))))


def study(angle_degrees, frames):
    sides = {}
    for sign, name in ((-1, 'left'), (1, 'right')):
        a = (sign*.4255, -.4512, .9531)
        b = (sign*.4745, -1.6591, .2469)
        d = (sign*.94, -2.35, 1.24)
        wheel = (sign*1.515, -1.984, -.16)
        axle = add(wheel, (-sign*.16, 0, 0))
        axis = sub(b, a)
        # Mirror the angle as well as the points, preserving bilateral motion.
        angle = math.radians(angle_degrees) * sign
        rows = []
        invariant_error = 0.
        for i in range(frames):
            t = i / (frames-1)
            phase = t*t*(3-2*t)
            c = rotate(axle, a, axis, angle*phase)
            w = rotate(wheel, a, axis, angle*phase)
            shock = sub(c, d)
            invariant_error = max(invariant_error,
                abs(length(sub(c, a))-length(sub(axle, a))),
                abs(length(sub(c, b))-length(sub(axle, b))),
                length(sub(rotate(b, a, axis, angle*phase), b)),
                abs(length(sub(c, w))-.16))
            rows.append(dict(phase=t, axle=c, wheel_centre=w,
                             shock_length=length(shock),
                             shock_direction=scale(shock, 1/length(shock)),
                             wheel_axle_direction=scale(sub(w, c), 1/.16)))
        assert invariant_error < 1e-9, invariant_error
        lengths = [r['shock_length'] for r in rows]
        sides[name] = dict(attachment_a=a, attachment_b=b, shock_upper=d,
            hinge_axis=scale(axis, 1/length(axis)), samples=rows,
            maximum_rigid_length_error_metres=invariant_error,
            required_shock_stroke_metres=max(lengths)-min(lengths),
            shock_length_range_metres=[min(lengths), max(lengths)],
            inward_travel_metres=sign*(wheel[0]-rows[-1]['wheel_centre'][0]),
            upward_travel_metres=rows[-1]['wheel_centre'][2]-wheel[2])
    for l, r in zip(sides['left']['samples'], sides['right']['samples']):
        assert length(sub(l['wheel_centre'], (-r['wheel_centre'][0], *r['wheel_centre'][1:]))) < 1e-9
    return dict(installed=False, status='kinematic study; well clearance and real stroke limits unverified',
                fold_angle_degrees=angle_degrees, frames=frames, sides=sides)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--angle', type=float, default=65.)
    parser.add_argument('--frames', type=int, default=121)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.angle) or not 0 < abs(args.angle) <= 120 or not 3 <= args.frames <= 1001:
        parser.error('angle must be finite, nonzero and within 120 degrees; frames 3..1001')
    result = study(args.angle, args.frames)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps({side: {k: v for k, v in row.items() if k != 'samples'}
                      for side, row in result['sides'].items()}, indent=2))
