"""Sum GT5P_SAMPLE_WID tables (tid=w<n>) over all rounds, by function and by SPU image.
   widprof.py <map> <log> <wid> [top]"""
import bisect, re, sys, collections
syms = []
for line in open(sys.argv[1], errors="replace"):
    m = re.match(r"\s*[0-9a-f]{4}:[0-9a-f]{8}\s+(\S+)\s+([0-9a-f]{16})\s+(?:f\s+)?(?:i\s+)?(\S+)?", line)
    if m: syms.append((int(m.group(2), 16) - 0x140000000, m.group(1)))
syms.sort(); addrs = [a for a, _ in syms]
wid, top = sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 40
fn, img, total, on = collections.Counter(), collections.Counter(), 0, False
for line in open(sys.argv[2], errors="replace"):
    if "[ps-sample] round=" in line: on = ("tid=w%s " % wid) in line; continue
    if not on: continue
    m = re.match(r"\[ps-sample\]\s+\+0x([0-9A-Fa-f]+)\s+(\d+)", line)
    if not m:
        if "samples by running" in line: continue
        on = False; continue
    rva, n = int(m.group(1), 16), int(m.group(2))
    i = bisect.bisect_right(addrs, rva) - 1
    name = syms[i][1] if i >= 0 else "?"
    fn[name] += n; total += n
    mm = re.match(r"(gt5p_(?:audio_)?[jb][0-9A-F]+)_spu_func", name)
    img[mm.group(1) if mm else "(runtime/other)"] += n
print("total", total)
for k, v in img.most_common(12): print("  %5.1f%% %s" % (100 * v / total, k))
print()
for k, v in fn.most_common(top): print("  %5.1f%% %6d %s" % (100 * v / total, v, k))
