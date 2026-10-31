"""Validate an extracted player ZIP, standalone cancellation/resume and real PSOs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

sys.path.insert(0,str(Path(__file__).parents[1]))
from train_pipeline_cache import isolated,idle

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('zip','elf','assets','disc','output'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();idle();out=isolated(a.output)
    out.mkdir(parents=True)
    install=out/'Install with spaces';storage=out/'Fresh storage'
    with zipfile.ZipFile(a.zip) as archive:
        for n in archive.namelist():
            p=Path(n)
            assert not p.is_absolute() and '..' not in p.parts
            assert not n.lower().endswith(('.elf','.self','.fp','.dxbc','.recipe','.pso'))
        archive.extractall(install)
    (storage/'input').mkdir(parents=True)
    shutil.copyfile(a.elf,storage/'input/EMAIN.ELF')
    helper=install/'preparation/GT5P-Prepare.exe'
    command=[str(helper.resolve()),'--install',str(install.resolve()),'--storage',str(storage.resolve()),
             '--assets',str(a.assets.resolve())]
    env=dict(os.environ,PS3_VERBOSE='0',PATH=str(Path(os.environ['SystemRoot'])/'System32'))
    with (out/'cancel.log').open('wb') as log:
        child=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            begin=time.monotonic()
            while child.poll() is None:
                status=storage/'prepare-status.txt'
                if status.exists() and status.read_text().startswith('Vertex '):break
                if time.monotonic()-begin>90:raise AssertionError('Preparation did not reach vertex phase')
                time.sleep(.05)
            assert child.poll() is None,(out/'cancel.log').read_text(errors='replace')
            (storage/'prepare.cancel').write_text('cancel')
            assert child.wait(timeout=30)==2
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=15)
    state=next((storage/'preparation').glob('*/preparation-state.json'))
    assert json.loads(state.read_text())['phase']=='interrupted'
    assert not (storage/'prepared-cache.txt').exists()
    (storage/'prepare.cancel').unlink() # marker only; caches stay intact
    begin=time.monotonic()
    (storage/'setup.ini').write_text('[game]\ndirectory='+str(a.disc.resolve())+'\n',encoding='utf-16')
    env.update(GT5P_USER_DIR=str(storage.resolve()),GT5P_STORAGE_PICKER='0')
    with (out/'resume.log').open('wb') as log:
        subprocess.run([str((install/'tourline-prologue.exe').resolve()),'--prepare-assets',str(a.assets.resolve())],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200,check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    final=json.loads(state.read_text());assert final['phase']=='complete' and final['attempt']==2
    report=json.loads((state.parent/'report.json').read_text())
    assert report['counts']=={'prepared':report['requested']} and report['requested']>0
    assert (storage/Path((storage/'prepared-cache.txt').read_text())).resolve()==(state.parent/'shadercache').resolve()
    assert report['resume']['vertex_programs_reused']>0
    assert hashlib.sha256((storage/'input/EMAIN.ELF').read_bytes()).digest()==hashlib.sha256(a.elf.read_bytes()).digest()
    idle()
    (out/'validation.json').write_text(json.dumps(dict(cancelled=True,resumed=True,counts=report['counts'],
        seconds=time.monotonic()-begin,resume=report['resume'],package_sha256=hashlib.sha256(a.zip.read_bytes()).hexdigest()),indent=2)+'\n')
    print('Standalone fresh-storage preparation, cancellation/resume and persisted PSOs passed')

if __name__=='__main__':main()
