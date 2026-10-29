"""Synthetic coverage audit checks; no game data, GPU or shader compiler needed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location('coverage', Path(__file__).parents[1] / 'shader_coverage.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def instruction(words):
    return struct.pack('>4I', *[((w << 16) | (w >> 16)) & 0xffffffff for w in words])


def rejects(data):
    try:
        m.fp_identity(data)
    except ValueError:
        return
    raise AssertionError('Malformed shader accepted')


base = instruction([1 | (0x17 << 24) | (7 << 17), 2, 0, 0]) + bytes(16)
changed = base[:16] + bytes(range(16))
assert m.fp_identity(base) == m.fp_identity(changed + bytes(32))
assert m.fp_identity(base)['textures'] == 1 << 7
assert m.fp_identity(base)['constants'] == 1
assert m.fp_identity(instruction([3, 0, 0, 0]))['identity'] != m.fp_identity(base)['identity']
for data in (b'', bytes(16), base[:16], base[:17], bytes(32784)):
    rejects(data)

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    catalog = root / 'catalog'; catalog.mkdir()
    live = root / 'live'; live.mkdir()
    recipes = root / 'warmup-v1'; recipes.mkdir()
    digest = hashlib.sha256(base).hexdigest()
    (catalog / (digest + '.fp')).write_bytes(base)
    (catalog / 'bad.fp').write_bytes(base)
    (catalog / 'index.json').write_text(json.dumps({'sources': [dict(sha256=digest, file='synthetic/model')]}))
    (live / 'fp_exact.bin').write_bytes(base)
    (live / 'fp_constants.bin').write_bytes(changed + bytes(16))
    (live / 'fp_unknown.bin').write_bytes(instruction([3, 0, 0, 0]))
    (live / 'fp_bad.bin').write_bytes(b'bad')
    programs, sources, errors = m.asset_catalog(catalog)
    assert len(programs) == 1 and len(errors) == 1
    profiles = root / 'profiles'; profiles.mkdir()
    (profiles / 'valid.txt').write_text('0 0 0 0 0 0 0 0 80\n')
    (profiles / 'bad.txt').write_text('0 0 0 0 0 0 0 0 10000\n')
    profile_result = m.audit_profiles(profiles, programs)
    assert profile_result['counts'] == {'invalid': 1, 'valid': 1}
    assert profile_result['records'][1]['candidate_instruction_programs'] == 1
    result = m.audit_live(live, programs, sources)
    assert result['counts'] == dict(invalid=1, instructions=1, exact=1, unmatched=1)
    assert result['unique_instruction_programs'] == 2
    # A minimal synthetic envelope is enough for dependency checks. The audit
    # deliberately does not call such envelopes runtime-valid D3D12 descriptors.
    code = b'DXBCsynthetic'
    code_hash = m.fnv64(code)
    (recipes / f'code_{code_hash:016x}.dxbc').write_bytes(code)
    payload = struct.pack('<QIIQQQII', m.MAGIC, 1, 56, 123, code_hash, code_hash, len(code), len(code))
    recipe = recipes / 'pso_000000000000007b.recipe'
    recipe.write_bytes(payload + struct.pack('<Q', m.fnv64(payload)))
    (recipes / 'race-v1.txt').write_text('000000000000007b\n7b\n000000000000007c\ninvalid\n')
    result = m.audit_recipes(recipes, verify_hashes=True)
    assert result['counts'] == {'dependencies_present': 1}
    assert result['memberships']['race-v1.txt'] == dict(present=True, unique_entries=2,
                                                       invalid_lines=1, missing_recipes=1,
                                                       dependencies_present=1)
    (recipes / f'code_{code_hash:016x}.dxbc').write_bytes(b'DXBCtampered!')
    assert m.audit_recipes(recipes, True)['counts'] == {'dependency_error': 1}
    recipe.write_bytes(payload + bytes(8))
    assert m.audit_recipes(recipes, True)['counts'] == {'invalid': 1}
    recipe.write_bytes(payload + struct.pack('<Q', m.fnv64(payload)))
    (recipes / f'code_{code_hash:016x}.dxbc').unlink()
    assert m.audit_recipes(recipes)['counts'] == {'dependency_error': 1}
    # Exercise the complete CLI, including the ignored-output rule and refusal
    # to overwrite a previous report; the input cache must remain unchanged.
    scratch = m.ROOT / 'scratch'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='coverage-cli-', dir=scratch) as work:
        output = Path(work) / 'report'
        command = [sys.executable, str(m.ROOT / 'scripts/shader_coverage.py'),
                   '--catalog', str(catalog), '--live', str(live), '--cache', str(root),
                   '--output', str(output)]
        before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        subprocess.run(command, check=True, capture_output=True, text=True)
        report = json.loads((output / 'report.json').read_text())
        assert report['full_pipeline_reconstruction'] == 'unknown_missing_provenance'
        assert report['live'][0]['counts'] == dict(invalid=1, instructions=1, exact=1, unmatched=1)
        assert subprocess.run(command, capture_output=True).returncode != 0
        # The parent of the repository is outside this worktree's ignored tree.
        refused = m.ROOT.parent / (Path(work).name + '-refused')
        command[-1] = str(refused)
        assert subprocess.run(command, capture_output=True).returncode != 0
        assert not refused.exists()
        assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}

print('Shader matching, malformed programs, recipe dependencies/checksums and memberships passed')
