"""Resolve disc-build global callback slots using an isolated local initializer.

No gameplay starts. Extracted game code, ELF bytes and results stay in ignored
scratch. Global emit checks use controlled resource providers, never game assets.
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
from shader_material_textures import sampler_register, with_global_sampler_path


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
        'ppc_rotl64', 'ppc_mask64', 'ppc_rlw64', 'ppc_rldicl', 'ppc_rldicr', 'ppc_sraw',
        'ppu_f2i64', 'ppu_fp_quiet', 'ppu_fp_default_qnan', 'ppu_fp_bin',
        'ppu_fmul', 'ppu_fp_single', 'ppu_frsp'))
    snippets += '\n' + extract(libc, 'func_00C11F10')
    snippets += '\n' + extract(source, 'func_00830050')
    handlers = (args.generated / 'ppu_recomp_009.cpp').read_text()
    snippets += '\n' + '\n'.join(extract(handlers, n) for n in (
        'func_00D6DE78', 'func_00D6DE98', 'func_00D77C20', 'func_00D77CC0', 'func_00D77A90',
        'func_00D6CAA0', 'func_00D6D930', 'func_00D6D898', 'func_00D6D9C0'))
    snippets += '\n' + extract(source, 'func_0082C748')
    snippets += '\n' + extract(source, 'func_008103F0')
    snippets += '\n' + '\n'.join(extract(source, n) for n in (
        'func_008293A8', 'func_0082E240', 'func_00705FC0', 'func_0082DF70', 'func_00827DD0'))
    snippets += '\n' + extract(source, 'func_0082E330')
    snippets += '\n' + extract(source, 'func_0081F0F0')
    snippets += '\n' + '\n'.join(extract(libc, n) for n in (
        'func_00BCEBB0', 'func_00BCEE18', 'func_00BCF1B0',
        'func_00BCED48', 'func_00BCEED0', 'func_00BCEBC0',
        'func_00BD2660', 'func_00BD5B88', 'func_00C05D58'))
    wrappers = (args.generated / 'ppu_recomp_007.cpp').read_text()
    snippets += '\n' + '\n'.join(extract(wrappers, n) for n in (
        'func_00BA6998', 'func_00BA6590', 'func_00BA6BD8', 'func_00BA6CF0',
        'func_00BA6B40', 'func_00BA6C68', 'func_00BA6628', 'func_00BA1080', 'func_00B9F1F8'))
    assert 'g_trampoline_fn' not in snippets, 'Isolated routines must not schedule trampolines'
    prefix = '''#define PPU_NO_INLINE_LOADS
#define PPU_NO_INLINE_STORES
#include "ppu_recomp.h"
#include <string.h>
#include <assert.h>
#include <math.h>
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
static uint32_t allocation_success;
// Allocation boundary is controlled; the sampler-writing helper stays real.
void func_00BA08B8(ppu_context* ctx) {
 if(!allocation_success) {ctx->gpr[3]=0;return;}
 uint32_t a=ctx->gpr[3];vm_write32(a,7);vm_write32(a+4,0x1000);
 vm_write32(a+0x10,ctx->gpr[7] ? ctx->gpr[7] : 1);vm_write32(a+0x24,0);
 ctx->gpr[3]=1;
}
void func_00B9EE50(ppu_context* ctx) { ctx->gpr[3]=6; }
void func_00BD0080(ppu_context* ctx) { ctx->gpr[3]=0x1000; }
void func_00BCB520(ppu_context* ctx) { ctx->gpr[3]=0x2000; }
static uint32_t mirror_mode;
void func_00705020(ppu_context* ctx) { ctx->gpr[3]=0x1e62000; }
void func_00712F30(ppu_context* ctx) {}
void func_0080EC50(ppu_context* ctx) {}
void func_00811B70(ppu_context* ctx) { ctx->gpr[3]=0; }
void func_00815870(ppu_context* ctx) {}
void func_0082D068(ppu_context* ctx) {} // Plane normalization, no descriptor access.
void func_00C064F8(ppu_context* ctx) {
 uint32_t d=ctx->gpr[3],s=ctx->gpr[4],n=ctx->gpr[5];bounds(d,n);bounds(s,n);
 memmove(memory+d,memory+s,n);
}
static uint32_t provider;
void func_008311A0(ppu_context* ctx) { provider=103;ctx->gpr[3]=0x1e00000; }
void func_00830FC0(ppu_context* ctx) { provider=104;ctx->gpr[3]=0x1e00000; }
void func_00811BD0(ppu_context* ctx) { ctx->gpr[3]=0x1e39000; }
void func_00811D58(ppu_context* ctx) { ctx->gpr[3]=mirror_mode ? 0x1e61000 : 0; }
void func_00811D48(ppu_context* ctx) { ctx->gpr[3]=0; }
void func_00811D28(ppu_context* ctx) {}
void func_00811D38(ppu_context* ctx) {}
void func_00811BE0(ppu_context* ctx) {}
void func_0082E430(ppu_context* ctx) {}
void func_0082E488(ppu_context* ctx) {}
void func_008343D0(ppu_context* ctx) {}
void func_008343F0(ppu_context* ctx) {}
void func_008389F0(ppu_context* ctx) {}
void func_00810CD8(ppu_context* ctx) {}
void func_00BC8360(ppu_context* ctx) {}
void func_00BC84F8(ppu_context* ctx) {}
void func_00BCE538(ppu_context* ctx) {}
void func_00BCFEF8(ppu_context* ctx) {}
void func_00BCFFA0(ppu_context* ctx) {}
void ps3_indirect_call(ppu_context* ctx) {
 if(mirror_mode) {
  if(ctx->ctr==3 || ctx->ctr==4) return; // Viewport setup / scene rendering.
  if(ctx->ctr==5) {func_00827DD0(ctx);return;}
  if(ctx->ctr==6) {func_008293A8(ctx);return;}
  assert(!"Unsupported mirror virtual call");
 }
 assert(ctx->ctr==1 || ctx->ctr==2);
 ctx->gpr[3]=(ctx->ctr==2) ? 0x1e32000 : 0x1e02000;
}
'''
    suffix = '''
extern "C" __declspec(dllexport) void load(uint32_t a,const void* p,uint32_t n) {
 bounds(a,n);memcpy(memory+a,p,n);
}
extern "C" __declspec(dllexport) uint32_t word(uint32_t a) { return vm_read32(a); }
extern "C" __declspec(dllexport) void environment_setup(uint32_t mips,uint32_t slot,uint32_t unit,uint32_t poison,uint32_t success) {
 assert(slot<4 && unit<16);
 ppu_context ctx={0};ctx.gpr[1]=0x1ff0000;ctx.gpr[2]=0x133bc58;
 allocation_success=success;
 const uint32_t object=0x1e50000, texture=object+0x2c, descriptor=object+0x54;
 for(uint32_t j=0;j<0x90;j+=4) vm_write32(object+j,poison);
 vm_write32(object+4,64);vm_write32(object+8,32);
 ctx.gpr[3]=texture;ctx.gpr[4]=64;ctx.gpr[5]=32;ctx.gpr[6]=7;
 ctx.gpr[7]=mips;ctx.gpr[8]=0;ctx.gpr[9]=0;ctx.gpr[10]=0;
 func_00BA1080(&ctx);
 if(!success) {assert(ctx.gpr[3]==0);return;}
 assert(ctx.gpr[3]==1);
 ctx.gpr[3]=object;func_008293A8(&ctx);assert(ctx.gpr[3]==descriptor);
 uint32_t root=vm_read32(ctx.gpr[2]-0x66f8), registry=vm_read32(root-0x8000);
 vm_write32(vm_read32(ctx.gpr[2]-0x66fc)-0x8000,0x1e51000);
 vm_write32(0x1e51000,17);
 ctx.gpr[3]=registry;ctx.gpr[4]=descriptor;ctx.gpr[5]=slot;func_0082E240(&ctx);
 assert(vm_read32(registry+0x1c34+slot*4)==descriptor);
 assert(vm_read32(registry+0x1ca0+slot*4)==18 && vm_read32(0x1e51000)==18);
 uint32_t copy_state=vm_read32(ctx.gpr[2]-0x48bc);vm_write32(copy_state+8,0x1e10000);
 vm_write16(0x1e01006,unit);vm_write8(0x1e0100d,slot);ctx.gpr[4]=0x1e01000;
 func_00D6CAA0(&ctx);assert(vm_read32(copy_state+8)==0x1e10034);
}
extern "C" __declspec(dllexport) void mirror_pass(uint32_t address,uint32_t filtering,uint32_t unit,uint32_t divisor) {
 assert(unit<16 && divisor>0);
 ppu_context ctx={0};ctx.gpr[1]=0x1ff0000;ctx.gpr[2]=0x133bc58;
 const uint32_t source=0x1e50000,descriptor=source+0x54;
 for(uint32_t j=0;j<13;j++) vm_write32(descriptor+j*4,0x12340000+j);
 vm_write32(descriptor,0x201a00);vm_write32(descriptor+0xc,address);
 vm_write32(descriptor+0x18,filtering);vm_write32(source+4,1920);vm_write32(source+8,1080);
 // Synthetic resource vtables dispatch to real descriptor getters.
 vm_write32(source,0x1e66000);vm_write32(0x1e6601c,0x1e67000);
 vm_write32(0x1e66038,0x1e67010);vm_write32(0x1e67000,5);vm_write32(0x1e67004,0x133bc58);
 vm_write32(0x1e67010,6);vm_write32(0x1e67014,0x133bc58);
 vm_write32(0x1e61000,0x1e66000);vm_write32(0x1e60000,0x1e66000);
 vm_write32(0x1e6602c,0x1e67020);vm_write32(0x1e67020,3);vm_write32(0x1e67024,0x133bc58);
 vm_write32(0x1e61004,1920);vm_write32(0x1e61008,1080);
 vm_write32(0x1e39008,0x1e60000);vm_write32(0x1e3901c,source);
 vm_write32(0x1e63000,0);vm_write32(0x1e6306c,divisor);vm_write32(0x1e63018,0x1e64000);
 vm_write32(0x1e64000,0x1e68000);vm_write32(0x1e68000,0x1e67030);
 vm_write32(0x1e67030,4);vm_write32(0x1e67034,0x133bc58);
 uint32_t globals=vm_read32(ctx.gpr[2]-0x7780);
 uint32_t registry=vm_read32(vm_read32(ctx.gpr[2]-0x66f8)-0x8000);
 vm_write32(globals-0x7fa0,0x1e65000);vm_write32(globals-0x7f9c,registry);
 vm_write32(vm_read32(ctx.gpr[2]-0x66fc)-0x8000,0x1e51000);vm_write32(0x1e51000,100);
 vm_write32(0x1e62034,0x3f800000);
 ctx.gpr[3]=0x1e63000;mirror_mode=1;func_00705FC0(&ctx);mirror_mode=0;
 assert(vm_read32(descriptor+0xc)==address && vm_read32(descriptor+0x18)==filtering);
 assert(vm_read32(registry+0x1c48)==0x1e65000 && vm_read32(registry+0x1c98)==101);
 assert(vm_read32(0x1e61004)==1920 && vm_read32(0x1e61008)==1080);
 assert(vm_read32(0x1e60004)==1920 && vm_read32(0x1e60008)==1080);
 assert(vm_read32(0x1e62034)==0x3f800000);
 uint32_t copy_state=vm_read32(ctx.gpr[2]-0x48bc);vm_write32(copy_state+8,0x1e10000);
 vm_write16(0x1e01006,unit);ctx.gpr[4]=0x1e01000;func_00D6D9C0(&ctx);
 assert(vm_read32(copy_state+8)==0x1e10034);
}
extern "C" __declspec(dllexport) void shadow_pass(uint32_t address,uint32_t filtering,uint32_t enabled) {
 ppu_context ctx={0};ctx.gpr[1]=0x1ff0000;ctx.gpr[2]=0x133bc58;
 for(uint32_t j=0;j<13;j++) vm_write32(0x1e02000+j*4,0);
 vm_write32(0x1e02000,0x201a00);vm_write32(0x1e02008,0x18529);
 vm_write32(0x1e0200c,address);vm_write32(0x1e02018,filtering);vm_write32(0x1e0201c,0x400040);
 vm_write32(0x1e33000,0x1e34000);vm_write32(0x1e34038,0x1e35000);
 vm_write32(0x1e35000,1);vm_write32(0x1e35004,0x133bc58);
 vm_write32(0x1e36000,0x1e37000);vm_write32(0x1e37010,0x1e38000);
 vm_write32(0x1e38000,2);vm_write32(0x1e38004,0x133bc58);
 vm_write32(0x1e39018,0x1e33000);
 vm_write32(vm_read32(ctx.gpr[2]-0x66fc)-0x7ff4,0x1e3c000);
 vm_write32(vm_read32(ctx.gpr[2]-0x6784)-0x8000,0x1e3d000);
 vm_write8(0x1e3921c,enabled ? 0 : 1);vm_write8(0x1e36012,0);
 ctx.gpr[3]=0x1e36000;ctx.gpr[4]=0x1e3a000;
 func_008103F0(&ctx);
 if(enabled) assert(vm_read32(0x1e3d000+0x1c44)==0x1e02000);
}
extern "C" __declspec(dllexport) void dynamic_emit(uint32_t identifier,uint32_t unit,uint32_t address,uint32_t filtering,uint32_t present) {
 assert(unit<16);
 ppu_context ctx={0};ctx.gpr[1]=0x1ff0000;ctx.gpr[2]=0x133bc58;
 uint32_t root=vm_read32(ctx.gpr[2]-0x66f8), object=vm_read32(root-0x8000);
 uint32_t copy_state=vm_read32(ctx.gpr[2]-0x48bc);vm_write32(copy_state+8,0x1e10000);
 uint32_t descriptor=0x1e02000;
 for(uint32_t j=0;j<13;j++) vm_write32(descriptor+j*4,0x12340000+j);
 vm_write32(descriptor,0x201a00);vm_write32(descriptor+0xc,address);
 vm_write32(descriptor+0x18,filtering);
 vm_write32(object+0x1c34,present ? descriptor : 0);
 vm_write32(object+0x1c44,present ? descriptor : 0);
 vm_write32(object+0x1c48,present ? descriptor : 0);
 vm_write32(vm_read32(ctx.gpr[2]-0x66fc)-0x7ff4,present ? descriptor : 0);
 vm_write16(0x1e01006,unit);vm_write8(0x1e0100d,0);ctx.gpr[4]=0x1e01000;
 if(identifier==71) func_00D6CAA0(&ctx);
 else if(identifier==87) func_00D6D930(&ctx);
 else if(identifier==96) func_00D6D898(&ctx);
 else if(identifier==115) func_00D6D9C0(&ctx);
 else assert(!"Unsupported dynamic identifier");
 assert(vm_read32(copy_state+8)==0x1e10034);
}
extern "C" __declspec(dllexport) uint32_t emit(uint32_t identifier,uint32_t unit,uint32_t width,uint32_t address,uint32_t active) {
 assert(unit<16 && width>0 && width<4096);
 ppu_context ctx={0};ctx.gpr[1]=0x1ff0000;ctx.gpr[2]=0x133bc58;
 uint32_t root=vm_read32(ctx.gpr[2]-0x66f8);
 vm_write8(vm_read32(root-0x7fd0),active);
 uint32_t state=vm_read32(ctx.gpr[2]-0x4948);
 vm_write32(state+8,0x1e10000);
 uint32_t copy_state=vm_read32(ctx.gpr[2]-0x48bc);vm_write32(copy_state+8,0x1e10000);
 vm_write32(0x1e00004,address);vm_write32(0x1e00010,width);vm_write32(0x1e00020,1);
 vm_write16(0x1e01006,unit);ctx.gpr[4]=0x1e01000;provider=0;
 if(identifier==103) func_00D77C20(&ctx);
 else if(identifier==94) func_00D77CC0(&ctx);
 else if(identifier==104) func_00D77A90(&ctx);
 else assert(!"Unsupported emit identifier");
 assert(vm_read32((active ? state : copy_state)+8)==(active ? 0x1e1003c : 0x1e10034));
 return provider;
}
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
    lib.emit.argtypes = [ctypes.c_uint32] * 5
    lib.emit.restype = ctypes.c_uint32
    lib.mirror_pass.argtypes = [ctypes.c_uint32] * 4
    lib.environment_setup.argtypes = [ctypes.c_uint32] * 5
    lib.dynamic_emit.argtypes = [ctypes.c_uint32] * 5
    lib.shadow_pass.argtypes = [ctypes.c_uint32] * 3
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
    emitted = []
    for active in (0, 1):
        for identifier in (94, 103, 104):
            for unit in range(16):
                for width, address in ((16, 0x1000), (32, 0x2000), (128, 0x3000)):
                    expected_provider = (104 if identifier == 104 else 103) if active else 0
                    assert lib.emit(identifier, unit, width, address, active) == expected_provider
                    commands = [lib.word(0x1e10000 + j * 4) for j in range(15 if active else 13)]
                    assert commands[0] == 0x201a00 + unit * 32
                    name, kind = ('shadowPCFMap', 0x801) if identifier == 104 else ('ditherMap', 0x601 if identifier == 94 else 0x801)
                    definition = dict(bindings=[], globals=[dict(name=name, kind=kind, identifier=identifier, unit=unit)])
                    binding = with_global_sampler_path(definition, 'active' if active else 'fallback')['bindings'][0]
                    assert (commands[3], commands[6]) == (binding['address'], binding['filtering'])
                    assert sampler_register(commands[3], commands[6]) == binding['sampler']
                    facts = binding['texture_facts']
                    assert (commands[2] >> 4) & 15 == 2 and not commands[2] & 4
                    assert facts['shape'] == '2d'
                    assert facts['gamma'] == bool((commands[3] >> 20) & 7)
                    assert facts['unnormalized'] == bool(commands[2] & 0x4000)
                    emitted.append({'identifier': identifier, 'unit': unit, 'width': width,
                                    'active': bool(active), 'resource_address': address, 'words': commands})
    dynamic_checks = 0
    for identifier in (71, 87, 96, 115):
        for unit in range(16):
            for address in (0x101, 0x303, 0x301, 0x103):
                for filtering in (0x01012000, 0x02022000, 0x02062000, 0x01052000):
                    lib.dynamic_emit(identifier, unit, address, filtering, 1)
                    commands = [lib.word(0x1e10000 + j * 4) for j in range(13)]
                    assert commands[0] == 0x201a00 + unit * 32
                    assert commands[9] == 0x41840 + unit * 4
                    for j in range(13):
                        if j not in (0, 3, 6, 9):
                            assert commands[j] == 0x12340000 + j
                    assert commands[3] == address and commands[6] == filtering
                    dynamic_checks += 1
            lib.dynamic_emit(identifier, unit, 0, 0, 0)
            assert lib.word(0x1e1000c) == 0x60010101
            assert lib.word(0x1e10018) == 0x02022000
            dynamic_checks += 1
    shadow_checks = 0
    for address in (0, 0x101, 0x303, 0xffffffff):
        for minimum in range(8):
            for magnify in range(8):
                filtering = (minimum << 16) | (magnify << 24) | 0x2000
                lib.shadow_pass(address, filtering, 0)
                assert lib.word(0x1e0200c) == address and lib.word(0x1e02018) == filtering
                lib.shadow_pass(address, filtering, 1)
                actual_address, actual_filter = lib.word(0x1e0200c), lib.word(0x1e02018)
                assert actual_address & 0xf0f == 0x404
                assert (actual_filter >> 16) & 7 == 2 and (actual_filter >> 24) & 7 == 2
                assert sampler_register(actual_address, actual_filter) == 9
                assert sampler_register(lib.word(0x1e3c00c), lib.word(0x1e3c018)) == 9
                for name, identifier in (('realTimeShadowMap', 87), ('realTimeShadowMapColor', 96)):
                    d = dict(bindings=[], globals=[dict(name=name, kind=0x601, identifier=identifier, unit=13)])
                    b = with_global_sampler_path(d, shadow_path='shadow-lv')['bindings'][0]
                    assert actual_address & b['address_mask'] == b['address']
                    assert actual_filter & b['filtering_mask'] == b['filtering']
                    assert b['sampler'] == 9
                shadow_checks += 1
    environment_checks = 0
    environment_failures = 0
    environment_states = {}
    for mips in (1, 2, 4, 8):
        path = 'framebuffer-single' if mips == 1 else 'framebuffer-mipped'
        for slot in range(4):
            for unit in range(16):
                for poison in (0, 0xffffffff, 0x01012000, 0x02062000):
                    lib.environment_setup(mips, slot, unit, poison, 0)
                    assert lib.word(0x1e50060) == poison and lib.word(0x1e5006c) == poison
                    environment_failures += 1
                    lib.environment_setup(mips, slot, unit, poison, 1)
                    address, filtering = lib.word(0x1e1000c), lib.word(0x1e10018)
                    d = dict(bindings=[], globals=[dict(name='envMapSampler', kind=0x901, identifier=71, unit=unit)])
                    b = with_global_sampler_path(d, environment_path=path)['bindings'][0]
                    assert address & b['address_mask'] == b['address']
                    assert filtering & b['filtering_mask'] == b['filtering']
                    assert sampler_register(address, filtering) == b['sampler']
                    environment_checks += 1
                    environment_states[path] = dict(address=address, filtering=filtering, sampler=b['sampler'])
    mirror_definition = dict(bindings=[], used=1, globals=[dict(name='mirrorMapSampler', kind=0x601, identifier=115, unit=0)])
    mirror_binding = with_global_sampler_path(mirror_definition, mirror_path='scene-copy')['bindings'][0]
    assert mirror_binding['sampler_mask'] == 12 and mirror_binding['address_mask'] == 0
    mirror_checks = 0
    mirror_examples = []
    for address in (0x101, 0x303, 0x103, 0x301):
        for minimum in range(8):
            for magnify in range(8):
                filtering = minimum << 16 | magnify << 24 | 0x2000
                for unit in range(16):
                    lib.mirror_pass(address, filtering, unit, 2)
                    actual_address, actual_filter = lib.word(0x1e1000c), lib.word(0x1e10018)
                    assert actual_address & 0xf0f == address & 0xf0f
                    assert actual_filter & mirror_binding['filtering_mask'] == mirror_binding['filtering']
                    assert sampler_register(actual_address, actual_filter) & mirror_binding['sampler_mask'] == mirror_binding['sampler']
                    assert sampler_register(actual_address, actual_filter) == sampler_register(address, 0x02020000)
                    if minimum==0 and magnify==0 and unit==0:
                        mirror_examples.append(dict(input_address=address, input_filtering=filtering,
                                                    emitted_address=actual_address, emitted_filtering=actual_filter))
                    mirror_checks += 1
    report = {'elf_sha256': digest, 'registry_base': f'{base:08x}',
              'scope': 'Isolated callbacks, ShadowLV pass and framebuffer setup; render/scene/allocation helpers mocked; synthetic resources',
              'dynamic_descriptor_checks': dynamic_checks,
              'mirror_scene_copy_checks': mirror_checks,
              'mirror_examples': mirror_examples,
              'mirror_scope': 'Real consumer/copy getter/framebuffer getter/setter/emitter; scene render and plane normalization mocked',
              'environment_framebuffer_checks': environment_checks,
              'environment_allocation_failure_checks': environment_failures,
              'environment_examples': environment_states,
              'environment_scope': 'Real successful texture setup/getter/assignment/emitter; allocation boundary mocked; no later overrides',
              'shadow_lv_pass_checks': shadow_checks,
              'lookup_checks': 10, 'emit_checks': len(emitted), 'emitted': emitted, 'records': records}
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'emitted'}, indent=2))
    print('First emitted state per identifier/path:', [(i, active, next(r['words'] for r in emitted if r['identifier'] == i and r['active'] == active)) for active in (False, True) for i in (94, 103, 104)])
    print('Evidence:', folder / 'report.json')


if __name__ == '__main__':
    main()
