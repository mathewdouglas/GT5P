"""Build the actual condition syscall and reproduce the inline GCM wake race."""
import os
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
runtime = Path(os.environ.get('PS3RECOMP_DIR', root.parent / 'ps3recomp-gt5p-v018'))
(root / 'scratch').mkdir(exist_ok=True)
folder = Path(tempfile.mkdtemp(prefix='cond-callback-', dir=root/'scratch'))
batch = folder/'build.cmd'
batch.write_text('@echo off\ncall "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul\n'
 + '"C:\\Program Files\\LLVM\\bin\\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS '
 + f'/I"{runtime}/runtime/syscalls" /I"{runtime}/runtime/memory" /I"{runtime}/include" '
 + f'/Fo"{folder}/" /Fe"{folder}/test.exe" "{root}/scripts/test/cond_callback.c" "{runtime}/runtime/syscalls/sys_cond.c"\n',encoding='ascii')
subprocess.run(['cmd','/c',str(batch)],check=True,cwd=root)
for mode in ('0','1'):
 env=os.environ.copy();env['PS3_COND_DEFER_GCM']=mode
 for k in ('PS3_COND_PEEK','PS3_COND_SPURIOUS_MS','PS3_COND_TRACE_ID'):env.pop(k,None)
 subprocess.run([str(folder/'test.exe'),mode],env=env,check=True,timeout=10)
