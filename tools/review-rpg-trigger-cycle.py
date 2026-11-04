"""Build a private trigger pull/return from an inspected real actor grip.

Blender --background --python-exit-code 1 --python this.py --
 --blend PRIVATE/candidate.blend --review PRIVATE/review.json
 --actor ACTOR.ogf --weapon RPG.ogf --addons DIR --out PRIVATE
Only the two distal index phalanges move. Nothing is installed or cleared for
redistribution by this tool. A constant legacy attachment must survive export.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import addon_utils
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

p=argparse.ArgumentParser(description=__doc__)
for name in ('blend','review','actor','weapon','addons','out'):
    p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
a.out.mkdir(parents=True,exist_ok=True)
metadata=json.loads(a.review.read_text())
assert metadata['installed'] is False and metadata['reference_only'] is True
sys.path.insert(0,str(a.addons))
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
bpy.ops.wm.open_mainfile(filepath=str(a.blend))
bpy.context.scene.frame_set(0);bpy.context.view_layer.update()
rig=next(obj for obj in bpy.data.objects if obj.type=='ARMATURE' and len(obj.data.bones)==47)
body=[obj for obj in bpy.data.objects if obj.type=='MESH']
order=sorted(rig.pose.bones,key=lambda bone:len(bone.parent_recursive))
world={bone.name:bone.matrix.copy() for bone in order}
rest={bone.name:bone.matrix_local.copy() for bone in rig.data.bones}
c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)))
s=Matrix.Diagonal((1,1,-1,1))
chain=['bip01_r_finger1','bip01_r_finger11','bip01_r_finger12']
offset=Matrix(metadata['attachment_review']['matrix_game'])

def weapon_transform(matrices):
    first=c@matrices[chain[0]]@s;second=c@matrices[chain[1]]@s
    direction=(second.translation-first.translation).normalized()
    side=first.col[1].xyz.cross(direction).normalized()
    up=direction.cross(side).normalized()
    result=Matrix((side,up,direction)).transposed().to_4x4()
    result.translation=first.translation
    return result@offset

gun=weapon_transform(world)
before=set(bpy.data.objects)
bpy.ops.xray_import.ogf(directory=str(a.weapon.parent),files=[{'name':a.weapon.name}],import_motions=False)
imported=set(bpy.data.objects)-before
weapon_vertices,weapon_triangles,trigger_triangles=[],[],[]
for obj in imported:
    if obj.type!='MESH':continue
    points=[c@obj.matrix_world@v.co for v in obj.data.vertices]
    trigger={i for i,point in enumerate(points) if abs(point.x)<.005 and .085<point.y<.12 and .165<point.z<.19}
    base=len(weapon_vertices)
    weapon_vertices.extend(c@gun@point for point in points)
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        polygon=tuple(base+i for i in tri.vertices);weapon_triangles.append(polygon)
        if all(i in trigger for i in tri.vertices):trigger_triangles.append(polygon)
for obj in imported:bpy.data.objects.remove(obj,do_unlink=True)
assert len(trigger_triangles)==48,'Actual RPG trigger geometry changed'
weapon_tree=BVHTree.FromPolygons(weapon_vertices,weapon_triangles,all_triangles=True)
trigger_indices={i for tri in trigger_triangles for i in tri}
samples,triangles=[],[]
for obj in body:
    obj.data.calc_loop_triangles();polygons=[]
    for tri in obj.data.loop_triangles:
        weights={}
        for i in tri.vertices:
            for g in obj.data.vertices[i].groups:
                name=obj.vertex_groups[g.group].name;weights[name]=weights.get(name,0)+g.weight
        if max(weights,key=weights.get) in chain:polygons.append(tuple(tri.vertices))
    lookup={}
    for i in sorted({i for tri in polygons for i in tri}):
        vertex=obj.data.vertices[i];point=rig.matrix_world.inverted()@obj.matrix_world@vertex.co
        lookup[i]=len(samples)
        samples.append([(obj.vertex_groups[g.group].name,rest[obj.vertex_groups[g.group].name].inverted()@point,g.weight)
                        for g in vertex.groups if obj.vertex_groups[g.group].name in rest])
    triangles.extend(tuple(lookup[i] for i in tri) for tri in polygons)
assert triangles

def skin(matrices):
    return [sum(((matrices[name]@point)*weight for name,point,weight in weights),Vector((0,0,0))) for weights in samples]

hinge=(world[chain[1]].translation-world[chain[0]].translation).cross(
    world[chain[2]].translation-world[chain[1]].translation).normalized()
assert hinge.length>.99
axes={name:world[name].to_3x3().inverted()@hinge for name in chain[1:]}
relative={name:world[rig.data.bones[name].parent.name].inverted()@world[name] for name in chain[1:]}

def pose(degrees,weight=1):
    result={name:matrix.copy() for name,matrix in world.items()}
    for name,angle in zip(chain[1:],degrees):
        parent=rig.data.bones[name].parent.name
        result[name]=result[parent]@relative[name]@Matrix.Rotation(math.radians(angle)*weight,4,axes[name])
    return result

def contact(matrices):
    points=skin(matrices);tree=BVHTree.FromPolygons(points,triangles,all_triangles=True)
    collisions=len(weapon_tree.overlap(tree))
    gap=min(tree.find_nearest(weapon_vertices[i])[3] for i in trigger_indices)
    return collisions,gap,points

pressed_hits,pressed_gap,pressed_points=contact(world)
assert pressed_hits==0,('Pressed finger already penetrates weapon',pressed_hits)
candidates=[]
for pip in range(-12,13,2):
    for dip in range(-12,13,2):
        if pip==dip==0:continue
        hits,gap,points=contact(pose((pip,dip)))
        travel=max((left-right).length for left,right in zip(points,pressed_points))
        if hits or not pressed_gap+.0015<gap<pressed_gap+.007 or travel>.012:continue
        if any(contact(pose((pip,dip),weight))[0] for weight in (.125,.25,.375,.5,.625,.75,.875)):continue
        candidates.append((abs(gap-pressed_gap-.003)+.000002*(pip*pip+dip*dip),(pip,dip),gap,travel))
assert candidates,'No collision-free distal-only release found; refit the grip'
_,release,release_gap,travel=min(candidates)

def smooth(value):
    value=max(0,min(1,value));return value*value*(3-2*value)

frames=[]
for frame in range(21):
    released=1-smooth((frame-3)/5) if frame<=11 else smooth((frame-11)/7)
    frames.append(pose(release,released))
rig.animation_data_create();action=bpy.data.actions.new('review_rpg_trigger_pull')
rig.animation_data.action=action;action.xray.fps=30;action.xray.speed=1
for frame,matrices in enumerate(frames):
    for bone in order:
        bone.rotation_mode='QUATERNION'
        kwargs={} if bone.parent is None else dict(parent_matrix=matrices[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
        bone.matrix_basis=bone.bone.convert_local_to_pose(matrices[bone.name],bone.bone.matrix_local,invert=True,**kwargs)
        for channel in ('location','rotation_quaternion','scale'):bone.keyframe_insert(channel,frame=frame)
for curve in action.fcurves:
    for key in curve.keyframe_points:key.interpolation='LINEAR'
rig.xray.motions_collection.clear();rig.xray.motions_collection.add().name=action.name
bpy.context.scene.frame_set(0);bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);bpy.context.view_layer.objects.active=rig
bpy.ops.wm.save_as_mainfile(filepath=str(a.out/'candidate.blend'))
assert bpy.ops.xray_export.omf_file(filepath=str(a.out/'candidate.omf'),high_quality=True,fmt_ver='cscop')=={'FINISHED'}
spec=importlib.util.spec_from_file_location('poses',Path(__file__).resolve().parents[1]/'scripts/read-omf-poses.py')
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
motions=reader.Motions(a.out/'candidate.omf',a.actor)
checks=[]
first_exported=None
for index,expected in enumerate(frames):
    game=motions.pose(action.name,index/len(frames),matrices=True)
    matrices={name:c@Matrix(value.tolist())@s for name,value in game.items()}
    if first_exported is None:first_exported={name:value.copy() for name,value in matrices.items()}
    position=max((matrices[name].translation-value.translation).length for name,value in expected.items())
    rotation=max(abs(matrices[name][r][k]-value[r][k]) for name,value in expected.items() for r in range(3) for k in range(3))
    fixed=max(abs(matrices[name][r][k]-frames[0][name][r][k]) for name in matrices if name not in chain[1:] for r in range(4) for k in range(4))
    drift=max(abs(matrices[name][r][k]-first_exported[name][r][k]) for name in matrices if name not in chain[1:] for r in range(4) for k in range(4))
    current_gun=weapon_transform(matrices)
    gun_position=(current_gun.translation-gun.translation).length
    gun_rotation=max(abs(current_gun[r][k]-gun[r][k]) for r in range(3) for k in range(3))
    hits,gap,_=contact(matrices)
    assert position<.001 and rotation<.002 and fixed<.002 and drift<.000001
    assert gun_position<.001 and gun_rotation<.002
    assert hits==0,('Exported finger intersects weapon',index,hits)
    checks.append(dict(frame=index,intersections=hits,trigger_gap_metres=gap,
        unchanged_bone_drift_coefficient=drift,
        weapon_position_error_metres=gun_position,weapon_rotation_coefficient=gun_rotation,
        roundtrip_position_metres=position,roundtrip_rotation_coefficient=rotation))
loop_error=max(abs(matrices[name][r][k]-first_exported[name][r][k]) for name in matrices for r in range(4) for k in range(4))
assert loop_error<.000001,'Trigger does not return to the first pose'
metadata.update(installed=False,reference_only=True,redistribution_cleared=False,
    candidate_sha256=hashlib.sha256((a.out/'candidate.omf').read_bytes()).hexdigest(),motion=action.name,
    trigger_cycle=dict(frames=21,fps=30,release_degrees=release,pressed_gap_metres=pressed_gap,
        released_gap_metres=release_gap,maximum_index_travel_metres=travel,
        unchanged_bones=45,moving_bones=chain[1:],exported_frames=checks),
    loop_closure_coefficient=loop_error,
    input_blend_sha256=hashlib.sha256(a.blend.read_bytes()).hexdigest())
(a.out/'review.json').write_text(json.dumps(metadata,indent=2)+'\n')
print('PRIVATE_TRIGGER_CYCLE_REVIEWED',json.dumps(dict(frames=21,release=release,pressed_gap=pressed_gap,released_gap=release_gap,installed=False)))
