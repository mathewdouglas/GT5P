"""Standalone optional player preparation. Original assets and all outputs stay local."""
import argparse
import csv
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pipeline_template as template
import shader_fragment_batch
from preparation_checkpoint import preflight_tree
from shader_coverage import ROOT
from pipeline_asset_map import read as read_map


def safe_storage(storage):
    storage=storage.absolute()
    for p in (storage,*storage.parents):
        if p.is_symlink() or p.is_junction():raise ValueError('Preparation storage must not be redirected')
    if not storage.is_dir():raise ValueError('Player storage is missing')
    return storage.resolve()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('install','storage','assets'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--launcher-pid',type=int,default=0)
    a=ap.parse_args()
    storage=safe_storage(a.storage)
    install=a.install.resolve()
    def idle_for_player():
        # Verify the optional visible launcher owner. Exclude only our actual
        # parent, after verifying its full image path; never ignore another game.
        allowed=0
        if a.launcher_pid:
            if a.launcher_pid!=os.getppid():raise ValueError('Preparation launcher owner mismatch')
            api=ctypes.WinDLL('kernel32',use_last_error=True)
            api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong];api.OpenProcess.restype=ctypes.c_void_p
            api.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
            api.CloseHandle.argtypes=[ctypes.c_void_p]
            handle=api.OpenProcess(0x1000,False,a.launcher_pid)
            path=ctypes.create_unicode_buffer(32768);size=ctypes.c_ulong(len(path))
            try:
                if not handle or not api.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)):
                    raise ValueError('Cannot verify preparation launcher owner')
                if Path(path.value).resolve()!=install/'tourline-prologue.exe':raise ValueError('Preparation launcher image mismatch')
            finally:
                if handle:api.CloseHandle(handle)
            allowed=a.launcher_pid
        result=subprocess.run(['tasklist','/FI','IMAGENAME eq gt5p.exe','/FO','CSV','/NH'],capture_output=True,text=True,check=True)
        for row in csv.reader(result.stdout.splitlines()):
            if len(row)>1 and row[0].lower()=='gt5p.exe' and int(row[1])!=allowed:
                raise ValueError('Another GT5P process is running; nothing was stopped')
    template.idle=idle_for_player
    engine=install/'runtime/gt5p.exe';decoder=install/'preparation/decoder.dll'
    bundle=install/'assets/pipeline-templates/gt5p-disc-v2'
    document=template.read(bundle)
    if document['compatibility']!=template.compatibility(engine,decoder,storage/'input/EMAIN.ELF'):
        raise ValueError('This template does not match the installed game/renderer')
    location_map=bundle/'player-map.json'
    metadata=json.dumps([document,read_map(location_map)],sort_keys=True,separators=(',',':'))
    token=hashlib.sha256((metadata+hashlib.sha256(engine.read_bytes()).hexdigest()+
                          hashlib.sha256(decoder.read_bytes()).hexdigest()).encode()).hexdigest()[:24]
    parent=storage/'preparation'
    if parent.exists():preflight_tree(parent)
    parent.mkdir(exist_ok=True)
    out=parent/token
    cancel=storage/'prepare.cancel';status=storage/'prepare-status.txt'
    def progress(phase,counts):
        if cancel.exists():raise KeyboardInterrupt('Preparation cancelled; completed files kept')
        text=phase.replace('-',' ').capitalize()
        if 'completed' in counts:text+=f" {counts['completed']}/{counts['total']}"
        status.write_text(text,encoding='utf-8')
    def run_owned(exe,game_root,env,log,timeout=180):
        idle_for_player()
        begin=time.monotonic()
        with log.open('wb') as stream:
            child=subprocess.Popen([str(exe)],cwd=game_root,env=env,stdout=stream,stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                while child.poll() is None:
                    if cancel.exists():raise KeyboardInterrupt('Preparation cancelled; completed files kept')
                    if time.monotonic()-begin>timeout:raise TimeoutError('Preparation process exceeded its time budget')
                    time.sleep(.1)
                if child.returncode:raise ValueError('Preparation process failed; see '+str(log))
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=15)
        text=log.read_text(encoding='utf-8',errors='replace')
        if 'guest entry was not executed' not in text or '[GT5P] Executing' in text:
            raise ValueError('Offline execution guard was not confirmed')
        return text
    # The same owned runner is used by native PSO and exact fragment batches.
    template.run_offline=run_owned
    shader_fragment_batch.run_offline=run_owned
    report=template.prepare(bundle,None,storage/'input/EMAIN.ELF',engine,decoder,storage,out,
        assets=a.assets.resolve(),asset_map=location_map,resume=out.exists(),
        output_validator=lambda p:p,progress=progress)
    if report['counts']!={'prepared':len(document['records'])}:
        raise ValueError('Some entries could not be prepared; normal play remains available. See '+str(out/'report.json'))
    # Switch only after successful shader/native/persistence validation. Existing
    # caches remain intact; game demand can add missing/settings-specific entries.
    pointer=storage/'prepared-cache.txt';pending=pointer.with_suffix('.tmp')
    pending.write_text((out/'shadercache').relative_to(storage).as_posix(),encoding='utf-8');pending.replace(pointer)
    status.write_text('Complete. Normal demand compilation handles uncovered pipelines.',encoding='utf-8')


if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:
        print('Cancelled. Completed preparation is retained for resume.',flush=True);sys.exit(2)
    except Exception as exc:
        print(str(exc),file=sys.stderr,flush=True);sys.exit(1)
