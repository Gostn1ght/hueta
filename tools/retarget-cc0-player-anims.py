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
p.add_argument('--clip',action='append',help='source.glb=motion_name; repeat for a custom review set')
p.add_argument('--seat-origin',action='store_true',help='Place the pelvis at the seat anchor, without changing its orientation')
p.add_argument('--seat-fit',action='append',default=[],help='Review only: motion_name:ankle_drop_metres; fit feet and hands to a seated pose, preserving limb lengths')
p.add_argument('--seat-foot-forward',action='append',default=[],help='motion_name:metres; shorter footwell for compact cabins (default 0.4)')
p.add_argument('--prone-grounded',action='store_true',help='Review only: reduce crawl knee tuck, level feet and turn the head forward; not a weapon grip')
p.add_argument('--prone-grip',choices=['knife','pistol','rifle','launcher'],help='Review only: use the game skeleton\'s real weapon hand/finger pose; not a complete locomotion set')
p.add_argument('--grip-hand-dependence',type=int,choices=[1,2],default=1,help='Actual weapon LTX hand_dependence for the review')
p.add_argument('--prone-stock-idle',action='store_true',help='Review composite: body from existing X-Ray loophole_prone_visual instead of CC0 (not CC0 output)')
args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
assert not (args.prone_grounded and args.seat_origin), 'Prone and seated fitting are separate reviews'
assert not args.prone_grip or args.prone_grounded, 'Weapon review requires the grounded body review'
assert not args.prone_stock_idle or args.prone_grip, 'Stock body composite is an armed idle review'
seat_fits={}
for value in args.seat_fit:
 name,drop=value.split(':');drop=float(drop)
 assert args.seat_origin and .12<=drop<=.65, 'Seat fitting requires a pelvis origin and a supported chair height'
 assert name not in seat_fits
 seat_fits[name]=drop
seat_forward={}
for value in args.seat_foot_forward:
 name,forward=value.split(':');forward=float(forward)
 assert name in seat_fits and .2<=forward<=.6
 assert name not in seat_forward
 seat_forward[name]=forward
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

def seat_limb(world, first, middle, last, endpoint, pole):
 """Two-bone fit in model space; rotate complete subtrees, never scale bones."""
 origin=world[first].translation.copy();joint=world[middle].translation.copy();end=world[last].translation.copy()
 upper=(joint-origin).length;lower=(end-joint).length;delta=endpoint-origin;distance=delta.length
 assert abs(upper-lower)+.0001<distance<upper+lower-.0001, (first,'unreachable seat fit',distance,upper,lower)
 axis=delta/distance;along=(upper*upper-lower*lower+distance*distance)/(2*distance)
 bend=pole-axis*pole.dot(axis);assert bend.length>.0001;bend.normalize()
 elbow=origin+axis*along+bend*math.sqrt(max(0,upper*upper-along*along))
 original_end_rotation=world[last].to_quaternion()
 def rotate_branch(bone,desired):
  child=middle if bone==first else last;start=world[bone].translation.copy()
  rotation=(world[child].translation-start).rotation_difference(desired-start).to_matrix().to_4x4()
  transform=Matrix.Translation(start)@rotation@Matrix.Translation(-start)
  for descendant in order:
   if descendant.name==bone or any(parent.name==bone for parent in descendant.parent_recursive):world[descendant.name]=transform@world[descendant.name]
 rotate_branch(first,elbow);rotate_branch(middle,endpoint)
 # Keep the donor's foot/hand orientation; propagate its correction to toes/fingers.
 final=original_end_rotation.to_matrix().to_4x4();final.translation=world[last].translation
 transform=final@world[last].inverted()
 for descendant in order:
  if descendant.name==last or any(parent.name==last for parent in descendant.parent_recursive):world[descendant.name]=transform@world[descendant.name]
 assert (world[last].translation-endpoint).length<.0001

def fit_seat(world, drop, forward):
 for side,sign in [('l',-1),('r',1)]:
  prefix='bip01_'+side+'_'
  seat_limb(world,prefix+'thigh',prefix+'calf',prefix+'foot',
            Vector((sign*.12,forward,-drop)),Vector((0,1,0)))
  thigh=world[prefix+'thigh'].translation;knee=world[prefix+'calf'].translation
  support=thigh.lerp(knee,.4)
  hand=Vector((sign*.16,support.y,max(.15,support.z+.09)))
  seat_limb(world,prefix+'upperarm',prefix+'forearm',prefix+'hand',hand,
            Vector((sign*.08, -1, -.1)))

def orient_branch(world, bone, rotation):
 final=rotation.to_matrix().to_4x4();final.translation=world[bone].translation
 transform=final@world[bone].inverted()
 for descendant in order:
  if descendant.name==bone or any(parent.name==bone for parent in descendant.parent_recursive):world[descendant.name]=transform@world[descendant.name]

def ground_prone(world):
 """Keep donor timing, with a lower knee tuck on the game's actual limb lengths."""
 hip=world['bip01_pelvis'].translation
 for side,sign in [('l',-1),('r',1)]:
  prefix='bip01_'+side+'_';foot=world[prefix+'foot'].translation.copy()
  # The source pulls one ankle almost under the hip. Shorten that travel,
  # rather than flattening/rescaling the thigh or knee transforms.
  tuck=max(0.,min(1.,(foot.y-hip.y+.8)/.5))
  endpoint=Vector((sign*(.16+.04*tuck),hip.y-.83+.10*tuck,.075+.015*tuck))
  seat_limb(world,prefix+'thigh',prefix+'calf',prefix+'foot',endpoint,Vector((sign,-.15,-.15)))
  toe=rest[prefix+'toe0'].translation-rest[prefix+'foot'].translation
  rotation=toe.rotation_difference(Vector((sign*.02,-1,-.10)))@rest[prefix+'foot'].to_quaternion()
  orient_branch(world,prefix+'foot',rotation)
  assert world[prefix+'toe0'].translation.z>.02, 'Toes must stay above the ground, not only ankles'
 # The source looks down about 50 degrees. A horizontal head is needed for
 # the next aiming review; it does not yet supply a firearm/launcher grip.
 orient_branch(world,'bip01_head',rest['bip01_head'].to_quaternion())

weapon_pose=None
stock_body=None
if args.prone_grip:
 spec=importlib.util.spec_from_file_location('poses',root/'scripts/read-omf-poses.py')
 reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
 stock=reader.Motions(root/'scripts/netcoop-overlay/client/meshes/actors/stalker_animation.omf',template)
 slot={'knife':5,'pistol':1,'rifle':2,'launcher':4}[args.prone_grip]
 convert=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)))
 bone_axes=Matrix.Diagonal((1,1,-1,1))
 raw={n:Matrix(matrix.tolist()) for n,matrix in stock.pose(f'norm_torso_{slot}_aim_0',.2,matrices=True).items()}
 # Stock keys include their own aim offset. Normalize the actual engine's
 # weapon basis, not the wrist's display axes, to the horizontal view.
 right=raw['bip01_r_finger1'];left=raw['bip01_r_finger11' if args.grip_hand_dependence==1 else 'bip01_l_finger1']
 direction=(left.translation-right.translation).normalized()
 lateral=right.col[1].xyz.cross(direction).normalized();up=direction.cross(lateral).normalized()
 basis=Matrix.Identity(4)
 for i,axis in enumerate((lateral,up,direction)):basis.col[i].xyz=axis
 alignment=basis.inverted()
 weapon_pose={n:convert@alignment@matrix@bone_axes for n,matrix in raw.items()}
 if args.prone_stock_idle:
  stock_body=reader.Motions(root/'scripts/netcoop-overlay/client/meshes/actors/stalker_smart_cover_animation.omf',template)

def fit_prone_weapon(world):
 # Engine weapons are attached through finger1/finger11, not merely the palm.
 # Preserve the complete proven in-game finger grip and both-hand spacing.
 targets={'knife':(.25,.68,.15),'pistol':(.11,.88,.23),'rifle':(.12,.68,.26),'launcher':(.21,.72,.29)}
 shift=Vector(targets[args.prone_grip])-weapon_pose['bip01_r_finger1'].translation
 for side,sign in [('r',1),('l',-1)]:
  if side=='l' and args.prone_grip=='knife':continue
  prefix='bip01_'+side+'_'
  endpoint=weapon_pose[prefix+'hand'].translation+shift
  seat_limb(world,prefix+'upperarm',prefix+'forearm',prefix+'hand',endpoint,Vector((sign*.12,0,-1)))
  for bone in order:
   if bone.name==prefix+'hand' or any(parent.name==prefix+'hand' for parent in bone.parent_recursive):
    world[bone.name]=Matrix.Translation(shift)@weapon_pose[bone.name]
samples=[];snapshots=[];actions=[]
clay=bpy.data.materials.new('Review actual game actor');clay.diffuse_color=(.38,.48,.39,1)
for obj in target_meshes:obj.data.materials.clear();obj.data.materials.append(clay)
clips=[tuple(value.split('=',1)) for value in args.clip] if args.clip else [('crawl-plain.glb','review_cc0_crawl'),('pistol-prone-plain.glb','review_cc0_pistol_prone'),('driving-plain.glb','review_cc0_driving')]
assert all(len(pair)==2 for pair in clips)
for row,(file,name) in enumerate(clips):
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
    if dst=='bip01_pelvis':pose.translation=Vector((0,0,0)) if args.seat_origin else source_pose.translation*scale
    else:pose.translation=(world[parent.name]@rest[parent.name].inverted()@rest[dst]).translation
   else:pose=world[parent.name]@rest[parent.name].inverted()@rest[dst] if parent else rest[dst].copy()
   world[dst]=pose
  if name in seat_fits:fit_seat(world,seat_fits[name],seat_forward.get(name,.4))
  if stock_body:
   world={n:convert@Matrix(matrix.tolist())@bone_axes for n,matrix in stock_body.pose('loophole_prone_visual',frame/frames,matrices=True).items()}
  elif args.prone_grounded:ground_prone(world)
  if args.prone_grip:fit_prone_weapon(world)
  for bone in order:
   parent=bone.parent;pose=world[bone.name]
   kwargs={} if parent is None else dict(parent_matrix=world[parent.name],parent_matrix_local=parent.bone.matrix_local)
   bone.matrix_basis=bone.bone.convert_local_to_pose(pose,bone.bone.matrix_local,invert=True,**kwargs)
   bone.keyframe_insert('location',frame=frame);bone.keyframe_insert('rotation_quaternion',frame=frame);bone.keyframe_insert('scale',frame=frame)
  bpy.context.view_layer.update()
 for curve in action.fcurves:
  for k in curve.keyframe_points:k.interpolation='LINEAR'
 item=target.xray.motions_collection.add();item.name=name
 for col,fraction in enumerate([0,.25,.5,.75]):
  bpy.context.scene.frame_set(round((frames-1)*fraction));bpy.context.view_layer.update()
  samples.append(dict(clip=name,fraction=fraction,frame=round((frames-1)*fraction),frames=frames,seat_ankle_drop=seat_fits.get(name),seat_foot_forward=seat_forward.get(name,.4) if name in seat_fits else None,points={n:list(target.pose.bones[n].matrix.translation) for n in ['bip01_head','bip01_pelvis','bip01_l_hand','bip01_r_hand','bip01_l_foot','bip01_r_foot']},world={b.name:[list(row) for row in b.matrix] for b in order}))
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
exported=reader.Motions(out/'candidate.omf',template);worst=0;worst_rotation=0
roundtrip_c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)))
roundtrip_s=Matrix.Diagonal((1,1,-1,1))
for row in samples:
 pose=exported.pose(row['clip'],row['frame']/row['frames'],matrices=True)
 for bone,expected in row['world'].items():
  actual=roundtrip_c@Matrix(pose[bone].tolist())@roundtrip_s;expected=Matrix(expected)
  worst=max(worst,(actual.translation-expected.translation).length)
  worst_rotation=max(worst_rotation,max(abs(actual[r][c]-expected[r][c]) for r in range(3) for c in range(3)))
assert worst<.001,('OMF roundtrip changed the reviewed pose',worst)
assert worst_rotation<.002,('OMF roundtrip changed the bone orientation',worst_rotation)
(out/'roundtrip.json').write_text(json.dumps(dict(max_error_metres=worst,samples=len(samples),clips=list(exported.motions),source_commit=provenance['commit'],body_source='X-Ray loophole_prone_visual (existing bundled asset; not CC0)' if stock_body else 'Mesh2Motion CC0',grip_source=f'X-Ray norm_torso_{slot}_aim_0 (existing bundled asset; not CC0)' if args.prone_grip else None,template_sha256=hashlib.sha256(template.read_bytes()).hexdigest(),candidate_sha256=hashlib.sha256((out/'candidate.omf').read_bytes()).hexdigest()),indent=2)+'\n')
print('OMF_ROUNDTRIP_MAX_ERROR_METRES',worst,flush=True)
for obj in target_meshes:obj.hide_render=True
target.hide_render=True
for obj in snapshots:obj.hide_render=False
scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE_NEXT';scene.render.resolution_x=1800;scene.render.resolution_y=1200;scene.render.resolution_percentage=100
scene.world=bpy.data.worlds.new('Review World');scene.world.color=(.12,.12,.12)
floor_z=-.75 if args.seat_origin else -.06
bpy.ops.mesh.primitive_plane_add(size=60,location=(4.2,3.5,floor_z));floor=bpy.context.object
material=bpy.data.materials.new('Floor');material.diffuse_color=(.16,.18,.20,1);floor.data.materials.append(material)
for loc,power in [((3,-5,10),2200),((-5,4,8),1800),((9,10,10),2200)]:
 bpy.ops.object.light_add(type='AREA',location=loc);lamp=bpy.context.object;lamp.data.energy=power;lamp.data.size=8;lamp.rotation_euler=(Vector((4.2,3.5,0))-lamp.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(12,18,12));camera=bpy.context.object;camera.rotation_euler=(Vector((4.2,(len(clips)-1)*1.75,.2))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=max(15,len(clips)*4.2);scene.camera=camera
scene.render.filepath=str(out/'actual-game-actor-review.png');bpy.ops.render.render(write_still=True)
print('PRIVATE_REVIEW_READY',out,flush=True)
