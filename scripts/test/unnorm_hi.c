/* Compile the backend's actual pure helpers, extracted by unnorm_hi_extract.py,
 * without linking the renderer or creating a GPU device. */
#include "backend_helpers.h"
#include <assert.h>

int main(void)
{
    D3D12DrawRecord draw = {0};
    for (int u = 0; u < 16; ++u) {
        draw.tex[u].set = 1;
        draw.tex[u].fmt = 0xE5;
        draw.tex[u].w = 16;
        draw.tex[u].h = 8;
    }
    draw.tex[5].cube = 1;
    draw.tex[6].fmt = 0xA5; /* normalised */
    draw.tex[7].h = 0;
    draw.tex[8].set = 0;
    const char* en = getenv("RSX_UNNORM_HI");
    int disabled = (en && !strcmp(en, "0")) || getenv("RSX_NO_UNNORM");
    assert(dr_unnorm_hi(&draw) == (disabled ? 0u : (0xFFF0u & ~0x1E0u)));

    for (int u = 4; u < 16; ++u) {
        char text[2048], expected[128];
        snprintf(text, sizeof text,
            "a=rsx_tex[%d].Sample(rsx_samp[4], input.position.xy);"
            "b=rsx_tex[%d].SampleLevel(rsx_samp[4], uv.xy, 2.0);"
            "c=rsx_tex[%d].SampleBias(rsx_samp[4], uv.xy, -0.5);", u, u, u);
        assert(fp_scale_unit(text, sizeof text, u, 0, NULL) == 3);
        snprintf(expected, sizeof expected, "input.position.xy * rsx_texscale_hi[%d].%s",
                 (u-4)/2, u & 1 ? "zw" : "xy");
        assert(strstr(text, expected));
        snprintf(expected, sizeof expected, "uv.xy * rsx_texscale_hi[%d].%s, 2.0",
                 (u-4)/2, u & 1 ? "zw" : "xy");
        assert(strstr(text, expected));
        assert(!strstr(text, "rsx_TEX"));
    }
    char low[256] = "rsx_tex0.Sample(rsx_samp[0], uv.xy)";
    assert(fp_scale_unit(low, sizeof low, 0, 0, NULL) == 1);
    assert(strstr(low, " * rsx_texscale[0].xy + rsx_texscale[0].zw"));

    VPFPEntry a = {0}, b = {0};
    assert(fp_key_eq(&a, &b));
    b.unhi = 1u << 15;
    assert(!fp_key_eq(&a, &b));
    assert(fp_key_hash(&a) != fp_key_hash(&b));
    puts("Upper-unit coordinate, sampler and pipeline-key checks passed.");
    return 0;
}
