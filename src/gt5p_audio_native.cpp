/* CPU selection stays in a baseline TU; only the alternate audio images use
 * AVX/FMA. Register at bootstrap, before any SPU runs or caches a lookup. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#ifdef GT5P_HAVE_AUDIO_NATIVE
#include <intrin.h>
#include "spu_workload.h"
#include "spu_interp.h"
#define AUDIO_IMAGE(name) \
    extern "C" void gt5p_audio_##name##_spu_func_00000000(spu_context*); \
    extern "C" void gt5p_audio_##name##_spu_recomp_register(void)
AUDIO_IMAGE(j307E5DC7);
AUDIO_IMAGE(j65DD2F53);
AUDIO_IMAGE(j8AAB90A4);
#undef AUDIO_IMAGE

static __attribute__((target("xsave"), noinline)) uint64_t audio_xcr0() { return _xgetbv(0); }
static int registering_image;
static unsigned found, missing;
static bool installing;

extern "C" void gt5p_audio_register_function(uint32_t addr, spu_lifted_fn fn)
{
    if (spu_override_function(registering_image, addr, installing ? fn : nullptr)) ++found;
    else ++missing;
}
#endif

extern "C" void gt5p_audio_select_native(void)
{
#ifdef GT5P_HAVE_AUDIO_NATIVE
    const char* e = getenv("GT5P_AUDIO_NATIVE");
    if (e && *e == '0') return;
    int cpu[4]; __cpuidex(cpu, 1, 0);
    constexpr unsigned required = (1u << 12) | (1u << 27) | (1u << 28);
    if (((unsigned)cpu[2] & required) != required || (audio_xcr0() & 6) != 6) {
        printf("[audio-native] FMA unavailable to CPU/OS; keeping portable audio\n");
        return;
    }
    const struct {
        uint64_t fingerprint; int image; const char* name;
        spu_lifted_entry_fn entry; void (*register_all)(void);
    } images[] = {
        {0x307E5DC790A6786DULL, 4, "j307E5DC7", gt5p_audio_j307E5DC7_spu_func_00000000, gt5p_audio_j307E5DC7_spu_recomp_register},
        {0x65DD2F533DE508CBULL, 7, "j65DD2F53", gt5p_audio_j65DD2F53_spu_func_00000000, gt5p_audio_j65DD2F53_spu_recomp_register},
        {0x8AAB90A4679785DAULL, 9, "j8AAB90A4", gt5p_audio_j8AAB90A4_spu_func_00000000, gt5p_audio_j8AAB90A4_spu_recomp_register},
    };
    for (const auto& image : images) {
        int actual = 0;
        if (!spu_workload_find_img(image.fingerprint, &actual) || actual != image.image) continue;
        registering_image = actual; installing = false; found = missing = 0;
        image.register_all();
        if (missing || !found) {
            fprintf(stderr, "[audio-native] %s registry mismatch; keeping portable image\n", image.name);
            continue;
        }
        installing = true; found = missing = 0;
        image.register_all();
        spu_workload_register_img(image.fingerprint, image.entry, actual, image.name);
        printf("[audio-native] %s: %u native functions, image %d\n", image.name, found, actual);
    }
#endif
}
