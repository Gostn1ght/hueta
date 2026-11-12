"""Offline all-key skin/vehicle intersections for a fitted entry/exit candidate.

Run in background Blender; no renderer, installation or game process is used.
Reports failures rather than treating export roundtrip as collision clearance.
"""
from collections import Counter
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import addon_utils
import bpy
from mathutils import Matrix
from mathutils.bvhtree import BVHTree

p = argparse.ArgumentParser(description=__doc__)
for key in ('actor', 'addons', 'candidate', 'out'):
    p.add_argument('--' + key, type=Path, required=True)
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
a.out.mkdir(parents=True, exist_ok=False)
root = Path(__file__).resolve().parents[1]
overlay = root / 'scripts/netcoop-overlay/client'
review = json.loads((a.candidate.parent / 'review.json').read_text())
assert hashlib.sha256(a.candidate.read_bytes()).hexdigest() == review['candidate_sha256']
spec = importlib.util.spec_from_file_location('poses', root / 'scripts/read-omf-poses.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
sys.path.insert(0, str(a.addons))
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray', default_set=True, persistent=False)
bpy.ops.xray_import.ogf(directory=str(a.actor.parent), files=[{'name': a.actor.name}], import_motions=False)
actor = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
skin = [o for o in bpy.data.objects if o.type == 'MESH']
order = sorted(actor.pose.bones, key=lambda b: len(b.parent_recursive))
for bone in order:
    for constraint in list(bone.constraints):
        bone.constraints.remove(constraint)
section = None
for line in (overlay / 'configs/mod_system_lz_dcp_vehicles.ltx').read_text(encoding='cp1251').splitlines():
    if line.startswith('['):
        section = line.split(']')[0][1:]
    elif section == review['section'] and line.startswith('visual ='):
        visual = line.split('=', 1)[1].strip().replace('\\', '/')
model = overlay / 'meshes' / visual
assert hashlib.sha256(model.read_bytes()).hexdigest() == review['model_sha256']
layout = json.loads((root / 'tools/dcp-seat-layouts.json').read_text(encoding='utf-8'))[visual]['seats'][review['seat']]
fleet = json.loads((root / 'docs/audit/169_FLEET_SEATS_AND_DECKS.json').read_text())['rows']
row = next(r for r in fleet if r['section'] == review['section'])
import math
seat = Matrix(row['seat_matrices_game'][layout['bone']])
from mathutils import Vector
seat.translation += Vector(layout['offset'])
c = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
s = Matrix.Diagonal((1, 1, -1, 1))
actor.matrix_world = c @ (seat @ Matrix.Rotation(math.radians(layout['yaw']), 4, 'Y')) @ c
before = set(bpy.data.objects)
bpy.ops.xray_import.ogf(directory=str(model.parent), files=[{'name': model.name}], import_motions=False)
car_objects = set(bpy.data.objects) - before
car = next(o for o in car_objects if o.type == 'ARMATURE')
car_skin = [o for o in car_objects if o.type == 'MESH']
door = car.pose.bones.get(review['door']) if review['door'] else None
if door:
    limits = [(getattr(door.bone.xray.ikjoint, 'lim_' + axis + '_min'), getattr(door.bone.xray.ikjoint, 'lim_' + axis + '_max')) for axis in 'xyz']
    axis = max(range(3), key=lambda i: limits[i][1] - limits[i][0])
    angle = max(limits[axis], key=abs)
    door.rotation_mode = 'XYZ'

tag_cache = {}

def tree(objects):
    vertices, triangles, tags = [], [], []
    deps = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        evaluated = obj.evaluated_get(deps)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        offset = len(vertices)
        if obj.name not in tag_cache:
            groups = {g.index: g.name for g in obj.vertex_groups}
            vertex_tags = [groups[max(v.groups, key=lambda g: g.weight).group] if v.groups else obj.name for v in obj.data.vertices]
            tag_cache[obj.name] = [Counter(vertex_tags[i] for i in tri.vertices).most_common(1)[0][0] for tri in mesh.loop_triangles]
        assert len(tag_cache[obj.name]) == len(mesh.loop_triangles)
        tags.extend(tag_cache[obj.name])
        vertices.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
        triangles.extend(tuple(offset + i for i in tri.vertices) for tri in mesh.loop_triangles)
        evaluated.to_mesh_clear()
    return BVHTree.FromPolygons(vertices, triangles, all_triangles=True), min(v.z for v in vertices), tags

def smooth(t):
    t = max(0, min(1, t))
    return t * t * (3 - 2 * t)

motions = reader.Motions(a.candidate, a.actor)
samples = []
for clip in review['motions']:
    for frame in range(clip['frames']):
        t = frame / (clip['frames'] - 1)
        world = {n: c @ Matrix(m.tolist()) @ s for n, m in motions.pose(clip['motion'], frame / clip['frames'], matrices=True).items()}
        for bone in order:
            kwargs = {} if bone.parent is None else dict(parent_matrix=world[bone.parent.name], parent_matrix_local=bone.parent.bone.matrix_local)
            bone.matrix_basis = bone.bone.convert_local_to_pose(world[bone.name], bone.bone.matrix_local, invert=True, **kwargs)
        if door:
            lead=clip.get('door_lead_frames');trail=clip.get('door_trail_frames')
            opened=smooth(frame/lead)*(1-smooth((frame-(lead+clip['source_frames']-1))/trail)) if lead and trail else smooth(t/.2)*(1-smooth((t-.85)/.15))
            door.rotation_euler[axis] = angle * opened
        bpy.context.view_layer.update()
        body, floor, body_tags = tree(skin)
        vehicle, _, vehicle_tags = tree(car_skin)
        pairs = body.overlap(vehicle)
        regions = Counter(body_tags[i] + ' / ' + vehicle_tags[j] for i, j in pairs)
        samples.append(dict(motion=clip['motion'], frame=frame, intersection_pairs=len(pairs), intersections_by_bones=dict(regions), skin_floor_metres=floor - float(row['visual_bounds_blender'][0][2])))
        if frame % 30 == 0:
            print('ENTRY_KEY', clip['motion'], frame, len(pairs), flush=True)
result = dict(installed=False, candidate_sha256=hashlib.sha256(a.candidate.read_bytes()).hexdigest(), model_sha256=review['model_sha256'], actor_sha256=hashlib.sha256(a.actor.read_bytes()).hexdigest(), tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), samples=samples)
result['collision_free'] = all(r['intersection_pairs'] == 0 for r in samples)
result['floor_clear'] = all(r['skin_floor_metres'] >= -.01 for r in samples)
(a.out / 'clearance.json').write_text(json.dumps(result, indent=2) + '\n')
print('ENTRY_CLEARANCE', len(samples), result['collision_free'], result['floor_clear'], max(r['intersection_pairs'] for r in samples), flush=True)
