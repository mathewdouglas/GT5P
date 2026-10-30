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
for case in ('truncated-recipe', 'damaged-code', 'wrong-pipeline-key'):
    work = Path(tempfile.mkdtemp(prefix='reconstruct-negative-', dir=ROOT / 'scratch'))
    proof = work / 'pipeline'; proof.mkdir()
    for path in source.iterdir():
        if path.name == 'request.recipe' or path.suffix == '.dxbc':
            shutil.copy2(path, proof / path.name)
    if case == 'truncated-recipe':
        (proof / 'request.recipe').write_bytes(b'bad')
    elif case == 'damaged-code':
        path = next(proof.glob('code_*.dxbc'))
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
    else:
        path = proof / 'request.recipe'; data = bytearray(path.read_bytes())
        data[16] ^= 1  # Keep envelope checksum valid so key checking is exercised.
        struct.pack_into('<Q', data, len(data) - 8, fnv64(data[:-8])); path.write_bytes(data)
    env = offline_env(args.game_root.resolve(), work / 'cache')
    env['RSX_PSO_RECONSTRUCT'] = str(proof)
    run_offline(args.engine.resolve(), args.game_root.resolve(), env, work / 'run.log')
    result = json.loads((proof / 'result.json').read_text())
    assert result['created'] is False, (case, result)
    if case == 'wrong-pipeline-key':
        assert result['expected'] != result['actual'] and result['actual'] != '0000000000000000'
    print('Rejected', case, '(guest entry never executed)')
