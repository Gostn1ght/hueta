"""Offline review of official, owner-downloaded Mixamo FBX on the actual game rig.

Blender --background --python this.py -- --source-dir PRIVATE --template ACTOR
 --addons ADDONS --out PRIVATE --clip 'Prone Forward.fbx=review_prone_fwd'
Raw FBX/characters remain private. This tool never installs or publishes clips.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import addon_utils
import bpy
from mathutils import Matrix, Vector

p = argparse.ArgumentParser(description=__doc__)
for name in ('source-dir', 'template', 'addons', 'out'):
    p.add_argument('--' + name, type=Path, required=True)
p.add_argument('--clip', action='append', required=True)
p.add_argument('--root-mode', choices=['in-place', 'seat', 'preserve'], default='in-place')
p.add_argument('--lock-facing', action='store_true', help='Remove donor turn yaw; the network actor owns facing')
p.add_argument('--steering-fit', type=Path, help='Private model-specific wheel contacts in actor Blender space')
p.add_argument('--weapon-grip', choices=['pistol', 'rifle', 'launcher', 'knife'], help='Private idle review: original game weapon grip, with captured elbow bend planes')
p.add_argument('--prone-aim-layer', type=Path, help='Reviewed same-skeleton OMF weapon hold; parent-relative arms follow captured chest motion')
p.add_argument('--prone-aim-motion', default='review_rifle_idle')
p.add_argument('--no-save-blend', action='store_true', help='Export motion and review without a large editable scene')
p.add_argument('--grounding-audit', type=Path, help='Complete per-key actor/weapon floor audit for this same source and rig')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
assert not (a.weapon_grip and a.steering_fit)
steering_fit = json.loads(a.steering_fit.read_text()) if a.steering_fit else None
grounding = json.loads(a.grounding_audit.read_text()) if a.grounding_audit else None
if grounding:
    assert a.prone_aim_layer and grounding['actor_sha256'] == hashlib.sha256(a.template.read_bytes()).hexdigest()
    assert grounding['aim_layer_sha256'] == hashlib.sha256(a.prone_aim_layer.read_bytes()).hexdigest()
if steering_fit:
    assert a.root_mode == 'seat'
    assert hashlib.sha256(Path(steering_fit['model_path']).read_bytes()).hexdigest() == steering_fit['model_sha256']
a.out.mkdir(parents=True, exist_ok=True)
(a.out / 'review.json').unlink(missing_ok=True) # a failed retry cannot retain an old approval receipt
root = Path(__file__).resolve().parents[1]
provenance = json.loads((a.source_dir / 'provenance.json').read_text())
assert provenance['source'] == 'https://www.mixamo.com/' and not provenance['raw_redistribution']
verified = {row['path']: row for row in provenance['files']}
clips = [value.split('=', 1) for value in a.clip]
for file, name in clips:
    assert Path(file).name == file and name.startswith('review_')
    assert hashlib.sha256((a.source_dir / file).read_bytes()).hexdigest() == verified[file]['sha256']
sys.path.insert(0, str(a.addons))
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('io_scene_xray', default_set=True, persistent=False)
bpy.ops.xray_import.ogf(directory=str(a.template.parent), files=[{'name': a.template.name}], import_motions=False)
target = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
assert len(target.data.bones) == 47
target.animation_data_create()
target.xray.motions_collection.clear()
rest = {bone.name: bone.matrix_local.copy() for bone in target.data.bones}
order = sorted(target.pose.bones, key=lambda bone: len(bone.parent_recursive))
for bone in order:
    for constraint in list(bone.constraints):
        bone.constraints.remove(constraint)
    bone.rotation_mode = 'QUATERNION'
spec = importlib.util.spec_from_file_location('merge', root / 'scripts/tools/merge-player-anims.py')
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)
for name, bones in merge.parse(root / 'scripts/netcoop-overlay/client/meshes/actors/stalker_animation.omf')['parts']:
    collection = target.data.collections.new(name)
    for bone, _ in bones:
        collection.assign(target.data.bones[bone])
mapping = {'bip01_pelvis': 'Hips', 'bip01_spine': 'Spine', 'bip01_spine1': 'Spine1', 'bip01_spine2': 'Spine2',
           'bip01_neck': 'Neck', 'bip01_head': 'Head'}
successor = {'bip01_pelvis': 'bip01_spine', 'bip01_spine': 'bip01_spine1', 'bip01_spine1': 'bip01_spine2',
             'bip01_spine2': 'bip01_neck', 'bip01_neck': 'bip01_head'}
for side, label in [('l', 'Left'), ('r', 'Right')]:
    for dst, src in [('clavicle', 'Shoulder'), ('upperarm', 'Arm'), ('forearm', 'ForeArm'), ('hand', 'Hand'),
                     ('thigh', 'UpLeg'), ('calf', 'Leg'), ('foot', 'Foot'), ('toe0', 'ToeBase')]:
        mapping['bip01_' + side + '_' + dst] = label + src
    for finger, label2 in [('0', 'Thumb'), ('1', 'Index'), ('2', 'Middle')]:
        for index, suffix in [(1, ''), (2, '1'), (3, '2')]:
            mapping['bip01_' + side + '_finger' + finger + suffix] = label + 'Hand' + label2 + str(index)
    for first, second in [('clavicle', 'upperarm'), ('upperarm', 'forearm'), ('forearm', 'hand'),
                          ('thigh', 'calf'), ('calf', 'foot'), ('foot', 'toe0'), ('hand', 'finger1')]:
        successor['bip01_' + side + '_' + first] = 'bip01_' + side + '_' + second
    for finger in ('0', '1', '2'):
        for suffix, child in [('', '1'), ('1', '2')]:
            successor['bip01_' + side + '_finger' + finger + suffix] = 'bip01_' + side + '_finger' + finger + child
mapping = {dst: 'mixamorig:' + src for dst, src in mapping.items()}
align = Matrix.Rotation(math.pi, 4, 'Z')  # downloaded default character faces -Y
samples = []
metadata = []
aim_layer = None
if a.prone_aim_layer:
    assert a.weapon_grip in ('rifle','launcher') and a.lock_facing
    spec_layer = importlib.util.spec_from_file_location('aim_poses', root / 'scripts/read-omf-poses.py')
    layer_reader = importlib.util.module_from_spec(spec_layer)
    spec_layer.loader.exec_module(layer_reader)
    layer_pose = layer_reader.Motions(a.prone_aim_layer, a.template).pose(a.prone_aim_motion, 0, matrices=True)
    layer_c = Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)))
    layer_s = Matrix.Diagonal((1,1,-1,1))
    aim_layer = {name:layer_c @ Matrix(matrix.tolist()) @ layer_s for name,matrix in layer_pose.items()}
canonical = None
if a.weapon_grip:
    spec = importlib.util.spec_from_file_location('poses', root / 'scripts/read-omf-poses.py')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    stock = reader.Motions(root / 'scripts/netcoop-overlay/client/meshes/actors/stalker_animation.omf', a.template)
    slot = {'pistol': 1, 'rifle': 2, 'launcher': 4, 'knife': 5}[a.weapon_grip]
    raw = {name: Matrix(matrix.tolist()) for name, matrix in stock.pose(f'norm_torso_{slot}_aim_0', .2, matrices=True).items()}
    c = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    s = Matrix.Diagonal((1, 1, -1, 1))
    grip = {name: c @ matrix @ s for name, matrix in raw.items()}
    # Existing motion libraries can carry another model's finger offsets.
    # Transfer their orientations, keeping THIS actor's joint translations.
    for bone in order:
        if any(parent.name in ('bip01_l_hand', 'bip01_r_hand') for parent in bone.parent_recursive):
            parent = bone.parent.name
            grip[bone.name].translation = (grip[parent] @ rest[parent].inverted() @ rest[bone.name]).translation
    raw = {name: c @ matrix @ s for name, matrix in grip.items()}
    right = raw['bip01_r_finger1']
    direction = (raw['bip01_r_finger11'].translation - right.translation).normalized()
    side = right.col[1].xyz.cross(direction).normalized()
    up = direction.cross(side).normalized()
    basis = Matrix.Identity(4)
    for index, axis in enumerate((side, up, direction)):
        basis.col[index].xyz = axis
    canonical = {name: c @ basis.inverted() @ matrix @ s for name, matrix in raw.items()}
    if a.weapon_grip == 'launcher':
        # The stock torso pose's left hand sits behind the trigger, not on
        # this RPG-7 mesh's front vertical grip (Z .109..214, Y 0..140 m).
        # Place the left palm outside that grip and turn its curled fingers
        # around it. This does not change the right-index weapon anchors.
        local = {name: c @ matrix @ s for name, matrix in canonical.items()}
        target_wrist = local['bip01_r_finger1'].translation + Vector((-.027, -.113, -.02)) + Vector((-.08, .035, .10))
        transform = Matrix.Translation(target_wrist) @ Matrix.Rotation(math.radians(-30), 4, 'Z') @ Matrix.Translation(-local['bip01_l_hand'].translation)
        for bone in order:
            if bone.name == 'bip01_l_hand' or any(parent.name == 'bip01_l_hand' for parent in bone.parent_recursive):
                canonical[bone.name] = c @ transform @ local[bone.name] @ s


def fit_hands(world, desired, labels=('r', 'l'), launcher=False):
    """Solve wrists without moving the seated/prone body or scaling limbs."""
    for label in labels:
        first, middle, last = ['bip01_' + label + '_' + name for name in ('upperarm', 'forearm', 'hand')]
        origin, joint, end = [world[name].translation.copy() for name in (first, middle, last)]
        endpoint = desired[last].translation
        upper, lower = (joint - origin).length, (end - joint).length
        delta = endpoint - origin
        distance = delta.length
        assert abs(upper - lower) + .0001 < distance < upper + lower - .0001, (a.weapon_grip, label, 'unreachable', distance, upper + lower)
        axis = delta / distance
        along = (upper * upper - lower * lower + distance * distance) / (2 * distance)
        # Keep the RPG elbow behind its wrist, so the forearm approaches the
        # grip forwards instead of forcing a near-right-angle wrist bend.
        hand_direction = (desired[f'bip01_{label}_finger1'].translation - endpoint).normalized()
        pole = endpoint - lower * hand_direction - origin if launcher else joint - origin
        bend = pole - axis * pole.dot(axis)
        assert bend.length > .0001
        bend.normalize()
        elbow = origin + axis * along + bend * math.sqrt(max(0, upper * upper - along * along))
        for name, child, point in [(first, middle, elbow), (middle, last, endpoint)]:
            pivot = world[name].translation.copy()
            rotation = (world[child].translation - pivot).rotation_difference(point - pivot).to_matrix().to_4x4()
            transform = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
            for bone in order:
                if bone.name == name or any(parent.name == name for parent in bone.parent_recursive):
                    world[bone.name] = transform @ world[bone.name]
        if launcher:
            # Match the RPG grip's forearm roll as well as its wrist position.
            # A donor rifle cuff can otherwise twist into the tube despite
            # correctly solved elbow/wrist joint centres.
            swing = (desired[last].translation - desired[middle].translation).rotation_difference(endpoint - elbow)
            world[middle] = swing.to_matrix().to_4x4() @ desired[middle].to_quaternion().to_matrix().to_4x4()
            world[middle].translation = elbow
        for bone in order:
            if bone.name == last or any(parent.name == last for parent in bone.parent_recursive):
                world[bone.name] = desired[bone.name].copy()


def fit_weapon(world):
    """Keep the source body; place proven finger grips through unstretched arms."""
    anchor = world['bip01_r_finger1'].translation.copy()
    if a.weapon_grip in ('rifle', 'pistol'):
        # A crawling donor alternates hands across its centreline. A two-hand
        # weapon must stay on its firing shoulder rather than follow that hand
        # through the head/torso at every stride.
        shoulders = (world['bip01_r_upperarm'].translation + world['bip01_l_upperarm'].translation) * .5
        anchor = shoulders + Vector((.25 if a.weapon_grip=='rifle' else .04, .30, -.12))

    if a.weapon_grip == 'launcher':
        anchor += Vector((.10, 0, .09))
        shoulder = world['bip01_r_upperarm'].translation
        # RPG-7 tube centre is ~49 mm above the right finger anchor after its
        # real LTX offset. Raise it above the shoulder/upper-arm envelope;
        # lowering only the elbow still leaves the tube through the arm.
        anchor.z = max(anchor.z, shoulder.z + .055)
        anchor.x = max(anchor.x, shoulder.x + .075)
    # Both wrists must be reachable by this skeleton. Moving only the left
    # wrist destroys the weapon grip; project the whole grip into the two arm
    # reach volumes instead, without changing limb lengths or the body pose.
    origin = canonical['bip01_r_finger1'].translation
    labels = ('r',) if a.weapon_grip == 'knife' else ('r', 'l')
    minimum_x = world['bip01_head'].translation.x + .22 if a.weapon_grip == 'rifle' else None
    for _ in range(128):
        corrected = False
        for label in labels:
            shoulder, elbow, wrist = [world[f'bip01_{label}_{part}'].translation for part in ('upperarm','forearm','hand')]
            reach = (elbow-shoulder).length + (wrist-elbow).length - .012
            centre = shoulder - (canonical[f'bip01_{label}_hand'].translation - origin)
            delta = anchor - centre
            if delta.length > reach:
                anchor = centre + delta.normalized() * reach
                corrected = True
        if minimum_x is not None and anchor.x < minimum_x:
            anchor.x = minimum_x
            corrected = True
        if not corrected: break
    shift = anchor - origin
    desired = {name: Matrix.Translation(shift) @ matrix for name, matrix in canonical.items()}
    fit_hands(world, desired, ('r',) if a.weapon_grip == 'knife' else ('r', 'l'), a.weapon_grip in ('launcher', 'rifle', 'pistol'))


def fit_steering(world):
    lean = float(steering_fit.get('torso_lean_degrees', 0))
    assert 0 <= lean <= 5
    pelvis = world['bip01_pelvis'].translation
    transform = Matrix.Translation(pelvis) @ Matrix.Rotation(math.radians(-lean), 4, 'X') @ Matrix.Translation(-pelvis)
    for bone in order:
        if bone.name == 'bip01_spine' or any(parent.name == 'bip01_spine' for parent in bone.parent_recursive):
            world[bone.name] = transform @ world[bone.name]
    desired = {name: matrix.copy() for name, matrix in world.items()}
    for label in ('r', 'l'):
        last = f'bip01_{label}_hand'
        anchor = f'bip01_{label}_finger1'
        shift = Vector(steering_fit['finger_contacts_actor_blender'][label]) - world[anchor].translation
        for bone in order:
            if bone.name == last or any(parent.name == last for parent in bone.parent_recursive):
                desired[bone.name] = Matrix.Translation(shift) @ world[bone.name]
    fit_hands(world, desired)


for file, name in clips:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(a.source_dir / file))
    imported = set(bpy.data.objects) - before
    donor = next(obj for obj in imported if obj.type == 'ARMATURE')
    assert set(mapping.values()) <= set(donor.pose.bones.keys())
    source_action = donor.animation_data.action
    start, end = source_action.frame_range
    frames = round(end - start) + 1
    source_rest = {bone.name: align @ donor.matrix_world @ bone.matrix_local for bone in donor.data.bones}
    source_leg = sum((source_rest[mapping[first]].translation - source_rest[mapping[second]].translation).length
                     for first, second in [('bip01_l_thigh', 'bip01_l_calf'), ('bip01_l_calf', 'bip01_l_foot')])
    target_leg = sum((rest[first].translation - rest[second].translation).length
                     for first, second in [('bip01_l_thigh', 'bip01_l_calf'), ('bip01_l_calf', 'bip01_l_foot')])
    scale = target_leg / source_leg
    correction = {}
    for dst, src in mapping.items():
        q = Matrix.Identity(3).to_quaternion()
        if dst in successor:
            child = successor[dst]
            q = (rest[child].translation - rest[dst].translation).rotation_difference(
                source_rest[mapping[child]].translation - source_rest[src].translation)
        if dst in ('bip01_l_hand', 'bip01_r_hand'):
            # Index direction alone leaves palm roll unconstrained. Use the
            # thumb as a second independent rest axis, so the captured grip
            # faces the wheel rather than merely putting the wrist near it.
            def palm_frame(matrices, hand, index, thumb):
                forward = (matrices[index].translation - matrices[hand].translation).normalized()
                side = matrices[thumb].translation - matrices[hand].translation
                side = (side - forward * side.dot(forward)).normalized()
                return Matrix((forward, side, forward.cross(side))).transposed()
            index, thumb = dst.replace('hand', 'finger1'), dst.replace('hand', 'finger0')
            q = (palm_frame(source_rest, src, mapping[index], mapping[thumb]) @
                 palm_frame(rest, dst, index, thumb).transposed()).to_quaternion()
        correction[dst] = source_rest[src].to_quaternion().inverted() @ q @ rest[dst].to_quaternion()
    endpoints = []
    for frame in (start, end):
        bpy.context.scene.frame_set(round(frame))
        bpy.context.view_layer.update()
        endpoints.append((align @ donor.matrix_world @ donor.pose.bones[mapping['bip01_pelvis']].matrix).translation * scale)
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    action.xray.fps = 30
    action.xray.speed = 1
    target.animation_data.action = action
    for frame in range(frames):
        bpy.context.scene.frame_set(round(start + frame))
        bpy.context.view_layer.update()
        world = {}
        for bone in order:
            dst = bone.name
            parent = bone.parent
            if dst in mapping:
                source = align @ donor.matrix_world @ donor.pose.bones[mapping[dst]].matrix
                pose = (source.to_quaternion() @ correction[dst]).to_matrix().to_4x4()
                if dst == 'bip01_pelvis':
                    location = source.translation * scale
                    if a.root_mode == 'seat':
                        location = Vector((0, 0, 0))
                    elif a.root_mode == 'in-place':
                        drift = endpoints[0].lerp(endpoints[1], frame / max(1, frames - 1))
                        location.x -= drift.x
                        location.y -= drift.y
                    pose.translation = location
                else:
                    pose.translation = (world[parent.name] @ rest[parent.name].inverted() @ rest[dst]).translation
            else:
                pose = world[parent.name] @ rest[parent.name].inverted() @ rest[dst] if parent else rest[dst].copy()
            world[dst] = pose
        if a.lock_facing:
            hips = world['bip01_r_thigh'].translation - world['bip01_l_thigh'].translation
            yaw = math.atan2(hips.y, hips.x)
            pivot = world['bip01_pelvis'].translation
            turn = Matrix.Translation(pivot) @ Matrix.Rotation(-yaw, 4, 'Z') @ Matrix.Translation(-pivot)
            world = {name: turn @ matrix for name, matrix in world.items()}
        if aim_layer:
            # The locomotion donor plants its hands. Its wrist roll must not
            # rotate the held rifle into the ground. Retain the reviewed
            # weapon hold as a hierarchy-local layer: chest sway and the
            # engine's view callback carry BOTH hands and weapon together.
            chest = 'bip01_neck'
            hips = world['bip01_r_thigh'].translation - world['bip01_l_thigh'].translation
            heading = math.atan2(hips.y, hips.x)
            arm_frame = Matrix.Translation(world[chest].translation) @ Matrix.Rotation(heading, 4, 'Z') @ Matrix.Translation(-aim_layer[chest].translation)
            for bone in order:
                bone_name, parent = bone.name, bone.parent
                if bone_name.startswith(('bip01_r_', 'bip01_l_')) and any(part in bone_name for part in ('clavicle','upperarm','forearm','hand','finger')):
                    world[bone_name] = arm_frame @ aim_layer[bone_name]
        elif canonical:
            fit_weapon(world)
        if steering_fit:
            fit_steering(world)
        if grounding:
            contact = grounding['clips'][name]
            assert contact['frames'] == frames and contact['source_sha256'] == verified[file]['sha256']
            lift = contact['lift_metres'][frame]
            assert 0 <= lift < .3
            # One smooth root correction moves the WHOLE rig, preserving all
            # joints and the weapon grip. Do not lift wrists independently.
            world = {bone_name: Matrix.Translation((0,0,lift)) @ matrix for bone_name,matrix in world.items()}
        for bone in order:
            kwargs = {} if bone.parent is None else dict(parent_matrix=world[bone.parent.name], parent_matrix_local=bone.parent.bone.matrix_local)
            bone.matrix_basis = bone.bone.convert_local_to_pose(world[bone.name], bone.bone.matrix_local, invert=True, **kwargs)
            bone.keyframe_insert('location', frame=frame)
            bone.keyframe_insert('rotation_quaternion', frame=frame)
            bone.keyframe_insert('scale', frame=frame)
        bpy.context.view_layer.update()
        if frame in sorted({0, frames // 4, frames // 2, 3 * frames // 4, frames - 1}):
            samples.append(dict(clip=name, frame=frame, frames=frames,
                                matrices={bone: [list(row) for row in target.pose.bones[bone].matrix] for bone in rest}))
    for curve in action.fcurves:
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'
    item = target.xray.motions_collection.add()
    item.name = name
    metadata.append(dict(source=file, sha256=verified[file]['sha256'], clip=name, frames=frames, scale=scale))
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    print('REVIEW_RETARGETED', name, frames, scale, flush=True)
bpy.ops.object.select_all(action='DESELECT')
target.select_set(True)
bpy.context.view_layer.objects.active = target
if not a.no_save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=str(a.out / 'candidate.blend'))
assert bpy.ops.xray_export.omf_file(filepath=str(a.out / 'candidate.omf'), high_quality=True, fmt_ver='cscop') == {'FINISHED'}
spec = importlib.util.spec_from_file_location('poses', root / 'scripts/read-omf-poses.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
exported = reader.Motions(a.out / 'candidate.omf', a.template)
convert = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
bone_axes = Matrix.Diagonal((1, 1, -1, 1))
worst = 0
worst_angle = 0
worst_rotation_coefficient = 0
for sample in samples:
    pose = exported.pose(sample['clip'], sample['frame'] / sample['frames'], matrices=True)
    for bone in rest:
        actual = convert @ Matrix(pose[bone].tolist()) @ bone_axes
        expected = Matrix(sample['matrices'][bone])
        worst = max(worst, (actual.translation - expected.translation).length)
        worst_rotation_coefficient = max(worst_rotation_coefficient,
            max(abs(actual[row][column] - expected[row][column]) for row in range(3) for column in range(3)))
        angle = actual.to_quaternion().rotation_difference(expected.to_quaternion()).angle
        worst_angle = max(worst_angle, min(angle, abs(2 * math.pi - angle)))
        # Root-to-pelvis translation is the captured root height, not a limb.
        if target.data.bones[bone].parent and bone not in ('bip01', 'bip01_pelvis'):
            parent = target.data.bones[bone].parent.name
            length = (pose[bone][:3, 3] - pose[parent][:3, 3])
            assert abs(float(sum(length * length)) ** .5 - (rest[bone].translation - rest[parent].translation).length) < .001, (sample['clip'], bone)
assert worst < .001, worst
assert worst_angle < .002, worst_angle
assert worst_rotation_coefficient < .002, worst_rotation_coefficient
(a.out / 'review.json').write_text(json.dumps(dict(source=provenance['source'], raw_files_private=True, installed=False,
    root_mode=a.root_mode, lock_facing=a.lock_facing, weapon_grip=a.weapon_grip, steering_fit=steering_fit, clips=metadata, roundtrip_max_error_metres=worst, roundtrip_max_angle_radians=worst_angle,
    roundtrip_max_rotation_coefficient=worst_rotation_coefficient,
    grounding=None if not a.grounding_audit else dict(sha256=hashlib.sha256(a.grounding_audit.read_bytes()).hexdigest(),method='circular max envelope followed by binomial smoothing; whole rig translation'),
    aim_layer=None if not a.prone_aim_layer else dict(sha256=hashlib.sha256(a.prone_aim_layer.read_bytes()).hexdigest(),motion=a.prone_aim_motion),
    candidate_sha256=hashlib.sha256((a.out / 'candidate.omf').read_bytes()).hexdigest()), indent=2) + '\n')
print('PRIVATE_MIXAMO_REVIEW_READY', a.out, 'roundtrip error', worst)
