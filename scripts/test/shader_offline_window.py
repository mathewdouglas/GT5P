"""Verify hidden offline windows and exact-profile/base-profile source parity."""
import argparse
import ctypes
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).parents[1]))
from shader_reconstruct import offline_env
from train_pipeline_cache import isolated, idle

ap=argparse.ArgumentParser(description=__doc__)
for name in ('engine','game-root','profile','output'):
    ap.add_argument('--'+name,type=Path,required=True)
args=ap.parse_args()
idle()
root=isolated(args.output)
if root.exists():ap.error('Use a new ignored output')
root.mkdir(parents=True)
api=ctypes.WinDLL('user32',use_last_error=True)
callback_type=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
api.EnumWindows.argtypes=[callback_type,ctypes.c_void_p]
api.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
api.IsWindowVisible.argtypes=[ctypes.c_void_p]
results=[]
for exact in (False,True):
    work=root/str(int(exact));work.mkdir()
    cache=work/'shadercache';cache.mkdir()
    shutil.copytree(args.profile/'shadercache/fp-profiles-v2',cache/'fp-profiles-v2')
    env=offline_env(args.game_root.resolve(),cache)
    env.update(RSX_SHADER_LIBRARY=str((args.profile/'library').resolve()),
               RSX_SHADER_LIBRARY_PROFILE_LIMIT='1',RSX_SHADER_LIBRARY_RESULT=str(work/'compiled.tsv'),
               RSX_SHADER_LIBRARY_EXACT=str(int(exact)))
    seen=set();visible=set()
    with (work/'native.log').open('wb') as stream:
        proc=subprocess.Popen([str(args.engine.resolve())],cwd=args.game_root.resolve(),env=env,stdout=stream,stderr=subprocess.STDOUT)
        @callback_type
        def inspect(hwnd,user):
            pid=ctypes.c_ulong()
            api.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==proc.pid:
                seen.add(int(hwnd))
                if api.IsWindowVisible(hwnd):visible.add(int(hwnd))
            return True
        try:
            deadline=time.monotonic()+120
            while proc.poll() is None and time.monotonic()<deadline:
                api.EnumWindows(inspect,None)
                time.sleep(.01)
            if proc.poll() is None:raise ValueError('Offline compiler timed out')
            assert proc.returncode==0
        finally:
            if proc.poll() is None:
                proc.terminate();proc.wait(timeout=15)
    text=(work/'native.log').read_text(errors='replace')
    assert seen and not visible,(seen,visible)
    assert 'guest entry was not executed' in text and '[GT5P] Executing' not in text
    rows=[r.split() for r in (work/'compiled.tsv').read_text().splitlines()]
    selected=[r for r in rows if len(r)==5 and r[2]=='2' and r[4]=='1']
    assert selected
    if exact:assert all(r[2]=='2' for r in rows)
    results.append(dict(exact=exact,hidden_windows=len(seen),visible_windows=len(visible),rows=rows,selected=selected))
assert results[0]['selected']==results[1]['selected']
(root/'report.json').write_text(json.dumps(results,indent=2))
print('Offline windows stayed hidden; exact profiles preserve source keys and omit base compiles')
