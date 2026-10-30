"""Negative checks for the offline native proof mode, using a local proof sample."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_reconstruct import ROOT, offline_env, run_offline, fnv64

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--engine', required=True, type=Path)
ap.add_argument('--game-root', required=True, type=Path)
ap.add_argument('--sample', required=True, type=Path, help='Verified sample containing pipeline/request.recipe and rebuilt code')
args = ap.parse_args()
if b'gt5p.exe' in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq gt5p.exe', '/NH'], capture_output=True).stdout.lower():
    raise SystemExit('Close the game before native proof checks')
source = args.sample / 'pipeline'
cases = ['truncated-recipe', 'damaged-code', 'wrong-pipeline-key']
if (source / 'material.state').is_file():
    cases += ['material-missing', 'material-malformed', 'material-wrong-state', 'material-off']
if (source / 'pass.state').is_file():
    cases += ['pass-missing', 'pass-malformed', 'pass-wrong-state', 'pass-off', 'pass-without-material']
for case in cases:
    work = Path(tempfile.mkdtemp(prefix='reconstruct-negative-', dir=ROOT / 'scratch'))
    proof = work / 'pipeline'; proof.mkdir()
    for path in source.iterdir():
        if path.name in ('request.recipe', 'material.state', 'pass.state') or path.suffix == '.dxbc':
            shutil.copy2(path, proof / path.name)
    if case == 'truncated-recipe':
        (proof / 'request.recipe').write_bytes(b'bad')
    elif case == 'damaged-code':
        path = next(proof.glob('code_*.dxbc'))
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
    elif case == 'wrong-pipeline-key':
        path = proof / 'request.recipe'; data = bytearray(path.read_bytes())
        data[16] ^= 1  # Keep envelope checksum valid so key checking is exercised.
        struct.pack_into('<Q', data, len(data) - 8, fnv64(data[:-8])); path.write_bytes(data)
    elif case == 'material-missing':
        (proof / 'material.state').unlink()  # Only the newly copied test fixture.
    elif case in ('material-malformed', 'material-off'):
        (proof / 'material.state').write_text('invalid')
    elif case == 'material-wrong-state':
        path = proof / 'material.state'; fields = path.read_text().split()
        fields[2] = f'{int(fields[2], 16) ^ 1:x}'
        path.write_text(' '.join(fields) + '\n')
    if case == 'pass-missing':
        (proof / 'pass.state').unlink()  # Only the newly copied fixture.
    elif case in ('pass-malformed', 'pass-off'):
        (proof / 'pass.state').write_text('invalid')
    elif case == 'pass-wrong-state':
        path = proof / 'pass.state'; fields = path.read_text().split()
        fields[1] = '1' if fields[1] == '5' else '5'
        path.write_text(' '.join(fields) + '\n')
    env = offline_env(args.game_root.resolve(), work / 'cache')
    env['RSX_PSO_RECONSTRUCT'] = str(proof)
    if case.startswith('material-'):
        env['RSX_PSO_RECONSTRUCT_MATERIAL'] = '0' if case == 'material-off' else '1'
    if case.startswith('pass-'):
        env['RSX_PSO_RECONSTRUCT_MATERIAL'] = '0' if case == 'pass-without-material' else '1'
        env['RSX_PSO_RECONSTRUCT_PASS'] = '0' if case == 'pass-off' else '1'
    run_offline(args.engine.resolve(), args.game_root.resolve(), env, work / 'run.log')
    result = json.loads((proof / 'result.json').read_text())
    if case == 'material-off':
        assert result['created'] and result['expected'] == result['actual']
        assert not result['material_requested'] and not result['material_applied']
        print('Explicit material mode 0 ignored malformed state and preserved legacy proof')
        continue
    if case == 'pass-off':
        assert result['created'] and result['expected'] == result['actual']
        assert not result['pass_requested'] and not result['pass_applied']
        print('Explicit pass mode 0 ignored malformed state and preserved legacy proof')
        continue
    if case in ('pass-missing', 'pass-malformed', 'pass-without-material'):
        assert result['pass_requested'] and not result['pass_applied']
    if case == 'pass-wrong-state':
        assert result['pass_applied'] and result['expected'] != result['actual']
    assert result['created'] is False, (case, result)
    if case == 'wrong-pipeline-key':
        assert result['expected'] != result['actual'] and result['actual'] != '0000000000000000'
    if case in ('material-missing', 'material-malformed'):
        assert result['material_requested'] and not result['material_applied']
    if case == 'material-wrong-state':
        assert result['material_applied'] and result['expected'] != result['actual']
    print('Rejected', case, '(guest entry never executed)')
