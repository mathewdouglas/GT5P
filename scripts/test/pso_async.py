"""Compile the production PSO queue with a real WARP device and delayed driver calls."""
from pathlib import Path
import subprocess
import os
root=Path(__file__).resolve().parents[2]
runtime = Path(os.environ.get('PS3RECOMP_DIR', root.parent / 'ps3recomp-gt5p-v018'))
work=root/'scratch/pso-async-test';work.mkdir(exist_ok=True)
s=(runtime/'libs/video/rsx_d3d12_backend.c').read_text(encoding='utf-8')
block=s[s.index('/* PSO_ASYNC_BEGIN'):s.index('/* PSO_ASYNC_END */')]
(work/'queue.inc').write_text(block,encoding='utf-8')
cmd=work/'build.cmd'
cmd.write_text(f'''@echo off
call "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul
"C:\\Program Files\\LLVM\\bin\\clang-cl.exe" /nologo /TC /O2 /MD /D_CRT_SECURE_NO_WARNINGS /I"{work}" /Fo"{work}/test.obj" /Fe"{work}/test.exe" "{root}/scripts/test/pso_async.c" /link d3d12.lib dxgi.lib d3dcompiler.lib uuid.lib
if errorlevel 1 exit /b 1
"{work}/test.exe" "{work}"
''',encoding='ascii')
subprocess.run(['cmd','/c',str(cmd)],cwd=root,check=True)
