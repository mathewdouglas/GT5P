# Count calls to lifted functions in address ranges. Every 10 s (on the next
# call) prints "[fnc] <addr> n=<calls since last line> t=<tick ms>" to stdout,
# with the caller's lr, r3 and r4, so it interleaves with [milestone] lines.
#   .venv\Scripts\python scripts\diag\fncount_patch.py 838000-840000 [612000-616000 ...]
#   .venv\Scripts\python scripts\diag\fncount_patch.py --restore
# Keeps generated/<file>.fnc_orig beside each patched file.
import glob, os, re, sys

GEN = os.path.join(os.path.dirname(__file__), "..", "..", "generated")
BS = "\\"

HOOK = ("{ static volatile long _fc = 0; static unsigned long long _ft = 0; "
        "_InterlockedIncrement(&_fc); unsigned long long _now = GetTickCount64(); "
        "if (_now - _ft >= 10000) { long _n = _InterlockedExchange(&_fc, 0); _ft = _now; "
        "fprintf(stdout, \"[fnc] ADDR n=%ld t=%llu lr=0x%08X r3=0x%08X r4=0x%08X" + BS + "n\", _n, _now, "
        "(unsigned)ctx->lr, (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4]); } }\r\n")

PRE = ("#include <stdio.h>\n#include <intrin.h>\n"
       "extern \"C\" __declspec(dllimport) unsigned long long __stdcall GetTickCount64(void);\n")

def restore():
    for o in glob.glob(os.path.join(GEN, "*.fnc_orig")):
        dst = o[:-len(".fnc_orig")]
        os.replace(o, dst)
        # The original keeps its old time, older than an object built from
        # the patched copy; stamp it now so the build recompiles it.
        os.utime(dst)
        print("restored", dst)

def patch(ranges):
    tot = 0
    for f in sorted(glob.glob(os.path.join(GEN, "ppu_recomp_*.cpp"))):
        src = open(f, encoding="latin-1", newline="").read()
        n = 0
        def rep(m):
            nonlocal n
            a = int(m.group(1), 16)
            if not any(lo <= a < hi for lo, hi in ranges):
                return m.group(0)
            n += 1
            return m.group(0) + HOOK.replace("ADDR", m.group(1))
        nsrc = re.sub(r"^void func_([0-9A-F]{8})\(ppu_context\* ctx\) \{\r?\n", rep, src, flags=re.M)
        if n:
            if not os.path.exists(f + ".fnc_orig"):
                open(f + ".fnc_orig", "w", encoding="latin-1", newline="").write(src)
            open(f, "w", encoding="latin-1", newline="").write(PRE + nsrc)
            print(os.path.basename(f), n)
            tot += n
    print("total", tot)

if __name__ == "__main__":
    if sys.argv[1:] == ["--restore"]:
        restore()
    else:
        patch([tuple(int(x, 16) for x in r.split("-")) for r in sys.argv[1:]])
