"""Test the offline transform against a local lifted routine, never tracked.

The game-derived source/DLL remain in ignored scratch. No guest game starts,
no generated input is patched, and the oracle executes only on private blocks.
"""
import argparse
import ctypes
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
import shader_material_state as m
from shader_depth_commands import asset_blocks
from shader_material_state_native import words


def extract(source, name):
    match = re.search(r'^(?:static inline [^\n]+|void) ' + name + r'\([^\n]*\)\s*\{', source, re.M)
    if not match:
        raise ValueError('Required local function absent: ' + name)
    pos, depth = match.end(), 1
    while depth and pos < len(source):
        depth += (source[pos] == '{') - (source[pos] == '}')
        pos += 1
    if depth:
        raise ValueError('Incomplete local function')
    return source[match.start():pos]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--generated', type=Path, required=True, help='Local disc-build ppu_recomp_005.cpp')
    ap.add_argument('--states', type=Path, required=True, help='State audit model inventory')
    ap.add_argument('--vcvars', type=Path, default=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'))
    ap.add_argument('--compiler', type=Path, default=Path('C:/Program Files/LLVM/bin/clang-cl.exe'))
    args = ap.parse_args()
    source = args.generated.read_text()
    snippets = '\n'.join(extract(source, name) for name in ('ppc_rlw64', 'ppc_sraw', 'func_00834968'))
    folder = m.ROOT / 'scratch' / ('material-prepare-native-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    prefix = '''#define PPU_NO_INLINE_LOADS
#define PPU_NO_INLINE_STORES
#include "ppu_recomp.h"
#include <string.h>
#include <assert.h>
#define PPU_MM_SNAP
static uint32_t memory[40];
extern "C" uint32_t vm_read32(uint64_t a) { assert(a>=4096 && a<4256 && !(a&3));return memory[(a-4096)/4]; }
extern "C" void vm_write32(uint64_t a,uint32_t v) { assert(a>=4096 && a<4256 && !(a&3));memory[(a-4096)/4]=v; }
'''
    suffix = '''
extern "C" __declspec(dllexport) void prepare(const uint32_t* input,uint32_t* output) {
 memcpy(memory,input,sizeof memory);ppu_context ctx={0};ctx.gpr[3]=4096;
 func_00834968(&ctx);memcpy(output,memory,sizeof memory);
}
'''
    (folder / 'oracle.cpp').write_text(prefix + snippets + suffix)
    command = ('@echo off\ncall "' + str(args.vcvars.resolve()) + '" >nul\nif errorlevel 1 exit /b 1\n"' +
               str(args.compiler.resolve()) + '" /nologo /O2 /MD /LD /I"' + str(args.generated.resolve().parent) +
               '" /Fo"' + str(folder / 'oracle.obj') + '" /Fe"' + str(folder / 'oracle.dll') +
               '" "' + str(folder / 'oracle.cpp') + '"\n')
    (folder / 'build.cmd').write_text(command)
    subprocess.run(['cmd', '/c', str(folder / 'build.cmd')], check=True, cwd=folder)
    library = ctypes.CDLL(str(folder / 'oracle.dll'))
    library.prepare.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
    blocks = [block['words'] for block in asset_blocks(json.loads(args.states.read_text()))]
    rng = random.Random(141)
    for _ in range(2048):
        w = words()
        w[1], w[4], w[33], w[34] = (rng.randrange(2) for _ in range(4))
        w[32] = rng.randrange(0x200, 0x208)
        w[38], w[39] = rng.getrandbits(32), rng.getrandbits(32)
        blocks.append(w)
    for w in blocks:
        before = list(w)
        output = (ctypes.c_uint32 * 40)()
        library.prepare((ctypes.c_uint32 * 40)(*w), output)
        assert list(output) == m.prepare_state(w), (w, list(output), m.prepare_state(w))
        assert w == before
    print(f'{len(blocks)} full blocks matched the isolated lifted material-preparation routine; original generated source unchanged')


if __name__ == '__main__':
    main()
