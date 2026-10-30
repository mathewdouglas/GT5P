"""Validate named-bank selection against isolated lifted lookup/bind routines.

Original bytes and extracted code remain in ignored scratch. No game starts.
Only libc string comparison and the final GPU program upload are intercepted.
"""
import argparse
import ctypes
import hashlib
import json
import random
from pathlib import Path
import struct
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_shared_passes import bank_pairs
from shader_shared_profiles import colour_correct_descriptor, convolution_descriptor
from shader_material_prepare_native import extract


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--generated', type=Path, required=True)
    ap.add_argument('--elf', type=Path, required=True)
    args = ap.parse_args()
    data = args.elf.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != '8ee3523e8c05d6a27d3cc32f6caeb530059473e8b9ae04ad92fdbfb677603036':
        raise ValueError('Unsupported disc ELF')
    folder = Path(__file__).resolve().parents[2] / 'scratch' / ('shared-pass-native-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    source = (args.generated / 'ppu_recomp_005.cpp').read_text()
    snippets = '\n'.join(extract(source, n) for n in (
        'ppc_rotl64', 'ppc_mask64', 'ppc_rlw64', 'ppc_rldicl', 'ppc_rldicr', 'ppc_sraw', 'ppc_rldimi',
        'ppu_fp_quiet', 'ppu_fp_default_qnan', 'ppu_fp_bin', 'ppu_fp_single',
        'ppu_fdiv', 'ppu_fadd', 'ppu_fmul', 'ppu_fmadd_core', 'ppu_frsp',
        'func_00832920', 'func_008329A8', 'func_00832A50', 'func_00832BC8',
        'func_00831B78', 'func_00833290', 'func_0081FDA8', 'func_00827DD0', 'func_00823F28', 'func_00820A28', 'func_00820C08'))
    libc = (args.generated / 'ppu_recomp_008.cpp').read_text()
    snippets += '\n' + '\n'.join(extract(libc, 'func_' + n) for n in (
        '00BC5540', '00BCFD90', '00BCFFA0', '00BCFEF8', '00BCC3A0', '00BDE360',
        '00BD2660', '00BD5B88', '00C05D58'))
    snippets += '\n' + extract((args.generated / 'ppu_recomp_007.cpp').read_text(), 'func_00BA6CF0')
    prefix = '''#define PPU_NO_INLINE_LOADS
#define PPU_NO_INLINE_STORES
#include "ppu_recomp.h"
#include <string.h>
#include <assert.h>
#include <math.h>
#include <stdio.h>
#define PPU_MM_SNAP
#define DRAIN_TRAMPOLINE(ctx) do {while(g_trampoline_fn) {void(*next)(void*)=g_trampoline_fn;g_trampoline_fn=0;next(ctx);}} while(0)
static unsigned char memory[0x2000000];
static void (*g_trampoline_fn)(void*);
static uint32_t vertex,fragment;
static void bounds(uint64_t a,unsigned n) {assert(a<sizeof memory && n<=sizeof memory-a);}
extern "C" uint8_t vm_read8(uint64_t a) {bounds(a,1);return memory[a];}
extern "C" uint16_t vm_read16(uint64_t a) {return (vm_read8(a)<<8)|vm_read8(a+1);}
extern "C" uint32_t vm_read32(uint64_t a) {return (uint32_t(vm_read16(a))<<16)|vm_read16(a+2);}
extern "C" uint64_t vm_read64(uint64_t a) {return (uint64_t(vm_read32(a))<<32)|vm_read32(a+4);}
extern "C" void vm_write8(uint64_t a,uint8_t v) {bounds(a,1);memory[a]=v;}
extern "C" void vm_write16(uint64_t a,uint16_t v) {vm_write8(a,v>>8);vm_write8(a+1,v);}
extern "C" void vm_write32(uint64_t a,uint32_t v) {vm_write16(a,v>>16);vm_write16(a+2,v);}
extern "C" void vm_write64(uint64_t a,uint64_t v) {vm_write32(a,v>>32);vm_write32(a+4,v);}
void func_00C09258(ppu_context* ctx) {
 uint32_t a=ctx->gpr[3],b=ctx->gpr[4];unsigned i=0;
 for(;i<256 && vm_read8(a+i) && vm_read8(a+i)==vm_read8(b+i);i++) {} assert(i<256);
 ctx->gpr[3]=(int32_t)vm_read8(a+i)-(int32_t)vm_read8(b+i);
}
void func_00833268(ppu_context* ctx) {vertex=ctx->gpr[3];}
void func_00832790(ppu_context* ctx) {fragment=ctx->gpr[3];}
static unsigned draws,callbacks;
static unsigned resource_mode;
void func_0081FCD0(ppu_context* ctx) {ctx->gpr[3]=0x10000;}
void func_00832840(ppu_context* ctx) {ctx->gpr[3]=0x1e28000;}
void func_00832878(ppu_context* ctx) {ctx->gpr[3]=0;}
void func_00833E50(ppu_context* ctx) {}
void func_00833908(ppu_context* ctx) {}
void func_00B5DEB0(ppu_context* ctx) {
 char format[64],text[64];unsigned i=0;
 for(;i<63 && vm_read8(ctx->gpr[4]+i);i++)format[i]=vm_read8(ctx->gpr[4]+i);
 format[i]=0;assert(!strcmp(format,"Convolution_%d"));
 int n=snprintf(text,sizeof text,"Convolution_%d",(int)ctx->gpr[5]);assert(n>0 && n<64);
 for(int j=0;j<=n;j++)vm_write8(ctx->gpr[3]+j,text[j]);
}
void func_00BC84F8(ppu_context* ctx) {}
void func_00BC8478(ppu_context* ctx) {}
void func_00BC7BE0(ppu_context* ctx) {}
void func_00BC5C40(ppu_context* ctx) {}
void func_00BC5698(ppu_context* ctx) {draws++;}
void func_00BC83D0(ppu_context* ctx) {}
void func_00BCFCE0(ppu_context* ctx) {}
void func_00BCFCB0(ppu_context* ctx) {draws++;}
void func_00BD3670(ppu_context* ctx) {}
void func_00BD3518(ppu_context* ctx) {}
void func_00BD3608(ppu_context* ctx) {}
void func_00C064F8(ppu_context* ctx) {
 bounds(ctx->gpr[3],ctx->gpr[5]);bounds(ctx->gpr[4],ctx->gpr[5]);
 memmove(memory+ctx->gpr[3],memory+ctx->gpr[4],ctx->gpr[5]);
}
void ps3_indirect_call(ppu_context* ctx) {
 if(resource_mode && ctx->ctr==1) {func_00827DD0(ctx);return;}
 if(resource_mode && ctx->ctr==3) {ctx->gpr[3]=0x1e27000;return;}
 if(ctx->ctr==1) {for(unsigned i=0;i<32;i+=4)vm_write32(ctx->gpr[3]+i,0);return;}
 // Target activation and the selected gamma callback remain controlled boundaries.
 assert(ctx->gpr[3]==0x1fec || ctx->ctr==2);callbacks++;
 if(resource_mode && ctx->ctr==0xbcfd90)func_00BCFD90(ctx);
 else if(resource_mode && ctx->ctr==0xbc5540)func_00BC5540(ctx);
}
'''
    suffix = '''
extern "C" __declspec(dllexport) void load(uint32_t a,const void* p,uint32_t n) {bounds(a,n);memcpy(memory+a,p,n);}
extern "C" __declspec(dllexport) uint32_t vertex_mask(uint32_t mask,uint32_t poison) {
 ppu_context ctx={0};ctx.gpr[3]=0x1e70000;ctx.gpr[4]=0x1e26000;
 for(unsigned i=0;i<32;i+=4)vm_write32(ctx.gpr[4]+i,poison);
 vm_write16(ctx.gpr[4]+0x16,0);vm_write32(ctx.gpr[4]+4,mask);vm_write32(ctx.gpr[3]+8,0x1e71000);
 func_00BDE360(&ctx);assert(vm_read32(0x1e71008)==0x81ff0);return vm_read32(0x1e7100c);
}
extern "C" __declspec(dllexport) uint32_t select_pair(uint32_t bank,uint32_t name,uint32_t tag,uint32_t* out) {
 ppu_context ctx={0};ctx.gpr[1]=0x1ff0000;ctx.gpr[3]=bank;ctx.gpr[4]=name;ctx.gpr[5]=tag;
 vertex=fragment=0;g_trampoline_fn=0;func_00832BC8(&ctx);uint32_t record=ctx.gpr[3];
 ctx.gpr[3]=bank;ctx.gpr[4]=record;func_00833290(&ctx);
 if(g_trampoline_fn) {assert(g_trampoline_fn==(void(*)(void*))func_00832790);func_00832790(&ctx);}
 out[0]=vertex;out[1]=fragment;return record;
}
static void setup(ppu_context& ctx,unsigned poison) {
 ctx={};ctx.gpr[1]=0x1ff0000;ctx.gpr[2]=0x133bc58;
 for(unsigned i=0;i<0x600;i+=4)vm_write32(0x1e70000+i,poison);
 const int offsets[]={0x4c10,0x4918,0x491c,0x49e8,0x4920};
 for(int offset : offsets)vm_write32(ctx.gpr[2]-offset,0x1e70000);
 vm_write32(0x1e70008,0x1e71000);vm_write32(0x1e70530,0);
 vm_write32(ctx.gpr[2]-0x48bc,0x1e81000);vm_write32(0x1e81008,0x1e80000);
 vm_write16(0x1e28006,0);
 vm_write32(ctx.gpr[2]-0x6724,0x12910dc);
 for(unsigned i=0;i<32;i+=4)vm_write32(0x1e21000+i,64);
 vm_write32(0x1e21000,0x1e23000);vm_write32(0x1e22000,0x1e23000);
 vm_write32(0x1e2301c,0x1e24000);vm_write32(0x1e24000,1);vm_write32(0x1e24004,ctx.gpr[2]);
 vm_write32(0x1e23010,0x1e24010);vm_write32(0x1e24010,2);vm_write32(0x1e24014,ctx.gpr[2]);
 vm_write32(0x1e23038,0x1e24020);vm_write32(0x1e24020,3);vm_write32(0x1e24024,ctx.gpr[2]);
}
extern "C" __declspec(dllexport) unsigned colour_state(unsigned same,unsigned gamma,unsigned mode,unsigned poison,uint32_t* out) {
 ppu_context ctx;setup(ctx,poison);
 ctx.gpr[3]=same ? 0x1e21000 : 0x1e22000;ctx.gpr[4]=0x1e21000;
 ctx.gpr[5]=0x1e25000;ctx.gpr[6]=ctx.gpr[7]=0x1e25000;ctx.gpr[9]=gamma;ctx.gpr[10]=mode;ctx.fpr[1]=1;
 draws=callbacks=vertex=fragment=0;func_0081FDA8(&ctx);assert(draws==1 && callbacks==2);
 out[0]=vertex;out[1]=fragment;
 unsigned end=vm_read32(0x1e70008),n=(end-0x1e71000)/4;assert(n<=64);
 for(unsigned i=0;i<n;i++)out[2+i]=vm_read32(0x1e71000+i*4);return n;
}
extern "C" __declspec(dllexport) void colour_resource(unsigned same,unsigned gamma,unsigned mode,unsigned poison,const uint32_t* input,uint32_t* output) {
 for(unsigned i=0;i<13;i++)vm_write32(0x1e27000+i*4,input[i]);
 resource_mode=1;uint32_t commands[66];unsigned n=colour_state(same,gamma,mode,poison,commands);resource_mode=0;
 for(unsigned i=0;i<13;i++)output[i]=vm_read32(0x1e80000+4*i);
 output[13]=0xffffffff;
 for(unsigned i=2;i+1<n+2;i+=2)if(commands[i]==0x41fec)output[13]=commands[i+1];
 assert(output[13]!=0xffffffff);
}
extern "C" __declspec(dllexport) unsigned convolution_resource(unsigned record,unsigned gamma,unsigned taps,unsigned poison,const uint32_t* input,uint32_t* output) {
 ppu_context ctx;setup(ctx,poison);
 for(unsigned i=0;i<13;i++)vm_write32(0x1e27000+i*4,input[i]);
 ctx.gpr[3]=0x1e29000;ctx.gpr[4]=taps;func_00820A28(&ctx);assert(vm_read32(0x1e29000)==record);
 ctx.gpr[3]=0x1e22000;ctx.gpr[4]=0x1e27000;ctx.gpr[5]=0x1e25000;
 ctx.gpr[6]=gamma;ctx.gpr[7]=ctx.gpr[8]=0x1e25000;ctx.gpr[9]=0x1e29000;ctx.gpr[10]=taps;
 resource_mode=1;draws=callbacks=vertex=fragment=0;func_00820C08(&ctx);resource_mode=0;
 assert(draws==1 && callbacks==2);
 for(unsigned i=0;i<13;i++)output[i]=vm_read32(0x1e80000+4*i);
 output[13]=0xffffffff;output[14]=vertex;output[15]=fragment;
 unsigned n=(vm_read32(0x1e70008)-0x1e71000)/4;assert(n<=64);
 for(unsigned i=0;i<n;i++)output[16+i]=vm_read32(0x1e71000+4*i);
 for(unsigned i=16;i+1<n+16;i+=2)if(output[i]==0x41fec)output[13]=output[i+1];
 assert(output[13]!=0xffffffff);return n;
}
'''
    (folder / 'oracle.cpp').write_text(prefix + snippets + suffix)
    vcvars = 'C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'
    command = ('@echo off\ncall "' + vcvars + '" >nul\nif errorlevel 1 exit /b 1\n'
               '"C:/Program Files/LLVM/bin/clang-cl.exe" /nologo /O2 /MD /LD /I"' +
               str(args.generated.resolve()) + '" /Fo"' + str(folder / 'oracle.obj') +
               '" /Fe"' + str(folder / 'oracle.dll') + '" "' + str(folder / 'oracle.cpp') + '"\n')
    (folder / 'build.cmd').write_text(command)
    subprocess.run(['cmd', '/c', str(folder / 'build.cmd')], cwd=folder, check=True)
    dll = ctypes.CDLL(str(folder / 'oracle.dll'))
    dll.load.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    dll.select_pair.argtypes = [ctypes.c_uint32] * 3 + [ctypes.POINTER(ctypes.c_uint32)]
    dll.select_pair.restype = ctypes.c_uint32
    dll.colour_state.argtypes = [ctypes.c_uint32] * 4 + [ctypes.POINTER(ctypes.c_uint32)]
    dll.colour_state.restype = ctypes.c_uint32
    dll.colour_resource.argtypes = [ctypes.c_uint32] * 4 + [ctypes.POINTER(ctypes.c_uint32)] * 2
    dll.convolution_resource.argtypes = [ctypes.c_uint32] * 4 + [ctypes.POINTER(ctypes.c_uint32)] * 2
    dll.convolution_resource.restype = ctypes.c_uint32
    dll.vertex_mask.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    dll.vertex_mask.restype = ctypes.c_uint32
    mask_checks = 0
    for mask in (0, 1, 9, 0x101, 0xffff, 0x10000, 0xffffffff):
        for poison in (0, 0xffffffff, 0xa5a5a5a5):
            assert dll.vertex_mask(mask, poison) == mask
            mask_checks += 1
    # This disc's loaded regions use file offset + 0x10000. Private memory only.
    dll.load(0x10000, data, len(data))
    reports, checks = [], 0
    # The texture-UI bank at 0x1344900 uses another vertex wrapper; fail closed.
    try:
        bank_pairs(data, 0x1344900)
    except ValueError as exc:
        assert str(exc) == 'invalid vertex wrapper'
    else:
        raise AssertionError('unsupported UI wrapper accepted')
    for base in (0x1328680, 0x134a580, 0x134d400):
        pairs = bank_pairs(data, base)
        for pair in pairs:
            assert dll.vertex_mask(pair['vertex_input_mask'], 0xa5a5a5a5) == pair['vertex_input_mask']
            mask_checks += 1
        size = struct.unpack_from('>I', data, base + 4)[0]
        image = bytearray(data[base:base + size])
        # Relocate only the table/name pointers read by these routines. Upload
        # boundaries inspect record addresses; shader payloads are never executed.
        address = 0x10000
        for offset in (0x1c, 0x20, 0x2c):
            struct.pack_into('>I', image, offset, struct.unpack_from('>I', image, offset)[0] + address)
        for p in pairs:
            entry = p['record'] - base
            struct.pack_into('>I', image, entry, struct.unpack_from('>I', image, entry)[0] + address)
        dll.load(address, bytes(image), len(image))
        for p in pairs:
            query = p['name'].encode() + b'\0'
            dll.load(0x1e00000, query, len(query))
            output = (ctypes.c_uint32 * 2)()
            record = dll.select_pair(address, 0x1e00000, p['tag'], output)
            assert record == address + p['record'] - base
            vt, ft = (struct.unpack_from('>I', data, base + o)[0] for o in (0x20, 0x2c))
            assert list(output) == [address + vt + p['vertex_index'] * 40, address + ft + p['fragment_index'] * 72]
            checks += 1
            # Same string with an absent tag must not bind anything.
            assert dll.select_pair(address, 0x1e00000, 0xffffffff, output) == 0
            assert list(output) == [0, 0]
            checks += 1
        for query in (b'\0', b'!absent\0', b'zzzz-absent\0', b'ColorCorrectx\0'):
            dll.load(0x1e00000, query, len(query))
            output = (ctypes.c_uint32 * 2)()
            assert dll.select_pair(address, 0x1e00000, 0, output) == 0
            assert list(output) == [0, 0]
            checks += 1
        reports.append(dict(bank=base, pairs=len(pairs), names=[p['name'] for p in pairs]))
    colour = next(p for p in pairs if p['name'] == 'ColorCorrect')
    state_checks = 0
    expected = [0x40324, 0x01010101, 0x40370, 0xfff0, 0x40a70, 0,
                0x40328, 0, 0x40348, 0, 0x40304, 0, 0x40a74, 0,
                0x4183c, 0, 0x40310, 0]
    for same in range(2):
        for gamma in (0, 1, 2, 255):
            for mode in (0, 1, 2, 255):
                for poison in (0, 0xffffffff, 0xa5a5a5a5, 0x12345678):
                    output = (ctypes.c_uint32 * 66)()
                    n = dll.colour_state(same, gamma, mode, poison, output)
                    assert list(output)[2:2+n][:len(expected)] == expected, [hex(v) for v in list(output)[2:2+n]]
                    assert list(output)[2:2+n][-2:] == [0x41d7c, 0xffff0000 | int(bool(poison))]
                    assert output[0] == 0x10000 + vt + colour['vertex_index'] * 40
                    assert output[1] == 0x10000 + ft + colour['fragment_index'] * 72
                    state_checks += 1
    rng = random.Random(163)
    resource_checks = 0
    for same in (0, 1):
        for mode in (0, 1, 2, 255, 256, 0xffffffff):
            for gamma in (0, 1, 2, 0xffffffff):
                for poison in (0, 0xffffffff, 0xa5a5a5a5):
                    for _ in range(8):
                        words = [rng.getrandbits(32) for _ in range(13)]
                        incoming = (ctypes.c_uint32 * 13)(*words)
                        outgoing = (ctypes.c_uint32 * 14)()
                        dll.colour_resource(same, gamma, mode, poison, incoming, outgoing)
                        assert list(outgoing)[:13] == colour_correct_descriptor(words, same, mode)
                        assert outgoing[13] == int(bool(gamma))
                        resource_checks += 1
    convolution = next(p for p in pairs if p['name'] == 'Convolution_8')
    convolution_checks = 0
    for gamma in (0, 1, 2, 255, 0x80000000, 0xffffffff):
        for poison in (0, 0xffffffff, 0xa5a5a5a5):
            for _ in range(32):
                words = [rng.getrandbits(32) for _ in range(13)]
                incoming = (ctypes.c_uint32 * 13)(*words)
                outgoing = (ctypes.c_uint32 * 80)()
                n = dll.convolution_resource(0x10000 + convolution['record'] - base, gamma, 8, poison, incoming, outgoing)
                assert list(outgoing)[:13] == convolution_descriptor(words, gamma)
                assert outgoing[13] == int(bool(gamma))
                assert outgoing[14] == 0x10000 + vt + convolution['vertex_index'] * 40
                assert outgoing[15] == 0x10000 + ft + convolution['fragment_index'] * 72
                assert list(outgoing)[16:16+len(expected)] == expected
                convolution_checks += 1
    report = dict(elf_sha256=digest, checks=checks, colour_state_checks=state_checks, vertex_mask_checks=mask_checks,
                  colour_resource_checks=resource_checks, banks=reports,
                  convolution_checks=convolution_checks,
                  colour_commands=expected,
                  scope='Real lookup, pair indices, framebuffer getter copy, ColorCorrect edits/gamma and texture command emission. Source descriptor provider, target activation, sampler metadata and draw/constant upload boundaries controlled.')
    (folder / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(checks=checks, colour_state_checks=state_checks, report=str(folder / 'report.json'))))


if __name__ == '__main__':
    main()
