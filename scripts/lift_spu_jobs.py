#!/usr/bin/env python3
"""Lift every captured SPURS job image and regenerate src/gen/spu_workloads.c.

SPURS job binaries are raw code+data blobs, not ELFs, and this title's are not
at a fixed address -- the runtime only sees one when the chain dispatches it.
Capture them first, then lift:

    SPU_DUMP_MISS=analysis/spu/dump ./build/gt5p.exe      # run until quiet
    python scripts/lift_spu_jobs.py

The dump filenames carry the fingerprint the runtime computed
(spujob_<FP>_<size>.bin), which is the value to register: that hash is seeded
with 1469598103934665603 -- the FNV-1a-64 offset basis with a digit dropped --
so anything computed offline with a real FNV-1a-64 will not match, and a
mismatch is silent (the job logs `dispatch MISS` and does nothing).

The WWS job manager policy module is different: it is embedded in EMAIN.ELF at
a known address, so its fingerprint is computed in-process instead of baked in.
"""
import re
import subprocess
import sys
from pathlib import Path

import target
from dis import read

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT.parent / "ps3recomp" / "tools"
DUMPS = ROOT / "analysis" / "spu" / "dump"
OUT = ROOT / "generated" / "spu_lifted"
REG = target.path("spu_registry")

WWS_JOB_PM_EA = target.addr("wws_job_pm_ea")
WWS_JOB_PM_SIZE = target.addr("wws_job_pm_size")

NAME_RE = re.compile(r"^spujob_([0-9A-Fa-f]{16})_(\d+)\.bin$")

# The SPURS kernel loads a policy module at local-store 0xA00, and the module
# is linked for that address: its scheduler keeps continuation addresses as
# absolute values and branches to them. Lifted at base 0 every such branch
# lands in unrelated code. Jobs are position independent and stay at 0.
PM_LOAD_BASE = 0xA00


def run(*args):
    r = subprocess.run([sys.executable, *map(str, args)],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:], sep="\n", file=sys.stderr)
        raise SystemExit(f"failed: {' '.join(map(str, args))}")
    return r.stdout


def lift(blob, prefix, outdir, base=0, extra=None):
    funcs = outdir.parent / f"{outdir.name}_funcs.json"
    out = run(TOOLS / "find_spu_functions.py", "--raw", "--base", hex(base),
              "--out", funcs, blob)
    n_funcs = re.search(r"Detected ([\d,]+) function", out)
    run(TOOLS / "spu_lifter.py", blob, "--base", hex(base), "--functions", funcs,
        "--symbol-prefix", prefix, "--output", outdir, "--source-name", "spu_recomp.c",
        *(["--extra-funcs", extra] if extra else []))
    return int(n_funcs.group(1).replace(",", "")) if n_funcs else 0


def pic_continuations(raw, lsa):
    """Addresses a body builds as `ila rT, off` + `a rT, rT, r126` and later
    branches to. r126 holds the load address, so the lifter, which sees only
    the offset, does not take them for code."""
    words = [int.from_bytes(raw[i:i + 4], "big") for i in range(0, len(raw) - 3, 4)]
    found = set()
    for w, nxt in zip(words, words[1:]):
        if w >> 25 != 0x21 or nxt >> 21 != 0x0C0:         # ila, a
            continue
        rt, off = w & 0x7F, (w >> 7) & 0x3FFFF
        rb, ra, rt2 = (nxt >> 14) & 0x7F, (nxt >> 7) & 0x7F, nxt & 0x7F
        if rt2 == rt and {ra, rb} == {rt, 126} and off < len(raw) and off % 4 == 0:
            found.add(lsa + off)
    return found


FUNC_RE = re.compile(r"^void (\w+_spu_func_)([0-9A-F]{8})\(spu_context\* ctx\) \{")
XFER_RE = re.compile(
    r"\{ ctx->pc = (0x[0-9A-Fa-f]+); g_spu_trampoline_fn = (\w+_spu_func_([0-9A-F]{8})); return; \}")


def chain_forward(outdir):
    """Turn transfers to a LATER block of the same image into direct tail calls.

    The lifter ends every block by naming the next one in g_spu_trampoline_fn
    and returning to a dispatch loop, including when the next block is simply
    the code that follows. The sound mixer's per-sample filter loop is three
    such blocks, so each audio sample cost three trips through the dispatcher
    and its per-step checks, which was over a quarter of the job thread's
    time. A forward transfer (taken or fallen into) becomes a guaranteed tail
    call instead. Backward transfers still go through the dispatcher, so every
    loop keeps passing the point where interrupts and halts are noticed.
    `spu_link` calls and indirect branches are left alone. Idempotent."""
    src = outdir / "spu_recomp.c"
    out, cur, n = [], None, 0
    for line in src.read_text(encoding="utf-8").split("\n"):
        m = FUNC_RE.match(line)
        if m:
            cur = int(m.group(2), 16)
        elif cur is not None and "spu_link(" not in line:
            def sub(x):
                nonlocal n
                if int(x.group(3), 16) <= cur:
                    return x.group(0)
                n += 1
                return ("{ ctx->pc = %s; __attribute__((musttail)) return %s(ctx); }"
                        % (x.group(1), x.group(2)))
            line = XFER_RE.sub(sub, line)
        out.append(line)
    src.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return n


def main():    # --chain: apply chain_forward to the job images already generated, without
    # lifting again.
    if "--chain" in sys.argv:
        for d in sorted(OUT.glob("j*")):
            if d.is_dir():
                print(f"  {d.name}: {chain_forward(d)} forward transfers made direct")
        return
    dumps = sorted(p for p in DUMPS.glob("spujob_*.bin") if NAME_RE.match(p.name))
    if not dumps:
        raise SystemExit(f"no spujob_*.bin in {DUMPS} -- run with SPU_DUMP_MISS first")

    # image_id 1 is the policy module. It is embedded in the executable, so it
    # is cut out of input/EMAIN.ELF here instead of being captured at run time.
    pm_blob = ROOT / "analysis" / "spu" / "wwsjob.bin"
    pm_blob.write_bytes(read(WWS_JOB_PM_EA, WWS_JOB_PM_SIZE))
    pm_dir = OUT / "wwsjob"
    pm_dir.mkdir(parents=True, exist_ok=True)
    # Entry points nothing branches to directly. The interrupt handler is one:
    # the module reaches it through a branch instruction it writes to LS 0 at
    # run time, so the function finder cannot see it.
    n = lift(pm_blob, "gt5p_wwsjob", pm_dir, base=PM_LOAD_BASE,
             extra=target.TARGET.get("wws_job_pm_extra_funcs"))
    print(f"  policy module at 0x{WWS_JOB_PM_EA:08X}: {n} functions -> {pm_dir.relative_to(ROOT)}")

    # Jobs take 2..N.
    jobs, total = [], 0
    for i, blob in enumerate(dumps, start=2):
        fp, size = NAME_RE.match(blob.name).groups()
        prefix = f"gt5p_j{fp[:8]}"
        outdir = OUT / f"j{fp[:8]}"
        outdir.mkdir(parents=True, exist_ok=True)
        n = lift(blob, prefix, outdir)
        total += n
        print(f"  {blob.name}: {n} functions -> {outdir.relative_to(ROOT)}"
              f" ({chain_forward(outdir)} forward transfers made direct)")
        jobs.append((fp, int(size), prefix, i, blob.name))

    externs = "\n".join(
        f"extern void {p}_spu_func_00000000(spu_context*);\n"
        f"extern void {p}_spu_recomp_register(void);" for _, _, p, _, _ in jobs)
    regs = "\n\n".join(
        f"    /* {name} */\n"
        f"    spu_begin_image({img});\n"
        f"    {p}_spu_recomp_register();\n"
        f"    spu_workload_register_img(0x{fp}ULL, {p}_spu_func_00000000, {img},\n"
        f"                              \"j{fp[:8]}\");"
        for fp, _sz, p, img, name in jobs)

    # Job bodies the policy module streams into its own local store and then
    # branches into. They sit at fixed addresses in the executable, so they are
    # cut from it like the policy module, and lifted at the local-store address
    # the module loads them to. Find new ones with SPU_DUMP_OVL=<dir>,<lsa>.
    for k, (ea, size, lsa) in enumerate(target.TARGET.get("wws_job_bodies", [])):
        ea, lsa, img = int(ea, 16), int(lsa, 16), 2 + len(jobs) + k
        blob = ROOT / "analysis" / "spu" / f"body_{ea:08X}.bin"
        blob.write_bytes(read(ea, size))
        prefix, outdir = f"gt5p_b{ea:08X}", OUT / f"b{ea:08X}"
        outdir.mkdir(parents=True, exist_ok=True)
        # The module enters a body at the offset in its header, which nothing
        # in the body branches to, so the function finder needs to be told.
        raw = blob.read_bytes()
        seeds = {lsa + int.from_bytes(raw[0x10:0x14], "big")} | pic_continuations(raw, lsa)
        n = lift(blob, prefix, outdir, base=lsa, extra=",".join(map(hex, sorted(seeds))))
        total += n
        print(f"  job body at 0x{ea:08X}: {n} functions -> {outdir.relative_to(ROOT)}")
        externs += f"\nextern void {prefix}_spu_recomp_register(void);"
        regs += (f"\n\n    /* job body at 0x{ea:08X}, {size} bytes, runs at LS 0x{lsa:X} */\n"
                 f"    spu_begin_image({img});\n"
                 f"    {prefix}_spu_recomp_register();\n"
                 f"    spu_overlay_register_region(0x{ea:08X}u, {size}u, {img});")

    REG.write_text(TEMPLATE.format(externs=externs, regs=regs,
                                   pm_ea=f"0x{WWS_JOB_PM_EA:08X}",
                                   pm_size=WWS_JOB_PM_SIZE, pm_base=PM_LOAD_BASE,
                                   n_jobs=len(jobs)), encoding="utf-8")
    print(f"\n{len(jobs)} job images, {total} SPU functions lifted")
    print(f"wrote {REG.relative_to(ROOT)}")


TEMPLATE = '''/* SPU workload registry for Gran Turismo 5 Prologue -- GENERATED by
 * scripts/lift_spu_jobs.py. Do not edit by hand.
 *
 * The runtime matches a guest SPU image by content fingerprint and runs the
 * lifted entry registered here. Without a match it logs
 *
 *     [spurs-job] dispatch MISS fp=... size=... job=...
 *
 * and runs nothing, silently -- the job does no work and whatever was waiting
 * on it waits forever.
 *
 * Two kinds of image are registered below.
 *
 * The WWS job manager POLICY MODULE is embedded in EMAIN.ELF at a known
 * address, so its fingerprint is computed here from the loaded image using the
 * runtime's own hash. That is not fussiness: spu_workload_fingerprint is
 * documented as FNV-1a-64 but seeds with 1469598103934665603, the offset basis
 * with a digit dropped (14695981039346656037 is the real one). Self-consistent,
 * so it hashes fine -- but a constant from any offline FNV-1a-64 will not match.
 *
 * The JOB images have no fixed address; they are only visible when the chain
 * dispatches them. Their fingerprints come from the SPU_DUMP_MISS filenames,
 * which is the runtime's own value, so they are safe to bake in. A fingerprint
 * here must match its dumped file exactly or the image will miss again.
 */
#include <stdio.h>
#include <stdint.h>
#include "spu_workload.h"

extern unsigned char* vm_base;
extern void spu_begin_image(int image_id);
extern void spu_overlay_register_region(uint32_t content_ea, uint32_t span, int image_id);

extern void gt5p_wwsjob_spu_func_{pm_base:08X}(spu_context*);
extern void gt5p_wwsjob_spu_recomp_register(void);

{externs}

#define WWS_JOB_PM_EA   {pm_ea}u
#define WWS_JOB_PM_SIZE {pm_size}u

/* Call after the ELF is in memory and before the game creates any SPURS
 * workload, job chain or task -- main.cpp does both. */
void gt5p_spu_register_all(void)
{{
    uint64_t fp = spu_workload_fingerprint(vm_base + WWS_JOB_PM_EA, WWS_JOB_PM_SIZE);

    spu_begin_image(1);
    gt5p_wwsjob_spu_recomp_register();
    spu_workload_register_img(fp, gt5p_wwsjob_spu_func_{pm_base:08X}, 1, "Wws_Job");

{regs}

    spu_begin_image(0);

    printf("[GT5P] SPU: Wws_Job (fp=0x%016llX) + {n_jobs} job image(s) registered\\n",
           (unsigned long long)fp);
}}
'''

if __name__ == "__main__":
    main()
