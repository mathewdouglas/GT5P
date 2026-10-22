"""Exercise offline compilation and reuse with this machine's game executable.

No game data is tracked. Uses an isolated scratch cache; never clears or moves
the player's shadercache. Close the running game before starting this check.
"""
from pathlib import Path
import re
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parents[2]
cache = root / 'scratch' / ('shader-library-test-' + uuid.uuid4().hex)
tool = root / 'scripts/precompile_shaders.py'


def run(*args):
    subprocess.run([sys.executable, str(tool), '--scope', 'executable', '--cache', str(cache), *args],
                   cwd=root, check=True, timeout=180)
    log = (cache / 'precompile.log').read_text(encoding='utf-8', errors='replace')
    assert '[GT5P] Executing' not in log
    assert 'guest entry was not executed' in log
    result = re.search(r'finished: programs=(\d+) attempts=(\d+) rejected=(\d+) compiled=(\d+)', log)
    assert result, log[-3000:]
    return tuple(map(int, result.groups()))


first = run('--base-profiles')
assert first[0] > 0 and first[2] == 0 and first[3] > 0, first
second = run('--compile-only', '--base-profiles')
assert second[:3] == first[:3] and second[3] == 0, second

catalog = cache / 'library-v1/executable'
(catalog / 'invalid.fp').write_bytes(b'invalid')
(catalog / 'oversized.fp').write_bytes(bytes(32784))
damaged = run('--compile-only', '--base-profiles')
assert damaged[0] == first[0] and damaged[2] == 2 and damaged[3] == 0, damaged

# A profile using all 16 units cannot match the executable-only sample mask.
# Match filtering must leave the base attempts unchanged; broad mode must try it.
profiles = cache / 'fp-profiles-v2'; profiles.mkdir()
(profiles / 'filter.txt').write_text('0 1000 0 0 0 0 0 0 ffff\n')
filtered = run('--compile-only')
assert filtered[1] == second[1], filtered
broad = run('--compile-only', '--all-profile-combinations')
assert broad[1] == first[0] * 3 and broad[3] > 0, broad
print('Native offline compile, zero-recompile repeat, invalid inputs and profile filtering passed:', cache)
