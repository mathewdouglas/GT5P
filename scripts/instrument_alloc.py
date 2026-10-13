#!/usr/bin/env python3
"""Wrap a lifted function so its arguments and return value can be logged.

The runtime's dispatch-table override only intercepts *indirect* calls; a `bl`
in lifted code calls `func_XXXXXXXX` directly and never looks the address up.
So to see what a lifted function is handed and what it hands back, the wrapper
has to go in beside it, in the generated source.

    python scripts/instrument_alloc.py 0094FF30 [more addrs...]

renames `func_0094FF30` to `gt5p_orig_func_0094FF30` in whichever chunk defines
it and appends a same-named wrapper that calls the original, drains the
trampoline chain so `r3` is final, and reports (r3, r4, r5) in and r3 out to
`gt5p_alloc_note()` in src/gt5p_allocwatch.cpp.

Idempotent, and re-run it after every re-lift — `generated/` is regenerated
wholesale and is not in the repo.
"""
import re
import sys
from pathlib import Path

GEN = Path(__file__).resolve().parent.parent / "generated"

WRAPPER = '''
/* ---- instrument_alloc.py: {name} ------------------------------------- */
extern "C" void gt5p_alloc_note(const char* who, uint32_t a3, uint32_t a4,
                                uint32_t a5, uint32_t ret);
extern "C" uint32_t gt5p_alloc_pre(const char* who, uint32_t a3, uint32_t a4,
                                   uint32_t a5);
extern "C" void gt5p_alloc_call_note(const char* who, uint64_t tid, uint64_t lr,
                                     uint32_t a3, uint32_t a4, uint32_t a5,
                                     uint32_t a6, uint32_t ret);

void {name}(ppu_context* ctx)
{{
    uint64_t entry_lr = ctx->lr;
    uint64_t entry_tid = ctx->thread_id;
    uint32_t a3 = (uint32_t)ctx->gpr[3];
    uint32_t a4 = (uint32_t)ctx->gpr[4];
    uint32_t a5 = (uint32_t)ctx->gpr[5];
    uint32_t a6 = (uint32_t)ctx->gpr[6];
    uint32_t pre_end = 0;
    if (strcmp("{name}", "func_00B3D458") == 0 && a4 >= 0x20000000u)
        pre_end = vm_read32(a4 + 4);
    if (strcmp("{name}", "func_007D3008") == 0 && getenv("GT5P_ARENA_TRACE") &&
        (entry_lr == 0x007F2FF4 || entry_lr == 0x007F3568 ||
         entry_lr == 0x007F3588 || a5 >= 0x1000)) {{
        fprintf(stderr, "[d-arena:entry] lr=%08llX arena=%08X base=%08X cur=%08X out=%08X old=%08X size=%08X\\n",
                (unsigned long long)entry_lr, a3, vm_read32(a3), vm_read32(a3 + 4),
                a4, a4 ? vm_read32(a4) : 0, a5);
    }}
{list_trace}
    /* Pre-hook may rewrite the size argument (GT5P_HEAPPAD); a3/a5 above are
       still the values the caller passed, which is what the log wants. */
    ctx->gpr[4] = gt5p_alloc_pre("{name}", a3, a4, a5);
    gt5p_orig_{name}(ctx);
    /* Drain here so r3 is the final return value and not a mid-chain state;
       the caller's own DRAIN_TRAMPOLINE then finds nothing left to do. */
    DRAIN_TRAMPOLINE(ctx);
    if (strcmp("{name}", "func_007D3008") == 0 && getenv("GT5P_ARENA_TRACE") &&
        (entry_lr == 0x007F2FF4 || entry_lr == 0x007F3568 ||
         entry_lr == 0x007F3588 || a5 >= 0x1000)) {{
        fprintf(stderr, "[d-arena:exit ] lr=%08llX arena=%08X base=%08X cur=%08X out=%08X val=%08X size=%08X ret=%08X\\n",
                (unsigned long long)entry_lr, a3, vm_read32(a3), vm_read32(a3 + 4),
                a4, a4 ? vm_read32(a4) : 0, a5, (uint32_t)ctx->gpr[3]);
    }}
    gt5p_alloc_call_note("{name}", entry_tid, entry_lr, a3, a4, a5,
                         a6, (uint32_t)ctx->gpr[3]);
    if (strcmp("{name}", "func_00B3D458") == 0 && pre_end < 0x20000000u) {{
        fprintf(stderr, "[SPLIT-BAD] tid=%llu caller=0x%08llX heap=%08X node=%08X "
                        "old_end=%08X size=%08X align=%08X new_end=%08X ret=%08X\\n",
                (unsigned long long)entry_tid, (unsigned long long)entry_lr,
                a3, a4, pre_end, a5, a6, vm_read32(a4 + 4),
                (uint32_t)ctx->gpr[3]);
        fflush(stderr);
    }}
    gt5p_alloc_note("{name}", a3, a4, a5, (uint32_t)ctx->gpr[3]);
}}
'''


def instrument(addr):
    name = f"func_{addr.upper()}"
    define = f"void {name}(ppu_context* ctx) {{"
    for chunk in sorted(GEN.glob("ppu_recomp_*.cpp")):
        text = chunk.read_text(encoding="utf-8", errors="replace")
        if f"gt5p_orig_{name}" in text:
            print(f"  {name}: already instrumented in {chunk.name}")
            return True
        if define not in text:
            continue
        text = text.replace(define, f"void gt5p_orig_{name}(ppu_context* ctx) {{", 1)
        # The forward declarations live in ppu_recomp.h; add one for the
        # renamed original so the wrapper below can call it.
        text = text.replace("void gt5p_orig_" + name,
                            f"void gt5p_orig_{name}(ppu_context* ctx);\nvoid gt5p_orig_" + name, 1)
        trace = ""
        if addr.upper() in {"00B3D158", "00B3D1E8"}:
            trace = '''    /* Optional snapshot of allocator free-list transitions. */
    static unsigned list_n = 0;
    const char* list_env = getenv("GT5P_LIST_TRACE");
    uint32_t node = a4;
    if (list_env && *list_env && (node >= 0x20000000u || node < 0x10000u)
        && list_n++ < 4096) {
        fprintf(stderr, "[LIST] %s tid=%llu caller=0x%08llX heap=0x%08X node=0x%08X "
                        "words=%08X %08X %08X %08X\\n",
                "{name}", (unsigned long long)ctx->thread_id,
                (unsigned long long)ctx->lr, a3, node,
                vm_read32(node), vm_read32(node + 4),
                vm_read32(node + 8), vm_read32(node + 12));
        fflush(stderr);
    }
'''.replace("{name}", name)
        trace = trace.replace("{", "{{").replace("}", "}}")
        chunk.write_text(text + WRAPPER.format(name=name, list_trace=trace), encoding="utf-8")
        print(f"  {name}: wrapped in {chunk.name}")
        return True
    print(f"  {name}: NOT FOUND in any chunk", file=sys.stderr)
    return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    ok = all(instrument(re.sub(r"^0x", "", a)) for a in sys.argv[1:])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
