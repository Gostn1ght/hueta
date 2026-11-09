"""Offline actual actor/OMF review, optionally with a real weapon and its LTX offsets.

Blender --background --python this.py -- --actor ACTOR --addons ADDONS
 --omf CANDIDATE --motion NAME --out DIRECTORY [--weapon-ltx FILE --meshes DIR]
Weapon transform follows CWeapon::UpdateXForm's finger anchors. No game starts.
"""
import argparse
import importlib.util
import math
from pathlib import Path
import re
import sys

import addon_utils
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

p = argparse.ArgumentParser(description=__doc__)
for name in ('actor', 'addons', 'omf', 'out'):
    p.add_argument('--' + name, type=Path, required=True)
p.add_argument('--motion', required=True)
p.add_argument('--weapon-ltx', type=Path)
p.add_argument('--meshes', type=Path)
p.add_argument('--no-render', action='store_true', help='Only audit weapon direction and skin intersections')
p.add_argument('--samples', type=int, default=4)
p.add_argument('--weapon-position', help='Review-only attachment override X,Y,Z; not an installed configuration')
p.add_argument('--weapon-transform', type=Path, help='Private review.json attachment matrix; not an installed engine transform')
p.add_argument('--close-up', action='store_true', help='Also render the actual right hand and trigger at a readable scale')
p.add_argument('--only-close-up', action='store_true', help='Skip the three full-body cameras')
p.add_argument('--close-up-view', choices=('both','outer','inner'), default='both')
p.add_argument('--render-frames', help='Comma-separated sample indices to render; audit still includes every sample')
p.add_argument('--preview-width', type=int, default=1000)
p.add_argument('--views', default='top,side,front', help='Comma-separated review cameras')
p.add_argument('--skip-surface-audit', action='store_true', help='Render-only sequence after a separate skin-intersection audit')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
assert 1 <= a.samples <= 300
assert not a.only_close_up or a.close_up
assert 320<=a.preview_width<=2000
render_frames={int(value) for value in a.render_frames.split(',')} if a.render_frames else set(range(a.samples))
assert render_frames<=set(range(a.samples))
a.out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(a.addons))
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray', default_set=True, persistent=False)
bpy.ops.xray_import.ogf(directory=str(a.actor.parent), files=[{'name': a.actor.name}], import_motions=False)
rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
body = [o for o in bpy.data.objects if o.type == 'MESH']
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('poses', root / 'scripts/read-omf-poses.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
motions = reader.Motions(a.omf, a.actor)
convert = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
bone_axes = Matrix.Diagonal((1, 1, -1, 1))
order = sorted(rig.pose.bones, key=lambda b: len(b.parent_recursive))
for bone in order:
    for constraint in list(bone.constraints):
        bone.constraints.remove(constraint)
actor_material = bpy.data.materials.new('Actor')
actor_material.diffuse_color = (.30, .59, .76, 1)
for obj in body:
    obj.data.materials.clear()
    obj.data.materials.append(actor_material)
weapon = []
weapon_meshes = []
trigger_components = []
if a.weapon_ltx:
    assert a.meshes
    fields = {}
    for line in a.weapon_ltx.read_text(encoding='cp1251').splitlines():
        match = re.match(r'^\s*(visual|position|orientation|hand_dependence)\s*=\s*([^;]+)', line)
        if match:
            fields.setdefault(match[1], match[2].strip())
    visual = fields['visual'].replace('\\', '/')
    path = a.meshes / (visual if visual.lower().endswith('.ogf') else visual + '.ogf')
    before = set(bpy.data.objects)
    bpy.ops.xray_import.ogf(directory=str(path.parent), files=[{'name': path.name}], import_motions=False)
    imported = set(bpy.data.objects) - before
    weapon_meshes = [obj for obj in imported if obj.type == 'MESH']
    if a.weapon_ltx.stem == 'w_rpg7':
        # Identify the actual curved trigger inside the guard. In this OGF
        # the separate part at Z=.10-.13 is the hammer behind the grip.
        for obj in weapon_meshes:
            parents=list(range(len(obj.data.vertices)))
            def find(index):
                while parents[index]!=index:
                    parents[index]=parents[parents[index]];index=parents[index]
                return index
            for edge in obj.data.edges:
                first,second=edge.vertices;parents[find(first)]=find(second)
            components={}
            for vertex in obj.data.vertices:components.setdefault(find(vertex.index),set()).add(vertex.index)
            for indices in components.values():
                if len(indices)<20:continue
                points=[convert@obj.matrix_world@obj.data.vertices[index].co for index in indices]
                if all(abs(point.x)<.005 and .085<point.y<.12 and .165<point.z<.19 for point in points):
                    trigger_components.append((obj,indices))
        assert len(trigger_components)==1, 'RPG trigger geometry changed; re-identify it before reviewing contact'
    weapon = [(obj, obj.matrix_world.copy()) for obj in imported if obj.parent not in imported]
    material = bpy.data.materials.new('Weapon')
    material.diffuse_color = (.19, .21, .16, 1)
    for obj in imported:
        if obj.type == 'MESH':
            obj.data.materials.clear()
            obj.data.materials.append(material)
    # Exact columns of Fmatrix::setHPB, then translate_over, as loaded by
    # CWeapon. The knife has a 90-degree pitch offset, unlike these firearms.
    h, p, b = (math.radians(float(v)) for v in fields.get('orientation', '0,0,0').split(','))
    ch, cp, cb, sh, sp, sb = math.cos(h), math.cos(p), math.cos(b), math.sin(h), math.sin(p), math.sin(b)
    offset = Matrix.Identity(4)
    offset.col[0].xyz = Vector((ch*cb-sp*sh*sb, -cp*sb, sp*ch*sb+sh*cb))
    offset.col[1].xyz = Vector((sp*sh*cb+ch*sb, cp*cb, sh*sb-sp*ch*cb))
    offset.col[2].xyz = Vector((-cp*sh, sp, cp*ch))
    offset.translation = Vector(tuple(float(v) for v in (a.weapon_position or fields.get('position', '0,0,0')).split(',')))
    if a.weapon_transform:
        import json
        assert not a.weapon_position
        offset = Matrix(json.loads(a.weapon_transform.read_text())['attachment_review']['matrix_game'])
    one_hand = int(fields.get('hand_dependence', '2')) == 1


def weapon_body_intersections(trigger_point=None):
    """Triangle surface intersections, excluding intentional hand contacts.

    Use the actual deformed skin, not just joint distances. This is a review
    diagnostic for the selected model, not a universal collision guarantee.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    vertices, triangles = [], []
    for obj in weapon_meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        base = len(vertices)
        vertices.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        triangles.extend(tuple(base + i for i in tri.vertices) for tri in mesh.loop_triangles)
        evaluated.to_mesh_clear()
    weapon_tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    trigger_vertices,trigger_triangles=[],[]
    for obj,indices in trigger_components:
        evaluated=obj.evaluated_get(depsgraph);mesh=evaluated.to_mesh();mesh.calc_loop_triangles()
        base=len(trigger_vertices)
        trigger_vertices.extend(evaluated.matrix_world@vertex.co for vertex in mesh.vertices)
        trigger_triangles.extend(tuple(base+i for i in tri.vertices) for tri in mesh.loop_triangles
                                 if all(i in indices for i in tri.vertices))
        evaluated.to_mesh_clear()
    trigger_tree=BVHTree.FromPolygons(trigger_vertices,trigger_triangles,all_triangles=True) if trigger_triangles else None
    result = {}
    regions = {f'{side}_{part}': f'bip01_{side}_{part}' for side in ('r', 'l') for part in ('upperarm', 'forearm')}
    regions['head'] = 'bip01_head'
    regions.update({part: 'bip01_' + part for part in ('spine', 'spine1', 'spine2', 'pelvis')})
    if trigger_point is not None:
        regions['trigger_index_pad'] = ('bip01_r_finger1','bip01_r_finger11','bip01_r_finger12')
    for region, group_name in regions.items():
        vertices, triangles = [], []
        triangle_bones=[]
        for obj in body:
            evaluated = obj.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh()
            assert len(mesh.vertices) == len(obj.data.vertices), 'Contact review requires topology-preserving skinning'
            mesh.calc_loop_triangles()
            names = group_name if isinstance(group_name,tuple) else (group_name,)
            groups = {group.index for name in names if (group:=obj.vertex_groups.get(name)) is not None}
            influenced = {vertex.index for vertex in obj.data.vertices
                if any(assignment.group in groups and assignment.weight >= .35 for assignment in vertex.groups)}
            base = len(vertices)
            vertices.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
            for tri in mesh.loop_triangles:
                if not any(i in influenced for i in tri.vertices):continue
                triangles.append(tuple(base+i for i in tri.vertices))
                weights={}
                for i in tri.vertices:
                    for assignment in obj.data.vertices[i].groups:
                        name=obj.vertex_groups[assignment.group].name
                        weights[name]=weights.get(name,0)+assignment.weight
                triangle_bones.append(max(weights,key=weights.get))
            evaluated.to_mesh_clear()
        tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True) if triangles else None
        overlaps=weapon_tree.overlap(tree) if tree else []
        by_bone={}
        for _,index in overlaps:
            name=triangle_bones[index];by_bone[name]=by_bone.get(name,0)+1
        result[region] = dict(triangles=len(triangles), intersecting_pairs=len(overlaps),
                              intersections_by_dominant_bone=by_bone)
        if region == 'trigger_index_pad':
            assert tree
            result[region]['nearest_surface_to_trigger_metres'] = tree.find_nearest(trigger_point)[3]
            if trigger_tree:
                contact_vertices={i for tri in trigger_triangles for i in tri}
                result[region]['trigger_surface_to_index_metres']=min(tree.find_nearest(trigger_vertices[i])[3] for i in contact_vertices)
                result[region]['trigger_triangle_intersections']=len(trigger_tree.overlap(tree))
                result[region]['trigger_triangles']=len(trigger_triangles)
                by_bone={}
                for _,index in trigger_tree.overlap(tree):
                    name=triangle_bones[index];by_bone[name]=by_bone.get(name,0)+1
                result[region]['trigger_intersections_by_dominant_bone']=by_bone
    return result

scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'MATERIAL'
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.render.resolution_x = a.preview_width
scene.render.resolution_y = round(a.preview_width*.65)
scene.render.resolution_percentage = 100
scene.world = bpy.data.worlds.new('World')
scene.world.color = (.22, .22, .22)
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, -.02))
floor = bpy.context.object
material = bpy.data.materials.new('Ground')
material.diffuse_color = (.3, .31, .32, 1)
floor.data.materials.append(material)
bpy.ops.object.camera_add()
camera = bpy.context.object
camera.data.type = 'ORTHO'
camera.data.ortho_scale = 2.35
scene.camera = camera
report = []
for sample_index in range(a.samples):
    phase = sample_index / a.samples
    game = motions.pose(a.motion, phase, matrices=True)
    world = {n: convert @ Matrix(m.tolist()) @ bone_axes for n, m in game.items()}
    for bone in order:
        parent = {} if bone.parent is None else dict(parent_matrix=world[bone.parent.name], parent_matrix_local=bone.parent.bone.matrix_local)
        bone.matrix_basis = bone.bone.convert_local_to_pose(world[bone.name], bone.bone.matrix_local, invert=True, **parent)
    bpy.context.view_layer.update()
    if weapon:
        right = Matrix(game['bip01_r_finger1'].tolist())
        left = Matrix(game['bip01_r_finger11' if one_hand else 'bip01_l_finger1'].tolist())
        direction = (left.translation - right.translation).normalized()
        side = right.col[1].xyz.cross(direction).normalized()
        up = direction.cross(side).normalized()
        transform = Matrix.Identity(4)
        for i, axis in enumerate((side, up, direction)):
            transform.col[i].xyz = axis
        transform.translation = right.translation
        for obj, original in weapon:
            obj.matrix_world = convert @ transform @ offset @ convert @ original
        bpy.context.view_layer.update()
        body_min_z = 1e9
        for skin in body:
            evaluated = skin.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            body_min_z = min(body_min_z, min((evaluated.matrix_world @ vertex.co).z for vertex in mesh.vertices))
            evaluated.to_mesh_clear()
        trigger_point = None
        if a.weapon_ltx.stem == 'w_rpg7':
            trigger_point = convert @ transform @ offset @ Vector((.00042,.1022,.1771))
        barrel_direction=(transform@offset).col[2].xyz.normalized()
        report.append(dict(phase=phase, finger_attachment_direction=list(direction),
                           weapon_direction=list(barrel_direction), muzzle_forward_dot=float(barrel_direction.z),
                           review_only_weapon_position=a.weapon_position,
                           review_only_attachment_matrix=bool(a.weapon_transform),
                           body_min_z=body_min_z, weapon_min_z=min((obj.matrix_world @ vertex.co).z for obj in weapon_meshes for vertex in obj.data.vertices),
                           body_surface_intersections=None if a.skip_surface_audit else weapon_body_intersections(trigger_point)))
    center = Vector((0, .1, .23))
    render_sample=not a.no_render and sample_index in render_frames
    for name, location in ([] if not render_sample or a.only_close_up else [('top', (0, .1, 5)), ('side', (4, .1, .8)), ('front', (2, 3, 1.4))]):
        if name not in a.views.split(','):continue
        camera.data.ortho_scale = 3.6 if name == 'top' else 2.8
        camera.location = location
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(a.out / f'{name}-{int(phase*100):02}.png')
        bpy.ops.render.render(write_still=True)
    if a.close_up and render_sample:
        center = world['bip01_r_hand'].translation.lerp(world['bip01_r_finger1'].translation,.6)
        camera.data.ortho_scale = .40
        for name, delta in [('trigger-outer',Vector((1,.3,.2))),('trigger-inner',Vector((-1,.3,.2)))]:
            if a.close_up_view!='both' and name!='trigger-'+a.close_up_view:continue
            camera.location = center+delta
            camera.rotation_euler = (center-camera.location).to_track_quat('-Z','Y').to_euler()
            scene.render.filepath = str(a.out/f'{name}-{int(phase*100):02}.png')
            bpy.ops.render.render(write_still=True)
import json
(a.out / 'weapon-directions.json').write_text(json.dumps(report, indent=2) + '\n')
print('PRONE_REVIEW_READY', a.out)
