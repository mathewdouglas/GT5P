# Plan: the Car Dealer page at 30 fps

Written 2026-10-16 from the measurements in [progress.md](progress.md) Phase 53.
Each step names its gate: the measurement that says it is done. Measure with
`scratch\perf.ps1 -Tag <t> -N 3` (median of three, `FS_HIDE` on, no settings
file) unless a step says otherwise. Every change gets a switch to undo it.

## Status after Phase 63 (2026-10-17)

- **Acura page:** a median of 29.6 fps against a cap of 29.97 (the vblank
  now runs at 59.94 Hz).
- **Ferrari page:** 25.1 fps median, 20 to 30 depending on the car pair.
  The other dealers with more than two cars behave the same way.
- **The critical path is the SPU render pass.** Frames take whole vblanks,
  so a frame is 2 vblanks (33.4 ms) only while the pass, plus about 2 ms
  around it, fits in that.
- **Phase 64:** step 1 is done (0 freezes in 20 Ferrari visits) and GPU
  timestamps are in (about 20 ms of GPU per Ferrari frame). Lane pinning
  is now the default: **Ferrari median 28.2 fps** (24.8 unpinned).
- **Done:** steps 0 (stall detection), 2, 4 and 5b.
- **Dropped:** step 3 (no GPU wait to hide). 5a and 5c measured nothing.
- **Open:**
  - step 1 (the stalls, now traced to two shapes of a ring-space deadlock,
    Phase 63);
  - 5d;
  - GPU timestamps;
  - step 6;
  - pipelines built ahead of time (background compiling is in, Phase 65);
  - step 7 below.
- **The step 5 gate (35 fps with drawing off) cannot be reached under
  vblank pacing.** Read it as "the render pass in 28 ms or less on the
  heaviest pair". Today that pair takes about 36 ms.
- **The SPU runtime is done for now.** Phase 62 took 1.15x off the lanes'
  time, and what is left of it is about 22%. Lane pinning (Phase 63) is
  another 1.14x but waits on step 1.
- **About 69% of the lanes' busy time is the render job's own code** (job
  body `b01376080`). Step 7 is about that code.

## Where the time goes

Frames are shown on a 16.7 ms vblank, so 30 fps needs every frame done in under
33 ms. Two limits are each too slow, and both have to come down:

| Limit | Now | Target |
| --- | --- | --- |
| The present thread: FIFO walk, vertex conversion, D3D12 submission | about 44.5 ms a frame (18 fps) | 28 ms or less |
| The title's own threads (PPU and SPU), measured with every draw dropped (`RSX_VTX_SKIP=1`) | 24.5 fps ceiling (about 41 ms) | 35 fps or more (28 ms) |

The dealership also stalls in about one run in three (Phase 46.3), which
makes it unplayable and spoils measurements.

What the present thread spends its frame on (`GT5P_SAMPLE`): 23% in D3D12 and
driver calls from the frame loop; about 34% CPU vertex conversion
(`ix_vertex`, `vplan_fetch`, `vplan_build`); 3% hashing fragment programs
every draw; small debug and checking costs. Each frame starts with
`wait_for_gpu()`, so the CPU and GPU never work at the same time.

What the title's threads spend it on: the main thread is about half runtime
plumbing (`lv2_syscall` 22%, `vm_write64` 14%, the SPU coherency check on
writes 8%, mutexes 8%). `PDI:1` mostly spins in the queue-3 wait
(`func_00BA97B0`) calling `cellSpursGetWorkloadInfo`, paying for HLE routing
and `ppu_prof_resolve_host` on every call. The SPU job lanes use about 2.6
cores in threads created per dispatch.

## Steps

### 0. Measurement first (small)

- `perf.ps1` detects a stalled run (no presents) and repeats it, reporting
  the stall count.
- GPU timestamp queries: the GPU's own time per frame, which step 3 needs.
  **Done (Phase 64):** a timestamp at each end of the frame's command list
  (`RSX_GPU_TIME=0` turns it off). The `[present-prof]` line prints the 5 s
  average and maximum, and F3 shows the last frame. On this machine (4x
  MSAA, shaded per sample): about 7 ms on the menu and 20 ms on the Ferrari
  page, with peaks to 30 ms. This GPU fits the 33 ms budget, but a GPU at
  half its speed would not: there MSAA is the first setting to lower.

### 1. The dealership stall

Sampled in the act: four job lanes spin in `spu_rdch` (waiting on an SPU
channel) inside job body `b01376080` at `0x462C`/`0x4598`, while `PDI:1`
waits in the queue-3 loop. Find the channel, who should write it, and why
they do not (a lane hand-off race is the standing hypothesis).

Gate: no stalls in 10 runs. **Halfway (Phase 54):** the title's ready-count
kicks were lost to a `PUTLLC` race; with that fixed, 3 stalls in 37 runs
(one batch of 10 had none), against 7 in 38 before. The rest is open.

**Done (Phase 64):** 0 freezes in 20 Ferrari visits. Lane 3, which the
render lists' SPU mask (`0xEF` at header `+0x2F`) excludes, was still sent
in, and the job manager's per-SPU bookkeeping row for SPU 3 is queue 3's
progress row: its plain `PUT`s overwrote the other SPUs' progress.
`SPURS_LANE_MASK` sends only the SPUs a list allows.

### 2. Cheap fixes on the present thread (about 2-3 ms)

- `rsx_vtx_pos_dbg` runs once per draw and returns at once; its 1.4% is more
  likely an unnamed static function after it, charged to the nearest name by
  `scratch/maplook.py`. Left alone.
- `rsx_fp_code_hash`: cached per program address while the program's
  instruction slots are unchanged (`RSX_FPHASH_CACHE=0` to undo), instead of
  two byte-at-a-time walks every draw.
- `tex_snap_draw`: returns at once when no texture is volatile.

### 3. CPU/GPU overlap (dropped, Phase 56)

Measured: the GPU wait at frame start is 0, so there is nothing to overlap.
The original text follows.

Keep two sets of per-frame upload resources (vertices, constants, indices,
texture staging) and wait only for the frame before last, instead of draining
the GPU at the start of every frame. Step 0's GPU time says the real gain
before committing. Risk: geometry torn by a buffer reused too early (it has
happened in this code; Phase 34's gcm/cube note), so behind a switch and
checked with captures.

### 4. Vertex conversion (about 15 ms, a third of the frame)

**Phase 56:** 4b is in (`RSX_VTX_GPU`, with sparse calls left to the CPU):
15.7 to 17.2 fps. Uploads still take about 21 ms of the walk, now index
handling and the sparse calls; 4a (a cross-frame cache of converted
vertices, as the Yakuza port has) is the next lever there.

**Phase 57:** 4a is in (`RSX_VTXCACHE`), as a cache of the raw streams the
GPU decodes rather than of converted vertices. About 19.6 fps; uploads went
from 21 to 12.5 ms. Half of each frame's uploads are the SPU's output ring,
new every frame, and cannot be cached. What remains in the walk is the index
handling, about 1.65 million indices a frame. The present itself takes about
12 ms on the same thread.

**Phase 58:** the present is off the walker (`RSX_PRESENT_THREAD`), and its
descriptor writes are cached (`RSX_SRV_CACHE`): 25.1 fps. A frame is now
about 8 ms of waiting for the flip, then a 30 ms SPU pass (max 35 to 39).
The walker takes 26 ms of that pass. With drawing off the title reaches
29.3 fps. What is left is a faster walk (index handling, method decode) and
faster SPU job code (step 5).

- **4a** Keep converted vertex data from frame to frame. The showroom and the
  cars barely change: find a candidate by draw metadata, compare its source
  bytes, and convert only what changed (as the Yakuza port does, below).
- **4b** If 4a falls short: let the GPU decode the guest's vertex formats
  (upload raw streams, decode in the vertex shader), as RPCS3 does.

Gate: present thread at 28 ms a frame or less.

### 5. The title's own threads (24.5 to 35 fps or more)

- **5a Guest memory access, inline.** Every guest load and store in the lifted
  code is an out-of-line call (`vm_read32`, `vm_write64` in `ppu_loader.cpp`),
  each checking a mode flag, bounds, the null page and the raw SPU register
  window, and every store runs the coherency check. A header-inline fast path
  (one range test for the special windows, the coherency check only while a
  reservation is held) helps every guest thread at once. The largest lever
  outside rendering.
- **5b Persistent SPU lanes.** A pool of lane threads instead of `CreateThread`
  per dispatch. Count creations per second first.
- **5c The queue-3 spin.** Make `cellSpursGetWorkloadInfo` and its HLE path
  cheap (no `ppu_prof_resolve_host` per call), and yield when nothing has
  changed, so `PDI:1` stops taking a core from the lanes.
- **5d Main-thread plumbing.** Which syscalls dominate `lv2_syscall`'s 22%,
  and a fast path for them; the mutexes.

Gate: `RSX_VTX_SKIP=1` reaches 35 fps or more.

**5b done (Phase 56):** lane pool, kernel wake, idle-lane pruning, 1 ms
stagger: title-only 23.4 to 29.3 fps.

**Measured (Phase 55):** 5a (`GT5P_VM_INLINE`) and a pause in the 5c spin
change nothing within noise; the ceiling stays about 23 fps. The main thread
is not saturated (77%); `PDI:1` waits for the SPU workloads. The ceiling is
the SPU job pipeline's latency, so 5b and the job lists' critical path come
before any more PPU work.

### 7. Native versions of the hot code

The game's code runs natively compiled but as a faithful PS3: every SPU job
runs on an emulated SPU, with 128 registers kept in memory, a 256 KB local
store and DMA copies in and out. x86 has 16 vector registers, so the hot SIMD
loops spill constantly; Phase 45 measured that a register cache cannot fix
that.

A native version is written for the PC from what the code does. It keeps
its data in host registers and host memory, and can be split over more
threads than the four lanes the title uses. The Yakuza port does this for
its hottest SPU jobs.

**Candidates.** Shares are of the render lanes' busy samples on the Ferrari
page (`GT5P_SAMPLE=all GT5P_SAMPLE_GRAIN=16`, Phase 62's build). Lifted
"functions" are fragments split at branch targets, so the units are address
ranges of job body `b01376080`, which runs at LS `0x4000`.

| # | Code | Share | What it looks like | Why it is a candidate |
| --- | --- | --- | --- | --- |
| 7a | Routine at `0xF400` (called from `0x8E4C` and `0x8F54`): setup `0xF620`, loop `0xF8C0`, tail `0xFDE0` | 22.6% | `0xF8C0` is a 146-instruction loop: 36% byte shuffles, 23% integer, 16% float (`fma`, `fnms`, `fcgt`), 8% selects, 12% local-store loads and stores, and a compare against `0xFFFF` (a strip-restart index). **Hypothesis:** a per-triangle test over an index buffer (facing and zero-area tests from cross products) that compacts the surviving indices. | One routine, one hot loop, the largest single share. If it is culling, the PC's GPU culls anyway, so a native version could also pass every triangle through (a deliberate, visible change, behind its own switch). |
| 7b | `0x10418`-`0x10F80` (`0x10EE0` 6.8%, `0x10C18` 4.7%, `0x10418` 2.8%, `0x10938` 1.4%, ...) | 17.7% | Branchy, no loops inside the fragments; memory 25-32%, selects 13-16%, little float. No direct `brsl` callers, so it is entered by jumps. **Hypothesis:** per-vertex or per-attribute output formatting. | Second largest. Find its entry and its loop first. |
| 7c | `0xB140`-`0xBCA0` (entries `0xB140`, `0xB640`, `0xBC80`; hot `0xBB50`, `0xB3E0`, `0xB240`) | 13.5% | Mixed float and shuffle, small loops. | Three small entry points, easier to check one at a time. |
| 7d | `0xD0F8`-`0xD500` (entries `0xD0F8`, `0xD200`, `0xD340`, `0xD440`, `0xD500`) | 5.0% | Short float and memory loops (`0xD480`: 37% memory, 25% float). | Small and self-contained: a good first one to prove the method on. |
| 7e | The ring-space wait at `0x4554`-`0x462C` | part of 5.9% | Polls a ring label by DMA, reading the decrementer each time. | Replace the poll with a wait on the label write (the FIFO walker writes it). Frees lane time while waiting, and is the place to break the Phase 63 deadlock. |
| 7f | The sound job chain (`j65DD2F53` `0x1E8`, `0x220`, `0x234`; `jA95EC7E4` `0xA890`, `0xAD68`) | about a quarter of a core, always | The mixer and its DSP jobs. | Not on the frame's critical path, but always running; a native mixer frees most of that core on a 4- to 6-thread CPU. Risk: audible differences. |
| 7g | PPU waits: `PDI:1` in `func_00BA97B0` and `func_00BA9510` (job-list counters, then `cellSpursGetWorkloadInfo` in a loop); Main's poll loop (`func_0091312C`, `func_00912E30`, `func_009131E0`, `func_0092CD68`) | about 1.6 cores of spinning | Busy-wait loops on guest memory. | A blocking wait, woken by the lane or group-end event, gives no fps here (12 threads) but frees cores on smaller CPUs. Small and checkable. |

Regions 7a to 7d are about 59% of the lanes' busy time. At 2 to 4 times
faster natively, the pass would be about 1.4 to 1.8 times shorter: the
heaviest pair from about 36 ms to 20-26 ms, inside the 28 ms target.

**How each one is done:**
1. **Understand it first.**
   - From the disassembly (`scratch/fnmix.py` for the instruction mix, the
     callers and the loops; `tools/spu_disasm.py`), and from its inputs and
     outputs in local store, traced on a live run.
   - Write the behaviour up in `progress.md`: what it reads, what it writes,
     the edge cases.
   - The native code is written from that description, not pasted from the
     lifted C (which is generated from the game and stays out of tracked
     files).
2. **Swap it in at the function registry.** A native function registered
   for the same image and LS address replaces the lifted one, so the job
   manager and the rest of the body are untouched.
   - One switch for all of them, `SPU_NATIVE=0`, and one per candidate
     (`SPU_NATIVE_OFF=7a,...`).
   - A native version must leave registers and local store exactly as the
     original would wherever later code reads them.
3. **Check it against the lifted original:**
   - **offline:** the Phase 45 harness (`scratch/rc/bench.c`) runs both on
     the same random register and local-store state and compares every
     register and every local-store byte (NaN payloads aside);
   - **in game:** `SPU_NATIVE=check` runs both on copies of the context for
     every call and reports the first difference, as `RSX_VTX_GPU=check`
     does for vertices;
   - **frames:** captures compared with the lifted build's, on the same car
     pair.
4. **Measure it within one boot** with an A/B switch (Phase 62's method:
   `SPURS_LANE_CYC=1`, `scratch/abcyc.py`).

**Order:**
1. 7d, to prove the method on something small.
2. 7a, the largest share.
3. 7b and 7c.
4. 7e together with step 1.
5. 7g and 7f, for smaller CPUs.

**Gate:** the heaviest car pair's render pass in 28 ms or less on the Ferrari
page, and frames of two vblanks; no new stalls; captures match.

**Risks:**
- A native version that differs in a corner case (a degenerate triangle, a
  NaN, a buffer boundary) corrupts geometry only now and then. The checker
  mode and the captures are there for that.
- Each version is specific to this executable (BCUS98158 v03.00); another
  build needs its addresses found again (`config/targets.json` is the place
  for them).
- Copyright: the native code is new code written from observed behaviour,
  like the HLE libraries; no game code or decompiled text goes into the
  repository.

### 6. Check the result

Median of five runs at 30 fps or more; the F3 profiler shows frames of two
vblanks, not three; no stalls; captures match the Phase 51 ones;
`scripts/soak.py 6 40` unchanged.

## Wider gains (any screen, not only the dealership)

Status as of Phase 63. Each item is a switch when it is done, and is
measured within one boot where the per-visit car pair would otherwise hide
it.

**Not tried yet:**
- **Compiler settings for the lifted code.**
  - It is built at the default Release optimisation for baseline x86-64.
  - `-mavx2` was measured on one hot SPU loop only, 1.01 to 1.05x (Phase 59);
    never on the whole lifted PPU and SPU code, where 3-operand VEX
    encodings would also cut register moves.
  - Link-time optimisation and profile-guided optimisation (PGO, trained on
    the dealer pages) are untried. PGO suits this code: huge, branchy, and
    with a very uneven profile.
  - Options go on source groups, never as definitions on the whole target,
    and full rebuilds need `CMAKE_BUILD_PARALLEL_LEVEL=4`.
  - AVX2 must stay optional: it would leave out CPUs without it.
- **Pipelines built ahead of time.**
  - A first visit to a dealer page compiles 500 to 800 shaders and
    pipelines, a 20 to 28 s freeze with the badge up.
  - Even with all of them cached, the page's first frame takes up to 8 s,
    rebuilding pipelines from the cache on the replay thread (Phase 42's
    first-entry stall).
  - Options:
    - a D3D12 pipeline library (`ID3D12PipelineLibrary`) saved beside the
      shader cache, so cached pipelines load instead of being rebuilt;
    - building them on worker threads from the cache at boot;
    - compiling new ones off the replay thread and drawing without them for
      a frame or two.
  - **Phase 65: the third option is in** ("Precompile shaders", on). New
    shaders compile on a worker pool and their draws wait out; an empty
    cache's first dealer page shows within about 3 s (it took over a
    minute). Measured with a warm cache, a page entry's misses now cost only
    about 150 ms in all, so the first two options would gain little here.
- **Frames in flight on the GPU.**
  - The replay thread starts each frame with a full `wait_for_gpu()`, so
    recording frame N waits for the GPU to finish N-1. The FIFO walk already
    overlaps the GPU.
  - It gains nothing on this machine (the wait measured 0 on Acura and 2 to
    6 ms on some Ferrari runs). It would help a weaker GPU by up to the
    recording time, 5 to 7 ms a frame.
  - Costs: one frame more of latency, and the risk of torn geometry from an
    upload buffer reused too early (step 3).
  - Set aside for now; it would be a "frames in flight" setting.
- **Indirect branches without the resolver.**
  - After Phase 62 the resolver, its lookup and the drain loop are still
    about 10% of lane time.
  - A per-call-site inline cache would serve most branches with one compare
    and no call: the last target and its function, in the lifted code next
    to each `bi`.
  - So would more constant targets found at lift time: Phase 62 did
    `ila`+`bi`, but not targets loaded from a constant table.
- **Interrupt returns without `longjmp`.**
  - The job manager's DMA interrupts return through `longjmp`, which on
    Windows unwinds the stack: about 2% of lane time (`spu_restart_dispatch`,
    `spu_irq_regs_maybe_restore`).
  - A return that unwinds without the system unwinder (`__builtin_longjmp`,
    or restructuring the drain loop so the handler returns normally) would
    cut it. Risky, because it touches every SPU workload.
- **Decrementer reads.**
  - The ring-space poll reads the SPU decrementer on every pass, a
    `QueryPerformanceCounter` call each time.
  - Reading the time stamp counter (`rdtsc`), scaled once, would be cheaper
    and is enough for a poll's timing.

**Partly done:**
- **The SPU channel and MFC paths.** Phase 62 added fast paths for the SPU
  write hook and the drain. The DMA (`mfc_do_transfer`, its `memcpy`, and
  the reserved-line scan on every `PUT`) and channel reads are still about
  6% of lane time.
- **Thread placement.**
  - Pinning the render lanes to their own cores is 1.14x on the lanes
    (Phase 63), but raises the freeze rate, so it is opt-in until step 1 is
    fixed.
  - Keeping the other busy threads off the lanes' cores is untried: the
    sound chain, the replay thread, the FIFO walker. They could go on the
    core lane 3 leaves idle.
- **The menu's main thread** is at 93% of a core at 31 fps, against the
  console's 60. 5a (inline guest memory access) measured nothing on the
  dealer page and was not re-measured on the menu.

**Measured, no gain:** 5a and 5c on the dealer page (Phase 55); an
ideal-processor hint for the lanes (Phase 63); a register cache in the SPU
lifter (Phase 45).

## What another ps3recomp port does

[Yakuza: Dead Souls EX](https://github.com/canersaka/Yakuza-Dead-Souls-EX)
(MIT, a fork of the same ps3recomp) reaches its game's 30 fps cap in light
scenes and about 20 fps in its crowded opening, which its README calls the
open problem. Read on 2026-10-16; ideas only, nothing copied.

- **Guest memory access inline** (5a). Loads are `vm_base + addr` and a byte
  swap in a header; stores are inline with one SPU-coherence range test. Its
  build notes say inlining these helpers is most of the optimiser's gain.
- **Whole-program optimisation** of the lifted code (`/O2 /Ob3 /GL` and
  link-time code generation, on the lifted objects only). Worth most after 5a,
  when the helpers can be inlined.
- **Geometry reuse** (4a). A cache entry is chosen by metadata, then every
  source byte is compared before the converted output, kept on the GPU, is
  reused; a miss snapshots the input. Comparing bytes is exact and cheaper
  than converting. Conversion runs attribute by attribute over contiguous
  spans. Pipeline state is cached by register state and checked byte for byte
  (step 2's hashing).
- **Frames in flight** (3). Submission does not wait for the GPU; upload sets
  rotate per frame.
- **SPU jobs on persistent workers** (5b), two by default. It replaces SPURS
  job chains with its own runner, which does not carry over: GT5P's render
  jobs run under the title's own job manager (the lifted policy module).
  Some hot SPU jobs (visibility, poses) are rewritten as native AVX2 code: a
  later, title-specific option.
- **Thread placement**: an option puts the RSX consumer and the main SPU worker
  on two separate physical cores of the fastest class.

## Risks

Steps 3 and 4a reuse data across frames, which is exactly where the movie's
tearing and the paint's wrong colours came from: each gets a switch and a
side-by-side capture check. The title's own ceiling (step 5) is the less
certain half; if 5a-5d do not reach 35 fps, the next lever is the SPU job code
itself, which was tuned once already for small gains (Phases 44-45).
