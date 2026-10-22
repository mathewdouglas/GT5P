/* Native replacements hooked into lifted SPU job code (Phase 110).
 *
 * scripts/spu_native_patch.py puts a call to each function here at the top of
 * a lifted block ("spu_native_hooks" in config/targets.json). A replacement
 * only moves the guest state forward over work it can do natively and leaves
 * the block itself to finish, so every register still ends as the lifted
 * code leaves it.
 *
 * GT5P_SPU_NATIVE: 0 off; 1 on (default); 2 check: compute the result
 * natively, change nothing, and compare with what the lifted code then does.
 * GT5P_SPU_NATIVE_STATS=1 prints counts every 5 s (always on in check mode).
 */
#include "spu_context.h"
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static volatile int s_mode = -1, s_stats = 0;

static int native_mode(void)
{
    int m = s_mode;
    if (m < 0) {
        const char* e = getenv("GT5P_SPU_NATIVE");
        m = e ? atoi(e) : 1;
        s_stats = m == 2 || getenv("GT5P_SPU_NATIVE_STATS") != NULL;
        s_mode = m;
        if (m) fprintf(stderr, "[spu-native] mode %d%s%c", m, m == 2 ? " (check)" : "", 10);
    }
    return m;
}

static volatile long long s_walks, s_skipped, s_ok, s_bad;

static void native_report(void)
{
    static volatile unsigned long long t0;
    struct timespec ts; timespec_get(&ts, TIME_UTC);
    unsigned long long now = (unsigned long long)ts.tv_sec * 1000u + (unsigned long long)ts.tv_nsec / 1000000u;
    unsigned long long was = t0;
    if (!was) { __atomic_compare_exchange_n(&t0, &was, now, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED); return; }
    if (now - was < 5000 || !__atomic_compare_exchange_n(&t0, &was, now, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED))
        return;
    fprintf(stderr, "[spu-native] sorted walk: %lld walks, %lld nodes skipped natively; check %lld ok, %lld wrong%c",
            __atomic_exchange_n(&s_walks, 0, __ATOMIC_RELAXED), __atomic_exchange_n(&s_skipped, 0, __ATOMIC_RELAXED),
            __atomic_exchange_n(&s_ok, 0, __ATOMIC_RELAXED), __atomic_exchange_n(&s_bad, 0, __ATOMIC_RELAXED), 10);
}

/* A halfword or word of local store as rotqby takes it from the quadword
 * holding `a`: bytes past the quadword's end wrap to its start. */
static inline uint32_t ls_u16q(const uint8_t* ls, uint32_t a)
{
    uint32_t q = a & (SPU_LS_MASK & ~0xFu), o = a & 0xFu;
    if (__builtin_expect(o <= 14, 1)) { uint16_t v; memcpy(&v, ls + q + o, 2); return __builtin_bswap16(v); }
    return ((uint32_t)ls[q + o] << 8) | ls[q + ((o + 1) & 0xFu)];
}
static inline float ls_f32q(const uint8_t* ls, uint32_t a)
{
    uint32_t q = a & (SPU_LS_MASK & ~0xFu), o = a & 0xFu;
    if (__builtin_expect(o <= 12, 1)) {
        uint32_t v; memcpy(&v, ls + q + o, 4); v = __builtin_bswap32(v);
        float f; memcpy(&f, &v, 4); return f;
    }
    uint32_t w = ((uint32_t)ls[q + o] << 24) | ((uint32_t)ls[q + ((o + 1) & 0xFu)] << 16) |
                 ((uint32_t)ls[q + ((o + 2) & 0xFu)] << 8) | ls[q + ((o + 3) & 0xFu)];
    float f; memcpy(&f, &w, 4); return f;
}

/* Job body 0x0133A700, blocks 0x43E0/0x43E8/0x4420: inserting a node into a
 * list kept in descending order of a float key. r7 is the node the walk is
 * at; the next node's index is the halfword at +66 (0xFFFF ends the list);
 * nodes are 68 bytes from r13; the key is the float at +60; r12 holds the new
 * node's key. The walk moves on while the new key is not greater than the
 * next node's (fcgt), then 0x4420 links the new node in after r7. 40% of the
 * race's one-SPU workloads 5/6 ran this walk, one node per pass through the
 * lifted blocks.
 *
 * Natively: find the node the walk would stop at, and set r7 to the node one
 * step before it. The lifted code then takes that last step (which writes
 * every register an advancing pass writes) and the final test, so every
 * register ends as before. Nothing is written to local store. */
static _Thread_local int t_pending;
static _Thread_local uint32_t t_expect;

void gt5p_spu_sorted_walk(spu_context* ctx)
{
    const int mode = native_mode();
    if (!mode || (mode == 2 && t_pending)) return;
    const uint8_t* ls = ctx->ls;
    const uint32_t base = ctx->gpr[13]._u32[0];
    const float key = ctx->gpr[12]._f32[0];
    uint32_t p = ctx->gpr[7]._u32[0], back1 = p;
    unsigned n = 0;
    for (; n < 0x10000u; n++) {
        uint32_t nx = ls_u16q(ls, p + 66);
        if (nx == 0xFFFFu) break;
        uint32_t q = base + (uint32_t)((int32_t)(int16_t)nx * 68);
        if (key > ls_f32q(ls, q + 60)) break;
        back1 = p; p = q;
    }
    if (mode == 2) {
        t_pending = 1; t_expect = p;
        __atomic_fetch_add(&s_walks, 1, __ATOMIC_RELAXED);
        native_report();
        return;
    }
    if (n >= 2) ctx->gpr[7]._u32[0] = back1;   /* the lifted code takes the last step */
    if (s_stats) {
        __atomic_fetch_add(&s_walks, 1, __ATOMIC_RELAXED);
        if (n >= 2) __atomic_fetch_add(&s_skipped, n - 1, __ATOMIC_RELAXED);
        native_report();
    }
}

/* 0x4420, where the walk ends: in check mode, the node it actually stopped at
 * against the native answer. */
void gt5p_spu_sorted_walk_end(spu_context* ctx)
{
    if (s_mode != 2 || !t_pending) return;
    t_pending = 0;
    if (ctx->gpr[7]._u32[0] == t_expect) __atomic_fetch_add(&s_ok, 1, __ATOMIC_RELAXED);
    else {
        long long b = __atomic_fetch_add(&s_bad, 1, __ATOMIC_RELAXED);
        if (b < 8)
            fprintf(stderr, "[spu-native] sorted walk MISMATCH: lifted stopped at 0x%05X, native 0x%05X%c",
                    ctx->gpr[7]._u32[0], t_expect, 10);
    }
}
