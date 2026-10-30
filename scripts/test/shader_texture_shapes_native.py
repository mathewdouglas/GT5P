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
from shader_texture_shapes import texture_fields
from shader_coverage import ROOT


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--runtime', required=True, type=Path)
args = ap.parse_args()
source = (args.runtime / 'libs/video/rsx_d3d12_backend.c').read_text()
snippets = '\n'.join(function(source, n) for n in ('dr_volume_mask', 'dr_cube_mask', 'dr_unnorm_hi', 'dr_unnorm'))
start = source.index('    { static int off = -1;', source.index('static void dr_note_surface('))
end = source.index('    if (rsx_stencil_mask_pass(st))', start)
gamma_block = source[start:end]
assignments = []
for field in ('depth', 'cube'):
    marker = f'        s_d3d.cur_texs[unit].{field}'
    start = source.index(marker, source.index('static void d3d12_bind_texture('))
    end = source.index(';', start) + 1
    assignments.append(source[start:end].replace('s_d3d.cur_texs[unit]', 'dr.tex[unit]'))
prefix = '''#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#define RSX_TEX_UNITS 16
typedef uint32_t u32;
typedef uint8_t u8;
typedef uint16_t u16;
typedef struct {struct {u32 set,depth,cube,w,h,fmt;} tex[16];u32 tex_gamma,tex_gamma_hi,srgb_wr,tex_sc,tex_dz,tex_mip,dz_sel;} D3D12DrawRecord;
typedef struct {struct {u32 address;} textures[16];u32 shader_packer;} rsx_state;
static int texture_volume_on(void) {return 1;}
'''
suffix = '''
__declspec(dllexport) void shape(u32 format,u32 control3,u32 address,u32 unit,u32* out) {
 struct {u32 format,control3;} input={format,control3},*tex=&input;
 D3D12DrawRecord dr={0},*drp=&dr;dr.tex[unit].set=1;
 dr.tex[unit].fmt=(format>>8)&255;dr.tex[unit].w=64;dr.tex[unit].h=32;
 rsx_state input_state={0},*st=&input_state;st->textures[unit].address=address;
''' + '\n'.join(assignments) + gamma_block.replace('dr->', 'drp->') + '''
 out[0]=dr_cube_mask(&dr);out[1]=dr.tex_gamma_hi|(dr_volume_mask(&dr)<<16);out[2]=dr_unnorm_hi(&dr);u32 dim[16][2];out[3]=dr_unnorm(&dr,dim);
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
for key in ('RSX_CUBE_TEX', 'RSX_CUBE_HI', 'RSX_NO_GAMMA', 'RSX_GAMMA_HI', 'RSX_UNNORM_HI', 'RSX_NO_UNNORM'):
    os.environ.pop(key, None)
lib = ctypes.CDLL(str(folder / 'oracle.dll'))
lib.shape.argtypes = [ctypes.c_uint32] * 4 + [ctypes.POINTER(ctypes.c_uint32)]
checks = 0
for unit in range(16):
    for dimension, cube in ((2, 0), (2, 4), (3, 0)):
        for depth in (0, 1, 8, 4095):
            for other in (0x00018800, 0x0001a800, 0x0030c803, 0xffffe800):
                fmt, control3 = other | dimension << 4 | cube, depth << 20
                for gamma in (0, 1, 7):
                    address = gamma << 20
                    binding = dict(unit=unit, format=fmt, control3=control3, address=address, width=64, height=32)
                    fields = texture_fields(dict(bindings=[binding], globals=[], used=1 << unit), sampling=True)
                    out = (ctypes.c_uint32 * 4)()
                    lib.shape(fmt, control3, address, unit, out)
                    assert fields['known_units'] == 1 << unit
                    assert list(out)[:3] == [fields['values']['cube'], fields['values']['ghi'], fields['values']['unhi']]
                    if dimension == 2 and not cube:
                        assert out[3] == ((1 << unit) if unit < 4 and fmt & 0x4000 else 0)
                    checks += 1

report = dict(checks=checks, ordinary_low_coordinate_checks=checks // 3, scope='Production bind depth/cube, read-gamma block and shape/coordinate key helpers; ordinary 2D low-coordinate cases have no alias redirects; default switches; no GPU/game startup')
(folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(report)
print('Evidence:', folder / 'report.json')
