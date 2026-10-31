"""Build the standalone preparer/production VP decoder; no game inputs required."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtime',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--clang-cl',default='C:/Program Files/LLVM/bin/clang-cl.exe')
    ap.add_argument('--decoder',type=Path,help='Reuse an already verified production decoder when only freezing tool changes')
    a=ap.parse_args();out=a.output.resolve()
    if out.exists():raise ValueError('Use a fresh preparation build output')
    if importlib.metadata.version('pyinstaller')!='6.16.0':raise ValueError('Build requires PyInstaller 6.16.0')
    out.mkdir(parents=True)
    manifest=json.loads((ROOT/'config/ps3recomp.json').read_text())
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--console',
        '--name','GT5P-Prepare','--distpath',str(out/'dist'),'--workpath',str(out/'work'),
        '--specpath',str(out),'--paths',str(ROOT/'scripts'),
        '--add-data',str(ROOT/'config/ps3recomp.json')+os.pathsep+'config',
        '--add-data',str(ROOT/manifest['patch'])+os.pathsep+'patches',
        str(ROOT/'scripts/player_prepare.py')],cwd=ROOT,check=True)
    folder=out/'dist/GT5P-Prepare'
    runtime=a.runtime.resolve()
    command=[a.clang_cl,'/nologo','/O2','/MT','/LD','/D_CRT_SECURE_NO_WARNINGS',
        '/I'+str(runtime/'include'),'/I'+str(runtime/'libs/video'),
        '/Fo'+str(out/'decoder.obj'),'/Fe'+str(folder/'decoder.dll'),
        str(runtime/'libs/video/rsx_vp_decompiler.c'),'/link',
        '/EXPORT:rsx_vp_decompile','/EXPORT:rsx_vp_decompile_gpufetch']
    if a.decoder:
        from package_player import windows_binary
        shutil.copyfile(windows_binary(a.decoder),folder/'decoder.dll')
    else:subprocess.run(command,check=True)
    # Import library/EXP are build outputs, not player inputs. Leave them in the
    # build directory; list only required distribution files below.
    licenses=folder/'licenses';licenses.mkdir()
    shutil.copyfile(Path(sys.base_prefix)/'LICENSE.txt',licenses/'Python-LICENSE.txt')
    dist=importlib.metadata.distribution('pyinstaller')
    source=next(dist.locate_file(x) for x in dist.files if str(x).endswith('/licenses/COPYING.txt'))
    shutil.copyfile(source,licenses/'PyInstaller-COPYING.txt')
    files={p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in folder.rglob('*') if p.is_file() and p.suffix.lower() not in ('.lib','.exp')}
    (folder/'files.json').write_text(json.dumps(dict(schema=1,files=files),indent=2)+'\n')
    print('Preparer distribution:',folder)

if __name__=='__main__':main()
