#!/usr/bin/env python3
"""Boot the port headless for a fixed time and summarise the log.

    python scripts/boot.py [seconds=20] [NAME=VALUE ...]

Extra NAME=VALUE arguments are set in the game's environment, e.g.
`PS3_HLE_TRACE=200000 PS3_SCTRACE=1` to trace imports and syscalls, or
`GT5P_MAINSTACK=10` to print where the main thread is.

The full log goes to scratch/boot.err and scratch/boot.out. stdout is fully
buffered by the port and lost when the process is killed, so expect little in
boot.out; set PS3_VERBOSE=0 when a number matters (see README).
"""
import collections
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOISE = ("faulted in guest page", "timer_usleep", "[null-read]")


def nid_names():
    p = ROOT / "analysis" / "hle_stubs_named.json"
    if not p.exists():
        return {}
    return {int(e["nid"], 16): "%s:%s" % (e["module"], e["name"]) for e in json.loads(p.read_text())}


def main():
    args = sys.argv[1:]
    secs = int(args.pop(0)) if args and args[0].isdigit() else 20
    env = dict(os.environ, PS3_HEADLESS="1")
    for a in args:
        k, _, v = a.partition("=")
        env[k] = v
    scratch = ROOT / "scratch"
    scratch.mkdir(exist_ok=True)
    out, err = scratch / "boot.out", scratch / "boot.err"
    with open(out, "wb") as fo, open(err, "wb") as fe:
        p = subprocess.Popen([str(ROOT / "build" / "gt5p.exe")], cwd=ROOT, env=env, stdout=fo, stderr=fe)
        try:
            rc = p.wait(timeout=secs)
            print("exited rc=%d (0x%X)" % (rc, rc & 0xFFFFFFFF))
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            print("still running after %ds, killed" % secs)

    names = nid_names()
    lines = err.read_text(encoding="utf-8", errors="replace").splitlines()
    print("stderr lines: %d" % len(lines))

    tags = collections.Counter((re.match(r"\s*(\[[^\]]+\])", l) or [None, l[:24]])[1] for l in lines)
    print("by tag: " + ", ".join("%s x%d" % kv for kv in tags.most_common(14)))

    opens = []
    for l in lines:
        m = re.search(r"(?:Open|open|stat|Stat|opendir)\w*\W+(?:path=)?'([^']+)'", l)
        if m and m.group(1) not in opens:
            opens.append(m.group(1))
    print("distinct paths touched: %d" % len(opens))
    for p_ in opens[:25]:
        print("   " + p_)

    hle = collections.Counter()
    for l in lines:
        m = re.match(r"\[HLETRACE\] nid=0x([0-9A-F]+)", l)
        if m:
            hle[int(m.group(1), 16)] += 1
    if hle:
        print("imports called: %d distinct, %d calls" % (len(hle), sum(hle.values())))

    def annotate(l):
        m = re.search(r"nid=0x([0-9A-F]+)", l)
        return l[:200] + ("   <- " + names.get(int(m.group(1), 16), "?") if m else "")

    keep = [l for l in lines if not any(n in l for n in NOISE)]
    tail = int(env.get("BOOT_TAIL", "40"))
    print("--- last %d lines (noise removed)" % tail)
    for l in keep[-tail:]:
        print(annotate(l))


if __name__ == "__main__":
    main()
