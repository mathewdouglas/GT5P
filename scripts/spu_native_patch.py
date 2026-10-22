#!/usr/bin/env python3
"""Hook native replacements into lifted SPU job code.

Each entry of "spu_native_hooks" in config/targets.json is
[image directory, block address, host function]: the lifted block
generated/spu_lifted/<image>/spu_recomp.c:..._spu_func_<block> gets a call to
that function (src/gt5p_spu_native.c) as its first statement. The function
may advance the guest state past work it does natively; it must leave the
lifted block to finish so every register ends as the lifted code leaves it.
GT5P_SPU_NATIVE at run time: 0 off, 1 on (default), 2 check (compute natively,
compare against what the lifted code then does, change nothing).

Run after every SPU lift or --chain, with spin_patch.py; generated/ is not in
the repo.

    python scripts/spu_native_patch.py            # patch (idempotent)
    python scripts/spu_native_patch.py --check    # report, change nothing
    python scripts/spu_native_patch.py --restore  # undo
"""
import sys
from pathlib import Path

import target

GEN = Path(__file__).resolve().parent.parent / "generated" / "spu_lifted"
MARK = "/* spu_native_patch */"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    hooks = target.TARGET.get("spu_native_hooks", [])
    by_image = {}
    for image, block, fn in hooks:
        by_image.setdefault(image, []).append((int(block, 16), fn))
    bad = 0
    for image in sorted(set(by_image) | {d.name for d in GEN.glob("*") if d.is_dir()}):
        src = GEN / image / "spu_recomp.c"
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        lines = text.split("\n")
        clean = [l for l in lines if MARK not in l]
        if mode == "--restore":
            if len(clean) != len(lines):
                src.write_text("\n".join(clean), encoding="utf-8", newline="\n")
                print(f"  {image}: restored")
            continue
        want = by_image.get(image, [])
        if not want:
            continue
        out, done = [], set()
        decls = [f"void {fn}(spu_context* ctx); {MARK}" for _, fn in dict.fromkeys(want)]
        last_inc = max((i for i, l in enumerate(clean[:40]) if l.startswith("#include")), default=-1)
        for i, line in enumerate(clean):
            out.append(line)
            if i == last_inc:
                out.extend(decls)
                decls = []
            for block, fn in want:
                head = f"void gt5p_{image}_spu_func_{block:08X}(spu_context* ctx) {{"
                if line == head:
                    out.append(f"        {fn}(ctx); {MARK}")
                    done.add(block)
        missing = [hex(b) for b, _ in want if b not in done]
        if decls:
            missing.append("no #include line for the declarations")
        if missing:
            bad += 1
            print(f"  {image}: NOT FOUND {missing}")
            continue
        new = "\n".join(out)
        if mode == "--check":
            print(f"  {image}: {'patched' if new == text else 'needs patching'} ({len(want)} hooks)")
            continue
        if new != text:
            src.write_text(new, encoding="utf-8", newline="\n")
        print(f"  {image}: {len(want)} hooks")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
