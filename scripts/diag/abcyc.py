"""A/B within one boot from the [lane-cyc] windows (SPURS_LANE_CYC=1).
   python scripts/diag/abcyc.py [--key fast|pin] <run.err> [<run.err> ...]
--key fast (default): SPU_FAST_AB=1 runs; --key pin: SPURS_LANE_PIN_AB=1 runs.
Per log: the mean CPU ms per render-lane run (workloads 0 and 1) in windows
with key=1 against key=0, skipping windows with few runs (not on the page)."""
import re
import sys

args = sys.argv[1:]
key = "fast"
if args[:1] == ["--key"]:
    key, args = args[1], args[2:]

for path in args:
    by = {0: [], 1: []}
    wall = {0: [], 1: []}
    for l in open(path, errors="replace"):
        if not l.startswith("[lane-cyc]"):
            continue
        m = re.search(r"\b%s=(\d)" % key, l)
        if not m:
            continue
        vals = re.findall(r"w([01]): (\d+) runs, wall ([\d.]+) ms, cpu ([\d.]+) ms", l)
        runs = sum(int(n) for _, n, _, _ in vals)
        if runs < 150 or not vals:
            continue
        by[int(m.group(1))].append(sum(int(n) * float(c) for _, n, _, c in vals) / runs)
        wall[int(m.group(1))].append(sum(int(n) * float(w) for _, n, w, _ in vals) / runs)

    def mean(v):
        return sum(v) / len(v) if v else float("nan")
    a, b = mean(by[1]), mean(by[0])
    wa, wb = mean(wall[1]), mean(wall[0])
    print(f"{path}: {key}=1 cpu {a:.2f} wall {wa:.2f} ms ({len(by[1])} windows)  "
          f"{key}=0 cpu {b:.2f} wall {wb:.2f} ms ({len(by[0])} windows)  -> wall {wb / wa if wa == wa and wa else float('nan'):.3f}x")
