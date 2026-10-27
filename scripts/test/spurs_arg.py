"""Extract the local lifted profiling routine into ignored test output; no game code is tracked."""
from pathlib import Path
import os
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
runtime = Path(os.environ.get('PS3RECOMP_DIR', root.parent / 'ps3recomp-gt5p-v018'))
(root/'scratch').mkdir(exist_ok=True)
folder = Path(tempfile.mkdtemp(prefix='spurs-arg-',dir=root/'scratch'))
source = (root/'generated/spu_lifted/wwsjob/spu_recomp.c').read_text(encoding='utf-8')
pieces = ['void gt5p_wwsjob_spu_func_000028B0(spu_context*);']
for address in ('00002720','00002850','000028B0'):
    a = source.index('void gt5p_wwsjob_spu_func_'+address+'(')
    b = source.index('\nvoid ',a+1)
    pieces.append(source[a:b])
(folder/'profile_attach.inc').write_text('\n'.join(pieces),encoding='utf-8')
source = (runtime/'runtime/spu/spurs_policy.c').read_text(encoding='utf-8')
a = source.index('static void spurs_pm_set_arg(')
b = source.index('\n}',a)+2
(folder/'policy_arg.inc').write_text(source[a:b],encoding='utf-8')
batch = folder/'build.cmd'
batch.write_text('@echo off\ncall "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul\n'
 + '"C:\\Program Files\\LLVM\\bin\\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /DSPU_LS_NO_PROBES '
 + f'/I"{runtime}/runtime/spu" /I"{folder}" /Fo"{folder}/" /Fe"{folder}/test.exe" "{root}/scripts/test/spurs_arg.c"\n',encoding='ascii')
subprocess.run(['cmd','/c',str(batch)],check=True,cwd=root)
for mode in ('0','1','default'):
    env=os.environ.copy(); env.pop('SPURS_PM_ARG64',None)
    if mode!='default': env['SPURS_PM_ARG64']=mode
    subprocess.run([str(folder/'test.exe'),'0' if mode=='0' else '1'],env=env,check=True,timeout=10)
