"""Differential shape-key check using production bind statements and key helpers."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_material_state_native import function
from shader_texture_shapes import shape_fields
from shader_coverage import ROOT


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--runtime', required=True, type=Path)
args = ap.parse_args()
source = (args.runtime / 'libs/video/rsx_d3d12_backend.c').read_text()
snippets = '\n'.join(function(source, n) for n in ('dr_volume_mask', 'dr_cube_mask'))
assignments = []
for field in ('depth', 'cube'):
    marker = f'        s_d3d.cur_texs[unit].{field}'
    start = source.index(marker, source.index('static void d3d12_bind_texture('))
    end = source.index(';', start) + 1
    assignments.append(source[start:end].replace('s_d3d.cur_texs[unit]', 'dr.tex[unit]'))
prefix = '''#include <stdlib.h>
#include <stdint.h>
#define RSX_TEX_UNITS 16
typedef uint32_t u32;
typedef struct {struct {u32 set,depth,cube;} tex[16];u32 tex_gamma,srgb_wr;} D3D12DrawRecord;
static int texture_volume_on(void) {return 1;}
'''
suffix = '''
__declspec(dllexport) void shape(u32 format,u32 control3,u32 unit,u32* out) {
 struct {u32 format,control3;} input={format,control3},*tex=&input;
 D3D12DrawRecord dr={0};dr.tex[unit].set=1;
''' + '\n'.join(assignments) + '''
 out[0]=dr_cube_mask(&dr);out[1]=dr_volume_mask(&dr)<<16;
}
'''
folder = ROOT / 'scratch' / ('texture-shapes-native-' + uuid.uuid4().hex)
folder.mkdir()
(folder / 'oracle.c').write_text(prefix + snippets + suffix)
vc = 'C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'
compiler = 'C:/Program Files/LLVM/bin/clang-cl.exe'
(folder / 'build.cmd').write_text(f'@echo off\ncall "{vc}" >nul\nif errorlevel 1 exit /b 1\n'
                                 f'"{compiler}" /nologo /O2 /MD /LD /D_CRT_SECURE_NO_WARNINGS /Fooracle.obj /Feoracle.dll oracle.c\n')
subprocess.run(['cmd', '/c', str(folder / 'build.cmd')], cwd=folder, check=True)
for key in ('RSX_CUBE_TEX', 'RSX_CUBE_HI'):
    os.environ.pop(key, None)
lib = ctypes.CDLL(str(folder / 'oracle.dll'))
lib.shape.argtypes = [ctypes.c_uint32] * 3 + [ctypes.POINTER(ctypes.c_uint32)]
checks = 0
for unit in range(16):
    for dimension, cube in ((2, 0), (2, 4), (3, 0)):
        for depth in (0, 1, 8, 4095):
            for other in (0, 0x00018800, 0x00308803, 0xffffa800):
                fmt, control3 = other | dimension << 4 | cube, depth << 20
                binding = dict(unit=unit, format=fmt, control3=control3, width=64, height=32)
                fields = shape_fields(dict(bindings=[binding], globals=[], used=1 << unit))
                out = (ctypes.c_uint32 * 2)()
                lib.shape(fmt, control3, unit, out)
                assert fields['known_units'] == 1 << unit
                assert list(out) == [fields['values']['cube'], fields['values']['ghi']]
                checks += 1
report = dict(checks=checks, scope='Production bind depth/cube statements and key helpers; default switches; no GPU/game startup')
(folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(report)
print('Evidence:', folder / 'report.json')
