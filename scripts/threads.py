#!/usr/bin/env python3
"""Per-thread summary of a port log: what each guest thread was last doing.

    python scripts/threads.py [scratch/boot.err]

For each thread the runtime created: its name, entry, whether it exited, and
the last blocking call it logged ([WAIT] lines carry tid= or follow the
thread's own syscall trace). Run the boot with PS3_SCTRACE=1 to get the
syscall trail; without it only waits the runtime logs by itself are shown.
"""
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scratch" / "boot.err"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    threads = collections.OrderedDict()
    threads[0] = {"name": "main", "entry": "-", "exited": False}
    last = collections.defaultdict(list)
    counts = collections.Counter()
    for l in lines:
        m = re.match(r'\[SYS\] sys_ppu_thread_create tid=(\d+) name="([^"]*)" entry=(\S+)', l)
        if m:
            threads[int(m.group(1))] = {"name": m.group(2), "entry": m.group(3), "exited": False}
            last[int(m.group(1))] = []
            continue
        m = re.match(r"\[SYS\] sys_ppu_thread_exit\(tid=(\d+)", l)
        if m and int(m.group(1)) in threads:
            threads[int(m.group(1))]["exited"] = True
            continue
        m = re.search(r"\btid=(\d+)\b", l)
        if m and (l.startswith("[sc]") or l.startswith("[WAIT]") or l.startswith("[LWM")):
            t = int(m.group(1))
            counts[t] += 1
            short = re.sub(r" from func_.*", "", l)[:150]
            tail = re.search(r" from (func_\S+)", l)
            last[t].append(short + ("  @" + tail.group(1)[:60] if tail else ""))
            if len(last[t]) > 3:
                last[t].pop(0)
    for t, info in threads.items():
        state = "exited" if info["exited"] else "alive"
        print("tid %-3d %-7s %-28s entry=%s  traced=%d" % (t, state, info["name"], info["entry"], counts[t]))
        if not info["exited"]:
            for s in last[t]:
                print("        " + s)


if __name__ == "__main__":
    main()
