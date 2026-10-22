# Count calls to every lifted function of one SPU job body. Every 10 s (on the
# next call) prints "[sfc] <body> <addr> n=<calls since last line> t=<tick>"
# to stdout, so the lines interleave with [milestone] lines.
#   .venv\Scripts\python scripts\diag\spufn_count.py b01376080
#   .venv\Scripts\python scripts\diag\spufn_count.py --restore b01376080
import os, re, sys

body = sys.argv[-1]
p = os.path.join(os.path.dirname(__file__), "..", "..", "generated", "spu_lifted", body, "spu_recomp.c")
bak = p + ".sfc_orig"
if sys.argv[1] == "--restore":
    if os.path.exists(bak):
        os.replace(bak, p)
        # The original keeps its old time, older than an object built from
        # the patched copy; stamp it now so the build recompiles it.
        os.utime(p)
        print("restored", p)
    sys.exit(0)
src = open(p, encoding="latin-1", newline="").read()
if os.path.exists(bak):
    src = open(bak, encoding="latin-1", newline="").read()
else:
    open(bak, "w", encoding="latin-1", newline="").write(src)
NL = chr(92) + "n"
HOOK = ("{ static volatile long _fc = 0; static unsigned long long _ft = 0; "
        "_InterlockedIncrement(&_fc); unsigned long long _now = GetTickCount64(); "
        "if (_now - _ft >= 10000) { long _n = _InterlockedExchange(&_fc, 0); _ft = _now; "
        "fprintf(stdout, \"[sfc] BODY ADDR n=%ld t=%llu" + NL + "\", _n, _now); } }\n")
n = 0
def rep(m):
    global n
    n += 1
    return m.group(0) + HOOK.replace("BODY", body).replace("ADDR", m.group(1))
out = re.sub(r"^void gt5p_%s_spu_func_([0-9A-F]{8})\(spu_context\* ctx\) \{\r?\n" % body, rep, src, flags=re.M)
out = ("#include <stdio.h>\n#include <intrin.h>\n"
       "__declspec(dllimport) unsigned long long __stdcall GetTickCount64(void);\n") + out
open(p, "w", encoding="latin-1", newline="").write(out)
print(n, "functions instrumented in", p)
