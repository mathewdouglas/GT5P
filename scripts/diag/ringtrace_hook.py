# Ring-allocation trace for the render job b01376080 (Phase 73). Hooks its
# ring-space check (0x4598) and its job end (0x14E98) with calls to
# spurs_ring_trace (ps3recomp runtime/spu/spurs_policy.c); the stall dump then
# prints each render lane's last 512 allocations: head, wanted end, label read.
#   .venv\Scripts\python scripts\diag\ringtrace_hook.py      (then rebuild)
#   .venv\Scripts\python scripts\diag\spufn_count.py --restore b01376080
# Backs the file up as .sfc_orig. It perturbs timing: stalls get rarer.
import os, shutil
p = os.path.join(os.path.dirname(__file__), "..", "..", "generated", "spu_lifted", "b01376080", "spu_recomp.c")
bak = p + ".sfc_orig"
if os.path.exists(bak):
    raise SystemExit("already patched: restore first")
src = open(p, encoding="latin-1", newline="").read()
NL = "\r\n" if "\r\n" in src else "\n"
anchor = "        ctx->gpr[50] = spu_rotqby(ctx->gpr[51], ctx->gpr[80]);" + NL
i = src.find("void gt5p_b01376080_spu_func_00004598(")
j = src.find(anchor, i)
assert i >= 0 and j >= 0
hook = NL.join([
    "        { extern void spurs_ring_trace(const spu_context*, uint32_t, uint32_t, uint32_t, uint32_t, int);",
    "          uint32_t _l = ctx->gpr[50]._u32[0], _h = ctx->gpr[12]._u32[0], _w = ctx->gpr[5]._u32[0];",
    "          spurs_ring_trace(ctx, _h, _w, _l, ctx->gpr[20]._u32[0], _l > _h && _l <= _w); }",
]) + NL
src = src[:j + len(anchor)] + hook + src[j + len(anchor):]
# Job end (0x14E98, called once per job from 0x7C04): a marker with the
# ring head and label as the job reaches it.
k = src.find("void gt5p_b01376080_spu_func_00014E98(spu_context* ctx) {" + NL)
assert k >= 0
k = src.find(NL, k) + len(NL)
end_hook = NL.join([
    "        { extern void spurs_ring_trace(const spu_context*, uint32_t, uint32_t, uint32_t, uint32_t, int);",
    "          const uint8_t* _q = ctx->ls + 0x1F000;",
    "          #define _BE(p) ((uint32_t)(p)[0] << 24 | (uint32_t)(p)[1] << 16 | (uint32_t)(p)[2] << 8 | (p)[3])",
    "          spurs_ring_trace(ctx, _BE(_q + 0x88), 0, _BE(_q), _BE(_q + 0x8C), 2);",
    "          #undef _BE",
    "        }",
]) + NL
src = src[:k] + end_hook + src[k:]
shutil.copy2(p, bak)
open(p, "w", encoding="latin-1", newline="").write(src)
print("hooked", p)
