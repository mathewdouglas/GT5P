"""Compare native SPU fused helpers against scalar fmaf, including tiny inputs."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
runtime=root.parent/'ps3recomp-gt5p-master'
(root/'scratch').mkdir(exist_ok=True)
folder=Path(tempfile.mkdtemp(prefix='audio-math-',dir=root/'scratch'))
clang='"C:\\Program Files\\LLVM\\bin\\clang-cl.exe"'
flags=f'/nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /DSPU_LS_NO_PROBES /I"{runtime}/runtime/spu"'
lines=['@echo off','call "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul']
for name,extra in [('reference','-msse4.1 /DSPU_FMA_LIBM'),('fast','-msse4.1 -mfma')]:
 lines += [f'{clang} {flags} {extra} /DNAME=audio_{name} /c /Fo"{folder}/{name}.obj" "{root}/scripts/test/audio_math.c"','if errorlevel 1 exit /b 1']
lines += [f'{clang} {flags} /Fo"{folder}/" /Fe"{folder}/test.exe" "{root}/scripts/test/audio_math_check.c" "{folder}/reference.obj" "{folder}/fast.obj"']
batch=folder/'build.cmd';batch.write_text('\n'.join(lines)+'\n',encoding='ascii')
subprocess.run(['cmd','/c',str(batch)],check=True,cwd=root)
subprocess.run([str(folder/'test.exe')],check=True,timeout=60)
