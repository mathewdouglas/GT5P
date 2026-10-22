/* Address reuse after a glyph atlas must not discard a scene's depth clear. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rsx_commands.h"
static u32 s_mask_zeta_off;
#include "clear_helpers.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)
int main(void)
{
    rsx_state st = {0};
    const char* e = getenv("RSX_DEPTH_CLEAR_REUSE");
    int fixed = !e || strcmp(e, "0");
    CHECK(depth_clear_flags(NULL, 3) == 0);
    CHECK(depth_clear_flags(&st, 3) == 0);
    st.surface_zeta_offset = 0x100000;
    st.color_mask = 0x01010101;
    CHECK(depth_clear_flags(&st, 3) == 3);
    CHECK(depth_clear_flags(&st, 0xf0) == 0);
    /* A mask was generated in the same allocation during a previous pass.
     * The next mirror pass uses that allocation as real scene depth. */
    s_mask_zeta_off = st.surface_zeta_offset;
    CHECK(depth_clear_flags(&st, 1) == (fixed ? 1u : 0u));
    CHECK(depth_clear_flags(&st, 3) == (fixed ? 1u : 0u));
    CHECK(depth_clear_flags(&st, 2) == 0); /* stencil retains its colour substitute */
    st.stencil_test_enable = 1;
    st.color_mask = 0;
    CHECK(depth_clear_flags(&st, 3) == 0); /* actual mask drawing unchanged */
    st.color_mask = 0x01010101;
    CHECK(depth_clear_flags(&st, 1) == (fixed ? 1u : 0u));
    st.surface_zeta_offset += 0x10000;
    CHECK(depth_clear_flags(&st, 3) == 3); /* independent depth/stencil unaffected */
    puts(fixed ? "PASS: reused glyph allocation preserves scene depth clears" :
                 "PASS: rollback reproduces discarded depth clears");
    return 0;
}
