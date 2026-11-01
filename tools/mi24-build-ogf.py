"""Owner's commissioned MI24 (FBX) -> flyable X-Ray OGF on the Mi-2 rig (doc 141).

Geometry: the owner's FBX, turned nose to +Y, scaled to a real Mi-24 rotor
(17.3 m), standing on z=0, retaining every source triangle. Skeleton/physics
properties come from the shipped Mi-2 (veh_mi2_pilot.ogf): root_0, root
(fuselage box), front_propeller (main rotor), back_propeller (tail rotor +
tail boom box), korpus1 (seat reference). A new "idle" turns both rotors;
the engine plays it as fast as the rotor turns.
"""
import bpy, addon_utils, bmesh, json, math, sys, argparse
from mathutils import Matrix, Quaternion, Vector
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True, help='Directory containing MI24.fbx')
parser.add_argument('--addons', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--template', type=Path, default=Path(__file__).resolve().parents[1] / 'scripts/netcoop-overlay/client/meshes/dynamics/vehicles/mi2/veh_mi2_pilot.ogf')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
sys.path.insert(0, str(args.addons.resolve()))
addon_utils.enable('io_scene_xray', default_set=True, persistent=False)
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=True)
SCALE = 17.3 / 22.0
# Owner 2026-11-01: retain the complete source mesh, including cockpit detail.
DECIMATE = dict.fromkeys(('body', 'main_rotor', 'rear_rotor', 'glass'), 1.0)

bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray', default_set=True, persistent=False)
assert bpy.ops.xray_import.ogf(directory=str(args.template.parent), files=[{'name': args.template.name}], import_motions=True) == {'FINISHED'}
rig = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
for o in [o for o in bpy.context.scene.objects if o.type == 'MESH']:
    bpy.data.objects.remove(o, do_unlink=True)

before = set(bpy.context.scene.objects)
assert bpy.ops.import_scene.fbx(filepath=str(args.source / 'MI24.fbx')) == {'FINISHED'}
parts = {}
for o in [o for o in bpy.context.scene.objects if o not in before]:
    if o.type != 'MESH':
        bpy.data.objects.remove(o, do_unlink=True); continue
    key = 'glass' if 'glass' in o.name else 'main_rotor' if 'main_rotor' in o.name else 'rear_rotor' if 'rear_rotor' in o.name else 'body'
    parts[key] = o
assert set(parts) == {'body', 'glass', 'main_rotor', 'rear_rotor'}, parts

# Nose to +Y, real size, standing on the ground.
turn = Matrix.Rotation(math.pi, 4, 'Z') @ Matrix.Scale(SCALE, 4)
for o in parts.values():
    o.data.transform(turn @ o.matrix_world); o.matrix_world = Matrix.Identity(4)
lowest = min((v.co.z for v in parts['body'].data.vertices))
for o in parts.values():
    o.data.transform(Matrix.Translation((0, 0, -lowest)))

def stats(o):
    vs = [v.co for v in o.data.vertices]
    mean = sum(vs, Vector()) / len(vs)
    lo = Vector([min(v[i] for v in vs) for i in range(3)]); hi = Vector([max(v[i] for v in vs) for i in range(3)])
    return mean, lo, hi

hub, _, main_hi = stats(parts['main_rotor'])
tail, tail_lo, tail_hi = stats(parts['rear_rotor'])
body_mean, body_lo, body_hi = stats(parts['body'])
print('HUB', tuple(round(v, 2) for v in hub), 'TAIL', tuple(round(v, 2) for v in tail), 'BODY', tuple(round(v, 2) for v in body_lo), tuple(round(v, 2) for v in body_hi))

for key, o in parts.items():
    ratio = DECIMATE[key]
    before_tris = sum(len(p.vertices) - 2 for p in o.data.polygons)
    if ratio < 1:
        m = o.modifiers.new('dec', 'DECIMATE'); m.ratio = ratio; m.use_collapse_triangulate = True
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier=m.name)
    print('MESH', key, before_tris, '->', sum(len(p.vertices) - 2 for p in o.data.polygons))

# Materials: X-Ray shaders and the baked textures.
def material(name, texture, shader):
    mat = bpy.data.materials.new(name); mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    tex = nodes.new('ShaderNodeTexImage'); tex.name = 'veh\\' + texture; tex.label = tex.name
    png = OUT / f'preview_{texture}.png'
    tex.image = bpy.data.images.load(str(png)) if png.exists() else bpy.data.images.new(texture, 4, 4)
    mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    mat.xray.eshader = shader; mat.xray.cshader = 'default'; mat.xray.gamemtl = 'default_object'
    return mat
mats = {'MI_air_mi24_base_1': material('mi24_body1', 'veh_mi24_lz_body1', 'models\\model'),
        'MI_air_mi24_base_2': material('mi24_body2', 'veh_mi24_lz_body2', 'models\\model'),
        'MI_air_mi24_details': material('mi24_details', 'veh_mi24_lz_details', 'models\\model'),
        'MI_air_mi24_rotor': material('mi24_rotor', 'veh_mi24_lz_rotor', 'models\\model'),
        'MI_air_mi8_glass_clean_01': material('mi24_glass', 'veh_mi24_lz_glass', 'models\\lz_heli_glass')}
for o in parts.values():
    for i, slot in enumerate(o.material_slots):
        base = slot.material.name.split('.')[0] if slot.material else ''
        assert base in mats, base
        o.data.materials[i] = mats[base]

# The commissioned FBX has the gear stowed inside its fuselage. Supply
# visible extended struts/tyres; all three assemblies have independent bones
# and matching rigid collision shapes, translated into the wells by CCar.
gear = {
    'gear_left': (Vector((-1.75,-1.7,-0.55)), Vector((-0.9,-1.7,0.9)), 0.4),
    'gear_right': (Vector((1.75,-1.7,-0.55)), Vector((0.9,-1.7,0.9)), 0.4),
    'gear_nose': (Vector((0,4.15,-0.65)), Vector((0,4.0,0.5)), 0.3),
}
tyre_mat=material('mi24_tyre','veh_mi24_lz_tyre','models\\model')
for name,(wheel,pivot,radius) in gear.items():
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=0.28, location=wheel, rotation=(0,math.pi/2,0))
    tyre=bpy.context.object;tyre.data.materials.append(tyre_mat)
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    delta=wheel-pivot
    bpy.ops.mesh.primitive_cylinder_add(vertices=16,radius=0.065,depth=delta.length,location=(pivot+wheel)/2)
    strut=bpy.context.object;strut.rotation_mode='QUATERNION';strut.rotation_quaternion=delta.to_track_quat('Z','Y')
    strut.data.materials.append(mats['MI_air_mi24_details'])
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    bpy.ops.object.select_all(action='DESELECT');tyre.select_set(True);strut.select_set(True);bpy.context.view_layer.objects.active=tyre
    bpy.ops.object.join();parts[name]=tyre

# Windows remain full-detail, but no longer belong to the fuselage bone.
# Classify whole faces, retaining both layers of each source glass surface.
glass=parts.pop('glass')
windows={}
for face in glass.data.polygons:
    centre=sum((glass.data.vertices[i].co for i in face.vertices),Vector())/len(face.vertices)
    cabin='front' if centre.y>3.6 else 'rear' if centre.y>1.7 else 'cabin'
    side='left' if centre.x < -0.15 else 'right' if centre.x>0.15 else 'centre'
    windows.setdefault('glass_'+cabin+'_'+side,set()).add(face.index)
for name,indices in windows.items():
    obj=glass.copy();obj.data=glass.data.copy();bpy.context.collection.objects.link(obj)
    bm=bmesh.new();bm.from_mesh(obj.data);bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.index not in indices],context='FACES')
    bm.to_mesh(obj.data);bm.free();parts[name]=obj
bpy.data.objects.remove(glass,do_unlink=True)

# Skeleton: keep five bones of the Mi-2 rig, move them to the MI24.
keep = {'root_0', 'root', 'front_propeller', 'back_propeller', 'korpus1'}
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
eb = rig.data.edit_bones
eb['back_propeller'].parent = eb['root']
eb['korpus1'].parent = eb['root']
for b in list(eb):
    if b.name not in keep:
        eb.remove(b)
cockpit = Vector((0.0, body_hi.y - 3.6, 1.55))   # pilot's seat area, refined by seats in the profile
targets = {'root': Vector((0.0, body_mean.y, 1.8)), 'front_propeller': hub, 'back_propeller': tail, 'korpus1': cockpit}
for name, where in targets.items():
    b = eb[name]; delta = where - b.head; b.head += delta; b.tail += delta
for name,where in [(n,pivot) for n,(_,pivot,_) in gear.items()]+[(n,stats(parts[n])[0]) for n in windows]:
    b=eb.new(name);b.parent=eb['root'];b.head=where;b.tail=where+Vector((0,0,0.2))
bpy.ops.object.mode_set(mode='OBJECT')
bones = rig.data.bones
for name in (*gear,*windows):
    for collection in bones['root'].collections:
        collection.assign(bones[name])

def to_xr(v):  # Blender (x, y, z) -> X-Ray (x, z, y)
    return (v.x, v.z, v.y)
def box(bone, lo, hi, mass):
    centre = (lo + hi) / 2; half = (hi - lo) / 2
    rel = centre - bone.head_local
    s = bone.xray.shape
    s.type = '1'; s.box_rot = (1, 0, 0, 0, 1, 0, 0, 0, 1)
    s.box_trn = to_xr(rel); s.box_hsz = (half.x, half.z, half.y)
    bone.xray.mass.value = mass; bone.xray.mass.center = to_xr(rel)
for name in ('root_0', 'front_propeller', 'korpus1'):
    bones[name].xray.shape.type = '0'
bones['front_propeller'].xray.mass.value = 300.0
bones['korpus1'].xray.mass.value = 50.0
# A single full-height fuselage box intercepted every shot before the glass.
# Lower hull + narrower upper cabin/engine deck leave both cockpits and the
# side panes ray-pickable. Keep the original root centre of mass: changing
# hit volumes must not suddenly move the flight body's balance to the floor.
box(bones['root'], Vector((-1.15, body_hi.y - 13.2, 0.0)), Vector((1.15, body_hi.y - 0.2, 1.0)), 7000.0)
bones['root'].xray.mass.center=to_xr(Vector((0,body_hi.y-6.7,1.75))-bones['root'].head_local)
box(bones['korpus1'],Vector((-0.8,body_hi.y-13.2,1.0)),Vector((0.8,1.7,3.5)),50.0)
bones['korpus1'].xray.ikjoint.type='0'
box(bones['back_propeller'], Vector((-0.45, body_lo.y + 1.0, 1.9)), Vector((0.45, body_hi.y - 13.2, 3.3)), 600.0)
for name,(_,pivot,_) in gear.items():
    _,lo,hi=stats(parts[name]);box(bones[name],lo,hi,30.0)
    bones[name].xray.ikjoint.type='0' # rigid: wheel geometry is part of the body, not an unstable extra joint
for name in windows:
    _,lo,hi=stats(parts[name]);box(bones[name],lo-Vector((0.01,0.01,0.01)),hi+Vector((0.01,0.01,0.01)),0.1)
    bones[name].xray.ikjoint.type='0'
    bones[name].xray.shape.flags_nophysics=True # ray-pickable, never an invisible collision wall after breakage

# "idle": both rotors turn (main 2 rev, tail 6 rev per 60 frames at 30 fps).
for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)
act = bpy.data.actions.new('idle'); act.xray.fps = 30.0; act.xray.speed = 1.0
rig.animation_data_create(); rig.animation_data.action = act
spin = {'front_propeller': (Vector((0, 0, 1)), 2), 'back_propeller': (Vector((1, 0, 0)), 6)}
for name, (world_axis, turns) in spin.items():
    pb = rig.pose.bones[name]; pb.rotation_mode = 'QUATERNION'
    local = (bones[name].matrix_local.to_3x3().inverted() @ world_axis).normalized()
    for f in range(60):
        pb.rotation_quaternion = Quaternion(local, 2 * math.pi * turns * f / 60.0)
        pb.keyframe_insert('rotation_quaternion', frame=f)
for fc in act.fcurves:
    for k in fc.keyframe_points: k.interpolation = 'LINEAR'
rig.xray.motions_collection.clear()
item = rig.xray.motions_collection.add(); item.name = 'idle'
rig.xray.userdata = '#include "models\\vehicles\\veh_mi24_pilot.ltx"'
rig.name = 'veh_mi24_pilot'

# Skin: rigid parts on their bones.
# OGF uses 16-bit vertex indices. Split full-detail meshes into draw chunks
# without deleting any triangles, UVs or normals (a decimator is not needed).
for key, source in list(parts.items()):
    if len(source.data.polygons) <= 18000:
        continue
    del parts[key]
    for first in range(0, len(source.data.polygons), 18000):
        obj = source.copy(); obj.data = source.data.copy()
        bpy.context.collection.objects.link(obj)
        bm = bmesh.new(); bm.from_mesh(obj.data); bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if not first <= f.index < first + 18000], context='FACES')
        bm.to_mesh(obj.data); bm.free()
        parts[f'{key}.{first // 18000}'] = obj
    bpy.data.objects.remove(source, do_unlink=True)
groups = {'body': 'root', 'glass': 'root', 'main_rotor': 'front_propeller', 'rear_rotor': 'back_propeller'}
for key, o in parts.items():
    o.vertex_groups.clear()
    g = o.vertex_groups.new(name=groups.get(key.split('.')[0],key)); g.add(range(len(o.data.vertices)), 1.0, 'REPLACE')
    o.parent = rig
    m = o.modifiers.new('arm', 'ARMATURE'); m.object = rig
    o.name = 'mi24_' + key

bpy.ops.object.select_all(action='DESELECT')
rig.select_set(True); bpy.context.view_layer.objects.active = rig
for o in parts.values(): o.select_set(True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'mi24-conversion.blend'))
dest = OUT / 'veh_mi24_pilot.ogf'
res = bpy.ops.xray_export.ogf_file(filepath=str(dest), fmt_version='cscop', export_motions=True,
                                   use_export_paths=False, texture_name_from_image_path=False)
assert res == {'FINISHED'} and dest.is_file(), res
report = dict(output=str(dest), scale=SCALE, hub=list(hub), tail=list(tail), body_lo=list(body_lo), body_hi=list(body_hi),
              cockpit=list(cockpit), bones=sorted(b.name for b in bones),
              tris={k: sum(len(p.vertices) - 2 for p in o.data.polygons) for k, o in parts.items()})
(OUT / 'mi24-conversion.json').write_text(json.dumps(report, indent=2) + '\n')
print('MI24_EXPORTED', json.dumps(report))
