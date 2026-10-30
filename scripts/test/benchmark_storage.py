"""Storage preflight, owned-copy cleanup, junction and cache protection checks."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]))
from benchmark_storage import ROOT, discard_game_copy, require_space

(ROOT/'scratch').mkdir(exist_ok=True)
root=Path(tempfile.mkdtemp(prefix='benchmark-storage-',dir=ROOT/'scratch'))
trial=root/'1-control';game=trial/'game'
(game/'input').mkdir(parents=True)
(trial/'logs').mkdir();(trial/'runner.log').write_text('retained')
(trial/'shadercache').mkdir();(trial/'shadercache/keep.txt').write_text('retained')
file=game/'copied.txt';file.write_text('disposable');file.chmod(stat.S_IREAD)
target=root/'fixture';target.mkdir();(target/'keep.txt').write_text('source retained')
if os.name=='nt':
    env=dict(os.environ,GT5P_STORAGE_LINK=str(game/'input/pkg'),GT5P_STORAGE_TARGET=str(target))
    subprocess.run(['powershell','-NoProfile','-Command',
                    'New-Item -ItemType Junction -Path $env:GT5P_STORAGE_LINK -Target $env:GT5P_STORAGE_TARGET | Out-Null'],env=env,check=True)
else:
    (game/'input/pkg').symlink_to(target,target_is_directory=True)
removed=discard_game_copy(game)
assert not game.exists() and removed==len('disposable')
assert (target/'keep.txt').read_text()=='source retained'
assert (trial/'shadercache/keep.txt').is_file() and (trial/'runner.log').is_file()

protected=root/'2-prepared';protected_game=protected/'game'
(protected_game/'shadercache').mkdir(parents=True)
(protected/'logs').mkdir();(protected/'runner.log').write_text('retained')
(protected_game/'keep.txt').write_text('retained')
try:
    discard_game_copy(protected_game)
except ValueError:
    pass
else:
    raise AssertionError('Nested shadercache was not protected')
assert (protected_game/'keep.txt').exists()
try:
    discard_game_copy(ROOT/'src/game')
except ValueError:
    pass
else:
    raise AssertionError('Non-scratch deletion allowed')

fixture=root/'space-fixture'
for folder in ('assets','gamedata','input'):(fixture/folder).mkdir(parents=True,exist_ok=True)
(fixture/'input/EMAIN.ELF').write_bytes(b'synthetic')
with patch('benchmark_storage.shutil.disk_usage',return_value=SimpleNamespace(free=1)):
    try:
        require_space(root,fixture)
    except ValueError:
        pass
    else:
        raise AssertionError('Low-space copy was not blocked')
(root/'report.json').write_text(json.dumps(dict(owned_cleanup=True,junction_target_preserved=True,
    shadercache_preserved=True,non_scratch_rejected=True,low_space_rejected=True),indent=2))
print('Owned-copy cleanup, junction target, shadercache protection and low-space preflight passed:',root)
