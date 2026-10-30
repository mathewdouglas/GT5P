"""Compare explicit colour-only target construction with production no-DSV code."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_coverage import ROOT


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtime', required=True, type=Path)
    args = ap.parse_args()
    source = (args.runtime / 'libs/video/rsx_d3d12_backend.c').read_text()
    start = source.index('    { static int pa = -1;', source.index('/* Bit 27:'))
    end = source.index('    { static int doff', start)
    production = source[start:end]
    folder = ROOT / 'scratch' / ('shared-target-native-' + uuid.uuid4().hex)
    folder.mkdir()
    prefix = '''#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <d3d12.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
'''
    for name in ('rsx_native_reconstruct.h', 'rsx_material_reconstruct.h'):
        prefix += '#include "' + str((args.runtime / 'libs/video' / name).resolve()).replace('\\', '/') + '"\n'
    suffix = '''
__declspec(dllexport) int compare(const char* backed,const char* colour,unsigned poison) {
 D3D12_GRAPHICS_PIPELINE_STATE_DESC pd,independent;
 memset(&pd,poison,sizeof pd);memset(&independent,poison,sizeof independent);
 if(!pso_native_base(backed,&pd)||!pso_material_apply(backed,&pd))return 1;
 if(!pso_native_base(colour,&independent)||!pso_material_apply(colour,&independent))return 2;
 unsigned stencil=0xf8000000;
''' + production + '''
 return memcmp(&pd,&independent,sizeof pd)?3:0;
}
__declspec(dllexport) int parse(const char* path) {
 D3D12_GRAPHICS_PIPELINE_STATE_DESC pd;
 if(!pso_native_base(path,&pd))return 0;
 return pso_material_apply(path,&pd)?2:1;
}
'''
    (folder / 'oracle.c').write_text(prefix + suffix)
    vc = 'C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'
    (folder / 'build.cmd').write_text('@echo off\ncall "' + vc + '" >nul\nif errorlevel 1 exit /b 1\n'
        '"C:/Program Files/LLVM/bin/clang-cl.exe" /nologo /O2 /MD /LD /Fooracle.obj /Feoracle.dll oracle.c\n')
    subprocess.run(['cmd', '/c', str(folder / 'build.cmd')], cwd=folder, check=True)
    os.environ.pop('PSO_DSV_ALWAYS', None)
    dll = ctypes.CDLL(str(folder / 'oracle.dll'))
    dll.compare.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    dll.parse.argtypes = [ctypes.c_char_p]
    checks = 0
    for format, samples in ((11, 1), (11, 2), (28, 1)):
        backed = folder / f'b-{format}-{samples}'
        colour = folder / f'c-{format}-{samples}'
        for path in (backed, colour):
            path.mkdir()
            (path / 'material.state').write_text('GT5P_MATERIAL_V1 0 f f0000000\n')
        (backed / 'target.state').write_text(f'GT5P_TARGET_V1 {format} {samples}\n')
        (colour / 'target.state').write_text(f'GT5P_TARGET_V2 {format} {samples} 0\n')
        for poison in (0, 0xff, 0xa5, 0x5a):
            assert dll.compare(str(backed).encode(), str(colour).encode(), poison) == 0
            checks += 1
    invalid = folder / 'invalid'
    invalid.mkdir()
    (invalid / 'material.state').write_text('GT5P_MATERIAL_V1 0 f f0000000\n')
    for text in (b'GT5P_TARGET_V2 11 1\n', b'GT5P_TARGET_V2 11 1 2\n',
                 b'GT5P_TARGET_V2 11 3 0\n', b'GT5P_TARGET_V2 28 2 0\n',
                 b'GT5P_TARGET_V2 11 1 0 extra\n', b'GT5P_TARGET_V2 11 1 0\0', b'x' * 100):
        (invalid / 'target.state').write_bytes(text)
        assert dll.parse(str(invalid).encode()) == 0
        checks += 1
    (invalid / 'target.state').write_text('GT5P_TARGET_V2 11 1 0\n')
    (invalid / 'material.state').write_text('GT5P_MATERIAL_V1 0 f b0000000\n')
    assert dll.parse(str(invalid).encode()) == 1, 'Contradictory depth state accepted'
    checks += 1
    (folder / 'report.json').write_text(json.dumps(dict(checks=checks, scope='Whole native descriptor equality with production no-DSV transform; malformed and contradictory target rejection'), indent=2))
    print(f'{checks} shared native target checks passed: {folder / "report.json"}')


if __name__ == '__main__':
    main()
