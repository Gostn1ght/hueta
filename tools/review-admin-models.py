import bpy,addon_utils,sys,json,importlib.util,math
from pathlib import Path
from mathutils import Matrix,Vector
import argparse
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);p.add_argument('--addons',type=Path,required=True);p.add_argument('--prone',type=Path)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);base=a.candidate
sys.path.insert(0,str(a.addons.resolve()));addon_utils.enable('io_scene_xray',default_set=True,persistent=True)
bpy.context.preferences.addons['io_scene_xray'].preferences.textures_folder=str(base/'textures')
spec=importlib.util.spec_from_file_location('poses',root/'scripts/read-omf-poses.py');reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)));reports=[]
for name in ['mahito','areke']:
 bpy.ops.wm.read_factory_settings(use_empty=True)
 addon_utils.enable('io_scene_xray',default_set=True,persistent=True)
 bpy.context.preferences.addons['io_scene_xray'].preferences.textures_folder=str(base/'textures')
 path=base/'meshes/actors/lostzone_admin'/(name+'.ogf')
 bpy.ops.xray_import.ogf(directory=str(path.parent),files=[{'name':path.name}],import_motions=False)
 rig=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE');assert len(rig.data.bones)==47
 meshes=[o for o in bpy.context.scene.objects if o.type=='MESH'];order=sorted(rig.pose.bones,key=lambda b:len(b.parent_recursive))
 for bone in order:
  for constraint in list(bone.constraints):bone.constraints.remove(constraint)
  bone.rotation_mode='QUATERNION'
 stock=reader.Motions(root/'scripts/netcoop-overlay/client/meshes/actors/stalker_animation.omf',path)
 prone=reader.Motions(a.prone,path) if a.prone else None
 snapshots=[];samples=[]
 seated=reader.Motions(root/'scripts/netcoop-overlay/client/meshes/actors/modded_stalker_animations/netcoop_player_prone.omf',path)
 poses=[(None,'rest',0),(stock,'norm_walk_fwd_0',0),(stock,'norm_walk_fwd_0',.5),(stock,'steering_idle_0_0',.2),(seated,'lz_vehicle_passenger',.2)]
 if prone:poses.append((prone,'review_cc0_crawl',.25))
 for col,(motions,clip,phase) in enumerate(poses):
  world={n:c@Matrix(m.tolist())@Matrix.Diagonal((1,1,-1,1)) for n,m in motions.pose(clip,phase,matrices=True).items()} if motions else {b.name:b.matrix_local.copy() for b in rig.data.bones}
  for bone in order:
   parent=bone.parent;kwargs={} if parent is None else dict(parent_matrix=world[parent.name],parent_matrix_local=parent.bone.matrix_local)
   bone.matrix_basis=bone.bone.convert_local_to_pose(world[bone.name],bone.bone.matrix_local,invert=True,**kwargs)
  bpy.context.view_layer.update();points=[]
  for obj in meshes:
   data=bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
   vertices=[obj.matrix_world@v.co for v in data.vertices];points+=vertices
   snap=bpy.data.objects.new(name+'_'+clip+'_'+str(col),data);bpy.context.collection.objects.link(snap);snap.matrix_world=obj.matrix_world.copy();snap.location.x+=col*2.5;snapshots.append(snap)
  lo=[min(p[i] for p in points) for i in range(3)];hi=[max(p[i] for p in points) for i in range(3)]
  assert all(math.isfinite(v) for v in lo+hi) and max(hi[i]-lo[i] for i in range(3))<3,('exploded pose',name,clip,lo,hi)
  samples.append(dict(clip=clip,phase=phase,lo=lo,hi=hi))
 for obj in meshes:obj.hide_render=True
 rig.hide_render=True
 scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE_NEXT';scene.render.resolution_x=1800;scene.render.resolution_y=700;scene.render.resolution_percentage=100
 scene.world=bpy.data.worlds.new('World');scene.world.color=(.15,.15,.15)
 bpy.ops.mesh.primitive_plane_add(size=50,location=(5,0,-.04));floor=bpy.context.object;mat=bpy.data.materials.new('floor');mat.diffuse_color=(.15,.17,.20,1);floor.data.materials.append(mat)
 for loc,power in [((4,4,6),2200),((-3,-2,5),1200),((12,3,6),2400)]:
  bpy.ops.object.light_add(type='AREA',location=loc);lamp=bpy.context.object;lamp.data.energy=power;lamp.data.size=7;lamp.rotation_euler=(Vector((5,0,1))-lamp.location).to_track_quat('-Z','Y').to_euler()
 bpy.ops.object.camera_add(location=(6,14,6));camera=bpy.context.object;camera.rotation_euler=(Vector((5,0,.7))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=13;scene.camera=camera
 scene.render.filepath=str(base/(name+'-game-poses.png'));bpy.ops.render.render(write_still=True)
 reports.append(dict(name=name,samples=samples,images=[dict(name=i.name,size=list(i.size)) for i in bpy.data.images]))
 print('VERIFIED_GAME_OGF',name,'47 bones;',len(samples),'finite bounded review poses',flush=True)
(base/'game-poses-reviewed.json').write_text(json.dumps(reports,indent=2)+'\n')
