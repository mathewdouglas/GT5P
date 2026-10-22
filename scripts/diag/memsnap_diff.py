"""Find guest memory that tells two states apart, from GT5P_MEMSNAP files.

    memsnap_diff.py --a snap00.bin snap01.bin --b snap02.bin snap03.bin [--max 60]

Each group (--a, --b) holds snapshots taken in one state (running, paused).
Prints the guest addresses whose bytes are the same across every snapshot of
a group but differ between the groups, as 32-bit words with both values,
lowest addresses first (the executable's own data comes before the heaps).
Snapshots hold game memory: keep them in scratch/ and delete them after.
"""
import argparse
import struct
import sys

import numpy as np


def load(path):
    """The snapshot's regions, mapped from the file (each is ~1 GB)."""
    regions = {}
    mm = np.memmap(path, dtype=np.uint8, mode="r")
    off = 0
    while off + 8 <= len(mm):
        addr, n = struct.unpack("<II", mm[off:off + 8].tobytes())
        regions[addr] = mm[off + 8:off + 8 + n]
        off += 8 + n
    return regions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", nargs="+", required=True)
    ap.add_argument("--b", nargs="+", required=True)
    ap.add_argument("--c", nargs="*", default=[],
                    help="more snapshots that must equal group a (other states that are not b)")
    ap.add_argument("--ptrs", action="store_true",
                    help="for each small-value hit, the executable's data words that point into "
                         "the object holding it (same pointer in every snapshot)")
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--below", type=lambda s: int(s, 0), default=0x100000000,
                    help="only addresses below this")
    args = ap.parse_args()
    A = [load(p) for p in args.a]
    B = [load(p) for p in args.b]
    C = [load(p) for p in args.c]
    common = set(A[0])
    for s in A[1:] + B + C:
        common &= set(s)
    A = A + C
    hits = []
    for addr in sorted(common):
        if addr >= args.below:
            continue
        n = min(len(s[addr]) for s in A + B) & ~3
        a0 = A[0][addr][:n]
        b0 = B[0][addr][:n]
        mask = a0 != b0
        for s in A[1:]:
            mask &= s[addr][:n] == a0
        for s in B[1:]:
            mask &= s[addr][:n] == b0
        if not mask.any():
            continue
        words = np.unique(np.nonzero(mask)[0] // 4)
        for w in words:
            o = int(w) * 4
            va = struct.unpack(">I", a0[o:o + 4].tobytes())[0]
            vb = struct.unpack(">I", b0[o:o + 4].tobytes())[0]
            hits.append((addr + o, va, vb))
    print(f"{len(hits)} words differ consistently between the groups")
    # Small values first (flags, states), then by address.
    small = [h for h in hits if h[1] < 0x100 and h[2] < 0x100]
    print(f"{len(small)} of them hold small values (< 0x100) in both states:")
    for addr, va, vb in small[:args.max]:
        print(f"  {addr:08X}  a={va:08X}  b={vb:08X}")
    print("first by address:")
    for addr, va, vb in hits[:args.max]:
        print(f"  {addr:08X}  a={va:08X}  b={vb:08X}")
    if args.ptrs:
        # Words in the executable's data (below 0x02000000) holding the same
        # heap pointer in every snapshot, pointing at most 0x4000 bytes below
        # a hit: [static] + offset reaches the flag in any boot.
        snaps = A + B
        static = sorted(a for a in common if a < 0x02000000)
        stable = []
        for base in static:
            n = min(len(s[base]) for s in snaps) & ~3
            w0 = snaps[0][base][:n].view(">u4")
            same = np.ones(len(w0), dtype=bool)
            for s in snaps[1:]:
                same &= s[base][:n].view(">u4") == w0
            idx = np.nonzero(same & (w0 >= 0x20000000) & (w0 < 0xD0000000))[0]
            stable += [(base + int(i) * 4, int(w0[i])) for i in idx]
        ptr_vals = np.array([v for _, v in stable], dtype=np.int64)
        print(f"pointer chains ({len(stable)} stable static pointers):")
        for addr, va, vb in small[:args.max]:
            d = addr - ptr_vals
            for i in np.nonzero((d >= 0) & (d < 0x4000))[0][:4]:
                print(f"  {addr:08X} (a={va:X} b={vb:X}) = [{stable[i][0]:08X}] {stable[i][1]:08X} + 0x{int(d[i]):X}")


if __name__ == "__main__":
    sys.exit(main())
