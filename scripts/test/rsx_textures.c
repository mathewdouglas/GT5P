/* Synthetic RSX shader streams only: no title code or assets. */
#include "libs/video/rsx_fp_decompiler.c"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %d: %s\n", __LINE__, #x); return 1; } } while (0)

static void word(u8* p, u32 w)
{
    u32 be = (w << 16) | (w >> 16);
    p[0] = (u8)(be >> 24); p[1] = (u8)(be >> 16);
    p[2] = (u8)(be >> 8); p[3] = (u8)be;
}
int main(void)
{
    u8 code[96] = {0};
    /* An inline constant that looks like a TEX must not become a binding. */
    word(code, 1u << 24); word(code + 4, 2);
    word(code + 16, (0x17u << 24) | (7u << 17) | 1u);
    word(code + 32, (0x17u << 24) | (15u << 17));
    word(code + 48, (0x18u << 24) | (4u << 17));
    word(code + 64, (0x2Fu << 24) | (1u << 17) | 1u);
    CHECK(rsx_fp_texture_mask(code, 80) == ((1u << 15) | (1u << 4) | (1u << 1)));
    CHECK(rsx_fp_texture_mask(code, 64) == 0xFFFFu);
    CHECK(rsx_fp_texture_mask(code, 16) == 0xFFFFu);
    CHECK(rsx_fp_texture_mask(NULL, 0) == 0xFFFFu);
    u32 size, legacy;
    u64 identity = rsx_fp_code_identity_cached(0x12300, code, 80, &size, &legacy);
    CHECK(identity && size == 80);
    u8 moved[80]; memcpy(moved, code, sizeof moved);
    CHECK(rsx_fp_code_identity_cached(0x13300, moved, 80, &size, &legacy) == identity);
    word(code + 16, 0x12345678u); /* Per-draw constant values do not change code identity. */
    CHECK(rsx_fp_code_identity_cached(0x12300, code, 80, &size, &legacy) == identity);
    word(code + 32, (0x17u << 24) | (14u << 17));
    CHECK(rsx_fp_code_identity_cached(0x12300, code, 80, &size, &legacy) != identity);
    word(code, 1u); word(code + 4, 0);
    CHECK(rsx_fp_texture_mask(code, 16) == 0);

    u64 bank = 0;
    for (u32 u = 0; u < 16; u++) bank |= (u64)u << (4 * u);
    bank = (bank & ~((u64)15 | ((u64)15 << 52))) | 13u | ((u64)5 << 52);
    char text[256] = "SamplerState rsx_samp[16]; Texture.Sample(rsx_samp[0], uv);"
                     "Texture.Sample(rsx_samp13, uv); Texture.Sample(rsx_samp[15], uv);";
    CHECK(rsx_fp_apply_sampler_map(text, sizeof text, bank) == 3);
    CHECK(strstr(text, "SamplerState rsx_samp[16]"));
    CHECK(strstr(text, "Texture.Sample(rsx_samp[13], uv)")); /* No 0 -> 13 -> 5 cascade. */
    CHECK(strstr(text, "Texture.Sample(rsx_samp5, uv)"));
    CHECK(strstr(text, "Texture.Sample(rsx_samp[15], uv)"));
    char tight[12] = "rsx_samp[0]";
    CHECK(rsx_fp_apply_sampler_map(tight, sizeof tight, bank) == -1);
    puts("PASS: sampled-unit masks, constant skipping, conservative malformed-code handling and all-unit sampler remapping");
    return 0;
}
