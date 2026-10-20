#!/usr/bin/env python3
"""Let guest spin waits on SPU progress give up their CPU.

Some guest functions wait for an SPU job list by re-reading its progress
counters in a loop with no syscall (GT5P's render thread in func_00BAB5C8
waits ~7 ms a frame for the render list). On the console the SPUs finish in a
few ms. Here every guest PPU thread shares two host CPUs, so that spin, at a
higher host priority, kept the main thread (guest priority 2048, host IDLE)
off its CPU for most of a frame.

Each loop listed under "spin_waits" in config/targets.json ([function, label
of the loop head]) gets a call to gt5p_spin_pause (src/gt5p_spin.cpp) on its
back edge: a short pause, then a yield, then short sleeps. GT5P_SPIN_YIELD=0
at run time makes it a pause only.

Run after every re-lift, with setjmp_patch.py; generated/ is not in the repo.

    python scripts/spin_patch.py            # patch (idempotent)
    python scripts/spin_patch.py --check    # report, change nothing
    python scripts/spin_patch.py --restore  # undo
"""
import re
import sys
from pathlib import Path

import target

GEN = Path(__file__).resolve().parent.parent / "generated"
MARK = "/* spin_patch */"
DECL = 'extern "C" void gt5p_spin_pause(uint32_t* n); ' + MARK + "\n"
COUNTER = "        uint32_t _spin_wait = 0; " + MARK + "\n"


def find_function(func):
    head = "void func_%s(ppu_context* ctx) {" % func
    for f in sorted(GEN.glob("ppu_recomp_*.cpp")):
        text = f.read_text(encoding="utf-8", errors="surrogateescape")
        start = text.find(head)
        if start >= 0:
            end = text.find("\n}\n", start)
            if end < 0:
                raise SystemExit(f"func_{func}: no end of function in {f.name}")
            return f, text, start, end + 3
    raise SystemExit(f"func_{func} not found in generated/")


def patch_body(body, func, label):
    goto = "goto loc_%s;" % label
    at_label = body.find("loc_%s:" % label)
    if at_label < 0:
        raise SystemExit(f"func_{func}: no label loc_{label}")
    n = 0
    out, pos = [], 0
    for m in re.finditer(re.escape(goto), body):
        if m.start() < at_label:
            raise SystemExit(f"func_{func}: goto loc_{label} before its label; not a loop back edge")
        out.append(body[pos:m.start()])
        out.append("{ gt5p_spin_pause(&_spin_wait); %s } %s" % (goto, MARK))
        pos = m.end()
        n += 1
    if not n:
        raise SystemExit(f"func_{func}: no back edge to loc_{label}")
    out.append(body[pos:])
    body = "".join(out)
    first = body.index("{\n") + 2
    return body[:first] + COUNTER + body[first:], n


def unpatch_body(body):
    body = body.replace(COUNTER, "")
    return re.sub(r"\{ gt5p_spin_pause\(&_spin_wait\); (goto loc_[0-9A-F]+;) \} " + re.escape(MARK),
                  r"\1", body)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    waits = target.TARGET.get("spin_waits", [])
    if not waits:
        print(f"no spin_waits for {target.NAME}")
        return
    edited = {}
    for func_s, label_s in waits:
        func, label = "%08X" % int(func_s, 16), "%08X" % int(label_s, 16)
        f, text, start, end = find_function(func)
        text = edited.get(f, text)
        start = text.find("void func_%s(ppu_context* ctx) {" % func)
        end = text.find("\n}\n", start) + 3
        body = text[start:end]
        patched = MARK in body
        if mode == "--check":
            print(f"func_{func} ({f.name}): {'patched' if patched else 'NOT patched'}")
            continue
        if mode == "--restore":
            if patched:
                text = text[:start] + unpatch_body(body) + text[end:]
                edited[f] = text
                print(f"func_{func}: restored")
            continue
        if patched:
            print(f"func_{func}: already patched")
            continue
        body, n = patch_body(body, func, label)
        text = text[:start] + body + text[end:]
        edited[f] = text
        print(f"func_{func}: {n} back edge(s) to loc_{label} pause")
    for f, text in edited.items():
        if mode == "--restore":
            if MARK not in text.replace(DECL, ""):
                text = text.replace(DECL, "")
        elif DECL not in text:
            # After the include block at the top of the chunk.
            last = 0
            for m in re.finditer(r"^#include [^\n]*\n", text, re.M):
                if m.start() > 4000:
                    break
                last = m.end()
            text = text[:last] + DECL + text[last:]
        f.write_text(text, encoding="utf-8", errors="surrogateescape", newline="")


if __name__ == "__main__":
    main()
