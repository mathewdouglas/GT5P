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

A boot that goes wrong during sound start-up (scripts/bootcheck.py) is printed,
marked BAD, and booted again: the soak keeps going until it has the asked-for
number of usable runs, or has thrown away as many again. The last line says how
many were thrown away, so the failure rate is still on the page. SOAK_KEEP_BAD=1
turns the retry off, for measuring that rate itself.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootcheck
import target

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = 5          # seconds between main-thread samples (and stdout flushes)


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    out_dir = ROOT / "scratch" / "soak"
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PS3_HEADLESS="1", PS3_VERBOSE="0", GT5P_MAINSTACK=str(SAMPLE),
               GT5P_NO_SETTINGS="1",
               FS_HIDE="grim/file/contents")   # no boot movie: AGENTS.md, Phase 50
    for a in sys.argv[3:]:                      # extra NAME=VALUE for the game
        k, _, v = a.partition("=")
        env[k] = v
    totals = []
    bad = {}
    keep_bad = bool(os.environ.get("SOAK_KEEP_BAD"))
    i = 0
    while len(totals) < runs and i < runs * 2:
        i += 1
        out, err = out_dir / f"run{i}.out", out_dir / f"run{i}.err"
        with open(out, "wb") as fo, open(err, "wb") as fe:
            p = subprocess.Popen([str(ROOT / "build" / (target.EXE_NAME + ".exe"))], cwd=ROOT, env=env,
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
        why = bootcheck.bad_reason(e)
        paths = len(set(re.findall(r"\[cellFs\] \w+\(path='([^']+)'", o)))
        print("run %d: %-8s pdipfs=%-3d gtvol_opens=%-4d paths=%-4d prepare_flip=%-3d pad_poll=%d np=%d crash=%d main_lr=%s" % (
            i, rc, pdipfs, vol, paths, o.count("SetPrepareFlip"), o.count("GetData polling"),
            o.count("[sceNp]"), e.count("ACCESS VIOLATION"), bootcheck.last_lr(e))
              + ("   BAD: " + why if why else ""))
        if why:
            bad[why] = bad.get(why, 0) + 1
            if not keep_bad:
                continue
        totals.append(pdipfs or vol)
    print("assets: " + " ".join(map(str, totals)))
    print("bad boots: %d of %d" % (sum(bad.values()), i))
    for w, n in bad.items():
        print("   %d x %s" % (n, w))


if __name__ == "__main__":
    main()
