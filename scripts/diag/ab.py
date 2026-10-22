"""A/B boots: python scripts/diag/ab.py <exe> <outdir> <runs> <secs> [NAME=VALUE...]
Classifies each run by the arena overrun (sized smaller than filled) and by
guard credits taken twice, not by bootcheck's signatures."""
import os, re, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import bootcheck
exe, out, runs, secs = sys.argv[1], ROOT / sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, PS3_HEADLESS="1", PS3_VERBOSE="0", GT5P_MAINSTACK="5",
           GT5P_ARENA_TRACE="1", SPURS_JG_TRACE="1")
for a in sys.argv[5:]:
    k, _, v = a.partition("="); env[k] = v
tot = dict(over=0, dbl=0, full=0, bad=0)
for i in range(1, runs + 1):
    fo, fe = out / f"run{i}.out", out / f"run{i}.err"
    with open(fo, "wb") as o, open(fe, "wb") as e:
        p = subprocess.Popen([str(ROOT / exe)], cwd=ROOT, env=env, stdout=o, stderr=e)
        try: rc = "rc=0x%X" % (p.wait(timeout=secs) & 0xFFFFFFFF)
        except subprocess.TimeoutExpired: p.kill(); p.wait(); rc = "running"
    so = fo.read_text(encoding="utf-8", errors="replace")
    se = fe.read_text(encoding="utf-8", errors="replace")
    last, meas, over = {}, {}, 0
    for m in re.finditer(r"\[d-arena:post\] n=\d+ arena=(\w+) base=(\w+) cur=(\w+)", se):
        a, b, c = m[1], int(m[2], 16), int(m[3], 16)
        pv = last.get(a)
        if pv and (pv[0] != b or c < pv[1]):
            if pv[0] == 0: meas[a] = pv[1]
            elif a in meas and pv[1] > meas[a]: over += 1
        last[a] = (b, c)
    for a, pv in last.items():
        if pv[0] and a in meas and pv[1] > meas[a]: over += 1
    cred = dbl = 0
    for m in re.finditer(r"^\[JG\] (notify|open)", se, re.M):
        if m[1] == "notify": cred += 1
        else:
            cred -= 1
            if cred < 0: dbl += 1; cred = 0
    vol = len(re.findall(r"Open\(path='[^']*GT\.VOL'", so))
    why = bootcheck.bad_reason(se)
    walkers = se.count("spurs-jc")
    print("run %2d: %-13s gtvol=%-4d flips=%-4d overruns=%d double_opens=%-3d walkers=%-3d lr=%s%s" % (
        i, rc, vol, so.count("SetPrepareFlip"), over, dbl, walkers, bootcheck.last_lr(se),
        "  BAD: " + why if why else ""), flush=True)
    tot["over"] += over > 0; tot["dbl"] += dbl > 0; tot["full"] += vol >= 128; tot["bad"] += bool(why)
print("TOTAL runs=%d with_overrun=%d with_double_open=%d full_boot(>=128 opens)=%d bootcheck_bad=%d" % (
    runs, tot["over"], tot["dbl"], tot["full"], tot["bad"]))
