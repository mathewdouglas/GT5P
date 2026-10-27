"""Exercise real D3D12 startup preload using copies of local cache records.

Requires one run of the current build to learn recipes. Never changes the
source shadercache. Derived bytecode and test logs stay in ignored scratch/.
"""
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import uuid

root = Path(__file__).resolve().parents[2]
source = root / 'shadercache'
work = root / 'scratch' / ('shader-warmup-' + uuid.uuid4().hex)
# Old cache entries may describe an earlier sampler/root-signature generation.
# Use recipes learned by the current build's preceding smoke run; damaged-input
# cases below still exercise rejection explicitly without touching the source cache.
recipes = sorted((source / 'warmup-v1').glob('*.recipe'),
                 key=lambda p: p.stat().st_mtime_ns, reverse=True)[:3]
assert len(recipes) == 3, 'Run this build once to learn at least three pipeline recipes'
assert b'gt5p.exe' not in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq gt5p.exe', '/NH'],
                                       capture_output=True).stdout.lower(), 'Close the game first'

for case in ('valid', 'damaged', 'background-valid', 'background-damaged'):
    background = case.startswith('background-')
    damaged = case.endswith('damaged')
    cache = work / case
    records = cache / 'warmup-v1'; records.mkdir(parents=True)
    for recipe in recipes:
        shutil.copy2(recipe, records / recipe.name)
        _, _, _, pipeline, vs, ps, _, _ = struct.unpack('<QIIQQQII', recipe.read_bytes()[:48])
        for code in (vs, ps):
            name = f'code_{code:016x}.dxbc'
            shutil.copy2(source / 'warmup-v1' / name, records / name)
        name = f'pso_{pipeline:016x}.bin'
        if (source / name).exists(): shutil.copy2(source / name, cache / name)
    if background:
        pipeline = struct.unpack('<QIIQQQII', recipes[0].read_bytes()[:48])[3]
        (records / 'menu-v1.txt').write_text(f'{pipeline:016x}\n')
        # Background startup prepares the menu set, then the race set; the
        # first race entry reuses the menu pipeline. No directory scan.
        race = [struct.unpack('<QIIQQQII', r.read_bytes()[:48])[3] for r in recipes]
        (records / 'race-v1.txt').write_text(''.join(f'{h:016x}\n' for h in race))
    if damaged:
        (records / 'pso_invalid.recipe').write_bytes(b'invalid recipe')
        next(records.glob('code_*.dxbc')).write_bytes(b'truncated bytecode')
    env = os.environ.copy()
    for key in ('PS3_HEADLESS', 'GT5P_NO_PRESENT', 'RSX_LIVE_DRAW', 'RSX_PSO_RECIPES', 'RSX_PSO_DISK'):
        env.pop(key, None)
    env.update(GT5P_NO_SETTINGS='1', PS3_VERBOSE='0', FS_HIDE='grim/file/contents',
               RSX_SHADER_WARMUP='1', RSX_SHADER_WARMUP_BACKGROUND='1' if background else '0',
               RSX_PSO_ASYNC='1', RSX_SHADER_ASYNC='1', RSX_SHADER_CACHE=str(cache), RSX_PSO_TIMING='1')
    out_path, err_path = cache / 'out.log', cache / 'err.log'
    with out_path.open('wb') as out, err_path.open('wb') as err:
        proc = subprocess.Popen([str(root / 'build/gt5p.exe')], cwd=root, env=env, stdout=out, stderr=err)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                log = err_path.read_text(errors='replace')
                stdout = out_path.read_text(errors='replace')
                if ('[shader-warmup] background finished:' if background else '[shader-warmup] finished:') in log and '[GT5P] Executing' in stdout:
                    break
                assert proc.poll() is None, 'Game exited during startup'
                time.sleep(.1)
            else: raise AssertionError('Startup preload or guest execution timed out')
            loaded, rejected = map(int, re.search(r'finished: loaded=(\d+) rejected=(\d+)', log).groups())
            if not damaged: assert (loaded, rejected) == (4 if background else 3, 0), log[:4000]
            elif background:   # without a directory scan only the truncated bytecode is reached
                assert loaded < 4 and rejected >= 1, log[:4000]
                assert (records / 'pso_invalid.recipe').exists(), 'background startup scanned the directory'
            else: assert loaded < 3 and rejected >= 2, log[:4000]
            if background:
                assert 'queued background preparation' in log and 'menu priority learned' in log
                assert 'recipes: 3 kept, 0 pruned' in log and 'race_ready=' in log, log[:4000]
            print(f'{case}: loaded={loaded}, rejected={rejected}; guest started')
        finally:
            if proc.poll() is None: proc.terminate()
            proc.wait(timeout=10)
print(f'Passed; evidence: {work}')
