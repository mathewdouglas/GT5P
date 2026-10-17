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
import os
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

# Guest registers kept in C locals inside each lifted function (the lifter's
# --regcache), off unless SPU_REGCACHE=1: on GT5P's hot render loop it measured
# 0.85-0.97x (Phase 45; about 70 live registers do not fit in 16 XMM ones).
REGCACHE = os.environ.get("SPU_REGCACHE", "0") == "1"

# Seed the targets of position-independent jump tables (pic_tables below).
# SPU_PIC_TABLES=0 lifts without them, as before Phase 47.
PIC_TABLES = os.environ.get("SPU_PIC_TABLES", "1") != "0"

# Resume entries (Phase 66): a job the job manager suspends at an interrupt
# point and a later run resumes has no host frames, so it returns up its guest
# call chain through call-return addresses that are no lifted entry, and the
# SPU interpreter takes over (the Daytona load froze that way). Each such
# address gets a copy of the rest of its function; the function itself is
# lifted unchanged. SPU_RESUME_SEEDS=0 lifts without them.
RESUME_SEEDS = os.environ.get("SPU_RESUME_SEEDS", "1") != "0"

# Absolute code-address tables in job bodies (Phase 72, abs_tables).
# SPU_ABS_TABLES=0 lifts without their targets.
ABS_TABLES = os.environ.get("SPU_ABS_TABLES", "1") != "0"


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
    resume = resume_points(Path(blob).read_bytes(), base, funcs) if RESUME_SEEDS else set()
    run(TOOLS / "spu_lifter.py", blob, "--base", hex(base), "--functions", funcs,
        "--symbol-prefix", prefix, "--output", outdir, "--source-name", "spu_recomp.c",
        *(["--extra-funcs", extra] if extra else []),
        *(["--resume-funcs", ",".join(map(hex, sorted(resume)))] if resume else []),
        *(["--regcache"] if REGCACHE else []))
    return int(n_funcs.group(1).replace(",", "")) if n_funcs else 0


def abs_tables(raw, lsa):
    """Targets of absolute code-address tables: quadwords whose four words are
    each 0 or a word-aligned address inside the image, at least two of them
    set. The render body's skinning keeps its software-pipelined loop entries
    that way (LS 0x16330-0x16400 in 0x01376080) and reaches them by `lqa`,
    `rotqbyi` and `bi`; 0x11520 was never lifted, so every skinned draw fell
    to the SPU interpreter (Phase 72). Shuffle-pattern constants have their
    low bits set and fail the alignment test."""
    lo, hi = lsa + 0x10, lsa + len(raw)
    found = set()
    # The first 0x20 bytes are the body's header: entry OFFSETS, not addresses.
    for o in range(0x20, len(raw) - 15, 16):
        ws = [int.from_bytes(raw[o + i:o + i + 4], "big") for i in range(0, 16, 4)]
        ok = [w == 0 or (w % 4 == 0 and lo <= w < hi) for w in ws]
        if all(ok) and sum(1 for w in ws if w) >= 2:
            found |= {w for w in ws if w}
    # A target must hold an instruction, not more table.
    return {t for t in found if int.from_bytes(raw[t - lsa:t - lsa + 4], "big") != 0}


def resume_points(raw, base, funcs_json):
    """Call-return addresses a resumed job can come back through: those of
    calls whose callee can reach an interrupt-enable point (a branch with the
    E bit), counting every indirect call as able to."""
    import json
    bounds = sorted((e["start"], e["end"]) for e in json.loads(Path(funcs_json).read_text()))
    words = [int.from_bytes(raw[i:i + 4], "big") for i in range(0, len(raw) - 3, 4)]

    def owner(pc):
        inner = [s for s, e in bounds if s <= pc < e]
        return max(inner) if inner else None

    calls, may = [], set()
    for i, w in enumerate(words):
        pc, op9, op11 = base + 4 * i, w >> 23, w >> 21
        if op11 in (0x1A8, 0x1A9, 0x1AA, 0x1AB, 0x128, 0x129, 0x12A, 0x12B) and w & 0x40000:
            if owner(pc) is not None:
                may.add(owner(pc))
        if op9 == 0x066:                                    # brsl
            d = (w >> 7) & 0xFFFF
            calls.append((pc, pc + 4 * (d - 0x10000 if d & 0x8000 else d)))
        elif op9 == 0x062:                                  # brasl
            calls.append((pc, 4 * ((w >> 7) & 0xFFFF)))
        elif op11 in (0x1A9, 0x1AB):                        # bisl, bisled
            calls.append((pc, None))
    calls = [(pc, t, owner(pc)) for pc, t in calls if owner(pc) is not None]
    reaches = lambda t: t is None or owner(t) in may
    while True:
        more = {f for _, t, f in calls if f not in may and reaches(t)}
        if not more:
            break
        may |= more
    return {pc + 4 for pc, t, _ in calls if reaches(t)}


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


def pic_tables(raw, lsa):
    """Targets of position-independent jump tables: `ila rT, table`, then
    within a few instructions `a rY, rT, r126`, then a load from rY and a `bi`
    to table + entry. The entries are signed offsets from the table, so the
    function finder sees data, not branch targets, and handlers only reached
    through the table are never lifted. At run time they then fall to the
    SPU interpreter (Phase 47: job j307E5DC7's table at LS 0x1C84, three of
    its 38 targets unlifted)."""
    words = [int.from_bytes(raw[i:i + 4], "big") for i in range(0, len(raw) - 3, 4)]
    found = set()
    for i, w in enumerate(words):
        if w >> 25 != 0x21:                                 # ila
            continue
        rt, off = w & 0x7F, (w >> 7) & 0x3FFFF
        if off % 4 or off >= len(raw):
            continue
        if not any(nxt >> 21 == 0x0C0 and {(nxt >> 7) & 0x7F, (nxt >> 14) & 0x7F} == {rt, 126}
                   for nxt in words[i + 1:i + 9]):         # a rY, rT, r126
            continue
        targets = []
        for k in range(off // 4, min(len(words), off // 4 + 512)):
            e = words[k] - (1 << 32) if words[k] >> 31 else words[k]
            t = off + e
            if e == 0 or t % 4 or not 0 <= t < len(raw):
                break
            targets.append(lsa + t)
        if len(targets) >= 2:
            found.update(targets)
    return found


FUNC_RE = re.compile(r"^void (\w+_spu_func_)([0-9A-F]{8})\(spu_context\* ctx\) \{")
# With the register cache a transfer first stores the registers it changed,
# "{ ctx->gpr[5] = r5; ... ctx->pc = ...". Those stores are kept.
XFER_RE = re.compile(
    r"\{ ((?:ctx->gpr\[\d+\] = r\d+; )*)ctx->pc = (0x[0-9A-Fa-f]+); "
    r"g_spu_trampoline_fn = (\w+_spu_func_([0-9A-F]{8})); return; \}")


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
                if int(x.group(4), 16) <= cur:
                    return x.group(0)
                n += 1
                return ("{ %sctx->pc = %s; __attribute__((musttail)) return %s(ctx); }"
                        % (x.group(1), x.group(2), x.group(3)))
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
        seeds = pic_tables(blob.read_bytes(), 0) if PIC_TABLES else set()
        n = lift(blob, prefix, outdir, extra=",".join(map(hex, sorted(seeds))) or None)
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
        if PIC_TABLES:
            seeds |= pic_tables(raw, lsa)
        if ABS_TABLES:
            seeds |= abs_tables(raw, lsa)
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
