"""Private whole-body SMD reference transfer to the real 47-bone actor.

Blender --background --python-exit-code 1 --python this.py -- --reference FILE
 --pose FILE --template ACTOR --addons DIR --out PRIVATE
No input asset is bundled, installed or declared cleared for redistribution.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import random
import sys

import addon_utils
import bpy
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree

p = argparse.ArgumentParser(description=__doc__)
for name in ('reference', 'pose', 'template', 'addons', 'out'):
    p.add_argument('--' + name, required=True, type=Path)
p.add_argument('--rpg-trigger-fit', action='store_true', help='Private right-hand fit with a matching, recorded RPG attachment offset')
p.add_argument('--hud-grip-motion', default='rpg7_iwp_shoot_aim', help='RPG hand clip used for the private grip reference')
p.add_argument('--hud-grip-frame', type=float, default=2/13, help='Normalized sample in the RPG hand clip')
p.add_argument('--fit-index-contact', action='store_true', help='Fit the index pad to the actual trigger without changing the palm')
p.add_argument('--trigger-clearance-mm', type=float, default=.8, help='Private contact fitting clearance in front of the trigger')
p.add_argument('--avoid-index-penetration', action='store_true', help='Include actual whole-index/weapon triangle intersections in the fit')
p.add_argument('--grip-lateral-mm', type=float, default=0, help='Private right-palm lateral adjustment for the body glove thickness')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
assert 0 <= a.hud_grip_frame <= 1
assert not a.fit_index_contact or a.rpg_trigger_fit, '--fit-index-contact requires --rpg-trigger-fit'
assert not a.avoid_index_penetration or a.fit_index_contact
assert 0 <= a.trigger_clearance_mm <= 15
assert abs(a.grip_lateral_mm)<=10
a.out.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[1]


def first_smd_frame(path):
    text = path.read_text()
    nodes = {int(i): (name, int(parent)) for i, name, parent in re.findall(
        r'^\s*(\d+)\s+"([^"]+)"\s+(-?\d+)\s*$', text, re.M)}
    data = {}
    recording = False
    for line in text.splitlines():
        if line.startswith('time '):
            if recording:
                break
            recording = True
            continue
        if recording:
            if line == 'end':
                break
            values = line.split()
            if len(values) == 7:
                data[int(values[0])] = list(map(float, values[1:]))
    world = {}
    while data:
        progressed = False
        for key, values in list(data.items()):
            parent = nodes[key][1]
            if parent != -1 and parent not in world:
                continue
            matrix = Euler(values[3:], 'XYZ').to_matrix().to_4x4()
            matrix.translation = Vector(values[:3]) * .0254
            world[key] = world[parent] @ matrix if parent != -1 else matrix
            del data[key]
            progressed = True
        assert progressed, 'Missing or cyclic SMD parent'
    align = Matrix.Rotation(math.pi, 4, 'Z')
    return {nodes[key][0]: align @ matrix for key, matrix in world.items()}


sys.path.insert(0, str(a.addons))
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray', default_set=True, persistent=False)
bpy.ops.xray_import.ogf(directory=str(a.template.parent), files=[{'name': a.template.name}], import_motions=False)
rig = next(obj for obj in bpy.data.objects if obj.type == 'ARMATURE')
assert len(rig.data.bones) == 47
order = sorted(rig.pose.bones, key=lambda bone: len(bone.parent_recursive))
rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
source_rest, source_pose = first_smd_frame(a.reference), first_smd_frame(a.pose)
mapping = {'bip01_pelvis': 'Pelvis', 'bip01_spine': 'Spine', 'bip01_spine1': 'Spine2',
           'bip01_spine2': 'Spine4', 'bip01_neck': 'Neck1', 'bip01_head': 'Head1'}
successor = {'bip01_pelvis': 'bip01_spine', 'bip01_spine': 'bip01_spine1',
             'bip01_spine1': 'bip01_spine2', 'bip01_spine2': 'bip01_neck', 'bip01_neck': 'bip01_head'}
for side, label in (('r', 'R'), ('l', 'L')):
    for target, source in [('clavicle', 'Clavicle'), ('upperarm', 'UpperArm'), ('forearm', 'Forearm'),
                           ('hand', 'Hand'), ('thigh', 'Thigh'), ('calf', 'Calf'), ('foot', 'Foot'), ('toe0', 'Toe0')]:
        mapping[f'bip01_{side}_{target}'] = f'{label}_{source}'
    for first, last in [('clavicle', 'upperarm'), ('upperarm', 'forearm'), ('forearm', 'hand'),
                        ('hand', 'finger1'), ('thigh', 'calf'), ('calf', 'foot'), ('foot', 'toe0')]:
        successor[f'bip01_{side}_{first}'] = f'bip01_{side}_{last}'
    for finger in ('0', '1', '2'):
        for suffix in ('', '1', '2'):
            mapping[f'bip01_{side}_finger{finger}{suffix}'] = f'{label}_Finger{finger}{suffix}'
        for suffix, child in (('', '1'), ('1', '2')):
            successor[f'bip01_{side}_finger{finger}{suffix}'] = f'bip01_{side}_finger{finger}{child}'
mapping = {name: 'ValveBiped.Bip01_' + source for name, source in mapping.items()}
assert set(mapping.values()) <= source_rest.keys() & source_pose.keys()


def palm_frame(matrices, hand, index, thumb):
    forward = (matrices[index].translation - matrices[hand].translation).normalized()
    side = matrices[thumb].translation - matrices[hand].translation
    side = (side - forward * side.dot(forward)).normalized()
    return Matrix((forward, side, forward.cross(side))).transposed()


correction = {}
baseline_correction = {}
for target, source in mapping.items():
    q = Matrix.Identity(3).to_quaternion()
    if target in successor:
        child = successor[target]
        q = (rest[child].translation - rest[target].translation).rotation_difference(
            source_rest[mapping[child]].translation - source_rest[source].translation)
    if target in ('bip01_r_hand', 'bip01_l_hand'):
        index, thumb = target.replace('hand', 'finger1'), target.replace('hand', 'finger0')
        q = (palm_frame(source_rest, source, mapping[index], mapping[thumb]) @
             palm_frame(rest, target, index, thumb).transposed()).to_quaternion()
    baseline_correction[target] = source_rest[source].to_quaternion().inverted() @ q @ rest[target].to_quaternion()
    correction[target] = source_rest[source].to_quaternion().inverted() @ q @ rest[target].to_quaternion()
length_pairs = [('bip01_l_thigh', 'bip01_l_calf'), ('bip01_l_calf', 'bip01_l_foot')]
scale = sum((rest[x].translation - rest[y].translation).length for x, y in length_pairs) / sum(
    (source_rest[mapping[x]].translation - source_rest[mapping[y]].translation).length for x, y in length_pairs)
world = {}
baseline_world = {}
for bone in order:
    name, parent = bone.name, bone.parent
    if name in mapping:
        matrix = (source_pose[mapping[name]].to_quaternion() @ correction[name]).to_matrix().to_4x4()
        if name == 'bip01_pelvis':
            matrix.translation = Vector((0, 0, source_pose[mapping[name]].translation.z * scale))
        else:
            matrix.translation = (world[parent.name] @ rest[parent.name].inverted() @ rest[name]).translation
    else:
        matrix = world[parent.name] @ rest[parent.name].inverted() @ rest[name] if parent else rest[name].copy()
    world[name] = matrix
    if name in mapping:
        baseline = (source_pose[mapping[name]].to_quaternion() @ baseline_correction[name]).to_matrix().to_4x4()
        baseline.translation = matrix.translation if name == 'bip01_pelvis' else (
            baseline_world[parent.name] @ rest[parent.name].inverted() @ rest[name]).translation
    else:
        baseline = baseline_world[parent.name] @ rest[parent.name].inverted() @ rest[name] if parent else rest[name].copy()
    baseline_world[name] = baseline

attachment_review = None
grip_source = None
if a.rpg_trigger_fit:
    c = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    s = Matrix.Diagonal((1, 1, -1, 1))
    # Freeze the actual, previously reviewed attachment before changing the
    # finger roll. Using the corrected index as the old reference would
    # silently rotate the launcher and invalidate the accepted support pose.
    game = {name: c @ matrix @ s for name, matrix in baseline_world.items()}
    right = game['bip01_r_finger1']
    direction = (game['bip01_r_finger11'].translation - right.translation).normalized()
    side = right.col[1].xyz.cross(direction).normalized()
    up = direction.cross(side).normalized()
    basis = Matrix((side, up, direction)).transposed()
    old_offset = Vector((-.027, -.113, -.02))
    old_gun = Matrix.Identity(4)
    for index, axis_value in enumerate((side, up, direction)):
        old_gun.col[index].xyz = axis_value
    old_gun.translation = right.translation+basis@old_offset
    # Fit the palm to the actual grip, then fit the index separately. The
    # original Source launcher and this mesh have different trigger locations.
    # Reuse this RPG's actual first-person finger motion. The general body
    # animation has a different grip; the HUD clip is authored for the trigger.
    meshes=a.template.parents[2]
    hud_model=meshes/'anomaly_weapons/hands/wpn_hand_01.ogf'
    hud_motion=meshes/'dynamics/weapons/wpn_rpg7/wpn_hand_rpg7_hud_animation.omf'
    hud_weapon=meshes/'dynamics/weapons/wpn_rpg7/wpn_rpg7_hud.ogf'
    hud_weapon_motion=meshes/'dynamics/weapons/wpn_rpg7/wpn_rpg7_hud_animation.omf'
    world_weapon=meshes/'dynamics/weapons/wpn_rpg7/wpn_rpg7.ogf'
    before=set(bpy.data.objects)
    bpy.ops.xray_import.ogf(directory=str(hud_model.parent),files=[{'name':hud_model.name}],import_motions=False)
    imported=set(bpy.data.objects)-before
    hud_rig=next(obj for obj in imported if obj.type=='ARMATURE')
    hud_rest={bone.name:bone.matrix_local.copy() for bone in hud_rig.data.bones}
    for obj in imported:bpy.data.objects.remove(obj,do_unlink=True)
    spec_grip=importlib.util.spec_from_file_location('grip_reader',root/'scripts/read-omf-poses.py')
    grip_reader=importlib.util.module_from_spec(spec_grip);spec_grip.loader.exec_module(grip_reader)
    hud_game={name:Matrix(value.tolist()) for name,value in grip_reader.Motions(hud_motion,hud_model).pose(
        a.hud_grip_motion,a.hud_grip_frame,matrices=True).items()}
    grip_source = dict(motion=a.hud_grip_motion, normalized_frame=a.hud_grip_frame,
        files={str(path.relative_to(meshes)):hashlib.sha256(path.read_bytes()).hexdigest()
               for path in (hud_model,hud_motion,hud_weapon,hud_weapon_motion,world_weapon)})
    weapon_game=grip_reader.Motions(hud_weapon_motion,hud_weapon).pose('idle',.2,matrices=True)
    hud_to_world=Matrix.Identity(4)
    # The 28-vertex curved piece inside the guard is the trigger. The
    # separate 100-vertex part behind the grip is the hammer, not the trigger.
    trigger_local=Vector((.00042,.1022,.1771))
    hud_to_world.translation=trigger_local-Vector(weapon_game['spusk'][:3,3])
    grip_source['world_trigger_game']=list(trigger_local)
    source_hand=c@old_gun@hud_to_world@hud_game['r_hand']@s
    palm_rotation=(palm_frame(hud_rest,'r_hand','bip01_r_finger1','r_finger0')@
        palm_frame(rest,'bip01_r_hand','bip01_r_finger1','bip01_r_finger0').transposed()).to_quaternion()
    hand_correction=hud_rest['r_hand'].to_quaternion().inverted()@palm_rotation@rest['bip01_r_hand'].to_quaternion()
    desired_hand=(source_hand.to_quaternion()@hand_correction).to_matrix().to_4x4()
    desired_hand.translation=source_hand.translation
    desired_hand.translation+= (c@old_gun).to_3x3()@Vector((a.grip_lateral_mm/1000,0,0))
    grip_source['right_palm_lateral_mm']=a.grip_lateral_mm
    desired={name:matrix.copy() for name,matrix in world.items()}
    desired['bip01_r_hand']=desired_hand
    hud_blender={name:c@matrix@s for name,matrix in hud_game.items()}
    remap={'bip01_r_hand':'r_hand',**{f'bip01_r_finger0{suffix}':f'r_finger0{suffix}' for suffix in ('','1','2')}}
    for bone in order:
        if not any(parent.name=='bip01_r_hand' for parent in bone.parent_recursive):continue
        name,parent=bone.name,bone.parent.name
        src,src_parent=remap.get(name,name),remap.get(parent,parent)
        def anatomical_frame(matrices,bone,other,normal):
            axis=(matrices[other].translation-matrices[bone].translation).normalized()
            side=(normal-axis*normal.dot(axis)).normalized()
            return Matrix((axis,side,axis.cross(side))).transposed()
        target_normal=palm_frame(rest,'bip01_r_hand','bip01_r_finger1','bip01_r_finger0').col[2]
        source_normal=palm_frame(hud_rest,'r_hand','bip01_r_finger1','r_finger0').col[2]
        if name in successor:
            child=successor[name];src_child=remap.get(child,child)
            target_frame=anatomical_frame(rest,name,child,target_normal)
            source_frame=anatomical_frame(hud_rest,src,src_child,source_normal)
        else:
            target_frame=anatomical_frame(rest,parent,name,target_normal)
            source_frame=anatomical_frame(hud_rest,src_parent,src,source_normal)
        align_finger=(source_frame@target_frame.transposed()).to_quaternion()
        correction_finger=hud_rest[src].to_quaternion().inverted()@align_finger@rest[name].to_quaternion()
        source_world=c@old_gun@hud_to_world@hud_game[src]@s
        desired[name]=(source_world.to_quaternion()@correction_finger).to_matrix().to_4x4()
        desired[name].translation=(desired[parent]@rest[parent].inverted()@rest[name]).translation
    first, middle, last = 'bip01_r_upperarm', 'bip01_r_forearm', 'bip01_r_hand'
    origin, joint, end = [world[name].translation.copy() for name in (first, middle, last)]
    endpoint = desired[last].translation
    upper, lower = (joint-origin).length, (end-joint).length
    axis = endpoint-origin
    distance = axis.length
    assert abs(upper-lower)+.0001 < distance < upper+lower-.0001
    axis.normalize()
    along = (upper*upper-lower*lower+distance*distance)/(2*distance)
    bend = joint-origin-axis*(joint-origin).dot(axis)
    assert bend.length > .0001
    elbow = origin+axis*along+bend.normalized()*math.sqrt(max(0,upper*upper-along*along))
    for name, child, point in [(first,middle,elbow),(middle,last,endpoint)]:
        pivot = world[name].translation.copy()
        rotation = (world[child].translation-pivot).rotation_difference(point-pivot).to_matrix().to_4x4()
        transform = Matrix.Translation(pivot)@rotation@Matrix.Translation(-pivot)
        for bone in order:
            if bone.name == name or any(parent.name == name for parent in bone.parent_recursive):
                world[bone.name] = transform@world[bone.name]
    for bone in order:
        if bone.name == last or any(parent.name == last for parent in bone.parent_recursive):
            world[bone.name] = desired[bone.name]
    if a.fit_index_contact:
        # Fit a real skinned pad vertex, not a joint centre. Only the index
        # articulates; local rotations preserve the imported phalanx lengths.
        chain=['bip01_r_finger1','bip01_r_finger11','bip01_r_finger12']
        before=set(bpy.data.objects)
        bpy.ops.xray_import.ogf(directory=str(world_weapon.parent),files=[{'name':world_weapon.name}],import_motions=False)
        imported=set(bpy.data.objects)-before
        trigger_trees=[]
        weapon_vertices,weapon_triangles=[],[]
        for obj in imported:
            if obj.type!='MESH':continue
            vertices=[c@obj.matrix_world@v.co for v in obj.data.vertices]
            # Only the curved trigger's connected geometry occupies this box.
            indices={i for i,point in enumerate(vertices) if abs(point.x)<.005 and .085<point.y<.12 and .165<point.z<.19}
            obj.data.calc_loop_triangles()
            base=len(weapon_vertices)
            weapon_vertices.extend(c@old_gun@point for point in vertices)
            weapon_triangles.extend(tuple(base+i for i in tri.vertices) for tri in obj.data.loop_triangles)
            triangles=[tuple(tri.vertices) for tri in obj.data.loop_triangles if all(i in indices for i in tri.vertices)]
            if triangles:trigger_trees.append(BVHTree.FromPolygons(vertices,triangles,all_triangles=True))
        assert len(trigger_trees)==1,'Re-identify the actual RPG trigger geometry'
        surface,normal,_,_=trigger_trees[0].find_nearest(trigger_local+Vector((0,0,.014)))
        # Touch the forward-facing surface; pressing is toward the grip,
        # not sideways through the trigger. Check the whole skin separately;
        # contact at a single pad vertex does not exclude penetration nearby.
        target_local=surface+Vector((0,0,a.trigger_clearance_mm/1000))
        target=c@old_gun@target_local
        grip_source['index_contact_target_game']=list(target_local)
        for obj in imported:bpy.data.objects.remove(obj,do_unlink=True)
        weapon_tree=BVHTree.FromPolygons(weapon_vertices,weapon_triangles,all_triangles=True)
        def skin(weights, matrices):
            return sum(((matrices[name]@point)*weight for name,point,weight in weights),Vector((0,0,0)))
        samples=[]
        for obj in bpy.data.objects:
            if obj.type!='MESH':continue
            distal=obj.vertex_groups.get(chain[-1])
            if distal is None:continue
            for vertex in obj.data.vertices:
                if sum(g.weight for g in vertex.groups if g.group==distal.index)<.7:continue
                point=rig.matrix_world.inverted()@obj.matrix_world@vertex.co
                weights=[(obj.vertex_groups[g.group].name,
                          rest[obj.vertex_groups[g.group].name].inverted()@point,g.weight)
                         for g in vertex.groups if obj.vertex_groups[g.group].name in rest]
                samples.append(weights)
        assert samples
        index_vertices,index_triangles=[],[]
        for obj in bpy.data.objects:
            if obj.type!='MESH':continue
            groups={group.index for group in obj.vertex_groups if group.name in chain}
            influenced={v.index for v in obj.data.vertices if any(g.group in groups and g.weight>=.35 for g in v.groups)}
            if not influenced:continue
            obj.data.calc_loop_triangles()
            triangles=[]
            for tri in obj.data.loop_triangles:
                if not any(i in influenced for i in tri.vertices):continue
                weights={}
                for i in tri.vertices:
                    for g in obj.data.vertices[i].groups:
                        name=obj.vertex_groups[g.group].name;weights[name]=weights.get(name,0)+g.weight
                # The palm/grip seam shares small index weights. Its fixed
                # hand contact must not drive the finger into a different pose.
                if max(weights,key=weights.get) in chain:triangles.append(tuple(tri.vertices))
            used={i for tri in triangles for i in tri};lookup={}
            for i in sorted(used):
                vertex=obj.data.vertices[i]
                point=rig.matrix_world.inverted()@obj.matrix_world@vertex.co
                weights=[(obj.vertex_groups[g.group].name,rest[obj.vertex_groups[g.group].name].inverted()@point,g.weight)
                         for g in vertex.groups if obj.vertex_groups[g.group].name in rest]
                lookup[i]=len(index_vertices);index_vertices.append(weights)
            index_triangles.extend(tuple(lookup[i] for i in tri) for tri in triangles)
        pad=min(samples,key=lambda weights:(skin(weights,world)-target).length_squared)
        relative={name:world[rig.data.bones[name].parent.name].inverted()@world[name] for name in chain}
        proximal=world[chain[1]].translation-world[chain[0]].translation
        intermediate=world[chain[2]].translation-world[chain[1]].translation
        hinge=proximal.cross(intermediate).normalized()
        assert hinge.length>.99
        axes=[world[name].to_3x3().inverted()@hinge for name in chain]
        spread=world[chain[0]].to_3x3().inverted()@proximal.cross(hinge).normalized()
        def fitted(angles):
            result={name:matrix.copy() for name,matrix in world.items()}
            for i,name in enumerate(chain):
                parent=rig.data.bones[name].parent.name
                rotation=Matrix.Rotation(angles[i],4,axes[i])
                if i==0:rotation=rotation@Matrix.Rotation(angles[3],4,spread)
                result[name]=result[parent]@relative[name]@rotation
            return result
        def score(angles):
            matrices=fitted(angles)
            distance=(skin(pad,matrices)-target).length_squared
            collisions=0
            if a.avoid_index_penetration:
                points=[skin(weights,matrices) for weights in index_vertices]
                tree=BVHTree.FromPolygons(points,index_triangles,all_triangles=True)
                collisions=len(weapon_tree.overlap(tree))
            return distance+(.0005**2)*sum(v*v for v in angles)+collisions*.000004
        bounds=[math.radians(v) for v in (55,65,70,30)]
        seeds=[[0.0]*4]
        if a.avoid_index_penetration:
            rng=random.Random(61104)
            seeds.extend([[rng.uniform(-bound,bound) for bound in bounds] for _ in range(160)])
            seeds=sorted(seeds,key=score)[:6]
        solutions=[]
        for seed in seeds:
            angles=seed.copy()
            for step_degrees in (12,6,3,1,.3,.1):
                step=math.radians(step_degrees)
                for iteration in range(100):
                    best,changed=score(angles),False
                    for j in range(4):
                        for sign in (-1,1):
                            trial=angles.copy();trial[j]=max(-bounds[j],min(bounds[j],trial[j]+step*sign))
                            value=score(trial)
                            if value<best:
                                angles,best,changed=trial,value,True
                    if not changed:break
            solutions.append(angles)
        angles=min(solutions,key=score)
        solved=fitted(angles)
        for name in chain:world[name]=solved[name]
        contact_error=(skin(pad,world)-target).length
        print('INDEX_FIT',contact_error,[math.degrees(v) for v in angles],
              list(old_gun.inverted()@c@skin(pad,world)))
        assert contact_error<(.02 if a.avoid_index_penetration else .003), ('Index pad cannot reach trigger',contact_error)
        overlaps=weapon_tree.overlap(BVHTree.FromPolygons(
            [skin(weights,world) for weights in index_vertices],index_triangles,all_triangles=True))
        collision_pairs=len(overlaps)
        assert not a.avoid_index_penetration or collision_pairs==0, ('Refit the index surface',collision_pairs)
        collision_bones={}
        for _,triangle in overlaps:
            weights={}
            for index in index_triangles[triangle]:
                for name,_,weight in index_vertices[index]:weights[name]=weights.get(name,0)+weight
            dominant=max(weights,key=weights.get)
            collision_bones[dominant]=collision_bones.get(dominant,0)+1
        grip_source['index_contact_fit']=dict(pad_error_metres=contact_error,
            requested_clearance_mm=a.trigger_clearance_mm,
            index_dominant_triangles_weapon_intersections=collision_pairs,
            intersections_by_dominant_bone=collision_bones,
            collision_aware_fit=a.avoid_index_penetration,
            local_angle_adjustments_degrees=[math.degrees(v) for v in angles],
            palm_unchanged=world['bip01_r_hand']==desired['bip01_r_hand'])
    for name in ('bip01_l_upperarm','bip01_l_forearm','bip01_l_hand','bip01_head','bip01_pelvis'):
        assert world[name] == desired[name], 'Only the right arm may change'
    new_right=c@world['bip01_r_finger1']@s
    new_next=c@world['bip01_r_finger11']@s
    new_direction=(new_next.translation-new_right.translation).normalized()
    new_side=new_right.col[1].xyz.cross(new_direction).normalized()
    new_up=new_direction.cross(new_side).normalized()
    new_base=Matrix.Identity(4)
    for index,axis_value in enumerate((new_side,new_up,new_direction)):
        new_base.col[index].xyz=axis_value
    new_base.translation=new_right.translation
    new_offset=new_base.inverted()@old_gun
    restored=new_base@new_offset
    position_error=(restored.translation-old_gun.translation).length
    rotation_error=max(abs(restored[r][k]-old_gun[r][k]) for r in range(3) for k in range(3))
    assert position_error<.000001 and rotation_error<.000001
    attachment_review = dict(matrix_game=[list(row) for row in new_offset],game_change_required=True,installed=False,
        left_arm_unchanged=True,weapon_origin_error_metres=position_error,weapon_rotation_error_coefficient=rotation_error)

rig.animation_data_create()
action = bpy.data.actions.new('review_smd_prone_launcher')
rig.animation_data.action = action
action.xray.fps = 30
action.xray.speed = 1
for bone in order:
    for constraint in list(bone.constraints):
        bone.constraints.remove(constraint)
    bone.rotation_mode = 'QUATERNION'
    kwargs = {} if bone.parent is None else dict(parent_matrix=world[bone.parent.name], parent_matrix_local=bone.parent.bone.matrix_local)
    bone.matrix_basis = bone.bone.convert_local_to_pose(world[bone.name], bone.bone.matrix_local, invert=True, **kwargs)
    for frame in (0, 1):
        bone.keyframe_insert('location', frame=frame)
        bone.keyframe_insert('rotation_quaternion', frame=frame)
        bone.keyframe_insert('scale', frame=frame)
rig.xray.motions_collection.clear()
item = rig.xray.motions_collection.add()
item.name = action.name
spec = importlib.util.spec_from_file_location('merge', root / 'scripts/tools/merge-player-anims.py')
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)
for name, bones in merge.parse(root / 'scripts/netcoop-overlay/client/meshes/actors/stalker_animation.omf')['parts']:
    collection = rig.data.collections.new(name)
    for name, _ in bones:
        collection.assign(rig.data.bones[name])
bpy.context.scene.frame_set(0)
bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT')
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.wm.save_as_mainfile(filepath=str(a.out / 'candidate.blend'))
assert bpy.ops.xray_export.omf_file(filepath=str(a.out / 'candidate.omf'), high_quality=True, fmt_ver='cscop') == {'FINISHED'}
spec = importlib.util.spec_from_file_location('poses', root / 'scripts/read-omf-poses.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
exported = reader.Motions(a.out / 'candidate.omf', a.template).pose(action.name, 0, matrices=True)
c = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
s = Matrix.Diagonal((1, 1, -1, 1))
worst_position = worst_rotation = 0
for name, expected in world.items():
    actual = c @ Matrix(exported[name].tolist()) @ s
    worst_position = max(worst_position, (actual.translation - expected.translation).length)
    worst_rotation = max(worst_rotation, max(abs(actual[r][k] - expected[r][k]) for r in range(3) for k in range(3)))
    parent = rig.data.bones[name].parent
    if parent and name not in ('bip01', 'bip01_pelvis'):
        assert abs((actual.translation - (c @ Matrix(exported[parent.name].tolist()) @ s).translation).length -
                   (rest[name].translation - rest[parent.name].translation).length) < .001
assert worst_position < .001 and worst_rotation < .002
(a.out / 'review.json').write_text(json.dumps(dict(installed=False,reference_only=True,redistribution_cleared=False,
    source_sha256=hashlib.sha256(a.pose.read_bytes()).hexdigest(),reference_sha256=hashlib.sha256(a.reference.read_bytes()).hexdigest(),
    candidate_sha256=hashlib.sha256((a.out/'candidate.omf').read_bytes()).hexdigest(),roundtrip_position_metres=worst_position,
    roundtrip_rotation_coefficient=worst_rotation,scale=scale,attachment_review=attachment_review,
    grip_source=grip_source),indent=2)+'\n')
print('PRIVATE_WHOLE_POSE_REFERENCE_READY',a.out)
