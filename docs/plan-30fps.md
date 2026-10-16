# Plan: the Car Dealer page at 30 fps

Written 2026-10-16 from the measurements in [progress.md](progress.md) Phase 53.
Each step names its gate: the measurement that says it is done. Measure with
`scratch\perf.ps1 -Tag <t> -N 3` (median of three, `FS_HIDE` on, no settings
file) unless a step says otherwise. Every change gets a switch to undo it.

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

### 1. The dealership stall

Sampled in the act: four job lanes spin in `spu_rdch` (waiting on an SPU
channel) inside job body `b01376080` at `0x462C`/`0x4598`, while `PDI:1`
waits in the queue-3 loop. Find the channel, who should write it, and why
they do not (a lane hand-off race is the standing hypothesis).

Gate: no stalls in 10 runs. **Halfway (Phase 54):** the title's ready-count
kicks were lost to a `PUTLLC` race; with that fixed, 3 stalls in 37 runs
(one batch of 10 had none), against 7 in 38 before. The rest is open.

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

### 6. Check the result

Median of five runs at 30 fps or more; the F3 profiler shows frames of two
vblanks, not three; no stalls; captures match the Phase 51 ones;
`scripts/soak.py 6 40` unchanged.

## Wider gains (any screen, not only the dealership)

- **Compiler settings.** The lifted code is built at the default Release
  optimisation for x86-64 baseline: no `/arch:AVX2` (or `-mavx2`), no link-time
  optimisation. Both are measurable switches; PGO (profile-guided optimisation)
  is a further step. Mind the build-note rule: options go on source groups,
  never as definitions on the whole target, and full rebuilds need
  `CMAKE_BUILD_PARALLEL_LEVEL=4`.
- **5a above** applies to every screen; the menu's main thread is at 93% of a
  core at 31 fps (it should run at 60).
- **Pipelines built ahead of time.** Pipeline builds stall the frame thread
  (the "Compiling shaders" badge). A D3D12 pipeline library or
  `ID3D12Device1::CreatePipelineLibrary` cache, or building pipelines on a
  worker thread from the shader cache at boot, removes those stalls.
- **The SPU lifter.** Lane code spends most of its time in channel and MFC
  helpers (`spu_rdch`, `mfc_submit`, `mfc_for`); fast paths for the common
  channels help every SPU workload, sound included.

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
