# Instrument lifted functions in generated/ to find a callee that returns with
# a different guest stack pointer than it was called with (a leaked frame).
#   .venv\Scripts\python scripts\diag\spcheck_patch.py func_007AE990 [func_...]
#   .venv\Scripts\python scripts\diag\spcheck_patch.py --restore
# Keeps generated/<file>.spc_orig beside each patched file; --restore puts
# the originals back. Prints "[spcheck] after <callee> from <fn>: r1 a -> b"
# (first 40) at run time.
import glob, os, re, sys

GEN = os.path.join(os.path.dirname(__file__), "..", "..", "generated")

def restore():
    for o in glob.glob(os.path.join(GEN, "*.spc_orig")):
        dst = o[:-len(".spc_orig")]
        os.replace(o, dst)
        # The original keeps its old time, older than an object built from
        # the patched copy; stamp it now so the build recompiles it.
        os.utime(dst)
        print("restored", dst)

def patch(names):
    files = glob.glob(os.path.join(GEN, "ppu_recomp_*.cpp"))
    for name in names:
        for f in files:
            src = open(f, encoding="latin-1", newline="").read()
            m = re.search(r"^void %s\(ppu_context\* ctx\) \{\r?\n" % re.escape(name), src, re.M)
            if not m:
                continue
            end = re.compile(r"\n\}\r?\n").search(src, m.end()).start()
            body = src[m.end():end]
            call = re.compile(r"ctx->lr = (0x[0-9A-F]+); (func_[0-9A-F]+)\(ctx\); DRAIN_TRAMPOLINE\(ctx\);")
            def rep(c):
                return ("{ uint64_t _spc = ctx->gpr[1]; ctx->lr = %s; %s(ctx); DRAIN_TRAMPOLINE(ctx); "
                        "if (ctx->gpr[1] != _spc) { static int _spn = 0; if (_spn++ < 40) "
                        "fprintf(stderr, \"[spcheck] after %s from %s at %s: r1 0x%%08llX -> 0x%%08llX\\n\", "
                        "(unsigned long long)_spc, (unsigned long long)ctx->gpr[1]); } }"
                        % (c.group(1), c.group(2), c.group(2), name, c.group(1)))
            nb, n = call.subn(rep, body)
            ind = re.compile(r"ps3_indirect_call\(ctx\); DRAIN_TRAMPOLINE\(ctx\);")
            def rep_i(c):
                return ("{ uint64_t _spc = ctx->gpr[1]; uint32_t _ctr = (uint32_t)ctx->ctr; "
                        "ps3_indirect_call(ctx); DRAIN_TRAMPOLINE(ctx); "
                        "if (ctx->gpr[1] != _spc) { static int _spn = 0; if (_spn++ < 40) "
                        "fprintf(stderr, \"[spcheck] after indirect 0x%%08X from %s: r1 0x%%08llX -> 0x%%08llX\\n\", "
                        "_ctr, (unsigned long long)_spc, (unsigned long long)ctx->gpr[1]); } }" % name)
            nb, ni = ind.subn(rep_i, nb)
            n += ni
            if not os.path.exists(f + ".spc_orig"):
                open(f + ".spc_orig", "w", encoding="latin-1", newline="").write(src)
            src = src[:m.end()] + nb + src[end:]
            if "#include <stdio.h>" not in src[:2000]:
                src = "#include <stdio.h>\n" + src
            open(f, "w", encoding="latin-1", newline="").write(src)
            print(name, "in", os.path.basename(f), ":", n, "calls instrumented")
            break
        else:
            print(name, "not found")

if __name__ == "__main__":
    if sys.argv[1:] == ["--restore"]:
        restore()
    else:
        patch(sys.argv[1:])
