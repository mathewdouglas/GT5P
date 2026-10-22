"""Check CPU/OS fallback, image identity, preflight and actual registry replacement."""
import os
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
runtime=root.parent/'ps3recomp-gt5p-master'
(root/'scratch').mkdir(exist_ok=True)
folder=Path(tempfile.mkdtemp(prefix='audio-native-',dir=root/'scratch'))
s=(runtime/'runtime/spu/spu_channels.c').read_text(encoding='utf-8')
a=s.index('typedef void (*spu_fn)');b=s.index('/* Report a CROSS-IMAGE match:',a)
(folder/'registry.inc').write_text(s[a:b],encoding='utf-8')
batch=folder/'build.cmd'
batch.write_text('@echo off\ncall "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul\n'
 + '"C:\\Program Files\\LLVM\\bin\\clang-cl.exe" /nologo /O2 /MD /EHsc /D_CRT_SECURE_NO_WARNINGS /DGT5P_HAVE_AUDIO_NATIVE=1 '
 + f'/I"{runtime}/runtime/spu" /Fo"{folder}/" /Fe"{folder}/dispatch.exe" "{root}/scripts/test/audio_native.cpp"\n'
 + 'if errorlevel 1 exit /b 1\n'
 + '"C:\\Program Files\\LLVM\\bin\\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS '
 + f'/I"{folder}" /Fo"{folder}/" /Fe"{folder}/registry.exe" "{root}/scripts/test/audio_registry.c"\n',encoding='ascii')
subprocess.run(['cmd','/c',str(batch)],check=True,cwd=root)
subprocess.run([str(folder/'registry.exe')],check=True,timeout=10)
for case in ('off','default','cpu','os','missing','identity','on'):
 env=os.environ.copy();env.pop('GT5P_AUDIO_NATIVE',None)
 if case!='default':env['GT5P_AUDIO_NATIVE']='0' if case=='off' else '1'
 subprocess.run([str(folder/'dispatch.exe'),case],env=env,check=True,timeout=10)
