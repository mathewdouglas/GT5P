"""Sum the GT5P_SAMPLE=all lane tables of several rounds, by function.
   python scripts/diag/lanesum.py build/gt5p.map <log> [first_round] [top] [table]
table: lanes (default) or rest. Prints samples and share of the busy samples
(spurs_pool_lane's wait counts as idle)."""
import bisect
import collections
import re
import sys

syms = []
for line in open(sys.argv[1], errors="replace"):
    m = re.match(r"\s*[0-9a-f]{4}:[0-9a-f]{8}\s+(\S+)\s+([0-9a-f]{16})\s+(?:f\s+)?(?:i\s+)?(\S+)?", line)
    if m:
        syms.append((int(m.group(2), 16) - 0x140000000, m.group(1)))
syms.sort()
addrs = [a for a, _ in syms]
first = int(sys.argv[3]) if len(sys.argv) > 3 else 0
top = int(sys.argv[4]) if len(sys.argv) > 4 else 50
table = sys.argv[5] if len(sys.argv) > 5 else "lanes"

tot = collections.Counter()
cur = None
for l in open(sys.argv[2], errors="replace"):
    if "[ps-sample]" not in l:
        continue
    h = re.search(r"round=(\d+) tid=\d+ cpu=(\w+)", l)
    if h:
        cur = h.group(2) == table and int(h.group(1)) >= first
        continue
    if not cur:
        continue
    m = re.search(r"\+0x([0-9A-Fa-f]+)\s+(\d+)", l)
    if not m or ".dll" in l.lower():
        continue
    rva, n = int(m.group(1), 16), int(m.group(2))
    i = bisect.bisect_right(addrs, rva & ~1) - 1
    name = syms[i][1] if i >= 0 else "?"
    if rva & 1:
        name += " (in a DLL it called)"
    tot[name] += n

all_n = sum(tot.values())
idle = sum(v for k, v in tot.items() if k.startswith("spurs_pool_lane"))
busy = all_n - idle
print(f"{all_n} samples, {idle} idle in spurs_pool_lane, {busy} busy")
for k, v in tot.most_common(top):
    print(f"{v:6d} {100.0 * v / busy:5.1f}%  {k}")
