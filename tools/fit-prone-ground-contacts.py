"""Keep authored elbows low while refitting legs to their original boot poses."""
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

p=argparse.ArgumentParser(description=__doc__)
for name in ('source','actor','addons','out'):
    p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.out.mkdir(parents=True,exist_ok=True)
repo=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
reader=module('poses',repo/'scripts/read-omf-poses.py');merge=module('merge',repo/'scripts/tools/merge-player-anims.py')
metadata=json.loads((a.source/'review.json').read_text(encoding='utf-8'))
assert hashlib.sha256((a.source/'candidate.omf').read_bytes()).hexdigest()==metadata['candidate_sha256']
sys.path.insert(0,str(a.addons));bpy.ops.wm.read_factory_settings(use_empty=True);addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
bpy.ops.xray_import.ogf(directory=str(a.actor.parent),files=[{'name':a.actor.name}],import_motions=False)
rig=next(o for o in bpy.data.objects if o.type=='ARMATURE');body=[o for o in bpy.data.objects if o.type=='MESH']
order=sorted(rig.pose.bones,key=lambda b:len(b.parent_recursive));rest={b.name:b.matrix_local.copy() for b in rig.data.bones}
for bone in order:
    bone.rotation_mode='QUATERNION'
    for constraint in list(bone.constraints):bone.constraints.remove(constraint)
for name,bones in merge.parse(a.source/'candidate.omf')['parts']:
    collection=rig.data.collections.new(name)
    for name,_ in bones:collection.assign(rig.data.bones[name])
rig.animation_data_create();rig.xray.motions_collection.clear()
c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)));s=Matrix.Diagonal((1,1,-1,1))
motions=reader.Motions(a.source/'candidate.omf',a.actor)
def apply(world):
    for bone in order:
        kwargs={} if bone.parent is None else dict(parent_matrix=world[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
        bone.matrix_basis=bone.bone.convert_local_to_pose(world[bone.name],bone.bone.matrix_local,invert=True,**kwargs)
    bpy.context.view_layer.update()
def floor():
    minimum=1e9
    for obj in body:
        evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
        minimum=min(minimum,min((evaluated.matrix_world@v.co).z for v in mesh.vertices));evaluated.to_mesh_clear()
    return minimum
def reachable(world,amount):
    for side in ('r','l'):
        origin,joint,end=[world[f'bip01_{side}_{part}'].translation for part in ('thigh','calf','foot')]
        distance=(end-origin+Vector((0,0,amount))).length
        first,second=(joint-origin).length,(end-joint).length
        if not abs(first-second)+.0001<distance<first+second-.0001:return False
    return True
samples=[];contacts=[]
for clip in metadata['clips']:
    action=bpy.data.actions.new(clip['clip']);action.xray.fps=30;action.xray.speed=1;rig.animation_data.action=action
    max_down=max_up=0
    for frame in range(clip['frames']):
        bpy.context.scene.frame_set(frame)
        source={n:c@Matrix(m.tolist())@s for n,m in motions.pose(clip['clip'],frame/clip['frames'],matrices=True).items()}
        height=min(source[f'bip01_{side}_forearm'].translation.z for side in ('r','l'))
        excess=max(0,height-.09);amount=excess*excess/.02 if excess<.01 else excess-.005
        if amount and not reachable(source,amount):
            lo,hi=0,amount
            for _ in range(24):
                mid=(lo+hi)/2
                if reachable(source,mid):lo=mid
                else:hi=mid
            amount=lo
        world={n:Matrix.Translation((0,0,-amount))@m for n,m in source.items()}
        if amount>1e-6:
            for side in ('r','l'):
                upper,lower,foot=[f'bip01_{side}_{part}' for part in ('thigh','calf','foot')]
                start,joint,end=[world[n].translation.copy() for n in (upper,lower,foot)]
                goal=source[foot].translation;axis=goal-start;distance=axis.length;axis.normalize()
                length_a,length_b=(joint-start).length,(end-joint).length
                along=(length_a**2-length_b**2+distance**2)/(2*distance);radius=math.sqrt(max(0,length_a**2-along**2))
                centre=start+axis*along;pole=joint-centre;pole-=axis*pole.dot(axis);pole.normalize()
                knee=centre+pole*radius
                if knee.z<.10 and radius>.0001:
                    down=Vector((0,0,-1));down-=axis*down.dot(axis);down.normalize();cross=axis.cross(down).normalized()
                    cosine=max(-1,min(1,(.10-centre.z)/(radius*down.z))) if abs(down.z)>.0001 else 1
                    sine=math.sqrt(max(0,1-cosine*cosine));choices=[down*cosine+cross*sine,down*cosine-cross*sine]
                    knee=centre+max(choices,key=lambda v:v.dot(pole))*radius
                for name,origin,old_vector,new_vector in ((upper,start,joint-start,knee-start),(lower,knee,end-joint,goal-knee)):
                    world[name]=old_vector.rotation_difference(new_vector).to_matrix().to_4x4()@world[name];world[name].translation=origin
                for bone in order:
                    if bone.name==foot or any(parent.name==foot for parent in bone.parent_recursive):world[bone.name]=source[bone.name].copy()
        apply(world);lift=max(0,.006-floor());assert lift<.06,(clip['clip'],frame,'excessive support correction',lift)
        world={n:Matrix.Translation((0,0,lift))@m for n,m in world.items()};apply(world)
        assert max(world[f'bip01_{side}_forearm'].translation.z for side in ('r','l'))<.20,(clip['clip'],frame,'elbow remains raised')
        max_down=max(max_down,amount);max_up=max(max_up,lift)
        for bone in order:
            for channel in ('location','rotation_quaternion','scale'):bone.keyframe_insert(channel,frame=frame,group=bone.name)
        samples.append((clip['clip'],frame,clip['frames'],world))
    rig.animation_data.action=action
    # Keys inserted above belong to this action, including every unchanged bone.
    for curve in action.fcurves:
        for key in curve.keyframe_points:key.interpolation='LINEAR'
    rig.xray.motions_collection.add().name=action.name
    contacts.append(dict(motion=clip['clip'],max_lowering_metres=max_down,max_floor_lift_metres=max_up))
bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);bpy.context.view_layer.objects.active=rig
assert bpy.ops.xray_export.omf_file(filepath=str(a.out/'candidate.omf'),high_quality=True,fmt_ver='cscop')=={'FINISHED'}
decoded=reader.Motions(a.out/'candidate.omf',a.actor);worst=0;worst_rotation=0
for name,frame,count,expected in samples:
    actual=decoded.pose(name,frame/count,matrices=True)
    for bone in order:
        matrix=c@Matrix(actual[bone.name].tolist())@s
        worst=max(worst,(matrix.translation-expected[bone.name].translation).length)
        worst_rotation=max(worst_rotation,max(abs(matrix[r][k]-expected[bone.name][r][k]) for r in range(3) for k in range(3)))
        if bone.parent and bone.name not in ('bip01','bip01_pelvis'):
            length=(matrix.translation-(c@Matrix(actual[bone.parent.name].tolist())@s).translation).length
            assert abs(length-(rest[bone.name].translation-rest[bone.parent.name].translation).length)<.001
assert worst<.001 and worst_rotation<.002
metadata.update(candidate_sha256=hashlib.sha256((a.out/'candidate.omf').read_bytes()).hexdigest(),verified_keys=len(samples),roundtrip_max_error_metres=worst,roundtrip_max_rotation_coefficient=worst_rotation,
    support_fit=dict(tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),input_sha256=hashlib.sha256((a.source/'candidate.omf').read_bytes()).hexdigest(),clips=contacts))
(a.out/'review.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
print('PRONE_CONTACTS_FITTED',len(samples),worst,contacts)
