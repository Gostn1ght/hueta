"""Build vehicle transitions on the actual human skeleton in offline Blender.

Stock chair movement supplies the leg articulation; joint-local blending
retargets it to the real driver/passenger poses with the seated hip at zero.
No game executable is run and no existing motion is replaced.
"""
import argparse,importlib.util,math,sys
from pathlib import Path
import addon_utils,bpy
from mathutils import Matrix

p=argparse.ArgumentParser()
p.add_argument('--template',type=Path,required=True)
p.add_argument('--addons',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--gamma',type=Path,required=True)
args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
root=Path(__file__).resolve().parents[1]
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
reader=module('poses',root/'scripts/read-omf-poses.py')
merge=module('merge',root/'scripts/tools/merge-player-anims.py')
stock=root/'scripts/netcoop-overlay/client/meshes/actors/stalker_animation.omf'
chair=reader.Motions(args.gamma/'meshes/actors/stalker_smart_cover_animation.omf',args.template)
driver=reader.Motions(stock,args.template)
sys.path.insert(0,str(args.addons.resolve()))
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
bpy.ops.xray_import.ogf(directory=str(args.template.parent),files=[{'name':args.template.name}],import_motions=False)
rig=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
assert len(rig.data.bones)==47
for name,bones in merge.parse(stock)['parts']:
 collection=rig.data.collections.new(name)
 for bone,_ in bones:collection.assign(rig.data.bones[bone])
for action in list(bpy.data.actions):bpy.data.actions.remove(action)
rig.xray.motions_collection.clear();rig.animation_data_create()
order=sorted(rig.pose.bones,key=lambda b:len(b.parent_recursive))
for b in order:
 for c in list(b.constraints):b.constraints.remove(c)
 b.rotation_mode='QUATERNION'
# Game coordinates -> imported Blender coordinates, including rotation basis.
c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)))
def locals_for(source,name,fraction,hip_zero=False):
 world=source.pose(name,fraction,matrices=True)
 shift=world['bip01_pelvis'][:3,3].copy() if hip_zero else world['bip01'][:3,3].copy()*0
 if not hip_zero:
  # In-place: the authority moves the body between outside feet and seat hip.
  shift[0]=world['bip01'][0,3];shift[2]=world['bip01'][2,3]
 poses={}
 for n,m in world.items():
  a=Matrix(m.tolist());a.translation-=__import__('mathutils').Vector(shift.tolist());poses[n]=c@a@c
 return {b.name:poses[b.parent.name].inverted()@poses[b.name] if b.parent else poses[b.name] for b in order}
targets={'driver':locals_for(driver,'steering_idle_0_0',.2,True),
         'passenger':locals_for(chair,'animpoint_sit_high_idle_1',.2,True)}
def smooth(x):return x*x*(3-2*x)
def emit(name,poses_at,frames,once):
 action=bpy.data.actions.new(name);action.use_fake_user=True;action.xray.fps=30;action.xray.speed=1
 rig.animation_data.action=action
 for frame in range(frames):
  bpy.context.scene.frame_set(frame);locals=poses_at(frame/(frames-1));world={}
  for b in order:
   world[b.name]=world[b.parent.name]@locals[b.name] if b.parent else locals[b.name]
   kwargs={} if b.parent is None else dict(parent_matrix=world[b.parent.name],parent_matrix_local=b.parent.bone.matrix_local)
   b.matrix_basis=b.bone.convert_local_to_pose(world[b.name],b.bone.matrix_local,invert=True,**kwargs)
   b.keyframe_insert('location',frame=frame);b.keyframe_insert('rotation_quaternion',frame=frame);b.keyframe_insert('scale',frame=frame)
 for curve in action.fcurves:
  for k in curve.keyframe_points:k.interpolation='LINEAR'
 item=rig.xray.motions_collection.add();item.name=name
emit('lz_vehicle_passenger',lambda t:targets['passenger'],2,False)
for role,target in targets.items():
 for exit in (False,True):
  def pose(t,exit=exit,target=target):
   u=1-t if exit else t
   source=locals_for(chair,'lead_0_sit_down_0',min(.98,u))
   w=smooth(max(0,min(1,(u-.30)/.70)))
   result={n:source[n].lerp(target[n],w) for n in source}
   # Reach toward the outer door before stepping in and before closure.
   # Exit uses the exact reverse articulation, including the two hand reaches.
   reach=math.sin(math.pi*u/.30) if u<.30 else math.sin(math.pi*(u-.65)/.35) if u>.65 else 0.
   side='l' if role=='driver' else 'r';sign=1 if side=='l' else -1
   arm='bip01_'+side+'_upperarm';forearm='bip01_'+side+'_forearm'
   result[arm]=result[arm]@Matrix.Rotation(sign*math.radians(45)*reach,4,'Y')
   result[forearm]=result[forearm]@Matrix.Rotation(math.radians(25)*reach,4,'X')
   return result
  emit('lz_vehicle_'+('exit_' if exit else 'enter_')+role,pose,55,True)
bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);bpy.context.view_layer.objects.active=rig
args.output.parent.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output.with_suffix('.blend')))
assert bpy.ops.xray_export.omf_file(filepath=str(args.output))=={'FINISHED'}
print('VEHICLE_TRANSITIONS_EXPORTED',args.output)
