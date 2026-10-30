"""Exercise capture-free preparation gates and bounded batch manifests locally."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_reconstruct import ROOT, offline_env, run_offline, fnv64

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--engine', required=True, type=Path)
ap.add_argument('--game-root', required=True, type=Path)
ap.add_argument('--sample', required=True, type=Path, help='Capture-free job pipeline directory')
args = ap.parse_args()
root = Path(tempfile.mkdtemp(prefix='material-prepare-native-', dir=ROOT / 'scratch'))
cases = ['positive', 'prepare-off', 'native-off', 'pass-off', 'material-off',
         'nonzero-expected', 'damaged-code', 'traversal', 'long-id', 'too-many', 'oversized', 'trailing-invalid']
for case in cases:
    work = root / case; work.mkdir()
    job = work / ('a' * 64) / 'pipeline'; job.mkdir(parents=True)
    for path in args.sample.iterdir():
        if path.name in ('request.recipe', 'material.state', 'pass.state', 'target.state') or path.suffix == '.dxbc':
            shutil.copy2(path, job / path.name)
    env = offline_env(args.game_root.resolve(), work / 'cache')
    env.update(RSX_PSO_PREPARE_BATCH=str(work), RSX_PSO_PREPARE_MATERIAL='1',
               RSX_PSO_RECONSTRUCT_NATIVE='1', RSX_PSO_RECONSTRUCT_PASS='1', RSX_PSO_RECONSTRUCT_MATERIAL='1')
    manifest = 'a' * 64 + '\n'
    if case in ('prepare-off', 'native-off', 'pass-off', 'material-off'):
        switch = dict(zip(('prepare-off', 'native-off', 'pass-off', 'material-off'),
                          ('RSX_PSO_PREPARE_MATERIAL', 'RSX_PSO_RECONSTRUCT_NATIVE',
                           'RSX_PSO_RECONSTRUCT_PASS', 'RSX_PSO_RECONSTRUCT_MATERIAL')))[case]
        env[switch] = '0'
    if case == 'nonzero-expected':
        path = job / 'request.recipe'; data = bytearray(path.read_bytes())
        struct.pack_into('<Q', data, 16, int(positive_key, 16))
        struct.pack_into('<Q', data, len(data) - 8, fnv64(data[:-8])); path.write_bytes(data)
    if case == 'damaged-code':
        path = next(job.glob('code_*.dxbc')); data = bytearray(path.read_bytes())
        data[-1] ^= 1; path.write_bytes(data)
    if case == 'traversal':
        manifest = '../bad\n'
    if case == 'long-id':
        manifest = 'a' * 65 + '\n'
    if case == 'too-many':
        manifest *= 4097
    if case == 'oversized':
        manifest += ' ' * (4096 * 66)
    if case == 'trailing-invalid':
        manifest += 'invalid\n'
    (work / 'jobs.txt').write_text(manifest, encoding='ascii')
    run_offline(args.engine.resolve(), args.game_root.resolve(), env, work / 'run.log')
    result_path = job / 'result.json'
    if case == 'positive':
        result = json.loads(result_path.read_text())
        assert result['prepared']
        positive_key = result['actual']
        run_offline(args.engine.resolve(), args.game_root.resolve(), env, work / 'reuse.log')
        log = (work / 'reuse.log').read_text(errors='replace')
        assert 'requests=1 created=1 driver_calls=1 cached_blob_calls=1' in log, log[-3000:]
    else:
        assert not result_path.exists() or not json.loads(result_path.read_text())['created'], case
        if case in ('traversal', 'long-id', 'too-many', 'oversized', 'trailing-invalid'):
            assert not result_path.exists(), 'Malformed manifest partially executed'
        assert not list((work / 'cache').glob('pso_*.bin')), case
    print('Passed', case, flush=True)
(root / 'report.json').write_text(json.dumps(dict(cases=cases, passed=len(cases), cache_reuse=True), indent=2))
print(root)
