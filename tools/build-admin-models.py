"""Offline skin conversion of user-provided data; no source scripts executed."""
import sys,json,math,hashlib
from pathlib import Path
import bpy,addon_utils
from mathutils import Matrix,Vector
import argparse,struct
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--sources',type=Path,required=True,help='Extracted areke/source and mahito/source + texture folders')
p.add_argument('--template',type=Path,required=True,help='47-bone stock actor OGF')
p.add_argument('--addons',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
base=a.sources;out=a.output;out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(a.addons.resolve()))
template=a.template
# Keep the GLB's actual embedded albedo; loose alternatives differ in colour.
glb=(base/'areke/source/Anime style Elf2.glb').read_bytes()
length=struct.unpack_from('<I',glb,12)[0];scene=json.loads(glb[20:20+length]);binary=glb[28+length:]
embedded=base/'areke/textures/embedded';embedded.mkdir(parents=True,exist_ok=True);images=[]
for i,image in enumerate(scene['images']):
 view=scene['bufferViews'][image['bufferView']];offset=view.get('byteOffset',0);name=image.get('name','image_'+str(i))+'.png'
 (embedded/name).write_bytes(binary[offset:offset+view['byteLength']]);images.append(name)
materials={}
for material in scene['materials']:
 tex=material['pbrMetallicRoughness']['baseColorTexture'];filename=images[scene['textures'][tex['index']]['source']]
 materials[material['name']]=dict(image=filename,alpha=material.get('alphaMode','OPAQUE'))
(embedded/'materials.json').write_text(json.dumps(materials,indent=2)+'\n')
align=Matrix.Rotation(math.pi,4,'Z');reports=[]
for name in ['areke','mahito']:
 bpy.ops.wm.read_factory_settings(use_empty=True)
 addon_utils.enable('io_scene_xray',default_set=True,persistent=True)
 if name=='areke':bpy.ops.import_scene.gltf(filepath=str(base/'areke/source/Anime style Elf2.glb'))
 else:bpy.ops.import_scene.fbx(filepath=str(base/'mahito/source/Adam Smasher.Fbx'),use_anim=False)
 source=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
 original_objects=list(bpy.context.scene.objects);worlds={o:o.matrix_world.copy() for o in original_objects}
 bpy.context.view_layer.objects.active=source;source.select_set(True)
 bpy.ops.object.mode_set(mode='EDIT')
 for bone in source.data.edit_bones:bone.use_connect=False
 bpy.ops.object.mode_set(mode='OBJECT')
 def depth(o):
  count=0
  while o.parent:count+=1;o=o.parent
  return count
 corners=[worlds[o]@Vector(v) for o in original_objects if o.type=='MESH' and o.name!='Icosphere' for v in o.bound_box]
 lo=min(v.z for v in corners);hi=max(v.z for v in corners);uniform_scale=1.80/(hi-lo)
 transform=Matrix.Translation((0,0,-lo*uniform_scale))@Matrix.Scale(uniform_scale,4)@align
 for o in sorted(original_objects,key=depth):o.matrix_world=transform@worlds[o]
 bpy.context.view_layer.update()
 before=set(bpy.context.scene.objects)
 bpy.ops.xray_import.ogf(directory=str(template.parent),files=[{'name':template.name}],import_motions=False)
 imported=set(bpy.context.scene.objects)-before;target=next(o for o in imported if o.type=='ARMATURE')
 for o in imported:
  if o.type!='ARMATURE':bpy.data.objects.remove(o,do_unlink=True)
 target.name='lz_admin_'+name;target.animation_data_clear()
 assert len(target.data.bones)==47
 target_rest={b.name:target.matrix_world@b.matrix_local for b in target.data.bones}
 if name=='areke':
  mapping={'Bip001':'bip01','Bip001 Pelvis':'bip01_pelvis','Bip001 Spine':'bip01_spine','Bip001 Spine1':'bip01_spine1','Bip001 Neck':'bip01_neck','Bip001 Head':'bip01_head'}
  for side in ['L','R']:
   for a,b in [('Thigh','thigh'),('Calf','calf'),('Foot','foot'),('Toe0','toe0'),('Clavicle','clavicle'),('UpperArm','upperarm'),('Forearm','forearm'),('Hand','hand')]:mapping['Bip001 '+side+' '+a]='bip01_'+side.lower()+'_'+b
   for finger in ['0','1','2']:
    mapping['Bip001 '+side+' Finger'+finger]='bip01_'+side.lower()+'_finger'+finger
    mapping['Bip001 '+side+' Finger'+finger+'1']='bip01_'+side.lower()+'_finger'+finger+'1'
 else:
  mapping={'root_hips':'bip01_pelvis','pelvis':'bip01_pelvis','spine_lower_01':'bip01_spine','spine_middle':'bip01_spine1','spine_shoulders':'bip01_spine2','head_neck_lower':'bip01_neck','head_neck_upper':'bip01_head'}
  for side in ['left','right']:
   for a,b in [('shoulder_01','clavicle'),('shoulder_02','upperarm'),('elbow','forearm'),('wrist','hand')]:mapping['arm_'+side+'_'+a]='bip01_'+side[0]+'_'+b
   for a,b in [('thigh','thigh'),('knee','calf'),('ankle','foot'),('toes','toe0')]:mapping['leg_'+side+'_'+a]='bip01_'+side[0]+'_'+b
   for finger,index in [('1','0'),('2','1'),('3','2')]:
    for a,b in [('a',''),('b','1'),('c','2')]:mapping['arm_'+side+'_finger_'+finger+a]='bip01_'+side[0]+'_finger'+index+b
 assert set(mapping)<=set(source.data.bones.keys()),set(mapping)-set(source.data.bones.keys())
 source_rest={b.name:source.matrix_world@b.matrix_local for b in source.data.bones}
 order=sorted(source.pose.bones,key=lambda b:len(b.parent_recursive));posed={}
 for bone in order:
  for constraint in list(bone.constraints):bone.constraints.remove(constraint)
  bone.rotation_mode='QUATERNION'
  n=bone.name;parent=bone.parent
  core=(n in ['Bip001','Bip001 Pelvis','Bip001 Spine','Bip001 Spine1','Bip001 Neck','Bip001 Head','root_hips','pelvis','spine_lower_01','spine_middle','spine_shoulders','head_neck_lower','head_neck_upper'])
  if core:
   # Preserve the author's head, torso and waist proportions. Stock actor
   # pivots are the animation rig, not a body-shape template for the donor.
   pose=source_rest[n].copy()
  elif n in mapping:
   dst=mapping[n];rotation=Matrix.Identity(3).to_quaternion()
   # Match actual segment directions, not FBX/GLTF bone display tails.
   next_bones=[b for b in source.data.bones if b.name in mapping and b.parent and b.parent.name==n and mapping[b.name]!=dst]
   axial=[b for b in next_bones if mapping[b.name] in ['bip01_spine','bip01_spine1','bip01_spine2','bip01_neck','bip01_head']]
   if axial:next_bones=axial
   if next_bones:
    child=max(next_bones,key=lambda b:(source_rest[b.name].translation-source_rest[n].translation).length)
    a=source_rest[child.name].translation-source_rest[n].translation
    b=target_rest[mapping[child.name]].translation-target_rest[dst].translation
    if a.length>.001 and b.length>.001:rotation=a.rotation_difference(b)
   pose=rotation.to_matrix().to_4x4()@source_rest[n];pose.translation=target_rest[dst].translation
  else:pose=posed[parent.name]@source_rest[parent.name].inverted()@source_rest[n] if parent else source_rest[n]
  posed[n]=pose
  local=source.matrix_world.inverted()@pose
  kwargs={} if parent is None else dict(parent_matrix=source.matrix_world.inverted()@posed[parent.name],parent_matrix_local=parent.bone.matrix_local)
  bone.matrix_basis=bone.bone.convert_local_to_pose(local,bone.bone.matrix_local,invert=True,**kwargs)
 bpy.context.view_layer.update()
 errors=sorted([(((source.matrix_world@b.matrix).translation-posed[b.name].translation).length,b.name) for b in source.pose.bones],reverse=True)
 print('PIVOT_ERROR',name,errors[:8],flush=True)
 mapped_error=max(error for error,bone in errors if bone in mapping)
 assert mapped_error<.001,('mapped pose did not match intended game pivots',mapped_error)
 # Every extra facial/hair/twist weight follows its nearest mapped parent.
 weightmap={}
 for bone in source.data.bones:
  ancestor=bone
  while ancestor and ancestor.name not in mapping:ancestor=ancestor.parent
  weightmap[bone.name]=mapping[ancestor.name] if ancestor else 'bip01_pelvis'
 tex_dir=out/'textures/actors/lostzone_admin';tex_dir.mkdir(parents=True,exist_ok=True)
 materials={};tex_manifest=[]
 for mat in list(bpy.data.materials):
  if not any(o.type=='MESH' and mat in list(o.data.materials) for o in original_objects):continue
  if name=='areke':
   token=mat.name.lower();embedded=json.loads((base/name/'textures/embedded/materials.json').read_text())
   filename='embedded/'+embedded[mat.name]['image']
  else:
   token=mat.name.lower()
   filename=('T_GateMouseUniversal_Backpack_D.tga.png' if 'backpack' in token else 'T_GateMouse_Head_D.tga.png' if 'head' in token else 'T_GateMouse_FaceAcc_D.tga.png' if 'stuff' in token else 'T_GateMouse_Body_D.tga.png')
  image=bpy.data.images.load(str(base/name/'textures'/filename),check_existing=True)
  texture=name+'_'+Path(filename).stem.replace('.tga','').lower()
  image.name='actors\\lostzone_admin\\'+texture
  material=bpy.data.materials.new(name+'_'+mat.name);material.use_nodes=True
  material.xray.initialize('LOADED',0) # do not let creation callbacks replace the authored skin shader
  bsdf=material.node_tree.nodes.get('Principled BSDF');tex=material.node_tree.nodes.new('ShaderNodeTexImage');tex.name='actors\\lostzone_admin\\'+texture;tex.image=image;material.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
  alpha=name=='areke' and embedded[mat.name]['alpha']!='OPAQUE'
  if alpha:material.node_tree.links.new(tex.outputs['Alpha'],bsdf.inputs['Alpha'])
  bsdf.inputs['Roughness'].default_value=.45 if name=='mahito' else .8
  material.xray.eshader='models\\model_aref' if alpha else 'models\\model';material.xray.cshader='default';material.xray.gamemtl='default_object'
  material.xray.flags_twosided=name=='areke'
  materials[mat.name]=material
  tex_manifest.append(dict(source=str(base/name/'textures'/filename),texture='actors/lostzone_admin/'+texture+'.dds',alpha=alpha))
 meshes=[];counts=[]
 excluded=['Icosphere','0009_charface_none','0012_charface_none'] if name=='areke' else []
 for obj in original_objects:
  if obj.type!='MESH' or obj.name in excluded:continue
  mesh=bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
  mesh.transform(obj.matrix_world)
  new=bpy.data.objects.new(name+'_'+obj.name,mesh);bpy.context.collection.objects.link(new)
  new.data.materials.clear()
  for mat in obj.data.materials:new.data.materials.append(materials[mat.name])
  # Recreate normalized weights on the stock, collision-ready skeleton.
  groups={n:new.vertex_groups.new(name=n) for n in sorted(set(mapping.values()))}
  indexes={g.index:weightmap.get(g.name,'bip01_pelvis') for g in obj.vertex_groups}
  for vertex,old in zip(mesh.vertices,obj.data.vertices):
   weights={}
   for group in old.groups:
    bone=indexes[group.group];weights[bone]=weights.get(bone,0)+group.weight
   weights=sorted(weights.items(),key=lambda pair:pair[1],reverse=True)[:4]
   total=sum(w for _,w in weights)
   if total<=1e-8:weights=[('bip01_pelvis',1)];total=1
   for bone,weight in weights:groups[bone].add([vertex.index],weight/total,'REPLACE')
  modifier=new.modifiers.new('Game skeleton','ARMATURE');modifier.object=target;new.parent=target
  meshes.append(new);counts.append(dict(mesh=obj.name,vertices=len(mesh.vertices),triangles=sum(len(p.vertices)-2 for p in mesh.polygons)))
 for obj in original_objects:bpy.data.objects.remove(obj,do_unlink=True)
 bpy.ops.object.select_all(action='DESELECT');target.select_set(True);bpy.context.view_layer.objects.active=target
 for obj in meshes:obj.select_set(True)
 model=out/'meshes/actors/lostzone_admin'/(name+'.ogf');model.parent.mkdir(parents=True,exist_ok=True)
 bpy.ops.wm.save_as_mainfile(filepath=str(out/(name+'-adapted.blend')))
 result=bpy.ops.xray_export.ogf_file(filepath=str(model),fmt_version='cscop',export_motions=False,use_export_paths=False,texture_name_from_image_path=False)
 assert result=={'FINISHED'} and model.is_file(),result
 report=dict(name=name,model=str(model),sha256=hashlib.sha256(model.read_bytes()).hexdigest(),uniform_scale=uniform_scale,core_proportions_preserved=True,mapping=mapping,meshes=counts,excluded=excluded,textures=tex_manifest)
 reports.append(report);(out/'conversion.json').write_text(json.dumps(reports,indent=2)+'\n')
 # Review the actual adapted body, with the supplied textures.
 scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE_NEXT';scene.render.resolution_x=900;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
 scene.world=bpy.data.worlds.new('World');scene.world.color=(.12,.12,.12)
 bpy.ops.mesh.primitive_plane_add(size=20,location=(0,0,-.02));floor=bpy.context.object;floor.data.materials.append(bpy.data.materials.new('floor'));floor.data.materials[0].diffuse_color=(.14,.16,.18,1)
 for loc,power in [((3,4,5),700),((-3,2,4),600),((0,-3,4),800)]:
  bpy.ops.object.light_add(type='AREA',location=loc);lamp=bpy.context.object;lamp.data.energy=power;lamp.data.size=4;lamp.rotation_euler=(Vector((0,0,1))-lamp.location).to_track_quat('-Z','Y').to_euler()
 bpy.ops.object.camera_add(location=(2.8,5,2));camera=bpy.context.object;camera.rotation_euler=(Vector((0,0,.95))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=2.5;scene.camera=camera
 scene.render.filepath=str(out/(name+'-review.png'));bpy.ops.render.render(write_still=True)
 print('ADAPTED',name,len(meshes),'meshes',sum(row['triangles'] for row in counts),'triangles',flush=True)
