"""Offline Blender: derive rigid wreck pieces from each actual DCP vehicle.

All source faces, UVs and materials survive exactly once. No other vehicle's
parts are borrowed. Candidate outputs stay outside the overlay until reviewed.
"""
import argparse, collections, hashlib, json, re, struct, sys
from pathlib import Path
import addon_utils, bpy, bmesh
from mathutils import Vector

p=argparse.ArgumentParser()
p.add_argument('--root',type=Path,required=True)
p.add_argument('--addons',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--only',default='')
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
sys.path.insert(0,str(a.addons.resolve()));a.root=a.root.resolve();a.out=a.out.resolve()
models=json.loads((a.root/'tools/dcp-seat-layouts.json').read_text(encoding='utf-8'))
report_path=a.out/'debris-reviewed-candidate.json'
reports=json.loads(report_path.read_text()) if report_path.exists() and not a.only else []
userdata='[impulse_transition_from_source_bone]\nref_bone = root\nimp_transition_factor = 0.1\nlv_transition_factor = 1\nav_transition_factor = 1\n'

def normalize_userdata(path):
    # The exporter can pick a split mesh as the property owner for large bodies.
    # Explicitly persist the reviewed fragment userdata, independently of which
    # Blender object it selected. Use the source root for rigid-body velocity;
    # a decorative door bone need not have a physics element of its own.
    data=path.read_bytes();offset=0;chunks=[]
    while offset<len(data):
        tag,size=struct.unpack_from('<II',data,offset);offset+=8
        assert offset+size<=len(data)
        if tag!=17:chunks.append(struct.pack('<II',tag,size)+data[offset:offset+size])
        offset+=size
    payload=userdata.encode()+b'\0'
    chunks.append(struct.pack('<II',17,len(payload))+payload)
    path.write_bytes(b''.join(chunks))
def xr(v):return (v.x,v.z,v.y)
def classify(name,parents):
    current=name
    while current:
        if re.search(r'(?<!stearing_)(?:left|right)_wheel\d*$',current):return current
        if re.search(r'^(?:back_)?(?:left|right)_door$',current):return current
        if current in {'front_door','back_door','hood','bonnet','trunk'}:return current
        # Folding bus door panels form one fragment per doorway.
        if re.fullmatch(r'(front|back)_door\d',current):return current.split('_door')[0]+'_door'
        current=parents.get(current,'')
    return 'body'

for relative in models:
    if a.only and a.only not in relative:continue
    old=next((r for r in reports if r['source']==relative),None)
    if old:
        assert old['source_sha256']==hashlib.sha256((a.root/'scripts/netcoop-overlay/client/meshes'/relative).read_bytes()).hexdigest()
        for part in old['parts']:
            path=a.out/'meshes'/part['path']
            assert hashlib.sha256(path.read_bytes()).hexdigest()==part['sha256']
            normalize_userdata(path)
            part['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        report_path.write_text(json.dumps(reports,indent=2)+'\n')
        continue
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
    source=a.root/'scripts/netcoop-overlay/client/meshes'/relative
    bpy.ops.xray_import.ogf(directory=str(source.parent),files=[{'name':source.name}],import_motions=False)
    donor=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    donor.animation_data_clear()
    for bone in donor.pose.bones:bone.matrix_basis.identity()
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    parents={b.name:b.parent.name if b.parent else '' for b in donor.data.bones}
    groups=collections.defaultdict(list);source_tris=0
    for mesh in meshes:
        mesh.data.calc_loop_triangles()
        names={g.index:g.name for g in mesh.vertex_groups}
        dominant={v.index:names[max(v.groups,key=lambda q:q.weight).group] if v.groups else 'root' for v in mesh.data.vertices}
        for face in mesh.data.loop_triangles:
            votes=collections.Counter(classify(dominant[i],parents) for i in face.vertices)
            group=votes.most_common(1)[0][0]
            groups[group].append((mesh,face.index))
            source_tris+=1
    # Some tracked donor models have every face bound to one rigid body.
    # Retain that real wreck instead of inventing another vehicle's wheels.
    assert 'body' in groups and 1<=len(groups)<=20,(relative,list(groups))
    total_mass=sum(max(0.,b.xray.mass.value) for b in donor.data.bones if b.xray.shape.type!='0' and not b.xray.shape.flags_nophysics)
    total_mass=max(100.,total_mass)
    weights={name:0.04 if 'wheel' in name else 0.025 for name in groups if name!='body'}
    weights['body']=max(.4,1.-sum(weights.values()));norm=sum(weights.values())
    result=[]
    # Donor must not be selected/exported with the new one-bone fragments.
    for name,faces in groups.items():
        vertices=[];triangles=[];uv=[];materials=[];material_indices=[];remap={}
        for mesh,index in faces:
            face=mesh.data.loop_triangles[index];indices=[]
            for vertex,loop in zip(face.vertices,face.loops):
                key=(mesh.name,vertex)
                if key not in remap:
                    remap[key]=len(vertices);vertices.append(mesh.matrix_world@mesh.data.vertices[vertex].co)
                indices.append(remap[key]);uv.append(tuple(mesh.data.uv_layers.active.data[loop].uv))
            triangles.append(indices)
            material=mesh.data.materials[face.material_index]
            if material not in materials:materials.append(material)
            material_indices.append(materials.index(material))
        data=bpy.data.meshes.new(name);data.from_pydata(vertices,[],triangles);data.update()
        layer=data.uv_layers.new(name='Texture')
        for loop,value in zip(layer.data,uv):loop.uv=value
        for material in materials:data.materials.append(material)
        for face,index in zip(data.polygons,material_indices):face.material_index=index;face.use_smooth=True
        obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
        armature=bpy.data.armatures.new(name);rig=bpy.data.objects.new(name+'_rig',armature);bpy.context.collection.objects.link(rig)
        bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);bpy.context.view_layer.objects.active=rig
        bpy.ops.object.mode_set(mode='EDIT');bone=armature.edit_bones.new('root');bone.head=(0,0,0);bone.tail=(0,0,.2);bpy.ops.object.mode_set(mode='OBJECT')
        bone=armature.bones['root'];bone.xray.ikjoint.type='0'
        lo=Vector(tuple(min(v[i] for v in vertices) for i in range(3)));hi=Vector(tuple(max(v[i] for v in vertices) for i in range(3)))
        centre=(lo+hi)/2;half=(hi-lo)/2
        shape=bone.xray.shape;shape.type='1';shape.box_rot=(1,0,0,0,1,0,0,0,1)
        shape.box_trn=xr(centre);shape.box_hsz=xr(Vector(tuple(max(.015,x) for x in half)))
        bone.xray.mass.value=total_mass*weights[name]/norm;bone.xray.mass.center=xr(centre);bone.xray.gamemtl='objects\\car_cabine'
        group=obj.vertex_groups.new(name='root');group.add(range(len(vertices)),1.,'REPLACE');obj.parent=rig
        mod=obj.modifiers.new('armature','ARMATURE');mod.object=rig
        draw_objects=[obj]
        if len(triangles)>12000:
            draw_objects=[]
            for first in range(0,len(triangles),12000):
                chunk=obj.copy();chunk.data=obj.data.copy();bpy.context.collection.objects.link(chunk)
                bm=bmesh.new();bm.from_mesh(chunk.data);bm.faces.ensure_lookup_table()
                bmesh.ops.delete(bm,geom=[f for f in bm.faces if not first<=f.index<first+12000],context='FACES')
                bm.to_mesh(chunk.data);bm.free();draw_objects.append(chunk)
            bpy.data.objects.remove(obj,do_unlink=True)
        rig.xray.isroot=True
        assert 'root' in parents
        rig.xray.userdata=userdata
        dest=a.out/'meshes/physics/vehicles/lz_debris'/source.stem/(name+'.ogf');dest.parent.mkdir(parents=True,exist_ok=True)
        for draw in draw_objects:draw.select_set(True)
        assert bpy.ops.xray_export.ogf_file(filepath=str(dest),fmt_version='cscop',export_motions=False,use_export_paths=False,texture_name_from_image_path=False)=={'FINISHED'}
        normalize_userdata(dest)
        result.append(dict(name=name,path=dest.relative_to(a.out/'meshes').as_posix(),triangles=len(triangles),mass=bone.xray.mass.value,lo=list(lo),hi=list(hi),sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
        for draw in draw_objects:bpy.data.objects.remove(draw,do_unlink=True)
        bpy.data.objects.remove(rig,do_unlink=True)
    assert sum(x['triangles'] for x in result)==source_tris
    reports.append(dict(source=relative,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),triangles=source_tris,parts=result,rigid_only=len(groups)==1))
    print('WRECK',relative,len(result),'parts',source_tris,'triangles',flush=True)
    (a.out/'debris-reviewed-candidate.json').write_text(json.dumps(reports,indent=2)+'\n')
a.out.mkdir(parents=True,exist_ok=True)
(a.out/'debris-reviewed-candidate.json').write_text(json.dumps(reports,indent=2)+'\n')
