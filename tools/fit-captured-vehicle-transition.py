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
p.add_argument('--driver-omf',type=Path,help='Optional private fitted driver candidate for the seated endpoint; never installs it')
p.add_argument('--layouts',type=Path,help='Private seat layout candidate; source layout remains unchanged')
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
layout_path=a.layouts or root/'tools/dcp-seat-layouts.json'
layout=json.loads(layout_path.read_text(encoding='utf-8'))[visual]['seats'][a.seat]
row=next(r for r in json.loads((root/'docs/audit/169_FLEET_SEATS_AND_DECKS.json').read_text(encoding='utf-8'))['rows'] if r['section']==a.section)
seat_game=Matrix(row['seat_matrices_game'][layout['bone']]);seat_game.translation+=Vector(layout['offset'])
seat_matrix=c@(seat_game@Matrix.Rotation(math.radians(layout['yaw']),4,'Y'))@c
actor.matrix_world=seat_matrix
if a.seat==0:
    fit=json.loads((root/'tools/dcp-driver-pose-fits.json').read_text(encoding='utf-8'))[visual]
    driver_path=a.driver_omf or overlay/'meshes/actors/modded_stalker_animations/netcoop_vehicle_driving.omf'
    if a.driver_omf:
        driver_review=json.loads((driver_path.parent/'review.json').read_text(encoding='utf-8'))
        assert hashlib.sha256(driver_path.read_bytes()).hexdigest()==driver_review['candidate_sha256']
        if 'layout_sha256' in driver_review:
            assert hashlib.sha256(layout_path.read_bytes()).hexdigest()==driver_review['layout_sha256'], 'Driver/transition seat layout mismatch'
        driver_binding=next(r for r in driver_review['rows'] if r.get('section')==a.section and 'clips' in r)
        assert driver_binding['sha256']==hashlib.sha256(model.read_bytes()).hexdigest()
        fit=dict(idle=driver_binding['clips'][0])
    target=pose(reader.Motions(driver_path,a.actor),fit['idle'],0)
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
door_hinge=None
if door:
    hinge=module('vehicle_door_review',root/'tools/vehicle-door-review.py')
    door_axis,door_angle,door_hinge=hinge.outward_hinge(car,[o for o in car_objects if o.type=='MESH'],car.pose.bones[door.name])
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
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=4
scene.render.threads_mode='FIXED';scene.render.threads=2
scene.render.resolution_x=512;scene.render.resolution_y=410;scene.render.resolution_percentage=100
scene.world=bpy.data.worlds.new('entry_review_world');scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.3,.3,.3,1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.7
bpy.ops.object.light_add(type='AREA',location=seat_point+Vector((-3,-4,5)));bpy.context.object.data.energy=700;bpy.context.object.data.shape='DISK';bpy.context.object.data.size=5
bpy.ops.object.camera_add();camera=bpy.context.object;scene.camera=camera;camera.data.type='ORTHO';camera.data.ortho_scale=4.5
ground=float(row['visual_bounds_blender'][0][2]);bpy.ops.mesh.primitive_plane_add(size=20,location=(0,0,ground-.005))
metadata=[];samples=[]
# Both standing endpoints must be outside the real body, not inside the seat.
# Warp only the standing portion; the seated endpoint stays exactly fitted.
bounds=row['visual_bounds_blender'];side=-1 if seat_point.x<0 else 1
standing_x=float(bounds[0 if side<0 else 1][0])+side*.45
standing_y=float(seat_point.y)
for leaving,source_name in [(False,'review_car_enter'),(True,'review_car_exit')]:
    frames=source_names[source_name];edge=0 if leaving else (frames-1)/frames
    end=pose(source,source_name,edge);align=target['bip01_pelvis']@end['bip01_pelvis'].inverted()
    sequence=[]
    for frame in range(frames):
        t=frame/(frames-1);world={n:align@m for n,m in pose(source,source_name,frame/frames).items()}
        world=local_blend(world,smooth((.18-t)/.18) if leaving else smooth((t-.82)/.18))
        sequence.append(world)
    # Open before the body enters the doorway; close after it has cleared.
    # These holds are a timing study, not a finished hand/handle animation.
    lead=15;trail=15;source_frames=frames
    sequence=[sequence[0]]*lead+sequence+[sequence[-1]]*trail
    frames=len(sequence)
    def body_t(frame):return max(0,min(1,(frame-lead)/(source_frames-1)))
    def door_open(frame):
        return smooth(frame/lead)*(1-smooth((frame-(lead+source_frames-1))/trail))
    actor.animation_data.action=None
    stand=sequence[-1 if leaving else 0];apply(stand)
    vertical=ground+.006-minimum_height()
    old_standing=seat_matrix@stand['bip01'].translation
    standing_shift=Vector((standing_x-old_standing.x,standing_y-old_standing.y,vertical))
    floor_samples=[]
    # Measure every key, then use a conservative smooth whole-rig lift. This
    # preserves bone lengths and cannot silently hide a mid-cycle floor hit.
    warped=[];required=[]
    for frame,base in enumerate(sequence):
        t=body_t(frame);weight=smooth((t-.25)/.75) if leaving else 1-smooth(t/.75)
        shift=seat_matrix.to_3x3().inverted()@(standing_shift*weight)
        world={n:Matrix.Translation(shift)@m for n,m in base.items()};apply(world)
        warped.append(world);required.append(max(0,ground+.006-minimum_height()))
    envelope=[max(required[max(0,i-4):min(frames,i+5)]) for i in range(frames)]
    lifts=[sum(envelope[min(frames-1,max(0,i+j-2))]*w for j,w in enumerate((1,4,6,4,1)))/16 for i in range(frames)]
    assert max(lifts)<.4,('Excessive entry floor correction',max(lifts))
    for frame,world in enumerate(warped):
        shift=seat_matrix.to_3x3().inverted()@Vector((0,0,lifts[frame]))
        warped[frame]={n:Matrix.Translation(shift)@m for n,m in world.items()}
    name=f'lz_{"exit" if leaving else "enter"}_{a.section[4:]}_{a.seat:02}'
    action=bpy.data.actions.new(name);actor.animation_data.action=action;action.xray.fps=30;action.xray.speed=1
    for frame,base in enumerate(sequence):
        scene.frame_set(frame)
        t=body_t(frame);weight=smooth((t-.25)/.75) if leaving else 1-smooth(t/.75)
        # Correct model height at the standing endpoint without changing bones.
        world=warped[frame];apply(world)
        floor_samples.append(minimum_height()-ground)
        assert floor_samples[-1]>=.005,('Entry skin below ground',name,frame,floor_samples[-1])
        for bone in order:
            error=(bone.matrix.translation-world[bone.name].translation).length
            assert error<.0001,('Preview pose differs',name,frame,bone.name,error)
            for channel in ('location','rotation_quaternion','scale'):bone.keyframe_insert(channel,frame=frame)
        for bone in order:
            if bone.parent and bone.name not in ('bip01','bip01_pelvis'):
                assert abs((world[bone.name].translation-world[bone.parent.name].translation).length-(rest[bone.name].translation-rest[bone.parent.name].translation).length)<.001
        samples.append(dict(motion=name,frame=frame,frames=frames,matrices={n:[list(r) for r in m] for n,m in world.items()}))
        if frame in (0,frames//2,frames-1):
            if a.render:
                if door:
                    opened=door_open(frame)
                    car.pose.bones[door.name].rotation_euler[door_axis]=door_angle*opened
                bpy.context.view_layer.update()
                centre=seat_point+Vector((0,0,.2));camera.location=centre+Vector((-3,-4,2));camera.rotation_euler=(centre-camera.location).to_track_quat('-Z','Y').to_euler()
                scene.render.filepath=str(a.out/f'{name}-{frame:03}.png');bpy.ops.render.render(write_still=True)
    for curve in action.fcurves:
        for key in curve.keyframe_points:key.interpolation='LINEAR'
    actor.xray.motions_collection.add().name=name
    outside=seat_matrix@stand['bip01'].translation+standing_shift
    assert abs(outside.x-standing_x)<.001 and abs(outside.y-standing_y)<.001
    metadata.append(dict(motion=name,frames=frames,source_frames=source_frames,door_lead_frames=lead,door_trail_frames=trail,duration_ms=round((frames-1)/30*1000),standing_root_blender=list(outside),ground_correction_metres=vertical,standing_margin_metres=.45,maximum_cycle_floor_lift_metres=max(lifts),minimum_skin_above_ground_metres=min(floor_samples),floor_violation_keys=[i for i,h in enumerate(floor_samples) if h<-.01]))
bpy.ops.object.select_all(action='DESELECT');actor.select_set(True);bpy.context.view_layer.objects.active=actor
if a.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=str(a.out/'candidate.blend'))
assert bpy.ops.xray_export.omf_file(filepath=str(a.out/'candidate.omf'),high_quality=True,fmt_ver='cscop')=={'FINISHED'}
readback=reader.Motions(a.out/'candidate.omf',a.actor);worst=0
for sample in samples:
    actual=pose(readback,sample['motion'],sample['frame']/sample['frames'])
    for name,matrix in sample['matrices'].items():worst=max(worst,(actual[name].translation-Matrix(matrix).translation).length)
assert worst<.001,worst
(a.out/'review.json').write_text(json.dumps(dict(installed=False,section=a.section,seat=a.seat,layout_sha256=hashlib.sha256(layout_path.read_bytes()).hexdigest(),driver_sha256=hashlib.sha256(driver_path.read_bytes()).hexdigest() if a.seat==0 else None,model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),door=None if not door else door.name,door_axis=None if not door else door_axis,door_angle=None if not door else door_angle,door_hinge=door_hinge,door_helper_sha256=hashlib.sha256((root/'tools/vehicle-door-review.py').read_bytes()).hexdigest(),motions=metadata,roundtrip_max_error_metres=worst,candidate_sha256=hashlib.sha256((a.out/'candidate.omf').read_bytes()).hexdigest()),indent=2)+'\n')
print('CAPTURED_TRANSITIONS_REVIEW_READY',a.section,a.seat,worst)
