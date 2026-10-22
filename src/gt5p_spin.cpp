/* Back-edge hook for guest spin waits (scripts/spin_patch.py).
 *
 * Guest PPU threads share two host CPUs (PS3_PPU_PRIO_SCHED=2). A guest loop
 * that waits for an SPU job list by re-reading memory, with no syscall, holds
 * one of them for the whole wait at its host priority; the main thread, at
 * guest priority 2048 (host IDLE), then got no time on it. Here a wait pauses
 * for a few iterations, yields, and then sleeps in short high-resolution
 * steps, so other guest threads run while the SPUs finish. Waking costs at
 * most about one step (GT5P_SPIN_SLEEP_US, default 100, 10..2000).
 * GT5P_SPIN_YIELD=0: pause only, close to the original spin. */
#include <windows.h>
#include <immintrin.h>
#include <stdint.h>
#include <stdlib.h>
#include "ps3emu/timeline.h"   /* PS3_TIMELINE: each sleeping step (kind Q) */

#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 0x00000002
#endif

extern "C" void gt5p_spin_pause(uint32_t* n)
{
    static int yield = -1;
    static LONGLONG step_100ns;
    if (yield < 0) {
        const char* s = getenv("GT5P_SPIN_SLEEP_US");
        long us = s ? atol(s) : 100;
        step_100ns = (us < 10 ? 10 : us > 2000 ? 2000 : us) * 10;
        const char* e = getenv("GT5P_SPIN_YIELD");
        yield = !(e && *e == '0');
    }
    const uint32_t i = (*n)++;
    if (!yield || i < 32) { _mm_pause(); return; }
    if (i < 64) { SwitchToThread(); return; }
    static thread_local HANDLE timer = CreateWaitableTimerExW(
        nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    if (!timer) { Sleep(0); return; }
    LARGE_INTEGER due; due.QuadPart = -step_100ns;
    const uint64_t t0 = g_tl_on ? ps3_tl_us() : 0;
    SetWaitableTimer(timer, &due, 0, nullptr, nullptr, FALSE);
    WaitForSingleObject(timer, INFINITE);
    if (t0) ps3_tl_rec('Q', i, (uint32_t)(ps3_tl_us() - t0));
}
