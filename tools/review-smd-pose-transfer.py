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
import sys

import addon_utils
import bpy
from mathutils import Euler, Matrix, Vector

p = argparse.ArgumentParser(description=__doc__)
for name in ('reference', 'pose', 'template', 'addons', 'out'):
    p.add_argument('--' + name, required=True, type=Path)
p.add_argument('--rpg-trigger-fit', action='store_true', help='Private right-hand fit with a matching, recorded RPG attachment offset')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
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
    if a.rpg_trigger_fit and target.startswith('bip01_r_finger'):
        # Matching only the phalanx direction leaves its flexion plane free
        # to roll. Constrain it to the same palm normal on both skeletons.
        def finger_frame(matrices, name, child, normal):
            axis = (matrices[child].translation-matrices[name].translation).normalized()
            side = (normal-axis*normal.dot(axis)).normalized()
            return Matrix((axis,side,axis.cross(side))).transposed()
        hand='bip01_r_hand'
        target_normal=palm_frame(rest,hand,'bip01_r_finger1','bip01_r_finger0').col[2]
        source_normal=palm_frame(source_rest,mapping[hand],mapping['bip01_r_finger1'],mapping['bip01_r_finger0']).col[2]
        if target in successor:
            child=successor[target]
            target_frame=finger_frame(rest,target,child,target_normal)
            source_frame=finger_frame(source_rest,source,mapping[child],source_normal)
        else:
            parent=rig.data.bones[target].parent.name
            target_frame=finger_frame(rest,parent,target,target_normal)
            source_frame=finger_frame(source_rest,mapping[parent],source,source_normal)
        q=(source_frame@target_frame.transposed()).to_quaternion()
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
    wrist_game = (c@world['bip01_r_hand']@s).translation
    target_wrist = old_gun@Vector((.02,.07,.035))
    delta = basis.inverted()@(target_wrist-wrist_game)
    shift_game = basis @ delta
    shift = Vector((shift_game.x, shift_game.z, shift_game.y))
    desired = {name: matrix.copy() for name, matrix in world.items()}
    for bone in order:
        if bone.name == 'bip01_r_hand' or any(parent.name == 'bip01_r_hand' for parent in bone.parent_recursive):
            desired[bone.name] = Matrix.Translation(shift) @ world[bone.name]
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
    for name in ('bip01_l_upperarm','bip01_l_forearm','bip01_l_hand','bip01_head','bip01_pelvis'):
        assert world[name] == desired[name], 'Only the right arm may change'
    # The two proximal phalanges form a hook round the trigger guard. The
    # distal pad faces the measured trigger component (Z .099..133 m).
    first,middle,last='bip01_r_finger1','bip01_r_finger11','bip01_r_finger12'
    point_game=old_gun@Vector((-.012,.108,.117))
    endpoint=Vector((point_game.x,point_game.z,point_game.y))
    origin,joint,end=[world[name].translation.copy() for name in (first,middle,last)]
    upper,lower=(joint-origin).length,(end-joint).length
    axis=endpoint-origin;distance=axis.length
    assert abs(upper-lower)+.0001 < distance < upper+lower-.0001
    axis.normalize();along=(upper*upper-lower*lower+distance*distance)/(2*distance)
    bend=joint-origin-axis*(joint-origin).dot(axis)
    assert bend.length>.0001
    joint_target=origin+axis*along+bend.normalized()*math.sqrt(max(0,upper*upper-along*along))
    for name,child,point in [(first,middle,joint_target),(middle,last,endpoint)]:
        pivot=world[name].translation.copy()
        rotation=(world[child].translation-pivot).rotation_difference(point-pivot).to_matrix().to_4x4()
        transform=Matrix.Translation(pivot)@rotation@Matrix.Translation(-pivot)
        for bone in order:
            if bone.name==name or any(parent.name==name for parent in bone.parent_recursive):
                world[bone.name]=transform@world[bone.name]
    pad_game=old_gun@Vector((.0003,.1047,.1157))
    pad=Vector((pad_game.x,pad_game.z,pad_game.y))
    pivot=world[last].translation.copy()
    rest_axis=(rest[last].translation-rest[middle].translation).normalized()
    pad_axis=world[last].to_quaternion()@rest[last].to_quaternion().inverted()@rest_axis
    rotation=pad_axis.rotation_difference(pad-pivot).to_matrix().to_4x4()
    world[last]=Matrix.Translation(pivot)@rotation@Matrix.Translation(-pivot)@world[last]
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
    roundtrip_rotation_coefficient=worst_rotation,scale=scale,attachment_review=attachment_review),indent=2)+'\n')
print('PRIVATE_WHOLE_POSE_REFERENCE_READY',a.out)
