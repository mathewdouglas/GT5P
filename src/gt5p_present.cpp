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

#include "ppu_context.h"
#include "sys_ppu_thread.h"
#include "vm.h"

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

static DWORD WINAPI present_thread(LPVOID)
{
    fprintf(stderr, "[hostthread] present hosttid=%lu\n", (unsigned long)GetCurrentThreadId());
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

    ULONGLONG next_tick = GetTickCount64();
    for (;;) {
        Sleep(4);
        ULONGLONG now = GetTickCount64();

        int fired = 0;
        while ((long long)(now - next_tick) >= 0 && fired < 240) {
            cellGcmTickVBlank();
            cellGcmTickFlip();
            if (rsx_ok && cellGcm_take_flip_pending())
                backend_present();
            if (drain)
                cellGcm_rsx_process_fifo();
            next_tick += 16;          /* ~60 Hz */
            fired++;
        }
        if (fired >= 240)
            next_tick = now;          /* fell far behind -- resync */

        dump_threads();

        /* Drain again at the outer cadence: titles fence every render pass on
         * an RSX label the drain writes, and waiting a full 16 ms per fence
         * paces the guest to single-digit fps. */
        if (drain) {
            if (cellGcm_take_flip_pending() && rsx_ok)
                backend_present();
            cellGcm_rsx_process_fifo();
        }
        if (rsx_ok) {
            if (backend_pump() != 0)
                rsx_ok = 0;           /* window closed */
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
