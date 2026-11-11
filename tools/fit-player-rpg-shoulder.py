"""Fit the RPG and both grips clear of real actor skin; export an offline candidate.

The launcher and both hands move rigidly together. Only shoulder/elbow IK
changes; the torso, head, pelvis and legs retain their source matrices.
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
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

p=argparse.ArgumentParser(description=__doc__)
for name in ('blend','review','actor','weapon','addons','out'):
    p.add_argument('--'+name,required=True,type=Path)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(a.addons))
bpy.ops.wm.read_factory_settings(use_empty=True);addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
bpy.ops.wm.open_mainfile(filepath=str(a.blend));bpy.context.scene.frame_set(0);bpy.context.view_layer.update()
rig=next(obj for obj in bpy.data.objects if obj.type=='ARMATURE' and len(obj.data.bones)==47)
body=[obj for obj in bpy.data.objects if obj.type=='MESH']
order=sorted(rig.pose.bones,key=lambda bone:len(bone.parent_recursive));names=[bone.name for bone in order]
source={bone.name:bone.matrix.copy() for bone in order}
rest={bone.name:bone.matrix_local.copy() for bone in rig.data.bones}
c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)));s=Matrix.Diagonal((1,1,-1,1))
metadata=json.loads(a.review.read_text());old_offset=Matrix(metadata['attachment_review']['matrix_game'])

def attachment(matrices):
    first=c@matrices['bip01_r_finger1']@s;second=c@matrices['bip01_r_finger11']@s
    direction=(second.translation-first.translation).normalized();side=first.col[1].xyz.cross(direction).normalized()
    result=Matrix((side,direction.cross(side),direction)).transposed().to_4x4();result.translation=first.translation
    return result

gun=attachment(source)@old_offset
before=set(bpy.data.objects)
bpy.ops.xray_import.ogf(directory=str(a.weapon.parent),files=[{'name':a.weapon.name}],import_motions=False)
imported=set(bpy.data.objects)-before
gun_vertices,gun_triangles=[],[]
for obj in imported:
    if obj.type!='MESH':continue
    base=len(gun_vertices);gun_vertices.extend(c@gun@c@obj.matrix_world@v.co for v in obj.data.vertices)
    obj.data.calc_loop_triangles();gun_triangles.extend(tuple(base+i for i in tri.vertices) for tri in obj.data.loop_triangles)
for obj in imported:bpy.data.objects.remove(obj,do_unlink=True)
vertices,triangles,tags,weights=[],[],[],[]
bone_ids={name:i for i,name in enumerate(names)}
for obj in body:
    base=len(vertices)
    for vertex in obj.data.vertices:
        vertices.append([*(rig.matrix_world.inverted()@obj.matrix_world@vertex.co),1])
        weights.append([(obj.vertex_groups[g.group].name,g.weight) for g in vertex.groups if obj.vertex_groups[g.group].name in rest])
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        totals={}
        for i in tri.vertices:
            for name,weight in weights[base+i]:totals[name]=totals.get(name,0)+weight
        dominant=max(totals,key=totals.get)
        if 'hand' in dominant or 'finger' in dominant:continue
        triangles.append(tuple(base+i for i in tri.vertices));tags.append(dominant)
vertices=np.array(vertices,dtype=float);rest_inverse=np.array([rest[name].inverted() for name in names])
max_weights=max(map(len,weights));ids=np.zeros((len(vertices),max_weights),dtype=int);values=np.zeros_like(ids,dtype=float)
for i,assignments in enumerate(weights):
    for j,(name,weight) in enumerate(assignments):ids[i,j]=bone_ids[name];values[i,j]=weight

def skin(matrices):
    transforms=np.array([matrices[name] for name in names])@rest_inverse
    return np.sum(np.einsum('nwij,nj->nwi',transforms[ids],vertices)*values[:,:,None],axis=1)[:,:3]

def fitted(dx,up):
    shift=(c@gun).to_3x3()@Vector((dx/1000,0,0))+Vector((0,0,up/1000))
    result={name:matrix.copy() for name,matrix in source.items()}
    for side in ('r','l'):
        upper,lower,hand=[f'bip01_{side}_{part}' for part in ('upperarm','forearm','hand')]
        origin,joint,wrist=[source[name].translation for name in (upper,lower,hand)]
        end=wrist+shift;axis=end-origin;distance=axis.length
        length_a,length_b=(joint-origin).length,(wrist-joint).length
        if not abs(length_a-length_b)+.0001<distance<length_a+length_b-.0001:return None
        axis.normalize();along=(length_a*length_a-length_b*length_b+distance*distance)/(2*distance)
        bend=joint-origin-axis*(joint-origin).dot(axis)
        elbow=origin+axis*along+bend.normalized()*math.sqrt(max(0,length_a*length_a-along*along))
        for name,start,old_direction,new_direction in (
            (upper,origin,joint-origin,elbow-origin),(lower,elbow,wrist-joint,end-elbow)):
            result[name]=old_direction.rotation_difference(new_direction).to_matrix().to_4x4()@source[name]
            result[name].translation=start
        for bone in order:
            if bone.name==hand or any(parent.name==hand for parent in bone.parent_recursive):
                result[bone.name].translation+=shift
    moved_gun=gun.copy();moved_gun.translation+=c.to_3x3()@shift
    return result,shift,moved_gun

def evaluate(dx,up):
    candidate=fitted(dx,up)
    if candidate is None:return None
    matrices,shift,moved_gun=candidate;points=skin(matrices)
    # Both elbows remain supported near the original ground plane.
    arm_vertices={i for tri,tag in zip(triangles,tags) if 'upperarm' in tag or 'forearm' in tag for i in tri}
    if min(points[i,2] for i in arm_vertices)<-.02:return None
    tree=BVHTree.FromPolygons(points,triangles,all_triangles=True)
    moved_vertices=[v+shift for v in gun_vertices]
    weapon_tree=BVHTree.FromPolygons(moved_vertices,gun_triangles,all_triangles=True)
    overlaps=weapon_tree.overlap(tree)
    return dict(dx=dx,up=up,pairs=len(overlaps),matrices=matrices,gun=moved_gun,
                tags={tag:sum(tags[i]==tag for _,i in overlaps) for tag in {tags[i] for _,i in overlaps}})

baseline=evaluate(0,0)
assert baseline is not None
coarse=[]
for dx in range(0,81,10):
    for up in range(0,81,10):
        item=evaluate(dx,up)
        if item is not None:coarse.append(item)
best=min(coarse,key=lambda v:(v['pairs'],v['dx']**2+v['up']**2))
refined=[]
for dx in range(max(0,best['dx']-10),best['dx']+11,2):
    for up in range(max(0,best['up']-10),best['up']+11,2):
        item=evaluate(dx,up)
        if item is not None:refined.append(item)
best=min(coarse+refined,key=lambda v:(v['pairs'],v['dx']**2+v['up']**2))
print('SHOULDER_FIT',json.dumps(dict(baseline=baseline['pairs'],pairs=best['pairs'],dx=best['dx'],up=best['up'],tags=best['tags'])),flush=True)
assert best['pairs']==0,'No collision-free body fit within the allowed adjustment'
world=best['matrices'];new_offset=attachment(world).inverted()@best['gun']
rig.animation_data_create();action=bpy.data.actions.new('review_rpg_shoulder_fit');rig.animation_data.action=action
action.xray.fps=30;action.xray.speed=1
for bone in order:
    bone.rotation_mode='QUATERNION'
    kwargs={} if bone.parent is None else dict(parent_matrix=world[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
    bone.matrix_basis=bone.bone.convert_local_to_pose(world[bone.name],bone.bone.matrix_local,invert=True,**kwargs)
    for frame in (0,1):
        for channel in ('location','rotation_quaternion','scale'):bone.keyframe_insert(channel,frame=frame)
rig.xray.motions_collection.clear();rig.xray.motions_collection.add().name=action.name
bpy.context.scene.frame_set(0);bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);bpy.context.view_layer.objects.active=rig
bpy.ops.wm.save_as_mainfile(filepath=str(a.out/'candidate.blend'))
assert bpy.ops.xray_export.omf_file(filepath=str(a.out/'candidate.omf'),high_quality=True,fmt_ver='cscop')=={'FINISHED'}
spec=importlib.util.spec_from_file_location('poses',Path(__file__).resolve().parents[1]/'scripts/read-omf-poses.py')
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
game=reader.Motions(a.out/'candidate.omf',a.actor).pose(action.name,0,matrices=True)
exported={name:c@Matrix(value.tolist())@s for name,value in game.items()}
position=max((exported[name].translation-value.translation).length for name,value in world.items())
rotation=max(abs(exported[name][r][k]-value[r][k]) for name,value in world.items() for r in range(3) for k in range(3))
assert position<.001 and rotation<.002
metadata.update(installed=False,reference_only=True,candidate_sha256=hashlib.sha256((a.out/'candidate.omf').read_bytes()).hexdigest(),
    shoulder_fit=dict(shift_weapon_right_mm=best['dx'],shift_world_up_mm=best['up'],baseline_body_pairs=baseline['pairs'],body_pairs=best['pairs'],
        roundtrip_position_metres=position,roundtrip_rotation_coefficient=rotation))
metadata['attachment_review']['matrix_game']=[list(row) for row in new_offset]
metadata['attachment_review']['left_arm_unchanged']=False
metadata['attachment_review']['both_grips_preserved_relative_to_weapon']=True
(a.out/'review.json').write_text(json.dumps(metadata,indent=2)+'\n')
print('SHOULDER_CANDIDATE_EXPORTED',a.out)
