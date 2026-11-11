"""Build a bounded whole-rig lift from every exported motion key; no installation."""
import argparse
import hashlib
import json
import math
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--candidate', type=Path, required=True)
p.add_argument('--actor', type=Path, required=True)
p.add_argument('--aim-layer', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
metadata = json.loads((a.candidate/'review.json').read_text(encoding='utf-8'))
assert metadata['aim_layer']['sha256'] == digest(a.aim_layer)
clips = {}
for clip in metadata['clips']:
    name, count = clip['clip'], clip['frames']
    report_path = a.candidate/('floor-all-'+name)/'weapon-directions.json'
    rows = json.loads(report_path.read_text(encoding='utf-8'))
    assert len(rows) == count, (name, 'Incomplete key audit')
    raw = []
    for index, row in enumerate(rows):
        assert abs(row['phase']-index/count) < 1e-9
        values = [row['body_min_z'], row['weapon_min_z']]
        assert all(math.isfinite(value) for value in values)
        raw.append(max(0., .006-min(values)))
    # Dilating before the binomial filter preserves clearance at every key.
    envelope = [max(raw[(i+j) % count] for j in range(-2, 3)) for i in range(count)]
    lift = [sum(weight*envelope[(i+j) % count] for j, weight in
                zip(range(-2, 3), (1, 4, 6, 4, 1)))/16 for i in range(count)]
    assert all(required-1e-9 <= value < .3 for required, value in zip(raw, lift))
    clips[name] = dict(frames=count, source_sha256=clip['sha256'],
                       report_sha256=digest(report_path), lift_metres=lift,
                       max_lift_metres=max(lift))
result = dict(installed=False, retarget_tool_sha256=metadata['retarget_tool_sha256'], actor_sha256=digest(a.actor),
              aim_layer_sha256=digest(a.aim_layer),
              candidate_sha256=digest(a.candidate/'candidate.omf'),
              recipe={key: metadata.get(key, False) for key in
                      ('root_mode', 'lock_facing', 'weapon_grip', 'aim_follow_chest', 'launcher_stable_torso', 'launcher_level_torso', 'launcher_grip_shift', 'launcher_forearm_roll')},
              aim_motion=metadata['aim_layer']['motion'], clips=clips)
a.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print('Grounding audit:', len(clips), 'clips,', sum(c['frames'] for c in clips.values()), 'keys')
