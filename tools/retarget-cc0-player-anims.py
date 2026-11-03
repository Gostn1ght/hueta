"""Offline CC0 motion retarget candidate; output is separate from active game data.

Run with portable Blender --background --python this_file -- --template ACTOR.ogf
--addons XRAY_ADDON_DIRECTORY --output PRIVATE_REVIEW_DIRECTORY.
Only crawl, pistol prone idle and driving are supplied: no door/entry clips.
"""
import sys, json, math, importlib.util
from pathlib import Path
import bpy, addon_utils
from mathutils import Matrix, Vector
import argparse, hashlib
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--donors',type=Path,default=root/'assets/animations/mesh2motion')
p.add_argument('--template',type=Path,required=True)
p.add_argument('--addons',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
base=args.donors;out=args.output;out.mkdir(parents=True,exist_ok=True)
provenance=json.loads((base/'provenance.json').read_text(encoding='utf-8'))
for row in provenance['files']:
 if 'blender_input' in row:
  assert hashlib.sha256((base/row['blender_input']).read_bytes()).hexdigest()==row['blender_input_sha256'],row['blender_input']
sys.path.insert(0,str(args.addons.resolve()))
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
template=args.template
bpy.ops.xray_import.ogf(directory=str(template.parent),files=[{'name':template.name}],import_motions=False)
target=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
target_meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
assert len(target.data.bones)==47
rest={b.name:b.matrix_local.copy() for b in target.data.bones}
order=sorted(target.pose.bones,key=lambda b:len(b.parent_recursive))
for b in order:
 for c in list(b.constraints):b.constraints.remove(c)
 b.rotation_mode='QUATERNION'
spec=importlib.util.spec_from_file_location('merge',root/'scripts/tools/merge-player-anims.py')
merge=importlib.util.module_from_spec(spec);spec.loader.exec_module(merge)
for name,bones in merge.parse(root/'scripts/netcoop-overlay/client/meshes/actors/stalker_animation.omf')['parts']:
 collection=target.data.collections.new(name)
 for name,_ in bones:collection.assign(target.data.bones[name])
target.xray.motions_collection.clear();target.animation_data_create()
mapping={'bip01_pelvis':'pelvis','bip01_spine':'spine_01','bip01_spine1':'spine_02','bip01_spine2':'spine_03','bip01_neck':'neck_01','bip01_head':'head'}
for side in ('l','r'):
 for dest,source in [('clavicle','clavicle'),('upperarm','upperarm'),('forearm','lowerarm'),('hand','hand'),('thigh','thigh'),('calf','calf'),('foot','foot'),('toe0','ball')]:
  mapping['bip01_'+side+'_'+dest]=source+'_'+side
 for finger,source in [('0','thumb'),('1','index'),('2','middle')]:
  for index,suffix in [(1,''),(2,'1'),(3,'2')]:mapping['bip01_'+side+'_finger'+finger+suffix]=source+f'_{index:02d}_'+side
# The donor faces -Y; the actual game actor faces +Y. Both use Z up here.
align=Matrix.Rotation(math.pi,4,'Z')
successor={'bip01_pelvis':'bip01_spine','bip01_spine':'bip01_spine1','bip01_spine1':'bip01_spine2','bip01_spine2':'bip01_neck','bip01_neck':'bip01_head'}
for side in ('l','r'):
 for a,b in [('clavicle','upperarm'),('upperarm','forearm'),('forearm','hand'),('thigh','calf'),('calf','foot'),('foot','toe0')]:successor['bip01_'+side+'_'+a]='bip01_'+side+'_'+b
samples=[];snapshots=[];actions=[]
clay=bpy.data.materials.new('Review actual game actor');clay.diffuse_color=(.38,.48,.39,1)
for obj in target_meshes:obj.data.materials.clear();obj.data.materials.append(clay)
for row,(file,name) in enumerate([('crawl-plain.glb','review_cc0_crawl'),('pistol-prone-plain.glb','review_cc0_pistol_prone'),('driving-plain.glb','review_cc0_driving')]):
 before=set(bpy.data.objects)
 bpy.ops.import_scene.gltf(filepath=str(base/file))
 imported=set(bpy.data.objects)-before;donor=next(o for o in imported if o.type=='ARMATURE')
 source_action=donor.animation_data.action;start,end=source_action.frame_range
 source_rest={b.name:align@donor.matrix_world@b.matrix_local for b in donor.data.bones}
 source_leg=(source_rest['thigh_l'].translation-source_rest['calf_l'].translation).length+(source_rest['calf_l'].translation-source_rest['foot_l'].translation).length
 target_leg=(rest['bip01_l_thigh'].translation-rest['bip01_l_calf'].translation).length+(rest['bip01_l_calf'].translation-rest['bip01_l_foot'].translation).length
 scale=target_leg/source_leg
 corrections={}
 for dst,src in mapping.items():
  q=Matrix.Identity(3).to_quaternion()
  if dst in successor:
   nxt=successor[dst];src_next=mapping[nxt]
   a=rest[nxt].translation-rest[dst].translation;b=source_rest[src_next].translation-source_rest[src].translation
   if a.length>1e-5 and b.length>1e-5:q=a.rotation_difference(b)
  corrections[dst]=source_rest[src].to_quaternion().inverted()@q@rest[dst].to_quaternion()
 action=bpy.data.actions.new(name);action.use_fake_user=True;action.xray.fps=30;action.xray.speed=1
 target.animation_data.action=action;actions.append(action)
 frames=round((end-start)/24*30)+1
 for frame in range(frames):
  source_time=start+(end-start)*frame/(frames-1)
  bpy.context.scene.frame_set(math.floor(source_time),subframe=source_time-math.floor(source_time));bpy.context.view_layer.update()
  world={}
  for bone in order:
   parent=bone.parent;dst=bone.name
   if dst in mapping:
    src=mapping[dst];source_pose=align@donor.matrix_world@donor.pose.bones[src].matrix
    pose=(source_pose.to_quaternion()@corrections[dst]).to_matrix().to_4x4()
    if dst=='bip01_pelvis':pose.translation=source_pose.translation*scale
    else:pose.translation=(world[parent.name]@rest[parent.name].inverted()@rest[dst]).translation
   else:pose=world[parent.name]@rest[parent.name].inverted()@rest[dst] if parent else rest[dst].copy()
   world[dst]=pose
   kwargs={} if parent is None else dict(parent_matrix=world[parent.name],parent_matrix_local=parent.bone.matrix_local)
   bone.matrix_basis=bone.bone.convert_local_to_pose(pose,bone.bone.matrix_local,invert=True,**kwargs)
   bone.keyframe_insert('location',frame=frame);bone.keyframe_insert('rotation_quaternion',frame=frame);bone.keyframe_insert('scale',frame=frame)
  bpy.context.view_layer.update()
 for curve in action.fcurves:
  for k in curve.keyframe_points:k.interpolation='LINEAR'
 item=target.xray.motions_collection.add();item.name=name
 for col,fraction in enumerate([0,.25,.5,.75]):
  bpy.context.scene.frame_set(round((frames-1)*fraction));bpy.context.view_layer.update()
  samples.append(dict(clip=name,fraction=fraction,frame=round((frames-1)*fraction),frames=frames,points={n:list(target.pose.bones[n].matrix.translation) for n in ['bip01_head','bip01_pelvis','bip01_l_hand','bip01_r_hand','bip01_l_foot','bip01_r_foot']}))
  for obj in target_meshes:
   mesh=bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
   snap=bpy.data.objects.new(f'{name}_{fraction}',mesh);bpy.context.collection.objects.link(snap)
   snap.matrix_world=obj.matrix_world.copy();snap.location+=Vector((col*2.9,row*3.5,0));snap.hide_render=True;snapshots.append(snap)
 for obj in imported:bpy.data.objects.remove(obj,do_unlink=True)
 print('RETARGETED',name,frames,'leg scale',scale,flush=True)
target.animation_data.action=actions[0]
bpy.ops.object.select_all(action='DESELECT');target.select_set(True);bpy.context.view_layer.objects.active=target
bpy.ops.wm.save_as_mainfile(filepath=str(out/'candidate.blend'))
assert bpy.ops.xray_export.omf_file(filepath=str(out/'candidate.omf'))=={'FINISHED'}
(out/'samples.json').write_text(json.dumps(samples,indent=2)+'\n')
# Read the exported GAME keyframes back independently: the Blender preview
# alone does not prove that bone coordinates survived OMF conversion.
spec=importlib.util.spec_from_file_location('poses',root/'scripts/read-omf-poses.py')
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
exported=reader.Motions(out/'candidate.omf',template);worst=0
for row in samples:
 pose=exported.pose(row['clip'],row['frame']/row['frames'])
 for bone,expected in row['points'].items():
  actual=pose[bone]
  worst=max(worst,(Vector((actual[0],actual[2],actual[1]))-Vector(expected)).length)
assert worst<.001,('OMF roundtrip changed the reviewed pose',worst)
(out/'roundtrip.json').write_text(json.dumps(dict(max_error_metres=worst,samples=len(samples),clips=list(exported.motions),source_commit=provenance['commit'],template_sha256=hashlib.sha256(template.read_bytes()).hexdigest(),candidate_sha256=hashlib.sha256((out/'candidate.omf').read_bytes()).hexdigest()),indent=2)+'\n')
print('OMF_ROUNDTRIP_MAX_ERROR_METRES',worst,flush=True)
for obj in target_meshes:obj.hide_render=True
target.hide_render=True
for obj in snapshots:obj.hide_render=False
scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE_NEXT';scene.render.resolution_x=1800;scene.render.resolution_y=1200;scene.render.resolution_percentage=100
scene.world=bpy.data.worlds.new('Review World');scene.world.color=(.12,.12,.12)
bpy.ops.mesh.primitive_plane_add(size=60,location=(4.2,3.5,-.06));floor=bpy.context.object
material=bpy.data.materials.new('Floor');material.diffuse_color=(.16,.18,.20,1);floor.data.materials.append(material)
for loc,power in [((3,-5,10),2200),((-5,4,8),1800),((9,10,10),2200)]:
 bpy.ops.object.light_add(type='AREA',location=loc);lamp=bpy.context.object;lamp.data.energy=power;lamp.data.size=8;lamp.rotation_euler=(Vector((4.2,3.5,0))-lamp.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(12,-12,12));camera=bpy.context.object;camera.rotation_euler=(Vector((4.2,3.5,.2))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=15;scene.camera=camera
scene.render.filepath=str(out/'actual-game-actor-review.png');bpy.ops.render.render(write_still=True)
print('PRIVATE_REVIEW_READY',out,flush=True)
