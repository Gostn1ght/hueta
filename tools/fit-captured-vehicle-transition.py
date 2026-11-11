"""Offline captured entry/exit fitted to a real vehicle seat; never installs.

Uses complete owner-downloaded Mixamo motion, not the retired chair gesture.
All endpoint blends are joint-local quaternion blends, without scaling limbs.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys

import addon_utils
import bpy
from mathutils import Matrix, Vector

p=argparse.ArgumentParser(description=__doc__)
for key in ('actor','addons','source','out'):
    p.add_argument('--'+key,type=Path,required=True)
p.add_argument('--section',required=True)
p.add_argument('--seat',type=int,default=0)
p.add_argument('--render',action='store_true')
p.add_argument('--save-blend',action='store_true',help='Save optional editable scene; omitted for lightweight numeric review')
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.out.mkdir(parents=True,exist_ok=True)
root=Path(__file__).resolve().parents[1];overlay=root/'scripts/netcoop-overlay/client'
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
reader=module('poses',root/'scripts/read-omf-poses.py');merge=module('merge',root/'scripts/tools/merge-player-anims.py')
sys.path.insert(0,str(a.addons));bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
bpy.ops.xray_import.ogf(directory=str(a.actor.parent),files=[{'name':a.actor.name}],import_motions=False)
actor=next(o for o in bpy.data.objects if o.type=='ARMATURE');skin=[o for o in bpy.data.objects if o.type=='MESH']
order=sorted(actor.pose.bones,key=lambda b:len(b.parent_recursive));rest={b.name:b.matrix_local.copy() for b in actor.data.bones}
for bone in order:
    bone.rotation_mode='QUATERNION'
    for constraint in list(bone.constraints):bone.constraints.remove(constraint)
actor.animation_data_create();actor.xray.motions_collection.clear()
for name,bones in merge.parse(overlay/'meshes/actors/stalker_animation.omf')['parts']:
    group=actor.data.collections.new(name)
    for bone,_ in bones:group.assign(actor.data.bones[bone])
c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)));s=Matrix.Diagonal((1,1,-1,1))
def pose(motions,name,t):return {n:c@Matrix(m.tolist())@s for n,m in motions.pose(name,t,matrices=True).items()}
models={};passenger={};current=None
for line in (overlay/'configs/mod_system_lz_dcp_vehicles.ltx').read_text(encoding='cp1251').splitlines():
    if line.startswith('['):current=line.split(']')[0][1:]
    elif line.startswith('visual ='):models[current]=line.split('=',1)[1].strip().replace('\\','/')
    elif line.startswith('netcoop_passenger_pose ='):passenger[current]=line.split('=',1)[1].strip()
visual=models[a.section];model=overlay/'meshes'/visual
layout=json.loads((root/'tools/dcp-seat-layouts.json').read_text(encoding='utf-8'))[visual]['seats'][a.seat]
row=next(r for r in json.loads((root/'docs/audit/169_FLEET_SEATS_AND_DECKS.json').read_text(encoding='utf-8'))['rows'] if r['section']==a.section)
seat_game=Matrix(row['seat_matrices_game'][layout['bone']]);seat_game.translation+=Vector(layout['offset'])
seat_matrix=c@(seat_game@Matrix.Rotation(math.radians(layout['yaw']),4,'Y'))@c
actor.matrix_world=seat_matrix
if a.seat==0:
    fit=json.loads((root/'tools/dcp-driver-pose-fits.json').read_text(encoding='utf-8'))[visual]
    target=pose(reader.Motions(overlay/'meshes/actors/modded_stalker_animations/netcoop_vehicle_driving.omf',a.actor),fit['idle'],0)
else:
    name=passenger[a.section]
    path=overlay/'meshes/actors/modded_stalker_animations'/('netcoop_vehicle_passengers.omf' if name.startswith('lz_vehicle_passenger_') else 'netcoop_player_prone.omf')
    target=pose(reader.Motions(path,a.actor),name,0)
before=set(bpy.data.objects)
bpy.ops.xray_import.ogf(directory=str(model.parent),files=[{'name':model.name}],import_motions=False)
car_objects=set(bpy.data.objects)-before;car=next(o for o in car_objects if o.type=='ARMATURE')
doors=[b for b in car.data.bones if 'door' in b.name.lower() and not any(k in b.name.lower() for k in ('back','trunk'))]
seat_point=seat_matrix.translation
door=min(doors,key=lambda b:(b.matrix_local.translation-seat_point).length) if doors else None
if door:
    limits=[(getattr(door.xray.ikjoint,'lim_'+axis+'_min'),getattr(door.xray.ikjoint,'lim_'+axis+'_max')) for axis in 'xyz']
    door_axis=max(range(3),key=lambda i:limits[i][1]-limits[i][0]);door_angle=max(limits[door_axis],key=abs)
    assert abs(door_angle)>.3,('No usable door joint',door.name,limits)
    car.pose.bones[door.name].rotation_mode='XYZ'
source=reader.Motions(a.source,a.actor);parsed=merge.parse(a.source)
source_names={d['name']:struct.unpack_from('<I',parsed['blobs'][d['motion']][1])[0] for d in parsed['defs']}
def apply(world):
    for bone in order:
        kwargs={} if bone.parent is None else dict(parent_matrix=world[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
        bone.matrix_basis=bone.bone.convert_local_to_pose(world[bone.name],bone.bone.matrix_local,invert=True,**kwargs)
    bpy.context.view_layer.update()
def minimum_height():
    value=1e9;deps=bpy.context.evaluated_depsgraph_get()
    for obj in skin:
        evaluated=obj.evaluated_get(deps);mesh=evaluated.to_mesh()
        value=min(value,min((evaluated.matrix_world@v.co).z for v in mesh.vertices));evaluated.to_mesh_clear()
    return value
def smooth(t):t=max(0,min(1,t));return t*t*(3-2*t)
def local_blend(world,weight):
    result={}
    for bone in order:
        name=bone.name;parent=bone.parent.name if bone.parent else None
        first=world[parent].inverted()@world[name] if parent else world[name]
        last=target[parent].inverted()@target[name] if parent else target[name]
        value=first.to_quaternion().slerp(last.to_quaternion(),weight).to_matrix().to_4x4()
        value.translation=first.translation.lerp(last.translation,weight)
        result[name]=result[parent]@value if parent else value
    return result
for obj in skin:
    material=bpy.data.materials.new('actor');material.diffuse_color=(.2,.55,.8,1);obj.data.materials.clear();obj.data.materials.append(material)
for obj in car_objects:
    if obj.type=='MESH':
        material=bpy.data.materials.new('car');material.diffuse_color=(.5,.5,.48,1);obj.data.materials.clear();obj.data.materials.append(material)
scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH';scene.display.shading.color_type='MATERIAL'
scene.render.resolution_x=1000;scene.render.resolution_y=800;scene.render.resolution_percentage=100
bpy.ops.object.camera_add();camera=bpy.context.object;scene.camera=camera;camera.data.type='ORTHO';camera.data.ortho_scale=4.5
ground=float(row['visual_bounds_blender'][0][2]);bpy.ops.mesh.primitive_plane_add(size=20,location=(0,0,ground-.005))
metadata=[];samples=[]
for leaving,source_name in [(False,'review_car_enter'),(True,'review_car_exit')]:
    frames=source_names[source_name];edge=0 if leaving else (frames-1)/frames
    end=pose(source,source_name,edge);align=target['bip01_pelvis']@end['bip01_pelvis'].inverted()
    sequence=[]
    for frame in range(frames):
        t=frame/(frames-1);world={n:align@m for n,m in pose(source,source_name,frame/frames).items()}
        world=local_blend(world,smooth((.18-t)/.18) if leaving else smooth((t-.82)/.18))
        sequence.append(world)
    actor.animation_data.action=None
    stand=sequence[-1 if leaving else 0];apply(stand)
    vertical=ground+.006-minimum_height()
    name=f'lz_{"exit" if leaving else "enter"}_{a.section[4:]}_{a.seat:02}'
    action=bpy.data.actions.new(name);actor.animation_data.action=action;action.xray.fps=30;action.xray.speed=1
    for frame,base in enumerate(sequence):
        scene.frame_set(frame)
        t=frame/(frames-1);weight=smooth((t-.25)/.75) if leaving else 1-smooth(t/.75)
        # Correct model height at the standing endpoint without changing bones.
        shift=seat_matrix.to_3x3().inverted()@Vector((0,0,vertical*weight))
        world={n:Matrix.Translation(shift)@m for n,m in base.items()};apply(world)
        for bone in order:
            error=(bone.matrix.translation-world[bone.name].translation).length
            assert error<.0001,('Preview pose differs',name,frame,bone.name,error)
            for channel in ('location','rotation_quaternion','scale'):bone.keyframe_insert(channel,frame=frame)
        for bone in order:
            if bone.parent and bone.name not in ('bip01','bip01_pelvis'):
                assert abs((world[bone.name].translation-world[bone.parent.name].translation).length-(rest[bone.name].translation-rest[bone.parent.name].translation).length)<.001
        samples.append(dict(motion=name,frame=frame,frames=frames,matrices={n:[list(r) for r in m] for n,m in world.items()}))
        if frame in (0,frames//4,frames//2,3*frames//4,frames-1):
            if a.render:
                if door:
                    opened=smooth(t/.2)*(1-smooth((t-.85)/.15))
                    car.pose.bones[door.name].rotation_euler[door_axis]=door_angle*opened
                bpy.context.view_layer.update()
                centre=seat_point+Vector((0,0,.2));camera.location=centre+Vector((-3,-4,2));camera.rotation_euler=(centre-camera.location).to_track_quat('-Z','Y').to_euler()
                scene.render.filepath=str(a.out/f'{name}-{frame:03}.png');bpy.ops.render.render(write_still=True)
    for curve in action.fcurves:
        for key in curve.keyframe_points:key.interpolation='LINEAR'
    actor.xray.motions_collection.add().name=name
    outside=seat_matrix@sequence[-1 if leaving else 0]['bip01'].translation+Vector((0,0,vertical))
    metadata.append(dict(motion=name,frames=frames,duration_ms=round((frames-1)/30*1000),standing_root_blender=list(outside),ground_correction_metres=vertical))
bpy.ops.object.select_all(action='DESELECT');actor.select_set(True);bpy.context.view_layer.objects.active=actor
if a.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=str(a.out/'candidate.blend'))
assert bpy.ops.xray_export.omf_file(filepath=str(a.out/'candidate.omf'),high_quality=True,fmt_ver='cscop')=={'FINISHED'}
readback=reader.Motions(a.out/'candidate.omf',a.actor);worst=0
for sample in samples:
    actual=pose(readback,sample['motion'],sample['frame']/sample['frames'])
    for name,matrix in sample['matrices'].items():worst=max(worst,(actual[name].translation-Matrix(matrix).translation).length)
assert worst<.001,worst
(a.out/'review.json').write_text(json.dumps(dict(installed=False,section=a.section,seat=a.seat,model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),door=None if not door else door.name,motions=metadata,roundtrip_max_error_metres=worst,candidate_sha256=hashlib.sha256((a.out/'candidate.omf').read_bytes()).hexdigest()),indent=2)+'\n')
print('CAPTURED_TRANSITIONS_REVIEW_READY',a.section,a.seat,worst)
