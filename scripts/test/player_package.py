"""Offline packaging checks using synthetic metadata only; never launch a game.

No real executable, DLL, game dump, key or decrypted game data is used. Run
after the active development/testing session is finished, as documented.
"""
import importlib.util
from pathlib import Path
import tempfile
from unittest.mock import patch
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('player_package', ROOT / 'scripts/release/package_player.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def put(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def main():
    with tempfile.TemporaryDirectory(prefix='gt5p-package-fixture-') as temp:
        root = Path(temp)
        package.ROOT = root / 'repo'
        pe = b'MZ' + bytes(58) + (64).to_bytes(4, 'little') + b'PE\0\0\x64\x86'
        elf = b'\x7fELF\x02\x02' + bytes(12) + b'\x00\x15'
        build = root / 'build'
        cmake = b'GT5P_TARGET:STRING=BCUS98158\nCMAKE_BUILD_TYPE:STRING=Release\n'
        put(build / 'CMakeCache.txt', cmake)
        put(build / 'gt5p.exe', pe)
        put(root / 'launcher.exe', pe)
        put(root / 'EMAIN.ELF', elf)
        for name in package.RUNTIME:
            put(build / name, pe)
        for name in package.VC_REQUIRED:
            put(root / 'crt' / name, pe)
        for name in package.NOTICES:
            put(root / 'notices' / name, b'Synthetic fixture https://example.invalid/source\n')
        put(package.ROOT / 'LICENSE', b'Synthetic license fixture\n')
        put(package.ROOT / 'launcher/START-HERE.txt', b'Synthetic instructions\n')
        put(package.ROOT / 'launcher/Change storage.cmd', b'@echo off\n')
        put(package.ROOT / 'assets/glyphs/textures.txt', b'# Synthetic metadata\n')
        put(package.ROOT / 'assets/glyphs/kenney/License.txt', b'Synthetic license\n')
        # These deliberately sit near the build input and must never leak.
        put(build / 'input/EMAIN.ELF', b'personal executable sentinel')
        put(build / 'gamedata/personal.txt', b'personal savedata sentinel')
        put(build / 'shadercache/private.txt', b'private cache sentinel')
        put(build / 'gt5p_settings.toml', b'personal settings sentinel')
        out = root / 'player.zip'
        argv = ['package_player.py', '--build-dir', str(build), '--launcher-exe', str(root/'launcher.exe'),
                '--elf', str(root/'EMAIN.ELF'), '--vc-runtime-dir', str(root/'crt'),
                '--notices-dir', str(root/'notices'), '--output', str(out)]

        def call():
            with patch.object(sys, 'argv', argv):
                package.main()

        def refused(label):
            try:
                call()
            except ValueError:
                assert not out.exists(), label
                print(label + ': refused')
            else:
                raise AssertionError(label + ' was accepted')

        put(build/'CMakeCache.txt', cmake.replace(b'BCUS98158', b'NPUA80075'))
        refused('wrong target')
        put(build/'CMakeCache.txt', cmake.replace(b'Release', b'Debug'))
        refused('debug build')
        put(build/'CMakeCache.txt', cmake)
        missing = build/package.RUNTIME[0]
        missing.unlink()
        refused('missing dependency')
        put(missing, b'not a Windows DLL')
        refused('non-PE dependency')
        put(missing, pe)
        put(root/'EMAIN.ELF', b'not an ELF')
        refused('wrong executable format')
        put(root/'EMAIN.ELF', elf)
        png = package.ROOT/'assets/glyphs/bad.png'
        put(png, b'not a PNG')
        refused('disguised asset')
        png.unlink()
        call()
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            assert 'release.ini' in names and 'runtime/gt5p.exe' in names
            assert 'Change storage.cmd' in names
            assert not any(n.startswith(('input/', 'gamedata/', 'shadercache/')) for n in names)
            assert not any(n.lower().endswith(('.elf', '.self', '.toml')) for n in names)
            assert all(b'sentinel' not in z.read(n) for n in names)
            manifest = z.read('release.ini').decode()
            assert 'elf_sha256=' + package.sha(root/'EMAIN.ELF') in manifest
            assert 'game_sha256=' + package.sha(build/'gt5p.exe') in manifest
        print('allowlist, exclusion and digest checks: passed')
        before = out.read_bytes()
        try:
            call()
        except ValueError:
            assert out.read_bytes() == before
            print('existing ZIP preserved: passed')
        else:
            raise AssertionError('Existing output was overwritten')


if __name__ == '__main__':
    main()
