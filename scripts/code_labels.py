#!/usr/bin/env python3
"""Seed code labels the title keeps as raw addresses in its TOC.

GCC's "labels as values" (computed goto) stores label addresses in the TOC;
the function copies them into a table and jumps with `mtctr; bctr`. The
lifter sees an unresolved `bctr`, lowers it to ps3_indirect_tail, and the
runtime finds no lifted entry at the label ("[ppu] indirect tail to ...: no
lifted entry"). It then returns without running the function's epilogue, and
the caller gets back callee-saved registers that were never restored. GT5
01.04's script VM state machine (func_00B52140, labels 0x00B5248C,
0x00B52524, 0x00B526D8, 0x00B521AC) handed its caller r26 = 0 that way, and
the title ran on with a NULL object behind its warning screen (GT5 Phase 7).

Candidates are 4-aligned words within 32 KB of a TOC base that point into
executable code and are not a function descriptor's entry. Seeding a function
start that was already known changes nothing; seeding a label splits its
function there, and the first part falls through to the second.

    python scripts/code_labels.py            # report
    python scripts/code_labels.py --write    # merge into the target's seeds
"""
import json
import os
import struct
import sys

import target

ELF = os.path.join(os.path.dirname(__file__), '..', 'input', 'EMAIN.ELF')
TOC_REACH = 0x8000            # a 16-bit signed displacement either side of r2


def sections(d):
    shoff, = struct.unpack_from('>Q', d, 0x28)
    shentsize, shnum = struct.unpack_from('>HH', d, 0x3A)
    raw = [struct.unpack_from('>IIQQQQ', d, shoff + i * shentsize) for i in range(shnum)]
    # Retail executables carry no section names; keep (addr, offset, size, flags).
    # NOBITS sections (.bss) have no file bytes; leave them out.
    return [(addr, off, size, flags) for name, typ, flags, addr, off, size in raw
            if typ != 8 and off + size <= len(d)]


def main():
    d = open(ELF, 'rb').read()
    secs = sections(d)
    code_end = target.addr('code_end')

    # .opd holds 8-byte (entry, toc) pairs. Retail executables carry no section
    # names, so take the data section whose pairs are most often (code, toc).
    def opd_pairs(off, size):
        return [struct.unpack_from('>II', d, off + o) for o in range(0, size - 7, 8)]
    best = None
    for a, off, size, fl in secs:
        if not a or size < 64 or fl & 4:
            continue
        pairs = opd_pairs(off, size)
        good = sum(1 for e, t in pairs if 0x10000 <= e < code_end and e % 4 == 0 and t > code_end)
        if best is None or good / len(pairs) > best[0]:
            best = (good / len(pairs), off, size)
    entries, tocs = set(), {}
    for e, t in opd_pairs(best[1], best[2]):
        if 0x10000 <= e < code_end:
            entries.add(e)
            tocs[t] = tocs.get(t, 0) + 1
    tocs = {t for t, n in tocs.items() if n >= 16}     # real TOCs are shared widely

    data = [(a, off, size) for a, off, size, fl in secs
            if a and size and not (fl & 4) and fl & 2]          # allocated, not executable
    labels = {}
    for t in sorted(tocs):
        for a, off, size in data:
            lo, hi = max(a, t - TOC_REACH), min(a + size, t + TOC_REACH)
            for ea in range(lo + (-lo % 4), hi - 3, 4):
                w, = struct.unpack_from('>I', d, off + ea - a)
                if 0x10200 <= w < code_end and w % 4 == 0 and w not in entries:
                    labels.setdefault(w, ea)
    labels = {w: ea for w, ea in labels.items() if w not in entries}
    print('%d TOC bases, %d code labels in reach' % (len(tocs), len(labels)))
    if '-v' in sys.argv:
        for w in sorted(labels):
            print('  0x%08X  (word at 0x%08X)' % (w, labels[w]))

    if '--write' in sys.argv:
        path = str(target.path('seeds'))
        existing = json.load(open(path)) if os.path.exists(path) else []
        merged = sorted(set(existing) | {'0x%08X' % w for w in labels})
        json.dump(merged, open(path, 'w'), indent=2)
        print('seeds: %d -> %d in %s' % (len(existing), len(merged), target.TARGET['seeds']))


if __name__ == '__main__':
    main()
