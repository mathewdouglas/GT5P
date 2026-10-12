#!/usr/bin/env python3
"""Locate the guest libc setjmp and longjmp by shape.

Both open by rounding the buffer pointer up to 16:

    addi   r3, r3, 15
    rldicr r3, r3, 0, 59

setjmp then stores the callee-saved registers through r3 (`std rN, d(r3)` for
r14..r31) and longjmp loads them back (`ld rN, d(r3)`). Counting those in the
instructions that follow tells the two apart and rejects anything else that
happens to align a pointer.

    python scripts/find_setjmp.py

Prints candidates; put the pair in config/targets.json.
"""
import struct

from dis import SEGS, read
import target

ADDI_R3_15 = 0x3863000F
RLDICR_R3_59 = 0x786306E4
WINDOW = 64            # instructions to inspect after the prologue


def callee_saved_through_r3(words, opcode):
    """How many of r14..r31 are stored/loaded with base r3 (DS-form, xo 0)."""
    seen = set()
    for w in words:
        if (w >> 26) == opcode and (w & 3) == 0 and ((w >> 16) & 31) == 3:
            r = (w >> 21) & 31
            if 14 <= r <= 31:
                seen.add(r)
    return len(seen)


def main():
    lo, hi = 0x00010000, target.addr("code_end")
    for base, _off, fsz in SEGS:
        if not (base <= lo < base + fsz):
            continue
        end = min(base + fsz, hi)
        buf = read(lo, end - lo)
        words = struct.unpack(">%dI" % ((end - lo) // 4), buf)
        for i in range(len(words) - 1):
            if words[i] != ADDI_R3_15 or words[i + 1] != RLDICR_R3_59:
                continue
            body = words[i + 2:i + 2 + WINDOW]
            stores = callee_saved_through_r3(body, 62)   # std
            loads = callee_saved_through_r3(body, 58)    # ld
            if max(stores, loads) < 12:
                continue
            kind = "setjmp " if stores > loads else "longjmp"
            print("0x%08X  %s  std=%d ld=%d of r14..r31" % (lo + i * 4, kind, stores, loads))


if __name__ == "__main__":
    main()
