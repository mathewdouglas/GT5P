"""Exercise a compiled launcher against a stand-in child, never the game.

Build launcher_probe.cpp with /MT, then pass --launcher and --probe EXE paths.
All metadata, ELF bytes and volume files are synthetic; temporary data is private.
"""
import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time


def sfo(title='BCUS98158', version='03.00'):
    keys = b'TITLE_ID\0VERSION\0APP_VER\0'
    a, b = title.encode() + b'\0', version.encode() + b'\0'
    return (struct.pack('<5I', 0x46535000, 0x101, 68, 68 + len(keys), 3)
            + struct.pack('<HHIII', 0, 0x204, len(a), len(a), 0)
            + struct.pack('<HHIII', 9, 0x204, len(b), len(b), len(a))
            + struct.pack('<HHIII', 17, 0x204, 6, 6, len(a)+len(b))
            + keys + a + b + b'01.00\0')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--launcher', type=Path, required=True)
    ap.add_argument('--probe', type=Path, required=True)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='GT5P launcher test ') as temp:
        root = Path(temp)
        install, data = root/'Install with spaces', root/'User data'
        disc = root/'Disc dump'/'PS3_GAME'
        for p in (install/'runtime', install/'assets', data/'input', disc/'USRDIR'):
            p.mkdir(parents=True)
        launcher = install/'GT5P.exe'
        shutil.copyfile(args.launcher, launcher)
        shutil.copyfile(args.probe, install/'runtime/gt5p.exe')
        (install/'assets/probe.txt').write_text('distributable fixture')
        elf = b'\x7fELF synthetic launcher fixture'
        (data/'input/EMAIN.ELF').write_bytes(elf)
        for name in ('GT.VOL', 'TV.DAT'):
            (disc/'USRDIR'/name).write_bytes(b'synthetic volume')
        param = disc/'PARAM.SFO'
        param.write_bytes(sfo())
        setup = data/'setup.ini'

        def selection(path):
            setup.write_text('[game]\ndirectory='+str(path)+'\n', encoding='utf-16')

        def manifest():
            engine_hash = hashlib.sha256((install/'runtime/gt5p.exe').read_bytes()).hexdigest()
            (install/'release.ini').write_text('[release]\nschema=1\ntarget=BCUS98158\n'
                'version=03.00\nelf_sha256='+hashlib.sha256(elf).hexdigest()
                +'\ngame_sha256='+engine_hash+'\n')

        env = dict(os.environ, GT5P_USER_DIR=str(data), PS3_VERBOSE='0')
        env.pop('GT5P_PROBE_DELAY_MS', None)

        def check(label, expected=0, extra=()):
            p = subprocess.run([launcher, '--check', *extra], env=env, timeout=10,
                               capture_output=True)
            assert p.returncode == expected, (label, p.returncode, p.stderr)
            assert not (data/'probe.txt').exists(), label+' launched child'
            print(label+': passed')

        manifest()
        check('missing configuration', 1)
        selection(disc.parent)
        check('disc-root normalization')
        selection(disc)
        check('PS3_GAME selection')
        check('forced setup is noninteractive with check', 1, ('--setup',))
        check('unknown option is noninteractive with check', 1, ('--invalid',))
        p = subprocess.run([launcher, '--invalid', '--check'], env=env,
                           timeout=10, capture_output=True)
        assert p.returncode == 1
        long_env = dict(env, GT5P_USER_DIR=str(root/('long-path-' * 60)))
        p = subprocess.run([launcher, '--check'], env=long_env,
                           timeout=10, capture_output=True)
        assert p.returncode == 1
        print('check suppresses early path/option errors in either option order: passed')
        selection(root/'moved dump')
        check('moved dump', 1)
        selection(disc)
        for title, version in [('WRONG0000', '03.00'), ('BCUS98158', '02.00')]:
            param.write_bytes(sfo(title, version))
            check('wrong title/version '+title+'/'+version, 1)
        param.write_bytes(b'\x00PSF')
        check('truncated SFO', 1)
        param.write_bytes(sfo())
        (disc/'USRDIR/TV.DAT').rename(disc/'USRDIR/TV.hidden')
        check('missing volume', 1)
        (disc/'USRDIR/TV.hidden').rename(disc/'USRDIR/TV.DAT')
        (data/'input/EMAIN.ELF').write_bytes(b'wrong ELF')
        check('wrong ELF digest', 1)
        (data/'input/EMAIN.ELF').write_bytes(elf)
        original = (install/'runtime/gt5p.exe').read_bytes()
        (install/'runtime/gt5p.exe').write_bytes(b'wrong engine')
        check('wrong engine digest', 1)
        (install/'runtime/gt5p.exe').write_bytes(original)
        before = {p: p.read_bytes() for p in disc.rglob('*') if p.is_file()}
        p = subprocess.run([launcher], env=env, timeout=15, capture_output=True)
        assert p.returncode == 0, (p.returncode, p.stderr)
        probe = dict(line.split('=', 1) for line in (data/'probe.txt').read_text(encoding='utf-8-sig').splitlines())
        assert probe['argc'] == '2' and probe['arg1'] == str(data/'input/EMAIN.ELF')
        for key, expected in {'cwd':data, 'GT5P_ROOT':data, 'PS3_VFS_ROOT':data,
                              'PS3_GAMEDATA_ROOT':data/'gamedata',
                              'GT5P_SETTINGS':data/'gt5p_settings.toml'}.items():
            assert Path(probe[key]) == expected, (key, probe[key])
        assert Path(probe['GT5P_GAME_DIR']) == disc and probe['PS3_VERBOSE'] == '0'
        assert 'probe stdout' in (data/'logs/play.out').read_text()
        assert 'probe stderr' in (data/'logs/play.err').read_text()
        assert (data/'assets/probe.txt').read_text() == 'distributable fixture'
        assert all(p.read_bytes() == b for p, b in before.items())
        print('saved launch, spaced paths, environment, logs, assets, dump preservation: passed')
        settings = data/'gt5p_settings.toml'
        assert 'resolution = "720p"' in settings.read_text()
        settings.write_text('# existing personal settings\n')
        p = subprocess.run([launcher], env=env, timeout=15, capture_output=True)
        assert p.returncode == 0 and settings.read_text() == '# existing personal settings\n'
        print('second launch and settings preservation: passed')
        (data/'probe.txt').unlink()
        child_env = dict(env, GT5P_PROBE_DELAY_MS='30000')
        owner = subprocess.Popen([launcher], env=child_env)
        child_handle = None
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        try:
            deadline = time.monotonic() + 10
            while not (data/'probe.txt').exists() and time.monotonic() < deadline:
                time.sleep(.05)
            assert (data/'probe.txt').exists(), 'child never started'
            marker = (data/'probe.txt').read_bytes()
            child_pid = int(dict(line.split('=', 1) for line in marker.decode('utf-8-sig').splitlines())['pid'])
            child_handle = kernel.OpenProcess(0x00100000, False, child_pid)
            assert child_handle, 'could not observe owned child'
            duplicate = subprocess.run([launcher, '--check'], env=env, timeout=10)
            assert duplicate.returncode == 1
            assert (data/'probe.txt').read_bytes() == marker
            print('duplicate launch blocked while owned child runs: passed')
        finally:
            owner.terminate()
            owner.wait(timeout=10)
            if child_handle:
                try:
                    assert kernel.WaitForSingleObject(child_handle, 10000) == 0, 'owned child survived launcher exit'
                finally:
                    kernel.CloseHandle(child_handle)
        # The killed launcher's job must retire its child and release the lock.
        deadline = time.monotonic() + 10
        while True:
            p = subprocess.run([launcher, '--check'], env=env, timeout=10)
            if p.returncode == 0:
                break
            assert time.monotonic() < deadline, 'child retained launcher lock'
            time.sleep(.05)
        print('launcher termination retires owned child and releases lock: passed')

        # A small per-user locator remembers an external/custom storage path.
        # Keep this isolated from the real Local AppData profile.
        home, target = root/'Locator home', root/'External SSD'/'GT5P data'
        shutil.copytree(data, home)
        storage_env = dict(env, GT5P_LAUNCHER_HOME=str(home))
        storage_env.pop('GT5P_USER_DIR')
        (home/'shadercache').mkdir()
        (home/'shadercache/sentinel.bin').write_bytes(b'personal cache')
        (home/'gamedata/save.bin').write_bytes(b'personal save')
        moved = subprocess.run([launcher, '--set-storage', target], env=storage_env,
                               timeout=15, capture_output=True)
        assert moved.returncode == 0, moved.stderr
        for name in ('setup.ini', 'input/EMAIN.ELF', 'gt5p_settings.toml',
                     'shadercache/sentinel.bin', 'gamedata/save.bin'):
            assert (target/name).read_bytes() == (home/name).read_bytes(), name
        locator = (home/'storage.ini').read_bytes()
        p = subprocess.run([launcher, '--check'], env=storage_env, timeout=10)
        assert p.returncode == 0
        p = subprocess.run([launcher], env=storage_env, timeout=15)
        assert p.returncode == 0
        probe = dict(line.split('=',1) for line in (target/'probe.txt').read_text(encoding='utf-8-sig').splitlines())
        assert Path(probe['GT5P_ROOT']) == target
        print('custom storage: verified copy, original preservation, remembered launch location: passed')
        owner = subprocess.Popen([launcher], env=dict(storage_env, GT5P_PROBE_DELAY_MS='30000'))
        try:
            # The previously completed child has gone; wait for this one's PID.
            old_pid = probe['pid']
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    current = dict(line.split('=',1) for line in (target/'probe.txt').read_text(encoding='utf-8-sig').splitlines())
                    if current.get('pid') and current['pid'] != old_pid:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(.05)
            else:
                raise AssertionError('delayed custom-storage child did not start')
            blocked = root/'Must not be created'
            p = subprocess.run([launcher, '--set-storage', blocked], env=storage_env,
                               timeout=10, capture_output=True)
            assert p.returncode == 1 and not blocked.exists()
            assert (home/'storage.ini').read_bytes() == locator
        finally:
            owner.terminate()
            owner.wait(timeout=10)
        print('storage relocation blocked while game child runs: passed')
        for dest in (target/'nested', root, install, home, disc):
            p = subprocess.run([launcher, '--set-storage', dest], env=storage_env,
                               timeout=10, capture_output=True)
            assert p.returncode == 1, dest
            assert (home/'storage.ini').read_bytes() == locator
        print('nested/source/installation/nonempty targets refused without changing selection: passed')
        unavailable = target.with_name('temporarily disconnected')
        target.rename(unavailable)
        try:
            p = subprocess.run([launcher, '--check'], env=storage_env, timeout=10)
            assert p.returncode == 1
            assert not target.exists(), 'missing storage recreated silently'
            assert (home/'storage.ini').read_bytes() == locator
        finally:
            unavailable.rename(target)
        second = root/'Second SSD'/'Data'
        p = subprocess.run([launcher, '--set-storage', second], env=storage_env,
                           timeout=15, capture_output=True)
        assert p.returncode == 0, p.stderr
        assert (second/'gamedata/save.bin').read_bytes() == b'personal save'
        assert (target/'gamedata/save.bin').read_bytes() == b'personal save'
        p = subprocess.run([launcher, '--check'], env=storage_env, timeout=10)
        assert p.returncode == 0
        print('unavailable drive preserves selection; subsequent storage relocation: passed')


if __name__ == '__main__':
    main()
