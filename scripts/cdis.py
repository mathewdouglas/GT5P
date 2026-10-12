#!/usr/bin/env python3
"""Full PPC64 disassembly of a range of the game ELF, via capstone.

scripts/dis.py decodes only the forms its author needed; this prints every
instruction, and annotates TOC-relative loads with the word they fetch.

    python scripts/cdis.py 0x007DAEC0            # one function (bounds from analysis)
    python scripts/cdis.py 0x007DAEC0 0x7DAF40   # explicit range
"""
import importlib.util
import os
import struct
import sys

# scripts/dis.py shadows the standard library's dis, which capstone needs (via
# inspect). Import capstone with this directory off the path, then load our
# dis.py under another name.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p or ".") != _here]
from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN  # noqa: E402

_spec = importlib.util.spec_from_file_location("gt5p_dis", os.path.join(_here, "dis.py"))
gt5p_dis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gt5p_dis)
bounds, read = gt5p_dis.bounds, gt5p_dis.read

TOC = None


def toc():
    """r2 for the main module: second word of the entry point's descriptor."""
    global TOC
    if TOC is None:
        elf = open(gt5p_dis.ELF, "rb").read()
        entry = struct.unpack(">Q", elf[0x18:0x20])[0]
        TOC = struct.unpack(">I", read(entry + 4, 4))[0]
    return TOC


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    lo = int(args[0], 0)
    hi = int(args[1], 0) if len(args) > 1 else bounds(lo)[1]
    md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    buf = read(lo, hi - lo)
    for off in range(0, len(buf), 4):
        a = lo + off
        w = struct.unpack(">I", buf[off:off + 4])[0]
        ins = next(md.disasm(buf[off:off + 4], a), None)
        text = "%-8s %s" % (ins.mnemonic, ins.op_str) if ins else ".long 0x%08X" % w
        note = ""
        # lwz rN, d(r2): show what the TOC slot holds
        if (w >> 26) == 32 and ((w >> 16) & 31) == 2:
            d = w & 0xFFFF
            d -= 0x10000 if d & 0x8000 else 0
            try:
                note = "   ; [toc%+d] = 0x%08X" % (d, struct.unpack(">I", read(toc() + d, 4))[0])
            except KeyError:
                pass
        print("  %08X  %s%s" % (a, text, note))


if __name__ == "__main__":
    main()
