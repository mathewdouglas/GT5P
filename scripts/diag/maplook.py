"""Resolve sampler buckets against the linker map.
   python scripts/diag/maplook.py build/gt5p.map <log> [top] [tag]
tag: jc-sample (SPURS_JC_SAMPLE) or ps-sample (GT5P_SAMPLE, the default).
For ps-sample every thread block of the last complete round is printed."""
import bisect
import re
import sys

syms = []
for line in open(sys.argv[1], errors="replace"):
    m = re.match(r"\s*[0-9a-f]{4}:[0-9a-f]{8}\s+(\S+)\s+([0-9a-f]{16})\s+(?:f\s+)?(?:i\s+)?(\S+)?", line)
    if m:
        syms.append((int(m.group(2), 16) - 0x140000000, m.group(1), m.group(3) or ""))
syms.sort()
addrs = [a for a, _, _ in syms]
top = int(sys.argv[3]) if len(sys.argv) > 3 else 40
tag = "[%s]" % (sys.argv[4] if len(sys.argv) > 4 else "ps-sample")

lines = [l for l in open(sys.argv[2], errors="replace") if tag in l]
heads = [i for i, l in enumerate(lines) if "samples," in l]
if not heads:
    sys.exit("no sample blocks")
rounds = [re.search(r"round=(\d+)", lines[i]) for i in heads]
if rounds[-1]:
    # the last round may be cut off by the kill; use the one before if it has fewer blocks
    want = rounds[-1].group(1)
    blocks = [i for i, r in zip(heads, rounds) if r and r.group(1) == want]
    prevr = str(int(want) - 1)
    pblocks = [i for i, r in zip(heads, rounds) if r and r.group(1) == prevr]
    if len(pblocks) > len(blocks):
        blocks = pblocks
else:
    blocks = [heads[-1]]

def name_of(l):
    m = re.search(r"\+0x([0-9A-Fa-f]+)\s+(\d+)", l)
    if not m:
        return None, 0
    rva, n = int(m.group(1), 16), int(m.group(2))
    dm = re.search(r"\]\s+(\S+\.(?:dll|DLL))\+0x", l)
    if dm:
        return "(" + dm.group(1) + ")", n
    if rva > addrs[-1] + 0x1000000:
        return "(outside the executable)", n
    i = bisect.bisect_right(addrs, (rva & ~1) + 0x80) - 1
    nm = "%s  [%s]" % (syms[i][1], syms[i][2].split(":")[-1]) if i >= 0 else "?"
    if rva & 1:
        nm += "  (in a DLL it called)"
    return nm, n

for b in blocks:
    print(lines[b].strip())
    agg, total = {}, 0
    for l in lines[b + 1:]:
        if "samples," in l:
            break
        nm, n = name_of(l)
        if nm is None:
            break
        total += n
        agg[nm] = agg.get(nm, 0) + n
    for nm, n in sorted(agg.items(), key=lambda kv: -kv[1])[:top]:
        print("%5d  %s" % (n, nm))
    print()
