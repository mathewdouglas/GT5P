#!/usr/bin/env python3
"""Boot the port N times, headless, and print one line of counts per run.

The Windows-native counterpart of scripts/soak.sh, and it counts volume opens
for either data layout: PDIPFS files (the PSN package) or reads of GT.VOL (the
disc). PS3_VERBOSE=0, because verbose logging serialises every guest thread on
one lock and changes what the title does.

    python scripts/soak.py [runs=6] [seconds=40]

GT5P_MAINSTACK is set so the port flushes stdout while it runs; a boot that
never exits is killed from outside, and anything still buffered is lost. The
counts therefore describe the run up to its last sample, not to the kill.
Logs land in scratch/soak/run<N>.{out,err}.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = 5          # seconds between main-thread samples (and stdout flushes)


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    out_dir = ROOT / "scratch" / "soak"
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PS3_HEADLESS="1", PS3_VERBOSE="0", GT5P_MAINSTACK=str(SAMPLE))
    for a in sys.argv[3:]:                      # extra NAME=VALUE for the game
        k, _, v = a.partition("=")
        env[k] = v
    totals = []
    for i in range(1, runs + 1):
        out, err = out_dir / f"run{i}.out", out_dir / f"run{i}.err"
        with open(out, "wb") as fo, open(err, "wb") as fe:
            p = subprocess.Popen([str(ROOT / "build" / "gt5p.exe")], cwd=ROOT, env=env,
                                 stdout=fo, stderr=fe)
            try:
                rc = "rc=0x%X" % (p.wait(timeout=secs) & 0xFFFFFFFF)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                rc = "running"
        o = out.read_text(encoding="utf-8", errors="replace")
        e = err.read_text(encoding="utf-8", errors="replace")
        pdipfs = len(set(re.findall(r"Open\(path='([^']*PDIPFS[^']*)'", o)))
        vol = len(re.findall(r"Open\(path='[^']*GT\.VOL'", o))
        lrs = re.findall(r"\[mainstack\] in=\S+ sp=\S+ lr=(0x[0-9A-F]+)", e)
        paths = len(set(re.findall(r"\[cellFs\] \w+\(path='([^']+)'", o)))
        print("run %d: %-8s pdipfs=%-3d gtvol_opens=%-4d paths=%-4d prepare_flip=%-3d pad_poll=%d np=%d crash=%d main_lr=%s" % (
            i, rc, pdipfs, vol, paths, o.count("SetPrepareFlip"), o.count("GetData polling"),
            o.count("[sceNp]"), e.count("ACCESS VIOLATION"), lrs[-1] if lrs else "-"))
        totals.append(pdipfs or vol)
    print("assets: " + " ".join(map(str, totals)))


if __name__ == "__main__":
    main()
