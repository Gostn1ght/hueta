"""Private hand/cuff clearance search and bounded finger wrap; no installation."""
import argparse
import importlib.util
import json
import math
import random
import hashlib
from pathlib import Path
import sys

import addon_utils
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

p=argparse.ArgumentParser(description=__doc__)
for name in ('review','weapon','addons','out'):
    p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--blend',type=Path)
p.add_argument('--actor',type=Path)
p.add_argument('--omf',type=Path)
p.add_argument('--motion')
p.add_argument('--phase',type=float,default=0.)
p.add_argument('--roll-step',type=float,default=3.)
p.add_argument('--roll-limit',type=float,default=45.)
p.add_argument('--fit-finger-wrap',action='store_true')
p.add_argument('--export-grip',action='store_true')
p.add_argument('--forearm-only',action='store_true')
p.add_argument('--free-wrist',action='store_true',help='Also solve an unstretched two-bone arm around the fixed index grip')
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
assert 0<=a.phase<1 and .1<=a.roll_step<=10 and 0<a.roll_limit<=45
assert not a.export_grip or (a.fit_finger_wrap and a.actor)
assert not a.fit_finger_wrap or (a.free_wrist and not a.forearm_only)
assert not (a.forearm_only and a.free_wrist)
a.out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(a.addons));addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
assert bool(a.blend) != bool(a.omf)
if a.blend:
    bpy.ops.wm.open_mainfile(filepath=str(a.blend));bpy.context.scene.frame_set(0);bpy.context.view_layer.update()
else:
    assert a.actor and a.motion
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable('io_scene_xray',default_set=True,persistent=False)
    bpy.ops.xray_import.ogf(directory=str(a.actor.parent),files=[{'name':a.actor.name}],import_motions=False)
rig=next(o for o in bpy.data.objects if o.type=='ARMATURE' and len(o.data.bones)==47)
body=[o for o in bpy.data.objects if o.type=='MESH']
order=sorted(rig.pose.bones,key=lambda b:len(b.parent_recursive));names=[b.name for b in order]
if a.omf:
    spec=importlib.util.spec_from_file_location('poses',Path(__file__).resolve().parents[1]/'scripts/read-omf-poses.py');reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
    c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)));s=Matrix.Diagonal((1,1,-1,1))
    raw=reader.Motions(a.omf,a.actor).pose(a.motion,a.phase,matrices=True)
    matrices={n:c@Matrix(m.tolist())@s for n,m in raw.items()}
    for bone in order:
        for constraint in list(bone.constraints):bone.constraints.remove(constraint)
        kwargs={} if bone.parent is None else dict(parent_matrix=matrices[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
        bone.matrix_basis=bone.bone.convert_local_to_pose(matrices[bone.name],bone.bone.matrix_local,invert=True,**kwargs)
    bpy.context.view_layer.update()
world={b.name:b.matrix.copy() for b in order}
c=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)));s=Matrix.Diagonal((1,1,-1,1))
metadata=json.loads(a.review.read_text(encoding='utf-8'))
first=c@world['bip01_r_finger1']@s;second=c@world['bip01_r_finger11']@s
forward=(second.translation-first.translation).normalized();side=first.col[1].xyz.cross(forward).normalized()
attachment=Matrix((side,forward.cross(side),forward)).transposed().to_4x4();attachment.translation=first.translation
gun=attachment@Matrix(metadata['attachment_review']['matrix_game'])
before=set(bpy.data.objects)
bpy.ops.xray_import.ogf(directory=str(a.weapon.parent),files=[{'name':a.weapon.name}],import_motions=False)
weapon_vertices=[];weapon_triangles=[]
for obj in set(bpy.data.objects)-before:
    if obj.type!='MESH':continue
    base=len(weapon_vertices);weapon_vertices.extend(c@gun@c@obj.matrix_world@v.co for v in obj.data.vertices)
    obj.data.calc_loop_triangles();weapon_triangles.extend(tuple(base+i for i in tri.vertices) for tri in obj.data.loop_triangles)
weapon_tree=BVHTree.FromPolygons(weapon_vertices,weapon_triangles,all_triangles=True)
vertices=[];weights=[];triangles=[];tags=[]
rest_inverse={b.name:b.matrix_local.inverted() for b in rig.data.bones}
for obj in body:
    base=len(vertices)
    for v in obj.data.vertices:
        vertices.append([*(rig.matrix_world.inverted()@obj.matrix_world@v.co),1])
        weights.append([(obj.vertex_groups[g.group].name,g.weight) for g in v.groups if obj.vertex_groups[g.group].name in rest_inverse])
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        totals={}
        for i in tri.vertices:
            for name,weight in weights[base+i]:totals[name]=totals.get(name,0)+weight
        dominant=max(totals,key=totals.get)
        selected=(dominant=='bip01_r_forearm') if a.forearm_only else (dominant=='bip01_r_hand' or dominant.startswith('bip01_r_finger'))
        if selected:
            triangles.append(tuple(base+i for i in tri.vertices));tags.append(dominant)
vertices=np.array(vertices);ids=np.zeros((len(vertices),max(map(len,weights))),dtype=int);values=np.zeros_like(ids,dtype=float)
for i,assignments in enumerate(weights):
    for j,(name,weight) in enumerate(assignments):ids[i,j]=names.index(name);values[i,j]=weight
rest=np.array([rest_inverse[n] for n in names])
hand='bip01_r_hand';index='bip01_r_finger1'
axis=(world[index].translation-world[hand].translation).normalized();pivot=world[hand].translation
results=[];poses={}
trials=[('index-roll',degrees,axis,pivot) for degrees in range(-12,13)]
if a.forearm_only:
    pivot=world['bip01_r_forearm'].translation
    axis=(world[hand].translation-pivot).normalized()
    trials=[('forearm-roll',float(degrees),axis,pivot) for degrees in np.arange(-a.roll_limit,a.roll_limit+a.roll_step/2,a.roll_step)]
if a.free_wrist:
    for i,label in enumerate(('weapon-side','weapon-up','weapon-forward')):
        trials.extend((label,degrees,(c@gun).col[i].xyz.normalized(),world[index].translation) for degrees in range(-24,25,4) if degrees)
for label,degrees,turn_axis,turn_pivot in trials:
    turn=Matrix.Translation(turn_pivot)@Matrix.Rotation(math.radians(degrees),4,turn_axis)@Matrix.Translation(-turn_pivot)
    candidate={n:m.copy() for n,m in world.items()}
    for bone in order:
        lineage=[parent.name for parent in bone.parent_recursive]
        selected=(bone.name=='bip01_r_forearm') if a.forearm_only else ((bone.name==hand or hand in lineage) and bone.name!=index and index not in lineage)
        if selected:
            candidate[bone.name]=turn@world[bone.name]
    assert max((candidate[n].translation-world[n].translation).length for n in (index,'bip01_r_finger11'))<1e-6
    if (candidate[hand].translation-world[hand].translation).length>1e-7:
        upper,lower='bip01_r_upperarm','bip01_r_forearm'
        start,joint,end=[world[n].translation for n in (upper,lower,hand)]
        goal=candidate[hand].translation;direction=goal-start;distance=direction.length
        length_a,length_b=(joint-start).length,(end-joint).length
        if not abs(length_a-length_b)+.0001<distance<length_a+length_b-.0001:continue
        direction.normalize();along=(length_a**2-length_b**2+distance**2)/(2*distance)
        bend=joint-start-direction*(joint-start).dot(direction)
        elbow=start+direction*along+bend.normalized()*math.sqrt(max(0,length_a**2-along**2))
        for name,origin,old_vector,new_vector in ((upper,start,joint-start,elbow-start),(lower,elbow,end-joint,goal-elbow)):
            candidate[name]=old_vector.rotation_difference(new_vector).to_matrix().to_4x4()@world[name]
            candidate[name].translation=origin
    for bone in order:
        if not bone.parent:continue
        parent=bone.parent.name
        assert abs((candidate[bone.name].translation-candidate[parent].translation).length-(world[bone.name].translation-world[parent].translation).length)<.00001
    transforms=np.array([candidate[n] for n in names])@rest
    points=np.sum(np.einsum('nwij,nj->nwi',transforms[ids],vertices)*values[:,:,None],axis=1)[:,:3]
    overlaps=weapon_tree.overlap(BVHTree.FromPolygons(points,triangles,all_triangles=True))
    by_bone={}
    for _,i in overlaps:by_bone[tags[i]]=by_bone.get(tags[i],0)+1
    results.append(dict(axis=label,degrees=degrees,pairs=len(overlaps),by_bone=by_bone))
    poses[(label,degrees)]=candidate
best=min(results,key=lambda r:(r['pairs'],abs(r['degrees'])))
if a.fit_finger_wrap:
    assert not a.forearm_only and a.free_wrist
    best_palm=min(results,key=lambda r:(r['by_bone'].get('bip01_r_hand',0),r['pairs'],abs(r['degrees'])))
    assert best_palm['by_bone'].get('bip01_r_hand',0)==0,'No clear palm within bounded wrist search'
    wrapped={n:m.copy() for n,m in poses[(best_palm['axis'],best_palm['degrees'])].items()}
    def intersections(matrices):
        transforms=np.array([matrices[n] for n in names])@rest
        points=np.sum(np.einsum('nwij,nj->nwi',transforms[ids],vertices)*values[:,:,None],axis=1)[:,:3]
        overlaps=weapon_tree.overlap(BVHTree.FromPolygons(points,triangles,all_triangles=True))
        return points,overlaps
    fits=[]
    for digit in ('0','2'):
        chain=[f'bip01_r_finger{digit}{suffix}' for suffix in ('','1','2')]
        source={n:m.copy() for n,m in wrapped.items()}
        relative={n:source[rig.data.bones[n].parent.name].inverted()@source[n] for n in chain}
        proximal=source[chain[1]].translation-source[chain[0]].translation
        distal=source[chain[2]].translation-source[chain[1]].translation
        hinge=proximal.cross(distal).normalized();assert hinge.length>.99
        axes={n:source[n].to_3x3().inverted()@hinge for n in chain}
        spread=source[chain[0]].to_3x3().inverted()@proximal.cross(hinge).normalized()
        tips=[i for i,assignments in enumerate(weights) if any(n==chain[-1] and weight>.7 for n,weight in assignments)]
        assert tips
        def fitted(angles):
            result={n:m.copy() for n,m in source.items()}
            for j,n in enumerate(chain):
                turn=Matrix.Rotation(angles[j],4,axes[n])
                if not j:turn=turn@Matrix.Rotation(angles[3],4,spread)
                result[n]=result[rig.data.bones[n].parent.name]@relative[n]@turn
            return result
        def score(angles):
            matrices=fitted(angles);points,overlaps=intersections(matrices)
            gap=min(weapon_tree.find_nearest(Vector(points[i]))[3] for i in tips)
            return len(overlaps)*.0001+(gap-.001)**2+.00000002*sum(v*v for v in angles)
        bounds=[math.radians(v) for v in (70,75,75,35)]
        rng=random.Random(61111+int(digit));seeds=[[0.]*4]+[[rng.uniform(-b,b) for b in bounds] for _ in range(24)]
        solutions=[]
        for seed in sorted(seeds,key=score)[:3]:
            angles=seed.copy()
            for step in (15,7,3,1,.3):
                step=math.radians(step)
                for iteration in range(40):
                    value=score(angles);changed=False
                    for j in range(4):
                        for sign in (-1,1):
                            trial=angles.copy();trial[j]=max(-bounds[j],min(bounds[j],trial[j]+step*sign));candidate_score=score(trial)
                            if candidate_score<value:angles,value,changed=trial,candidate_score,True
                    if not changed:break
            solutions.append(angles)
        angles=min(solutions,key=score);wrapped=fitted(angles)
        fits.append(dict(digit=digit,degrees=[math.degrees(v) for v in angles]))
    points,overlaps=intersections(wrapped)
    by_bone={}
    for _,i in overlaps:by_bone[tags[i]]=by_bone.get(tags[i],0)+1
    wrap_review=dict(wrist=best_palm,adjustments=fits,pairs=len(overlaps),by_bone=by_bone)
    (a.out/'wrap-review.json').write_text(json.dumps(wrap_review,indent=2)+'\n',encoding='utf-8')
    print('FULL_HAND_WRAP',json.dumps(wrap_review),flush=True)
    if a.export_grip:
        assert a.actor and not overlaps,'Only a clear full hand can be exported'
        assert max(abs(wrapped[n][r][k]-world[n][r][k]) for n in ('bip01_r_finger1','bip01_r_finger11','bip01_r_finger12') for r in range(4) for k in range(4))<.000001
        rig.animation_data_create();rig.animation_data.action=None
        action=bpy.data.actions.new('review_rpg_full_hand');rig.animation_data.action=action;action.xray.fps=30;action.xray.speed=1
        for bone in order:
            bone.rotation_mode='QUATERNION'
            kwargs={} if bone.parent is None else dict(parent_matrix=wrapped[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
            bone.matrix_basis=bone.bone.convert_local_to_pose(wrapped[bone.name],bone.bone.matrix_local,invert=True,**kwargs)
            for frame in (0,1):
                for channel in ('location','rotation_quaternion','scale'):bone.keyframe_insert(channel,frame=frame)
        rig.xray.motions_collection.clear();rig.xray.motions_collection.add().name=action.name
        bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);bpy.context.view_layer.objects.active=rig
        assert bpy.ops.xray_export.omf_file(filepath=str(a.out/'candidate.omf'),high_quality=True,fmt_ver='cscop')=={'FINISHED'}
        metadata.update(installed=False,reference_only=True,full_hand_wrap=wrap_review,candidate_sha256=hashlib.sha256((a.out/'candidate.omf').read_bytes()).hexdigest())
        (a.out/'review.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')

(a.out/'palm-search.json').write_text(json.dumps(dict(installed=False,baseline=next(r for r in results if r['degrees']==0),best=best,candidates=results),indent=2)+'\n',encoding='utf-8')
print('PALM_SEARCH',json.dumps(best))
