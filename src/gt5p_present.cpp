/* Present / vblank ticker.
 *
 * Nothing in a port's own main() advances the display. The game requests a flip
 * (`_cellGcmSetFlipCommand`), then polls `cellGcmGetFlipStatus` until it clears
 * -- and `cellGcmTickFlip` is what clears it. Without a thread calling it, a
 * title that flips waits forever, and nothing ever drains the RSX FIFO, so no
 * command the guest wrote is ever executed.
 *
 * ps3recomp's own harness (runtime/ppu/tests/boot_main.cpp) runs a thread like
 * this; a port with its own main() needs its own.
 *
 * Ticks are driven off real elapsed time rather than off how long present()
 * takes: on a hidden or occluded window DXGI throttles Present hard, and pacing
 * the guest's frame counter behind it drops the whole boot to a few frames a
 * second.
 *
 * ponytail: the harness cadence, unchanged (16 ms ticks, drain again at the
 * outer 4 ms cadence). Measure before retuning -- the drain interval is
 * load-bearing for titles that fence every render pass.
 */
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>
#include <tlhelp32.h>

#include "ppu_context.h"
#include "sys_ppu_thread.h"
#include "vm.h"
#include "ps3emu/thread_name.h"

/* GT5P_THREADS=1: every 2 s, print each PPU thread's state and the guest
 * address of its last syscall/HLE call. "Runs its job loop but never loads
 * anything" is exactly the shape a wedged worker produces, and nothing else
 * shows which thread is where. */
extern "C" const char* g_hle_inflight[];

static void dump_threads(void)
{
    static int on = -1;
    if (on < 0) on = getenv("GT5P_THREADS") ? 1 : 0;
    if (!on) return;

    static ULONGLONG next = 0;
    ULONGLONG now = GetTickCount64();
    if (now < next) return;
    next = now + 2000;

    static const char* kState[] = { "FREE", "RUNNING", "FINISHED", "DETACHED" };
    fprintf(stderr, "[threads]\n");
    for (int i = 0; i < PPU_THREAD_MAX; i++) {
        const ppu_thread_info* t = &g_ppu_threads[i];
        if (t->state == PPU_THREAD_STATE_FREE) continue;
        fprintf(stderr, "   tid=%d %-9s entry=0x%08llX prof_pc=0x%08X hle=%-26s name=\"%s\"\n",
                i, kState[t->state & 3],
                (unsigned long long)t->entry_addr, t->prof_pc,
                (i < 64 && g_hle_inflight[i]) ? g_hle_inflight[i] : "-",
                t->name);
    }
}

extern "C" {
int  rsx_d3d12_backend_init(unsigned width, unsigned height, const char* title);
void rsx_d3d12_backend_present(void);
int  rsx_d3d12_backend_pump_messages(void);
void cellGcmTickVBlank(void);
void cellGcmTickFlip(void);
void cellGcm_rsx_process_fifo(void);
int  cellGcm_take_flip_pending(void);

/* Live NV4097->D3D12 engine (libs/video/rsx_live_draw.c), RSX_LIVE_DRAW=1. */
int  rsx_live_draw_enabled(void);
int  rsx_live_draw_init(void* hwnd, uint32_t w, uint32_t h,
                        const uint8_t* (*guest_ptr)(void*, uint32_t, uint32_t, uint32_t),
                        void* user);
void rsx_live_draw_present(uint32_t buffer_id);
int  rsx_null_backend_init(uint32_t w, uint32_t h, const char* title);
int  rsx_null_backend_pump_messages(void);
void* rsx_null_backend_get_hwnd(void);
void rsx_null_backend_suppress_present(int on);
uint32_t cellGcmResolveLocated(int local, uint32_t offset);
uint32_t cellGcmResolveIO(uint32_t offset);
uint32_t cellGcmGetCurrentDisplayBufferId(void);
}

/* RSX_LIVE_DRAW=1: draw through the live engine instead of rsx_d3d12_backend.
 *
 * The D3D12 backend presents a batch only when one of its draws targets a
 * registered display buffer. A title that renders its frame offscreen and
 * finishes with a 2D-engine blit into the display buffer never has such a draw:
 * the blit is a CPU copy in guest memory of a surface that exists only on the
 * GPU. Every such frame is rendered and counted in the titlebar FPS, and none
 * is shown. That fits the menu here (sounds respond to input, the picture never
 * changes, titlebar reads 30 fps), but is not yet confirmed for this title.
 * The live engine performs those blits on the GPU (cellGcmSys.c,
 * rsx_live_draw_blit / rsx_live_draw_resolve_blit).
 *
 * Wired the way the shared harness does it (runtime/ppu/tests/boot_main.cpp):
 * the null backend owns the window, the engine binds its swap chain to that
 * HWND and presents the buffer the guest flipped to. Unset, nothing changes. */
static int s_rsx_live = 0;

/* (location, offset) -> host pointer for the engine. location 0 is RSX local
 * memory, 1 is main memory through the IO table; the whole span must be in
 * range. Copied from boot_main.cpp's rsx_live_guest_ptr. */
static const uint8_t* live_guest_ptr(void*, uint32_t location, uint32_t offset,
                                     uint32_t min_bytes)
{
    if (!vm_base) return nullptr;
    uint32_t ea;
    if (location == 0) {
        ea = cellGcmResolveLocated(1, offset);
    } else {
        ea = cellGcmResolveIO(offset);
        if (!ea) ea = cellGcmResolveLocated(0, offset);
    }
    if (!ea || ea == 0xFFFFFFFFu || (uint64_t)ea + min_bytes > 0x100000000ull)
        return nullptr;
    return (const uint8_t*)vm_base + ea;
}

static int backend_init(const char* title)
{
    if (rsx_live_draw_enabled()) {
        if (rsx_null_backend_init(1280, 720, title) == 0 &&
            rsx_live_draw_init(rsx_null_backend_get_hwnd(), 1280, 720,
                               live_guest_ptr, nullptr) == 0) {
            s_rsx_live = 1;
            rsx_null_backend_suppress_present(1);
            fprintf(stderr, "[rsx] live-draw engine up (D3D12); GDI present suppressed\n");
            return 0;
        }
        fprintf(stderr, "[rsx] live-draw init FAILED -- falling back to the D3D12 backend\n");
    }
    return rsx_d3d12_backend_init(1280, 720, title);
}

/* Present the buffer the guest flipped to, not buffer 0: a double-buffered
 * title alternates 0,1 and a fixed 0 shows every other frame stale. */
static void backend_present(void)
{
    if (s_rsx_live) rsx_live_draw_present(cellGcmGetCurrentDisplayBufferId());
    else            rsx_d3d12_backend_present();
}

static int backend_pump(void)
{
    return s_rsx_live ? rsx_null_backend_pump_messages()
                      : rsx_d3d12_backend_pump_messages();
}

/* GT5P_SAMPLE=<n>: a sampling profiler for the n busiest threads (default 4,
 * at most 8). Every 10 s it reports, for each thread it sampled, the 60
 * busiest 256-byte code buckets as offsets from the executable's base, then
 * picks the threads that used the most CPU in that round to sample next. A
 * sample in a DLL is charged to its first caller in the executable (bit 0
 * set), so time in the CRT or the driver shows up under the function that
 * called it. `scratch/maplook.py build/gt5p.map <log>` names the buckets; the
 * thread ids match the [hostthread] and [THREAD] lines. Lifted guest code is
 * in the executable, so a guest thread's buckets are func_XXXXXXXX names. */
static int sample_rip(HANDLE th, unsigned long long base, unsigned long long* rva)
{
    if (SuspendThread(th) == (DWORD)-1) return 0;
    CONTEXT c; memset(&c, 0, sizeof c); c.ContextFlags = CONTEXT_FULL;
    BOOL ok = GetThreadContext(th, &c);
    unsigned long long tag = 0;
    if (ok && (c.Rip < base || c.Rip >= base + 0x10000000ull)) {
        for (int f = 0; f < 24; f++) {
            DWORD64 ib = 0;
            PRUNTIME_FUNCTION rf = RtlLookupFunctionEntry(c.Rip, &ib, NULL);
            if (!rf) { c.Rip = *(DWORD64*)c.Rsp; c.Rsp += 8; }
            else { void* hd = NULL; DWORD64 ef = 0;
                   RtlVirtualUnwind(UNW_FLAG_NHANDLER, ib, c.Rip, rf, &c, &hd, &ef, NULL); }
            if (c.Rip >= base && c.Rip < base + 0x10000000ull) { tag = 1; break; }
            if (!c.Rip) break;
        }
    }
    ResumeThread(th);
    if (!ok) return 0;
    *rva = ((c.Rip - base) & ~0xFFull) | tag;
    return 1;
}

static unsigned long long thread_cpu_100ns(HANDLE th)
{
    FILETIME a, b, k, u;
    if (!GetThreadTimes(th, &a, &b, &k, &u)) return 0;
    return (((unsigned long long)k.dwHighDateTime << 32) | k.dwLowDateTime) +
           (((unsigned long long)u.dwHighDateTime << 32) | u.dwLowDateTime);
}

struct SampThread {
    DWORD tid; HANDLE h; unsigned long long cpu0;
    struct { unsigned long long rva; unsigned n; } b[4096];
    unsigned nb, total;
};
struct ThreadCpu { DWORD tid; unsigned long long cpu, d; };

static DWORD WINAPI sampler_thread(LPVOID p)
{
    const int want = (int)(uintptr_t)p;
    const unsigned long long base = (unsigned long long)GetModuleHandleW(NULL);
    const DWORD me = GetCurrentThreadId(), pid = GetCurrentProcessId();
    static SampThread s[8];
    static ThreadCpu prev[1024], cur[1024];
    int ns = 0, nprev = 0, round = 0;
    ULONGLONG t0 = GetTickCount64();
    for (;;) {
        Sleep(1);
        for (int i = 0; i < ns; i++) {
            unsigned long long rva;
            if (!sample_rip(s[i].h, base, &rva)) continue;
            unsigned k = 0;
            for (; k < s[i].nb; k++) if (s[i].b[k].rva == rva) { s[i].b[k].n++; break; }
            if (k == s[i].nb && s[i].nb < 4096) { s[i].b[k].rva = rva; s[i].b[k].n = 1; s[i].nb++; }
            s[i].total++;
        }
        const ULONGLONG now = GetTickCount64();
        if (now - t0 < (round ? 10000u : 3000u)) continue;
        const double secs = (double)(now - t0) / 1000.0;
        for (int i = 0; i < ns; i++) {
            SampThread* t = &s[i];
            const double pct = 100.0 * (double)(thread_cpu_100ns(t->h) - t->cpu0) / 1e7 / secs;
            fprintf(stderr, "[ps-sample] round=%d tid=%lu cpu=%.0f%% %u samples, %u buckets, base 0x%llX\n",
                    round, (unsigned long)t->tid, pct, t->total, t->nb, base);
            for (int r = 0; r < 60; r++) {
                unsigned best = 0;
                for (unsigned q = 1; q < t->nb; q++) if (t->b[q].n > t->b[best].n) best = q;
                if (!t->nb || !t->b[best].n) break;
                HMODULE hm = NULL; char mn[MAX_PATH] = "";
                if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                       GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                       (LPCSTR)(base + (t->b[best].rva & ~1ull)), &hm) &&
                    hm && (unsigned long long)hm != base) {
                    GetModuleFileNameA(hm, mn, sizeof mn);
                    const char* sl = strrchr(mn, '\\');
                    fprintf(stderr, "[ps-sample]   %s+0x%llX  %u\n", sl ? sl + 1 : mn,
                            base + t->b[best].rva - (unsigned long long)hm, t->b[best].n);
                } else
                    fprintf(stderr, "[ps-sample]   +0x%llX  %u\n", t->b[best].rva, t->b[best].n);
                t->b[best].n = 0;
            }
            CloseHandle(t->h);
        }
        /* The next round samples the threads that used the most CPU in this one. */
        int ncur = 0;
        HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        THREADENTRY32 te; te.dwSize = sizeof te;
        if (snap != INVALID_HANDLE_VALUE) {
            if (Thread32First(snap, &te)) do {
                if (te.th32OwnerProcessID != pid || te.th32ThreadID == me || ncur >= 1024) continue;
                HANDLE h = OpenThread(THREAD_QUERY_LIMITED_INFORMATION, FALSE, te.th32ThreadID);
                if (!h) continue;
                cur[ncur].tid = te.th32ThreadID; cur[ncur].cpu = thread_cpu_100ns(h);
                CloseHandle(h);
                cur[ncur].d = 0;
                for (int j = 0; j < nprev; j++)
                    if (prev[j].tid == cur[ncur].tid) { cur[ncur].d = cur[ncur].cpu - prev[j].cpu; break; }
                ncur++;
            } while (Thread32Next(snap, &te));
            CloseHandle(snap);
        }
        memcpy(prev, cur, sizeof(cur[0]) * (size_t)ncur); nprev = ncur;
        ns = 0;
        for (int pick = 0; pick < want; pick++) {
            int best = -1;
            for (int j = 0; j < ncur; j++)
                if (cur[j].d && (best < 0 || cur[j].d > cur[best].d)) best = j;
            if (best < 0) break;
            HANDLE h = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                                  FALSE, cur[best].tid);
            if (h) {
                s[ns].tid = cur[best].tid; s[ns].h = h; s[ns].cpu0 = thread_cpu_100ns(h);
                s[ns].nb = 0; s[ns].total = 0; ns++;
            }
            cur[best].d = 0;
        }
        round++;
        t0 = GetTickCount64();
    }
}

/* GT5P_SAMPLE=all: one table for the whole process. Threads are re-listed
 * every 250 ms and each is sampled about once a millisecond while it has used
 * CPU since its last sample, so short-lived threads (the job manager's lanes,
 * created for each dispatch) are counted too. Every 10 s the 80 busiest
 * buckets, in the same format, with round=N tid=0. */
/* Lane threads announce themselves (cellSpurs.c's g_spurs_lane_start_hook):
 * the sampler takes each handle from this ring on its next pass. */
extern "C" void (*g_spurs_lane_start_hook)(void);
static HANDLE s_lane_ring[1024];
static volatile LONG s_lane_ring_n = 0;
/* PS3_HOST_AVOID_PPU=1: the present thread and the job manager's lanes are
 * kept off the logical CPUs the guest PPU threads are pinned to
 * (sys_ppu_thread.c, PS3_PPU_PRIO_SCHED / PS3_PPU_CORES), so they do not take
 * time from them. An experiment (Phase 44). */
extern "C" DWORD_PTR ppu_sched_mask(void);
static DWORD_PTR host_avoid_mask(void)
{
    static int on = -1; static DWORD_PTR m = 0;
    if (on < 0) {
        on = getenv("PS3_HOST_AVOID_PPU") ? 1 : 0;
        if (on) {
            DWORD_PTR pm = 0, sm = 0;
            GetProcessAffinityMask(GetCurrentProcess(), &pm, &sm);
            DWORD_PTR ppu = ppu_sched_mask();
            if (!ppu) ppu = 3;   /* the default, before any guest thread set it */
            m = pm & ~ppu;
            fprintf(stderr, "[sched] PS3_HOST_AVOID_PPU: present thread and lanes on mask 0x%llX\n",
                    (unsigned long long)m);
        }
    }
    return on ? m : 0;
}
static void sampler_lane_hook(void);
static int s_sampler_lanes = 0;
static void lane_start_hook(void)
{
    DWORD_PTR m = host_avoid_mask();
    if (m) SetThreadAffinityMask(GetCurrentThread(), m);
    if (s_sampler_lanes) sampler_lane_hook();
}
static void sampler_lane_hook(void)
{
    HANDLE h = NULL;
    if (!DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &h,
                         0, FALSE, DUPLICATE_SAME_ACCESS)) return;
    LONG k = InterlockedIncrement(&s_lane_ring_n) - 1;
    HANDLE old = (HANDLE)InterlockedExchangePointer((PVOID volatile*)&s_lane_ring[k & 1023], h);
    if (old) CloseHandle(old);   /* the sampler fell 1,024 behind; drop the oldest */
}

static DWORD WINAPI sampler_all_thread(LPVOID)
{
    const unsigned long long base = (unsigned long long)GetModuleHandleW(NULL);
    const DWORD me = GetCurrentThreadId(), pid = GetCurrentProcessId();
    struct T { DWORD tid; HANDLE h; unsigned long long cpu; int seen, lane; };
    static T th[1024]; int nth = 0;
    /* Table 0: every thread but the lanes; table 1: the job manager's lanes. */
    struct B { unsigned long long rva; unsigned n; };
    static B bt[2][16384];
    unsigned nbt[2] = { 0, 0 }, tot[2] = { 0, 0 }; int round = 0;
    ULONGLONG t0 = GetTickCount64(), tl = 0;
    for (;;) {
        Sleep(1);
        const ULONGLONG now = GetTickCount64();
        if (now - tl >= 250) {
            tl = now;
            for (int i = 0; i < nth; i++) th[i].seen = 0;
            HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
            THREADENTRY32 te; te.dwSize = sizeof te;
            if (snap != INVALID_HANDLE_VALUE) {
                if (Thread32First(snap, &te)) do {
                    if (te.th32OwnerProcessID != pid || te.th32ThreadID == me) continue;
                    int k = 0;
                    for (; k < nth; k++) if (th[k].tid == te.th32ThreadID) { th[k].seen = 1; break; }
                    if (k == nth && nth < 1024) {
                        HANDLE h = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT |
                                              THREAD_QUERY_INFORMATION, FALSE, te.th32ThreadID);
                        if (h) { th[nth].tid = te.th32ThreadID; th[nth].h = h; th[nth].lane = 0;
                                 th[nth].cpu = thread_cpu_100ns(h); th[nth].seen = 1; nth++; }
                    }
                } while (Thread32Next(snap, &te));
                CloseHandle(snap);
            }
            for (int i = 0; i < nth; ) {
                if (!th[i].seen || WaitForSingleObject(th[i].h, 0) == WAIT_OBJECT_0) {
                    CloseHandle(th[i].h); th[i] = th[--nth]; continue; }
                i++;
            }
        }
        static LONG lane_taken = 0;
        while (lane_taken < s_lane_ring_n && nth < 1024) {
            HANDLE h = (HANDLE)InterlockedExchangePointer((PVOID volatile*)&s_lane_ring[lane_taken & 1023], NULL);
            lane_taken++;
            if (!h) continue;
            const DWORD tid = GetThreadId(h);
            int k = 0;
            for (; k < nth; k++) if (th[k].tid == tid) break;
            if (k < nth) { th[k].lane = 1; CloseHandle(h); continue; }
            th[nth].tid = tid; th[nth].h = h; th[nth].cpu = 0; th[nth].seen = 1; th[nth].lane = 1; nth++;
        }
        for (int i = 0; i < nth; i++) {
            const unsigned long long c = thread_cpu_100ns(th[i].h);
            if (c == th[i].cpu) continue;          /* idle since the last look */
            th[i].cpu = c;
            unsigned long long rva;
            if (!sample_rip(th[i].h, base, &rva)) continue;
            const int t = th[i].lane;
            B* b = bt[t]; unsigned& nb = nbt[t];
            unsigned k = 0;
            for (; k < nb; k++) if (b[k].rva == rva) { b[k].n++; break; }
            if (k == nb && nb < 16384) { b[k].rva = rva; b[k].n = 1; nb++; }
            tot[t]++;
        }
        if (GetTickCount64() - t0 < 10000) continue;
        for (int t = 0; t < 2; t++) {
        B* b = bt[t]; unsigned nb = nbt[t];
        fprintf(stderr, "[ps-sample] round=%d tid=%d cpu=%s %u samples, %u buckets, base 0x%llX\n",
                round, t, t ? "lanes" : "rest", tot[t], nb, base);
        for (int r = 0; r < 150; r++) {
            unsigned best = 0;
            for (unsigned q = 1; q < nb; q++) if (b[q].n > b[best].n) best = q;
            if (!nb || !b[best].n) break;
            HMODULE hm = NULL; char mn[MAX_PATH] = "";
            if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                   GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                   (LPCSTR)(base + (b[best].rva & ~1ull)), &hm) &&
                hm && (unsigned long long)hm != base) {
                GetModuleFileNameA(hm, mn, sizeof mn);
                const char* sl = strrchr(mn, '\\');
                fprintf(stderr, "[ps-sample]   %s+0x%llX  %u\n", sl ? sl + 1 : mn,
                        base + b[best].rva - (unsigned long long)hm, b[best].n);
            } else
                fprintf(stderr, "[ps-sample]   +0x%llX  %u\n", b[best].rva, b[best].n);
            b[best].n = 0;
        }
        }
        nbt[0] = nbt[1] = 0; tot[0] = tot[1] = 0; round++;
        t0 = GetTickCount64();
    }
}

extern "C" void gt5p_start_sampler(void)
{
    const char* e = getenv("GT5P_SAMPLE");
    if (!e) return;
    if (!strcmp(e, "all")) {
        s_sampler_lanes = 1;
        g_spurs_lane_start_hook = lane_start_hook;
        CreateThread(NULL, 0, sampler_all_thread, NULL, 0, NULL);
        return;
    }
    int n = atoi(e); if (n <= 0) n = 4; if (n > 8) n = 8;
    CreateThread(NULL, 0, sampler_thread, (LPVOID)(uintptr_t)n, 0, NULL);
}

extern "C" void gt5p_start_profview(void);
extern "C" void gt5p_pv_frame(double fifo_total, double pres_total, double pump_total);

static DWORD WINAPI present_thread(LPVOID)
{
    fprintf(stderr, "[hostthread] present hosttid=%lu\n", (unsigned long)GetCurrentThreadId());
    ps3_name_thread(L"present");
    gt5p_start_sampler();
    if (host_avoid_mask()) {
        SetThreadAffinityMask(GetCurrentThread(), host_avoid_mask());
        g_spurs_lane_start_hook = lane_start_hook;
    }
    const char* title = getenv("PS3_TITLE");
    if (!title || !*title) title = "Gran Turismo 5 Prologue (ps3recomp)";

    /* PS3_HEADLESS=1: no window (RDP / unattended runs), but the vblank and
     * flip clock and the FIFO drain still run, so the guest sees the same
     * timing it would with a display. */
    const int headless = getenv("PS3_HEADLESS") != NULL;
    int rsx_ok = !headless && (backend_init(title) == 0);
    fprintf(stderr, "[rsx] backend init %s\n",
            headless ? "skipped -- headless" : rsx_ok ? "OK -- window open" : "FAILED");
    const int drain = rsx_ok || headless;

    /* GT5P_PRESENT_PROF=1: every 5 s, where this thread's time went. */
    const int prof = getenv("GT5P_PRESENT_PROF") != nullptr;
    LARGE_INTEGER qf; QueryPerformanceFrequency(&qf);
    double p_vbl = 0, p_flip = 0, p_pres = 0, p_fifo = 0, p_pump = 0;
    unsigned p_ticks = 0, p_pres_n = 0;
    ULONGLONG p_last = GetTickCount64();
    /* Running totals of the same, never reset, for the profiler view
     * (gt5p_profview.cpp), which takes the difference at each present. */
    double c_p_vbl = 0, c_p_flip = 0, c_p_pres = 0, c_p_fifo = 0, c_p_pump = 0;
#define PROF_T(acc, stmt) do { LARGE_INTEGER a_, b_; QueryPerformanceCounter(&a_); stmt; QueryPerformanceCounter(&b_); double d_ = (double)(b_.QuadPart - a_.QuadPart) / qf.QuadPart; acc += d_; c_##acc += d_; } while (0)
    if (rsx_ok) gt5p_start_profview();

    /* GT5P_PRESENT_SLEEP=<ms>: the outer cadence, 4 by default. The FIFO is
     * only walked once per pass, so the sleep is time the guest's command
     * rings are not drained. */
    const char* sl = getenv("GT5P_PRESENT_SLEEP");
    const DWORD outer_sleep = sl ? (DWORD)atoi(sl) : 4;

    ULONGLONG next_tick = GetTickCount64();
    for (;;) {
        Sleep(outer_sleep);
        ULONGLONG now = GetTickCount64();

        /* Catch up on missed ticks, but not for longer than 100 ms at a
         * time: when one tick's work takes more than its 16 ms the backlog
         * never clears, and running 240 of them back to back kept this
         * thread away from the message pump for so long that Windows marked
         * the window "not responding". */
        int fired = 0;
        while ((long long)(now - next_tick) >= 0 && fired < 240) {
            PROF_T(p_vbl, cellGcmTickVBlank());
            PROF_T(p_flip, cellGcmTickFlip());
            if (rsx_ok && cellGcm_take_flip_pending()) {
                PROF_T(p_pres, backend_present()); p_pres_n++;
                gt5p_pv_frame(c_p_fifo, c_p_pres, c_p_pump);
            }
            if (drain)
                PROF_T(p_fifo, cellGcm_rsx_process_fifo());
            next_tick += 16;          /* ~60 Hz */
            fired++; p_ticks++;
            if (GetTickCount64() - now >= 100) { fired = 240; break; }
        }
        if (fired >= 240)
            next_tick = GetTickCount64();   /* fell behind -- resync */

        dump_threads();

        /* Drain again at the outer cadence: titles fence every render pass on
         * an RSX label the drain writes, and waiting a full 16 ms per fence
         * paces the guest to single-digit fps. */
        if (drain) {
            if (cellGcm_take_flip_pending() && rsx_ok) {
                PROF_T(p_pres, backend_present()); p_pres_n++;
                gt5p_pv_frame(c_p_fifo, c_p_pres, c_p_pump);
            }
            PROF_T(p_fifo, cellGcm_rsx_process_fifo());
        }
        if (rsx_ok) {
            int closed = 0;
            PROF_T(p_pump, closed = backend_pump());
            if (closed != 0)
                rsx_ok = 0;           /* window closed */
        }
        if (prof && GetTickCount64() - p_last >= 5000) {
            fprintf(stderr, "[present-prof] 5 s: ticks=%u presents=%u | vblank %.2fs flip %.2fs "
                            "present %.2fs fifo %.2fs pump %.2fs\n",
                    p_ticks, p_pres_n, p_vbl, p_flip, p_pres, p_fifo, p_pump);
            p_vbl = p_flip = p_pres = p_fifo = p_pump = 0; p_ticks = p_pres_n = 0;
            p_last = GetTickCount64();
        }
    }
}

extern "C" void gt5p_start_present_thread(void)
{
    if (getenv("GT5P_NO_PRESENT")) {
        printf("[GT5P] GT5P_NO_PRESENT: headless, no present thread\n");
        return;
    }
    CreateThread(NULL, 4u * 1024 * 1024, present_thread, NULL, 0, NULL);
    printf("[GT5P] present thread started (60 Hz vblank/flip ticker)\n");
}
