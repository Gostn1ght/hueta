"""Choose an outward Blender preview hinge, not the ODE limit's raw sign.

ODE joint angles and a pose bone's Euler sign are not interchangeable.
This helper changes only an offline preview; it never edits a game model.
"""
import bpy
from mathutils import Vector


def outward_hinge(rig, meshes, door):
    limits = [(getattr(door.bone.xray.ikjoint, 'lim_' + a + '_min'),
               getattr(door.bone.xray.ikjoint, 'lim_' + a + '_max')) for a in 'xyz']
    axis = max(range(3), key=lambda i: limits[i][1] - limits[i][0])
    magnitude = max(abs(v) for v in limits[axis])
    assert magnitude > .3, ('Door has no usable hinge', door.name, limits)
    weighted = []
    for obj in meshes:
        group = obj.vertex_groups.get(door.name)
        if group:
            indices = [v.index for v in obj.data.vertices
                       if any(g.group == group.index and g.weight > .5 for g in v.groups)]
            if indices:
                weighted.append((obj, indices))
    assert weighted, ('No skin weighted to door', door.name)
    door.rotation_mode = 'XYZ'

    def centre(angle):
        door.rotation_euler = (0, 0, 0)
        door.rotation_euler[axis] = angle
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        points = []
        for obj, indices in weighted:
            evaluated = obj.evaluated_get(deps)
            mesh = evaluated.to_mesh()
            points.extend(evaluated.matrix_world @ mesh.vertices[i].co for i in indices)
            evaluated.to_mesh_clear()
        return sum(points, Vector()) / len(points)

    closed = centre(0)
    side = -1 if closed.x < rig.matrix_world.translation.x else 1
    trials = [(angle, centre(angle)) for angle in (-magnitude, magnitude)]
    angle, opened = max(trials, key=lambda row: side * row[1].x)
    assert side * (opened.x - closed.x) > .05, ('Door preview fails outward travel', door.name)
    centre(0)
    return axis, angle, dict(closed_centre=list(closed), open_centre=list(opened),
                            outward_side=side, outward_travel=side * (opened.x - closed.x))
