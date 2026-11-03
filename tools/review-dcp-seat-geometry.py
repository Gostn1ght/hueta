"""Offline Blender cutaways using the actual game actor, motion and seat matrices.

Run with Blender --background --python this.py -- --addons PATH --actor PATH
  --out PATH --target dcp_zil131:0,1,2 [--target dcp_paz3206:8,9,10,11].
No game process is started and no source mesh is modified.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys

import addon_utils
import bmesh
import bpy
from mathutils import Matrix, Vector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--addons', required=True)
    parser.add_argument('--actor', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--target', action='append', required=True)
    parser.add_argument('--layouts', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    root = Path(__file__).resolve().parents[1]
    overlay = root / 'scripts/netcoop-overlay/client'
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, args.addons)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable('io_scene_xray', default_set=True, persistent=False)
    bpy.ops.xray_import.ogf(directory=str(args.actor.parent),
                           files=[{'name': args.actor.name}], import_motions=False)
    rig = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    spec = importlib.util.spec_from_file_location('poses', root / 'scripts/read-omf-poses.py')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    passenger = reader.Motions(overlay / 'meshes/actors/modded_stalker_animations/netcoop_player_prone.omf', args.actor)
    driver = reader.Motions(overlay / 'meshes/actors/stalker_animation.omf', args.actor)
    convert = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    body_material = bpy.data.materials.new('Actor')
    body_material.diffuse_color = (.19, .56, .85, 1)
    car_material = bpy.data.materials.new('Vehicle')
    car_material.diffuse_color = (.63, .64, .59, 1)
    marker_material = bpy.data.materials.new('Seat origin')
    marker_material.diffuse_color = (1, .15, .04, 1)
    bodies = {}
    for role, source, motion in [('driver', driver, 'steering_idle_0_0'),
                                  ('passenger', passenger, 'lz_vehicle_passenger')]:
        world = {n: convert @ Matrix(m.tolist()) @ convert
                 for n, m in source.pose(motion, .2, matrices=True).items()}
        for bone in sorted(rig.pose.bones, key=lambda b: len(b.parent_recursive)):
            parent = {} if bone.parent is None else dict(
                parent_matrix=world[bone.parent.name],
                parent_matrix_local=bone.parent.bone.matrix_local)
            bone.matrix_basis = bone.bone.convert_local_to_pose(
                world[bone.name], bone.bone.matrix_local, invert=True, **parent)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        bodies[role] = []
        for mesh in meshes:
            data = bpy.data.meshes.new_from_object(mesh.evaluated_get(depsgraph))
            data.materials.clear()
            data.materials.append(body_material)
            bodies[role].append((data, mesh.matrix_world.copy()))
    for obj in [rig, *meshes]:
        obj.hide_render = True
    layouts = json.loads((args.layouts or root / 'tools/dcp-seat-layouts.json').read_text(encoding='utf-8'))
    rows = {r['section']: r for r in json.loads(
        (root / 'docs/audit/169_FLEET_SEATS_AND_DECKS.json').read_text(encoding='utf-8'))['rows']}
    models = {}
    current = None
    for line in (overlay / 'configs/mod_system_lz_dcp_vehicles.ltx').read_text(encoding='cp1251').splitlines():
        if line.startswith('['):
            current = line.split(']')[0][1:]
        elif line.startswith('visual ='):
            models[current] = line.split('=', 1)[1].strip().replace('\\', '/')
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.world = bpy.data.worlds.new('Background')
    scene.world.color = (.07, .07, .07)
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    scene.camera = camera
    for target in args.target:
        section, selected = target.split(':')
        visual = models[section]
        indexes = (list(range(len(layouts[visual]['seats']))) if selected == 'all'
                   else [int(i) for i in selected.split(',')])
        path = overlay / 'meshes' / visual
        before = set(bpy.data.objects)
        bpy.ops.xray_import.ogf(directory=str(path.parent), files=[{'name': path.name}], import_motions=False)
        vehicle = set(bpy.data.objects) - before
        seats = []
        for index in indexes:
            seat = layouts[visual]['seats'][index]
            game = Matrix(rows[section]['seat_matrices_game'][seat['bone']])
            game.translation += Vector(seat['offset'])
            seats.append(convert @ (game @ Matrix.Rotation(math.radians(seat['yaw']), 4, 'Y')) @ convert)
        height = max(s.translation.z for s in seats) + .24
        for obj in vehicle:
            if obj.type != 'MESH':
                continue
            obj.data.materials.clear()
            obj.data.materials.append(car_material)
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bmesh.ops.delete(bm, geom=[f for f in bm.faces
                if all((obj.matrix_world @ v.co).z > height for v in f.verts)], context='FACES')
            bm.to_mesh(obj.data)
            bm.free()
        spawned = []
        actors = []
        for index, seat in zip(indexes, seats):
            for data, base in bodies['driver' if index == 0 else 'passenger']:
                obj = bpy.data.objects.new('Actor seat ' + str(index), data)
                scene.collection.objects.link(obj)
                obj.matrix_world = seat @ base
                actors.append(obj)
                spawned.append(obj)
            bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=.045,
                                               location=seat.translation)
            obj = bpy.context.object
            obj.data.materials.append(marker_material)
            spawned.append(obj)
            bpy.ops.object.text_add(location=seat.translation + Vector((-.1, 0, .05)))
            label = bpy.context.object
            label.data.body = str(index)
            label.data.size = .16
            spawned.append(label)
        center = sum((s.translation for s in seats), Vector()) / len(seats)
        width = max(s.translation.x for s in seats) - min(s.translation.x for s in seats)
        depth = max(s.translation.y for s in seats) - min(s.translation.y for s in seats)
        camera.data.ortho_scale = max(3.8, width + 1.6, (depth + 1.8) * 4 / 3)
        for view, direction in [('top', (0, -.01, 8)), ('front', (4, 7, 5))]:
            camera.location = center + Vector(direction)
            camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
            for with_actors in (False, True):
                for actor in actors:
                    actor.hide_render = not with_actors
                scene.render.filepath = str(args.out / f'{section}-{view}-{"actors" if with_actors else "mesh"}.png')
                bpy.ops.render.render(write_still=True)
        for obj in [*spawned, *vehicle]:
            bpy.data.objects.remove(obj, do_unlink=True)
        print('REVIEWED', section, indexes, flush=True)


if __name__ == '__main__':
    main()
