"""Resolve disc-build global callback slots using an isolated local initializer.

No gameplay starts. Extracted game code, ELF bytes and results stay in ignored
scratch. This identifies callbacks, not their eventual texture/sampler state.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import uuid

from shader_material_prepare_native import extract


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--generated', type=Path, required=True)
    ap.add_argument('--elf', type=Path, required=True)
    args = ap.parse_args()
    data = args.elf.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != '8ee3523e8c05d6a27d3cc32f6caeb530059473e8b9ae04ad92fdbfb677603036':
        raise ValueError('Unsupported ELF: this oracle is specific to the measured disc build')
    folder = Path(__file__).resolve().parents[2] / 'scratch' / ('global-registry-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    source = (args.generated / 'ppu_recomp_005.cpp').read_text()
    libc = (args.generated / 'ppu_recomp_008.cpp').read_text()
    snippets = '\n'.join(extract(source, n) for n in (
        'ppc_rotl64', 'ppc_mask64', 'ppc_rlw64', 'ppc_rldicl', 'ppc_rldicr'))
    snippets += '\n' + extract(libc, 'func_00C11F10')
    snippets += '\n' + extract(source, 'func_00830050')
    handlers = (args.generated / 'ppu_recomp_009.cpp').read_text()
    snippets += '\n' + '\n'.join(extract(handlers, n) for n in ('func_00D6DE78', 'func_00D6DE98'))
    assert 'g_trampoline_fn' not in snippets, 'Isolated routines must not schedule trampolines'
    prefix = '''#define PPU_NO_INLINE_LOADS
#define PPU_NO_INLINE_STORES
#include "ppu_recomp.h"
#include <string.h>
#include <assert.h>
#define PPU_MM_SNAP
#define DRAIN_TRAMPOLINE(ctx) ((void)0)
static unsigned char memory[0x2000000];
static uint32_t fallback;
static void bounds(uint64_t a, unsigned n) { assert(a<sizeof memory && n<=sizeof memory-a); }
extern "C" uint8_t vm_read8(uint64_t a) { bounds(a,1);return memory[a]; }
extern "C" uint16_t vm_read16(uint64_t a) { return (vm_read8(a)<<8)|vm_read8(a+1); }
extern "C" uint32_t vm_read32(uint64_t a) { return (uint32_t(vm_read16(a))<<16)|vm_read16(a+2); }
extern "C" uint64_t vm_read64(uint64_t a) { return (uint64_t(vm_read32(a))<<32)|vm_read32(a+4); }
extern "C" void vm_write8(uint64_t a,uint8_t v) { bounds(a,1);memory[a]=v; }
extern "C" void vm_write16(uint64_t a,uint16_t v) { vm_write8(a,v>>8);vm_write8(a+1,v); }
extern "C" void vm_write32(uint64_t a,uint32_t v) { vm_write16(a,v>>16);vm_write16(a+2,v); }
extern "C" void vm_write64(uint64_t a,uint64_t v) { vm_write32(a,v>>32);vm_write32(a+4,v); }
void func_0082C1A0(ppu_context* ctx) { ctx->gpr[3]=fallback; }
'''
    suffix = '''
extern "C" __declspec(dllexport) void load(uint32_t a,const void* p,uint32_t n) {
 bounds(a,n);memcpy(memory+a,p,n);
}
extern "C" __declspec(dllexport) uint32_t word(uint32_t a) { return vm_read32(a); }
extern "C" __declspec(dllexport) uint32_t lookup(uint32_t which,uint32_t value) {
 ppu_context ctx={0};ctx.gpr[1]=0x1ff0000;ctx.gpr[2]=0x133bc58;
 uint32_t root=vm_read32(ctx.gpr[2]-0x66f8);
 uint32_t target=which ? vm_read32(root-0x8000)+0x1cb0 : vm_read32(root-0x7fe0)+0x70;
 vm_write32(target,value);
 if(which) func_00D6DE98(&ctx);else func_00D6DE78(&ctx);
 return (uint32_t)ctx.gpr[3];
}
extern "C" __declspec(dllexport) void init(uint32_t gate,uint32_t arg,uint32_t value) {
 ppu_context ctx={0};ctx.gpr[1]=0x1ff0000;ctx.gpr[2]=0x133bc58;
 ctx.gpr[3]=gate;ctx.gpr[4]=arg;fallback=value;func_00830050(&ctx);
}
'''
    (folder / 'oracle.cpp').write_text(prefix + snippets + suffix)
    vc = 'C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'
    compiler = 'C:/Program Files/LLVM/bin/clang-cl.exe'
    (folder / 'build.cmd').write_text(
        f'@echo off\ncall "{vc}" >nul\nif errorlevel 1 exit /b 1\n'
        f'"{compiler}" /nologo /O2 /MD /LD /I"{args.generated.resolve()}" '
        f'/Fooracle.obj /Feoracle.dll oracle.cpp\n')
    subprocess.run(['cmd', '/c', str(folder / 'build.cmd')], cwd=folder, check=True)
    lib = ctypes.CDLL(str(folder / 'oracle.dll'))
    lib.load.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    lib.word.argtypes = [ctypes.c_uint32]
    lib.word.restype = ctypes.c_uint32
    lib.init.argtypes = [ctypes.c_uint32] * 3
    lib.lookup.argtypes = [ctypes.c_uint32] * 2
    lib.lookup.restype = ctypes.c_uint32
    assert data[:6] == b'\x7fELF\x02\x02', 'Expected ELF64 big endian'
    phoff = struct.unpack_from('>Q', data, 32)[0]
    stride, count = struct.unpack_from('>HH', data, 54)
    for i in range(count):
        kind, _, off, va, _, size, memsize, _ = struct.unpack_from('>IIQQQQQQ', data, phoff + i * stride)
        if kind == 1:
            assert size <= memsize and off + size <= len(data) and va + memsize < 0x1ff0000
            payload = ctypes.create_string_buffer(data[off:off + size])
            lib.load(va, payload, size)
    base = lib.word(lib.word(0x133bc58 - 0x66f8) - 0x7fe0)
    assert base and base + 0x9c0 < 0x1ff0000
    slots = [71, 87, 94, 96, 103, 104, 115]
    expected = {
        71: (0xD6CAA0, 0xD6AD38), 87: (0xD6D930, 0xD6DE98),
        94: (0xD77CC0, 0xD6DE78), 96: (0xD6D898, 0xD6DE98),
        103: (0xD77C20, 0xD6DE78), 104: (0xD77A90, 0xD6DE78),
        115: (0xD6D9C0, 0xD6DEB8),
    }
    def snapshot():
        return [lib.word(base + table + i * 4) for table in (0x388, 0x7b0) for i in slots]
    before = snapshot()
    assert not any(before), 'Expected uninitialized BSS callback slots'
    for gate, arg in ((0, 0xffff), (1, 0), (1, 0xffffffff)):
        lib.init(gate, arg, 17)
        assert snapshot() == before, 'Initializer gate did not suppress writes'
    lib.init(1, 0xffff, 17)
    first = snapshot()
    assert any(first), 'Initializer did not populate any selected callback slots'
    lib.init(1, 0xffff, 12345)
    assert snapshot() == first, 'Callback slots depend on the stubbed fallback value'
    records = []
    for i in slots:
        row = {'identifier': i}
        for label, table in (('emit', 0x388), ('lookup', 0x7b0)):
            opd = lib.word(base + table + i * 4)
            assert opd and opd + 8 < 0x1ff0000
            code, toc = lib.word(opd), lib.word(opd + 4)
            assert code == expected[i][label == 'lookup'] and toc == 0x133bc58
            row[label] = {'opd': f'{opd:08x}', 'code': f'{code:08x}', 'toc': f'{toc:08x}'}
        records.append(row)
    for which in (0, 1):
        for value in (0, 1, 0x12345678, 0x80000000, 0xffffffff):
            assert lib.lookup(which, value) == value
    report = {'elf_sha256': digest, 'registry_base': f'{base:08x}',
              'scope': 'Isolated initializer and two lookup handlers; fallback stubbed; emit callbacks not executed',
              'lookup_checks': 10, 'records': records}
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print('Evidence:', folder / 'report.json')


if __name__ == '__main__':
    main()
