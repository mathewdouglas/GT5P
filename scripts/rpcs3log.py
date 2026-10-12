#!/usr/bin/env python3
"""Summarise an RPCS3 log of this title, for comparing against a port run.

    python scripts/rpcs3log.py <RPCS3.log> [--copy scratch/rpcs3.log]

RPCS3 keeps its log open while it runs; this reads it with sharing allowed, so
it works on a live log. --copy saves a snapshot to read later.
"""
import collections
import re
import sys

LINE = re.compile(r"^·(?P<lvl>\S) (?P<time>[\d:.]+) (?:\{(?P<thr>[^}]*)\} )?(?P<chan>[\w ]+?): (?P<msg>.*)$")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    data = open(args[0], "rb").read()
    if "--copy" in sys.argv:
        open(sys.argv[sys.argv.index("--copy") + 1], "wb").write(data)
    lines = data.decode("utf-8", errors="replace").splitlines()
    print("lines: %d" % len(lines))

    chans, levels = collections.Counter(), collections.Counter()
    opens, stats, todo, errors, spurs = [], [], collections.Counter(), [], collections.Counter()
    for l in lines:
        m = LINE.match(l)
        if not m:
            continue
        chan, msg, lvl = m.group("chan"), m.group("msg"), m.group("lvl")
        chans[chan] += 1
        levels[lvl] += 1
        if chan == "sys_fs":
            # RPCS3 quotes guest strings with typographic quotes.
            p = re.search(r'sys_fs_(open|stat|opendir)\(path=[“"]([^”"]*)[”"]', msg)
            if p:
                (opens if p.group(1) == "open" else stats).append(p.group(2))
        if lvl in ("E", "F"):
            errors.append("%s %s: %s" % (m.group("time"), chan, msg[:170]))
        if lvl == "T" or "TODO" in msg or "UNIMPLEMENTED" in msg:
            todo[chan + ": " + re.sub(r"\(.*", "", msg)[:70]] += 1
        if chan == "cellSpurs":
            spurs[re.sub(r"\(.*", "", msg)[:60]] += 1

    print("by level: " + ", ".join("%s=%d" % kv for kv in levels.most_common()))
    print("by channel: " + ", ".join("%s x%d" % kv for kv in chans.most_common(24)))
    oc = collections.Counter(opens)
    print("sys_fs_open: %d calls, %d distinct paths" % (len(opens), len(oc)))
    for p, n in oc.most_common(25):
        print("   %5dx %s" % (n, p))
    sc = collections.Counter(stats)
    print("sys_fs_stat/opendir: %d calls, %d distinct paths" % (len(stats), len(sc)))
    for p, n in sc.most_common(30):
        print("   %5dx %s" % (n, p))
    print("cellSpurs calls:")
    for k, n in spurs.most_common(30):
        print("   %5dx %s" % (n, k))
    print("TODO / unimplemented:")
    for k, n in todo.most_common(30):
        print("   %5dx %s" % (n, k))
    print("errors and fatals: %d" % len(errors))
    for e in errors[:25]:
        print("   " + e)


if __name__ == "__main__":
    main()
