#!/usr/bin/env python3
"""Centre the menus' label fade mask in ultrawide.

The text renderer (func_00768340 on BCUS98158) turns a label strip's rectangle,
given in the menus' 16:9 layout pixels, into the fade mask its vertex program
reads (c[131]): x0 = rect.x / (W/2) - 1, with W the screen width it works in.
That assumes the layout fills the screen. With the ultrawide UI aspect the
menus are laid out 16:9 and centred in a wider W (2560 at 64/27), the menus'
projection says so (x offset -0.75), but this one subtraction still uses 1.0:
the mask sits a quarter of the screen to the left and the My Page labels fade
out early ("2P Battle" cut, "Events" missing). The right offset is the
layout's share of the screen, (H * 16/9) / W, which is exactly 1 at 16:9.

The listed function's `fpr[13] - fpr[31]` (31 holds 1.0) becomes a call to
gt5p_ui_mask_x (src/gt5p_uifix.cpp), handed W (fpr[30]) and H (fpr[29]).
GT5P_UI_MASK_FIX=0 at run time keeps 1.0. Config: "ui_label_mask_func" in
config/targets.json.

Run after every re-lift, with setjmp_patch.py and spin_patch.py; generated/
is not in the repo.

    python scripts/ui_mask_patch.py            # patch (idempotent)
    python scripts/ui_mask_patch.py --check    # report, change nothing
    python scripts/ui_mask_patch.py --restore  # undo
"""
import re
import sys
from pathlib import Path

import target

GEN = Path(__file__).resolve().parent.parent / "generated"
MARK = "/* ui_mask_patch */"
DECL = 'extern "C" double gt5p_ui_mask_x(double w, double h, double one); ' + MARK + "\n"
ORIG = ("        ctx->fpr[13] = ppu_fp_single(ppu_fsub(ctx->fpr[13], ctx->fpr[31]));\n"
        "        ctx->fpr[11] = -ctx->fpr[12];\n")
NEW = ("        ctx->fpr[13] = ppu_fp_single(ppu_fsub(ctx->fpr[13], "
       "gt5p_ui_mask_x(ctx->fpr[30], ctx->fpr[29], ctx->fpr[31]))); " + MARK + "\n"
       "        ctx->fpr[11] = -ctx->fpr[12];\n")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = target.TARGET.get("ui_label_mask_func")
    if not fn:
        print(f"no ui_label_mask_func for {target.NAME}")
        return
    head = "void func_%08X(ppu_context* ctx) {" % int(fn, 16)
    for f in sorted(GEN.glob("ppu_recomp_*.cpp")):
        text = f.read_text(encoding="utf-8", errors="surrogateescape")
        start = text.find(head)
        if start < 0:
            continue
        end = text.find("\n}\n", start) + 3
        body = text[start:end]
        patched = MARK in body
        if mode == "--check":
            print(f"{head[5:18]} ({f.name}): {'patched' if patched else 'NOT patched'}")
            return
        if mode == "--restore":
            if not patched:
                print(f"{head[5:18]}: not patched")
                return
            body = body.replace(NEW, ORIG)
            text = (text[:start] + body + text[end:]).replace(DECL, "")
            print(f"{head[5:18]}: restored")
        else:
            if patched:
                print(f"{head[5:18]}: already patched")
                return
            if body.count(ORIG) != 1:
                raise SystemExit(f"{head[5:18]}: expected the mask subtraction once, found {body.count(ORIG)}")
            body = body.replace(ORIG, NEW)
            text = text[:start] + body + text[end:]
            last = 0
            for m in re.finditer(r"^#include [^\n]*\n", text, re.M):
                if m.start() > 4000:
                    break
                last = m.end()
            text = text[:last] + DECL + text[last:]
            print(f"{head[5:18]}: label mask origin patched")
        f.write_text(text, encoding="utf-8", errors="surrogateescape", newline="")
        return
    raise SystemExit(f"{head} not found in generated/")


if __name__ == "__main__":
    main()
