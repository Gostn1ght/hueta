"""Offline model-specific wheel grips from an owner-retargeted Mixamo motion.

Produces private OMF candidates and a binding report. Does not install assets.
Wheel vertices, seat matrices and steering pivot come from each actual DCP OGF.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import addon_utils
import bpy
from mathutils import Matrix, Vector

p=argparse.ArgumentParser(description=__doc__)
for name in ('actor','addons','source','out'):
    p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--section',action='append')
p.add_argument('--fit-overrides',type=Path,help='Private geometry-reviewed joint adjustments keyed by visual; model SHA required')
p.add_argument('--layouts',type=Path,help='Private seat layout candidate; source layout remains unchanged')
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.out.mkdir(parents=True,exist_ok=True)
overrides=json.loads(a.fit_overrides.read_text(encoding='utf-8')) if a.fit_overrides else {}
(a.out/'review.json').unlink(missing_ok=True)
root=Path(__file__).resolve().parents[1];overlay=root/'scripts/netcoop-overlay/client'
sys.path.insert(0,str(a.addons));bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
bpy.ops.xray_import.ogf(directory=str(a.actor.parent),files=[{'name':a.actor.name}],import_motions=False)
target=next(o for o in bpy.data.objects if o.type=='ARMATURE');target.animation_data_create()
order=sorted(target.pose.bones,key=lambda b:len(b.parent_recursive))
rest={b.name:b.matrix_local.copy() for b in target.data.bones}
for bone in order:
    for constraint in list(bone.constraints):bone.constraints.remove(constraint)
    bone.rotation_mode='QUATERNION'
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
merge=module('merge',root/'scripts/tools/merge-player-anims.py')
reader=module('poses',root/'scripts/read-omf-poses.py')
parts=merge.parse(overlay/'meshes/actors/stalker_animation.omf')['parts']
for name,bones in parts:
    collection=target.data.collections.new(name)
    for bone,_ in bones:collection.assign(target.data.bones[bone])
target.xray.motions_collection.clear()
source_review=json.loads((a.source/'review.json').read_text())
assert source_review['source']=='https://www.mixamo.com/' and source_review['raw_files_private']
assert hashlib.sha256((a.source/'candidate.omf').read_bytes()).hexdigest()==source_review['candidate_sha256']
motion=reader.Motions(a.source/'candidate.omf',a.actor)
source_name=source_review['clips'][0]['clip'];frames=source_review['clips'][0]['frames']
c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)));s=Matrix.Diagonal((1,1,-1,1))
poses=[{n:c@Matrix(m.tolist())@s for n,m in motion.pose(source_name,i/frames,matrices=True).items()} for i in range(frames)]
# Reuse the same two-bone solver as the official retargeter. This is our own
# checked-in source, not downloaded executable content.
code=(root/'tools/retarget-mixamo-player-anims.py').read_text()
scope=dict(Matrix=Matrix,Vector=Vector,math=math,order=order,a=SimpleNamespace(weapon_grip=None))
exec(code[code.index('def fit_hands('):code.index('\ndef fit_weapon(')],scope)
fit_hands=scope['fit_hands']
rows={r['section']:r for r in json.loads((root/'docs/audit/169_FLEET_SEATS_AND_DECKS.json').read_text())['rows']}
layout_path=a.layouts or root/'tools/dcp-seat-layouts.json'
layouts=json.loads(layout_path.read_text(encoding='utf-8'))
models={};current=None
for line in (overlay/'configs/mod_system_lz_dcp_vehicles.ltx').read_text(encoding='cp1251').splitlines():
    if line.startswith('['):current=line.split(']')[0][1:]
    elif line.startswith('visual ='):models[current]=line.split('=',1)[1].strip().replace('\\','/')
stock=reader.Motions(overlay/'meshes/actors/stalker_animation.omf',a.actor)
passengers=reader.Motions(overlay/'meshes/actors/modded_stalker_animations/netcoop_vehicle_passengers.omf',a.actor)
leg_fits=json.loads((root/'tools/dcp-seat-pose-fits.json').read_text())
selected=a.section or sorted(set(rows)&set(models));report=[];expected={}
for section in selected:
    visual=models[section];path=overlay/'meshes'/visual
    before=set(bpy.data.objects);actions_before=set(bpy.data.actions)
    try:
        adjustment=overrides.get(visual,{})
        if adjustment:
            assert adjustment['model_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
            assert 0<=adjustment['torso_lean_degrees']<=45
            for key in ('left_elbow_swivel','right_elbow_swivel','right_knee_pitch','right_ankle_pitch'):
                assert math.isfinite(adjustment.get(key,0)) and abs(adjustment.get(key,0))<=60,key
            assert isinstance(adjustment.get('stabilize_head',False),bool)
            assert math.isfinite(adjustment.get('neck_pitch_degrees',0)) and abs(adjustment.get('neck_pitch_degrees',0))<=15
        bpy.ops.xray_import.ogf(directory=str(path.parent),files=[{'name':path.name}],import_motions=False)
        imported=set(bpy.data.objects)-before
        rig=next(o for o in imported if o.type=='ARMATURE')
        wheel=next(b for b in rig.data.bones if any(v in b.name.lower() for v in ('stearing_wheel','steering_wheel','stear_wheel')))
        seat=layouts[visual]['seats'][0];game=Matrix(rows[section]['seat_matrices_game'][seat['bone']])
        game.translation+=Vector(seat['offset']);seat_matrix=c@(game@Matrix.Rotation(math.radians(seat['yaw']),4,'Y'))@c
        inverse=seat_matrix.inverted();wheel_name=wheel.name; pivot=inverse@rig.matrix_world@wheel.matrix_local
        points=[]
        for obj in imported:
            if obj.type!='MESH' or wheel.name not in obj.vertex_groups:continue
            group=obj.vertex_groups[wheel.name].index
            points.extend(inverse@obj.matrix_world@v.co for v in obj.data.vertices if any(g.group==group and g.weight>.5 for g in v.groups))
        assert len(points)>20,'no physical steering-wheel mesh'
        local=[pivot.inverted()@v for v in points]
        lo=Vector(tuple(min(v[i] for v in local) for i in range(3)));hi=Vector(tuple(max(v[i] for v in local) for i in range(3)))
        centre=(lo+hi)/2;radius=max(hi.x-lo.x,hi.y-lo.y)/2
        assert .08<radius<.6,('wheel radius',radius)
        contacts={label:min(points,key=lambda v:(pivot.inverted()@v-(centre+Vector((sign*.86*radius,.5*radius,0)))).length_squared) for label,sign in [('r',1),('l',-1)]}
        # Bone axes can point in either direction across donors. Physical right
        # and left are established in actor space, not inferred from bone names.
        contacts=dict(zip(('l','r'),sorted(contacts.values(),key=lambda v:v.x)))
        for obj in imported:bpy.data.objects.remove(obj,do_unlink=True)
        lower_clip=leg_fits.get(visual,{}).get('pose','steering_idle_0_0')
        lower_source=passengers if lower_clip.startswith('lz_vehicle_passenger_') else stock
        lower={n:c@Matrix(m.tolist())@s for n,m in lower_source.pose(lower_clip,.2,matrices=True).items()}
        lower_origin=lower['bip01_pelvis'].inverted()
        clips=[];model_expected={};max_error=0
        def fitted_world(base,angle,lean_degrees):
            world={n:m.copy() for n,m in base.items()}
            # Keep previously fitted leg articulation. Applying one captured
            # car's foot height to a low coupe would push feet through its floor.
            for bone in order:
                if any(parent.name in ('bip01_l_thigh','bip01_r_thigh') for parent in [bone,*bone.parent_recursive]):
                    world[bone.name]=world['bip01_pelvis']@lower_origin@lower[bone.name]
            pelvis=world['bip01_pelvis'].translation
            lean=Matrix.Translation(pelvis)@Matrix.Rotation(math.radians(-lean_degrees),4,'X')@Matrix.Translation(-pelvis)
            for bone in order:
                if bone.name=='bip01_spine' or any(p.name=='bip01_spine' for p in bone.parent_recursive):world[bone.name]=lean@world[bone.name]
            if adjustment.get('stabilize_head',False):
                # A donor's incidental head bob/look can hit a low coupe roof.
                # Keep its neutral joint-local hold while the chest still moves;
                # rotate about the neck joint, without shortening the neck.
                for bone in order:
                    if bone.name!='bip01_neck' and not any(p.name=='bip01_neck' for p in bone.parent_recursive):continue
                    name=bone.name;parent=bone.parent.name
                    world[name]=world[parent]@poses[0][parent].inverted()@poses[0][name]
                    if name=='bip01_neck':
                        origin=world[name].translation
                        rotation=Matrix.Translation(origin)@Matrix.Rotation(math.radians(adjustment.get('neck_pitch_degrees',0)),4,'X')@Matrix.Translation(-origin)
                        world[name]=rotation@world[name]
            turn=pivot@Matrix.Rotation(angle,4,'Z')@pivot.inverted()
            desired={n:m.copy() for n,m in world.items()}
            for label in ('r','l'):
                hand='bip01_'+label+'_hand';anchor='bip01_'+label+'_finger1'
                shift=contacts[label]-world[anchor].translation
                for bone in order:
                    if bone.name==hand or any(p.name==hand for p in bone.parent_recursive):desired[bone.name]=turn@Matrix.Translation(shift)@world[bone.name]
            fit_hands(world,desired)
            # Swivel each elbow about the fixed shoulder/wrist line. Hands and
            # all fingers keep the wheel grip, while neither arm bone stretches.
            for label,key in (('l','left_elbow_swivel'),('r','right_elbow_swivel')):
                origin=world[f'bip01_{label}_upperarm'].translation
                endpoint=world[f'bip01_{label}_hand'].translation
                rotation=Matrix.Translation(origin)@Matrix.Rotation(math.radians(adjustment.get(key,0)),4,(endpoint-origin).normalized())@Matrix.Translation(-origin)
                for part in ('upperarm','forearm'):
                    name=f'bip01_{label}_{part}';world[name]=rotation@world[name]
            for joint,key in (('bip01_r_calf','right_knee_pitch'),('bip01_r_foot','right_ankle_pitch')):
                origin=world[joint].translation
                rotation=Matrix.Translation(origin)@Matrix.Rotation(math.radians(adjustment.get(key,0)),4,'X')@Matrix.Translation(-origin)
                for bone in order:
                    if bone.name==joint or any(parent.name==joint for parent in bone.parent_recursive):world[bone.name]=rotation@world[bone.name]
            return world,turn
        # Choose one constant torso lean per model, across the complete idle
        # and steering sweep. Never change hip/seat position or stretch arms.
        lean_degrees=None
        samples=[(pose,0) for pose in poses]+[(poses[0],angle) for angle in (-.6,-.3,0,.3,.6)]
        for trial in ([adjustment['torso_lean_degrees']] if adjustment else range(0,31,3)):
            try:
                for base,angle in samples:fitted_world(base,angle,trial)
                lean_degrees=trial;break
            except AssertionError:pass
        assert lean_degrees is not None,('wheel unreachable without excessive torso lean',{k:list(v) for k,v in contacts.items()})
        for mode in ('idle','left','right'):
            name='lz_drive_'+section.removeprefix('dcp_')+'_'+mode
            count=frames if mode=='idle' else 31;worlds=[]
            for i in range(count):
                angle=0 if mode=='idle' else (-.6 if mode=='left' else .6)*i/(count-1)
                world,turn=fitted_world(poses[i if mode=='idle' else 0],angle,lean_degrees)
                for label in ('r','l'):
                    error=(world['bip01_'+label+'_finger1'].translation-turn@contacts[label]).length
                    max_error=max(max_error,error);assert error<.00001,error
                for bone in order:
                    if bone.parent and bone.name not in ('bip01','bip01_pelvis'):
                        length=(world[bone.name].translation-world[bone.parent.name].translation).length
                        expected_length=(rest[bone.name].translation-rest[bone.parent.name].translation).length
                        assert abs(length-expected_length)<.001,('Joint length changed',name,i,bone.name,length,expected_length)
                worlds.append(world)
            # Commit the action only after every frame passes arm reach checks.
            action=bpy.data.actions.new(name);action.use_fake_user=True;action.xray.fps=30;action.xray.speed=1
            target.animation_data.action=action
            for i,world in enumerate(worlds):
                bpy.context.scene.frame_set(i)
                for bone in order:
                    kwargs={} if bone.parent is None else dict(parent_matrix=world[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
                    bone.matrix_basis=bone.bone.convert_local_to_pose(world[bone.name],bone.bone.matrix_local,invert=True,**kwargs)
                    bone.keyframe_insert('location',frame=i);bone.keyframe_insert('rotation_quaternion',frame=i);bone.keyframe_insert('scale',frame=i)
            for curve in action.fcurves:
                for key in curve.keyframe_points:key.interpolation='LINEAR'
            item=target.xray.motions_collection.add();item.name=name;clips.append(name)
            model_expected[name]=[(i,{n:m.copy() for n,m in worlds[i].items()}) for i in sorted({0,count//2,count-1})]
        expected.update(model_expected)
        report.append(dict(section=section,visual=visual,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),clips=clips,wheel=wheel_name,torso_lean_degrees=lean_degrees,lower_body_motion=lower_clip,geometry_adjustment=adjustment,contacts={k:list(v) for k,v in contacts.items()},max_contact_error_metres=max_error))
        print('FITTED_DRIVER',section,flush=True)
    except (AssertionError,StopIteration) as error:
        for obj in set(bpy.data.objects)-before:bpy.data.objects.remove(obj,do_unlink=True)
        for action in set(bpy.data.actions)-actions_before:
            for i in range(len(target.xray.motions_collection)-1,-1,-1):
                if target.xray.motions_collection[i].name==action.name:target.xray.motions_collection.remove(i)
            bpy.data.actions.remove(action)
        report.append(dict(section=section,skipped=str(error)))
        print('SKIPPED_DRIVER',section,str(error),flush=True)
bpy.ops.object.select_all(action='DESELECT');target.select_set(True);bpy.context.view_layer.objects.active=target
assert expected,'no reachable wheel grips'
bpy.ops.wm.save_as_mainfile(filepath=str(a.out/'candidate.blend'))
assert bpy.ops.xray_export.omf_file(filepath=str(a.out/'candidate.omf'),high_quality=True,fmt_ver='cscop')=={'FINISHED'}
exported=reader.Motions(a.out/'candidate.omf',a.actor);worst=0
for name,samples in expected.items():
    count=frames if name.endswith('_idle') else 31
    for i,world in samples:
        actual={n:c@Matrix(m.tolist())@s for n,m in exported.pose(name,i/count,matrices=True).items()}
        for bone in order:
            worst=max(worst,(actual[bone.name].translation-world[bone.name].translation).length)
assert worst<.001,worst
(a.out/'review.json').write_text(json.dumps(dict(source=source_review,rows=report,layout_sha256=hashlib.sha256(layout_path.read_bytes()).hexdigest(),roundtrip_max_error_metres=worst,installed=False,candidate_sha256=hashlib.sha256((a.out/'candidate.omf').read_bytes()).hexdigest()),indent=2)+'\n')
print('FLEET_DRIVER_READY',len(expected)//3,'models',worst,flush=True)
