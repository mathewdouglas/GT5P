"""Check the actual packaged game window title; close only the owned launcher job."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).parents[1]))
from train_pipeline_cache import idle,isolated

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('launcher','storage','output'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();idle();out=isolated(a.output);out.mkdir(parents=True)
    assert a.launcher.name=='tourline-prologue.exe'
    expected=(a.launcher.resolve().parent/'runtime/gt5p.exe').resolve()
    api=ctypes.WinDLL('user32');kernel=ctypes.WinDLL('kernel32')
    cb=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    api.EnumWindows.argtypes=[cb,ctypes.c_void_p]
    api.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    api.GetWindowTextW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    found=[]
    @cb
    def inspect(hwnd,unused):
        title=ctypes.create_unicode_buffer(1024);api.GetWindowTextW(hwnd,title,len(title))
        if not title.value.startswith('Project Tourline Prologue'):return True
        pid=ctypes.c_ulong();api.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        handle=kernel.OpenProcess(0x1000,False,pid.value)
        path=ctypes.create_unicode_buffer(32768);size=ctypes.c_ulong(len(path))
        try:
            if handle and kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)) and Path(path.value)==expected:
                found.append(dict(title=title.value,pid=pid.value,engine=str(expected)))
        finally:
            if handle:kernel.CloseHandle(handle)
        return True
    env=dict(os.environ,GT5P_USER_DIR=str(a.storage.resolve()),PS3_VERBOSE='0',GT5P_STORAGE_PICKER='0')
    child=subprocess.Popen([str(a.launcher.resolve())],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    game_handle=None
    try:
        begin=time.monotonic()
        while not found and time.monotonic()-begin<30:
            assert child.poll() is None,'Packaged launcher exited before its game window appeared'
            api.EnumWindows(inspect,None);time.sleep(.1)
        assert found,'Branded packaged game window was not observed'
        game_handle=kernel.OpenProcess(0x100000,False,found[-1]['pid'])
        (out/'report.json').write_text(json.dumps(found[-1],indent=2)+'\n')
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=15)
        if game_handle:
            try:assert kernel.WaitForSingleObject(game_handle,15000)==0,'Owned game did not retire with its launcher'
            finally:kernel.CloseHandle(game_handle)
    idle()
    print('Packaged entry point and real Project Tourline Prologue game title passed')

if __name__=='__main__':main()
