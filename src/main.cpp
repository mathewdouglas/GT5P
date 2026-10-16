/**
 * Gran Turismo 5 Prologue Recompiled — entry point
 *
 * Brings up the ps3recomp virtual machine, loads EMAIN.ELF at its own
 * addresses, registers the lifted function table, and calls the guest's
 * entry point.
 *
 * There is deliberately no import resolver here. Every one of this title's
 * 439 import thunks was lifted as `ps3_hle_call(<nid>, ctx)` (the lifter's
 * --hle-stubs path, fed by scripts/gen_hle_stubs.py reading the ELF's own
 * module descriptors), so imports resolve by NID inside the runtime with
 * nothing to patch at load time.
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>                 /* timeBeginPeriod */
#pragma comment(lib, "winmm.lib")
#endif

#include "ps3emu/ps3types.h"
#include "ps3emu/error_codes.h"
#include "ps3emu/module.h"

#include "ppu_context.h"
#include "vm.h"
#include "lv2_syscall_table.h"
#include "sys_ppu_thread.h"   /* g_ppu_threads: the all-threads dump */
#include "sys_mutex.h"        /* g_sys_mutexes: who holds what */

#include "elf_loader.h"
#include "gt5p_settings.h"

/* The lifter's function table, defined in the generated sources. Declared here
 * rather than including generated/ppu_recomp.h: that header defines its own
 * ppu_context, which collides with the runtime's. The two layouts are kept
 * identical by the lifter, and this is the only symbol we need from it. */
extern "C" {
typedef struct { uint64_t addr; void (*func)(ppu_context*); const char* name; } func_entry;
extern const func_entry function_table[];
extern const uint64_t   function_table_count;   /* entries, excluding sentinel */
}

/* Definitions the runtime and the HLE libraries declare extern. */
uint8_t* vm_base = nullptr;
ps3_module_registry g_ps3_module_registry = {};

extern "C" {
void ppu_register_function(uint64_t addr, void (*fn)(ppu_context*));
void ppu_recomp_register(void);           /* installs function_table[] */
void ppu_install_thread_trampoline(void);
void ppu_hle_register_all(void);          /* generated: src/gen/ppu_hle_nids.cpp */
void ppu_sysprx_register(void);
void ps3_install_guest_ptr_trap(void);
unsigned int ps3_hle_count(void);
void cellfs_set_root_path(const char* root);
void cellfs_add_path_mapping(const char* ps3_prefix, const char* host_path);
void cellGame_init_from_paramsfo(const char* sfo_path);
void cellVideoOut_set_resolution(uint8_t resolutionId);   /* cellVideoOut.c */
void vm_write32(uint64_t addr, uint32_t val);   /* big-endian guest store */
uint32_t vm_read32(uint64_t addr);
extern uint32_t ppu_hle_inject_base;      /* HLE-visible GCM window base */
uint32_t ppu_prof_resolve_host(void* ra);  /* host RIP -> guest function addr */
void ppu_ww_dump_tail(void);              /* PPU_WWATCH_TAIL ring, if armed */
int  ppu_stwcx32(uint64_t ea, uint32_t expected, uint32_t val);
void ps3_indirect_call(ppu_context* ctx);
void ps3_hle_call(unsigned nid, ppu_context* ctx);
uint8_t vm_read8(uint64_t addr);
void ppu_guard_page(uint32_t guest_ea);
void vm_write64(uint64_t a, uint64_t v);
void vm_write8(uint64_t a, uint8_t v);
void vm_write16(uint64_t a, uint16_t v);
uint64_t vm_read64(uint64_t a);
extern const char* g_hle_inflight[64];    /* per-thread: HLE currently executing */
void gt5p_spu_register_all(void);         /* generated: src/gen/spu_workloads.c */
void gt5p_start_present_thread(void);     /* src/gt5p_present.cpp */
}

/* RSX local memory, as cellGcmGetConfiguration reports it (cellGcmSys.c). */
#define GT5P_LOCAL_MEM_BASE 0xC0000000u
#define GT5P_LOCAL_MEM_SIZE 0x10000000u

/* GCM control/label page. cellGcmSys keeps put/get/ref and the label slots
 * here, and the RSX pump reads them every frame. */
#define GT5P_GCM_CTRL_BASE  0x03000000u
#define GT5P_GCM_CTRL_SIZE  0x00010000u

/* argv/envp block handed to the guest _start. */
#define GT5P_ARGV_BASE      0x00F00000u

/* Main thread stack. The runtime hands ppu_thread stacks out of its own
 * region at 0xD0000000; main is created by us, so it needs one too. 1 MB
 * matches what lv2 gives a title's primary thread. */
#define GT5P_MAIN_STACK_BASE 0xCFE00000u
#define GT5P_MAIN_STACK_SIZE 0x00100000u

static ppu_context g_main_ctx;

/* How the HLE libraries call back into lifted code (ps3emu/guest_call.h). The
 * runtime leaves the hook NULL and a library that finds it NULL skips its
 * callback without saying so. The disc build needs it at boot:
 * cellGameDataCheckCreate2 hands the title its hard-disk directory through a
 * callback, and without it every path the title built under /dev_hdd0 was
 * missing "game/BCUS98158/USRDIR". Found by comparing against an RPCS3 log. */
extern "C" {
typedef void (*ps3_guest_caller_fn)(uint32_t, uint64_t, uint64_t, uint64_t, uint64_t,
                                    uint64_t, uint64_t, uint64_t, uint64_t);
extern ps3_guest_caller_fn g_ps3_guest_caller;            /* libs/system/cellSysutil.c */
uint64_t ppu_guest_call(uint32_t opd, uint64_t, uint64_t, uint64_t, uint64_t,
                        uint64_t, uint64_t, uint64_t, uint64_t);   /* ppu_loader.cpp */
void spurs_set_synth_job_done(int on);                             /* cellSpurs.c */
}
static void gt5p_guest_caller(uint32_t opd, uint64_t a0, uint64_t a1, uint64_t a2,
                              uint64_t a3, uint64_t a4, uint64_t a5, uint64_t a6,
                              uint64_t a7)
{
    ppu_guest_call(opd, a0, a1, a2, a3, a4, a5, a6, a7);
}

/* The guest context of whichever thread asks (ppu_loader.cpp). */
extern "C" thread_local ppu_context* g_active_ctx;

/* function_table[] is emitted in ascending address order and
 * sentinel-terminated; function_table_count excludes the sentinel. */
static void (*dispatch_lookup(uint32_t guest_addr))(ppu_context*)
{
    uint64_t lo = 0, hi = function_table_count;
    while (lo < hi) {
        uint64_t mid = lo + (hi - lo) / 2;
        uint32_t a = (uint32_t)function_table[mid].addr;
        if (a == guest_addr) return function_table[mid].func;
        if (a < guest_addr) lo = mid + 1; else hi = mid;
    }
    return nullptr;
}

/* Nearest lifted function at or below `addr`, for turning a saved return
 * address back into func_XXXXXXXX+offset. */
static uint32_t enclosing_func(uint32_t addr)
{
    uint64_t lo = 0, hi = function_table_count, best = 0;
    while (lo < hi) {
        uint64_t mid = lo + (hi - lo) / 2;
        uint32_t a = (uint32_t)function_table[mid].addr;
        if (a <= addr) { best = a; lo = mid + 1; } else hi = mid;
    }
    return (uint32_t)best;
}

#ifdef _WIN32
/* GT5P_MAINSTACK=<seconds>: after that long, print the main thread's guest call
 * chain. The lifter's fragment model leaves the ABI back-chain LR slots zero,
 * so walking is useless; scanning the stack for words that land inside a lifted
 * function is not, and a lifted function's name IS its guest address.
 *
 * The runtime has ppu_dump_guest_stack, but it filters to guest < 0x600000 --
 * this title's code runs to 0xBE0AF4, so every address worth seeing here is
 * outside that window. */
#define GT5P_CODE_LO 0x00010000u
#define GT5P_CODE_HI GT5P_CODE_END      /* per build: config/targets.json */

static HANDLE g_main_thread;
static uintptr_t g_last_rip;
static void dump_hostmap(void);

/* GT5P_GUARD=<watch>:<arm>: spin until the guest word at <arm> becomes
 * non-zero, then write-protect <watch>'s page so the runtime's guard handler
 * reports every writer into it.
 *
 * The store watch (LBP_WW) only sees lifted vm_write8/16/32. A 64-bit `std`,
 * an atomic, or a host-side memset lands invisibly -- and this title has a
 * free-list entry whose fields are zeroed at init and read back as -1 with no
 * store in between, which is exactly that shape. */
static DWORD WINAPI guard_arm(LPVOID spec)
{
    uint32_t watch = 0, arm = 0, want = 0;
    int n = sscanf((const char*)spec, "%x:%x:%x", &watch, &arm, &want);
    if (n < 2 || !watch) return 0;
    for (int i = 0; i < 60000 && arm; i++) {
        uint32_t v = vm_read32(arm);
        if (n >= 3 ? (v == want) : (v != 0)) break;
        Sleep(1);
    }
    fprintf(stderr, "[GT5P] arming page guard on 0x%08X ([0x%08X]=0x%08X)\n",
            watch, arm, vm_read32(arm));
    dump_hostmap();
    fflush(stderr);
    ppu_guard_page(watch);
    return 0;
}

/* The page guard reports a writer as a module RVA. Print the RVAs of the
 * runtime entry points a guest store can plausibly come through, so the nearest
 * one below it names the writer without a symbol server. RVAs move between
 * builds, so this has to come from the same run as the guard output. */
static void dump_hostmap(void)
{
    {
        char* mb = (char*)GetModuleHandleA(nullptr);
        struct { const char* n; void* p; } k[] = {
            { "vm_write32",     (void*)&vm_write32     },
            { "vm_read32",      (void*)&vm_read32      },
            { "ppu_stwcx32",    (void*)&ppu_stwcx32    },
            { "ps3_hle_call",   (void*)&ps3_hle_call   },
            { "ps3_indirect",   (void*)&ps3_indirect_call },
            { "ppu_guard_page", (void*)&ppu_guard_page },
            { "vm_write8",      (void*)&vm_write8      },
            { "vm_write16",     (void*)&vm_write16     },
            { "vm_write64",     (void*)&vm_write64     },
            { "vm_read64",      (void*)&vm_read64      },
            { "ppu_register_fn",(void*)&ppu_register_function },
        };
        for (auto& e : k)
            fprintf(stderr, "[hostmap] %-14s rva=0x%llX\n", e.n,
                    (unsigned long long)((char*)e.p - mb));
    }
    fflush(stderr);
}

/* GT5P_THREADS=1: with each main-thread sample, every guest thread the runtime
 * created -- where it is and what it last asked the kernel for -- then every
 * kernel mutex that is held and by whom. A deadlock needs both halves: the
 * waiter names the mutex (r3 of syscall 102), the mutex names its owner, and
 * the owner's line says what it is waiting for in turn. */
static void dump_threads_and_mutexes(void)
{
    for (int i = 0; i < PPU_THREAD_MAX; i++) {
        ppu_thread_info* t = &g_ppu_threads[i];
        if (t->state != PPU_THREAD_STATE_RUNNING && t->state != PPU_THREAD_STATE_DETACHED)
            continue;
        char chain[400]; chain[0] = 0;
        if (t->host_thread && SuspendThread(t->host_thread) != (DWORD)-1) {
            CONTEXT hc; hc.ContextFlags = CONTEXT_FULL;
            if (GetThreadContext(t->host_thread, &hc)) {
                int p = 0;
                for (int f = 0; f < 40 && hc.Rip && p < 340; f++) {
                    uint32_t g = ppu_prof_resolve_host((void*)hc.Rip);
                    if (g) p += snprintf(chain + p, sizeof(chain) - p, " func_%08X", g);
                    else if (f == 0)    /* where exactly, when not in lifted code */
                        p += snprintf(chain + p, sizeof(chain) - p, " <rva:%llX>",
                                      (unsigned long long)(hc.Rip - (DWORD64)GetModuleHandleA(nullptr)));
                    DWORD64 imgBase = 0;
                    PRUNTIME_FUNCTION rf = RtlLookupFunctionEntry(hc.Rip, &imgBase, nullptr);
                    if (!rf) break;
                    PVOID hd = nullptr; DWORD64 est = 0;
                    RtlVirtualUnwind(UNW_FLAG_NHANDLER, imgBase, hc.Rip, rf,
                                     &hc, &hd, &est, nullptr);
                }
            }
            ResumeThread(t->host_thread);
        }
        /* Lowest word of the stack ever written: how deep it has been, not
         * how deep it is now. Zero free means it reached the bottom, and the
         * page below belongs to another thread. */
        uint32_t low = t->stack_addr;
        for (; t->stack_size && low < t->stack_addr + t->stack_size; low += 4) {
            uint32_t w; memcpy(&w, vm_base + low, 4);
            if (w) break;
        }
        fprintf(stderr, "[thread] tid=%llu name=\"%s\" sp=0x%08X stack=0x%08X+0x%X free=0x%X lr=0x%08X sc=%u r3=0x%08X r4=0x%08X chain:%s\n",
                (unsigned long long)t->ctx.thread_id, t->name, (uint32_t)t->ctx.gpr[1],
                t->stack_addr, t->stack_size, low - t->stack_addr, (uint32_t)t->ctx.lr,
                (uint32_t)t->ctx.gpr[11], (uint32_t)t->ctx.gpr[3],
                (uint32_t)t->ctx.gpr[4], chain);
    }
    for (int i = 0; i < SYS_MUTEX_MAX; i++) {
        sys_mutex_info* m = &g_sys_mutexes[i];
        if (!m->active || m->lock_count <= 0) continue;
        char name[9]; memcpy(name, m->name, 8); name[8] = 0;
        fprintf(stderr, "[mutex] id=%d name=\"%s\" owner_tid=%llu count=%d recursive=%d\n",
                i + 1, name, (unsigned long long)m->owner_tid, m->lock_count, m->recursive);
    }
}

static DWORD WINAPI main_stack_dump(LPVOID secs)
{
  for (;;) {
    Sleep((DWORD)(intptr_t)secs * 1000);

    /* Where is the main thread actually executing? ctx->lr only names the last
     * `bl` the lifted code took, and a function reached by a tail branch, or
     * looping without calling anything, never updates it. Suspending the thread
     * and mapping its RIP back through the function table names the guest
     * function it is *in*. */
    uint32_t live = 0;
    char hoststack[1400]; hoststack[0] = 0;
    if (g_main_thread) {
        CONTEXT hc; hc.ContextFlags = CONTEXT_FULL;
        if (SuspendThread(g_main_thread) != (DWORD)-1) {
            if (GetThreadContext(g_main_thread, &hc)) {
                live = ppu_prof_resolve_host((void*)hc.Rip);
                g_last_rip = (uintptr_t)hc.Rip;

                /* Walk the host stack with the Win64 unwinder and map each
                 * frame back to its guest function. A frame that resolves to
                 * func_00000000 is runtime/library code, and its position in
                 * the chain says which lifted function called into it. */
                int p = 0;
                for (int f = 0; f < 24 && hc.Rip && p < 1250; f++) {
                    uint32_t g = ppu_prof_resolve_host((void*)hc.Rip);
                    p += snprintf(hoststack + p, sizeof(hoststack) - p,
                                  g ? "  func_%08X" : "  <host:%08X>",
                                  g ? g : (unsigned)(hc.Rip & 0xFFFFFFFF));
                    DWORD64 imgBase = 0;
                    PRUNTIME_FUNCTION rf = RtlLookupFunctionEntry(hc.Rip, &imgBase, nullptr);
                    if (!rf) break;                 /* leaf / no unwind data */
                    PVOID hd = nullptr; DWORD64 est = 0;
                    RtlVirtualUnwind(UNW_FLAG_NHANDLER, imgBase, hc.Rip, rf,
                                     &hc, &hd, &est, nullptr);
                }
            }
            ResumeThread(g_main_thread);
        }
    }

    uint32_t sp = (uint32_t)g_main_ctx.gpr[1];
    fprintf(stderr, "[mainstack] in=func_%08X sp=0x%08X lr=0x%08X ctr=0x%08X r3=0x%08X r31=0x%08X\n",
            live, sp, (uint32_t)g_main_ctx.lr, (uint32_t)g_main_ctx.ctr,
            (uint32_t)g_main_ctx.gpr[3], (uint32_t)g_main_ctx.gpr[31]);
    fprintf(stderr, "[mainstack] in_hle=%s rip=%p\n",
            g_hle_inflight[0] ? g_hle_inflight[0] : "-", (void*)g_last_rip);
    {
        static int once = 0;
        if (!once++)
            fprintf(stderr, "[hostmap] stwcx32=%p indirect=%p hle_call=%p "
                            "read32=%p write32=%p\n",
                    (void*)&ppu_stwcx32, (void*)&ps3_indirect_call,
                    (void*)&ps3_hle_call, (void*)&vm_read32, (void*)&vm_write32);
    }
    fprintf(stderr, "[mainregs]");
    for (int r = 0; r < 32; r++)
        fprintf(stderr, " r%d=%08X", r, (uint32_t)g_main_ctx.gpr[r]);
    fprintf(stderr, "\n[mainregs] [r9]=%08X [r26]=%08X\n",
            vm_read32((uint32_t)g_main_ctx.gpr[9]),
            vm_read32((uint32_t)g_main_ctx.gpr[26]));

    /* GT5P_PEEK=addr[,addr...]: eight guest words at each address, then eight
     * more at whatever the first word points to. addr@offset follows one
     * pointer; addr@@offset follows two before adding offset. */
    if (const char* peek = getenv("GT5P_PEEK")) {
        char buf[512];
        strncpy(buf, peek, sizeof buf - 1); buf[sizeof buf - 1] = 0;
        for (char* tok = strtok(buf, ","); tok; tok = strtok(nullptr, ",")) {
            uint32_t offset = 0;
            int pointer_hops = 1;
            if (char* at = strchr(tok, '@')) {
                *at++ = 0;
                if (*at == '@') { pointer_hops = 2; at++; }
                offset = (uint32_t)strtoul(at, nullptr, 0);
            }
            uint32_t a = (uint32_t)strtoul(tok, nullptr, 0);
            const int levels = pointer_hops + 2;
            for (int level = 0; level < levels && a; level++) {
                fprintf(stderr, "[peek] %08X:", a);
                for (int k = 0; k < 8; k++)
                    fprintf(stderr, " %08X", vm_read32(a + (uint32_t)k * 4));
                /* The same words straight out of the mapping, bypassing
                 * vm_read32 and its instrumentation. If these two lines
                 * disagree, the accessor is lying — and the guest reads the
                 * same lie. */
                fprintf(stderr, "\n[peek] %08X raw:", a);
                for (int k = 0; k < 8; k++) {
                    uint32_t w;
                    memcpy(&w, vm_base + a + (uint32_t)k * 4, 4);
                    fprintf(stderr, " %08X", _byteswap_ulong(w));
                }
                fputc('\n', stderr);
                a = vm_read32(a);
                if (level + 1 == pointer_hops) a += offset;
            }
        }
    }
    /* GT5P_PEEK_R31=off[,off...]: 64 bytes at main's r31 + each (signed, hex)
     * offset, as words and as text. For an object on the heap, whose address
     * moves from run to run but which a parked main still points at. */
    if (const char* pk = getenv("GT5P_PEEK_R31")) {
        char buf[256];
        strncpy(buf, pk, sizeof buf - 1); buf[sizeof buf - 1] = 0;
        for (char* tok = strtok(buf, ","); tok; tok = strtok(nullptr, ",")) {
            uint32_t a = (uint32_t)g_main_ctx.gpr[31] + (uint32_t)strtol(tok, nullptr, 16);
            fprintf(stderr, "[peek31] %08X:", a);
            for (int k = 0; k < 16; k++) fprintf(stderr, " %08X", vm_read32(a + (uint32_t)k * 4));
            fprintf(stderr, "  \"");
            for (int k = 0; k < 64; k++) {
                unsigned char c = vm_base[a + (uint32_t)k];
                fputc(c >= 32 && c < 127 ? c : '.', stderr);
            }
            fprintf(stderr, "\"\n");
        }
    }
    fprintf(stderr, "[hostchain]%s\n", hoststack);
    if (getenv("GT5P_THREADS")) dump_threads_and_mutexes();

    uint32_t last = 0;
    int shown = 0;
    for (int i = 0; i < 2048 && shown < 10; i++) {
        uint32_t w = vm_read32(sp + (uint32_t)i * 4);
        if (w < GT5P_CODE_LO || w >= GT5P_CODE_HI || w == last) continue;
        uint32_t f = enclosing_func(w);
        if (!f || w - f == 0 || w - f >= 0x4000) continue;   /* not a return site */
        fprintf(stderr, "   func_%08X+0x%-5X\n", f, w - f);
        last = w;
        shown++;
    }
    fflush(stderr);
    /* stdout is fully buffered and a boot that never exits is killed from
     * outside, which loses everything still in the buffer -- including the
     * cellFs lines the asset count is taken from. */
    fflush(stdout);
  }
}
#endif

#ifdef _WIN32
/* Commit guest pages on first touch, the way ps3recomp's own boot harness
 * does. A title with its own main() does not get that for free, and any guest
 * access to a page nothing had explicitly committed kills the process instead
 * of just working. Commits are logged -- a page the guest touches that nothing
 * allocated is still worth knowing about; this makes it survivable, not
 * invisible. GT5P_NO_FAULT_COMMIT=1 lets the fault stand. */
static LONG CALLBACK fault_commit(EXCEPTION_POINTERS* ep)
{
    const EXCEPTION_RECORD* er = ep->ExceptionRecord;
    if (er->ExceptionCode != EXCEPTION_ACCESS_VIOLATION || er->NumberParameters < 2)
        return EXCEPTION_CONTINUE_SEARCH;
    uintptr_t at = (uintptr_t)er->ExceptionInformation[1];
    if (!vm_base || at < (uintptr_t)vm_base || at >= (uintptr_t)vm_base + 0x100000000ull)
        return EXCEPTION_CONTINUE_SEARCH;
    void* page = (void*)(at & ~(uintptr_t)0xFFFF);
    if (!VirtualAlloc(page, 0x10000, MEM_COMMIT, PAGE_READWRITE))
        return EXCEPTION_CONTINUE_SEARCH;
    static LONG n = 0;
    if (InterlockedIncrement(&n) <= 24)
        fprintf(stderr, "[GT5P] faulted in guest page 0x%08X (%s) -- committed\n",
                (uint32_t)((uintptr_t)page - (uintptr_t)vm_base),
                er->ExceptionInformation[0] == 1 ? "write" : "read");
    return EXCEPTION_CONTINUE_EXECUTION;
}

static LONG CALLBACK report_crash(EXCEPTION_POINTERS* ep)
{
    const EXCEPTION_RECORD* er = ep->ExceptionRecord;
    if (er->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && er->NumberParameters >= 2) {
        const char* how = er->ExceptionInformation[0] == 0 ? "read"
                        : er->ExceptionInformation[0] == 1 ? "write" : "execute";
        uintptr_t at = (uintptr_t)er->ExceptionInformation[1];
        fprintf(stderr, "\n[GT5P] ACCESS VIOLATION: %s at host 0x%llX", how,
                (unsigned long long)at);
        if (vm_base && at >= (uintptr_t)vm_base && at < (uintptr_t)vm_base + 0x100000000ull)
            fprintf(stderr, " = GUEST 0x%08X", (uint32_t)(at - (uintptr_t)vm_base));
        fprintf(stderr, " (thread %lu)\n", GetCurrentThreadId());
    }
    /* The registers below are the main thread's, which is not much use when a
     * worker faults. Name the guest function the faulting thread is in, and
     * its callers, by unwinding the host stack -- same method as
     * main_stack_dump. */
    {
        CONTEXT hc = *ep->ContextRecord;
        fprintf(stderr, "[GT5P]   fault chain:");
        for (int f = 0; f < 16 && hc.Rip; f++) {
            uint32_t g = ppu_prof_resolve_host((void*)hc.Rip);
            if (g) fprintf(stderr, " func_%08X", g);
            else   fprintf(stderr, " <host:%08X>", (unsigned)(hc.Rip & 0xFFFFFFFF));
            DWORD64 imgBase = 0;
            PRUNTIME_FUNCTION rf = RtlLookupFunctionEntry(hc.Rip, &imgBase, nullptr);
            if (!rf) break;
            PVOID hd = nullptr; DWORD64 est = 0;
            RtlVirtualUnwind(UNW_FLAG_NHANDLER, imgBase, hc.Rip, rf, &hc, &hd, &est, nullptr);
        }
        fputc('\n', stderr);
    }
    /* The filter runs on the faulting thread, so its own guest context is the
     * runtime's thread-local one. */
    if (ppu_context* c = g_active_ctx) {
        fprintf(stderr, "[GT5P]   faulting thread regs: lr=%08X ctr=%08X",
                (uint32_t)c->lr, (uint32_t)c->ctr);
        for (int r = 0; r < 32; r++)
            fprintf(stderr, "%s r%d=%llX", r % 8 == 0 ? "\n[GT5P]    " : "", r,
                    (unsigned long long)c->gpr[r]);
        fputc('\n', stderr);
        /* The host unwind above stops after 16 frames, which in a runaway
         * recursion is 16 copies of one name. The guest stack still holds the
         * whole story: follow its back chain and print each return address
         * once per run of repeats, so the frames under the recursion show. */
        if (vm_base) {
            auto rd32 = [](uint64_t ea) -> uint32_t {
                const uint8_t* p = vm_base + (uint32_t)ea;
                return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
            };
            uint32_t sp = (uint32_t)c->gpr[1], last = 0, run = 0, stride = 0; int shown = 0;
            fprintf(stderr, "[GT5P]   guest back chain from sp=%08X:", sp);
            for (uint32_t n = 0; n < 8000000u && sp >= 0x10000u && shown < 28; n++) {
                uint32_t up = rd32((uint64_t)sp + 4);          /* low word of the 64-bit back chain */
                if (up <= sp || up - sp > 0x100000u) {
                    /* A recursion this deep runs off its own stack into
                     * memory other threads write. Step over the damage at the
                     * frame size seen so far. */
                    if (!stride || n < 16) break;
                    up = sp + stride;
                    if (shown < 27 && !run) { fprintf(stderr, " [chain broken at %08X]", sp); }
                }
                stride = up - sp;
                uint32_t lr = rd32((uint64_t)up + 0x14);       /* saved LR in the caller's frame */
                if (lr == last) run++;
                else {
                    if (run) fprintf(stderr, " (x%u)", run + 1);
                    fprintf(stderr, " %08X@%08X", lr, up); last = lr; run = 0; shown++;
                }
                sp = up;
            }
            if (run) fprintf(stderr, " (x%u)", run + 1);
            fprintf(stderr, "; stopped at sp=%08X [sp]=%08X %08X\n", sp, rd32(sp), rd32((uint64_t)sp + 4));
            /* What lies above the last frame followed, raw: 96 words. */
            fprintf(stderr, "[GT5P]   stack above %08X:", sp);
            for (int k = 0; k < 96; k++) {
                if (k % 8 == 0) fprintf(stderr, "\n[GT5P]     +%03X:", k * 4);
                fprintf(stderr, " %08X", rd32((uint64_t)sp + k * 4));
            }
            fputc('\n', stderr);
            /* Return addresses near the object in r3: when it is a local of
             * the function that started the recursion, its callers' saved LRs
             * are just above it. Word pairs (0, code address) only. */
            { uint32_t o2 = (uint32_t)c->gpr[3] & ~7u;
              if (o2 >= 0x10000u) {
                  fprintf(stderr, "[GT5P]   code addresses on the stack around r3:");
                  for (uint32_t a = o2 - 0x600u; a < o2 + 0x2000u; a += 8) {
                      uint32_t hi = rd32(a), lo = rd32((uint64_t)a + 4);
                      if (!hi && lo >= 0x00010000u && lo < 0x00E40000u && !(lo & 3u))
                          fprintf(stderr, " %08X@%+d", lo, (int)(a - o2));
                  }
                  fputc(10, stderr);
              } }
            uint32_t o = (uint32_t)c->gpr[3];
            if (o >= 0x10000u) {
                fprintf(stderr, "[GT5P]   [r3=%08X]:", o);
                for (int k = 0; k < 12; k++) fprintf(stderr, " %08X", rd32((uint64_t)o + k * 4));
                fputc('\n', stderr);
            }
        }
    }
    ppu_ww_dump_tail();   /* PPU_WWATCH_TAIL=1: the last writes to the watched address */
    fprintf(stderr, "[GT5P]   r1(SP)=0x%08X r2(TOC)=0x%08X r3=0x%08X LR=0x%08X CTR=0x%08X\n",
            (uint32_t)g_main_ctx.gpr[1], (uint32_t)g_main_ctx.gpr[2],
            (uint32_t)g_main_ctx.gpr[3], (uint32_t)g_main_ctx.lr,
            (uint32_t)g_main_ctx.ctr);
    fflush(stderr);
    fflush(stdout);
    return EXCEPTION_EXECUTE_HANDLER;
}
#endif

static void setup_argv(const char* argv0)
{
    /* PS3 _start ABI: r3 = argc, r4 = argv, r5 = envp. A PS3 title derives its
     * content directory from argv[0], so passing none leaves it with no data
     * path at all. /app_home is the prefix ppu_fs.cpp strips before appending
     * the rest to the VFS root. */
    vm_commit(GT5P_ARGV_BASE, 0x10000u);
    memset(vm_base + GT5P_ARGV_BASE, 0, 0x10000u);

    /* argv is an array of 64-bit pointers, not 32-bit.
     *
     * The guest CRT's first act (func_00010368) is
     *
     *     r10 = argv + 4;  r28 = argv;
     *     do { r0 = [r10]; [r28] = r0; r10 += 8; r28 += 4; } while (++i < argc);
     *
     * -- read at stride 8, write at stride 4, i.e. compact an array of 64-bit
     * pointers into 32-bit ones by keeping each low half. It does the same to
     * envp immediately after. Writing 32-bit entries here made it read every
     * other slot: argv[0] came out as our argv[1] and the rest as NULL, so the
     * title had never seen a single argument -- including its own path. */
    uint32_t str_ea = GT5P_ARGV_BASE + 0x100;
    strcpy((char*)(vm_base + str_ea), argv0);
    vm_write64(GT5P_ARGV_BASE + 0, str_ea);   /* argv[0] */

    /* GT5P is configured by its command line, and it is not optional.
     *
     * func_00013C98(name, buf, len) fetches a setting, and it is a plain argv
     * scan: strlen(name), then for each argv[i] check argv[i][strlen(name)]
     * == '=', i.e. tokens of the form name=value. Its first act is
     *
     *     if (argc <= 1) return 0;
     *
     * so with only argv[0] every setting comes back missing. The filesystem
     * setup (func_00014B58) asks for `boot_from` first and returns immediately
     * when it is absent -- which is why no file device is ever constructed, why
     * PDIPFS is never mounted, and why the application script cannot be found.
     *
     * The accepted values sit next to the key in .rodata:
     *     0x00E98350 "boot_from"   0x00E98360 "bdvd"
     *                              0x00E98368 "gamedata"
     *                              0x00E98378 "hddgame"
     * and the path it builds from there is "/dev_bdvd/PS3_GAME/USRDIR" + "/" +
     * "PDIPFS", which is exactly what cellFs serves. GT5P_ARGS overrides the
     * whole list (space-separated) for experimenting with the other two. */
    const char* extra = getenv("GT5P_ARGS");
    /* gamedata, not bdvd. All three are accepted, but they select different
     * volume formats: bdvd looks for USRDIR/GT.VOL (the retail disc layout)
     * and gamedata looks for PDIPFS, which is what the PSN package ships. */
    if (!extra || !*extra) extra = "boot_from=" GT5P_BOOT_FROM;

    char args[512];
    strncpy(args, extra, sizeof args - 1);
    args[sizeof args - 1] = '\0';

    uint32_t argc_out = 1;
    uint32_t next_str = str_ea + 0x80;
    for (char* tok = strtok(args, " \t"); tok && argc_out < 30;
         tok = strtok(nullptr, " \t")) {
        strcpy((char*)(vm_base + next_str), tok);
        vm_write64(GT5P_ARGV_BASE + argc_out * 8, next_str);
        next_str += (uint32_t)strlen(tok) + 1;
        next_str = (next_str + 15) & ~15u;
        argc_out++;
    }
    vm_write64(GT5P_ARGV_BASE + argc_out * 8, 0);   /* argv[argc] = NULL */

    uint32_t envp_ea = GT5P_ARGV_BASE + 0x600;
    vm_write64(envp_ea, 0);                   /* envp[0] = NULL, also 64-bit */

    g_main_ctx.gpr[3] = argc_out;
    g_main_ctx.gpr[4] = GT5P_ARGV_BASE;
    g_main_ctx.gpr[5] = envp_ea;
    printf("[GT5P] argv[0] = \"%s\" (argc=%u", argv0, argc_out);
    for (uint32_t i = 1; i < argc_out; i++)
        printf(", \"%s\"", (const char*)(vm_base + vm_read32(GT5P_ARGV_BASE + i * 4)));
    printf(")\n");
}

/* Closing the game window ends the game. Nothing else did: the title's
 * threads kept running with no window. The log is flushed first. */
extern "C" void (*rsx_d3d12_on_close)(void);
static void window_closed(void)
{
    printf("[GT5P] window closed; exiting\n");
    fflush(stdout); fflush(stderr);
    ExitProcess(0);
}

/* Run from anywhere. The game is found by paths relative to the working
 * directory (input/EMAIN.ELF, input/pkg/, gamedata/), which is the project
 * root when a script starts the port. Started any other way -- double-clicked
 * in build/, say -- the working directory is wherever the exe is, nothing is
 * found, and the port used to exit at once. So when the default executable is
 * not where the working directory says, look for it upwards from the exe's
 * own folder and work from there. GT5P_ROOT names the folder outright.
 * Returns 0 when the game cannot be found. */
static int locate_project_root(void)
{
    const char* forced = getenv("GT5P_ROOT");
    if (forced && *forced) {
        if (!SetCurrentDirectoryA(forced)) {
            fprintf(stderr, "[GT5P] ERROR: GT5P_ROOT=\"%s\" is not a folder\n", forced);
            return 0;
        }
        return 1;
    }
    if (GetFileAttributesA("input\\EMAIN.ELF") != INVALID_FILE_ATTRIBUTES) return 1;
    char dir[MAX_PATH];
    DWORD n = GetModuleFileNameA(NULL, dir, sizeof dir);
    if (!n || n >= sizeof dir) return 0;
    for (int up = 0; up < 5; up++) {
        char* cut = strrchr(dir, '\\');
        if (!cut) break;
        *cut = 0;                       /* the exe's folder, then its parents */
        char probe[MAX_PATH + 32];
        snprintf(probe, sizeof probe, "%s\\input\\EMAIN.ELF", dir);
        if (GetFileAttributesA(probe) != INVALID_FILE_ATTRIBUTES) {
            SetCurrentDirectoryA(dir);
            printf("[GT5P] working from %s\n", dir);
            return 1;
        }
    }
    return 0;
}

int main(int argc, char* argv[])
{
    /* Buffer both streams, first thing: setvbuf has to come before any output.
     * Unbuffered stdio issues a write per conversion, so with several guest
     * threads logging at once lines interleave mid-token and a message that IS
     * in the log reads as absent to grep. The crash filter flushes, so a fault
     * still shows the tail; the flush thread below covers a killed run. */
    static char out_buf[1 << 16], err_buf[1 << 16];
    setvbuf(stdout, out_buf, _IOFBF, sizeof out_buf);
    setvbuf(stderr, err_buf, _IOFBF, sizeof err_buf);

    /* gt5p_settings.toml, before anything below reads the environment: the
     * settings are handed to the runtime as environment variables that are
     * not already set (see gt5p_settings.h). */
    gt5p_settings_load();

    /* Someone started this by hand if its output is a console window rather
     * than a file. Verbose logging serialises every guest thread on one lock
     * (the sound stutters and the menu drops frames), so it is off for them
     * unless asked for; the scripts redirect output and are not affected. */
    const bool by_hand = GetFileType(GetStdHandle(STD_OUTPUT_HANDLE)) == FILE_TYPE_CHAR;
    if (by_hand && !getenv("PS3_VERBOSE")) _putenv_s("PS3_VERBOSE", "0");

    if (argc <= 1 && !locate_project_root()) {
        const char* msg =
            "The game files were not found.\n\n"
            "This program expects the project layout: a folder holding\n"
            "input\\EMAIN.ELF (the decrypted executable) and input\\pkg\\\n"
            "(PARAM.SFO and USRDIR). It looks in the current folder and in the\n"
            "folders above the exe. Set GT5P_ROOT to that folder to name it.";
        fprintf(stderr, "[GT5P] ERROR: %s\n", msg);
        if (by_hand) MessageBoxA(NULL, msg, "Gran Turismo 5 Prologue", MB_OK | MB_ICONERROR);
        return EXIT_FAILURE;
    }

    rsx_d3d12_on_close = window_closed;

    /* Schedule guest threads by their PS3 priority on two host cores, as the
     * console's two hardware threads would. Left to the host scheduler, about
     * one boot in four fails during sound start-up; with this on, 1 in 52
     * did (docs/progress.md, Phase 22). Set PS3_PPU_PRIO_SCHED=0 to turn it
     * off. Must be set before the runtime creates its first thread. */
    if (!getenv("PS3_PPU_PRIO_SCHED")) _putenv_s("PS3_PPU_PRIO_SCHED", "2");

    /* Run a SPURS workload only while its ready count is nonzero, on as many
     * virtual SPUs as the count asks for. This title fills a job list first
     * and raises the count afterwards; run before that, the dealership's
     * render jobs read output rings not yet set up (docs/progress.md, Phase
     * 39). SPURS_READY_GATE=0 for the old every-pass dispatch. */
    if (!getenv("SPURS_READY_GATE")) _putenv_s("SPURS_READY_GATE", "1");

    /* SPU render lanes on cores of their own (strict pinning): 1.14 times
     * faster lanes, Ferrari at a median 28.2 fps against 24.8 free, and no
     * freeze in 20 visits since Phase 64. The settings page's choice, set just
     * above when settings are loaded, wins; this is for runs without them.
     * SPURS_LANE_PIN=0 for the scheduler's placement. */
    if (!getenv("SPURS_LANE_PIN")) _putenv_s("SPURS_LANE_PIN", "2");

    /* Shaders not in the disk cache compile on background threads, all of a
     * frame's at once, instead of one by one on the frame thread (Phase 65:
     * an empty cache kept the first dealer page away for over a minute). The
     * settings page's "Precompile shaders" wins; RSX_SHADER_ASYNC=0 for the
     * old way. */
    if (!getenv("RSX_SHADER_ASYNC")) _putenv_s("RSX_SHADER_ASYNC", "1");

    /* Ask for 1 ms timer resolution. Without it Sleep(1) lasts about 15.6 ms
     * on Windows, and the runtime paces the SPU job poll, the present thread
     * and guest usleep with short sleeps: the agreement screen ran at 12.8
     * frames a second, exactly five such sleeps a frame (docs/progress.md,
     * Phase 27). GT5P_TIMER_RES=0 leaves the system default, to compare. */
    {
        const char* tr = getenv("GT5P_TIMER_RES");
        if (!tr || tr[0] != '0') timeBeginPeriod(1);
    }

    /* A run that is killed, as the test scripts stop one, loses whatever is
     * still in those buffers: up to 64 KB, which hid everything the title
     * logged after choosing a manufacturer (Phase 41). Flush both every
     * GT5P_FLUSH_MS (default 1000; 0 turns it off). */
    {
        const char* fe = getenv("GT5P_FLUSH_MS");
        static DWORD flush_ms = fe ? (DWORD)strtoul(fe, nullptr, 10) : 1000;
        if (flush_ms)
            CreateThread(nullptr, 0, [](LPVOID) -> DWORD {
                for (;;) { Sleep(flush_ms); fflush(stdout); fflush(stderr); }
            }, nullptr, 0, nullptr);
    }

    printf("=== Gran Turismo 5 Prologue Recompiled ===\n");
    printf("Built with ps3recomp | %llu lifted functions\n\n",
           (unsigned long long)function_table_count);

#ifdef _WIN32
    ps3_install_guest_ptr_trap();
    if (!getenv("GT5P_NO_FAULT_COMMIT"))
        AddVectoredExceptionHandler(1, fault_commit);
    SetUnhandledExceptionFilter(report_crash);
#endif

    /* Move the HLE-visible GCM window (labels, control register, and the 16 KB
     * of offset tables) off this title's heap. NPUA80075 maps 174 MB at
     * 0x20000000 -- the runtime's default base -- and publishing the offset
     * tables there overwrote the CRT allocator's size-class pool, which wedged
     * the main thread in a livelock for the whole boot. 0x03000000 is free
     * here, and main() commits it below. Must be set before any guest code. */
    ppu_hle_inject_base = GT5P_GCM_CTRL_BASE;

    if (int32_t rc = vm_init()) {
        fprintf(stderr, "[GT5P] ERROR: VM init failed (0x%08X)\n", (unsigned)rc);
        return EXIT_FAILURE;
    }
    printf("[GT5P] VM initialised (base=%p)\n", (void*)vm_base);

    vm_commit(0, 0x10000);                                   /* null-page guard  */
    vm_commit(GT5P_GCM_CTRL_BASE, GT5P_GCM_CTRL_SIZE);
    memset(vm_base + GT5P_GCM_CTRL_BASE, 0, GT5P_GCM_CTRL_SIZE);
    vm_commit(GT5P_LOCAL_MEM_BASE, GT5P_LOCAL_MEM_SIZE);     /* RSX local memory */
    printf("[GT5P] GCM control page + %u MB RSX local memory committed\n",
           GT5P_LOCAL_MEM_SIZE / (1024 * 1024));

    /* NPUA80075 is an HDD title (PARAM.SFO CATEGORY=HG), so the disc, hdd-game
     * and app_home roots all have to land on the extracted package. */
    {
        const char* vfs = getenv("PS3_VFS_ROOT");
        if (!vfs || !*vfs) vfs = ".";
        cellfs_set_root_path(vfs);

        /* GT5P_GAME_DIR: the folder holding PARAM.SFO and USRDIR, relative to
         * the root and with a trailing slash. */
        static char game_dir[512], pdipfs_dir[600];
        const char* gd = getenv("GT5P_GAME_DIR");
        snprintf(game_dir, sizeof game_dir, "%s", gd && *gd ? gd : "input/pkg/");
        snprintf(pdipfs_dir, sizeof pdipfs_dir, "%sUSRDIR/PDIPFS/", game_dir);

        cellfs_add_path_mapping("/dev_bdvd/PS3_GAME/",          game_dir);
#ifdef GT5P_HDD_TITLE
        cellfs_add_path_mapping("/dev_hdd0/game/" GT5P_TITLE_ID "/", game_dir);
#endif
        cellfs_add_path_mapping("/app_home/",                   game_dir);
        cellfs_add_path_mapping("/dev_hdd0/",                   "gamedata/dev_hdd0/");
        /* With boot_from=gamedata the title opens its packed volume by a
         * RELATIVE path -- "PDIPFS/K/4D" -- because on hardware the process's
         * working directory is its own USRDIR. Nothing here has a cwd, so map
         * the prefix explicitly. */
        cellfs_add_path_mapping("PDIPFS/",                      pdipfs_dir);
        printf("[GT5P] cellFs root=\"%s\" (%s game dir -> %s)\n", vfs, GT5P_TITLE_ID, game_dir);

        /* Give cellGame the real ids. Without this the HLE answers every
         * cellGame/cellDiscGame query with its built-in fallback, and this
         * title's boot was being told its id is "BLES00000" when PARAM.SFO
         * says NPUA80075 -- which matters the moment anything builds a path
         * from it (/dev_hdd0/game/<id>/...). */
        {
            char sfo[512];
            snprintf(sfo, sizeof sfo, "%s/%sPARAM.SFO", vfs, game_dir);
            cellGame_init_from_paramsfo(sfo);
        }
    }

    /* video.resolution = "1080p": tell the game the display is 1080p. The
     * runtime reports 720p unless told otherwise, and the game renders at what
     * it is told; it supported 1080p on the console. The present window
     * follows (gt5p_present.cpp). */
    if (gt5p_settings().resolution == 1080) {
        cellVideoOut_set_resolution(1 /* CELL_VIDEO_OUT_RESOLUTION_1080 */);
        printf("[GT5P] reporting a 1920x1080 display\n");
    }

    lv2_register_all_syscalls(&g_lv2_syscalls);

    const char* elf_path = argc > 1 ? argv[1] : "input/EMAIN.ELF";
    printf("[GT5P] Loading ELF: %s\n", elf_path);
    ElfLoadResult elf = load_elf_into_vm(elf_path);
    if (!elf.success) {
        fprintf(stderr, "[GT5P] ERROR: failed to load %s\n", elf_path);
        vm_shutdown();
        return EXIT_FAILURE;
    }

    ppu_hle_register_all();
    ppu_sysprx_register();
    printf("[HLE] ps3recomp NID registry: %u handlers\n", ps3_hle_count());

    ppu_recomp_register();
    ppu_install_thread_trampoline();
    if (!getenv("GT5P_NO_GUEST_CALLER")) g_ps3_guest_caller = gt5p_guest_caller;
    /* Whether the runtime invents a completion event for each SPURS job. This
     * build's jobs send their own (config/targets.json). */
    spurs_set_synth_job_done(GT5P_SPURS_SYNTH_DONE);
    gt5p_spu_register_all();   /* after the ELF load: fingerprints the loaded image */

    uint32_t entry_addr = (uint32_t)elf.func_addr;
    auto entry_func = dispatch_lookup(entry_addr);
    if (!entry_func) {
        fprintf(stderr, "[GT5P] ERROR: entry 0x%08X is not in the lifted function "
                        "table.\n", entry_addr);
        vm_shutdown();
        return EXIT_FAILURE;
    }

    g_main_ctx.gpr[2] = elf.toc;

    /* Give the main thread an identity. ps3recomp's own loader does this; a
     * title with its own main() has to. Left at 0, main is the one thread the
     * kernel objects cannot tell from "nobody": sys_mutex uses owner 0 as its
     * free marker, and sys_ppu_thread_get_id reports a sentinel. The first
     * thread the title creates also took slot 0 and id 1 -- main's by rights.
     * GT5P_NO_MAIN_ID=1 restores the old behaviour for comparison. */
    if (!getenv("GT5P_NO_MAIN_ID")) {
        g_main_ctx.thread_id = ppu_thread_register_main();
        /* 1001 is the primary priority in this executable's process
         * parameters (RPCS3 logs it at load). The title compares the
         * priorities of the threads it creates against it. */
        ppu_thread_set_main_priority(1001);
        /* GT5P_PRIO_HANDOFF=1: make a thread that creates a higher-priority
         * one wait until it first blocks, as lv2 would. An experiment, off by
         * default: measured, it did not remove the boot's bad runs. */
        ppu_thread_set_prio_handoff(getenv("GT5P_PRIO_HANDOFF") ? 1 : 0);
    }

    /* Give the main thread an actual stack.
     *
     * g_main_ctx is zero-initialised and nothing ever set gpr[1], so the guest
     * started with SP = 0 and its first `stdu r1, -0x90(r1)` wrapped to
     * 0xFFFFFF70. Main's whole call stack has been living in the last few KB of
     * the 32-bit address space by accident -- outside the runtime's stack region
     * (0xD0000000, 256 MB), outside anything deliberately mapped, and reachable
     * only because the fault handler commits pages on demand.
     *
     * It half-works, which is why it survived this long: main can read back what
     * main wrote. But a worker thread reading an object in one of main's frames
     * gets a different answer -- the async file layer's request object reads
     * [obj+0x64] == 4 on main immediately after its constructor and 0 on the
     * worker, which is what stalls the sixth load. */
    {
        const uint32_t stack_size = GT5P_MAIN_STACK_SIZE;
        const uint32_t stack_base = GT5P_MAIN_STACK_BASE;
        vm_commit(stack_base, stack_size);
        memset(vm_base + stack_base, 0, stack_size);
        /* 16-byte aligned, with room for the caller's frame header, and a NULL
         * back-chain word so a stack walk terminates instead of wandering. */
        uint32_t sp = (stack_base + stack_size - 0x200) & ~0xFu;
        vm_write64(sp, 0);
        g_main_ctx.gpr[1] = sp;
        printf("[GT5P] main stack 0x%08X..0x%08X, SP=0x%08X\n",
               stack_base, stack_base + stack_size, sp);
    }
    /* argv[0] is not cosmetic here: the filesystem setup strcmps it against
     * "/dev_bdvd/PS3_GAME/USRDIR/EMAIN.SELF" to decide it is looking at its own
     * disc layout. With /app_home it takes a different branch and never opens
     * the volume at all. */
    setup_argv(getenv("PS3_ARGV0") && *getenv("PS3_ARGV0")
                   ? getenv("PS3_ARGV0")
                   : "/dev_bdvd/PS3_GAME/USRDIR/EMAIN.SELF");

#ifdef _WIN32
    if (getenv("GT5P_HOSTMAP")) dump_hostmap();

    if (const char* secs = getenv("GT5P_MAINSTACK")) {
        DuplicateHandle(GetCurrentProcess(), GetCurrentThread(),
                        GetCurrentProcess(), &g_main_thread,
                        THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, FALSE, 0);
        CreateThread(nullptr, 0, main_stack_dump,
                     (LPVOID)(intptr_t)atoi(secs), 0, nullptr);
    }
#endif

#ifdef _WIN32
    if (char* g = getenv("GT5P_GUARD"))
        CreateThread(nullptr, 0, guard_arm, g, 0, nullptr);
#endif

    gt5p_start_present_thread();

    printf("[GT5P] Executing 0x%08X (TOC 0x%08X)...\n\n",
           entry_addr, (uint32_t)elf.toc);
    fflush(stdout);

    entry_func(&g_main_ctx);

    printf("\n[GT5P] Guest returned. r3=0x%llX\n",
           (unsigned long long)g_main_ctx.gpr[3]);

    vm_shutdown();
    return EXIT_SUCCESS;
}
