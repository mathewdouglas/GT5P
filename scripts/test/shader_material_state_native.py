"""Differential check using production key functions; no game or GPU is started."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
import shader_material_state as m


def function(source, name):
    import re
    match = re.search(r'^static (?:u8|u32|int) ' + name + r'\([^\n]*\)\s*\{', source, re.M)
    if not match:
        raise ValueError('Production function signature changed: ' + name)
    # The extracted functions contain no braces in strings or character literals
    # that affect nesting. Keep the test failing closed if extraction changes.
    level = 1
    pos = match.end()
    while level and pos < len(source):
        level += (source[pos] == '{') - (source[pos] == '}')
        pos += 1
    if level:
        raise ValueError('Unterminated production function: ' + name)
    return source[match.start():pos]


def words():
    result = [0] * 40
    for index, value in ((0, 0x00780304), (31, 0x000C0A6C), (35, 0x0004183C),
                          (37, 0x00020000), (38, 0xFFFF0000), (5, 0x00010001),
                          (8, 0x80068006), (9, 0x01010101), (32, 0x201), (33, 1), (34, 1)):
        result[index] = value
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtime', type=Path, required=True)
    ap.add_argument('--vcvars', type=Path, default=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'))
    ap.add_argument('--compiler', type=Path, default=Path('C:/Program Files/LLVM/bin/clang-cl.exe'))
    ap.add_argument('--state-report', type=Path, help='Also compare every decoded real block in an audit report')
    args = ap.parse_args()
    source = (args.runtime / 'libs/video/rsx_d3d12_backend.c').read_text()
    names = ('gl_blend_factor_d3d', 'gl_blend_op_d3d', 'rsx_blend_key', 'depth_state_on', 'rsx_depth_bits', 'rsx_cull_key')
    snippets = '\n'.join(function(source, name) for name in names)
    prefix = '''#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <windows.h>
#include <d3d12.h>
typedef uint32_t u32;
typedef uint8_t u8;
typedef struct {
 u32 blend_sfactor,blend_dfactor,blend_equation;
 u32 depth_test_enable,depth_func,depth_mask;
 u32 cull_face_enable,cull_face,front_face,shader_program;
} rsx_state;
'''
    suffix = '''
__declspec(dllexport) void keys(const u32* w,u32* out) {
 rsx_state s={0};
 s.blend_sfactor=w[5];s.blend_dfactor=w[6];s.blend_equation=w[8];
 s.depth_func=w[32];s.depth_mask=w[33];s.depth_test_enable=w[34];
 s.cull_face_enable=w[36];s.cull_face=0x405;s.front_face=0x900;
 out[0]=rsx_blend_key(&s,w[4]);
 out[1]=((w[9]&0x10000)?1:0)|((w[9]&0x100)?2:0)|((w[9]&1)?4:0)|((w[9]&0x1000000)?8:0);
 out[2]=rsx_depth_bits(&s);out[3]=rsx_cull_key(&s)&1;
}
'''
    folder = m.ROOT / 'scratch' / ('material-state-native-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    (folder / 'keys.c').write_text(prefix + snippets + suffix)
    command = ('@echo off\ncall "' + str(args.vcvars.resolve()) + '" >nul\n'
               'if errorlevel 1 exit /b 1\n"' + str(args.compiler.resolve()) +
               '" /nologo /O2 /MD /LD /D_CRT_SECURE_NO_WARNINGS /Fo"' + str(folder / 'keys.obj') +
               '" /Fe"' + str(folder / 'keys.dll') + '" "' + str(folder / 'keys.c') + '"\n')
    (folder / 'build.cmd').write_text(command)
    subprocess.run(['cmd', '/c', str(folder / 'build.cmd')], check=True, cwd=folder)
    # The library must initialize with production diagnostic overrides unset.
    for key in ('BLENDDBG', 'RSX_DEPTH_STATE', 'RSX_DEPTH_ALWAYS', 'CULL_OFF_FP'):
        os.environ.pop(key, None)
    library = ctypes.CDLL(str(folder / 'keys.dll'))
    library.keys.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
    rng = random.Random(139)
    cases = []
    factors = [0, 1, *range(0x300, 0x309), *range(0x8001, 0x8005)]
    operations = [0, 0x8006, 0x8007, 0x8008, 0x800A, 0x800B]
    for _ in range(2048):
        w = words()
        w[4] = rng.randrange(2)
        w[5] = rng.choice(factors) | rng.choice(factors) << 16
        w[6] = rng.choice(factors) | rng.choice(factors) << 16
        if w[5] == w[6] == 0:
            w[5] = 1
        w[8] = rng.choice(operations) | rng.choice(operations) << 16
        w[9] = sum(flag for flag in (0x1000000, 0x10000, 0x100, 1) if rng.randrange(2))
        w[32:35] = [rng.randrange(0x200, 0x208), rng.randrange(2), rng.randrange(2)]
        w[36] = rng.randrange(2)
        cases.append(w)
    if args.state_report:
        for model in json.loads(args.state_report.read_text())['models']:
            for state in model['states'].values():
                w = words()
                for address, value in state['registers'].items():
                    address = int(address, 16)
                    index = (1 + (address - 0x304) // 4 if 0x304 <= address <= 0x378 else
                             32 + (address - 0xA6C) // 4 if 0xA6C <= address <= 0xA74 else 36)
                    w[index] = value
                cases.append(w)
    for w in cases:
        expected = m.decode_state(w)
        result = (ctypes.c_uint32 * 4)()
        library.keys((ctypes.c_uint32 * 40)(*w), result)
        assert list(result) == [expected[f] for f in m.FIELDS], (w, list(result), expected)
    print(f'{len(cases)} state blocks matched production blend/depth/cull key functions; no game/GPU started')


if __name__ == '__main__':
    main()
