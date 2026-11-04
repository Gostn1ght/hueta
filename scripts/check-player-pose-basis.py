"""Compare real OMF keys with independent Blender authoring matrices, including roll."""
from pathlib import Path
import hashlib
import importlib.util
import json
import numpy as np

root = Path(__file__).resolve().parents[1]
qa = json.loads((root / 'docs/audit/185_BONE_BASIS_REFERENCE.json').read_text())
omf = root / qa['omf_path']
assert hashlib.sha256(omf.read_bytes()).hexdigest() == qa['omf_sha256']
spec = importlib.util.spec_from_file_location('poses', root / 'scripts/read-omf-poses.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
skeleton = json.loads((root / 'assets/animations/mesh2motion/game-skeleton-47.json').read_text())
motions = reader.Motions(omf, parents=skeleton['parents'])
# The importer swaps world Y/Z. Bone LOCAL axes instead reflect Z: the
# exporter's root MATRIX_BONE_INVERTED accounts for the extra quarter turn.
# Object/seat transforms use C*M*C; skeletal bone transforms use C*M*S.
c = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float)
s = np.diag([1., 1., -1., 1.])
worst_position = worst_rotation = wrong_rotation = 0.
checked = 0
for sample in qa['samples']:
    keys = motions.pose(sample['clip'], sample['frame'] / sample['frames'], matrices=True)
    assert set(sample['world']) == set(keys) and len(keys) == 47
    for name, expected in sample['world'].items():
        expected = np.asarray(expected)
        actual = c @ keys[name] @ s
        assert np.isfinite(actual).all()
        worst_position = max(worst_position, float(np.linalg.norm(actual[:3, 3] - expected[:3, 3])))
        worst_rotation = max(worst_rotation, float(np.max(np.abs(actual[:3, :3] - expected[:3, :3]))))
        wrong_rotation = max(wrong_rotation, float(np.max(np.abs((c @ keys[name] @ c)[:3, :3] - expected[:3, :3]))))
        checked += 1
assert checked == 423
assert worst_position < .001 and worst_rotation < .001, (worst_position, worst_rotation)
assert wrong_rotation > 1., 'The old conjugation must be rejected even though it preserves joint positions'
print(f'PASS independent author/export basis: {checked} bone matrices; position {worst_position:.6f} m, rotation coefficient {worst_rotation:.6f}; old 90-degree error rejected')
