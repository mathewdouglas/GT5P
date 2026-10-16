# Progress log

The port's investigation, newest phase first. Numbers in a phase are what was
measured *at that phase*; later phases correct earlier readings, and the
corrections are left in place rather than rewritten.

**Working rule for this port.** Structural readings of lifted code have been
wrong far more often than the measurements under them. Before a conclusion goes
in here, run the one command that would falsify it; label anything untested as a
hypothesis in the text itself.

## Phase 66 - A track: the Daytona freeze, and resumed SPU jobs (2026-10-17)

**Reported:** with a car bought, the menu opens on News, and loading a
track sticks on the Daytona logo (Arcade, Track Select, Daytona).

**Menu, scripts.** The save now opens the top menu under a "Confirmation"
popup on every boot (Cross on it is not remembered); Circle closes it. Tabs:
News TV Online Rankings Arcade 2P-Battle Events Garage Dealerships Replay
Options Manual Save, no wrap. Held Right repeats about every 110 ms, too
fast to release on a tab by time, so `scratch/milestone.ps1` (`$ToDealers`)
holds Right 2 s to park on Save, taps Left four times, then Cross; the whole
run is retried once unless `DealerSelectRoot` was read. The list opens 11.8 s
after the menu (15.9 s before). `$DealerHold`, `$FerrariHold`, `dealer.ps1`
and `revisit.ps1` use it; Acura and Ferrari checked. `$DaytonaHold` and
`$DaytonaRaceHold` drive Arcade to Daytona. `scratch/shots.ps1` takes window
shots after any milestone.

**The freeze.** Reproduced first time. The log has `[spu-smc] microstep
img=1 pc=0x0560C ... handing to the interpreter` and then render lanes 0, 1,
2 and 4 leaving their policy-module runs at `pc=0x01700` instead of
exitToKernel, with jobs 0, 2, 4 and 6 of workload 0 in flight for ever
(row `0008 0008 0000 0002 0004 FFFF 0006 FFFF`); SPU 4's lane spins on them.

- `0x560C` is inside body `0x01376080` (at LS 0x4000), right after the
  command dispatcher's `bisl $r0,$r20` at `0x5604` (handlers from a 45-entry
  table at LS `0x155B0`, all lifted). `SPU_DUMP_OVL` during the load shows
  only the two known bodies streamed: no new code.
- The hand-off line now prints its context: `drain_ret=0 depth=0`, and the
  thread's drain trail is a new policy-module run, the interrupt handler
  (`0xA90`, `0xAAC`), the top-of-LS shim (`0x3FEC0`), then `0x7918`.
- So the job manager had **suspended** a render job at an interrupt point
  in an earlier run (op 31's handler `0x7880` calls two job-manager routines
  with interrupts off and turns them on with `bi` to `0x7918`; interrupts are
  taken there) and exited to the kernel; a later run resumes it from its
  local store with no host frames. `0x7918` is a lifted entry, but its
  return to `0x5608`, and every return above it, is not, and the SPU
  interpreter then takes the job to a dead end. Not seen in menus: the race
  runs five workloads.

**Fix: resume entries.** `scripts/lift_spu_jobs.py` finds the call-return
addresses a suspended job can come back through (calls whose callee can
reach a branch with the interrupt-enable bit; any indirect call counts) and
passes them to the lifter's new `--resume-funcs`, which lifts a copy from
each address to the end of its function and leaves that function exactly as
it was, so hot code is unchanged. 18 in the render body (`0x5608`, `0x4C0C`
among them), 172 in `0x0133A700`, 11 in the policy module; a few hundred
instructions in all. `SPU_RESUME_SEEDS=0` at lift time lifts without them.
After: Daytona's Race Mode page loads (no hand-off, no stall), and Single
Race reaches the starting grid.

**Open.**

- The Race Mode page and the starting grid show black where the track
  should be, at about 2,200 draws a frame (reported by the user too).
- After the starting grid the race load (`LoadingRoot`, `RaceRoot`,
  `QuickArcadeRoot`) stops presenting. Thread 20 logs 160
  `[ppu] bctr to NULL` from `func_0080EF74`, `func_008079EC`,
  `func_00811BE0` and others, with descriptor pointers such as `0x48028044`
  (an instruction word) or 1: guest calls through function pointers that are
  garbage. None in any menu, dealer or pit-screen run. Not investigated.

## Phase 65 - Dealers visited in a row, and shaders built in the background (2026-10-17)

**Reported:** go into a dealer, back out, go into another: the second runs
at a much lower frame rate, the third lower still.

**Reproduced** with `scratch/revisit.ps1 -UseSettings` (four dealers in a
row at 1080p; back out with Right, Left, then a 2 s Circle, as the page
ignores Circle until it has had input). Visits 1 and 2 ran at 30 fps,
visit 3 at 3 to 5 and visit 4 at about 2, recovering at once on leaving.

**The cause: the pipeline cache thrashed.** On the slow pages it filled its
8,192 entries in seconds and was emptied several times a second; a frame's
replay took 0.4 to 1.2 s. `PSOMISSDBG=2` (new: every 5 s, misses by the key
field that differed) put 16,000 to 21,000 misses in 5 s on `unnorm`.
- A program sampling a texel-addressed unit with no sample site to rescale
  is compiled once for every texture size: its pipeline is cached under
  `unnorm` 0 and its code hash goes in a set, so later lookups use 0.
- That set was a list of 128. Past it, lookups kept the real `unnorm`,
  missed the entry stored under 0, and compiled again on every draw. Each
  dealer adds programs, so the list ran out on the third or fourth page.

**The fix:** a hash set of 2,048, and an entry is stored under 0 only when
its program is in the set (`RSX_UNNORM_KEYFIX=0` for the old way). The
same four visits: 30, 30, 27-30 and 23-26 fps; the last is a heavier page
(3,300 draws, replay 6 ms a frame, no rebuilding). No cache-full message.

### Shaders built in the background ("Precompile shaders", on)

**Where shader time goes** (`RSX_PSO_TIMING=1`, new: a pipeline miss split
into HLSL, DXBC and the driver's pipeline build, every 5 s):
- With the disk cache warm, a dealer entry has about 300 misses costing
  150 ms in all (45 ms HLSL, 30 ms reading DXBC, 80 ms in the driver). Not
  the problem.
- With an empty cache (`RSX_SHADER_CACHE=<empty dir>`), the frame thread
  compiled 161 shaders one at a time, 0.1-0.5 s each, and the first dealer
  page had not appeared after 80 s.
- Shaders cannot be built before the game has shown them once: they come
  from its data as it plays. What can change is when and where.

**The change** (`RSX_SHADER_ASYNC=1`, set by GT5P and by the settings
page's "Precompile shaders", on by default):
- A pixel or vertex shader not on disk is handed to a pool of worker
  threads (half the logical CPUs, below normal priority;
  `RSX_SHADER_WORKERS`). The frame's pre-pass looks every draw up before
  recording, so all of a new page's shaders are queued in the first frame
  and compile in parallel.
- A worker writes the DXBC where the disk cache reads it; finishing is the
  file appearing. A failed compile is done again on the frame thread, which
  reports it as before.
- Until then the draw is left out (`VS_PENDING` for vertex shaders, dropped
  at record time on the GPU-fetch path, skipped at replay otherwise).
- Waiting pipelines and vertex programs are remembered, so the HLSL is not
  rebuilt for them every frame (it took 4.2 s of every 5 s before).
- Empty cache, three runs of two new dealers each: the first page shows
  within about 3 s and runs at 17-27 fps for 6-9 s while it fills in, then
  30; the second takes 3-6 s. No freeze in the six visits.

**Holding the picture triggers the ring-space deadlock.** Showing the last
complete frame instead of a half-drawn one (not calling `Present` while a
draw waits) froze the page in 2 of 3 empty-cache first visits: lanes
spinning at `0x4560`, one lane needing to wrap with its label at its ring's
start (`label=2A6BDF80`, start + size `2A6C2F80`). So Phase 63's first shape
is still a latent race, which the Phase 64 fix made rare (none in 60+
visits) but did not remove. `RSX_SHADER_ASYNC_HOLD=1` keeps that behaviour as
a way to reproduce it; by default partial frames are shown. Not followed up
yet: workloads 0 and 1 write the same ring memory per SPU (both lane-0 rings
start at `2A2BDF80`) with separate heads and labels, as our lane contexts
are per (workload, SPU); on the console both workloads would share the SPU's
local store.

**And without either.** In a 10-visit Ferrari check of this build (warm
cache, nothing compiled in any run), run 8 froze in the same shape. A
missed Right press had taken it to Daihatsu, so the race is not Ferrari's.
All four of workload 0's lanes needed to wrap, each with its label at its
ring's start. Its header showed the list's first 16 bytes (`+0x80`) as all
`FF`: SPU 4's bookkeeping row (`+0x40 + 16 * 4`) lies on them, as SPU 3's
lay on queue 3's row. Not followed up yet. The other nine: median 26.6 fps.

**Settings page:** "Precompile shaders" (VIDEO, on; key
`video.shader_precompile`). "Fifth SPU lane" is no longer on the page (it
cannot work, Phase 64); its file key stays for testing.

## Phase 64 - The dealer-page freeze: SPU 3 wrote over the progress row (2026-10-17)

**Result:** 0 freezes in 20 Ferrari visits (`perf.ps1 -Ferrari -N 20`),
against 5 in 26 over the two batches before the fix. Step 1's gate (no
freezes in 10 runs) is met. With that, lane pinning is on by default:
Ferrari runs at a median 28.2 fps (24.8 unpinned), with no freeze in 20.

**How a WWS job list reports progress** (the policy module's code at
`0x3320`-`0x3540` and the title's wait at `func_00BA97B0`):
- The header is the workload's data (`0x20022080` and `0x2002A100` for the
  render lists). A list pointer per queue at `+0x30 + 4q`; the render lists
  use queue 3 only, with its list at `+0x80`.
- Queue 3's row is at `+0x70`. Halfword 0 is the head the PPU has
  published. Halfword `spuNum + 2` is written by that SPU with a
  `GETLLAR`/`PUTLLC` loop at `0x3488`: the lowest index among the jobs it
  still has in flight on the queue, or `FFFF` when it has none.
- The title waits until the smallest of halfwords 1-7 reaches the head plus
  the run of non-empty entries after it.
- **Each SPU also keeps a bookkeeping row of its own at `+0x40 + 16 *
  spuNum`**, written with plain DMA `PUT`s: 16 bytes of `FF` on entry
  (`0x27E0`) and a count with leftover register words on exit (`0x2808`).
  Rows 0-2, which looked like unused queues (`00000000 1FFFFFFF ...`), are
  SPUs 0-2's.

**The cause.** SPU 3's bookkeeping row is queue 3's progress row.
- The render lists exclude SPU 3: the SPU mask byte at header `+0x2F` is
  `0xEF` (bit `0x80 >> spuNum`). So lane 3 never takes a job, but it still
  entered and left the module, and its plain `PUT`s landed on the live row
  between the other SPUs' atomic updates.
- A slot could then hold a job its SPU had long finished, or `1FFF`. The
  stalled rows show it: `0499 0499 0494 FFFF 1FFF FFFF 1FFF FFFF` has SPU
  3's leftover words in its second half, and SPU 0 is stuck at `0494`.
- Lane 3 was sent on the first eight dispatches of a list (until
  `SPURS_LANE_PRUNE` left it out) and on every 64th after. The stalls fit:
  dispatches 1, 1, 3, 5, 7 and 128.
- Both of Phase 63's shapes follow from it. With a progress slot stuck the
  title never closes the frame (shape 2), and an unfinished frame can leave
  the walker at a block the next list's lanes wait behind (shape 1, by
  inference: no capture of shape 1 since the fix).

**The fix:** `SPURS_LANE_MASK` (on) sends a lane only if the list's mask
allows its SPU (`=0` sends all). `[spurs-lane] wid=... allows SPUs mask
0xEF` prints once per list.

**Lane pinning is the default now.** With the freeze gone, 20 Ferrari
visits each (`perf.ps1 -Ferrari -N 20`):

| Build | Stalls | Median fps |
| --- | --- | --- |
| Fix, coherence registry at 8 | 0 of 20 | 24.2 |
| Fix, registry at 32 (default) | 0 of 20 | 24.8 |
| Fix, registry at 32, lanes pinned (`SPURS_LANE_PIN=2`) | 0 of 20 | 28.2 |

- `src/main.cpp` sets `SPURS_LANE_PIN=2` when nothing else has, and the
  settings page's "SPU lanes on own cores" defaults to Strict. A
  `gt5p_settings.toml` written before this says `"off"` (the old default)
  and keeps it.
- `spurs_lane_cpu` no longer wraps: on a CPU with fewer spare cores than
  lane numbers, the lanes past them stay free rather than share a logical
  CPU with another spinning lane.
- One run in a later check of 4 missed a scripted press at dealer select
  (the page was never entered; frames went on); not a freeze.

**Tried first, no effect:** sending back in a lane whose slot still named
a job when it left (`SPURS_LANE_INFLIGHT=1`, now off). 3 stalls in 18: the
re-entered module left again within microseconds, as it held no job.

**Other defects found on the way:**
- **The SPU coherence registry held 8 contexts**; this title has 17
  policy contexts. Those past the eighth got no lost-reservation event and
  waited for the 10 ms poll, which also misses a line changed and changed
  back between polls. It holds 32 now (`SPU_COH_CTX_MAX=8` for the old).
- **The lifter's vector stores bypass the lock-line lock** (`stvx`,
  `stvlx`, `stvrx` and `dcbz` write guest memory directly: about 14,000
  sites). Not changed: no evidence yet that one hits a line an SPU uses.

**Tools:**
- The stall dump prints each lane's ring descriptor (LS `0x1F080`: start,
  end, head, label EA) and window registers, and each workload's header from
  `+0x20` with its rows.
- `SPU_ROWLOG=<line ea>,...`: the last 64 writes to each line (PPU stores,
  `PUTLLC`s, DMA `PUT`s), printed with the stall dump, plus a 1 ms poller
  that logs writes made outside the lock (host tid 1). With it on, no run
  stalled (0 in 12).
- **GPU timestamps** (`RSX_GPU_TIME`, on): the GPU's own time per frame on
  the `[present-prof]` line (5 s average and maximum) and in F3. About 7 ms
  on the menu, 20 ms on the Ferrari page (peaks to 30), at 4x MSAA shaded
  per sample.

## Phase 63 - Lane placement, and the ring-space deadlock caught in the act (2026-10-17)

**Pinning the render lanes is 1.14 times faster, and is off by default.**
- `SPURS_LANE_PIN_AB=1` (with `SPURS_LANE_CYC=1`) puts each render lane on a
  core of its own in every other lane window, measured with
  `scratch/abcyc.py --key pin`. Within one boot the lane wall time per run
  fell 1.138x and 1.137x, and the CPU time with it: left to the scheduler,
  two lanes often shared a core.
- `spurs_lane_cpu` takes the cores from the processor topology, leaves out
  the PPU core (`ppu_sched_mask`), and gives workload 0 the first hardware
  thread and workload 1 the second. The two lists take alternate frames and
  never share a logical CPU.
- An ideal-processor hint gains nothing (`SPURS_LANE_PIN_AB=2`: 0.996x and
  0.998x).
- Pinned by default, Ferrari ran at a median 27.4 fps, against 25.1. But the
  page froze in 5 of 25 runs, against about 3 in 40 unpinned with the same
  fast paths.
- Two causes were found and fixed:
  - the core table was built lazily while all five lanes started together,
    so a lane could read it half built (now built once, under a lock);
  - pinned lanes now run above normal, like the sound chain and the replay
    thread, so those cannot starve them.
- The rate that remains is the deadlock below, which pinning makes more
  likely.
- So `SPURS_LANE_PIN` stays 0 by default. 2 (strict) is the settings page's
  "SPU lanes on own cores", now experimental again. The setting's key is now
  `lane_pinning`; the old `lane_cores` is read and ignored.

**`GT5P_STALL_DUMP` (on).** The stalls vanish under any tracing, so the
present thread waits until presents have run and then stopped for 3 s, and
prints the state once, and again at 8 s:
- every guest thread, with registers;
- every SPURS workload's group state and the guest's contention and ready
  bytes (`cellSpurs_debug_dump`);
- each lane's SPU pc, link register, events, reservation and last DMA, with
  its step count (`spurs_pm_debug_dump`);
- the FIFO walker's get, put, park address and the word there
  (`cellGcm_debug_dump`).

It costs nothing until then. A page entry whose first frame takes over 3 s
(shaders loading) also triggers it.

**What the dumps show.** Two shapes, both with the walker parked at an
unfilled block (`0xFFFFFFFF`) in an SPU command ring:

1. **Lanes spin on ring space** (Phase 54's second shape).
   - Workload 1 busy, four lanes in their runs at pc `0x4560`/`0x462C`
     (job body `b01376080`'s ring-space wait), polling labels
     `0x030004D0`-`0x03000510`, one per ring.
   - Their step counts rose from 14 to 49 million in 5 s: they are
     spinning, not blocked.
   - The labels only move as the walker passes blocks, and the block the
     walker waits for must come from a queued job that no lane is free to
     run. Each side waits for the other.
2. **Nobody is left to fill the block.**
   - Workloads 0 and 1 idle, ready 0, and `PDI:1` in `func_00BA9510`
     waiting on the list's progress row.
   - The row reads `01AA 01AA 01A6 01A8 01A5 FFFF 01A7 FFFF`: counters
     below the head, so jobs were still queued when the last lane left.
   - The lane retry (Phase 56) only re-sends a lane while another is still
     working.

**Next:** either shape needs the list's own state.
- For (2), re-dispatch a workload whose group ended with its list's
  counters short of the head.
- For (1), find which job owns the block the walker waits for, and why it
  is not running.

## Phase 62 - The SPU runtime around the job code: 1.15x on the lanes (2026-10-17)

**Result:**
- On the Ferrari page the render lanes need 1.15 to 1.16 times less CPU per
  pass, measured within one boot.
- `perf.ps1 -Ferrari -N 6`: median 25.1 fps (24.3 to 29.2), against 23.3,
  with no stalls.
- Acura: 29.67, 29.47 and 29.6 fps (cap 29.97).

**Measuring within one boot.** The car pair changes per visit, so builds
compared across boots differ by more than the changes do.
- `SPU_FAST_AB=1` with `SPURS_LANE_CYC=1` flips the new paths (`g_spu_fast`)
  at every 5 s lane window. `scratch/abcyc.py <run.err>` compares the mean
  lane CPU per run in "fast" windows against "slow" ones.
- Two boots agree within about 2%.

**Measuring where it goes.**
- `GT5P_SAMPLE_GRAIN=16` makes the sampler's buckets 16 bytes; at 256 a
  bucket was named after the function before the hot one (for example
  `spu_recent_pcs` for `spu_task_launch_check`).
- `GT5P_SAMPLE_TOP=<n>` sets how many buckets each table prints.
- `scratch/lanesum.py` sums the lane tables of several rounds.
- Before this phase, about 37% of a lane's busy samples were runtime around
  the job code.

**Changes**, all behind `g_spu_fast` (`SPU_FAST=0` restores the old paths):

| Change | Cumulative, within one boot |
| --- | --- |
| Depth guard only past depth 1,000; lockstep tick only with lockstep on; tail-return test reordered; `SPU_ARGWATCH` read once (`getenv` per lane run); stack-reset and IRQ-restore checks only when armed | 1.04 to 1.05x |
| `spu_indirect_branch` fast path: with no taskset registered, no switch set and no reserved address, resolve and tail-call before the long list of other titles' checks | 1.055 to 1.07x |
| `spu_task_launch_check`'s common case inline (`spu_tlc`) in `SPU_DRAIN` and `spu_drain_call` | 1.10 to 1.13x |
| `spu_drain_call` and `spu_img_restore` inline: after almost every call nothing is pending and the pc is the return address | 1.125x (one boot) |
| The lifter turns `ila $rN,X` + `bi $rN` into a direct transfer to `X` (82 sites, the job code's interrupt windows); `SPU_LIFT_CONST_BI=0` at lift time | 1.12 to 1.14x |
| `gcm_note_spu_put` uses the page tables instead of scanning the IO mappings on every SPU `PUT`; inline lookup memo in the fast path | 1.15 to 1.16x |

**Also:**
- `GCM_PARK_TIMEOUT_MS` (500): a kept park in an SPU ring that stays
  unpatched that long is followed to `put` after all. It has not fired in
  14 runs.
- The entry stall (about 1 in 8) did not come back in 13 runs with
  everything on. One earlier run stalled with only some of the changes in;
  the shape was the same as before.
- **Zero-size `PUT`s.** The rejected ones come from job body `0x01371A00` at
  `0x762C`, a DMA issue whose size is `r88`, computed as end minus start.
  They land on the park addresses the walker then waits at. Good runs show
  them too, so they look like empty blocks; not settled.

**Left:**
- About 25% of lane time is still runtime: `spu_drain_call_impl`'s loop, the
  fast path itself, DMA (`mfc_do_transfer` plus `memcpy`), channel reads,
  and `longjmp` for interrupt returns (about 2%).
- The rest is job code. `b01376080` `0xF8C0` alone is 15.6%.

## Phase 61 - The Ferrari page: what holds it under 30 fps (2026-10-16)

**Result so far:**
- Ferrari runs at 20 to 28 fps, depending on the car pair.
- Two stalls are fixed and one is left.
- Three more job bodies are lifted.
- The vblank runs at 59.94 Hz.
- The page is not at 30 fps yet.

**The cars change per visit, and the speed with them.** Each visit shows a
different pair, and every dealer with more than two cars does the same
(reported by the user).
- One boot is steady within ±3%. Boots differ from 20 to 30 fps, and the
  draw count varies from 2,500 to 3,700.
- `perf.ps1` now saves a window shot per run (`runN.png`), so a number can be
  matched to its pair, and `-Ferrari` drives to the page (`$FerrariHold` in
  `milestone.ps1`).
- Measured pairs:

| Pair | CPU per lane per render pass | fps |
| --- | --- | --- |
| F430 and F2007 (F1) | 30.5 ms | 27.3 |
| 599 and F40 | 41.2 ms | 20.9 |

**Where a frame goes** (`PS3_TIMELINE`, 43 ms frames):
- The title kicks one render list per frame, workloads 0 and 1 in turn.
- The pass runs on four lanes and lasts about 39 ms.
- At the end, `PDI:1` sleeps (`usleep` about 6 ms) to the next vblank, flips
  and kicks the next pass. A pass over two vblanks costs three.
- With every draw skipped the pass is about 31 ms, but the slowest boot was
  still 20 fps. The SPU work alone is over budget on the heavy pairs.
- `SPURS_LANE_CYC=1` prints, per workload, the mean lane run in wall time
  against the lane's own CPU time. They agree within 2% in every run: the
  lanes compute for the whole pass and do not wait.
- The FIFO walker keeps up. `GCM_WALK_STATS=1` counts about 9,300 parks a
  second at unfilled blocks, so it waits on the jobs and not the other way
  round.
- `PDI:1` (80%) spins in `func_00BA97B0` on the pass. Main (80%) spins in a
  polling loop of 75 code buckets. Neither is on the critical path.

**Changes:**
1. **Contention under the lock line** (`SPURS_CONT_COH=0` undoes it). This
   is the stall the sampler and the timeline provoked.
   - A thread polled workload 3 35 million times while it showed contention 3
     with no lane busy.
   - The kernel set and cleared the contention byte with plain stores. The
     byte shares a line with the ready counts, which the policy modules
     update by `GETLLAR`/`PUTLLC`. A store between a `PUTLLC`'s compare and
     its commit was written back over, as Phase 54 found for the ready count.
   - Now `spurs_cont_store` takes the lock line.
   - Provoked runs, before: 1 stall in 4 with the sampler, 2 in 2 with the
     timeline. After: 0 in 6 and 0 in 2.
2. **Texture-slot views moved out of the way.** Each slot's view was written
   at heap index `1 + slot`. That is over the render-target views (5 to 20)
   and, from slot 31 on, over the per-draw windows. With Phase 60's 512 slots
   it reached draw 30's window. Slot views now live past the per-draw
   windows (`TEXSLOT_SRV_BASE`); `RSX_TEXSLOT_SRV_LOW=1` restores the old
   place.
3. **Three more job bodies lifted.**
   - The bodies carry `0xC0DEC0DE` at +0x20. `scratch/find_bodies.py` scans
     the executable for them: seven in all, four already listed.
   - `0x0133A300` (944 bytes), `0x0133A700` (98,640) and `0x01360100`
     (57,600) are in `wws_job_bodies` now, at LS `0x4000`, sized from their
     headers: 89, 1,388 and 838 functions, no undecoded words. Each is
     referenced from a data table. They have not been seen streaming yet;
     races are the likely place.
   - All 12 SPURS job images in the executable (header `4400A850 32000080`
     at +0x10) are already captured.
   - Two SPU ELFs, `deep_spucore.elf` and `ipc_spucore.elf`, are embedded.
     No run so far creates a task or SPU thread group, so their use is
     unknown.
4. **The vblank at 59.94 Hz** (`GT5P_VBLANK_HZ`, 62.5 for the old clock).
   - The tick was a 16 ms step, 62.5 Hz, so two vblanks were 32.0 ms against
     the console's 33.4.
   - The ceiling is now 29.97 fps. Acura: 29.53, 29.47 and 29.8 fps.
5. **The walker wakes on the write it waits for** (`GCM_WALK_WAKE=0`).
   - A parked walker records the address. An SPU `PUT` that covers it sets
     the kick event, and the present loop now waits on that event
     (`cellGcm_fifo_kick_wait`) instead of sleeping.
   - 96% of parks end that way. No frame-rate change could be measured
     through the per-boot spread.
6. `spu_depth_guard`'s ring of recent drain sites is per thread. Every lane
   wrote the shared one on every drain. The lockstep tick is skipped when
   lockstep is off. No measurable change.

**Tried and dropped:**
- **`SPURS_JL_SPU3=1`** opens the render lists' SPU mask (`0F EF` at +0x2E
  of the list line fetched into LS `0x80`) to SPU 3, for a fifth lane. The
  page stalled as soon as SPU 3 took jobs. `SPURS_LLAR_LIST=1` lists the
  `GETLLAR` lines that found it.
- **`SPURS_LANE_CPUS=<list>`** gives each render lane its own core: a hint by
  default, `SPURS_LANE_CPU_HARD=1` for a hard mask, `SPURS_LANE_CPU_WIDS`
  for which workloads. One run reached 30.3 fps, but with the hard mask 1
  run in 4 stalled, and the hint gave nothing measurable.
- **`SPURS_LANE_STAGGER_US=<us>`** starts all later lanes together. At
  300 µs, 4 of 5 runs never drew the page.
- **An inline fast path for `spu_task_launch_check`** in `SPU_DRAIN`. Taken
  out after 2 of 6 runs stalled at page entry (cause not shown).

**Still open:**
- A stall at page entry, about 1 run in 8 to 10: presents stop, and only
  workload 4 is polled, idle. It looks like Phase 54's lost kick. It did not
  appear in 8 runs with `SPURS_KEVLOG=4 GT5P_THREADS=2` on.
- **SPU throughput.** The heavy pair needs about 1.35 times more for
  30 fps.
  - About 27% of a lane's busy samples are runtime bookkeeping around the
    job code: the indirect-branch resolve and its debug checks, the
    task-launch check, MFC transfers, the SPU write hook.
  - The rest is job code; `b01376080` `0xF8C0` alone is 14%.
- **Diagnostics added:** `GT5P_SAMPLE_PRESENT=1` keeps the present thread in
  the per-thread sampler.

## Phase 60 - Dealers other than Acura froze on entry (2026-10-16)

**Symptom.** Choosing any manufacturer but Acura showed its logo and then
nothing: presents stopped at `draws: 331`, about 2.4 cores busy (`PDI:1` and
Main near 90%). Aston Martin sometimes got through. Every run into Mercedes
and Ferrari froze. Three separate faults were behind it.

1. **A job body nobody had lifted.** `[spu-smc] microstep img=1 pc=0x08348
   ... handing to the interpreter`, then `[pm-end] lane 0 ... pc=0x02F30`.
   `SPU_DUMP_OVL=scratch/ovl_fer,0x4000` showed the job manager streaming in
   a fourth body: 17,936 bytes from `0x01371A00`. The dump is byte for byte
   the executable's. It is in `wws_job_bodies` now and lifted (297
   functions). Its 26 undecoded words are an ASCII message table, not code.
2. **The FIFO walker abandoned an SPU display list (the freeze).** With the
   body lifted the page still froze, now with the FIFO drained
   (`GCM_DRAINDBG`: getoff = put).
   - `PDI:1:200c3b40` sat in `func_00BA97B0`'s second loop. That loop
     polls `cellSpursGetWorkloadInfo` until a workload's contention and
     ready count are 0. `SPURS_WKLINFO_DBG=1` named the workload as 0, the
     render jobs, held at contention 5. Queue 3's row read `0001 0001`: the
     job of Phase 54 had run, so this is not that stall.
   - Each frozen run had one `FIFO resync (jump-park)` from an SPU ring
     (`0x0957...`) to the PPU's `put` (`0x00012080`). No good run had one.
   - The walker treats a self-JUMP as a park. If `put` is elsewhere, it
     assumes the title has left that segment, and jumps to `put` (a rule
     added for another title).
   - This title's SPU jobs write display lists into rings of their own,
     with a park at each one's write head, and patch it when they append.
     `put` is always in the PPU's ring, so the rule fired whenever the walker
     caught up with a job.
   - The jump dropped the rest of the list, including the label writes the
     jobs wait on for ring space, and workload 0 waited for ever.
   - A park now resyncs only when it lies in the same ring as `put`: one run
     of mapped IO pages that are contiguous in EA (`gcm_io_same_ring`).
     Otherwise it waits, and prints `park at io ... kept` the first four
     times. `GCM_PARK_RESYNC=1` restores the old rule; `=0` never resyncs
     on a park.
3. **Texture slots.** These pages bind more than 96 distinct textures a
   frame. The cache had 96 slots, and Mercedes left 486,001 binds unbound in
   a minute (`[TEX] texture slots full`). The table now has 1,024 slots;
   `RSX_TEX_SLOTS=<n>` sets how many are used (default 512). A hashed hint
   is checked before the scan, and an empty slot is taken before one that
   still holds a texture.

**Result:**
- Mercedes and Ferrari load and draw their cars, at 22 to 23 fps.
- The Acura page is unchanged: median 30.73 fps over 3 runs (30.75, 30,
  30.73), none stalled.
- The opening movie plays.
- A first entry into a new dealer still compiles 500 to 800 shaders. That
  takes 20 to 28 s with the badge up, and looks like a freeze.
- With warm shaders, Ferrari's first frame still took 7.9 s. That is the
  first-entry stall of Phase 42, not this fault.

**Measuring it:**
- `scratch\dealer.ps1 -Tag t -Moves "DOWN,RIGHT,RIGHT,RIGHT,RIGHT" -Enter`
  drives to the manufacturer list, moves, enters, and takes a window shot
  every few seconds. That sequence is Ferrari.
- A scripted direction used to push the left stick as well as the D-pad.
  The menu reads both, so each press moved the cursor twice: runs meant
  for Ferrari landed on Mercedes. Scripted presses are D-pad only now;
  `PAD_HOLD_STICK=1` restores the old behaviour.

**Open:**
- 22 to 23 fps on these pages against 30.7 on Acura: replay is 6.5 ms a
  frame against 2 ms, with about 3,000 draws.
- The cost of first entry.
- Whether the Phase 54 stalls on Acura are related. No saved Acura log has
  a jump-park resync, so probably not.

## Phase 59 - The FIFO walker, its sleep, the SPU job code and the shader caches: 25.1 to 30.6 fps (2026-10-16)

### Where the walker's time went

`GT5P_SAMPLE=6`, resolved with `scratch/maplook.py`. The walker (the
`present` host thread) was about 62% busy. Of its busy samples:

| Work | Samples |
| --- | --- |
| Index handling: `d3d12_draw_indexed`, the strip path, and `ix_vertex` (419 on its own) | about 1,000 |
| Copying the SPU ring's vertex data (`vraw_put`, `vgpu_finish`) | about 330 |
| FIFO decode | about 300 |
| `vp_record_cb`, with `rsx_fp_collect_constants` | about 290 |
| `vp_get_vs_mode` | 150 |
| `tex_snap_draw` | 125 |
| `vc_frame_end` | 50 |

`ix_vertex` only returns its argument in GPU-fetch mode, but it was an
out-of-line call made per index.

### The changes

- **Indices.** In GPU-fetch mode, triangle lists decode their guest indices
  in one tight loop. Strips store the guest indices directly, without the
  per-index `ix_vertex` call.
- **Vertex-shader lookup memo** (`RSX_VS_MEMO`, default on). The microcode
  store has a write counter (`rsx_state.vp_ucode_gen`). The lookup's last
  answer per variant (CPU or GPU fetch) is reused while the counter, the
  program start and the store size are unchanged. Before, every record
  found its program's END, hashed it and searched the cache.
- **Vertex constants** (`RSX_VCB_REUSE`, default on). Every record copied the
  whole 8 KB constant bank into its own constant-buffer slot, about 20 MB of
  upload-heap writes a frame. The records now have `vcb_slot`, the slot
  whose bank b0 binds. A record whose bank (`rsx_state.vc_gen`, advanced by
  every constant write), viewport z terms and projection-fallback class
  match the previous record of the same frame binds that record's slot.
  `DBG_ZOOM` and `VP_FIXPROJ` turn the reuse off.

### The walker's sleep, and the SPU job code: 27.4 to 29.5 fps

- **The present thread's outer sleep is now 1 ms by default (it was 4)**
  (`GT5P_PRESENT_SLEEP`). Once the walk was short, a timeline showed walks of
  2.5 to 4.4 ms with gaps of 4.2 to 4.5 ms between them: the sleep. The SPU
  render jobs waited for ring space in those gaps.
  - 1 ms gave 28.0 and 28.7 fps for the same CPU on the thread (45%).
  - 0 gave 28.2 and 28.5 fps but spins a core.
- **The lanes now bound the pass.** The walker is idle between bursts, and a
  pass still lasts about 30 ms. Each lane thread shows about 40% CPU only
  because the workload-0 and workload-1 pools alternate frames; within its
  pass a lane is about 80% busy. `GT5P_SAMPLE=all` puts 14% of lane samples
  in `b01376080` `0xF8C0`, Phase 45's culling loop.
- **Every local-store access in lifted SPU code tested debug probes.**
  - The probes are `SPU_LS_LOWREAD`, the LS watch, `SPU_SMC_WATCH` and the
    WWS policy-module probes.
  - `SPU_LS_NO_PROBES` (ps3recomp `spu_context.h`) compiles them out.
  - The GT5P CMake now defines it for the lifted SPU sources only.
    `-DGT5P_SPU_PROBES=ON` keeps them. The runtime and interpreter keep them
    either way.
  - On the hot loop, with the Phase 45 harness (`scratch/rc/bv.cmd`), the
    gain is 1.09 to 1.13x. `-mavx2` adds only 1.01 to 1.05x and is not used.
  - The harness flags 5 of 2,000 trials as differing in every variant,
    including the one that only drops probes. All 5 are `r24`, the loop's
    output pointer, fed by NaN payloads that x86 and SPU treat differently.
    That is Phase 45's NaN-payload case: the random register state produces
    NaNs, and SPU single precision has none.
- **Result:** `perf.ps1 -N 4`: 30.3, 29.5, 29.7 and 29.5 fps, median
  **29.5**, no stalls. The vblank-paced maximum is 31.25. `RSX_VTX_GPU=check`
  is clean and captures are clean.

### A run at 8 fps: the pipeline cache

A user run fell to 8.4 fps at the Car Dealer page. The F3 overlay showed
`fifo` at 109 ms a frame and the "Compiling shaders" badge on. That run had
1080p, MSAA 2 and vsync off. The `fifo` time includes the walker waiting for
the present thread at the frame handoff.

- **The pipeline cache grows for a long time on one page.** The
  `[present-thread]` line now prints the cache sizes. With those settings the
  cache reached 449 pipelines in a minute, still growing as the cars change
  colour. At 720p with MSAA 4 it reached 727. Vertex shaders stay at 56.
- **The old 1,024-entry cache misbehaved when full.**
  - It evicted its oldest entry, which could still be in use.
  - It shifted every entry after it down one.
  - It released the pipeline at once, while a frame in flight might hold it.
  - It searched linearly.

  A session over 1,024 pipelines would rebuild them in a cycle. Forcing that
  (`RSX_PSO_CACHE_MAX=100`) gives 1.5 fps with the badge on. That is the
  user's symptom; their run itself was not captured (no log when the exe is
  started directly).
- **The vertex-shader cache had the same eviction, worse.** At 256 entries it
  shifted every slot, and records, pipelines and the new lookup memo name a
  shader by slot. GPU fetch doubles the entries a program can take. This one
  was not seen filling.

**The fix.**
- The pipeline cache holds 8,192 entries behind a hash index (`s_fpi`), and
  entries never move. When full it stops caching, keeps the pipelines built
  meanwhile aside, and is emptied whole at the next frame start after the
  GPU wait.
- The vertex-shader cache holds 4,096 entries and never evicts. When full, a
  draw is dropped, with a log line.
- Switches: `RSX_PSO_LINEAR=1` uses the linear search, and
  `RSX_PSO_CACHE_MAX=<n>` tests the full path.

`perf.ps1 -N 4 -Watch 15` with this: 30.8, 30.1 and 30.6 fps, median
**30.6**. One run stalled: presents stopped with the walker idle (`fifo 0.00s`,
ticks normal), the Phase 54 stall. `RSX_VTX_GPU=check` is clean.

### Results

- `perf.ps1 -N 3`: 28.1, 27.4 and 25.6 fps, median **27.4**; no stalls.
- The walker is now 41% busy, against 62 to 66%.
- The busiest threads are now the guest main thread (87%) and `PDI:1` (76%).
- `RSX_VTX_GPU=check`: 0 of 1.7 billion fetches differ. Captures are clean.

## Phase 58 - Present: descriptor writes, then its own thread: 19.6 to 25.1 fps (2026-10-16)

### Where the present's time went

A timeline (`PS3_TIMELINE`, `scratch/tl.py --sum`) after Phase 57:
- the present thread spends 25.6 ms a frame walking the FIFO and 13.2 ms
  presenting;
- each SPU render pass (workloads 0 and 1) lasts about 39 ms (max 58).

`PERF=1` splits the present (`render_frame`, about 11.5 ms):
- **prepass, 9.5 ms:**
  - **SRV setup, 8 ms.** The prepass writes all 16 units of every draw every
    frame. That is about 33,000 `CreateShaderResourceView` calls a frame,
    nearly half of them null views, costing 6 ms. The `[PERF] record` line
    now counts them.
  - pipeline lookups, about 1 ms;
- recording, about 2 ms.

### The fix

`RSX_SRV_CACHE` (default on) keeps what each per-draw SRV slot holds and
skips a write the slot already has:
- each entry holds a reference on its resource, so a released texture's
  address cannot come back as a match for a new one;
- the three other writers that can land in those slots clear the entry
  (`srv_slot_forget`): the texture-slot view at heap slot `1 + slot` (slot
  runs to 96), the render-target views at `5 + slot`, and `rtcube_srv`.

The texture-slot views overlap the per-draw window of draws 0 to 4
(`DRAW_SRV_BASE` is 32). That is an existing overlap, not investigated
further.

### The present thread (`RSX_PRESENT_THREAD`, default on)

The timeline also showed the present running inside the SPU render pass. In
one frame the pass ran 11.4 to 43.5 ms and the present 13.3 to 19.6 ms.
While the walker presented, it did not consume the FIFO, and the jobs
stalled for ring space. Each pass lasted about walk plus present (33.5 ms).

**The handoff.** The walker records into one `FrameSet` while a
`present-replay` thread replays the other. A `FrameSet` holds a frame's
records, its count, its upload-buffer parity, its per-slot flags, its clear
colour, its present flag and its volatile-texture snapshots. Code reaches
the set through `FR`, a thread-local override on the present thread and the
recording set everywhere else. At a frame boundary the walker:
1. waits for the present thread to finish the frame before, handling its
   window messages after 20 ms;
2. waits for the GPU to finish that frame (its own fence), since that
   frame's upload half is the walker's next;
3. swaps the sets and does the recording resets that used to sit at the end
   of `render_frame_body`;
4. hands the frame over.

**Two things changed with the move.**
- The title-bar text is set from the walker: `SetWindowText` from the
  present thread would wait for the window's thread, which may be waiting
  for it.
- The volatile-texture table now has a lock, because the replay marks it and
  the recorder reads it.

**A known gap.** Texture bytes and fragment-program code are still read from
guest memory at replay, now up to a frame later than before. A title that
reuses an address within that window would show it. The movie
(volatile textures) plays without tearing (`scratch\movshot.ps1`).

`[present-thread]` prints every 5 s: replay time per frame, and how long the
walker waited for the thread and for the GPU. At the Car Dealer page the
replay takes 6.7 to 7.3 ms a frame and the walker waits 0.

`RSX_PRESENT_THREAD=0` replays on the walker as before (22.4 fps).

### Results

- **Present thread**, `perf.ps1 -N 6 -Watch 20`:
  - 24.2, 25.3, 25.7, 26.0, 23.3 and 25.1 fps, median **25.1**;
  - 0 of 6 stalled;
  - `RSX_VTX_GPU=check`: 0 of 1.6 billion fetches differ;
  - captures of the page and of the movie are clean.
- **Descriptor writes skipped:** 98% (652,891 of 663,720 per 20 frames).
- `render_frame` is about 6.5 ms a frame, from about 12.
- `perf.ps1 -N 3`: 23.4, 21.9 and 21.9 fps, no stalls. Captures are clean.

## Phase 57 - Cross-frame vertex cache: 17.4 to about 19.6 fps (2026-10-16)

Plan step 4a. All of it is in `libs/video/rsx_d3d12_backend.c` (ps3recomp).

### What repeats from frame to frame

`RSX_XFSTAT=1` keys every indexed upload by where it reads from: the index
array, its range, and the vertex layout and offsets. It hashes the index
bytes and the bytes of each referenced vertex. Every 5 s it prints how many
uploads match the frame before, or two frames before. It also splits upload
time by repeated against new and by GPU fetch against CPU. (It slows the
frame; use it only to measure.) `RSX_XFSTAT_DUMP=<s>` writes every call of
three frames, starting `<s>` seconds after the first indexed call, to
`xfdump.txt`.

A Car Dealer frame has about 7,100 indexed uploads, 3.4 MB of index bytes,
and 38 MB of referenced vertex bytes.

- **About 50% repeat the frame before exactly:** same addresses, same
  indices, same vertices. These are the static meshes in main memory.
- **The other 50% never repeat**, against either of the two frames before.
  These are the SPU's output. Each draw's index array and its vertices sit
  side by side in a ring in main memory (about `0x0A5xxxxx` to
  `0x0A8xxxxx`), at a new address every frame, with counts that change (141,
  159, 162 for one mesh). No cache can serve them.
- **Time per frame**, with the frame rate measured at that point:

  | | GPU fetch | CPU |
  | --- | --- | --- |
  | Repeated | 3,381 calls, 8.0 ms | 448 calls, 5.9 ms (13 us each) |
  | New | 3,748 calls, 5.6 ms | none |

- **The CPU calls were two-stream layouts.** They are mostly the car program
  `fp 05D21BC1`: indexed strips with restart, reading two interleaved
  arrays, both stride 24. The GPU path counted them as six separate arrays
  and copied each stream three times. That put them over the sparse limit.
  Each 256-index batch spans about 750 vertices.
- **Index 0xFFFF is the restart marker of those strips.** Restart is enabled
  with value 0xFFFF. The strip path already skips it.

### The cache

- **Attributes are grouped into streams**: same stride and memory, all
  within one vertex record. Each stream is placed on its own, so the
  two-stream layouts copy each array once, and none are left to the CPU.
- **Each stream is keyed by memory, stride and first attribute byte, and
  learns the vertex range its draws use.** From the second frame running in
  which it is seen, that whole range is copied once into a persistent area.
  The area lies past the two per-frame halves of `s_vraw`, in the same
  resource, so a draw still has one shader resource view. A descriptor
  reaches the area as `(2 - parity) * VRAW_BYTES + offset`. The host mirror
  of the area is `s_vper_mirror`.
- **Draws of a stream that has not been stable for long compare their own
  bytes with the mirror,** exactly as the per-frame reuse does.
- **Comparing every draw cost about 130 MB of reads a frame.** So a stream
  whose draws have all matched for 8 frames running is compared whole, once,
  at its first draw of a frame, and its other draws that frame are not. Any
  mismatch or new copy puts it back to a compare per draw. A stream that
  mismatches 4 times is left to the ring for good.
- **What that rule cannot see:** a stream that matches the frame before at
  its first draw, after 8 clean frames, and is then rewritten later in the
  same frame. `RSX_VTXCACHE_VERIFY=draw` compares every draw, always.
- **When the area is full it starts again empty,** after 3 frames, so that no
  frame in flight is still reading it.
- **Merging is kept:** consecutive batches of a mesh read the same cached copy
  and merge into one record, as before.
- **Switches:**
  - `RSX_VTXCACHE=0`: off;
  - `RSX_VTXCACHE_MB=<n>`: the area (default 64);
  - `RSX_VTXCACHE_MAX=<KB>`: the largest copy of one stream (default 8192).
  The vtxstat block now has a `vertex cache:` line.

### Results

- **Steady state, per 5 s:**
  - 456,457 stream hits, 454,953 of them not compared;
  - 179 MB compared;
  - 533 copies (6.5 MB);
  - 3 changed;
  - 25.7 of 64 MB used.
- **Uploads fell from about 21 to 12.5 ms a frame,** and `vgpu_finish` from
  7.6 to 3.8 ms.
- **Frame rate:**
  - `perf.ps1 -N 3`: 19.8 and 19.5 fps (the third run stalled);
  - `RSX_VTXCACHE=0`, same build: 16.8 fps;
  - Phase 56: 17.4 fps.
- **Correctness:**
  - `RSX_VTX_GPU=check` gives 0 of 1.22 billion attribute fetches different,
    with the per-draw compares and with the stable rule;
  - captures of the page (`winshot.ps1`) are clean.
- **The present thread is now 74 to 76% busy,** against 85 to 98% before:
  - FIFO walk about 24 ms a frame;
  - present about 12 ms.

  It is no longer the only limit. The guest main thread is at 83 to 88%,
  and `PDI:1` at about 72%.

## Phase 56 - SPU lanes rebuilt (title-only 23 to 29 fps); GPU vertex fetch (2026-10-16)

### A timeline of the frame

`PS3_TIMELINE=<start_s>,<length_s>` records, into memory and then
`PS3_TIMELINE_OUT` (CSV), the events that pace a frame:
- syscalls and HLE calls that blocked over 100 us;
- SPURS kicks, dispatches and group ends, and each lane run;
- workload-info changes, `usleep` asked against slept;
- flips, FIFO walks and presents.

`python scratch/tl.py <csv> <run.err> [frame] [--sum]` prints one frame in
order, or per-frame totals. (Quote the value in PowerShell:
`'PS3_TIMELINE=42,3'`, or the comma makes it an array.)

**Title-only (`RSX_VTX_SKIP=1`), 43.6 ms frames before this phase:**

| Part of the frame | Time |
| --- | --- |
| Flip to kick | 0-3 ms |
| Kick to dispatch | 1.5-2 ms (the kernel's `Sleep(1)` poll) |
| The render-job pass | about 31 ms, on four lanes started 3, 6 and 12 ms apart |
| Tail | 4.5 ms of lanes cycling in 1 ms retries before the group ended |

Workloads 0 and 1 alternate frames, one pass each, so the pass is the
critical path.

### 5b: the lanes

| Change | Undo with |
| --- | --- |
| The kernel thread also wakes on a ready-count store or a group's end | `SPURS_KERN_WAKE=0` |
| A pool of lane threads per workload, woken by an event, instead of threads made per dispatch | `SPURS_LANE_POOL=0` |
| A lane that finds nothing in 8 dispatches in a row is left out (retried every 64th) | `SPURS_LANE_PRUNE=0` |
| `SPURS_LANE_STAY` back to off: it made finished lanes cycle until the others were done | `SPURS_LANE_STAY=1` |
| Lane runs timed with the performance counter (`GetTickCount64` moves in 15.6 ms steps, so "did work" was misjudged) | — |
| Lane stagger 3 ms to 1 ms (0 still deadlocks the list set-up, Phase 41) | `SPURS_LANE_STAGGER_MS=3` |
| `sys_timer_usleep` uses a high-resolution waitable timer | `PS3_USLEEP_HIRES=0` |

- **Why lane 3 is left out.** It never got a job: the render lists' SPU mask
  (`0xEF` at job list +0x2F) excludes SPU 3, so the lists run on four lanes,
  probably as on the console.
- **Result:** title-only **23.4 to 29.3 fps** (34.8 ms frames, pass about
  26 ms, kick to dispatch 0.01 ms). The page draws on vblanks (62.5 Hz here),
  so 30 fps means pass plus overhead within two vblanks every frame; the
  slowest passes (up to 43 ms) still miss.
- **Stagger 1 ms:** 0 stalls in 10 runs, each watched for a minute.

### With drawing on

- **No GPU wait.** `PERF=1` now reports the wait at frame start: 0. Plan
  step 3 (CPU/GPU overlap) would gain nothing.
- **The coupling.** The frame is the render pass in lockstep with the FIFO
  walk: lanes wait for ring space (a quarter of lane time in the label poll),
  and the walk spends about 26 ms a frame in indexed vertex uploads.
- **Not the cadence.** `GT5P_PRESENT_SLEEP=1` or `0` changed nothing.

### GPU vertex fetch (`RSX_VTX_GPU`, on)

- **How it works.** Indexed triangle and strip uploads copy the guest's raw
  vertex bytes for their index range into a 96 MB ring (`RSX_VTXGPU_MB`) and
  write their indices rebased to that range. A shader variant
  (`rsx_vp_decompile_gpufetch`) takes only `SV_VertexID` and decodes each
  attribute from the ring (t20), with per-record descriptors in b2.
- **Reuse.** Batches of one interleaved stream reuse or extend a recent
  region, only when every byte of their range still matches the copy
  (`RSX_VTXGPU_REUSE=0` to never reuse). Records merge as before when they
  read the same region.
- **Sparse calls go to the CPU.** Separate-array calls whose index range is
  sparse (over 64 bytes per index, `RSX_VTXGPU_SPARSE`) are converted on the
  CPU, which converts only the vertices used.
- **Result:** 17.2 fps against 15.7 for the CPU path in the same session
  (3 runs each). Copies are about 17 MB a frame; uploads still take about
  21 ms of the walk, now mostly index handling and the sparse calls.

**Two faults found on the way:**

1. **A triangle list split across records.** The title sends lists as
   batches of 256 indices, and 256 is not a multiple of 3. The CPU path only
   ever drew them merged; any batch that becomes its own record starts
   mid-triangle and joins the wrong vertices: sawtooth patches over the car
   paint.
   - The GPU path now carries the leftover indices into the next record
     (`RSX_VTXGPU_NOCARRY=1` to see the fault).
   - Merging off on the old CPU path (`RSX_MERGE=0`) shows the same patches.
   - Most of the hypotheses tested before finding this (stale ring data,
     decode, input masks, self-copies, cube targets) were masked by it.
2. **Stale record flags.** Records are refilled field by field each frame,
   and only the indexed path set the GPU-fetch flag. A quad or glyph draw
   reusing a slot was replayed as GPU fetch: the scene vanished after a few
   seconds and text broke.
   - The flag is now stamped with the frame generation, like `ix_slot`
     (`gf_slot`).

**Also:**
- `MAX_DRAWS` is 6144 to 12288.
- Test switches:
  - `RSX_VTX_GPU=check`: every GPU-fetch vertex decoded on the CPU from the
    copy and compared with the converter.
  - `RSX_VTXGPU_FLOATIN=1|2`: CPU floats through the GPU path, or through
    the input assembler.
  - `RSX_VTXGPU_TYPES`, `RSX_VTXGPU_ALLIN`, `RSX_VTXGPU_MERGE`,
    `RSX_VTXGPU_MASKDUP`, `RSX_VTXGPU_PROBE`, `RSX_VTXGPU_DBG`.
  - `RSX_MERGEDBG=1`: state compared across merged batches; all identical.
- Diagnostics added: `[TEX] texture slots full`, `[FP] pipeline cache full`.

### Test scripts

- **Two game windows at once.** Piping a script into `Select-Object -First`
  stops it before it closes the game, so runs overlapped (two games on one
  CPU, every number wrong).
  - The scripts now stop leftovers before launching (`Stop-Stragglers`) and
    close the game in a `finally`.
  - `scratch\winshot.ps1` captures the game window itself (`PrintWindow`) at
    the page.
  - `perf.ps1` and `cpu3.ps1` take `-MinDraws`.

## Phase 55 - PPU-side speed-ups measured: none moves the dealership (2026-10-16)

Plan steps 5a and part of 5c, measured with `scratch\perf.ps1` against the
Phase 54 exe (normal: 5 runs; title-only, `RSX_VTX_SKIP=1 -MinDraws 0`: 3):

| Build | Car Dealer page | Title-only ceiling | Main menu |
| --- | --- | --- | --- |
| Phase 54 (baseline) | 16.47 fps (15.07-17.13) | 23.4 | 31.27 |
| 5a: guest memory access inline | 16.93 (16.8-17.53) | 23.07 | 31.27 |
| 5c: pause in the workload-info spin | 15.93 (15-17.33) | 22.73 | - |

All within run-to-run noise. `soak.py`: 152 `GT.VOL` opens on every boot
(more than the 129 above, because the save now boots to the main menu), no
bad boots.

- **5a** (`ppu_vm_inline.h`, force-included into the lifted chunks by the
  CMake option `GT5P_VM_INLINE`; `VM_INLINE=0` at run time sends every
  access out of line again).
  - It compiled first time, and `vm_write64` and `vm_read32` left the main
    thread's samples.
  - The exe grows from 97 MB to 176 MB, and the option needs a full rebuild.
    Left off by default.
  - The 8% `spu_coh_notify_write_except` in Phase 53's profile comes from
    SPU DMA PUTs, not PPU stores, so 5a could not move it.
- **What sets the title's pace.** Sampled title-only (`GT5P_SAMPLE=4`):
  - The main thread is at 77% and not saturated: `lv2_syscall` 24%,
    mutexes 11%.
  - `PDI:1` (85%) waits in `func_00BA97B0` for the SPU workloads to finish.
  - The lanes use about 2.5 cores in threads made per dispatch.
  - So the ~23 fps ceiling is the SPU job pipeline's latency (dispatch, job
    run, the hand-offs between them), not PPU work. Step 5b and the
    critical path through the job lists are next.
- **5c, the pause.** `cellSpursGetWorkloadInfo` can pause before answering
  "busy" (`SPURS_WKLINFO_PAUSE=<n>`). The idea: guest PPU threads share one
  physical core (mask 3), so `PDI:1`'s spin competes with the main thread.
  It measured no better, so it is off by default. Much of the wait is
  `func_00BA97B0`'s first loop, a guest spin on memory with no call in it.
- **Kept, cheaper on every syscall and HLE call** (a few % of the busy guest
  threads; too small to show in fps):
  - The profiler breadcrumb is stored as the host return address and
    resolved only when a diagnostic reads it. It was a binary search over
    every lifted function on each call. `PPU_PROF_EAGER=1` restores it.
  - `sc_trace`'s "is tracing on" test runs before the call, so its stack
    probe is no longer paid every syscall.
- `perf.ps1 -MinDraws <n>`: with every draw dropped, the title bar never
  shows 1,000 draws.

## Phase 54 - The dealership stall: a lost ready-count kick (2026-10-16)

**Result.** The stall rate about halves; it is not gone. On builds with the
fix below: 3 stalls in 37 runs on the Car Dealer page (8%; 0 in one batch
of 10), against 7 in 38 before it (18%), each run watched for about a
minute. The lane and contention changes listed under "Ruled out" were also on
in a batch before the fix, which still stalled once in 6; the store fix is
what moved it. The stalls that remain had no diagnostics on and are not
explained.

**What a stall is.** Two shapes, as in 46.3:

- **Presents stop (about 2.4 cores busy).** The FIFO is fully drained
  (`GCM_DRAINDBG`: getoff = put), so the title has stopped issuing commands,
  and no workload is ready or running. With `GT5P_THREADS=2` and `GT5P_PEEK`,
  the thread `PDI:1:200c3b40` sits in `func_00BA97B0` waiting on workload 4,
  the one-SPU job manager (`maxContention 1`, data `0x0139C900`). The guest
  object is at `0x0139A880`; queue 3's row is at `+0x70`.
  - `func_00BA97B0` first waits until the smallest of seven per-SPU u16
    progress counters (row `+2..+0xE`) reaches the queue's head plus its
    non-empty entries. It then calls `cellSpursGetWorkloadInfo` until
    `readyCount` (+0x23) and `contention` (+0x20) are both 0.
  - Here the row read `0001 0000 FFFF ...`: one entry queued, SPU 0's
    counter at 0, unused SPUs at FFFF. So the entry was queued, but workload
    4 was never made ready to run it.
- **Lanes spin (6.5 cores).** Four lanes of workload 0 wait for ring space
  in job body `b01376080`; the walker is parked at an unfilled `0xFFFFFFFF`
  block.
  - The wait at `0x4598`: when a job's write window `[r12, r5]` would pass
    the end of its lane's 1 MB ring (lane k's ring starts at
    `0x2A2BDF80 + k MB`), it wraps and waits until the label passes
    base + size.
  - Every spinning lane saw its label at exactly the ring base. The display
    lists set all five labels to the bases (`RSX_LABELWATCH=1` prints where:
    `0x09A6...` for workload 0, `0x0959...` for workload 1), about 290 times
    a lane in a run.
  - Workload 0 then waits for a block nothing fills. The likely filler is
    workload 4's job. That is a hypothesis: no captured run tied the
    unfilled block to it.

**The cause.**
- Workload 4 is kicked with `cellSpursReadyCountStore(4, 1)`, about 150
  times a second.
- The HLE wrote the ready byte with a plain host store. Policy modules
  update the same 128-byte line with `GETLLAR`/`PUTLLC`, and our `PUTLLC`
  compares and commits under the lock-line lock.
- A store landing between that compare and the commit was written back
  over, and the kick was lost.
- Now the store, and the lane-retry increment of Phase 41, take the lock
  line and notify reserving SPUs (`spurs_ready_store`, `spurs_ready_inc`),
  as a PPU store does on the console. `SPURS_READY_COH=0` restores the plain
  writes.

**Ruled out along the way:**
- **Contention reported as 0 while lanes still run.** It happens 1 to 4
  times a run, in the instant between a group clearing contention and
  clearing busy; stall-free runs have it too. Reporting at least 1 while the
  group is busy is kept (`SPURS_CONT_BUSY=0` to undo); it costs nothing.
- **Lanes leaving after doing work.** About 3,000 times a run, in good runs
  as well. `SPURS_LANE_STAY=0` keeps the old exit; the default now sends
  such a lane back in while others still work.
- **Workload priorities.** SPUs 0-4 are all allowed (priority bytes
  `04 04 04 04 04 00 00 00`).

**Open:** lane 3 of workloads 0 and 1 never gets a job: 512 of 512
dispatches end with "ran 0 ms". Without the 3 ms lane stagger, the page
never draws and lane 3 is the lane that leaves. The lists run on four lanes.

**Diagnostics added:**
- `SPURS_KEVLOG=<wid>`: one workload's last 48 ready stores, dispatches
  and exits, printed after 3 s with no dispatch.
- `SPURS_WKLINFO_DBG=1`: `cellSpursGetWorkloadInfo` calls per workload,
  with the values returned.
- `SPURS_LANE_DBG=1`: each lane leaving, with why.
- `RSX_LABELWATCH=1`: labels `0x400-0x5F0` moving backwards, and the FIFO
  position of each ring-base write.
- `SPU_SPINDBG=1`: an SPU repeating one GET, with its thresholds.
- `GCM_SEMALOG=1`: NV406E semaphore releases per label.
- `GCM_DRAINDBG` now prints the word at getoff.
- `GT5P_THREADS=2`: registers and `[r9]` per guest thread.
- `GT5P_PEEK=<ea>,...`: the 0xC0 bytes behind a guest pointer, with each
  thread dump.

**Faster test runs.** The exe prints `[milestone] <name> at <ms> ms` the
first time the title reads each screen's `.gpb` (`cellFs` stat/open;
`PAD_MILESTONES=0` for none).
- `PAD_HOLD` presses can count from a milestone
  (`@TopMenuTemplate+8000-8300:CROSS`). `!<other>` skips a retry once that
  milestone has appeared.
- `scratch\perf.ps1`, `cpu3.ps1`, `pvshot.ps1` and `capshot.ps1` now wait
  for `DealerTopRoot` and over 1,000 draws instead of fixed sleeps. The
  page comes up about 29 s after launch, against 47 s.
- `perf.ps1` ends a run at the first 5 s block with no presents, and counts
  stalls; `-Watch <s>` keeps watching after the measurement.

## Phase 53 - Dealership frame rate: the baseline for a 30 fps plan (2026-10-15)

Measured with `scratch\perf.ps1` (`FS_HIDE`, no settings file), current
build (shadow pass, rims, glass all drawn):

- **17.6 and 18.1 fps** in the clean runs; one run of three stalled.
- **Present thread: about 44.5 ms a frame** (FIFO walk 34.5, present 10;
  `GT5P_PRESENT_PROF`), as in Phase 45. Sampled (`GT5P_SAMPLE=6`): 23% in
  D3D12/driver calls made from the frame loop, about 34% CPU vertex
  conversion (`ix_vertex` 21%, `vplan_fetch` 9%, `vplan_build` 3%),
  `rsx_fp_code_hash` 3% (the fragment ucode hashed every draw),
  `rsx_vtx_pos_dbg` 1.4% (a debug helper on the hot path), `tex_snap_draw`
  1.3%. `render_frame_body` begins with `wait_for_gpu()`: the CPU never
  builds a frame while the GPU draws the last.
- **Guest-side ceiling: 24.5 fps** with every draw dropped
  (`RSX_VTX_SKIP=1`; the present thread then needs 5 ms a frame). Up from
  Phase 45's 20. Main thread 76%: `lv2_syscall` itself 22%, `vm_write64`
  14%, `spu_coh_notify_write_except` 8%, `sys_mutex` lock/unlock 8%.
  `PDI:1` 72%, mostly the queue-3 wait (`func_00BA97B0`) polling
  `cellSpursGetWorkloadInfo`, with `ppu_prof_resolve_host` and `hle_route`
  on every call. SPU job lanes about 2.6 cores, in threads created per
  dispatch (`CreateThread`, 1 MB stacks).
- **The stall, sampled** (a run at 6.6 fps): four `spurs-pm-worker` lanes at
  100%, each in `spu_rdch` (about 60% of samples) inside job body
  `b01376080` at `0x462C`/`0x4598`, and `PDI:1` in the queue-3 wait. The
  lanes wait on an SPU channel nothing writes; which channel is the next
  question (Phase 46.3).

30 fps needs both ceilings below 33 ms a frame (frames land on 16.7 ms
vblanks): the present thread from 44.5 ms, and the title's own threads from
about 41 ms.

## Phase 52 - An in-game settings page (F1) (2026-10-15)

`src/gt5p_settings_ui.cpp`: F1 over the game window, or the PS button on an
SDL controller, opens a page listing every setting of `gt5p_settings.toml`
by section (Video, Input, Debug). Keyboard, d-pad and mouse drive it. A
change is written to the file at once (`gt5p_settings_store`). Vsync and the
keyboard-as-controller switch apply live, through new setters
(`rsx_d3d12_set_present_sync`, `pad_set_keyboard_enabled`); the rest are
marked "after restart", and a "Restart now" row relaunches the exe with the
same command line, first clearing the variables loading the old file had
set, so the new process reads the new file. A setting an environment
variable overrides is shown greyed, `set by <VAR>` (the settings code now
records which were set before it applied the file, and keeps the file's own
values apart from the effective ones).

Like the F3 profiler it is a GDI window owned by the game window, so the
D3D12 backend is untouched. While it is open, `cellPad` hands the title every
pad at rest (`g_pad_input_blocked`) and publishes the buttons, all ports
ORed with the PS button as bit 16 (`g_pad_menu_buttons`), for the page to
read.

Two faults found by driving it with posted keys and `PAD_HOLD`
(`scratch\settings_test.ps1`, `scratch\settings_restart_test.ps1`):

- The page repositioned itself every 16 ms with a synchronous
  `SetWindowPos(HWND_TOP)`. That waits on the owner window's thread, the
  present thread, and froze the page for 1.7 s during a shader compile,
  losing a press. It now moves only when the game window moved,
  asynchronously, without touching z-order.
- It polled the pads itself as well, which would run SDL's controller update
  on two threads at once; it now reads what the game's own polls publish.

After both: three of three scripted runs of Down, Down, Cross turned vsync
off in the file; "Restart now" ended the old process and started a new one
on the new file.

Switches: `GT5P_SETTINGS_UI=0` (no page), `=1` (open at start, for tests),
`GT5P_SETTINGS_UI_DBG=1` (the buttons the page sees). Graphics options will
need the page to scroll: eight settings fill it.

### 52.1 A "Compiling shaders" badge

The backend builds shaders and pipelines on the thread that replays frames,
so the picture stops while it does. `src/gt5p_shaderbusy.cpp` shows a badge
in the bottom-right corner of the game window meanwhile ("Compiling shaders
(n)", a spinner), from its own thread and window so it animates while the
frame is frozen. The backend now counts the work: `g_rsx_shader_busy` is
raised around an HLSL compile that missed the shader cache and around a guest
pipeline build, with totals of each. The badge appears after 0.2 s of work,
so one quick pipeline does not flash it, and stays until 0.7 s after the
last, so a burst reads as one. It moves only asynchronously (52's lesson:
the game window's thread is the busy one).

On an empty shader cache a boot showed it four times (3, 13, 18 and 107
shaders and pipelines; 0.6-1.9 s each) and hid it after each. New setting
`[video] shader_indicator` (default on), on the F1 page and live;
`GT5P_SHADER_INDICATOR=0` overrides. `scratch\badge_test.ps1` repeats the
test.

## Phase 51 - Car paint, floor reflection and glass against RPCS3 (2026-10-15)

The task from the user's screenshots (Acura NSX, Car Dealer page): hard-edged
black areas on the cars, a faint floor reflection, and (added during the
work) glass that is not transparent enough. The page alternates car colours
per visit, so captures were compared by colour name, not by position.

### 51.1 Black panels: `log2` of a negative number

Pixel history without RenderDoc: `FP_IDCOLOR=3` showed the black roof, door
and deck and the correctly painted rear panel come from one program
(`0x05D3E001`, the body paint of 46.4), the same constants and the same ramp
texture (`TEXRACE_FP=<fp>`, new: unit checksums at each draw, 85 draws one
checksum). So the difference was per pixel. The paint takes `log2` of a dot
product with the reflection vector (a `pow` spelled out); our decompiler
emitted `log2(x)`, which is NaN for x < 0, and the output guard
(`_o == _o ? _o : 0`) turns NaN into black: every panel facing the "wrong"
way. `LG2` now takes `|x|`, as `RSQ` already did (`RSX_LG2_ABS=0` for the
old form). Red, silver and black cars now read as on RPCS3; the rims show
their spokes too. Ruled out on the way: the shadow term (`RSX_SHADOW=0`),
the RT write-back (`RSX_RT_WB=0`), one-pixel viewports (`RSX_VP_MIN2=1`), and
a mid-frame rewrite of the ramp texture.

### 51.2 Floor reflection

Not a separate fault. The title draws the cars mirrored at 640x360 into the
scene target (ops 631-1088), copies that corner into `0x2880000` with a mip
chain (op 1089), and the floor (`0x05D21181`, unit 3) samples it with the
right scale (`FP_SHOW=r[2]` shows the mirrored cars in place). The mirrored
cars had the same black panels as 51.1. After it, with the same colours as
RPCS3's capture (red behind, black in front) the red car's reflection and its
wheel show on the floor as in RPCS3, at a similar level. RPCS3's own copy of
that texture is as dim as ours (brightest 35/255 in both).

### 51.3 Glass: the blend constant was never set

The glass (`0x05EFBEC1`) outputs a reflection with constant alpha and blends
`src + dst * (1 - CONSTANT_COLOR)`. `NV4097_SET_BLEND_COLOR` (`0x031C`) was
never decoded and the D3D12 backend never called `OMSetBlendFactor`, so the
constant was D3D12's default and the windows hid what is behind them. It is
decoded now, kept per draw and set at replay (`RSX_BLEND_COLOR=0` to leave it
unset; `RSX_BLENDCOLDBG=1` lists the values: `0xFFB0B0B0`, `0xFF555555`
...). The seats and the backdrop now show through the windows as on RPCS3.

### 51.4 Checks

The main menu scene is identical with both fixes off and on; the agreement
screen draws; `soak.py 6 40`: 0 of 6 bad, 152 asset opens each, as before;
a 300 s dealership session logged no `PSO FAIL` or device removal and ran at
16.7 fps, but its window stopped updating at about 255 s (the 46.3 stall;
the log was overwritten before it was read).

Open: the user sees the front car's reflection flash in the live window.
Eight consecutive `RSX_CAP` frames show no change beyond normal motion
(0.25% of the car's pixels), so it does not show under capture.

## Phase 50 - The opening movie plays (2026-10-15)

### 50.1 Where the movie is, and why it never played

On boots after the agreement has been accepted, RPCS3 plays
`grim/file/contents/tv_50_519336755.pam` (a PAMF file: 1920x1088 H.264 at
59.94 fps, six-channel ATRAC3plus, 141 s) from the game's hard-disk install.
The disc's `USRDIR/MOVIE/34.pam` and `52.pam` are not opened. The title copies
that folder from `TV.DAT` itself on its first boot, before the agreement; this
port's first boot goes to the agreement without installing (not investigated:
RPCS3 waits about 20 s after `BootRoot.gpb` and then installs, ours loads the
save). The copy of RPCS3's install that Phase 41 put aside under
`gamedata/contents_aside` is now back in
`gamedata/dev_hdd0/game/BCUS98158/USRDIR/grim/file/contents` (gitignored game
data). The files are encrypted on disk; the title decrypts them and hands
plain PAMF to the libraries.

ps3recomp's movie libraries were stubs: `cellPamf` parsed an invented header
layout (hence Phase 41's "0 streams"), `cellDmux` handed the whole input over
as one AU, `cellVdec`/`cellAdec` produced nothing, and 15 of the title's
imports from them were unregistered (`cellDmuxOpenEx`, `cellVdecOpenEx`,
`cellAdecOpenEx`, `cellPamfGetHeaderSize` and others).

### 50.2 What is in ps3recomp now (`libs/codec/`)

- `cellPamf`: reads the real header (stream table at `0x88`, 0x30 per
  stream, entry-point tables) and implements every function the title imports.
  `PAMF_DUMP=<dir>` writes the decrypted headers; `PAMF_OFF=1` refuses them.
- `cellDmux`: a program-stream demultiplexer on its own thread. AVC is cut at
  access-unit delimiters, ATRAC3plus at ATS headers (`0F D0`, frame size in
  the low 10 bits of bytes 2-3); AUs are copied into the title's ES buffer and
  announced with AU_FOUND; DEMUX_DONE when a chunk is used up.
  `DMUX_TRACE=1`, `DMUX_DUMP=<dir>`.
- `cellVdec`, `cellAdec` (ATRAC3plus): decoder threads with command queues;
  pictures and PCM wait in queues until GetPicture/GetPcm. Decoding is FFmpeg
  7.1 (libavcodec), loaded at run time from DLLs beside the exe
  (`scripts/get_ffmpeg.ps1` fetches a pinned LGPL build into
  `third_party/ffmpeg`, gitignored; the build passes its headers to
  `codec_ffmpeg.c` only). Without the DLLs: black pictures and silence.
  `CODEC_FFMPEG=0`, `VDEC_TRACE=1`, `ADEC_TRACE=1`. The old silent `cellAdec`
  path is kept for every other codec type.
- Library threads call the title's callbacks on guest stacks of their own
  (`ppu_guest_call_set_stack`, new in `ppu_loader.cpp`): every host thread
  used to start on the same scratch stack at `0xCFFE0000`.

### 50.3 Four things between "it opens" and "it plays"

1. **An SPU job nobody had lifted.** After the first picture the player waited
   for ever in `func_00BA97B0` on job-manager queue 3 -- the same wait Phase 31
   found for the dealership. The movie's job body (`0x011A4E80`, 9,968 bytes,
   DMA'd to LS `0x4000`; `SPU_DUMP_OVL` found it) ran on the SPU interpreter
   (`[spu-smc] ... handing to the interpreter`) and never finished. It is in
   `wws_job_bodies` now and lifted. That job turns each YUV picture into a
   1920x1080 DXT1 texture, alternating between two at `0x1C3D00` and
   `0x3BE500`.
2. **Missing timestamps.** Only the first AU of each group of pictures carries
   a PTS. With the rest invalid the player displayed pictures the moment they
   arrived and discarded most (`GetPicture` with no buffer 3,565 of 3,704
   times): about six times real speed. `cellVdec` now gives such a picture the
   previous one's PTS plus a frame, as RPCS3 does (`VDEC_PTS_FILL=0` to stop);
   2,000 pictures then took 33.9 s of wall time for 34.4 s of movie. Audio had
   the same gap: an audio PES packet holds about 1.2 frames, so one AU in five
   had no PTS, and the movie's sound sped up and slowed down; measured, the
   title drew audio 15% faster than real time. `cellDmux` now fills those in
   (+3840 ticks, `DMUX_PTS_FILL=0`): 922 of 922 AUs carry one and the title
   draws exactly 100 frames per 4.27 s.
3. **Video ES buffer too small.** At 6 MB the demuxer filled it about 17 s in
   and waited, the audio starved, and the player's clock stopped. The title
   keeps 1.6 s or more of audio ahead; the buffer is 16 MB now.
4. **Tearing.** The D3D12 backend reads textures when it replays a frame,
   after the FIFO walk; the RSX reads them when it executes the draw. The
   SPU job had already started rewriting the movie texture by replay time on
   2,455 of 2,700 uploads (`RSX_TEX_SNAPDBG=1`). A texture seen changing
   between uploads is now copied at each draw that binds it, and the replay
   uploads that copy (`RSX_TEX_SNAP=0` to stop). Static textures are untouched.

### 50.4 Measurement runs

With the TV content installed the title plays the movie at boot, and the main
menu then ignores the scripted presses at their old times. `FS_HIDE=<text>`
(new, `cellFs`) looks a path up with `_hidden` after `<text>`, so
`FS_HIDE=grim/file/contents` makes the folder look empty without moving it.
`scripts/boot.py`, `scripts/soak.py` and the drive scripts in `scratch/` set
it; with it the Phase 43 presses reach the dealership again.

Not yet heard by a person after the timestamp fix; the tearing fix is
measured, not yet seen. Two dealership runs on the way stalled (2.6 and 6.8
fps): Phase 46.3's stall, next.

## Phase 49 - The shadow map is drawn and sampled (2026-10-15)

### 49.1 Where the shadow pass went

`RSX_ZETADBG=<hex>` (new) lists the first draws that use a depth surface. The
18 shadow-pass draws into `0x5080000` all have colour target NONE, so the
backend took them for display draws. They were drawn into the window, with a
1280x720 viewport and the shared depth buffer, which is cleared at every
change of target. Nothing ever held the 1024x1024 map.

`TEXREJ` now prints the unit's address register. Unit 13 is `0x60030404`:

- compare GEQUAL (bits 28-30 = 6);
- border wrap on both axes;
- linear filter.

RPCS3's capture of this title agrees, in its Vulkan terms:

- a compare sampler with LESS_EQUAL, the guest's GEQUAL reversed, so a
  pixel is lit where the stored depth is at least the reference;
- a linear filter;
- a white border.

Its fragment program samples with uv = `tc9.xy / tc9.w` and reference
`tc9.z / tc9.w`, and replicates the 0-1 result to all four channels.

### 49.2 The change (`RSX_ZONLY=0` turns all of it off)

- **Depth-only passes.** A draw with colour target NONE and a depth surface
  gets a depth buffer of its own for that surface. It is created at the
  surface's clip size, kept across frames, and bound with no colour target
  (`zb_*`, DSV heap slots 2-5).
- **Depth formats are bound.** Formats 0x90-0x93, LN forms included, are now
  accepted. A unit bound to a surface a depth-only pass drew samples that
  buffer through an R24 view.
- **The compare.** The fragment program's samples of such a unit become
  `rsx_shd<u>(coord)`: four Loads, the guest's compare against the reference,
  and bilinear weights. Texels outside the map read 1.0, the white border.
  The PSO key carries the shadow units and the compare (`s_pso_shd`).
- **`RSX_SHADOW=0`** keeps the pass but makes every compare pass, which is the
  old, unshadowed look.

Checked:

- **The map.** `RSX_CAP` now writes each depth-only buffer as
  `zb<slot>_<offset>.pgm`. It shows both cars from above, laid out like
  RPCS3's: 188,000 texels nearer than the far plane, depth 0x36EC80 to
  0xE7D119.
- **The term.** `RSX_SHADOW_SHOW=1` paints a program's shadow term green
  (lit) and red (shadowed). It is lit on top surfaces and shadowed under the
  rear spoiler lip, in the licence-plate recess, on the lower flanks and in
  the wheel wells. Grazing flanks show some speckle.
- **Twelve car programs** compare on unit 13. No sample site went
  unrewritten, and nothing failed to compile.
- **Frame rate.** No change: 19.4 fps against 19.4 in a paired run.

Mistakes made while checking, to save the next person:

- **Views of programs that don't sample.** Unit 13 stays bound with the
  shadow map for programs that never sample it, the final composite among
  them. A debug view that rewrote every program with the unit bound turned
  whole screens one colour. The views now apply only to programs with a
  sample site.
- **The car pass writes three targets.** Its output is `_out.t0`, not
  `return _o`, so the first views never reached it.
- **The capture fires in the logo fade.** The shadow pass already runs
  there. Use `RSX_CAP_ZB=<n>` to capture n frames after the first
  depth-only pass, and `scratch\capshot.ps1` to drive it.

**Polygon offset.** It is now decoded (`poly_offset_*` in `rsx_state`;
`RSX_POLYOFS_DBG=1`, `RSX_POFSDBG=<n>`), but not applied. The title sets
factor -5 and bias -200 on two 9-vertex draws in the main pass, probably
decals. The shadow pass uses none.

### 49.3 The dealership stall is not this

A/B with `scratch\ab_env.ps1` (new; one exe, alternating environments, the
Phase 43 measurement), four pairs. A had the shadows on, B had
`RSX_ZONLY=0`:

| | A, shadows on | B, `RSX_ZONLY=0` |
| --- | --- | --- |
| Runs that stalled | 1 of 4 | 3 of 4 |
| Window fps, runs that did not stall | 16.5, 17.9, 16.7 | 14.1 |

Both rates are above 46.3's "1 in 3". A RenderDoc replay shared the GPU with
some of these runs. Several runs that took an `RSX_CAP` capture also
stalled; plain runs today did not.

Soak (`scripts/soak.py 6 40`) after all of Phase 49: 0 of 6 bad, 152 opens
and about 1,638 flips each, as before.

### 49.4 The image is dimmer than RPCS3's: the bloom comes out black

**Correction, same day: not a fault.** The brighter RPCS3 screenshot was
captured in HDR and ours in SDR (the user's finding). RPCS3's own
framebuffer in the RenderDoc capture (`cars_final.png`) is no brighter than
ours: a deep blue backdrop with no visible glow. The rest of this section is
kept as a record. The bloom difference it measured is real but has no
visible effect worth chasing, and the two fixes stay because they are
correct.

The user compared screenshots: our whole dealership is dimmer than RPCS3's.
In RPCS3's capture the post-processing after the scene is:

- a bright-pass into 512x256, two more downsamples to 256x128 and 128x64,
  and horizontal blurs through `0x2880000`;
- the composite, `scene + bloom0 * k + bloom1 + bloom2`, into the
  1920x1080 display.

RPCS3 runs this title at 1080p. There is no tone curve.

Our chain has the same ops, and our scene target is no darker than RPCS3's.
Our bloom levels are nearly black: means of 0.2-0.4 out of 255, peaks of
3-5. RPCS3's 128x64 level is a broad grey glow.

**Measured.** The bright-pass program (`0x057B5501`, `out = scene + k0`,
`FPK_FP=57B5501`) runs with `k0 = -0.99` for the bright pass and 0 for the
plain downsamples. With -0.99 almost nothing passes.

**Hypothesis, not confirmed.** The title sets `k0` from its own exposure
estimate, and that estimate is wrong here. Two candidates were found and
fixed along the way, neither of which changed the picture:

- **One-pixel viewports were ignored.** The per-draw viewport needed at
  least 2x2, so the luminance reduction's last passes (2x1, then 1x1 at
  (0, 716) in `0x2880000`) covered the whole target and overwrote the
  levels. Fixed; `RSX_VP_MIN2=1` restores the old rule.
- **Small results never reached guest memory.** The backend never writes
  GPU results back into guest memory, and a title that reads its 1x1
  average luminance with the CPU sees stale bytes. Draws of at most 16
  pixels into an A8R8G8B8 target are now copied out at the end of the frame
  and written into guest memory when the next frame starts, while the GPU is
  idle. `RSX_RT_WB=0` turns it off; `RSX_RT_WB_DBG=<surface>|1` lists the
  copies. The 1x1 now reads `00 26 24 22` (A, R, G, B) in guest memory.

**Not established.** Reading RPCS3's `k0` from the capture gave
inconsistent values: the constants buffer is bound with dynamic offsets,
and `scratch/renderdoc/cbuf.py` doesn't resolve them. RPCS3's bright-pass
output also doesn't line up pixel for pixel with its own scene, so it is
not yet a trustworthy reference.

**Next.** Find what writes the program's constant at `0xC57B5500` (a guest
write watch) and trace its inputs back to whatever the title measures. Then
compare that input with RPCS3's.

Also added:

- `RSX_LUMA_POKE=<word>`, which writes a word into the pixel of the
  frame's last single-pixel offscreen draw. It hit a reflection cube's mip
  tail, so it is only a starting point.
- `scratch\capshot.ps1`, which saves the game's own backbuffer, never the
  desktop.

## Phase 48 - Player settings file, and a first look at 1080p (2026-10-15)

`gt5p_settings.toml` (`src/gt5p_settings.*`, toml++ 3.4.0 in
`external/tomlplusplus`) is read at the top of `main()`. Its keys are
`video.resolution`, `msaa`, `vsync`, `shader_cache`,
`input.sdl_controllers`, `keyboard` and `debug.verbose_log`. Each is
handed to the runtime as the environment variable it already reads, and
only when that variable is unset. `GT5P_NO_SETTINGS=1` ignores the file;
`boot.py`, `soak.py` and the `scratch\*.ps1` run scripts set it.

Tested here, from the log of short headless starts:

- defaults written to the repo root;
- a broken header reported with its line;
- `msaa = 3`, `vsync = 1`, `keyboard = "yes"` and an unknown `fov` each
  reported and defaulted;
- `RSX_MSAA=2` beating `msaa = 8`;
- an older file without the new keys;
- `GT5P_NO_SETTINGS`;
- `GT5P_RESOLUTION=1080p`.

Not tried:

- `vsync`, `shader_cache` and the input switches in play;
- starting from Explorer.

**1080p.** With `resolution = "1080p"` the title configures `resId=1` itself
and renders at 1920x1080. A windowed run to the dealership showed the cars,
rims and floor reflection at about 17 fps, the same as 720p. The Showroom
and Event icons and the Cross glyph beside "Enter" were missing; they draw
at 720p.

Hypothesis, not checked: the backend's rule that binds the frame copy for
any texture of display size (`SCREEN_AS_TEX`) or another 1280x720
assumption.

## Phase 47 - The rims and the shadow pass: Cell vector stores the lifter skipped (2026-10-15)

### 47.1 The reference: a RenderDoc capture of RPCS3

RPCS3 (Vulkan, RenderDoc compatibility mode on, resolution scale 100%) was
launched from RenderDoc and the dealership frame captured. RenderDoc 1.46's
replay API is scriptable from `qrenderdoc.exe --python <script>` (the scripts
are in `scratch/renderdoc/`, the captures and their output beside them; all
gitignored, they hold game data). What the frame is made of:

- Six 256x511 cube faces, the reflection group at 640x360, the bloom chain,
  then **a depth-only pass of 18 draws into a 1024x1024 target at local
  `0x5080000`** (the shadow map), then the main car pass, then the 2D layer.
- Pixel history on a rim pixel names the draw: one indexed triangle list of
  about 49,000 indices per wheel pair, reading the shadow map on unit 13, a
  64x64 ARGB texture on unit 0, the environment cube on 14 and the 16x16 table
  on 15. Two more triangle lists and a decal follow it per wheel set.
- In our frame (`RSX_CAP`, whose manifest now lists all 16 units): no
  1024x1024 pass, units 12 and 13 always the 1x1 dummy, and no draw with the
  rim's textures. The disc in our wheels was the brake rotor, as Phase 46.5
  said, but 46.5's "the title never sends the rims" stopped one step short.

### 47.2 Why the title turned shadows off

Traced in the PPU code with temporary prints in `generated/` (all removed):

- The unit-13 texture comes from a global slot (`G+0x1C44`, G at `0x015F8684`)
  that `func_00D6D930` binds, falling back to a 1x1 default when it is null.
- `PDIScene::PassShadow::render` (`func_008107C0`, vtable `0x01261348`; class
  names from the RTTI) fills it. It runs every frame, but `func_00825780`,
  which builds the shadow frustum, left its "nothing to shadow" byte
  (`ctx+0x721C`) set, so the pass took the disabled branch.
- That byte is cleared only when the caster bounds at `ctx+0x7338` are valid.
  They held `(0, 0xD00A7790, 4.62)` for both min and max: a guest stack
  address, not a coordinate.
- The bounds are grown from points transformed by `func_00BC6748`, which ends
  in `stvrx v0,r8,r3; stvlx v0,r0,r3`. The lifter emitted both as
  `/* TODO */` no-ops, so the transformed point was never stored and the
  bounds were built from whatever the stack held.

On the way, two dead ends worth recording: the data source is not it
(`boot_from=gamedata` against RPCS3's installed `PDIPFS` gives the same frame;
note RPCS3 runs the hard-disk `EMAIN.SELF`, 304 bytes larger than the disc's,
with `boot_from=gamedata`), and neither are the Z-cull report values
(`GCM_REPORT_FULL=<mask>`, new, answers chosen report types with 0xFFFF).

### 47.3 The fix: instructions the PPU lifter left as no-ops

ps3recomp `tools/ppu_lifter.py` now lowers every instruction it had marked
TODO in this executable except `.word` data:

| Instruction | Sites | |
| --- | --- | --- |
| `stvlx`, `stvrx` (and the `l` cache-hint forms) | 33 + 33 | Cell unaligned vector stores |
| `lswi`, `stswi` | 48 + 48 | byte strings through consecutive registers |
| `vsum4sbs` | 3 | signed byte sums per word, saturated |

Re-lifted with the README command, then `setjmp_patch.py` and
`instrument_alloc.py`. Against the previous tree the only code differences
are the new lowerings and those two scripts' output (the latter's script has
changed since; `scratch/instrument_txt.py`'s wrapper of `func_007D3580` is
gone, as Phase 22 says it would be).

Result at the dealership: **the five-spoke rims are drawn** (with the ACURA
centre caps), and the shadow pass is issued: 18 draws at 1024x1024, the
same count as RPCS3's. The rims were not a separate fault; they depended on
the same missing stores (which path exactly is not traced). Soak
(`scripts/soak.py 6 40`): 0 of 6 bad, all six at 152 `GT.VOL` opens and
about 1,640 flips.

### 47.4 Still open: the shadow map is bound but not sampled

The title now binds the shadow map to unit 13 as `DEPTH24_D8` (format `0xB0`,
linear), and the backend's bind list does not take depth formats, so the
unit keeps the dummy and the cars are drawn unshadowed. `RSX_TEXREJ=1` (new)
lists every bind the list rejects. Supporting it needs a depth copy per zeta
surface (the existing path keeps one, for the text mask) and the RSX's
compare-on-sample for depth textures. Next.

### 47.5 Also fixed: three unlifted SPU job handlers

Job image 4 (`j307E5DC7`) dispatches through a position-independent jump
table at LS `0x1C84` (`ila r81,0x1C84; a r66,r81,r126`, entries relative to
the table). Three of its 38 targets (`0x1DB8`, `0x1E90`, `0x1ED0`) were never
lifted and ran on the SPU interpreter; those are the `[spu-smc] microstep ...
handing to the interpreter` lines of 46.5. `scripts/lift_spu_jobs.py` now
seeds every target of such tables (`SPU_PIC_TABLES=0` to lift without). Only
that image changed. It made no visible difference; the interpreter had been
running them correctly.

Diagnostics added: `SPU_PUTVAL=<word>[,lo,hi]` (SPU DMA puts carrying a
word, the SPU-side `PPU_WVAL`); the FIFO trace (`GCM_FTRACE`) prints each
header's EA.

## Phase 46 - Indexed vertex uploads; car reflections; a dealership stall (2026-10-15)

### 46.1 Where the uploads go (`RSX_VTXSTAT=1`)

New diagnostic: every 5 s, per vertex-upload path, calls, vertices asked for
and written, time, and a histogram of call sizes. At the Car Dealer page, per
5 s (about 84 frames): indexed triangles 334,000 calls, 75.5 million vertices,
1.70 s (22.5 ns a vertex); indexed strips 67,000 calls, 16.5 million in and
36.6 million out, 1.08 s. Uploads were 2.79 s of the FIFO walk's 3.40 s;
`vp_stage_commit` (256-byte staging compacted afterwards) 0.35 s of it. Almost
every call is 64-256 indices: the RSX sends a stream in batches of at most
256, so splitting a draw across threads would not pay. The per-call vertex
cache hit 73% (84.5 million hits, 31.5 million fetches): most of the work was
copying already-converted vertices into duplicate slots.

With every upload skipped (`RSX_VTX_SKIP=1`) the present thread falls to 0.39 s
of FIFO and 0.03 s of present per 5 s and the page runs at 22 fps: the most
any vertex work can buy, before the title's own threads and the SPU jobs.

### 46.2 Indexed uploads (`RSX_VTX_INDEXED`, default on)

ps3recomp `rsx_d3d12_backend.c`. Indexed triangles and strips no longer expand
to triangle lists. Each call keeps a map from guest index to local vertex;
a vertex is fetched the first time the call sees it and written once, compact,
straight into the upload heap; the call's indices go to a new upload-heap index
buffer (4 M x 32-bit per frame, double-buffered like `vp_vb`) and the record
is drawn with `DrawIndexedInstanced`. Strip continuation, primitive restart
and winding are the same loop. Batch merging still works: indices are kept on
the CPU until the record is decided, then written with the merge offset (the
upload heap is write-combined and never read back). Whether a record slot is
indexed is stamped with a frame generation, because records are refilled
field by field and never cleared.

`RSX_VTX_INDEXED=0` restores the expansion; so do `RSX_VFAST=0`/`check`,
immediate-mode vertices, and the diagnostics that read expanded vertices
(`RSX_DBG_VTX`, `RSX_DBG_TRACK`, `RSX_DBG_SCALE`, `IDX_DBG`, `IDXDBG`,
`VTX_DUMP`).

Result: vertices written per frame fall to about a third (indexed triangles:
91 million indices, 27 million vertices per 5 s), upload time per frame from
about 33 to about 21 ms, present-thread work per frame from about 46 to 41 ms.
Clean runs 18.7-20 fps (median about 19.5) against 17.4 for the pre-session
baseline. The present thread is no longer saturated (about 76%); `PDI:1` and
the main thread are as busy. The page draws the same. The frame vertex cap
(`MAX_VERTICES`, 1.31 million) was below the 1.38 million the page asked for,
so some draws were being dropped before; now none are.

### 46.3 A dealership stall that today's builds hit far more often

Two shapes, neither logging anything: the job lanes spin (about 1-8 fps, 6.5
cores, no lane threads exiting), or the title stops submitting (no presents,
2.4 cores). Counted at the page: the pre-session baseline exe 0 of about 30
runs; builds since Phase 45's helper change about 1 in 9; builds with the
index buffers about 9 in 23. Measured and ruled out:

- the new SPU helpers: the same tree with the old ones (`SPU_SHUFB_SWAP`,
  `SPU_BYTETAB_RUNTIME`) stalled 3 of 6, the new 2 of 6;
- the index buffers themselves: `RSX_VTX_INDEXED=0` on the same build stalled
  too; so did a run with the profiler view disabled;
- the taskset `WAIT_SIGNAL` 1 s wait (upstream 0.14's fix): never entered.

Hypothesis, not tested: a race in the job manager's lane hand-offs whose
window grows as the pipeline gets faster (the rate rises with the frame
rate). Not found yet; it is the next thing to look at.

### 46.4 Car reflections

`RSX_TEXUNITDBG=<n>` (new) lists, for the first n fragment programs, every
bound unit: size, format, cube flag, offset, mip count, matching target, LOD,
filter, address and remap registers. 128 of the page's 141 programs bind
units above 3; the car materials share one layout. Three faults, each with a
switch that undoes it:

- **Cube maps on units 4-15** (`RSX_CUBE_HI=0`). The environment map is on
  unit 14, but only units 0-3 were treated as cubes, and the decompiler was
  always called with cube mask 0, so its per-unit `TextureCube` declarations
  never appeared: the cube was sampled as a 2D texture with the reflection
  vector's x and y (smeared roof and glass). Cube units 4-15 now go in bits
  20-31 of the PSO key word and the whole 16-unit mask goes to the decompiler.
- **A cube whose faces are render targets** (`RSX_CUBE_RT=0`). The title
  renders that map: six linear 256x256 faces, each its own surface with the
  mip chain stacked below level 0 at the same pitch (511 rows, face stride
  523,264 bytes, `RSX_RTDRAWDBG=<hex offset>` shows the mip draws every
  frame). The unit resolved to face 0's target, a 2D resource behind a
  `TextureCube`. Such a unit now gets a real 6-face cube with all levels,
  refreshed once a frame by the first draw that samples it.
- **Constant remaps** (`RSX_REMAP_CONST=0`). Two 1x1 units at offset 0 have
  `TEXTURE_CONTROL1` = `0x5500`: every channel ONE. Offset 0 is display buffer
  0, so they took the display-copy path, which ignores the remap, and read
  the screen's black corner; the paint's lit term was multiplied by it.
  A unit whose remap leaves no channel on the crossbar now samples its
  constants. `RSX_TEX0_PROBE=<AARRGGBB>` (an experiment that writes guest
  memory) was how this was found.

- **sRGB decode on units 4-15** (`RSX_GAMMA_HI=0`). The environment cube's
  address register asks for decode on read (bits 20-22 = 7), but the decode
  was only recorded for units 0-3, so the reflection read about twice too
  bright and buried the paint: both cars looked like mirror chrome. Units
  4-15 are now a second key word (`s_pso_ghi`) in the pipeline cache.

How the paint was traced, for the next material problem. `FP_IDCOLOR=3`
paints every program that samples unit 13, 14 or 15 a flat colour and logs
`[FPID] fp=... rgb=...`; sampling the screenshot and matching the sRGB-encoded
logged colours identified the body (`0x05D3E001`) and rims (`0x05D40541`,
`0x05EFBC01`) exactly. `FP_SHOW=<expr>` with `FP_TEX_FP=<hex>` then showed
the paint ramp lookup (`r[1]`, unit 0 at row `k5.x`: correct red) and the
vertex colour (`input.col0`; `VP_ATTRS_RAW=3:<n>` shows the raw bytes, grey
`60..9F` with `FF`, i.e. baked occlusion). The paint is lighting x a colour
ramp + specular x `col0.x` + environment x Fresnel x `col0.y`. `FP_SHOW` and
`FP_IDCOLOR` now also find this decompiler's `float4 _o = ` and
`float4 _o0 = ` outputs; they did nothing before.

Before: the silver car drew black, glass and roofs a pink-white smear. After:
Formula Red and Sebring Silver read as on RPCS3, with reflections in
proportion (the red is perhaps a little less saturated). Still different from
RPCS3: the rims. Their program (lighting x the 128x128 DXT3 rim texture on
unit 0) draws only a solid grey disc with a dark hub; the spokes are not cut
out by alpha (the program outputs a constant alpha), so they are geometry that
is not drawn or not visible. No failed pipeline, skipped primitive or
unsupported format is logged; `CULL_OFF=1` turns culling off everywhere and
only shows the sky dome's inside, so culling is untested. Also missing: the
reflection of the cars in the floor.

### 46.5 The rims are never drawn; depth state now follows the title

- **The disc in each wheel is the brake rotor.** `RSX_TEXDUMP=<hex offset>`
  (new) wrote the program's unit-0 texture (128x128 DXT3) to `scratch/`;
  decoded (`scratch/dxt.py`) it is a grey rotor with a dark centre, exactly
  what is drawn. The five-spoke rim in front of it is missing.
- **Not hidden.** `DEPTH_OFF=1` shows the whole car through itself (chassis,
  interior, all four wheels from both sides) and still no rims. `CULL_OFF_FP`
  (new: culling off for listed programs) changes nothing.
- **Not dropped by the backend.** `RSX_DROPDBG=1` (new) counts, per fragment
  program and primitive, draw callbacks against vertices emitted: nothing has
  calls without vertices. `RSX_UNKNOWN=1` (new) counts methods no handler
  knows: no draw method among them (no `INLINE_ARRAY`); the unhandled ones are
  state (texture-coordinate control `0x0B40`-`0x0B64`, vertex cache
  invalidates `0x1710`/`0x1714`, polygon offset `0x0A68`/`0x0A78`/`0x0A7C`,
  back-face stencil `0x034C`-`0x0378`, window offset `0x02B8`, `0x1D88`).
- So the title never sends the rim draws. Its render lists are built by SPU
  jobs; at the page job image 4 (`j307E5DC7`) keeps handing code at LS
  `0x1DC0`, `0x1EA4`, `0x1EE0` to the interpreter (`[spu-smc] microstep`), which
  AGENTS.md says not to trust. Hypothesis, not tested: a job that should emit
  the rims misbehaves there, or its culling drops them.
- **Depth state** (`RSX_DEPTH_STATE=0` undoes it). Every pipeline tested
  `LESS_EQUAL` and wrote depth whatever the title set; it now uses the title's
  compare and write mask (bits 28-31 of the stencil key word), and a disabled
  test is `ALWAYS` without writes. The page looks the same. This was
  suspected for the rims and is not their cause, but it was wrong either way.
- Frame captures for comparisons: `CELLMARK_DUMP=<n> CELLMARK_DUMP_MINDRAWS=1700
  CELLMARK_DUMP_EVERY=<k> CELLMARK_DUMP_DIR=<dir>/` writes what the renderer
  presented; desktop screenshots pick up whatever window is on top.
- Still open from an outside review, not checked: shadow-map compare on
  sampling (possibly the black spikes on the rear deck), black tail-light
  lenses, the floor reflection, units 4-15's filter/wrap and unnormalised
  coordinates. Also seen: the 16x16 tables on units 11 and 15 have the unnormalised
coordinate bit set, which the backend only honours on units 0-3, and units
4-15 use the fixed sampler bank rather than the title's filter and wrap.

## Phase 45 - SPU register cache, and the present thread is the bottleneck (2026-10-15)

Measured as in Phase 44 (`scratch/perf.ps1`), two runs per setting unless
stated.

### 45.1 SPU register cache: correct, not faster

ps3recomp `tools/spu_lifter.py --regcache` keeps each lifted function's guest
registers in C locals. `ctx->gpr[]` is stored only where something else can
read it: every exit (return, transfer, stop, halt; only registers changed
since the last sync) and around every runtime or lifted call (stored before,
all reloaded after, since stop handlers, the interpreter and callees write
registers). `scripts/lift_spu_jobs.py` passes it only with `SPU_REGCACHE=1`;
the default lift is byte-for-byte what it was (checked with `diff -r`).

The hottest lane function, `b01376080` `0xF8C0` (13% of lane samples), is a
143-instruction loop over about 70 registers. Measured on it alone with
`scratch/rc/bench.c`, which runs the old and new versions on the same random
register and local-store state (64 passes per call) and compares every
register lane and local-store word:

- 1,000 trials, **0 differ**. 14 NaN lanes carry a different payload: x86
  keeps the first operand's NaN and the compiler may swap a commutative add's
  operands. SPU single precision has no NaNs, so both are equally wrong there.
- Speed **0.85x to 0.97x** of the old code. About 70 live 128-bit values do
  not fit in 16 XMM registers; the compiler spills 858 times, so the loads and
  stores move from the context to the stack, plus entry and exit copies.
  Loads and stores to `ctx` were cheap all along (L1, store forwarding).
- In the game: 16.4 fps in one run against 17.5.

Kept, off. Not worth revisiting without more host registers (AVX-512 has 32).

### 45.2 SPU helpers: shufb without byte swaps, constant rotate masks

The time in that loop is in the helpers. Changes in ps3recomp
`runtime/spu/spu_helpers.h`:

- `spu_shufb` (31 per pass): SPU byte P is host byte `P ^ 3` and the control
  sits at the same host positions as the result, so the four swapping
  `pshufb`s go: index `C ^ 3`, bit 4 of C picks b, bit 7 marks the special
  selectors whose value is a table lookup on the high nibble. 9 instructions
  instead of about 17. `SPU_SHUFB_SWAP` restores the old one.
- The byte rotate/shift masks are a compile-time table, not one built on
  first use (a check on every rotate). `SPU_BYTETAB_RUNTIME` restores it.

Checked against the byte-loop references: 3.28 million cases (every control
byte value in every position, all shift counts), 0 differ
(`scratch/rc/test_shuf.c`). The hot loop: **1.07x to 1.08x**, results
identical over 1,000 trials. Too small to move the frame rate on its own.

### 45.3 The present thread is the serial limit

The frame-rate pattern pointed past the SPU code: 62 fps on the
confirmation screen, 31 on the menu, 20 at the dealership with every draw
dropped, 17.5 with them; and Phase 44 cut 7% of the lanes' work for no gain.

`src/gt5p_present.cpp`'s one thread ticks vblank and flips, walks the FIFO
(which does the vertex expansion), presents, and pumps window messages, then
sleeps 4 ms. Its `GT5P_PRESENT_PROF` lines at the dealership, per 5 s: FIFO
3.33 s, present 0.83 s, about 87 presents. So per frame about 37 ms of FIFO
walk plus 9 ms of present, roughly 46 ms on one thread, a ceiling near 21 fps.

| Setting | fps |
| --- | --- |
| Default (present waits for vsync, 4 ms sleep) | 18.3 (one other run stalled, the Phase 43 three-lane stall) |
| `RSX_PRESENT_SYNC=0` (new: present does not wait for vsync) | 18.0, 17.6 |
| `GT5P_PRESENT_SLEEP=1` (new: outer sleep in ms) | 18.7, 18.6 |
| `GT5P_PRESENT_SLEEP=0` | 18.7, 19.8; present thread at 99% |

Present time is the same 0.83 s with or without vsync, so it is the backend's
own submission, not a vblank wait. Sampled with `GT5P_SAMPLE=4` and no sleep
(4,423 samples of the present thread): `read_vp_vertex` **39%**, the message
pump 12% (it spins without the sleep), `render_frame_body` 9%,
`vp_stage_commit` 7%, FIFO decode itself about 5%.

So the Phase 43 conclusion that the SPU lanes are the critical path was
wrong: one lane per workload making it slower shows the lanes *can* become
the limit, not that they are it now. The limit is the present thread, two
fifths of it CPU vertex expansion, with the title's `PDI:1` (79%) and main
thread (73%) close behind. Hypothesis, not yet measured: that is why
`RSX_VTX_SKIP=1` only reaches 20, those two threads capping it once the
vertex work is gone. If it holds, past 20 needs both
the vertex work off (or spread beyond) the present thread and cheaper guest
PPU threads.

Defaults are unchanged; both switches are measurement aids for now.

### 45.4 Live profiler view (`GT5P_PROFVIEW`, F3)

`src/gt5p_profview.cpp`: a GDI window owned by the game window and kept over
its top-left corner, click-through, redrawn ten times a second. F3 (with the
game focused) shows and hides it; `GT5P_PROFVIEW=1` shows it from the start;
`GT5P_PROFVIEW=0` starts nothing. Not created headless. It shows:

- fps, average and worst frame over the last second;
- the last 220 frame intervals, coloured by how many 60 Hz vblanks each took
  (green 1, yellow 2, orange 3, red 4 or more), guide lines at 60/30/20 fps;
- the present thread's time per frame, stacked: FIFO walk, present, message
  pump, the rest (sleep and idle). The present thread passes running totals to
  `gt5p_pv_frame()` after each present;
- CPU per thread over the last second, from a thread snapshot, named by the
  guest's thread name or the host thread description. Host threads now name
  themselves (`ps3_name_thread`, ps3recomp `include/ps3emu/thread_name.h`,
  called where they print `[hostthread]`). The job lanes exit within the
  second, so they are the process total minus the live threads.

At the dealership it shows what 45.3 found, and one more thing: frame
intervals are only ever about 50 or 66 ms. The present thread's work is about
46.5 ms a frame (FIFO 37.2, present 9.3), and a flip completes on the next
16 ms vblank tick, so a frame takes 3 or 4 vblanks: 17.9 fps. A console in
vsync mode quantises the same way. So cutting the present thread's work pays
off in steps: below about 33 ms a frame reaches 30 fps; anything short of
that changes little.

## Phase 44 - Performance follow-ups (2026-10-15)

Each part is one change, measured the Phase 43 way: Car Dealer page with the
Showroom panel open, windowed, `PS3_VERBOSE=0`, warm shader cache.
`scratch/perf.ps1 -Tag <t> -N 3 [NAME=VALUE ...]` repeats it N times: the
title-bar fps at 85 s, then 15 s of CPU (process total, and threads that
exited, which are the job manager's lanes). Medians of three runs. The
baseline exe is in `scratch/baseline/`.

Baseline, re-measured this session: **17.0 fps** (17.44, 17.0, 16.73);
process 6.4 cores, of which 3.2 in lanes; present 83%, main 77%, `PDI:1` 77%,
`spurs-jc` 69%.

### 44.1 Where the guest PPU threads run

`PS3_PPU_PRIO_SCHED=2` (set by `src/main.cpp`) pins every guest PPU thread to
mask 3. `scratch/topo.c` (GetLogicalProcessorInformationEx) on this machine
(i5-12400F, 6 cores, 12 threads, no efficiency cores): core 0 is logical CPUs
0 and 1, core 1 is 2 and 3, and so on. So mask 3 is both hardware threads of
one physical core, as suspected.

| Mask | fps (3 runs) | Median |
| --- | --- | --- |
| 3 (legacy, both threads of core 0), new build | 17.0, 17.19, 17.19 | 17.2 |
| Topology: first CPU of cores 1 and 2 (CPUs 2, 4) | 16.49, 16.0, 16.24 | 16.2 |
| Both threads of core 1 (`PS3_PPU_CORES=C`) | 16.25, 16.0, 17.72 | 16.3 |
| Unpinned (`PS3_PPU_PRIO_SCHED=0`) | 15.52, 15.5, 16.0 | 15.5 |
| Mask 3 + present thread and lanes off CPUs 0-1 (`PS3_HOST_AVOID_PPU=1`) | 17.19, 17.46, 18.0 | 17.5 |

Unpinned the main thread rises to 98% of a core and the frame rate falls:
more CPU, fewer frames. Separate cores are slower than one shared core.
Hypothesis, not tested: `PDI:1` mostly polls a queue the main thread and the
jobs update, and on one core the two share L1/L2, so the hand-offs are
cheaper; spinning on a separate core may also take memory bandwidth.

Kept (ps3recomp `runtime/syscalls/sys_ppu_thread.c`, `src/gt5p_present.cpp`):

- `PS3_PPU_CORES=<hex mask>` picks the CPUs; `PS3_PPU_CORES=topo` chooses by
  topology (first logical CPU of n different physical cores, core 0 skipped
  on 3+ cores, performance cores first, group 0). The default stays mask 3,
  because it measured fastest. One line at the first pinned thread:
  `[sched] guest PPU threads on logical CPUs 0,1 ...`.
- `PS3_HOST_AVOID_PPU=1` (off by default): the present thread and every
  job-manager lane get the process mask minus the PPU CPUs (0xFFC here). The
  gain is within the run-to-run spread, so it is not the default.

Soak on the default build: `python scripts/soak.py 10 40`, **0 bad boots of
10**, every run 152 `GT.VOL` opens and about 1,640 flips. The default
behaviour is the same as before (mask 3), so no before-soak was run. Sound was
not listened to. Conclusion: no frame-rate gain from pinning; the job
manager's lanes (Phase 43) remain the critical path.

### 44.2 SPU-side overhead in the job manager's lanes (no frame-rate gain)

The prompt this part started from aimed at the per-job async thread path in
`spu_workload.c` (thread per job, a print per dispatch, `spu_coh_forget_range`
and the lock-line lock). That path does not run on the dealership: two full
runs logged no `dispatch HIT (async)` line, and `spu_coh_forget_range` is only
called from it. The samples Phase 43 labelled `spu_coh_forget_range` are
`spu_coh_is_reserved`, the next function: maplook names the nearest symbol at
or before an address. "SPU job chain 63%" is `spurs-jc`, not the lanes.

Measured instead, on the lanes (`GT5P_SAMPLE=all` now keeps a separate table
for the lane threads, `cpu=lanes`; `scratch/lanecat.py` sums maplook output
into categories):

| Share of lane samples | |
| --- | --- |
| 51% | the job body's lifted code (`b01376080`; top `0xF8C0`, a 149-line SIMD loop of shuffles, selects, float compares and conversions) |
| 19% | branch dispatch (`spu_indirect_branch`, `spu_lookup`, the drain step) |
| 14.5% | channel reads, about half decrementer reads (`QueryPerformanceCounter` per `rdch $ch8`) in the polling loop at `0x4554`-`0x462C` |
| 5% | MFC/DMA |
| about 0 | atomics, coherency |

So about 80% of lane time is computation; the lanes are compute-bound.

Changes (ps3recomp, each with a way back):

- `spu_lookup` (spu_channels.c): a per-thread memo of (address, image) to
  function. The registry only grows and the first match wins, so a hit stays
  right; misses are not cached. `SPU_LOOKUP_CACHE=0` turns it off. Lookup
  samples halved (40 to 19), indirect-branch samples 52 to 33.
- `spu_fi` called `ldexpf` twice per element (eight C-library calls per
  instruction; `fi` follows every reciprocal estimate), and the four integer
  conversions called `exp2`. Now exact powers of two built from their bits
  (spu_helpers.h; `SPU_LIBM_SCALE` at build time restores the calls).
  `scratch/test_pow2.c`: 10,024,512 comparisons against `ldexpf`/`exp2`, every
  exponent the instructions can produce plus 2,000,000 whole `fi`
  instructions, 0 differ. About 4.5% of lane samples were these calls.
- `getenv` is cached per call site in `spu_channels.c` and `spu_drain.c` too.

Result, `scratch/perf.ps1`, which now also reports the average presents per
second over the window (`GT5P_PRESENT_PROF`), more stable than one title-bar
reading: baseline exe 17.5 fps (17.5, 17.5, 17.3), this build 17.6 and 17.4
(a third run was ended early when the window was closed on the menu). **No
gain.** Lane CPU stayed at 3.2 cores. Soak, `python scripts/soak.py 10 40`:
0 bad boots of 10, every run 152 opens. Sound was not listened to; the
changes are bit-exact by test (scale factors) or return the same function
(lookup).

Why: no single waste is left. Most of the lanes' time is the lifted SPU code,
and the lifter keeps all 128 registers in `ctx->gpr[]`, so every instruction
loads and stores 16-byte values in memory. Also the process uses about 6.4 of
12 logical CPUs, roughly one busy thread per physical core on this 6-core
part, so moving work between threads gains little. What would move it
(untested): register allocation in the SPU lifter (locals per function so the
compiler keeps values in registers), then perf-2's inline PPU memory access.

## Phase 43 - Dealership frame rate: 7.4 to 17.5 fps, and the title's own ceiling is about 20 (2026-10-14)

Measured on the Car Dealer page with the Showroom panel open, windowed,
`PS3_VERBOSE=0`, warm shader cache, `scratch/cpu2.ps1 -At 85` (the save's
button timings; per-thread CPU over a window). Before: 7.4 fps.

Tools added:

- `GT5P_SAMPLE=<n>` (`src/gt5p_present.cpp`): a sampling profiler for the n
  busiest threads, re-chosen every 10 s by CPU used. Samples in a DLL are
  unwound to their first caller in the executable, so CRT and driver time is
  charged to whoever called it. `scratch/maplook.py build/gt5p.map <log>`
  names the buckets per thread. One sample is about 2.3 ms of wall time when
  four threads are sampled.
- `GT5P_PRESENT_PROF=1` (existed): the present thread's split. At 7.4 fps it
  was 105 ms a frame walking the FIFO (which includes all vertex assembly)
  and 22 ms in the D3D12 replay.
- `RSX_VTX_SKIP=1`: drop every vertex upload. Nothing draws but every frame
  flips, which gives the frame rate the title reaches when the backend costs
  nothing.

What was slow, in the order found, and the fix (all in ps3recomp; the patch
is refreshed):

1. **`getenv` per draw.** The backend and the FIFO walker test dozens of
   debug switches per draw with a bare `getenv`. On Windows each call takes
   the CRT environment lock and scans the environment: 32% of the present
   thread in `ucrtbase` plus 14% in `ntdll`. New `include/ps3emu/getenv_cache.h`
   caches each literal lookup per call site; included by
   `rsx_d3d12_backend.c`, `cellGcmSys.c`, `rsx_commands.c` and `ppu_hle.cpp`.
   7.4 to about 11 fps.
2. **Vertex fetch.** `rsx_fetch_attrib` re-derived the debug switches, the
   frequency rule, the context DMA and the 1 MB page for every attribute of
   every vertex, and strips and fans expanded to lists fetched each vertex
   about three times. `read_vp_vertex` now builds a plan per upload and keeps
   a 1,024-entry cache of fetched vertices for the length of the upload
   (`RSX_VFAST=0` for the old path; `RSX_VFAST=check` fetches both ways and
   reports differences: 2,000,000 vertices checked, 0 differ). 11 to 16.7 fps.
3. **Guest memory accessors.** Every lifted load and store runs through the
   extern `vm_read*`/`vm_write*` in `ppu_loader.cpp`, and each ran a dozen
   diagnostic checks first (watch windows, spin detectors, the read
   histogram, thread-local bookkeeping): about 90% of the `PDI:1` thread.
   They now take a fast path unless a switch those checks read is set
   (`VM_SLOW=1` forces the full path; `PPU_HOTREAD=1` keeps the spin
   detectors). Bounds, null reports, raw SPU registers, SPU reservation
   coherency and the GCM ref poll are kept. 16.7 to 17.3 fps.
4. **`ppu_gcm_pump` on every HLE call** did three interlocked operations on
   shared lines with nothing pending: 21% of the main thread. It now returns
   on a plain read when nothing is pending.
5. **NID routing.** Each HLE call made three linear searches (PRX exports,
   context handlers, the whole NID table): about 40% of `PDI:1`. Memoised per
   thread, checked against each registry's size and a new export-registry
   generation (`HLE_ROUTE_MEMO=0` to search). It removed the cost but not a
   frame: 17.5 fps.

Where it stands at 17.5 fps:

- Present thread about 80%: of a 57 ms frame, about 25 ms is vertex work
  (`read_vp_vertex`, `vp_stage_commit`), 5 ms D3D12 calls, and about 12 ms
  idle with nothing to walk.
- With `RSX_VTX_SKIP=1` the title reaches **about 20 fps** with the present
  thread at 8%. The main thread (86%), `PDI:1` (85%) and the SPU job chain
  (63%) are the ceiling, not the backend. Reaching 30 needs those about 1.5
  times faster. Their samples are now spread over lifted functions
  (`func_00BA97B0` on `PDI:1`; `func_0091312C`, `func_0092CD68` on main),
  `lv2_syscall`, the mutex calls and SPU coherency (`spu_coh_forget_range`).
  Whether `PDI:1` is computing or polling is not known; next is to read
  `func_00BA97B0` in Ghidra and compare its import rate per frame with
  RPCS3's log.
- Seen in 2 of about 10 runs: the frame rate falls to about 1 fps, with three
  job-manager lanes at 99% each in the job body's polling loop
  (`b01376080` at `0x4554`-`0x462C`, Phase 38: transfer, wait, compare,
  delay). Cause not found. Hypothesis to test first: Phase 42 raised
  `SPU_DMA_REPEAT_MS` from 5 s to 120 s, so a poll that used to be cut off
  after 5 s now runs for two minutes.
- The page renders as before (checked by capture).

### Later in Phase 43: the job manager is the critical path

- **Hidden CPU.** The job manager's lanes are threads created for each
  dispatch (2,455 in 75 s) and live for milliseconds, so a per-thread CPU
  table misses them. Over 15 s the process used 97 s of CPU and 48.6 s of it
  was in threads that had already exited: about 3.2 cores of lanes.
  `scratch/cpu3.ps1` prints process, live and exited CPU.
  `GT5P_SAMPLE=all` samples the whole process, and lanes register themselves
  through `g_spurs_lane_start_hook` (cellSpurs.c) so they are sampled for
  their whole life.
- **One lane per workload** (`SPURS_READY_LANES=0`): 6.8 fps with the SPURS
  kernel thread at 97%. Normally both job-manager workloads (wid 0 and 1)
  run on 5 lanes, their maxContention (`SPURS_KERN_STAT=1`). The jobs'
  throughput sets the frame rate: about 150 ms of CPU a frame.
- So the frame is a pipeline: SPU render jobs write command lists into
  per-SPU rings, the present thread's walker drains them (36 ms a frame,
  mostly vertex expansion), and jobs wait for ring space while it is behind.
  That is why freeing the backend only lifts the ceiling to 20 fps.
- In the lanes, the job body's own code (`b01376080`, top at `0xF8C0`) and
  the SPU runtime (channel waits in `spu_rdch`, MFC, branch dispatch,
  `spu__pshufb_tab`) take about equal shares; the polling loop at `0x462C`
  is a small part. The profile is flat: no single function left above about
  5% of the process.
- Two unconditional prints were removed from the lanes' path:
  `[mfc-list] RESUME-ELEMS` (six `fprintf` calls per resume, about 8,000 a
  second; now `MFC_LIST_DBG=1`) and `[spurs-pm] poll` (about 1,000 a second;
  now `SPURS_PM_TRACE=1`). The log went from about 270,000 lines to 4,270 in
  a run. No measurable frame-rate change.

What would raise it further, largest first (none tried):

1. Faster SPU job execution: the lifted SPU code and the runtime under it
   (channel and MFC emulation, branch dispatch), since that is the critical
   path at 5 lanes a workload.
2. A cheaper walker: draw indexed from the unique vertices (strips and
   lists are expanded to about 980,000 vertices a frame now) or decode
   vertices on the GPU, so the rings drain sooner.
3. Inline fast paths for lifted PPU loads and stores (the header the lifter
   emits; rebuilds all ten chunks), for the main thread.

## Phase 42 - The Car Dealer page draws: the backend was dropping most of each frame (2026-10-14)

Choosing a manufacturer now shows the Car Dealer page as on RPCS3: the cars
on the showroom floor, cycling through their colours with captions, "Car
Dealer", the credit balance, the Showroom and Event buttons, and the footer.
The logo of Phases 39 to 41 was the last thing ever drawn on the display.
Every frame after it lost its main view, its post-processing and its 2D
layer inside the D3D12 backend. The title was issuing them all along.

How it was found, in order:

1. Frame captures across the entry (`RSX_CAP=1450:40:6`): the logo frames
   have a UI target and display draws; from the first showroom frame on there
   are 630 cube-map draws, a 640x360 pass, a clear, and nothing else.
2. `GCM_FTRACE=<flip>,<n>` (new): every command header the walker decodes
   between two `SetPrepareFlip` calls, with its first argument. This title
   writes no flip words into the FIFO. A whole showroom list is about 42,800
   headers. Its last tenth sets up the bloom chain (512/256/128), a 2048-wide
   target and the 1920-wide UI surface, then about 1,500 immediate-mode
   vertex writes and the five reports. So the walker did reach the post and
   UI passes.
3. `FRAME_BUDGET=<frame>` (now takes a starting frame): each showroom frame
   asked for about 983,000 vertices in 4,300 draws. The backend's per-frame
   vertex buffer held 393,216 vertices and its draw table 2,048. Some 4,000
   draws a frame were dropped once it filled, leaving the first 700.

Fixes (ps3recomp, `libs/video` and `runtime/spu`):

- **Per-frame caps.** `MAX_VERTICES` 1,310,720 (the generic vertex buffer
  is that times 256 bytes, double-buffered: 640 MB of upload heap) and
  `MAX_DRAWS` 6,144 (per-draw constants 104 MB). Packing vertices tighter
  than 16 float4 slots would cut this; not done.
- **Fragment programs longer than 4 KB.** The backend let the decompiler
  read 4,096 bytes. The showroom's programs end 5,264 to over 8,192 bytes
  in. Constant collection failed (`[FP] decompile fail`), and the fallback
  stopped part-way. Now `FP_UCODE_MAX` 32 KB, HLSL buffer 128 KB.
  `FP_FAIL_DUMP=<dir>` writes a failing program out for offline checking.
- **More than 64 constants.** Those programs have 88 to 98. Over 64, the
  backend baked them into the shader text. The title patches them every
  frame, so every frame recompiled 37 KB shaders and the window stopped
  answering. The per-draw slot now holds 128 (`FP_CB_CONSTS`).
- **Two watchdogs that killed a legitimate wait.** The first showroom
  frames take 15 to 18 s to replay, because their pixel shaders compile in
  0.25 to 0.5 s each (`[FP] slow compile`, `[D3D12] frame took`).
  - The walker's stuck-get rule resynced to `put` after eight idle passes
    while it waited at an unfilled SPU block. It now waits up to
    `GCM_FFFF_STUCK_MS` (120 s) there.
  - The SPU repeat guard halted render jobs after 5 s of polling an RSX
    label. Each halted job left its block unfilled for good. Now 120 s
    (`SPU_DMA_REPEAT_MS`).

Measured: three windowed runs with `scratch\inp.ps1 ... PAD_HOLD=...` all
reached the page. The disc-mode `gamedata/` (no install) was used for the
last of them.

**Later the same day: the entry stall and the dips.**

- The dips to 1 to 2 fps were recompiles. Some showroom programs have about
  140 inline constants, still over the slot. Those constants were printed
  into the shader text, and they change as the cars turn (one is a rotation
  matrix), so each change was a new 37 KB compile. The slot now holds 256
  (`FP_CB_CONSTS`).
- Compiled shaders are kept on disk (`shadercache/`, gitignored;
  `RSX_SHADER_CACHE=<dir>`, `0` turns it off).
- `RSX_FP_OPT=skip|0|2|3` made no difference to compile time (the compiler
  front end is the cost).
- Two windowed runs: the first entry stalled 9 s once while the cache filled.
  The second had no stall and no compiles, and held about 5 frames a second.
- `FP_HLSL_DUMP=<program>[,<dir>]` writes every text compiled for one
  program.

**Then: the logo came back in some runs.** A capture of such a run
(`RSX_CAP=1750:1:1`, `FRAME_BUDGET=1740`) still had 354 draws a frame
truncated. Quads are uploaded as six vertices per four, so a 976,000-vertex
frame overran the 1.3 M-vertex buffer, and the tail it lost was the 2D layer
again. Whether it fitted depended on what was on screen.

- **Vertices are stored compactly now.** Every vertex was 256 bytes (16
  attribute slots). A vertex now holds only the attributes in the program's
  input mask (`SET_VERTEX_ATTRIB_INPUT_MASK`), 16 bytes each, in slot
  order. It is assembled in host memory and copied packed into the upload
  heap (`vp_stage_commit`). Each draw records its stride and mask. The
  replay binds the buffer per draw, and the pipeline's input layout follows
  the mask, which is part of its key. `RSX_VTX_MASK=0` keeps all sixteen.
- Measured: 0 draws truncated, about 2,050 recorded a frame; 7 frames a
  second on the page (5 before); the main menu at 38 (31 before). Three
  windowed runs in a row reached the page. In one, the third Cross opened the
  Showroom panel (Acura NSX '91, Cr. 80,000).
- `PERF=20` before the change: vertex fetch was 39% of a frame
  (17.6 M vertices per 20 frames). After it, 23%.

Open:

- About 7 frames a second on the page. Most of the rest of a frame is
  outside the backend (guest threads and the walker): not yet profiled.
- On a machine with an empty cache, about 9 s of an unanswering window on
  first entry.
- The fallback when a pixel shader cannot be decompiled still runs a
  built-in shader. Nothing in the showroom hits it now.

Also measured in this phase:

- `boot_from=gamedata` (`GT5P_ARGS`) runs the title from an installed
  `dev_hdd0/game/BCUS98158` (its `PDIPFS`), mounts the system cache and uses
  `/dev_hdd1`, as RPCS3 does after its install. `boot_from=hddgame` is the
  PSN layout and exits.
- Disc mode with no install uses `APP_CACHE` paths and never calls
  `cellSysCacheMount`. RPCS3's first, disc-mode boot does the same. It is not
  a fault.

## Phase 41 - The dealership loads what RPCS3 loads; a lost log tail and a form encoder (2026-10-14)

Phase 40 said the title "opens no more files after `DealerTopRoot.gpb`". That
was wrong. `src/main.cpp` gives stdout and stderr 64 KB buffers, and the test
scripts end a run with `Stop-Process -Force`, so the last 64 KB of output was
never written: everything after choosing a manufacturer. A thread now flushes
both streams every second (`GT5P_FLUSH_MS`, default 1000, 0 turns it off).

With the tail kept, a run that picks Acura (`scratch\inp.ps1 90`, the
Phase 39 `PAD_HOLD`) reads, after `DealerTopRoot.gpb`: `TopMenuTemplate.gpb`,
scene script `s0079`, `DLSGadgetRoot.gpb`, character `mb14`, motions
`m0105` to `m0112`, scripts `s0078`, then `s0081` and `s0080`. An RPCS3 log of
the same steps (Acura, waited for the showroom) has the same list up to
`m0110`. The only difference: RPCS3 also stats
`/dev_hdd1/grim/cache/contents/%2Fnews%2F%2Fus%2Froot.xml` twice right after
`TopMenuTemplate.gpb`. Our build never does. The window still shows only the
Acura logo at 90 s, at about 10 frames a second. So the dealership is not
waiting on a file; what it waits on is still open.

Found on the way: four cache paths came out with a trailing `=`
(`serverlist2_us.xml=`, `tv2_us_14.xml=`, `tv2_us_root.xml=`,
`tv_0_448916194.pam=`). ps3recomp's `cellHttpUtilFormUrlEncode` took
`(out, size, key, value, written)` and wrote `key=value`; the SDK's takes one
string, `(out, size, in, inSize, required)`. The length was read as a pointer to
an empty value. It now encodes one string (space to `+`, unreserved bytes
kept, the rest `%XX`, terminated; `required` counts the terminator). The paths
now match RPCS3's.

RPCS3 finds those files because its hard disk holds the game's own install
(`dev_hdd0/game/BCUS98158/USRDIR/grim/file/contents`, 1,003 files, 2 GB:
`tv2_*.xml`, `.img`, `.pam` movies). Ours has none. Two tests, with copies
under `gamedata/` (ignored):

- All 1,003 files: at boot the title reads `tv2_us_14.xml`, loads
  `MovieRoot.gpb` and opens `tv_50_519336755.pam`. ps3recomp's `cellPamf`
  reads it as "0 streams" (version `0041`). Then a call goes through a NULL
  function pointer from `func_0099CAA0+0x608` many times, and the run ends at
  15 s on an access violation in `func_0099CAA0`. Not investigated: the movie
  path is separate from the dealership.
- Only the 28 `.xml` files: boot as before, and the dealership is the same
  logo at 90 s. The news files are not what it waits for.

The copies are in `gamedata/contents_aside`; the `contents` folder is empty
again, as before this phase.

Next, still: why the dealership draws only its environment and reflection
passes. A hypothesis, not tested: it waits for a per-frame result (a report,
a label or an SPU job's flag) that never arrives, rather than for data.

## Phase 40 - Dealership frames flow; the game then sits on the logo (2026-10-14)

Continues Phase 39. After choosing a manufacturer the title now renders about
10 frames a second, about 700 draws each, for as long as it is left running
(120 s measured, 727 frames, no stalled job). The picture is still the
manufacturer's logo on black. Three changes got it there:

1. **The FIFO waits at a block an SPU job has not filled yet.** The title's
   display list (`0x294xxxxx`-`0x299xxxxx`) carries a block per object for
   the render jobs to fill in. Until a job does, the block starts with
   `0xFFFFFFFF`. The walker decoded that as a method (0x1FFC, 2047 arguments)
   and skipped the block and whatever followed. It now stops the pass there
   and reads the word again on the next (`GCM_FFFF_PARK=0` for the old
   behaviour). `GCM_BLOCKDBG=<n>` shows a block before and after it is
   filled. A filled block is an ordinary indexed draw: vertex array offsets
   into the 5 MB output ring (`0x1680`-`0x168C`), an index array
   (`0x181C`/`0x1820`), `BEGIN` triangles, `DRAW_INDEX_ARRAY`, `END`, and the
   label update the jobs wait on (`0x1D6C` = `0x480`+, `0x1D74` = put).
   That label is what was never written in Phase 39, so the jobs waited for
   ring space for ever.
2. **Virtual SPUs that leave a job list at once are sent back in.** Most
   frames, one or two of the five lanes read the list's row while another
   lane had it marked closed between two updates (traced with
   `SPU_WATCHLSA=D00 SPU_WATCHLSA_EA=...`: those lanes fetched the list line
   for index 0xFFFF). The module then leaves and takes one off the ready
   count. With three or four lanes the per-SPU rings overflow. While other
   lanes are still working, a lane whose run lasted under 2 ms gets the count
   back and runs again (`SPURS_LANE_RETRY=0`: no retry). Lanes also start
   3 ms apart (`SPURS_LANE_STAGGER_MS`).
3. **Antialiasing reworked.** The dealership grid was reported still jagged.
   It was multisampled (`[RT] slot 6 ... drawn with 4 samples`), but the
   steps left were inside surfaces (the highlights on the bevelled floor
   tiles), which multisampling does not touch. On a multisampled target the
   fragment program now runs once per sample (`sample` interpolation on its
   inputs; `RSX_SSAA=0` for once per pixel). Edges and highlights are smooth
   in the capture.

**Where it stops now (measured).** A frame captured on the logo screen
(`RSX_CAP=1700:1:1 RSX_CAP_MIN=600`) has 630 draws into the six 256x511
targets at `0x4D00000`-`0x4F7EC00`, 71 into the scene target at 640x360,
then a clear of the scene target, and nothing to the display buffer. Those
draws include the SPU-built blocks, so the job pipeline works. The title is
not issuing its main view or its 2D layer. The last files it opened are
`DealerTopTransition.gpb` and `DealerTopRoot.gpb`, then nothing more from
`GT.VOL`. Hypothesis, untested: it is waiting to load the car or the
showroom, and the request never completes. The next measurement is RPCS3's
file sequence after choosing a manufacturer, to see what it opens next.

Not regressed: 3 of 3 headless boots full (`scratch/ab-p39c`); the main
menu and the dealership grid draw as before.

## Phase 39 - The dealership's render jobs: four faults fixed, not drawing yet (2026-10-14)

Choosing a manufacturer still shows the logo on black. The stall of Phase 38
(a job polling main-memory address 0) was the first of a chain. Measured, in
the order found:

1. **Jobs ran before they were started.** The job's ring record (start, end,
   put, label address; 16 bytes per SPU at element `+0x80`, element 0 at
   `0x016FA500`) is filled by `0x00BA49A8`, called from `0x00BA4A78` just
   before `cellSpursReadyCountStore(workload 0, 5)`. An HLE trace showed the
   job running and stalling before that call. ps3recomp's SPURS kernel ran
   every enabled workload each pass whatever its ready count. With
   `SPURS_READY_GATE=1` (now set by `src/main.cpp`) a workload runs only while
   its ready count is nonzero, and the kernel no longer decrements the count:
   with the gate on, the count for workload 4 was seen to go 1 -> 0 by itself,
   so the job manager clears it.
2. **Every interrupt wrote 76 registers across the running job's stack.** The
   job manager's interrupt handler builds a register save routine at LS
   `0x3FEC0` at run time; the runtime's small interpreter for such code
   decoded `stqa`/`lqa` addresses with a shift of 4 instead of 2, so the save
   went to `0x3E700` upwards in 64-byte steps instead of `0x3F9C0`. One of
   those quadwords landed on the job's saved return address (`0x3F940`); the
   job then returned into the interrupt handler and from there to `0x3FFFC`.
   Fixed in `spu_smc_microstep`.
3. **`maxContention` was always 1.** It is the ninth argument of
   `_cellSpursWorkloadAttributeInitialize`, passed on the stack at
   `0x70(r1)`; the HLE wrote 1. The five workloads now read 5, 5, 3, 3, 1.
4. **One host thread ran all workloads in turn.** A render workload that
   blocks stopped workload 4, which the render thread waits on. With the gate
   on, a workload wanted on more than one SPU now runs on a thread of its own,
   on min(ready count, maxContention) virtual SPUs, started 3 ms apart
   (`SPURS_LANE_STAGGER_MS`).

Also: the "256 identical transfers" guard kept its counter in statics shared
by all SPU threads, so it rarely fired; it is per thread now, and a small
repeated read gets `SPU_DMA_REPEAT_MS` (5 s) before it counts as wedged.

**What is left.** With all four, the first dealership frame's 484 jobs
finish in about 0.4 s. The next frame's jobs then fill their output rings
(1 MB per SPU, 5 MB shared by both frames' elements, at `0x2A2BDF80`) and
wait for the RSX to move the ring's label (labels `0x48`-`0x51`), and
nothing moves it: at the stall every label still holds its ring's start, and
the FIFO walker never jumps or calls into the ring (`GCM_BRDBG` over the ring:
0 lines). Each frame then lasts as long as the guard takes to stop the
waiting jobs. The job builds `SET_SEMAPHORE_OFFSET` (`0x1D6C`) and `0x1D74`
commands carrying its put pointer (job body `0x14F64`-`0x14FDC`); how that
output is meant to reach the RSX is not found. Hypothesis, untested: the PPU
links each job's output into the frame's commands after the job reports,
and that step is not happening.

Two smaller things seen and not explained: one or two of the five virtual
SPUs leave at once with "no command" on most runs (their list line reads as
zeros), and the picture stays the logo even on the frame whose jobs finish.

Not regressed: 4 of 4 headless boots full (`scratch/ab-p39`), menu sound
3,187 jobs a second at 55%.

**Antialiasing, added after the above (same day).** A target whose surface
format asks for antialiasing now gets a multisampled twin that the draws go
to, a multisampled depth buffer beside it, pipelines with the matching sample
count (bits 16-19 of the pipeline key), and a resolve into the one-sample
texture when that is next read (`off_rt_transition`). Four samples by default,
where the console uses two; `RSX_MSAA=2` matches the console, `RSX_MSAA=1`
turns it off. Seen on the menu scene: `[RT] slot 6 ... drawn with 4 samples`,
edges smooth, no `PSO FAIL`. Not handled: a pass that samples the scene's
depth buffer would now find the one-sample depth buffer empty (none seen),
and alpha-to-coverage is still the alpha test at one half. What follows was
written before this.

**Antialiasing** is not implemented. The scene target asks for it
(`[RT] new slot 6 off=0x1980000 1280x720 aa=3`, two samples a pixel;
`RT_NEWDBG=1` prints this), and the backend creates every target with one
sample. That is the jagged edges.

New switches: `SPURS_READY_GATE`, `SPURS_READY_LANES=0`,
`SPURS_LANE_STAGGER_MS`, `SPURS_KERN_STAT=1|<hex ea>[,<ea>]` (which workload
the kernel thread is in; a job manager header's list pointers and rows),
`SPURS_PM_ENDLOG=<wid>`, `SPU_DMA_HALT_DUMP=<reg>`, `SPU_DMA_HALT_EA=<hex>|@<lsa>`,
`SPU_DMA_REPEAT_MS`, `SPU_IRQTRACE_MIN=<hex pc>`, `GCM_BRDBG=<lo>,<hi>`,
`RT_NEWDBG=1`. `SPURS_PM_FLOW` now keeps the last 2,048 transfers.

## Phase 38 - A DualSense, and why a manufacturer never opens (2026-10-14)

Still BCUS98158. A save now exists (`gamedata/dev_hdd0`), so the title boots
straight to the main menu: no agreement and no "Confirmation". The timed
scripts that scroll the agreement no longer apply; from a boot with the save,
`PAD_HOLD=28000-28300:CROSS,34000-34300:CROSS,46000-46300:CROSS` wakes the
menu, enters Dealerships and picks the first manufacturer.

**Controllers other than Xbox ones.** cellPad's Windows backend was XInput
only, which does not see a DualSense. `SDL2.dll` is now loaded at run time
if it is beside the exe or on the path, and every controller is then read
through SDL (XInput is not polled, so nothing is seen twice). Nothing links
against SDL and no header is needed: the sixteen functions used are looked
up by name. Without the DLL the port runs as before. `scripts/get_sdl2.ps1`
fetches the DLL into `third_party/` (gitignored) and the build copies it
beside the exe. Checked here: `[cellPad] port 0: DualSense Wireless
Controller`. `PAD_NO_SDL=1` ignores the DLL. A `PAD_HOLD` script now drives
port 0 even with a controller connected; before, it ran only when port 0
was empty, so an unattended run depended on what was plugged in.

**The dealership.** The grid of manufacturers draws correctly
(`scratch/devrem/deal/inp_035.png`). Choosing one shows its logo on black
and stays there, at 31 frames a second, for as long as it is left (90 s).
This is the stop Phases 30 and 31 could not reach reliably; it now happens
every time, and three layers of it were found.

1. *The render thread waits for a job that is never run.* It spins in
   `func_00BA97B0` (Phase 31) on queue 3 of the structure at `0x0139C900`:
   the row at `+0x70` reads `0001 0000 FFFF ...`, one command published and
   lane 0's counter still 0 (`GT5P_PEEK=0x0139C960`). `[HOTREAD] spinning on
   0x0139A880` is this loop.
2. *The job manager had stopped.* Just before, `[pm-end] lane 0 ... pc=0x02F30
   lr=0x047B8`: the policy module's run ended somewhere other than its exit
   to the kernel, with a return address inside the job body at local-store
   `0x4000`, and no `[spurs-pm] poll` follows. `SPU_DUMP_OVL=scratch/ovl,0x4000`
   shows why: the module streams in a second job body, 75,008 bytes from
   `0x01376080`, where only the 3,344-byte one at `0x011A4100` was known, so
   the first body's lifted code ran over the second body's bytes. It is now
   in `wws_job_bodies` and lifted (606 functions). The dump equals the
   executable's bytes at that address.
3. *The new body hit an instruction the disassembler did not know.* `[spu]
   UNSUPPORTED .word at LS 0x10E9C`: the word is `0x06012142`, `orbi`. The
   lifter and the runtime both had `orbi`, `xorhi` and `xorbi`;
   `tools/spu_disasm.py` was missing all three from its table, so each
   became a `.word` that does nothing. Added. No other undecoded word is in
   the body's code (the 35 left are tables after it).

**Where it stops now.** `[spu-dma] img=1 pc=0x04560: 256 identical transfers
to ea=0x00000000 -- halting the SPU`, then `[pm-end] ... pc=0x04560
lr=0x14F48`. The body's code at `0x4554` to `0x462C` is a polling loop: a
transfer from an address in main memory, a wait for its tag, a compare of
what came back, a short delay on the decrementer, and round again. The
address it polls is 0. Not established: where that address comes from (a
field of the job's descriptor or of its input buffers that is empty here),
and whether the runtime's 256-transfer guard is ending a wait that would
otherwise have finished. That is the next measurement; `lr=0x14F48` names
the caller.

Re-lifting changed every sound job image as well (the three instructions
were missing there too). After it: four 20 s headless boots with 129 opens
and no overrun (`scratch/ab-p38/`), and on the menu 3,187 jobs a second at
59% of a core with no underrun and no silent block.

## Phase 37 - Menu images, shade, and the road (2026-10-14)

Still BCUS98158. Compared against screenshots of the same screens in RPCS3
(agreement, "Confirmation", main menu, the idle scene). Three faults in the
ps3recomp checkout accounted for nearly every difference; each has a switch
that undoes it. Captures: `scratch/devrem/r11/` (menu at 45 s, scene at 60 s
and 75 s), `r12/inp_040.png` ("Confirmation").

**1. Every image in the menus was dropped.** The log already said so:
`immediate-mode primitive 6 (4 vertices) is not drawn` and `primitive 7 (6
vertices)`. The title draws its 2D images (logo, "My Page", icons, button
prompts, dialog panels, the pointer, the GT loading mark) as four-vertex
strips and six-vertex fans between `BEGIN` and `END`, and Phase 25 routed
only quads. Lists, strips, fans and polygons now take the same route
(`IMM_QUADS_ONLY=1` for the old behaviour).

**2. sRGB was ignored on both sides of the fragment program.** With (1) the
scene was still black wherever it was in shade (`r2/frame_01/rt_01980000.png`).
The scene materials are short: a texture whose alpha is an exponent, times a
brightness constant; nothing in them could lift shade. Ruled out first, by
measurement:

- *Exposure.* `FPK_FP=7460741` over 120 s: the brightness constant rises
  from 0 and stops at 0.2207. It is a fade, not metering.
- *Pixel-count queries.* `GCM_REPORTDBG` (new): each frame enables the
  pixel count and zcull statistics, clears them, disables them and reads
  five reports with no draw in between. Nothing is measured by them.
- *The last display pass* (`0x057B6481`): its constants are a per-channel
  power of 1.25, 1.3 and 1.4, which darkens.

`RSX_METHHIST=<n>` (new) prints every method the title sends with a count
and its first values. Two registers nothing read: bits 20 to 22 of
`SET_TEXTURE_ADDRESS` (decode sRGB to linear on read; `0x60730303` on the
units that sample render targets) and method `0x1FEC`, values 0 and 1,
9,911 times. With `0x1FEC` taken as `SET_SHADER_PACKER`
(`cellGcmSetFragmentProgramGammaEnable`: encode linear to sRGB on write),
the capture manifest, which now prints both per draw (`gam=`, `sw=`), pairs
exactly: every scene draw and every post-processing pass that reads a
target through a decoding unit writes with the encode on, and the straight
copies have neither. Both are now done in the generated shader (decode on
the filtered sample, encode on each output), keyed with the pipeline.
`RSX_NO_GAMMA=1` ignores both.

A wrong turn on the way, recorded because the symptom was instructive:
`0x1D7C` also toggles 0 and 1 around the scene, and was tried first. It is
the antialiasing control (`0xFFFF0000 | enable`), and treating it as the
encode made the manifest pair *wrongly* (decode on passes with no encode)
and the picture nearly black (`r7/`).

**3. TEX8 and TEX9 were zero.** After (2) the road, a hanging sign and one
building were still black (`r10/inp_075.png`). Their programs
(`0x07460841`, `0x07460F01`) decompiled with `float4(0,0,0,0)` where an
input should be: the decompiler knew fragment inputs up to TEX7. TEX8 is
vertex output register 15 and TEX9 shares register 6 with the point size;
both are now passed. The fragment side declares them only in a program that
reads them, so programs that do not still link against the backend's
fixed vertex shaders.

**Result.** The idle scene and the menu match the RPCS3 screenshots in
content: road, shaded buildings, signs, sky, all menu images. No `PSO FAIL`
in any run. Four 20 s headless boots: 129 opens each, no arena overrun
(`scratch/ab-p37/`).

**Still different, measured, cause not found.** The 2D layer is dimmer than
RPCS3's. Brightest pixel of the same element, RPCS3 then here: "Cr.35,000"
255 / 160, "Dealerships" 255 / 189, the logo 232 / 132, "2P Battle" 164 /
90, the copyright line 113 / 62, the "Confirmation" panel about 61 / 28.
The large "Welcome" text is 255 in both. The values here are the same in
captures from before this phase (`final/inp_050.png`), so it is not the
sRGB work. Roughly a factor of 0.55 to 0.63 on everything but large text.
Hypothesis, not tested: the title rasterises its 2D shapes into the stencil
atlas at twice their size and averages four samples per pixel
(`0x0507F0C1` sums four taps), and something in where those taps land, or
in how they are filtered, loses coverage on thin shapes.

**Not looked at.** RPCS3's first screenshot has the sky blown out to white
where this build shows blue sky and cloud from the same place; its second
shows blue sky too, so this may be the moment in the fade or the bloom
passes (the bloom scale of Phase 34 is still unverified). Fragment programs
that sample units 4 and up get nothing (the backend binds four units);
`0x07460841` samples 11, 12 and 13. The scene still takes until about 70 s
to reach full brightness, which is the title's own fade (see above), not
checked against RPCS3's timing.

### Later the same day: holes in the archway, a square round a tree

Two more differences from RPCS3, both reported from the menu's background,
and both fixed (`scratch/devrem/r17/inp_045.png`, `inp_075.png`).

**4. Strips lost two triangles at every batch seam.** The archway had
quad-shaped holes with sky and buildings showing through. The scenery is
indexed triangle strips sent 256 indices at a time (`DRAW_INDEX_ARRAY
prim=6 first=0 count=256`, `first=256 count=256`, ... inside one
`BEGIN`/`END`), and each batch was assembled as a strip of its own, so the
two triangles spanning each seam were never made. The run now carries over
between batches of one `BEGIN`/`END`. The same applies to non-indexed
strips, fans and polygons: the title's 2D shapes are polygons split the
same way (`DRAW_ARRAYS prim=10 first=0 count=107`, `first=107 count=92`),
and a later batch pivoted on its own first vertex instead of the
polygon's. `STRIP_NOCONT=1` for the old assembly.

**5. The alpha test did nothing, and alpha-to-coverage was not known.** A
sky-coloured rectangle surrounded the tree at the end of the street. The
tree is drawn blended, with depth writes, and with alpha-to-coverage on
(`0x1D7C` = `0xFFFF0011`: the antialiasing control's bit 4) in place of an
alpha test; the title never enables the alpha test itself (`0x0304` is
always 0 in the method histogram). Here every pixel of its rectangle went
into the depth buffer, and what was drawn behind it afterwards was cut
out. Two parts: alpha-to-coverage is stood in for by a test at one half
(`RSX_NO_A2C=1`), and the test is now actually made. The per-draw constant
`rsx_alphatest` was uploaded all along, but the decompiler adopted in this
tree emits nothing that reads it, so no title's alpha test has discarded
anything since that decompiler came in. A discard is now added to every
generated program (`FP_NO_ATEST=1`).

**The dim 2D layer: narrowed, not solved.** Ruled out by measurement:

- *Coverage.* The stencil atlas is binary (0 or 255 in every texel,
  `r16/frame_00/rt_01100000.bmp`), unit 0 is point-sampled, and glyphs are
  in the atlas at twice their screen size, so the four taps of the cover
  program form an exact 2x2 box. The hypothesis recorded above is wrong.
- *Vertex colour order.* Reading four-byte colours last byte first tints
  the text (`r15/`); memory order is right.
- *The scene.* A patch of road seen through the arch averages (28,25,20)
  here and (25,21,15) in RPCS3. Only the 2D layer is dim.

What the title sends (`VP_POSDBG=120000`, last frames of `r19/`): the
"2P Battle" label is colour 0.706 at alpha 0.498, drawn once a frame by
`0x0507F3C1`, whose output colour is the vertex colour unchanged. This
build shows 90, which is 0.706 x 0.5 x 255. RPCS3 shows 164. "Dealerships"
is 0.706 at alpha 1: 186 here, 255 there. So this build draws what the
vertex data and the blend state (source alpha, one minus source alpha) say,
and RPCS3 shows more than that state can produce in one draw. Across
elements RPCS3 is about 1.8 times this build until it clips. Not explained.
One fit, untested: an sRGB encode of both the colour and the alpha (0.706
to 0.86, 0.5 to 0.735, product 0.63, against RPCS3's 0.643).

**6. Samplers ignored the title's filter and wrap settings.** Texture unit
0 was always point-sampled and clamped and units 1 to 3 always linear and
repeating (the static samplers of the vertex-program root signature). The
scene's main texture is on unit 0, which the title sets to linear with
linear mip and repeat (`[SAMP] unit 0 filter 0x02062000 address
0x10730121`, from the new `RSX_SAMPDBG=1`), so scenery was drawn
unfiltered. Each unit now gets the filter and wrap the title asked for,
from a bank of twelve static samplers in registers s4 to s15: three
filters by four wrap pairs. Twelve because a `ps_5_0` shader has sixteen
sampler registers (a first version put a bank of 64 at s16 and every
program failed to compile with X4509) and the backend binds four texture
units. Mirror is drawn as repeat and border as clamp. `RSX_SAMP_FIXED=1`
for the old samplers. The stencil atlas keeps point sampling because the
title asks for it (`filter 0x01012000`). Roofs and brickwork are visibly
smoother (`r20/inp_075.png`); the 2D layer is unchanged.

### Running it by hand

`build\gt5p.exe` exited at once unless started from the project root,
because the game is found by paths relative to the working directory. It
now looks for `input\EMAIN.ELF` upwards from its own folder when the
working directory does not have it (`GT5P_ROOT` names the folder outright),
and shows a message box instead of vanishing when the game is not found.
Started with a console for output, it turns verbose logging off unless
`PS3_VERBOSE` is set. Closing the window now ends the process: nothing in
a recompiled title acted on the close, and the threads ran on without a
window. `play.cmd` in the project root does the same with the log sent to
`scratch\play.out` and `.err`, and prints the keyboard mapping. Checked:
started with `build\` and with `%TEMP%` as working directory, both reach
the agreement screen; closing the window exits with code 0. Four 20 s
headless boots after all of this: 129 opens each, no overrun
(`scratch/ab-p37c/`).

`scratch/menu.ps1` is 8 s faster: the agreement scrolls to its end in under
5 s, so DOWN is held 13 s to 19 s instead of 16 s to 27 s, and CROSS is
pressed every 3 s.

## Phase 36 - The remaining sound dropouts (2026-10-14)

Still BCUS98158. Phase 35 left the menu music with 0 to 1.7% of its blocks
empty, arriving sixteen at a time. Three causes, found in this order with
two new logs: `AUDIO_GAPDBG=1` prints each run of empty blocks with the
ring at that moment, and `AUDIO_LEADDBG=1` prints where the title writes
relative to the index it is shown.

**1. The test launcher.** The gaps came every 5.1 s. `scratch/inp.ps1` set
`GT5P_MAINSTACK=5`, which suspends guest threads every 5 s to print the
main thread's call chain, and the sound stops for as long. Removed from the
script's defaults. Anyone launching through that script has been hearing an
85 ms dropout every 5 s that the port itself does not have.

**2. A reader at a fixed distance from the index.** `AUDIO_LEADDBG` on the
menu, five seconds of writes by distance ahead of the published read index
(0 is the block about to be consumed, 15 is one behind it):

    468 0 0 0 0 0 0 0 0 0 0 0 36 0 12 395

The title writes one block per consumed-block event at a position it
counts for itself: the published index or one behind, never ahead. Held up
for a few blocks, it writes them afterwards, in order, and stays that far
behind until it next resynchronises. Phase 35's reader, two blocks behind
the index, then found nothing for a whole lap of the 16-block ring (85 ms
of silence) and played everything a lap late after that; `[audio-gap]`
showed the ring empty at the start of such a gap with no stall at that
moment. The mixer now follows the data: it consumes written blocks in the
order they were written, starts only when a cushion has built up
(`AUDIO_JITTER=<blocks>`, default 8, about 43 ms), and waits for the
cushion again if it runs dry. The index shown to the title still advances
one block per period. "Written" is "not all zero", which a consumed block
is because the mixer clears it.

**3. No headroom to catch up.** With (2) in, the gaps that were left lined
up with stalls of the title's audio thread (`SPURS_JG_GAPDBG=<ms>` prints a
guard notified later than that after its previous notify; the notifier is
`sgx-audio-thr`, priority 214). After a 25 ms stall the title owes five
blocks, and a job walker at 90% of a core produces them barely faster than
they are consumed. So the walker was made cheaper again:

| Change | ms per job | walker busy |
| --- | --- | --- |
| Phase 35's end | 0.28 | 89% |
| forward transfers in job images made direct tail calls; fast path in the dispatch step | 0.24 | 78% |
| `rotqby`, `rotqbyi`, `shlqbyi` as one `pshufb` each | 0.18 | 58% |

- **Forward chaining.** The lifter ends every block by naming the next in
  `g_spu_trampoline_fn` and returning to a dispatch loop, including when
  the next block is the code that follows. The mixer's per-sample filter
  loop (`j65DD2F53`, `0x1E8` to `0x220`) is three such blocks.
  `scripts/lift_spu_jobs.py` now rewrites a transfer to a later block of
  the same image as a `musttail` call (`--chain` applies it to what is
  already generated). Backward transfers still go through the dispatcher,
  so every loop passes the point where interrupts and halts are noticed.
  Job images only; the policy module and the bodies it streams are left as
  lifted.
- **Dispatch step.** `spu_task_launch_check` returns early when no
  diagnostic switch is set and the pc is not 0 (`SPU_SLOW_STEP=1`).
- **Byte helpers.** Checked against their loop forms over 200,000 random
  inputs (`scratch/test_spu_helpers.c`), with `spu_shufb` as well.

Two smaller changes for the stalls themselves: the mixer thread runs at
time-critical priority (`AUDIO_MIX_NORMAL_PRIO=1`), and guest priorities
below 220, not 200, map to the host's HIGHEST band, which puts the audio
thread above the group of worker threads at 223 to 256
(`PS3_PPU_PRIO_BAND=<n>`). Stalls of 14 ms or more in a 150 s run: 212 and
39 before, 49 and 21 with the band, 9 with both. They still happen and why
is not found; the mixer's own ticks are never more than 8 ms apart
(`AUDIO_RATE=1` now prints that), so the delay is on the title's side.

**Result.** Seven menu runs of 120 to 150 s after (2) and the walker changes:
one underrun in the first, none in the other six. Then, with the cushion at
8 and everything above, a 330 s run on the menu (`scratch/devrem/soak/`):
no underrun, no `[audio-gap]` line, and 64 of 65 five-second windows with
no empty block; the other is the window in which the sound first starts.
The walker ran 3,186 jobs a second at 0.18 ms each, 58% busy. Eight 20 s
headless boots: 129 opens each, no arena overrun (`scratch/ab-p36/`).

Not done: nobody has listened to it; it is measured on the menu only, and a
race has more voices; and the cushion adds about 43 ms of latency on top of
the device's.

## Phase 35 - The one-frame-a-second menu, and the stuttering sound (2026-10-14)

Still BCUS98158. Two separate faults, both in the ps3recomp checkout.

### The menu at one frame a second

Phase 34 left this with a hypothesis about the title outrunning the
backend. It was wrong. With `GT5P_PRESENT_PROF=1 GCM_FLIPCOUNT=1` on a slow
boot (`scratch/devrem/fs5/`): the title flips 60 times a second, the present
thread calls the backend's present 62 times a second, and those calls take
0.00 s out of every 5 s. They return without drawing.

`rsx_d3d12_backend_present` starts with `if (s_clear_presents > 0) return;`.
The backend has a second way to end a frame, on a clear of the display
(`d3d12_clear`), and once that has presented a single frame the flip-driven
present is switched off for the rest of the run. This title clears the
display a few times on the way into the main menu and then never again: the
menu redraws the whole screen each frame. Whether one of those clears
counts as a frame boundary depends on the order a clear and a flip arrive
in, which is the race. When one does, nothing presents until the record
list reaches its 2,048 limit, which is the "ten guest frames in one batch"
of Phase 34. Each guest frame in that batch is the ordinary 221-draw menu
frame; the menu had been running normally underneath.

Now the flip-driven present comes back once four flips have passed without
a clear-driven present (`RSX_CLEAR_PRESENT_STICKY=1` for the old
behaviour). Result: 8 of 8 driven boots reach the menu at 31 frames a
second (`cp1` to `cp8`), against 18 slow in 31 before. With the switch
set on the final build, 1 of 5 boots was slow again (`st1` to `st5`): the
old behaviour still produces it, though less often than the 18 in 31, and
the later sound changes moved the timing of that race, so the two rates
are not comparable.

Six 20 s headless boots with everything in this phase: 129 opens each, no
arena overrun (`scratch/ab-p35/`).

The user's observation that the music differs in the slow state is not
explained by this and was not looked into; the title may simply pick its
menu music at random.

### The stuttering sound

`AUDIO_RATE=1` counts the blocks the mixer plays that are entirely empty.
On the menu, with music playing: 40 to 49% (`au1/`). The mixer was on time
(187.5 blocks a second, none dropped); the title was supplying about half
the blocks. Per-thread CPU (`scratch/cpu.ps1`): main thread 93%, the job
chain walker `spurs-jc` 81%, the title's own audio thread 1%.

The sound mixer is the job chain at `0x20046600` (Phase 33's chain). New
`SPURS_JC_STATS=1`: 1,700 jobs a second at 0.47 ms each, the walker 82%
busy, where full rate is about 3,190 (17 jobs for each 5.33 ms block). A
new sampler, `SPURS_JC_SAMPLE=<chain>`, prints where the walker's host
thread is once a millisecond; `scratch/maplook.py` resolves it against a
linker map (`-DCMAKE_EXE_LINKER_FLAGS=/MAP:gt5p.map`). What it showed, and
what was done, in the order measured:

| Change | ms per job | jobs/s | empty blocks |
| --- | --- | --- | --- |
| start | 0.47 | 1,700 | 40 to 49% |
| job staging built in place; fingerprint remembered | 0.43 | 1,900 | 40% |
| SSE4.1 for lifted SPU code; context kept per thread | 0.37 | 2,100 | 31 to 34% |
| `fmaf` computed in double | 0.30 | 2,500 | 20 to 22% |
| walker woken by the guard notify | 0.28 | 3,190 | 2 to 5% |
| mixer reads two blocks behind | 0.28 | 3,190 | 0 to 1.7% |

- **Staging.** Each job allocated and zeroed a 256 KB local store, copied
  it into the context, and copied it out again afterwards, and the whole
  job binary was hashed byte by byte to find its lifted code. The working
  set is now built in the context, the copy-out happens only when the job
  posted a mailbox value (its one reader is the printf service), and the
  hash is remembered per binary.
- **`spu_shufb`** was 16% of the walker's samples: its vector form is
  behind `__SSE4_1__`, which nothing defined, so the byte loop ran.
  `CMakeLists.txt` now compiles the lifted SPU sources with `-msse4.1`.
- **Context clearing.** One context per host thread, kept between jobs,
  clearing only the span the previous job was given
  (`SPURS_JOB_FULLCLEAR=1` clears all of it).
- **`fmaf`.** Without `-mfma` the compiler calls the C library's software
  `fmaf`, four times per SPU multiply-add. Half the walker's samples were
  outside the executable, most of them this. Now a multiply and add in
  double, rounded once (`SPU_FMA_LIBM` to compile the old form). Not
  bit-exact with a fused result in the rare case where the double sum is
  exactly halfway between two floats.
- **Guard wake-up.** The walker waited for its guard with `Sleep(1)`,
  which returns one to two milliseconds late, once per audio block. It now
  waits on an event the notify sets (`SPURS_JG_SLEEP=1`).
- **Read lag.** With the job rate at full the ring map (`AUDIO_PEAK=1`)
  still showed data one and two blocks behind the reader: blocks finished
  just too late, read as silence, then heard a ring lap later. The mixer
  now reads `AUDIO_READ_LAG` blocks (default 2, about 11 ms) behind the
  index it publishes.

Also changed: the mixer paces one block per 5.33 ms on the clock with an
80 ms device buffer instead of two blocks per 10 ms device period
(`AUDIO_PACE_DEVICE=1`). That was the first theory and made no measurable
difference by itself (45% before and after); it is kept because the bursts
were real. The walker thread runs at above-normal priority
(`SPURS_JC_NORMAL_PRIO=1`).

Left: the walker is at about 90% of a core on the menu, so anything with
more voices than the menu will fall behind again. The per-step cost of the
SPU dispatch loop (`spu_task_launch_check` and what it calls, about a
sixth of the walker's time) is untouched. The remaining empty blocks come
sixteen at a time, one ring's worth, a few seconds apart; not investigated.
Nobody has listened to the result yet; these are counts, not ears. The
menu itself runs at 31 frames a second with the main thread at 93% of a
core, where the console runs it at 60.

## Phase 34 - The scene shows behind the menu (2026-10-14)

Still BCUS98158. Phase 33 ended with the menu's 3D scene drawn into its own
target and a black window. The window now shows the scene: a street of
half-timbered houses with flags and sky, captioned "Altstadt, Ahrweiler"
(`scratch/devrem/final/inp_075.png`; `m12/inp_060.png` earlier in the same
fade). Some surfaces are black; see the end. All changes are in the
ps3recomp checkout
(`libs/video/rsx_d3d12_backend.c`, `rsx_commands.*`, `cellGcmSys.c`,
`libs/input/cellPad.c`), and each has a switch that restores the old
behaviour.

The plan going in was "give the later passes the screen and the depth buffer
as textures". Both were needed, and neither was what kept the window black.
Five other faults were, found one at a time with a new
`FRAME_CUT_OP=<n>[,min]`, which ends each frame of at least `min` draws
after record `n` so that a capture shows the display as that record left it.

**1. Targets were remade several times a frame.** `[RT] recreate` showed
`0x2880000` going 2048x1436, 511, 255, 127 rows: the title draws to one
surface under several clip rectangles, and the backend sized the target
from the clip of each draw, discarding the contents each time. A target now
only grows (`RT_NO_GROW=1` for the old way).

**2. A texture can point inside a target.** The title keeps a whole mip
chain in one surface and binds each level by its own address (`0x2E20000`
is row 720 of `0x2880000`; the six `256x511` cube-face surfaces at
`0x4D00000` are the same idea). The backend matched textures to targets by
exact offset only. It now also finds the target whose memory contains the
address, using the surface pitch and antialias mode recorded with each
draw, and gives the unit a scale and an origin through `rsx_texscale`
(`RT_NO_TEXSCALE=1`; `RT_TEXDBG=<n>` prints each resolution once). The same
scale handles the 2x-antialiased scene surface (`SET_SURFACE_FORMAT`
`0x3148`, declared 2560 wide as a texture, 1280 wide as a target: scale
1.0) and the display.

**3. The display as a texture.** `fp=0x057B5501`, `0x057B5881` and
`0x057B6481` sample a display buffer (offset 0 or `0x880000`, declared
1920x1080). The backbuffer is snapshotted before such a draw when it has
changed since the last snapshot. Not verified: whether the scale chosen for
a normalised 1920x1080 texture over the 1280x720 image (1.5) is right; the
passes that use it are the bloom ones, and their result has not been looked
at on its own.

**4. The depth buffer as a texture.** Confirmed by measurement that
`0x2100000` is a depth surface: `[RTOFF]` prints it as `zeta` for the scene
target. The backend has one shared depth buffer that it clears at every
change of target, so it is copied to a typeless texture when the draws
that used it are over, and `fp=0x057B4D01` reads the copy. The title reads
depth as an A8R8G8B8 texture (crossbar `0xAA93`), so the generated shader
rebuilds the three depth bytes from the value. Two mistakes in the first
version, both measured: the copy was taken after a display draw that had
the same depth surface bound (so the pass read the display's depth), and
the size was taken from `0x2880000`, which is drawn with that depth surface
bound but does not test depth (`[RTTEX] depth surface 0x2100000 drawn with
target 0x2880000 2048x1436 aa=0`). Only draws that test depth count now,
and the table of which target a depth surface belongs to is kept across
frames; after both changes the same line reads `target 0x1980000 1280x720
aa=3` and the blur follows depth. Which of the two changes was needed is
not separated.

**5. Immediate-mode vertices kept only their position.** With all of the
above the display was still black after the scene's first copy to it.
`VP_ATTRS` on that pass (`fp=0x0FFFFD41`) showed the scene's vertex arrays
still enabled (`a0` three floats, `a2` type 6): the quad is not drawn from
arrays. Phase 25 added immediate mode for positions only, and every vertex
took the other attribute registers as they stood at `END`, so a whole quad
had one texture coordinate and sampled one texel, the black corner of the
scene. Each emitted vertex now carries all sixteen registers
(`IMM_OLD=1`). `SET_VERTEX_DATA3F_M`, `4UB_M` and attribute 0 through
`4F_M` are handled as well. Still dropped, and now reported once each:
immediate-mode triangle strips (4 vertices) and fans (6 vertices).

**6. Fragment programs returned the wrong register.** After (5) the window
was white. The decompiler was called with no shader-control word and
guessed the output register; for these programs it returned `r0` where the
result is in `h0`. `fp=0x057B5881` computes display plus three bloom
levels into `h0` and the shader returned only its last bloom sample;
`0x057B4D01` returned an unnormalised sum of six samples. The title's
control word is `0x2008400` (`[RSXSC]`, bit `0x40` clear: 16-bit exports,
`h0`), the draw record already carried that bit, and the pipeline key
already included it. It is now passed (`FP_CTRL_AUTO=1` to guess again).
This is also why the road in Phase 33's scene capture was plain white: it
was a raw texture sample, not the program's result.

**7. Fragment constants were frozen at first compile.** With the right
register the scene target went black (`m2/`: 0 of 3,600 sampled pixels
non-black). The scene materials end in a multiply by an inline constant
that the title patches every frame through `cellGcmInlineTransfer`
(`[GCM2D] inline write`), a brightness that starts at 0 when the menu fades
in (`FPK_FP=7460741` prints it: 0, then `7.5e-06`, rising to 0.22 by 70 s).
The pipeline cache is keyed on the program's code without its constants and
the constants are uploaded per draw, but the decompiler adopted in this
tree prints them into the shader as numbers unless its buffered form is
asked for. So every program kept the values it was first compiled with,
here a brightness of 0. The buffered form is now used, with one
declaration for the per-draw slot (`FP_CONSTBUF=0` for literals).

**8. Mip levels stacked in one surface.** With (1) to (7) the scene showed,
with several offset copies of itself over it (`m7/inp_070.png`).
`0x057B4D01` is a depth-of-field pass: it samples the blurred surface with
`SampleLevel` at a level computed from depth, and the backend's target has
one level. `SampleLevel` on such a unit now goes to a small function that
picks the level's rectangle in the surface and blends two levels. Related:
the passes that build each level sample the surface they are drawing to,
which D3D12 does not allow; they now sample a copy taken just before the
draw (`RT_NO_SELFCOPY=1`).

**What is still wrong with the picture.** The scene takes about 30 s to
reach full brightness after the menu appears (the constant in (7) is 0.22
at 70 s; at 60 s most of the picture is still near black, at 75 s it is
lit). Whether the real title fades that slowly is not known; one
hypothesis is that it reads back the 1x1 level of the blur surface to set
exposure, and guest memory behind a target is never written. Once lit,
some surfaces stay black, for example the building on the right of
`final/inp_075.png`. Not investigated; several scene programs sample cube
maps whose faces are built in the `0x4D00000` surfaces, which is one place
to look. The D3D12 debug layer was on for two boots that reached only the
slow state below and printed nothing; the scene passes have not been run
under it.

Four 20 s headless boots with all of this: 129 opens each, no arena
overrun (`scratch/ab-p34/`).

**A menu that comes up at one frame a second.** After "Confirmation" about
half of all boots show only "Cr.35,000" at about 1 frame a second with the
title bar at `draws: 2048`, and stay that way to the end of the run (up to
95 s). Measured:

- The capture of such a frame (`n2/frame_00/manifest.txt`) holds ten guest
  frames in one batch (ten clears of the scene target, 80 draws to each
  cube face where a frame has 8) and no draw to the scene target. 2048 is
  the backend's record limit, so more than that was submitted.
- The title calls flip more often in this state, not less: 4,966
  `SetPrepareFlip` lines in a 98 s run against about 3,500 in a good one.
- It is not the FIFO's catch-up path (one flip per drain is abandoned past
  64 KB of backlog): `GCM_CATCHUP_DBG=1` printed nothing in two such boots.
- It is not today's texture work: 5 of 6 boots with `RT_NO_TEXSCALE=1`, 1
  of 4 with `RT_NO_SELFCOPY=1`.
- It is not new today: 1 of 4 boots of yesterday's saved build
  (`scratch/baseline/gt5p_fix_t86.exe`) ended at `draws: 2048` too.
  Phase 33's note listing 2048 as a dealership draw count was this.
- Counted over today's driven boots after the script was fixed, with mixed
  switches: 18 slow, 13 good. In the four old-style runs where the time of
  the accepted press can be read, the two slow ones were the two whose
  "Confirmation" went away latest (after 45 s, against 37 s and 41 s).

Hypothesis, not tested: in this state the title is still loading the scene
and submits cheap frames at 60 a second without waiting; the backend cannot
draw them that fast, the frames pile into one batch, each present then
takes most of a second, and the present thread, which also delivers the
vblank and flip ticks and bounds its catch-up at 100 ms, hands the title a
fraction of the ticks it is owed. If the loader counts those, the load
stretches by the same factor. What decides which way a boot goes is not
known.

**A test script that stays on the menu.** `PAD_HOLD` presses are timed, and
the load behind "Confirmation" varies by seconds, so a script either stuck
on the dialog or pressed Cross once more and left for the dealership. Every
"black menu" capture before `m7` was a menu still fading in, about to be
left. `PAD_HOLD_STOP_DRAWS=<ms>,<m>` makes the scripted pad let go once a
frame of under `m` draws seen after `ms` (the dialog) is replaced by a
different draw count. `scratch/menu.ps1 <dir>` uses it. Draw counts seen on
the menu: 221 on its first frame, 381 with the options up, 198 to 247 once
only the caption is left.

## Phase 33 - The bad boot: two job-chain walkers answer one request (2026-10-13)

Still BCUS98158. This finds the cause of the Phase 18 / 22 / 32 bad boot. The
"allocation retried for ever" and "runaway sound-bank fixup" signatures are
one fault, and it is in ps3recomp's job-chain code, not in the heap.

**The chain of events, each link measured.**

1. *The free list is damaged by a buffer overrun.* During sound start-up the
   title sizes a block with a dry run and then fills it: `func_007F34F0` is
   called twice by `func_007F39C0`, first with a bump arena whose base is 0,
   then with the block it allocated for the size the first call reported.
   With `GT5P_ARENA_TRACE=1`, every bad boot in `scratch/heap-root-20261013-*`
   and in the runs below has exactly one pair where the fill pass used more
   than the dry run measured (most often `0x58` measured, `0x1F4` filled);
   no good boot has one. The words written past the block are the ones Phase
   32's evidence found in the free-list node: `0x4240A3D7` and `0xC2C0A3D7`
   are the floats 48.16 and -96.32.
2. *The two passes disagree because a text query came back empty once.*
   `func_007F2F08` asks a callback for a parameter description, counts its
   lines with `func_007D3580`, and reserves 20 bytes a line. A wrapper on
   `func_007D3580` (`scratch/instrument_txt.py`, `GT5P_TXT_TRACE=1`) shows the
   text: `outlevel, F:-96.32:48.16, 0.0, Out Level, dB ...`, 13 lines. In a
   bad boot the dry run gets an empty string (count 0) and the fill pass gets
   all 13. Only the main thread makes these calls; it is not a race on the
   shared text buffer at `[0x015F3710 + 0xB8]`.
3. *The text comes from an SPU job.* The callback is `func_007F6000`; selector
   7 sends command `0x2100` to a sound-effect module through
   `func_007F5E48`, which queues one job on the "soc-job" SPURS job chain,
   notifies the chain's guard (`0x20046780`) and waits in
   `sys_event_queue_receive` for the job's completion event
   (`func_007FE9E0`).
4. *The wait returned before the job ran.* With `SPURS_JG_TRACE=1` (new, in
   `cellSpurs.c`) the failing query reads `notify`, then the title's empty
   read, and only then `job begin`. The event it woke on was a stale one.
5. *Stale events come from jobs run twice.* The same trace shows `job begin`
   twice for one notify, and two `open guard` lines for one credit.
6. *Jobs run twice because the chain has more than one walker.* The title
   creates the chain, runs it, shuts it down, joins it and creates it again
   at the same address, 11 to 26 times in a 20 s boot. `cellSpursShutdownJobChain`
   cleared the chain's `running` flag and left the host thread walking it
   parked on the guard, where it stays for up to 20 s. The next
   `cellSpursRunJobChain` saw `running == 0` and started another. The guard's
   credit was taken with a plain read and subtract, so two walkers could both
   pass on one notify. Which query that happens on is timing, which is why
   the fault moved about and why priority scheduling changed its rate.

**The fix** (local ps3recomp, `libs/spurs/cellSpurs.c`): Shutdown now sets a
stop request that the walker checks in its command loop and while parked on a
guard, and the walker itself clears `running` when it leaves; Run waits
briefly for a stopping walker instead of dropping the run; the guard credit is
taken by compare-and-swap. `SPURS_JC_OLD_SHUTDOWN=1` restores the old
Shutdown.

**A/B.** Same source otherwise, executables kept as
`scratch/baseline/gt5p_prefix_t85.exe` and `gt5p_fix_t86.exe`, 20 s headless
boots with `GT5P_ARENA_TRACE=1 SPURS_JG_TRACE=1`, run by `scratch/ab.py`,
which counts overruns from the arena trace:

| | boots | with an overrun | reached 128+ `GT.VOL` opens |
| --- | --- | --- | --- |
| before the fix | 12 | 4 | 8 |
| after the fix | 24 | 0 | 24 |

All 24 fixed boots ended at the normal main wait (`lr=0x00B391F4`) with 129
opens. The trace also counts jobs begun while another was still running:
22 to 1,309 a boot before the fix, none after (the 4 to 7 the count still
reports are `job end` lines printed onto the tail of another thread's line).
Logs: `scratch/ab-ctl-1/`, `scratch/ab-fix-1/`, `scratch/ab-fix-2/`. Earlier
traced batches on the unfixed build (`scratch/heap-txt-a/`, `-c/`, `-d/`) had
3 of 6, 4 of 4 and 2 of 6 with an overrun. The four control overruns carried
three different `bootcheck` readings: two "runaway sound-bank fixup", one
"allocation retried for ever", and one that `bootcheck` did not flag at all
(`main_lr=0x00AFD560`, 94 opens). `bootcheck` under-counts this fault; the
arena trace is the reliable test for it.

**The upstream v0.14.0 taskset change is not involved.** Commit `50c4b36`
removes three host-side writes into the guest `CellSpursTaskset`, at `+0x00`
(`initialized`, in `cellSpursDestroyTaskset`), `+0x04` (`taskCount`, in
`cellSpursCreateTask`) and `+0x08` (`shutdownRequested`, in
`cellSpursShutdownTaskset`). All three land inside the taskset the title
passed, so they cannot reach allocator metadata unless the pointer is wrong,
and this title never calls them: `cellSpursCreateTaskset` prints on every call
and there is no such line in any log here (12 control boots, the traced
batches, `scratch/boot.out`). The sound service uses job chains, not tasksets.
v0.14.0's diff to `cellSpurs.c` does not touch the job-chain or guard code, so
it does not contain this fix either. Because the removed writes are
unreachable, no separate v0.14.0 build was made; the checkout stays on
`5244db9` plus local changes.

**Not established.**

- Whether real hardware can also deliver a stale event here. The reading
  above only needs one walker per chain, which is what a real chain has.
- A crash seen once on the unfixed build during this work
  (`rc=0xC00000FD`, stack overflow, `scratch/heap-txt-d/run1.err`, with an
  overrun in the same run). Assumed to be downstream of the overrun; not
  checked.
- The windowed "dark blue, `draws: 0`" boot (Phase 28) is assumed to be this
  fault. No windowed boots were run with the fix.
- 20 s boots only. Longer runs, and the menu and dealership, are untested
  with the fix; duplicate job runs happened throughout a boot before it, so
  later behaviour may change too.

Tools left in place: `SPURS_JG_TRACE=1`; `scratch/instrument_txt.py` (wraps
`func_007D3580` in `generated/`, so it is lost on a re-lift);
`scratch/ab.py <exe> <outdir> <runs> <secs>`.

### The device removal at the menu and dealership (2026-10-13)

Scripted windowed runs (`scratch/auto.ps1 x -NoBuild -Secs 80`, which holds
`PAD_HOLD` through the agreement and presses Cross every 4 s), on the
executable that already has the Phase 33 fix. Logs and captures are in
`scratch/devrem/`.

**Hypothesis under test:** a render target recreated while the frame's
command list is open is released at once, and the list then runs on freed
resources.

**Step 1, before any change.**

- With `D3D12_DBG=1 D3D12_IQ=1` (`s1.err`) the device was not removed in that
  run, no target was recreated, and there is no message 921. What the debug
  layer did report, 67 times in the first 80 messages, is error 615:
  `DrawInstanced: The depth stencil format does not match that specified by
  the current pipeline state ... (pipeline state = D24_UNORM_S8_UINT, DSV
  ID3D12Resource* = 0x0000000000000000)`. That is Phase 30's change of
  binding no depth buffer beside a colour target that is not window-sized:
  the pipeline still declared one.
- Three plain runs (`base1` to `base3.err`): one removal, two of the
  4-second-frame ending. Only the removal run recreated a target, and it did
  so three times inside one frame, straight before the report:
  `[RT] recreate slot 8 off=0x2880000 2048x1436 fmt=28 -> 2048x511`,
  `-> 2048x255`, `-> 2048x127`, then `[D3D12] DEVICE REMOVED (0x887A0006)`.
  One surface offset is used at four heights in a frame, which looks like a
  downsample chain. So the hypothesis fits the run that hung, and the debug
  run could not show 921 because it never recreated anything.

**Step 2, two changes** in ps3recomp `libs/video/rsx_d3d12_backend.c`, on
branch `gt5p/offrt-deferred-release` of the local checkout (uncommitted there,
beside the other local changes; `patches/ps3recomp-5244db9-local.patch` is
refreshed):

- the supplied patch, applied by hand because the file differs locally:
  replaced targets and their upload buffers are parked and released after the
  next frame's `wait_for_gpu()`;
- bit 27 of the pipeline's stencil key now means "no depth buffer bound", and
  such a pipeline is built with `DSVFormat = UNKNOWN` and depth and stencil
  off (`PSO_DSV_ALWAYS=1` for the old pipeline). `D3D12_IQ` now prints at
  most four of each message id.

Results:

- debug layer on (`fix_iq.err`): no errors at all, only warnings 679 and 820;
- four plain dealership runs (`fix1` to `fix4.err`): three recreated the
  target (the 60-line print quota was used up, so at least 15 frames each)
  and none printed `DEVICE REMOVED`. Before the change the device was lost
  two frames after the first recreation. Stdout, where `wait_for_gpu STUCK`
  goes, was not kept for those four; it was for `menu2`, which recreated
  targets and has no `STUCK` or `removed=` line.
- The dealership now gets further: `fix1/inp_055.png` shows "Acura NSX '91",
  "Cr.35,000", "ACURA", "Showroom", "Event" on a solid bright green
  background. Before, the picture froze on the frame before this one.

**The hypothesis held for the removal. The freeze is not over.**

- Dealership: captures are byte-identical from 55 s to the end, the title
  bar stays at `FPS: 31.00 | draws: 167`, `PERF=120` stops printing, and
  scripted Right, Right, Left change nothing (`lr.err`, `lr/`). The log has
  the render thread spinning at `lr=0x00BAA9FC`, Phase 31's wait on the job
  manager's counters. Read as: the title stops issuing frames. Not checked:
  whether flips really stop, which needs a timestamped flip count.
- Main menu (Cross only until the menu is up, then Right at 54 s;
  `menu.err`, `menu2.err`): the menu does change, `menu/inp_055.png` has the
  row scrolled and the welcome text gone, with `FPS: 1.9`. Then the window
  stops answering by 60 s, in 2 runs of 2, with targets recreated and no
  removal or stuck-fence message in either stream. Cause not looked for.
- The other ending, a frame every 4 s at `draws: 2048`, is unchanged (2 of
  the 5 plain dealership runs after the change).

Not done, as asked: the size a persistent target should have when one
surface is drawn at four heights, and the green background.

### The main menu: window hang, 1.9 frames a second, and the black scene (2026-10-13)

Runs are scripted and windowed; logs and captures in `scratch/devrem/`
(`mh1` to `mh6`, `bg1`, `cut1` to `cut4`, `attrs`).

**"Window not responding" was the present thread, fixed** in
`src/gt5p_present.cpp`. `scratch/cpu.ps1` on the hung menu showed the
`present` thread at 99% CPU. Its loop replays missed 16 ms ticks, up to 240
at a time, before it pumps window messages; once a tick's work took longer
than 16 ms the backlog never cleared. The replay now stops after 100 ms.
`GT5P_PRESENT_PROF=1` prints where that thread's time goes every 5 s.

**1.9 frames a second was the vertex-shader lookup, fixed** in ps3recomp.
`GT5P_PRESENT_PROF` put all the time in the FIFO walk (`fifo 5.2s` of 5 s),
`RSX_PROF=1` (new, per-method times) put it in the draw methods at about
1.3 ms a draw, and `PERF` with two new timers put it in one call:
`[PERF] record: vs-lookup 5.03s | constants 0.03s`. The lookup hashed the
microcode store from the program's start to the end of the store, so a
program's hash changed whenever a neighbour in the store did, most draws
compiled a shader, and the 16-entry cache was evicted continuously (eviction
also renumbers the slots that draw records and the pipeline cache hold). The
hash now stops at the program's END instruction (`VP_HASH_ALL=1` for the old
extent) and the cache holds 256. After: `[VP] cache: 520000 lookups, 10
misses, 10 entries`, and the menu holds 23 to 25 frames a second after a
Right press where it had 1.9. The menu moves: `mh6/inp_060.png` has the
cursor on "Options". Failed programs are now remembered and reported, though
none failed here.

**"Stuck after Accept" in these runs was the script.** "Confirmation" takes
its OK only when the menu load has finished; a script whose last Cross is at
41 s stays there when the load ends later. Stuck and good runs both have 306
`GT.VOL` opens. `scratch/auto.ps1`, which keeps pressing, goes through.

**What a main-menu frame is** (`RTT_DUMP=2 RTT_DUMP_MIN=300`, `bg1.err`, 382
draws):

1. 48 draws building mip chains for six 128x128 surfaces at `0x4D00000`
   onward. Each level is drawn into the same surface lower down, with the
   level above bound as a texture by its address inside that surface.
2. A clear and about 150 draws into `0x1980000`, 1280x720: the 3D scene.
   Most are 762 vertices, which is a 256-index triangle strip.
3. One draw copying `0x1980000` to the display (`fp=0xFFFFD41`), one copying
   it into `0x2880000`, and ten more building that surface's mip chain the
   same way (this is the target Phase 33 saw recreated at four heights).
4. Full-screen passes to the display and through `0x57B6B00`, `0x5836B00`,
   `0x5856B00`, then the stencil-mask text.

**The scene target is black.** `FRAME_CUT_T0=1980000` (new) ends the frame
straight after the copy in step 3, so the window shows the scene target
alone: black (`cut1/`, `cut2/`). Still black with the commonest scene shader
forced to white (`FP_ONE=7460601`, `cut3/`), which says the geometry is not
landing in the target rather than being shaded black. Unverified: that
`FP_ONE` took effect for that program.

Found on the way, fixed, and not the cause: vertex attribute type 6, three
signed fields of 11, 11 and 10 bits in one word, was not decoded at all
(`[VTXTYPE] UNHANDLED type=6 attr=2`). The scene's meshes carry their
normals that way. `VP_ATTRS=1` now covers indexed strips; the layouts it
prints are float positions with sane extents (for example x -48 to 2, y 56
to 80), packed normals, half-float texture coordinates, and a second
position and normal stream on attributes 10 and 11, all in main memory.

**Why nothing landed: the backend replaced the title's matrix.** A
magenta clear of the bound target (`RT_CLEARDBG=2` with the cut, `cut6/`)
came through as solid magenta, so the copy to the display works and the 137
scene draws covered no pixel. `vp_record_cb` has a "garbage projection"
fallback written for another title: when constant 0's x is outside 0 to 8
and the program reads constants 0 to 3, it overwrites them with a made-up
projection. This title's matrix is ordinary and starts with -1.47
(`RSX_DBG_CB=62EAC00`, extended to print constants 0 to 23 and the viewport):
`c0=(-1.46774 ...  -0.934338)`, `c3=(2.7e-05 0.0837 0.9965 20.7867)`, world
matrix identity. Stdout had `[VPFB] fallback proj on draw slot 49 (c00=-1.46774
vs_idx=6)` for exactly the scene's draws. The fallback now fires only for a
bank that is all zero or not finite (`VP_FIXPROJ_OLD=1` for the old test).
The scene's vertex program, read with the new `VP_DUMP_DIR=<dir>`, is six
instructions: position times constants 0 to 3, two outputs passed through.

After that change, with the scene shader forced to white and culling and
depth off, the scene target is solid white (`cut7/`): the geometry lands
and covers the whole target.

**The scene target now holds a recognisable scene.** The frame-capture tool
already in the backend (`RSX_CAP=start:count:stride`, `RSX_CAP_DIR`, plus a
new `RSX_CAP_MIN=<draws>` to wait for a frame of that size) writes every
render target of one frame as an image with a manifest of its draws. On the
382-draw menu frame (`scratch/devrem/cap1/frame_01/`) the scene target was
textured shards reaching across the screen. Cause: primitive restart. The
title sets `NV4097_SET_RESTART_INDEX_ENABLE` and a restart index of `0xFFFF`
(`[RSX] restart index value = 0xFFFF`), and neither method was handled, so
the restart marker in every strip was fetched as vertex 65535. Indexed
strips and fans now end the run at that index, and every second strip
triangle has its first two corners swapped, which the old loop did not do
and which costs half of each strip under back-face culling
(`STRIP_OLD=1` for the old loop). With that, `cap3/frame_01/rt_01980000.png`
shows a street: a lamp post, building fronts, sky between them, and a road
surface that is plain white.

Checked and not involved: `NV4097_SET_VERTEX_DATA_BASE_OFFSET` and
`_BASE_INDEX` were not handled either and now are, but this title never sets
a non-zero value.

**Why the window is still black behind the text** (read from the manifest,
not yet tested by changing anything). After the scene is copied to the
display the frame makes three more full-screen draws to the display with
blending off, and each depends on something the backend does not do:

- `fp=0x057B4D01` samples `0x2100000`, a 2560x720 surface that follows the
  scene's colour surface in memory with a depth-style channel remap, so
  most likely the scene's depth buffer, and `0x2880000`, the blurred copy
  whose mip levels are addressed inside one surface. The backend has neither
  as a texture.
- `fp=0x057B5881` and `fp=0x057B6481` sample offset 0 at 1920x1080, which is
  the display buffer they are drawing to.
- The scene surface is declared 2560 wide when sampled and 1280 wide when
  drawn to, which is what a 2-sample antialiased surface looks like. The
  backend's target is 1280 wide. Whether that distorts anything is not
  checked.

Also open in the scene itself: much of the target is still black around the
street, the road is white, and whether the remaining gaps are culling,
missing draws or textures is not looked at.

Four 20 s headless boots with all of the above: 129 opens each, no arena
overrun (`scratch/ab-now/`).

Notes for whoever continues:

- The main-menu frame differs with what the script has pressed by then: 382
  draws on the menu, about 56 while the dealership loads, 577, 167 or 2048 in
  the dealership. Check the draw count (first line of the manifest) before
  reading a capture.
- Captures and shader dumps under `scratch/devrem/` are derived from the
  title; they stay in `scratch/`.

## Phase 32 - The heap failure is intermittent again; unlock was only a snapshot (2026-10-13)

Still BCUS98158. This corrects Phase 31's all-boots-fail reading. The
executable had not changed between these measurements.

**Boot outcomes.** A windowed run at 06:32 reached the readable Online User
Agreement. A 40-second headless run stalled in the already-known
`func_0067E930` null-vtable path. In a six-run, 20-second headless soak, three
runs reached 129 `GT.VOL` opens / 27 paths and the normal main wait at
`lr=0x00B391F4`; the other three were classified as one 2 KB allocator retry
(`lr=0x00B3BBA8`) and two sound-bank fixup loops (`lr=0x007A9BE4` and
`0x00B56EDC`). A second six-run soak had five runs with normal/near-complete
progress and one suspicious low-progress run. These are small samples, not a
stable failure rate. Logs: `scratch/resume/soakA/`, `soakB/`, and the
windowed capture `scratch/inp.err` / `scratch/inp_020.png`.

**The apparent unlock stall.** In the suspicious second-soak run, a main-thread
snapshot showed `func_00B3D8A0` (heap allocator) calling the `sys_lwmutex_unlock`
stub at `0x00B57338`, with LR `0x00B57348`; the heap pointer slot at
`0x012918D0` held `0x016F81A0`, so it was not a null heap. A later 20-second
run with `PS3_HLE_TRACE=200000 PS3_SCTRACE=1` generated repeated calls to NID
`0x1BC200F4` (including calls from LR `0x00B57348`) and ended at the normal
main wait, `lr=0x00B391F4`. Thus the snapshot does **not** show unlock stuck;
the allocator can leave that call. The traced run is at `scratch/boot.err` and
was timing-instrumented, so it does not answer what makes the occasional
2 KB allocation return empty.

**A repeated allocator failure.** A third six-run, 20-second headless soak
again produced three complete 129-open boots and three known-bad runs: one
2 KB allocator retry and two sound-bank fixup loops. The failed allocation
run (`scratch/resume/soakC/run4.err`) was sampled repeatedly at
`lr=0x00B3BBA8` with request size `r3=0x7D0`, alignment `r5=0x10`, and the
heap pointer slot still set to `0x016F81A0`. The heap descriptor's first word
was `0x016F89B0`; that block begins `01268820 20000000 2ADFFF80 20000000`.
This rules out a missing heap pointer but does not yet decode the free-list or
explain why this request is rejected. The snapshot also reports mutex id 89
owned by main; it does not identify that as the allocator's lock.

**The Phase 22 mutex divergence was a false lead.** I re-compared its saved
`scratch/good.err` and `scratch/bad.err` HLE traces using only arguments each
lwmutex API consumes: `r3/r4` for `sys_lwmutex_lock`, and `r3` for unlock.
Every one of the bad trace's 1,167 heap-mutex calls matches the corresponding
good call. The earlier ?different at lock 1,131? came from `r5`/other
caller-clobbered register values, which those APIs ignore. This corrects
Phase 22: the traces do not establish a changed heap-lock sequence or a mutex
fault. The logs omit thread IDs, so they still cannot rule out different
interleavings between PPU threads.

**Corrected allocator object and free-list capture.** The earlier `+0x28`
read above came from the outer heap wrapper at `0x016F81A0`, not the allocator,
and must not be treated as a size-bin reading. The wrapper's first word points
to allocator object `0x016F89B0`; its `+0x58` lock matches the lock address
`0x016F8A08` seen in the syscall trace. The `GT5P_PEEK` grammar now supports
`slot@@offset` to follow both pointers. At the exact `0x00B3BBA8` retry in
`scratch/resume/soakI/run5.err`, request `0x7D0`, alignment `0x10`, all 16
free-list heads at allocator offsets `+0x10..+0x4C` were zero. In successful
`scratch/resume/soakH/run1.err`, the same heads held live list nodes. The
allocator's `+0x50`/`+0x54` fields are used as region bookkeeping by the split
and insertion routines; they are not bin heads. This establishes that the
failed allocation sampled an empty set of free lists, but does not show how
they became empty or whether another allocator invariant was involved. A
priority-off six-run soak reproduced this once (two other sound-fixup
failures, three complete boots); it is not a stable rate.

**Mutex comparison.** The Phase 22 saved good/bad traces still match on every
consumed heap-mutex argument for all 1,167 calls; their missing thread IDs
leave interleaving differences untested. Logs: `scratch/good.err`,
`scratch/bad.err`, and allocator captures in `scratch/resume/soakH/` and
`soakI/`.

**Allocator write watch.** A priority-off six-run soak with `PPU_WWATCH`
covering the actual allocator heads (run logs in `scratch/resume/soakK/`) saw
the allocator initialize the 16 heads at `+0x10..+0x4C` to zero. During a good
boot, later writes into watched heads came from the allocator's own list
helpers: `0x00B3D158` unlinks a node and `0x00B3D1E8` inserts one. The watch
address was fixed at `0x016F89C0` and remained valid for these runs, but it
only captures plain PPU stores to that window; it is not proof against vector
or SPU writes. That batch yielded five complete 129-open boots and one known
sound-bank fixup failure, not the allocator retry.

**Allocator retry with write and lock traces.** A twelve-run priority-off
batch reproduced the `0x00B3BBA8` retry once (six full 129-open boots, five
sound-fixup failures, one allocator retry; `scratch/resume/soakL/`). In that
retry, the watched allocator heads had been initialized normally. The log
shows the allocator's own list helpers changing them; by the retry snapshot
all heads were empty, `+0x50` was `0x200C3380`, and `+0x54` was `0x20000`.
The memory at `0x200C3380` began `200C3340 204B8380 FFFFFFFF 00000000`.
These values establish remaining allocator bookkeeping, but do not yet
establish that this is usable space for the request.

I added `PS3_LWM_TRACE=<guest address>` in the local ps3recomp patch to log
acquire/release order for one lwmutex. A following six-run batch reproduced
the allocator retry in run 1 and again sampled all heads empty. Its trace
(`scratch/resume/soakO/run1.err`) records two acquire/release pairs by guest
thread 20, interleaved with that thread's writes to the allocator list under
the lock. The trace cap did not fill. No non-main thread touched that lock
after those early events; main was the thread repeatedly retrying the 2 KB
request. This does not show a lock stall or an overlapping list mutation.
It also does not prove why the free-list entries disappeared or whether the
`+0x50` region state should satisfy the request. The same batch had three
sound-fixup failures, one full boot, and one short-progress run ending at
`lr=0x00B57394` that `bootcheck` did not classify.

**Next.** Resolve how the allocator code uses `+0x50`/`+0x54` when every
searchable size-class head is empty, and follow the final list removal before
the retry. Keep the known sound-bank and null-vtable signatures separate; do
not count every short/incomplete run as the same heap fault.

### Why the menu picture never changes, and the live RSX engine (2026-10-13)

Reported: at the main menu, left and right play the cursor sound but the
picture does not change, and the title bar reads about 30 frames a second.

**Hypothesis tested and rejected.** The proposal was that the menu is drawn
offscreen and finished with a 2D-engine blit (NV3089) into the display
buffer, which the D3D12 backend would count as a frame and never present.
Measured on the executable built 16:19 (kept as `scratch/baseline/gt5p.exe`),
one windowed run driven by `PAD_HOLD` with `VP_SUBMIT=200 RT_OFFDBG=1
NV3089_DBG=50 CELLMARK_BLINKDBG=1` (logs: `scratch/menu_base.err`, `.out`):

- no `[NV3089]` or `NV0039` line at all, in either stream;
- the display buffers are `SetDisplayBuffer(id=0, offset=0x0, pitch=8192,
  1280x720)` and `(id=1, offset=0x880000, ...)`, and `[RTOFF]` reports the
  1920x1080-clip surface at offset 0 as `disp=1`;
- frames carry on-screen draws and are presented: `[PRESENTGATE] records=247
  onscreen=35 offscreen=212 clears=0 has_display=1 seen_content=1 ->
  render_frame=YES`, 199 times, and `[PRESENT] draws=382` (the menu) 103
  times. The 200 `[PRESENTGATE]` lines were used up on the agreement screen,
  so the menu's own gate line was not captured; its `[PRESENT]` lines were.

**What freezes the picture.** The same log has `[D3D12] DEVICE REMOVED
(0x887A0006)`: Phase 30's device hang, on the first frame that adds the
targets `0x2880000`, `0x57B6B00`, `0x5836B00`, `0x5856B00`. From then on the
backend presents nothing, so the last picture and the last title-bar text
stay up, while the title, its input and its sound carry on. In this run the
window stopped answering at 70 s. "About 30 frames a second" is that frozen
text (31.0 to 31.5 in Phase 30's runs), not a frame rate. New in this log:
`[RT] recreate slot 8 off=0x2880000 2048x127 fmt=28 -> 2048x1436 fmt=28`
straight after the removal, so that target was first made 127 rows high.
Whether that is connected to the hang is not tested.

**The live engine.** The supplied patch to `src/gt5p_present.cpp` applied
cleanly (`git apply --3way`) and built without changes. With `RSX_LIVE_DRAW`
unset the port behaves as before (`[rsx] backend init OK -- window open`,
agreement at `draws: 206`, 49 frames a second). With `RSX_LIVE_DRAW=1`:

- `[rsx] live-draw engine up (D3D12); GDI present suppressed`;
- the run goes through agreement, confirmation and menu (title-bar draws
  138, 0, 243, 563) and holds 48 to 61 frames a second to the end of an 80 s
  run, with no device removal;
- every capture is black, including the agreement screen
  (`scratch/live/inp_005.png` to `inp_080.png`, all 4,994 bytes). The
  engine's own counters say why text cannot appear: `groups[seen=231945
  exec=78369 ... drop{... prim=153576 ...}]` and `depthSRV=0`. It drops the
  polygon primitives the title draws its glyph outlines with, and does not
  sample the depth-stencil surface as a texture (Phase 23). Unverified:
  whether `PrintWindow` captures this engine's swap chain faithfully; the
  window was not looked at by eye.

So the live engine avoids the hang and shows nothing; the D3D12 backend shows
the menu and then hangs. Left/right changing the picture was not observed in
either. The patch is kept, off by default.

## Phase 31 — What the render thread waits for; and every boot now fails (2026-10-13)

Still BCUS98158.

**The render thread's wait, read from the code.** `func_00BA97B0(this, q)`,
called with `q = 3` from `0x00BAA9F8`, works on the shared structure at
`[this]` (`0x0139C900`, workload 4's data). For queue `q` it takes the
16-byte row at `+0x40 + 16*q`. The first halfword is how far the title has
published the queue's command list; it then counts on through the list at
`[+0x30 + 4*q]` to the first empty entry to get a target. The next seven
halfwords of the row are compared one by one and the smallest kept, and the
loop repeats until that smallest value reaches the target. So each queue has
seven per-SPU progress counters, and the title waits for every one of them.
A lane that never advances its counter holds the frame for ever, or until
whatever releases it every 4 s. Which counter lags in the dealership is the
next measurement. `GT5P_PEEK=0x0139C940,0x0139C960` shows the rows, but see
below: no boot has got that far since.

**Tools.** REA cannot open this executable: `open_binary` answers
"unsupported ELF architecture" for 64-bit PowerPC. `scripts/ghidra_decomp.ps1`
and `scripts/ghidra/DecompAt.java` drive Ghidra headless instead, importing
without auto-analysis and decompiling only the addresses asked for, into
`analysis/ghidra/out/`. Not yet proven: the first import ran 25 minutes
without finishing and was stopped. Do not run it beside the title; with it
running, seven boots in seven stalled.

**Every boot fails now.** From about 01:40, with the executable built at
23:34 that had been booting about one time in two: 16 windowed boots in 16
stall at `draws: 0`, 3 to 4 frames a second, and three headless boots are
called "runaway sound-bank fixup" by `bootcheck`. The machine is idle (20%
CPU, 13.5 GB of commit free), nothing under `gamedata/` or `input/` has
changed, and Ghidra is no longer running. Not explained.

One real defect found while looking, and not the cause: on Windows
`sys_time_get_current_time` returned the performance counter, which is time
since the PC was started (12.6 days here), where the POSIX branch of the same
function returns wall-clock time. It now returns wall-clock time
(`PS3_TIME_UPTIME=1` for the old value). Six boots with it and four without
all stalled.

This is the Phase 22 heap fault at a rate of 1 in 1, which is the first time
it has been reproducible on demand. That makes it the thing to work on: it
blocks everything else, and a fault that happens every time can be traced
where one that happened 1 time in 52 could not.

## Phase 30 — The four-second frame: located in the job manager's command interpreter, not fixed (2026-10-12)

Still BCUS98158, in the dealership. Phase 29 said "about 8 s a frame"; the
title's own counter is steadier and says 0.24 to 0.25 frames a second, a
frame every 4.0 to 4.1 s, in every slow run. A run now ends one of three ways
at this point, roughly evenly: this slow state, a device removal (below), or
a failed boot.

**Where the time goes.** `scratch/cpu.ps1` samples per-thread CPU over 12 s
and names the threads (runtime threads now log `[hostthread] <kind>
hosttid=`):

| Thread | Share of one core |
| --- | --- |
| SPURS kernel thread of the main instance | 99 to 100% |
| guest render thread, spinning at `0x00BAA9FC` | 74 to 99% |
| guest "Main Thread" of the online layer | 72 to 100% |
| nine `spurs-jc` job-chain threads | 5 to 9% each |

`SPURS_PM_FLOW=1 SPURS_PM_FLOW_ALL=1` on the kernel thread: one policy-module
run on workload 4 that does not end, 180 million control transfers and then
224 million two seconds later, cycling `01CB8 01DDC 01DF8 01ED4 02318 01B9C
02DF8 02E18 02E38 02E60`. In the lifted module `0x1B9C` is the head of a
command interpreter: it reads 8-byte commands through a pointer, skips zero
words, takes an opcode field through a table at `0x15B0`, and returns on
opcode 28. `0x1CB8` is one command's handler, and it falls through to "next
command" when a register is zero. So the module is walking a job command list
again and again without finding a command it may run. It is busy-waiting, not
working: a normal run on this workload is 35 to 2,224 transfers.

**What it is waiting for is not found.** Two things tried, both measured,
neither the answer:

- Two guest threads spin at once, and guest threads are confined to two
  cores. `PS3_PPU_PRIO_SCHED=0`: the same 0.24, with three threads at 100%.
  Not starvation.
- The title makes five "Wws_Job" workloads on its five-SPU instance, each
  with a contention of 1, one lane per SPU; the runtime runs them in turn on
  one thread. `SPURS_LANES=1` (new, off by default) gives each SPU its own
  kernel thread. The same 0.24 and 0.25. Not that either, or not alone.

The frame time being the same to within 0.1 s in every run reads like a
timeout that releases the wait, not like work finishing. Neither of the
backend's 2 s GPU waits fires (`STUCK` is never printed). What times out is
not found. Next: let the flow trace run to the end of one such module run and
read what the last transfers before it returns are, and what the render
thread's loop at `0x00BAA9FC` compares against.

**The device removal, again.** It was not cured by Phase 29; it had only not
recurred in three runs. It happens in about one good boot in two, as the
dealership's first frames arrive, and the run then shows a frozen window at
`draws: 167`. The backend now keeps summaries of the last four frames and
prints them on removal. The frame in flight is the first to add four render
targets (`0x2880000`, `0x57B6B00`, `0x5836B00`, `0x5856B00`) and five
fragment programs drawn as single quads, one of them writing three targets.
`FP_DUMP_DIR=<dir>` (new) writes every program compiled; none of these has a
loop. Ruled out by test: the vertex-program dispatch bound
(`RSX_VP_LOOP_MAX=64`), and binding the window-sized depth buffer beside
targets of another size (now not done; `RT_DSV_ALWAYS=1` restores it). Also
measured: no offscreen target is destroyed and remade in these runs (`[RT]`
lines, new, print none), so that is not it. Cause not found.

**The same shader bug in the open.** Three of the dumped programs compute
their result into the half-precision register file and the decompiler returns
the full-precision one (`float4 _o = r[0]` after the last write went to
`h[0]`). Not a hang, but those passes will output the wrong thing once they
do run. Not fixed.

Diagnostics added: `scratch/cpu.ps1`, `[hostthread]` lines, `SPURS_LANES`,
`FP_DUMP_DIR`, `RT_DSV_ALWAYS`, `[RT] recreate` and `[RT] evict`, the
four-frame device-removed report.

## Phase 29 — The device removal was failed pipelines: four texture units where the RSX has sixteen (2026-10-12)

Still BCUS98158. Phase 28 stopped at a removed GPU device as the first 3D
draws arrive, and offered three leads. None of the three was the cause.

**What "0.1 frames a second, Not Responding" was.** Two things, in different
runs, both the same failure seen from different ends:

- pipeline creation fails for a program, nothing is cached for it, and every
  draw that uses it decompiles and compiles its shader again, every frame;
- after a device removal every creation fails, so that becomes all of them:
  `PERF=2` showed 2,304 pipeline requests a frame, 2,304 misses, 17 s a frame.

A failed creation is now cached like a successful one, and after a removal
the backend stops asking (`s_device_lost`). `PERF=<n>` above 1 now reports
every n frames; at 20 frames a report this scene never produced one.

**Why creation failed.** `D3D12_DBG=1` and the failure path now print the
validation layer's reason: "Shader sampler descriptor range
(BaseShaderRegister=15 ...) is not fully bound in root signature", and the
same for 14. The scene's fragment programs sample units 14 and 15. The
backend carried four units per draw: four SRVs in the descriptor table, four
static samplers, `tex[4]` in the draw record. It is sixteen now
(`RSX_TEX_UNITS`). Texel-coordinate scaling and cube detection still cover
units 0 to 3 only.

Measured after: no `PSO FAIL`, no device removal, and the dealership screen
("ACURA", Cr.35,000) holds for the rest of a 100 s run. `render_frame` is
0.17 s a frame there.

**Phase 28's leads, checked.** The vertex-program dispatch bound:
`RSX_VP_LOOP_MAX=64` (new) changed nothing, so not that. `FP_OFF=1` did avoid
the removal, which pointed at fragment programs; the reason is the one above,
not a loop. The "resource deleted prior to closing the command list" errors
and the `[VPFB]` projection override are still there and still unexamined.
Whether the original `DXGI_ERROR_DEVICE_HUNG` was a consequence of the failed
pipelines is not established: it has not recurred in the three runs since, and
that is all that can be said.

**Where it stands now.** Two faults remain in the dealership, both measured:

- The title takes about 8 s a frame there and the backend is not why:
  `PERF=2` gives `guest 16.27s (98%)` over two frames. `GT5P_THREADS=1` has the
  render thread (tid 21) in the job-counter spin at `0x00BAA9FC` in 8 samples
  of 10, so it is waiting for SPU work. Which job, and why it is slow, is not
  found. One earlier run had SPU image 2 (`j0AB3F1A7`) resuming at `0x6C6C`
  about 70 million times a second; that address is a 15-entry jump table,
  lifted as code, whose first word decodes as `stop`. The table's targets are
  all lifted entries, so the switch read a zero where an entry should be.
  Hypothesis, not tested: that job is the one being waited for. It did not
  show in later runs, which may only mean they did not get as far.
- Nothing of the 3D scene is visible, the frame hits the 2,048 draw-record
  cap, and `VBFULL=1` reports the vertex buffer full (393,216 vertices of 256
  bytes).

**Harness.** `PrintWindow` blocks for ever on a window that has stopped
answering; `scratch/inp.ps1` now stops instead. A run that hung this way sat
for 18 minutes.

Diagnostics added: `RSX_VP_LOOP_MAX`, `PERF=<n>`, the device-removed report
(draws and vertices per fragment program for the frame in flight), the
pipeline-failure reason, and `[spu] drain-resume` once per distinct image and
address with the registers a switch would have used.

## Phase 28 — The main menu and the dealership; the GPU device hangs on the first 3D scene (2026-10-12)

Still BCUS98158. Driven by `scratch/auto.ps1` (hold Down from 16 s to 27 s,
Right, then Cross every 4 s).

**Phase 27's "stays on Confirmation" was not a stall.** The page takes its OK
only once the load behind it has finished; presses made before that are
ignored, and the earlier script stopped pressing too soon. With presses
continuing, the title shows its main menu ("Welcome to Gran Turismo 5:
Prologue. The first thing you need to do is visit the Dealerships and buy
yourself a car.", Cr.35,000, and 2P Battle, Events, Garage, Dealerships,
Replay, Options, Manual), and the next press enters Dealerships: "ACURA" with
its reflection. Text only, on black, in both. The threads named "Http
Thread", "Comm Thread" and "Hash Thread" that start here are the title's
online-content layer; they were a suspect and are not what it waits for.

**Two counters that wrapped.** Both are `static int n; if (n++ < CAP)` around
a debug line on a hot path. After 2^31 passes the int is negative and the
line prints every time.

- `spu_drain.c`, `[spu] drain-resume`, cap 8: an SPU loop resumes there about
  70 million times a second. 3.1 GB of stderr in one run.
- `sys_ppu_thread.c`, `[prof-stamp]`, cap 0 (a disabled trace), on every
  syscall and HLE dispatch. It wrapped about a minute in, sooner now that
  the timer fix lets the title run faster; from then on every dispatch wrote
  a line. This is the "0.2 frames a second, Not Responding" the user saw on
  the main menu, and the 12 GB log noted in Phase 24.

Both fixed. The same idiom is used hundreds of times in ps3recomp; only
these two were found on paths hot enough to wrap. If a log suddenly grows by
gigabytes of one line, look for it.

**`PAD_SCRIPT` was already taken.** ps3recomp had a variable of that name
with another format (`<sec>:<mask>`), and both parsers read the string.
Phase 27's addition is renamed `PAD_HOLD`.

**The pipeline cache thrashed, partly from Phase 25's fix.** In the
dealership the window showed `draws: 2048` (the backend's per-frame cap) at
0.25 frames a second. `FP_LIST=1` counted 12,639 shader compiles in 80 s, then
33,928. Phase 25 had put the texel-addressed texture sizes into the pipeline
key and into the shader text, for every draw, including programs that sample
nothing. Now: the scale is read from the per-draw constants the backend
already uploaded (`rsx_texscale` at `b1`), the key holds only which units are
texel-addressed, programs with no sample site to scale are remembered and
keyed as plain, and the cache holds 1,024 entries, not 256. Measured: 465
compiles in a run that reaches the same point. `PSOMISSDBG=1` now names every
key field and prints 400 misses, not 12; what is left differs by vertex
program and stencil state, which are real variants.

**Where it stops now: the device is removed.** As the dealership's 3D scene
begins (the first `draw_indexed` calls, 256 indices at a time), pipeline
creation starts failing with `0x887A0005` and the process ends.
`D3D12_DBG=1 D3D12_IQ=1` gives the reason: `DXGI_ERROR_DEVICE_HUNG`, the GPU
took too long to execute its commands. Not investigated. Leads, none tested:

- the decompiled vertex programs with flow control run a dispatch loop of up
  to 16,384 passes per vertex; a program whose branch target is not one of
  the emitted blocks would spend all of them on every vertex;
- the validation layer also reports, six times each, a resource "deleted
  prior to closing the command list" and prior to executing it. Something
  releases a texture or target that the frame still uses;
- `[VPFB] fallback proj` prints for these draws: the backend replaces the
  title's projection matrix when its first element is outside 0 to 8, and
  here it is -1.47.

**Failed boots** (a sub-agent's report; it ran 21 windowed boots and stopped
early at the user's request). Every stall it could classify is Phase 22's
fault, a guest heap allocation that returns null: five of 21 runs.
`scripts/bootcheck.py` recognises both shapes when `GT5P_MAINSTACK=5` is set.

| Shape | Seen from outside | What it is |
| --- | --- | --- |
| Stall B | 1 to 3 frames a second, `draws: 0`, 33 to 41 flips | the allocator wrapper `func_00B3BB60` retries a 2,000-byte request for ever |
| Stall A | frame counter frozen, `draws: 0`, about 78 flips | the same null, unchecked: the sound loader reads into address `0x880`, and the vsync handler's descriptor is overwritten, so flips stop |
| Early exit | process gone in the first seconds | not seen in its runs; unclassified |

The dark blue the user saw on failed boots is the backend's own default clear
colour (0, 0, 0.1), set in `rsx_d3d12_backend_init` and replaced only when the
title issues a display clear. A dark blue window means the title never
cleared the screen.

Not measured, because the runs were cut short: the rate headless against
windowed, with `GT5P_TIMER_RES=0`, and with `PS3_PPU_PRIO_SCHED=0`. Its runs
also spanned several rebuilds and five overlapped another instance, so the
1-in-4 is a rough figure. Its proposed next step is to dump the heap object
on a stall and watch its limit words for the thread that rewrites them; the
address it derived for the heap pointer slot (about `0x012918D0`) is not
validated.

## Phase 27 — 62 frames a second, and the top-menu crash was `cellHttpUtilParseUri` (2026-10-12)

Still BCUS98158. Two separate results.

**Frame rate: Windows timer granularity.** The agreement screen ran at 12.8
frames a second and the confirmation at 20, both steady. A sub-agent measured
it without building: the D3D12 backend takes 3% of a frame (`PERF=1`, 0
pipeline misses), turning priority scheduling off changes nothing, logging is
under 1 MB a run, and two guest threads are busy while the rest wait. What is
left is sleeping. Nothing in the port asked for a finer timer, so `Sleep(1)`
lasted about 15.6 ms (15.25 ms measured in a fresh process on this machine),
and the SPURS kernel poll thread, the present thread and guest `usleep` all
pace themselves with short sleeps. 12.8 frames a second is 78.1 ms, exactly
five such sleeps.

`src/main.cpp` now calls `timeBeginPeriod(1)` at start-up.
`GT5P_TIMER_RES=0` leaves the system default. Measured after: 62 to 63 on the
confirmation screen (was 20), and 3,100 to 3,300 flips in a 65 s run (was
about 1,550). The agreement screen was not sampled alone after the change.
Not re-measured: the bad-boot and stalled-boot rates, which depend on timing;
two of the six windowed boots since stalled, as before.

The agent's other proposals, none done: wake the SPURS kernel thread on a
kick instead of polling (`spurs_kernel_thread` in `cellSpurs.c`), have the
present thread wait on the existing `cellGcm_fifo_kick_wait` instead of
`Sleep(4)`, and yield in the guest's job-counter spin at `0x00BAA9FC`, which
holds a core at about 90%.

**The crash while the top menu loads.** Phase 26 left a stack overflow in
`func_00D80560`, a tree erase walking a null node. Found in five steps, each a
measurement:

1. Runs no longer need a person. `PAD_HOLD="<from_ms>-<to_ms>:<KEY>,..."`
   (new, `libs/input/cellPad.c`) holds buttons on a schedule with no keyboard
   or focus. `scratch/auto.ps1` builds and drives the title past the
   agreement with it.
2. The crash report now follows the guest back chain and lists the code
   addresses stored on the stack around the object in `r3`
   (`src/main.cpp`). That named the path: `func_008E0848` has a local object
   at `r1+0x1C8`; it is built by `func_00B94278`, which allocates the tree's
   head node, and destroyed at `0x008E0978` through `func_00B93E20` and
   `func_00E01020`.
3. The allocation does not fail. Null stores are now reported once per new
   writer after the first eight (`ppu_loader.cpp`), and the constructor is not
   among them. So this is not Phase 22's failure, which was one of the two
   readings Phase 26 offered.
4. Nothing lifted clears the pointer. `PPU_WWATCH_TAIL=1` (new) keeps the last
   96 writes to a watched address and the crash handler prints them: the last
   write to the head pointer is the constructor's. But vector stores in lifted
   code are a bare `memcpy` into guest memory and never reach the watch.
5. `PPU_WW_GUARD=1 PPU_WW_GUARD_FN=B94278` (the second is new: arm the page
   guard only when that function sets the word) caught it: a host routine
   clearing upward in 32-byte steps from `0xD00CD5B0`, called from
   `func_008DF718` at `0x008DF7F8` with a structure at `r1+0x70`, a string, a
   buffer at `r1+0x90` and the size `0x100`.

That call is `cellHttpUtilParseUri(uri, string, pool, size, required)`. The
guest structure is 28 bytes: five string pointers, a port, four reserved
bytes, with the strings placed in the caller's pool. ps3recomp modelled it as
seven inline character arrays, 2,708 bytes, and began by zero-filling all of
it. The fill ran 2.7 KB up the guest stack through three callers' frames.
Both `cellHttpUtilParseUri` and `cellHttpUtilBuildUri` are rewritten to the
real layout and read and write the structure by offset.

Measured after: a 120 s scripted run takes no fault and prints no recursion
cap; the title goes on to stat and read 60 more files (scene scripts, a
character, motions), and `draw_indexed` is called for the first time.

**Where it stops now.** The window stays on the dimmed "Confirmation" page at
62 frames a second. File activity ends about 30 s before the run was stopped,
after `motion/m0076`; the main thread is in its usual wait and no thread is
reported spinning. Not investigated. `draw_indexed` being new is a lead: the
backend may be dropping what the next screen draws.

Corrections to earlier phases: Phase 26's failed `stat` of
`tv2_us_root.xml=` was not the cause, and the missing-file reading it offered
is wrong; that string is what was being parsed as a URI.

Diagnostics added: `PAD_HOLD`, `PPU_WWATCH_TAIL`, `PPU_WW_GUARD_FN`,
`GT5P_TIMER_RES`, the per-writer null-store report, and the back chain and
stack scan in the crash report.

## Phase 26 — Past the agreement: an unmatched `bctr` was lifted as a call (2026-10-12)

Still BCUS98158. Phase 25 left the process exiting after the agreement. Two
controlled runs settle what triggers it: left alone for 60 s the title stays on
the agreement (1,117 flips, alive); with the user pressing down to the end,
right, Z, then Z on "Confirmation", it exits 5 to 10 s later, every time
(four runs). `scratch/inp.ps1 <secs>` is the harness: it captures the window
every 5 s and reports when the process goes away.

**What the exit was.** Just before the stack overflow the runtime prints
`[ppu] recursion cap @0x00B5D900 depth=4001 -- skipping`, three times. The
dispatcher in `ppu_loader.cpp` counts nested indirect guest calls and, past
4,000, returns without making the call. A skipped call is silent data
corruption; here it was followed at once by a tree erase walking a null node
(`func_00CB0698`) until the host stack ran out.

**First hypothesis, wrong for this crash.** That the counter leaks: a guest
`longjmp` is done with a host `longjmp`, which skips the decrement. It does
leak, by one per jump (`[setjmp] longjmp unwinds 1 indirect call(s)`), and
`gt5p_longjmp.cpp` now restores the depth it recorded at `setjmp`. The exit
happened again with that in. Only three calls were skipped before the crash,
which also says the depth was not stuck high; it was really that deep.

**The cause.** The cap now prints the outermost targets. After a dozen
ordinary frames they are six addresses, `0x0078CCEC` to `0x0078CFB0`, over
and over, while the guest stack pointer does not move. Those are case blocks
of one function with a loop around a switch: it reads a byte, dispatches
through a table (`bctr` at `0x0078CD90`), and each case branches back to the
top. `scripts/jumptables.py` did not match that table, so the lifter split the
cases into functions and emitted the `bctr` as
`ps3_indirect_call(ctx); return;`, a nested host call per pass round the
loop. Four thousand bytes of input reach the cap.

**The fix.** A `bctr` with no matched table is still a jump. The lifter now
emits `ps3_indirect_tail(ctx); return;`, and the runtime hands a known target
to the tail-call trampoline, so the caller runs it at the same depth. The
generated source was brought into line by the same textual change (1,778
sites) rather than a re-lift. `PPU_NO_INDIRECT_TAIL=1` restores the nested
call. Measured: a headless boot is unchanged, and in the next input run the
recursion cap does not print.

**Still exits, one step further on.** The same input run ends at the same
moment with a stack overflow in a different function, `func_00D80560`: the
same shape of tree erase (node flag at `+0x45` this time), node argument 0.
The last file activity before it is `TopRoot.gpb` and `TopMenuTemplate.gpb`
read from `GT.VOL`, then a failed `stat` of
`/dev_hdd0/game/BCUS98158/USRDIR/grim/file/contents/tv2_us_root.xml=` (the
trailing `=` is in the request). So the title is building its top menu. Not
investigated. Two readings, neither tested: a container whose head node was
never allocated (Phase 22's unchecked allocation again), or an error path for
the missing file that the title never takes on a console with its data
installed.

**Windowed boots that stall are unchanged**: three of the eleven boots in
this phase never drew.

## Phase 25 — First picture: the licence agreement is readable (2026-10-12)

Still BCUS98158. The window now shows the "Online User Agreement" screen: the
title, the scrolling agreement text, "Decline", "Accept" and "Enter", all
legible. Three faults in ps3recomp's graphics path stood between Phase 24 and
that, found in this order.

**1. Texel-addressed textures were sampled as if normalised.** The painting
quads were rasterising all along. The title binds the mask with the
unnormalised-coordinates bit set (`0x40` in the texture format) and passes
coordinates in texels, 1 to about 1226 on a 1920×1080 texture. The D3D12
backend passed them straight to the sampler, so every sample fell outside the
glyphs and the quads came out with alpha 0. The decompiler already had the
fix-up (`rsx_fp_apply_unnorm_scale`); this backend never called it. It does
now, and the scale is part of the pipeline cache key. `RSX_NO_UNNORM=1` turns
it off.

Measured: with it on, `[FP] fp=0x507F3C1 texel-addressed units 0x1: 4 sample
sites scaled (unit0 1920x1080)`, and the page layout appears, with several
glyphs stacked in each cell.

**Phase 24's "forced to white shows nothing" was not a test.** `FP_ONE`
rewrites the text `_po.c0 = `, which the decompiler in this tree does not
emit; it ends with `float4 _o = h[0];`. The switch did nothing, silently, for
both that experiment and the mask pass, which relies on the same rewrite. It
now matches either spelling. The four things Phase 24 ruled out with it
(culling, depth, alpha test, re-binding) were ruled out by a test that could
not fail; they did turn out not to be the cause. The two leads it listed were
not the cause either: `D3D12_DBG=1 D3D12_IQ=1` reports no validation messages
for a 159-draw frame.

**2. Immediate-mode draws were dropped.** The stacked glyphs were cells never
being wiped. An `RSX_TRACE` of a late frame (new: `RSX_TRACE_FROM_STENCIL=<k>`
starts it after the k-th stencil enable) shows, per glyph: all three stencil
ops set to zero, `BEGIN(quads)`, eight writes to `0x1880`/`0x1884`, `END`;
then ops keep/keep/invert and the polygon through `DRAW_ARRAYS`. `0x1880` is
`SET_VERTEX_DATA2F_M`: the wipe quad's four corners are sent inline in the
command stream, with no vertex array. `rsx_commands.c` ignored the method, so
the wipes never happened. It now collects those vertices and hands them to a
new optional backend hook, `draw_immediate`, at `END`; the D3D12 backend draws
them through the quad path. `RSX_NO_IMM=1` drops them again.

Measured: draws per frame went from 159 to 206, and the text became legible.
Phase 23 described the wipe correctly; Phase 24's frame listing could not show
it, because a draw that was never recorded is not in the list.

There is no stencil clear to rely on: `CLEARDBG=1` shows the title's clears
are `0x1` (depth only) and `0xF0` (colour). The clear handler used to ignore
its flags and treat every clear as a colour clear; it now leaves colour alone
when no colour bit is set, and clears the mask target on a stencil clear.

**3. The guest scissor was not applied.** Agreement text scrolled above its
panel and ran over the title. The trace shows a scissor of 869×480 at
(205, 113) around the text draws and 100×42 at (1099, 21) around "Enter". The
backend used the viewport as the scissor. Each draw record now carries the
guest scissor and it is intersected with the viewport rectangle.
`RSX_NO_SCISSOR=1` turns it off. Measured: the text now stops at the panel's
top edge and fades out at its bottom edge, and the title is clear.

**Input works, and the title goes past the agreement.** The runs in this
phase were not all untouched: the user was scrolling the agreement and
pressing Z in the window, which the title takes as "Accept". That is where the
second captured screen comes from: "Confirmation. This game supports the
auto-save feature. ..." with an "OK" button, caught mid-fade at 70 draws a
frame and 20 frames a second. It follows the agreement.

**Open: the process then exits.** Four of fourteen runs ended by themselves
after 800 to 1,170 flips. The one trace kept (`scratch/crash.err`) is a stack
overflow: `func_00CB0698` calling itself without end at `lr=0x00CB082C`, with
its node argument 0 and reads of addresses `0x8` and `0x31`. By its shape the
function is a red-black tree erase (node flag at `+0x31`, child links at `+0`
and `+8`, a short-string capacity test against 15), so a container is being
destroyed through a null root. Hypothesis, not tested: this happens on the
step after "Confirmation", and is the unchecked failed allocation of Phase 22
showing up later. Which runs had key presses was not recorded, so the link to
input is the user's account plus timing, not a controlled test.

Eight further runs with `RSX_NO_IMM=1 RSX_NO_SCISSOR=1`: one exited the same
way at 1,131 flips, two were on a 42-draw screen (the confirmation without its
wipe quads), two were on the agreement, two stalled at `draws: 0` and one
exited at start. So the exit does not need the immediate-mode or scissor
changes. Input was not controlled in these either.

**Not yet right.** Nothing is drawn behind the text; the frame holds only mask
draws and the quads that paint them, so either this screen has no background
or its draws are another kind the backend drops. Not looked at. Back-face
stencil ops (`0x035C` to `0x0364`) and the stencil write mask (`0x032C`) are
still untracked; here they equal the front-face values and `0xFF`.

**Windowed boots are still unreliable**, as in Phase 24: in this session
about one run in four sat at `draws: 0` with roughly 80 flips, and two exited
at start. Those are not explained by input.

Diagnostics added: `RSX_TRACE_FROM_STENCIL`, `CLEARDBG`, `RSX_NO_UNNORM`,
`RSX_NO_IMM`, `RSX_NO_SCISSOR`; `VP_POSDBG` now prints all four corners of a
quad and the enabled vertex arrays; `D3D12_IQ` prints how many messages it
found, so "none" is distinguishable from "not running".

## Phase 24 — The mask renders: "Decline", "Accept", "Enter". The quads that paint it still do not (2026-10-12)

Still BCUS98158. Phase 23's second route is in: a draw with stencil on and
colour writes off now goes to an offscreen colour target keyed by the zeta
offset (`rsx_stencil_mask_pass`), with the stencil pass op done as a blend and
the pixel shader forced to output 1. `RSX_NO_STENCIL_MASK_RT=1` turns it off.
A logic op was tried first and D3D12 refused the pipeline (`0x80070057`): it
allows logic ops only on integer formats.

**It works as far as the mask.** `RTT_SAVERT=1100000 RTT_SAVERT_AFTER=45`
saves that target. It holds a row of glyphs reading "Decline", "Accept" and
"Enter", twice, in the top-left 1280×720 of a 1920×1080 surface. So the title
is on its licence-agreement screen (it stat-ed `AgreementRoot.gpb` just
before), its text is drawn as vector outlines, and each glyph is rasterised
into a 60-texel cell and then sampled four times by the quad that paints it.

**The painting quads show nothing.** Measured so far:

- they are recorded and submitted: 31 with program `0x507F3C1` and 8 with
  `0x507F0C1` per frame, target the back buffer, colour mask `F`, texture 0
  resolved to the mask target (`texrt=0`), the guest's own pipeline
  (`VP_SUBMIT`);
- their corners are on screen: `VP_POSDBG=12` gives clip positions such as
  `(-0.25, 0.75, 0, 1)` and `(0.30, 0.22, 0, 1)`;
- the back buffer is presented: `CLEAR_RGB=0.4,0,0` gives a red window;
- nothing appears on that red with the output forced to white (`FP_ONE`),
  culling off, depth test off, alpha test off and the render target re-bound
  before every draw.

So the draws reach the GPU with sane positions and write nothing. Not yet
explained. Two things to check next, neither tested:

- the mask target is 1920×1080 and is bound with the 1280×720 depth buffer,
  which D3D12 does not allow. The mask draws rasterise anyway, but the state
  left behind may be what drops the quads. Give the mask pass no depth buffer,
  or one of its own size;
- `DRAW_KEEP_TEX=1100000 DRAW_KEEP_NOCLEAR=1` keeps only the draws that sample
  the mask. If they show on their own, the fault is in the switching between
  the two targets.

**Windowed boots are unreliable.** Of the last dozen windowed runs about a
third never reached the UI in 50 s (70 to 150 flips, `draws: 0`), one of them a
bad boot by `bootcheck` and one a crash at start. Headless soaks do not show
this rate. Not looked at.

Diagnostics added: `VP_POSDBG=<N>`. Files `RTT_SAVERT` and `FP_DUMP` write go
to the working directory; move them to `scratch/`.

## Phase 23 — Why the window is black: the title draws into the stencil buffer and reads it back as a texture (2026-10-12)

Still BCUS98158. Phase 22 ended on a hypothesis about vertex layout. It was
wrong: attribute 0 really is four floats, and the title's 39-instruction vertex
program uses the last two as texel coordinates on purpose. The shaders
translate correctly and the matrix is a plain 2/1920, 2/1080 scale.

**What the frame is made of.** `RTT_DUMP=2` lists a frame's draws with their
state, and `RSX_TRACE=1500000` gives the commands around them.

| Draws per frame | Program | Colour writes | Stencil |
|---|---|---|---|
| about 120, polygons and quads | `0xFFFFDC1` | off | on, compare ALWAYS |
| 31, quads | `0x507F3C1` | on | off |
| 8, quads | `0x507F0C1` | on | off |

For each shape the title does this, 559 times in the frames traced:

1. stencil ops ZERO, ZERO, ZERO and one quad: wipe the shape's rectangle;
2. stencil ops KEEP, KEEP, INVERT and the shape's polygons: an even-odd fill
   into the stencil buffer;
3. nothing tests that stencil. The compare is ALWAYS throughout, and
   `SET_STENCIL_FUNC` is sent 34 times in 1.5 million commands, always ALWAYS.

The coloured quads that follow bind texture 0 at offset `0x01100000`
(`DRAWARGS`), which is the depth and stencil surface (`SET_SURFACE_ZETA_OFFSET
= 0x01100000`). So the stencil buffer is the title's coverage mask and it is
**sampled as a texture**. The 1920×1080 surface under a 1280×720 viewport is
consistent with that.

**Why nothing shows.** The D3D12 backend had stencil disabled in every
pipeline, so step 2 wrote to no buffer at all. It also cannot hand the stencil
plane to a pixel shader as a texture, so the quads sample whatever is in guest
memory at that offset, which is nothing.

**Done.**

- Stencil state is now part of the pipeline key and is applied
  (`rsx_stencil_key`), with the reference value set per draw. Only the front
  state is tracked; the title sets back to the same values.
- Polygons go through the vertex-program path as fans (Phase 22).
- `VP_VIEWDBG=1` prints the guest viewport transform; `RTT_DUMP` lines now
  carry the stencil word, reference and blend key.

A read-back of the back buffer after this is still solid black
(`CELLMARK_DUMP=2 CELLMARK_DUMP_MINDRAWS=100`), which is what the above
predicts: the mask is being built and never read.

**Not done: reading it back.** Two ways:

- bind the depth-stencil buffer's stencil plane as a shader resource when a
  texture's offset equals the zeta offset, and convert it to the channel the
  guest expects. A D24S8 word read as A8R8G8B8 puts stencil in blue;
- or keep it out of the depth buffer: send the colour-masked, stencil-only
  draws to an offscreen colour target keyed by the zeta offset, with INVERT as
  a `1 - dest` blend and ZERO as a plain write of 0, writing blue only. The
  backend already resolves a texture bound at a render target's offset to that
  target, so the coloured quads would pick it up with no further change.

The second is smaller and is the one to try first.

**Other things seen.** The 8-draw program is text: quads in 1920×1080 pixels,
glyph cells 60 texels apart. A windowed boot sometimes sits at 1 frame a second
for its first 90 frames before speeding up; not looked at.

## Phase 22 — The bad boot is a heap allocation that fails; priority scheduling makes it rare (2026-10-12)

Still BCUS98158. Two questions: why some boots go wrong, and why a good boot
shows nothing.

### The bad boot

Phase 18 listed four signatures and no cause. They are one fault seen at four
distances.

**What happens.** A bad and a good boot were traced with `PS3_SCTRACE=1
PS3_HLE_TRACE=400000` and compared.

- The file calls are identical in both, call for call, up to the last one the
  bad boot makes: 245 `cellFs` calls, the last a read of `0x1B210` bytes.
- In the good boot that read goes to `0x204DAE80`. In the bad boot it goes to
  `0x00000880`. The loader adds `0x880` to the block it was given, and the
  block was null.
- Under the heap's lightweight mutex (`0x016F8A08`) the bad boot has five
  requests in a row that come back empty: `0x620`, `0x680`, `0x810`,
  `0xFFFCA470` and `0x1BB00` bytes. The good boot has none at that point. The
  two boots' heap activity is the same for 1,131 lock operations and differs
  from there.
- Nothing checks the result. The I/O worker reads the file to address `0x880`,
  reports success, and the sound loader walks what it thinks is a bank
  (func_007CA908). From there memory is overwritten: the first failing system
  call comes 79,000 trace lines later, and after that the vertical-sync
  handler (func_00BCC1B8) is locking mutex ids `0` and `0xF950434E`.
- The other signatures are the same failure met elsewhere. "Allocation retried
  for ever" is main asking the same heap. "Lock on a corrupt object" and the
  rest come after the overwrite.

A good boot has no failing system call at all in 14 s. The bad one has 1,900.

**Why the heap is empty then is not known.** Phase 18's list of things ruled
out still stands, and `PS3_LWM_CHECK=1 PS3_SYNCLOG=1` found nothing in 12
boots, none of which went bad: the extra logging hides the fault.

**What makes it rare.** `PS3_PPU_PRIO_SCHED`, written in an earlier session and
left off: guest threads are confined to one or two host cores and run by PS3
priority.

| Setting | Bad boots |
|---|---|
| off | 3 of 14, 3 of 9, 2 of 8 |
| `=1` | 0 of 14, 0 of 14 |
| `=2` | 0 of 14, then 1 of 10 once it was the default |

That is 1 bad boot in 52 with it on against 8 in 31 with it off. It is rarer,
not gone: the one that did go bad was the allocation retry. So the fault is
far more likely when guest threads run in an order the console's scheduler
does not allow. That is a description, not a cause: which two threads, and
what one of them does to the heap, is still open. `src/main.cpp` now sets
`PS3_PPU_PRIO_SCHED=2` unless the variable is already set; `=0` turns it off.

It is also faster. Two 60 s boots with `=1`: 2,926 and 2,931 flips, against
about 1,180 without. They reach 25 paths rather than 27 in that time.

### The black window

- The title renders at 1920×1080. Its two colour surfaces are at offsets `0`
  and `0x880000` with a 1920×1080 clip (`RT_OFFDBG=1`), and both are registered
  display buffers, so the draws are aimed at the back buffer. The backend's
  window and viewport are 1280×720.
- Of the draws sampled, 89 are primitive 10 (polygon) and 22 primitive 8
  (quads). The per-frame SPU job of Phase 20 is what builds them.
- The D3D12 backend sent polygons down its fixed-function path, which neither
  expands them nor runs the guest's vertex program. They now go through the
  vertex-program path as fans. **The window is still black after that**, with
  a flat-colour pixel shader forced as well (`FP_IDCOLOR=1`), so the fault is
  before the pixel shader: in the vertex transform, the viewport, or the
  surface the result lands on.

- `VTX_DUMP=1` writes `vtx_dump.txt` into the working directory (move it to
  `scratch/`; it is derived from the running game). Its quads have attribute 0
  as `(718.9, 23.0, 1.0, 1.0)`, `(764.1, 23.0, 61.3, 1.0)`,
  `(764.1, 68.3, 61.3, 61.3)`: x and y in 1920×1080 pixels, and the third and
  fourth numbers stepping by 60 from quad to quad in the way cells of a glyph
  atlas would. So the title is drawing a row of text near the top of the
  screen, and its vertices are two floats of position followed by two of
  texture coordinate. **Hypothesis, not tested:** the backend reads attribute 0
  as four floats, so the texture coordinate lands in z and w, and a w of 61
  puts the vertex nowhere useful.

**Next.** For the picture: check the size the title declares for attribute 0
against what `upload_quads_vp` and `upload_strip_vp` read, and fill missing
components with (0, 0, 0, 1). For the bad boot: find the heap
operation at lock 1,131 that only the bad boot makes, and which thread makes
it.

## Phase 21 — The job finishes; frames run for the whole boot; 159 draws a frame, nothing visible (2026-10-12)

Still BCUS98158. Phase 20 ended with the wid 4 job running but its run never
finishing, and two hypotheses. Both were wrong. The job is short and correct:
2,119 transfers, start to return. Four further defects sat behind it.

| Defect | Evidence | After the fix |
|---|---|---|
| The module calls the job and the job returns to `0x3258`, which was not a lifted entry. The interpreter took the tail, and its `lqa`/`bi` on the saved return slot went to LS 0, the interrupt vector | Trail frozen with `SPURS_PM_FLOW_FREEZE=3258`: `040F4 03258 02660 02664 02668 02698 03260 00000 00A2C`. `SPU_LS_WATCH=0x1500` shows one write to the slot, the correct `0x2CA8`. Then the same seven addresses for ever, 56 million transfers in 10 s | `0x3258` and `0x3260` seeded (`wws_job_pm_extra_funcs`). The trail goes `03260 02CA8 02CB8` and into the store phase |
| 8 MFC engine slots. A policy-module context is persistent and keeps its slot, so the title passed 8 on every boot and the rest shared one engine's tag state | `[SPU] more than 8 contexts hold an MFC engine at once`. Five 60 s boots: 611, 615, 614, 658, 748 flips, each ending with the module asking for ever whether DMA tag 1 had completed (`02C88 02340 02D30 02D38`) | 32 slots. Five boots: 1,173 to 1,187 flips. One 120 s boot: 1,962 |
| Graphics interrupts were delivered only at HLE entry. With a window the FIFO walker runs on the present thread, and the render thread is by then asleep in `sys_cond_wait` on the user-command object with a one-second timeout | Windowed: 42 flips in 45 s, title bar `FPS: 1.00`, render thread at `lr=0x00BCA01C` in `sys_cond_wait(0x6A, 1000000)` | Also delivered at `lv2_syscall` entry. Three windowed 45 s runs: 81, 866, 561 flips. The slow one is not explained |
| A second weak declaration of `ppu_gcm_pump` is a duplicate definition to the COFF linker | `lld-link: error: duplicate symbol: ppu_gcm_pump` | A plain wrapper in `ppu_hle.cpp` |

Phase 20's "more than 32 contexts" still prints once late in a run, so slots are
also being leaked by something that is not a policy module. Not looked at.

**The picture.** With a window the title bar reads `FPS: 13.00 | draws: 159`.
A capture of the window at 60 s (`PrintWindow`, saved to `scratch/`) is solid
black. Earlier in the boot, before any draw, the same capture is dark blue, so
the capture does see the swap chain. 159 draws a frame are reaching the D3D12
backend and none of them shows.

**Frame rate.** About 13 a second once the job runs, against 30 before it. One
job per frame, so the job path is the limit: the kernel thread polls every
1 ms and runs the five workloads in turn.

**File activity.** No new path after `serverlist2_us.xml` in 120 s. Whether the
title is waiting for input on a screen that cannot be seen, or for the network,
is not known.

**Diagnostics added.** The hang watchdog now also prints the last 64 transfers
and a total, twice, two seconds apart (`HUNG-RUN NOW`), which is what separated
"long loop" from "seven addresses for ever". `SPURS_PM_FLOW_FREEZE=<hex pc>`
stops that ring 24 transfers after an address is first seen.

**Next.** Why 159 draws show nothing: which render target they go to and what
is presented. Then the intermittent slow windowed boot.

## Phase 20 — Frames stop at 20 s: the job manager was lifted at the wrong address (2026-10-12)

Still BCUS98158. Phase 19's boots were 20 s long. A 90 s boot issues the same
613 flips: the frames stop about 20 s in, just after the stat of
`serverlist2_us.xml`.

**Where it stops.** The render thread (`PDI:1:200c3b40`) is in func_00BA97B0
under func_00BAA9E8, reading `0x0139A880` in a loop. That function waits for
six per-SPU counters in a job-manager queue to reach a target. The queue
belongs to a fifth `Wws_Job` workload, wid 4, data `0x0139C900`, which the title
adds late and kicks with `cellSpursReadyCountStore(wid=4, 1)`. Nothing ever ran
it.

**Why nothing ran it.** Four findings, in the order they were met. Each was
confirmed by the boot that followed its fix.

| Finding | Evidence | After the fix |
|---|---|---|
| `scripts/lift_spu_jobs.py` lifted the policy module at base 0. The SPURS kernel loads it at local-store `0xA00`, and its scheduler keeps continuation addresses as absolute values. Every such branch landed 0xA00 bytes away | One `dispatch wid=0` in a whole run and no other. `[spu-spin] ... GETLLAR ea=0x016ECA00 x4M`. A trace of that line shows a `PUTLLC` with no `GETLLAR` before it, repeated for ever: the continuation `0x2CF0` had entered the middle of an atomic helper | wids 0 to 3 are dispatched and leave through exit-to-kernel. The kernel thread is no longer stuck in workload 0 |
| The module's interrupt handler at `0xA2C` is reached only through a branch the module writes to LS 0, so the function finder never saw it | `[spu-int] TAKEN ... vector->0x00A2C`, then `[pm-end] ... pc=0x00A60`: the run ended at the handler | The handler runs and returns (`[irq] IRET`) |
| The job that wid 4 runs is a 3,344-byte body at `0x011A4100` in the executable, streamed to LS `0x4000`. It had never been lifted | `[spu-ovl-dump] img=1 body ea=0x011A4100 size=3344`; `[spu-smc] microstep img=1 pc=0x04050 ... handing to the interpreter` | Lifted at `0x4000` and registered with `spu_overlay_register_region`. The trail shows its functions being dispatched |
| The body is entered at the offset in its header (`+0x10`, here 0x30) and builds return addresses as `ila` + `a ..., r126`. Neither is visible to the function finder at a non-zero base | `[spu-smc] microstep img=1 pc=0x040DC` | Both are seeded; no microstep or interpreter message in a 60 s boot |

The new values are in `config/targets.json` (`wws_job_pm_extra_funcs`,
`wws_job_bodies`). The base is a constant in the script, because `0xA00` is
where SPURS loads any policy module.

**Not yet fixed.** With all four in place the body runs but the run does not
finish within 25 s. `SPURS_PM_FLOW=1 SPURS_PM_FLOW_ALL=1` prints its trail: it
enters at `0x4068`, calls back into the module several times, and then cycles
through `0x41F0`–`0x4558` and `0x4960`–`0x4AA8`. The trail buffer holds 8,192
transfers and is full, so whether this is a long loop or an endless one is not
known. The render thread is still waiting. Hypotheses, none tested: a lifting
fault in the body (the lifter split `0x45E4`–`0x4CF4` into one function per
instruction, which suggests it could not find the structure); or a loop bound
that depends on something the module should have set up.

**Also changed, effect not shown.** The kernel-poll intercept in ps3recomp
answered 0. The module compares the answer with its own workload id (LS
`0x1DC`) and treats a difference as pre-emption, so 0 is right only for
workload 0. It now answers the current id. The stall is the same with and
without it, so this is correct by the module's code but is not what is holding
wid 4.

**Numbers.** `soak.py 6 30`: six usable boots, all 129 opens and 27 paths, about
605 flips. One of them reached the same end state with 45 flips, which is the
render thread meeting the wid 4 wait earlier. Two bad boots in eight, both the
allocation retry of Phase 18. That is more than Phase 19's 1 in 29, on a sample
too small to call a change.

**Diagnostics.** The hang watchdog in `runtime/spu/spurs_policy.c` used to
judge only the first traced run, which is an idle one at boot. It now keeps
watching and reports the first run that is still going 5 s later.
`SPU_DUMP_OVL=<dir>,0x4000` writes out each body the module streams; the
directory must exist.

**Next.** Find out whether the loop at `0x41F0` ends. Read the body at
`0x011A4100` (it carries the marker `C0DEC0DE` at `+0x20`) and what its loop
counts. Then look for further bodies: this is the first the title has asked
for, and there will be more.

## Phase 19 — It was never parked: frames at one every two seconds (2026-10-12)

Still BCUS98158. Phases 17 and 18 describe main "parked in `sys_cond_wait` at
`lr=0x00B391F4`" as the stop. That reading was wrong. Main waits there by
design, on a request it has handed to a script thread; the title was running
the whole time, at about half a frame per second.

**How it was found.** RPCS3's log shows the title quiet for 8.5 s after network
start-up and then stat-ing `BootRoot.gpb`. Counting graphics imports over a
38 s boot of the port gave 20 `cellGcmSetPrepareFlip` and 18
`cellGcmSetFlipImmediate`, the last of them at the very end of the run. The
script thread was counting frames that took two seconds each.

**Three defects in ps3recomp's cellGcm, each measured.**

| Defect | Evidence | Effect of the fix alone |
|---|---|---|
| 16 IO mapping slots. The title maps its 174 MB heap with 174 calls to `cellGcmMapMainMemory` | 159 `no free IO mapping slots`; `FIFO JUMP to unmapped IO ... drain stops here` | Both messages gone. Frame rate unchanged |
| The queue handler and the second vertical-sync handler were stored and never called | 1 signal to the second-V tick's condition in 45 s; the timer thread on it advanced only by its 10 s timeout | 2,000 signals in 22 s. Frame rate unchanged |
| A `GCM_SET_USER_COMMAND` in the command stream went to the lv2 RSX event path, which has no listener in a title that used `cellGcmSetUserHandler` | `[usercmd] #n arg=0 handlers=0x0 qid=0`; the render thread timing out a 1 s wait on the user handler's object twice a frame, 10 of 10 frames | Frames arrive |

The render thread is the one entered at `func_0079B180`. Phase 18 called it a
sound thread; it is not. The five objects at `0x017213E0` are, by offset: `+0x08`
user handler, `+0x30` flip, `+0x58` queue, `+0x80` second V, `+0xA0` vblank.

**Result.** `SOAK_KEEP_BAD=1 python scripts/soak.py 20 20`:

```
20 x gtvol_opens=129 paths=27 prepare_flip~610 main_lr=0x00B391F4
bad boots: 0 of 20
```

- 610 flips in about 20 s, against 19 in 40 s before.
- Three paths further than before, and the first is RPCS3's next step:
  `.../boot/US/BootRoot.gpb`, then `AgreementRoot.gpb`, then
  `grim/file/contents/serverlist2_us.xml`.
- With a window, the D3D12 backend starts and is fed a 1920x1080 texture bind,
  a shader, a render target and blending. Whether the picture is right has not
  been looked at by a person.
- No bad boot in 20, or in the 8 before them. Phase 18 measured 5 in 30. One
  boot after the fix did go wrong (main stuck at `lr=0x0067E990`, the render
  thread calling through a zeroed vtable), so the fault is rarer, not gone.
  **Hypothesis**, untested: the one-second timeouts changed the timing that
  exposed it. Phase 18's cause is still not found.

**Also in this phase.** `scripts/bootcheck.py` recognises the bad-boot
signatures; `boot.py` retries such a boot and `soak.py` reports and replaces
it (`SOAK_KEEP_BAD=1` to keep them and measure the rate).
`GT5P_PEEK_R31=off,...` dumps memory relative to main's `r31`.

**Next.** Look at the window. Then follow RPCS3's sequence: about 20 s after
`BootRoot.gpb` it opens `TV.DAT` and installs to the hard disk, which the port
has not been seen to start.

## Phase 18 — The "mutex deadlock" is not a deadlock (2026-10-12)

Still BCUS98158. Phase 17 ended with "2 of 8 runs deadlock on a mutex in the
sound code at `lr=0x00B56EDC`; find who holds it". Nobody holds it. This phase
is not finished: the boot is still not the same every run, and the cause below
the symptoms is not found.

**What the bad run actually is.** `0x00B56EB4` is the title's lock wrapper, and
it retries forever on any error from `sys_mutex_lock`. In a bad run that call
*fails* with `ESRCH` because the lock object it was handed has a garbage id.
The id is garbage because memory has been overwritten:

- A page guard on the title's pointer table at `0x0129144C` reports zero writes
  in good runs and thousands in bad ones, every one from `func_007CA908`.
- `func_007CA908` is a pointer-fixup pass over a loaded sound bank
  (`/sound_gt/se/squeal.esgx`, 0x1B210 bytes). `func_007A9B68` calls it with the
  data pointer from the file layer's result. In a bad run that pointer is
  `0x00000880`; in a good run it is `0x204DAE80`. The first bank loads to
  `0x28575B80`. All three end in `0x80` after a `0x..00` boundary, so the
  reading is buffer + `0x880` with a null buffer. **Hypothesis**, not measured:
  the buffer allocation returned null.
- With a null base the fixup pass walks all of memory rewriting words 16 bytes
  apart. Everything else seen in a bad run follows from that: the timer
  threads' list head, the sound objects at `0x0138D0E8`, the failing locks.

**The other signatures.** Thirty boots with default settings: 24 good, and

| Opens | Main is in | Count |
|---|---|---|
| 40 | `func_007CA908`, the runaway fixup above | 1 |
| 2 | `func_00B3BB60`, an allocation that is retried for ever, called from sound setup at `func_007C59D0` | 2 |
| 28 | `func_007FE9E0`, waiting for a sound job event that does not come | 1 |
| 6 | `func_00B57790`, a 2 ms sleep loop under `func_00BFA3C8` | 1 |
| 114 | still loading at the sample; not a failure | 1 |

Four signatures, all during start-up while the sound threads are being
created. Two of them are an allocation that cannot be satisfied.

**Ruled out, each by measurement.**

- A held mutex. The thread and mutex dump shows none that explains it.
- A condition wait returning without a signal. Checked over full syscall
  traces of bad runs: every return has a signal behind it.
- Stack overflow. No guest thread comes near its stack floor.
- The main thread having no identity. It ran as thread id 0, which the kernel
  objects read as "nobody". Fixed, because it is wrong; 5 of 30 still bad.
- The file-descriptor table. `alloc_fd` in cellFs had no lock, so two
  concurrent opens could share a descriptor. Fixed, because it is wrong; this
  title opens one file at a time and 6 of 30 were still bad.
- The lightweight mutex that guards the title's heap. `PS3_LWM_CHECK=1` counts
  threads inside each one; no double entry in 24 boots, 4 of them bad.
- Byte-sized guest stores. They are plain stores of their own width.

**Priorities: suggestive, not shown.** lv2 schedules by strict priority and the
title sets them deliberately (main 1001, sound threads 1, 640, 937, 1001, and
it raises itself to 1 around some locks). Host threads all run at once.

| Setting | Bad runs |
|---|---|
| default | 5 of 30, 6 of 30, 5 of 30 |
| `GT5P_PRIO_HANDOFF=1`: creator waits for a higher-priority new thread to block | 2 of 30, 3 of 24 |
| `PS3_PPU_PRIO_SCHED=1`: guest threads on one host core, host priority from guest priority | 2 of 40 |

Fewer, never zero, and the samples are too small to call the difference real.
The host mapping has seven levels for the title's ten. Both are off by default.

**New tools.**

- `GT5P_THREADS=1` adds to each main-thread sample every guest thread (stack
  pointer, stack free, last syscall, guest call chain) and every held mutex.
- `PS3_SYNCLOG=1` reports a failing `sys_mutex_lock` with the lock object's
  address and contents, and a refused `sys_cond_wait`.
- `PS3_LWM_CHECK=1`, described above.
- `GT5P_GUARD=<addr>:<arm>` already existed; it is what found the writer.

**Next.** Find out what the bank loader's allocation returns in a bad run,
rather than inferring it. The loader's result is built by a virtual call at
`0x00B0C25C` in `func_00B0C0C0`; the request and its result live on main's
stack at `0xCFEFF500`.

## Phase 17 — The Disc Build, BCUS98158 v03.00 (2026-10-12)

This fork's input is the US disc release, not the PSN package the phases below
describe. Every address from here to the next phase heading is a BCUS98158
address; none of them match v02.00. Build-specific constants now live in
`config/targets.json` (see AGENTS.md).

Measured against the v02.00 figures, with ps3recomp `master` at `5244db9` plus
the three local changes listed below:

| | v02.00 | BCUS98158 v03.00 |
|---|---|---|
| End of last executable section | `0xBE0AF4` | `0xE3EC24` |
| Functions lifted | 42,316 | 50,075 |
| Jump tables / seed addresses | — | 280 / 2,872 |
| Imports | 439 in 26 modules | 565 in 31 modules |
| `setjmp` / `longjmp` | `0x00A0A458` / `0x00A0A57C` | `0x00C109F0` / `0x00C10B14` |
| `Wws_Job` policy module | `0x00F4CB80`, 11,648 bytes | `0x01238F00`, 11,648 bytes |
| SPU job images captured | 12 | 12 |
| Game data | `PDIPFS` tree | `GT.VOL`, opened with `boot_from=bdvd` |

`setjmp`/`longjmp` were found by instruction shape (`scripts/find_setjmp.py`);
exactly one pair matched, 0x124 apart as in v02.00. The patch wrapped 2 call
sites.

```
python scripts/soak.py 6 40
run 1: running  gtvol_opens=6   prepare_flip=4  pad_poll=1 crash=0 main_lr=0x00B577A0
run 2: running  gtvol_opens=6   prepare_flip=4  pad_poll=1 crash=0 main_lr=0x00B577A0
run 3: running  gtvol_opens=2   prepare_flip=0  pad_poll=0 crash=0 main_lr=0x007D4308
run 4: running  gtvol_opens=6   prepare_flip=4  pad_poll=1 crash=0 main_lr=0x00B577A0
run 5: running  gtvol_opens=2   prepare_flip=0  pad_poll=0 crash=0 main_lr=0x007D4308
run 6: running  gtvol_opens=6   prepare_flip=4  pad_poll=1 crash=0 main_lr=0x00B577A0
```

So the boot is **not deterministic**: two outcomes in six runs. In four, the
title reads from `GT.VOL`, runs its SPURS jobs with no dispatch miss, starts
polling the pad, and calls `SetPrepareFlip` four times; main then sits at
`lr=0x00B577A0` with `r3=2000` (`func_00B57790`, a wrapper around
`func_00B442A0`). In two, main is at `lr=0x007D4308`, inside the sound engine's
allocator (`func_007D4260`), with two opens. One separate 40 s run logged 124
`GT.VOL` opens and stats under `/dev_hdd0/grim/...`; the soak did not reproduce
that count and the difference is **not explained**. No frame is drawn.

`gtvol_opens` counts opens of one file, so it is not comparable with the 116
distinct `PDIPFS` files of Phase 16. A like-for-like asset count for the disc
build does not exist yet.

### Three runtime faults, each found by the stall it caused

All three are in ps3recomp, changed locally in `../ps3recomp-gt5p-master` and
not sent upstream.

- **SPURS event ports were one table for the whole process.** This build runs
  two SPURS instances: `Wws_Job` on one and the sound engine (`sgx-snd`,
  prefix `sgx-spurs-`) on another, and both attach static port 1.
  `cellSpursAttachLv2EventQueue` returned BUSY for the second, the sound init
  (`func_007D4390`) unwound, and its error path (`func_007DD8B0` →
  `func_007DAEC0`) walked a thread list whose initialiser (`func_007DFA00`) had
  never run: an endless loop reading the null page. Ports are now kept per
  instance. Confirmed by the import trace: `Attach` was followed directly by
  `Detach` and `Finalize`, and after the change it is not.
- **The job-chain walker numbered completed jobs from the start of the walk.**
  The sound service (`func_007FE9E0`) indexes a 128-entry callback table with
  the `data2` of each completion event, per pass. After a few passes the index
  reached 0x19A, the entry read back as `0xFFFFFFFF`, and the load through it
  faulted. The index now restarts at each GUARD. Confirmed by the faulting
  thread's registers: `r6=r30=0x19A`, `r10=0xFFFFFFFF`.
- **SPU user events could not name their SPURS instance.** Added a per-thread
  record of the instance a policy-module worker runs for, used when routing an
  SPU event to a queue. This was written while chasing the fault above on a
  theory that turned out wrong (the events were correctly addressed), so its
  effect is **untested**.

### Compared against RPCS3 (same day)

The disc build was booted in RPCS3 (`rpcs3.exe --no-gui <dump>/PS3_GAME/USRDIR/EBOOT.BIN`)
for about 105 s of game time and its log kept as `scratch/rpcs3.log`
(`scripts/rpcs3log.py` summarises one). RPCS3 holds the log open exclusively
while it runs, so it can only be read after RPCS3 exits. What it settled:

- **Launch arguments.** `EBOOT.BIN` exits into `EMAIN.SELF` with
  `argv = { "/dev_bdvd/PS3_GAME/USRDIR/EMAIN.SELF", "boot_from=bdvd" }`. The
  port's guess was right.
- **The port never ran HLE callbacks.** `g_ps3_guest_caller` was NULL, so
  `cellGameDataCheckCreate2` skipped the title's `funcStat` callback, the title
  retried it three times and then built every hard-disk path without
  `game/BCUS98158/USRDIR`. `main.cpp` now installs the hook. After that the soak
  is the same on every run:

  ```
  python scripts/soak.py 6 40
  assets: 6 6 6 6 6 6        prepare_flip 19 19 19 21 19 19, main_lr=0x00B577A0 each time
  ```

  The early stall at `lr=0x007D4308` did not occur in these six runs or the
  three after the next change. Why installing the hook removed it is **not
  established**.
- **`isNewData` was pinned at 0.** RPCS3 reports new data on a first boot and
  the callback answers `OK_CANCEL`; the port reported existing data and got
  `OK`. `cellGameDataCheckCreate2` in ps3recomp now checks the host directory.
  The port's callback now answers `OK_CANCEL` too.
- **On a first boot this build installs itself to the hard disk.** In RPCS3 it
  creates `grim/` cache directories under `/dev_hdd0/game/BCUS98158/USRDIR`,
  and from about 30 s in it opens `TV.DAT` and writes a `PDIPFS` tree there:
  4,345 files, 4.0 GB, by the time RPCS3 was closed. Whether that install had
  finished is not known.
- **Where the port still falls short.** In RPCS3 the title opens `GT.VOL` 125
  times in its first 10 s and goes on to `sceNp2Init` / `sceNpInit` about 0.4 s
  after `cellSysutilRegisterCallback`. The port opens it 6 times and never
  reaches `sceNp2Init`; it cycles `SetPrepareFlip` / `SetFlipImmediate` instead.
  The divergence is somewhere in that 0.4 s and has not been located: RPCS3's
  log there is dominated by SPU recompiler messages.

### The runtime was reporting every SPU job twice

`libs/spurs/cellSpurs.c` sends a completion event for each job its chain walker
runs (`jc_signal_done`). That is a stand-in for the event the job's own SPU code
sends with `sys_spu_thread_throw_event` on the port the title attached. In this
build the lifted sound jobs run and port 16 is bound to queue 3, so the real
event arrives as well. Queue 3 showed both kinds side by side:

```
[evt] q=3 receive RETURNED: src=0xFFFFFFFF53505501 d1=0x0 d2=0x1000000000 d3=0x400   <- the job's own
[evt] q=3 receive RETURNED: src=0x0 d1=0x20046600 d2=0x1 d3=0x0                      <- the stand-in
```

The sound service counts completions, so the extra ones left main waiting on
queue 3 inside the sound init, or stopped the file thread after six opens. The
stand-in is now switchable (`spurs_set_synth_job_done`, or
`SPURS_NO_SYNTH_DONE=1`) and off for this build through `config/targets.json`.
A first attempt that dropped the stand-in only for jobs seen to report
themselves made things worse (four different outcomes in eight runs) and was
removed.

```
python scripts/soak.py 8 40                  # PS3_VERBOSE=0
assets: 127 127 127 40 127 40 127 127
python scripts/soak.py 6 30 PS3_VERBOSE=1
assets: 127 127 127 127 127 127
```

In the 127 runs the port now tracks RPCS3 through about the first 11 s of game
time: 127 `GT.VOL` opens against RPCS3's 125 in its first 10 s, the same 24
paths in the same order, and the same run of `sceNpInit` /
`sceNpManagerRegisterCallback` / `cellNetCtlGetInfo` /
`sceNpBasicRegisterHandler`. Main then parks in `sys_cond_wait` (syscall 107)
at `lr=0x00B391F4`, under `func_00B391A0` ← `func_00B39260` ← `func_0030BC70`.
That is the same kind of stop as Phase 16's, on a different build; whether it
is the same cause is **not established**. RPCS3's next step is a stat of
`.../projects/gt5p/boot/US/BootRoot.gpb`, which the port does not reach.

In the 40 runs (2 of 8, and none of 6 with verbose logging) main is blocked in
`sys_mutex_lock` (syscall 102) at `lr=0x00B56EDC`, under `func_00B3B998` ←
`func_00B3BA10` ← `func_007A9C20`, in the sound code. The holder of that mutex
has not been identified.

### Not done

- `GAMEDATA.ESP` (20 MB, header is the bitwise complement of a SELF header) is
  untouched and its role is unknown.
- 12 distinct unresolved imports are called during boot: `cellPadInfoSensorMode`,
  `cellKbRead`, `cellHttpInitCookie`, and nine unnamed NIDs in `cellHttp`,
  `sys_io`, `cellUsbd` and `sysPrxForUser`.
- The stat of `/dev_hdd0/PARAM.SFO` fails. On hardware this build installs game
  data to the hard disk; whether it expects that install to exist is not checked.

## Phase 16 — Onto Current ps3recomp (2026-09-28)

A month's work on four sibling ports (Tornado Outbreak, Guitar Hero III, The
Simpsons Arcade Game, Crazy Taxi) landed in ps3recomp `master` — 588 commits since
this port's toolkit base. GT5P was rebuilt on `master` at `795ac34`, re-lifted
with the current lifter from the same function list, `setjmp_patch.py`
re-applied, NID table regenerated.

```
bash scripts/soak.sh 8 40            # master lift + master runtime
assets: 116 116 116 116 116 116 116 116

bash scripts/soak.sh 6 40 ../GT5P-ab/build/gt5p.exe   # AUGUST lift + master runtime
assets: 107 107 107 107 107 107
```

August, same measure: `108 108 7 7 7 7 108 7`. So the runtime removed the
nondeterminism, and the re-lift (42,316 functions against 40,320) adds 107 → 116.

`GT5P_MAINSTACK` on the new build: main is **no longer in the allocator** — the
264-byte retry loop of Phase 15 is gone in both builds. It now sits at the same
place at 20, 30 and 50 s, registers unchanged:

```
[mainstack] in=func_00495294 sp=0xCFEFEB10 lr=0x00954194 ctr=0x00000000 r3=0x0000007B r31=0x2050F518
[hostchain]  func_00495294 ... func_009386C4  func_00954140  func_00954200  func_0015C2C8  func_0015EAE8 ...
```

Host backtraces mis-attribute frames here, so the repeated `func_00495294` is
not a finding. The August-lift build is also in `func_00495294` under
`func_009386C4`, from a different caller — so `func_009386C4` may be a common
wait, not the fault. **Unverified.**

Which upstream change fixed the free-list damage is **not established**. Three
are plausible and were found on GH3 with the same symptom (main spinning on a
failing allocation): per-thread TLS blocks (`cbeae9b` — every thread shared
main's TLS, and GH3 keeps an allocator context in TLS), one callee-save snapshot
per register in the lifter (`135b95a`), and dropped NULL-page stores (`7228188`).
The new build does log NULL traffic that August's could not see:

```
[null-read]  guest read32 from 0x00000000 (NULL+0x0) by guest-fn=0x006A5548   (+15 more, then suppressed)
[null-write] guest wrote16 0x0 to 0x00000016 (NULL+0x16) by guest-fn=0x0093EB00 -- DROPPED
```

`0x006A5548` sits near `func_006A4400`, which Phase 15 bracketed as the call
that corrupted the free list. Proximity, not a link.

### #185 and #189: no effect yet, because the boot stops first

Both rendering PRs from the sibling ports were tried on top of `master`, one at
a time (`gt5p/pr185` = Join + in-FIFO flip commits cherry-picked, its SECUREFILE
commit already superseded on master; `gt5p/pr189` = the PR merged):

```
master + #185:  assets: 116 116 116 116 116 116    one SetPrepareFlip, main parked as before
master + #189:  assets: 116 116 116 116 116 116    one SetPrepareFlip, main parked as before
```

For #185 that is expected rather than a verdict: `cellSpursJoinJobChain` logs
its first eight calls unconditionally and **never appears** — GT5P imports it but
has not reached per-frame work. Retry both once there is a frame loop. The port
stays on plain `master`.

Where main is parked, read from the lift: `func_009386C4` is a syscall wrapper,
and the call it is in is `li r11, 0x6B` → **syscall 107, `sys_cond_wait`, timeout
0** — waiting for a signal nobody sends. Which condition variable and who should
signal it is **not yet established**.

**Caveat:** every Phase 16 number is headless (`PS3_HEADLESS=1`, added this
phase — no window, but the vblank/flip clock and FIFO drain still run). August's
were windowed. A windowed soak has not been run yet.

## Phase 15 — longjmp Has To Actually Jump

> `func_00A0A57C` is the PS3 libc `longjmp`. It restores `r1`, `r2`, `r13`-`r31`,
> `LR` and `CR` from the buffer and ends in `blr`, so on hardware the branch goes
> to the address it just put in `LR` — the `setjmp` call site — and not to
> `longjmp`'s own caller. A static recompiler cannot express that, and
> `ppu_lifter` does not try: it emits that `blr` as a plain `return;`.
>
> So the lifted `longjmp` restored the whole guest register file and then
> returned to whoever called it. That was enough to hold this port at four
> files for the entire project.
>
> ```
>                        before          after
> PDIPFS files opened    4               108 at best, 7 median
> SPU job dispatches     159             113,765
> RSX SetTile            0               6
> RSX SetZcull           0               3
> SetDisplayBuffer       0               2
> SetPrepareFlip         0               1
> ```
>
> GT5P's LZ decoder aborts a decompression by `longjmp`-ing out of it.
> `func_00919060` arms a buffer at `obj+0x186C`; when the input runs dry,
> `func_009200F0` fires it. With the jump modelled as a return, control resumed
> **inside a 32 KB window-copy loop** carrying `func_00919060`'s registers —
> loop bound `0`, wrap pointer set to the object's own address — so the copy
> could never terminate and wrote bytes nearly 4 MB past its window. See
> [Finding It](#finding-it) for how that was cornered, and
> [Making longjmp Jump](#making-longjmp-jump) for the fix.
>
> The game now reads its own content in bulk, runs a continuous SPU job loop,
> and configures tiled render targets, Zcull, double-buffered display and a
> flip handler. It prepares one flip and does not go on to a second, so there
> is no frame loop yet and **still no attract mode**. Runs also vary — most
> stop at 7 files, roughly one in four reaches 108 — so a race sits behind
> this that the fix did not address.

### Making longjmp Jump

There are exactly two `setjmp` sites and three `longjmp` sites in the whole
binary, which makes a targeted fix practical. `scripts/setjmp_patch.py`:

- expands a **real host `setjmp`** at each guest-`setjmp` call site — it has to
  be lexically in the frame that will be jumped back into, so it cannot hide
  behind a helper;
- keeps the original lifted `longjmp` body, which is what restores the guest
  register file, and then fires a host `longjmp` to reach the site.

The guest therefore resumes with exactly the register state it expects; only
the transfer of control becomes host-side. Buffers are tracked on a stack and
each arming function's depth is restored on the way out, so a buffer whose
frame has returned can never be jumped into. Frames jumped over hold no C++
objects with destructors — lifted code is plain C in C++ clothing — so the
unwind is safe.

Re-run it after every re-lift, like `instrument_alloc.py`; `generated/` is
rebuilt wholesale.

### Finding It

Worth recording, because the symptom pointed nowhere near the cause. The chain
from the stalled file to the decoder took six layers of vtable dispatch, and at
the bottom `func_00956D20` was entered twice and returned once. It had no
blocking primitive in it, so it was spinning — but 2,280 bytes of dense bit
manipulation is not something to read hoping to spot the loop.

`scripts/bbcount.py` settles it mechanically: drop a counter on every label in
one lifted function and print the hottest. Four blocks at
`0x00957100`-`0x00957118` took 49.8 million hits each. Sampling that loop's
registers is what actually named the bug:

```
iteration          r28 wrap        r26 bound        r31 cursor
        1     base + 0x8000      base + 13        base + 9
    1,000     base + 0x8000      base + 1216      base + 1051
1,000,000     base + 0x8000      base + 25788     base + 25675
5,000,000     0x0112D640         0                base + 3,992,907
```

A million iterations of a perfectly healthy circular window copy, and then the
wrap and bound become values from a completely different function. Registers
that change without any instruction in the loop writing them means a call did
it — and the only call on that path was the one that fires the `longjmp`.

Instrumenting the *setup* block closed it: the loop was always entered with a
correct bound and wrap, every time. So it was never bad input, it was a bad
return.


### The Boot Does Not Stall On I/O

It runs out of heap, and it runs out of heap because the free list is corrupt.

Every thread dump in this document was blind to the one thread that matters.
`main` is created by `src/main.cpp`, not by `sys_ppu_thread_create`, so it never
appears in `g_ppu_threads` and `GT5P_THREADS=1` has never shown it. `GT5P_MAINSTACK`
unwinds it directly, and it has been sitting in the same place the whole time:

```
func_00010230 → func_00010368 → func_000107F8 → func_00011A28
  → func_00687C70 → func_00687F18 → func_006679A0
  → func_00937EF0 → func_00937E2C → func_0094FF30
```

`func_009F3FF0` is `while (alloc(size) == 0) { run a reclaim hook; yield 2 ms }`,
and instrumenting the allocator says exactly what it is retrying:

```
[pred] func_00937EF0(size=264) -> 0x00000000   calls=2155 zero=2000
[oom]  alloc(heap=0x011806B0 size=264 align=16) FAILED
       hdr: 00F76D48 20000000 2ADFFF80 20000000
```

**Main is spinning on a 264-byte allocation** against a 182 MB arena
(`0x20000000..0x2ADFFF80`). Not waiting on a file, a decompressor, an SPU job,
a flip or a lock. Out of memory.

#### Why a 182 MB arena cannot serve 264 bytes

One allocation eats it:

```
[layout] capacity=0x9AD29380 (2597491584)  used=0x003F5000 (4149248)  remainder=-1701624960
[giant]  2593342336 bytes (0x9A934380) granted at 0x656CBC80
```

`func_006679A0` lays out its buffers and then claims the remainder as
`capacity - used`. `used` is a sane 4 MB. The **capacity is already garbage
coming in** — 2.6 GB, from `func_00937CE0` → `func_00950650`, which walks the
heap's free list looking for the largest free block. So a free-list node is
carrying a nonsense size, and:

1. the query reports 2.6 GB free,
2. `func_006679A0` believes it and asks for the remainder,
3. `func_0094FF30` **grants** it, handing back `0x656CBC80` — far outside the
   arena,
4. the arena's bookkeeping is now destroyed and every later allocation fails,
5. main retries 264 bytes forever and the boot stops.

The size varies between runs (`0x9A934380`, `0xFFFFFFFF`), which is what a
corrupt node looks like rather than a fixed miscalculation, and it is why the
outcome is a spread rather than a constant.

This is the long-standing heap damage recorded in this document — the allocator
"walking into `0x42Cxxxxx`" — finally connected to a symptom. It also explains
why the asset count moves around: how far the boot gets depends on when the
free list is trampled.

#### The free list contains live blocks

Reporting any node whose size exceeds the arena names the bad nodes, and what
is *in* those size fields is the tell:

```
[freelist] node=0x200AC930 size=0x42C80000  -- larger than the arena
[freelist] node=0x2008A06D size=0x6C657665  -- larger than the arena
[freelist] node=0x200AC9B0 size=0x29EC3940  -- larger than the arena
```

`0x42C80000` is the `0x42Cxxxxx` value this document has chased for months. It
was never an address the allocator wandered to — it is a **pointer sitting in a
size field**. `0x6C657665` is ASCII `"leve"`. `0x29EC3940` points back into the
arena. And node `0x2008A06D` is not even 4-aligned, so the walk had already
followed a bad `next` into the middle of something.

Pointing the write watch at one of those nodes settles what it is:

```
[ww] 0x200AC930 <- 0x0  (w8) guest-fn=0x00A0B970      <- zero-fill
[ww] 0x200AC930 <- 0x51 (w1) guest-fn=0x00921730
[ww] 0x200AC931 <- 0xD4 (w1) guest-fn=0x00921730
```

Ten distinct functions write to that block in one boot — 32 writes from
`func_00921730` alone, with `func_00A0B970` zero-filling it first. Both are
exact function starts, so this is not the nearest-preceding attribution the
write watch usually gives. That block is **ordinary live memory in active use**,
and the free list points into it.

So this is not a buffer overrun spilling into a neighbouring header. A block is
on the free list *and* allocated at the same time: a premature free, a double
free, or a free-list insertion that keeps a node it should have unlinked. The
size the allocator then reports is whatever the live data happens to look like,
which is why it differs every run and why the asset count is a spread.

#### Retraction: `[node+4]` is an end pointer, not a size

Two claims recorded above this line were wrong, and both are withdrawn. They
were built on reading the free-list node's `+4` field as a block size. It is
not. `func_0094F788` does

```
lwz  r0, 4(r4)         ; r0 = [node+4]
...
subf r0, r4, r0        ; r0 = [node+4] - node
```

and `func_00950650` performs the identical subtraction. The field is the
block's **end pointer**; the size is `end - node`.

That invalidates the filter those findings rested on. Flagging any node whose
`+4` exceeded the arena size flagged legitimate nodes:

```
node=0x200AC9B0  end=0x29EC3940   in arena -> 165,769,104 bytes free
node=0x200ACA30  end=0x2942C390   in arena -> 154,663,264 bytes free
```

Those are ordinary large free regions in a mostly-empty 182 MB arena, not
damage. Three of the six "corrupt" nodes were healthy.

The second claim — that the nodes lay inside live allocations, so blocks were
free and allocated at once — fails for a separate reason: the cross-reference
table recorded every block the allocator ever returned and never removed the
ones that were freed. "Inside a live allocation" therefore only ever meant
"inside memory that was allocated at some point", which is exactly where a free
node *should* be. The check could not have produced any other answer.

So there is no evidence for a use-after-free, for the free list containing live
blocks, or for a bucket head pointing into the asset buffer. Those readings are
withdrawn.

#### What actually survives

Two nodes really are corrupt, and they are the ones whose end pointer lands
outside the arena entirely:

```
node=0x200AC930  end=0x42C80000   OUT OF ARENA
node=0x2008A06D  end=0x6C657665   OUT OF ARENA  (ASCII "leve")
```

`0x42C80000` is the long-unexplained `0x42Cxxxxx` value, and it is an end
pointer rather than an address the allocator wandered to. A node carrying an
end pointer outside the arena makes `end - node` enormous, which is what
`func_00950650` reports as free space, and the rest of the chain follows from
there. That part is unchanged and was measured directly, not inferred:

```
[layout] capacity=0x9AD29380  used=0x003F5000  remainder=-1701624960
[giant]  2593342336 bytes granted at 0x656CBC80
[pred]   func_00937EF0(size=264) -> 0x00000000   calls=2155 zero=2000
```

The allocator's own translation is clean, checked mechanically rather than by
eye: `scripts/audit_cmp.py` verifies every compare's signedness, width and CR
field against its encoding, and `scripts/audit_branch.py` verifies every
conditional branch's CR bit and sense. Both pass across the whole allocator
family. Nothing outside the allocator writes to the bucket array either — a
write watch over `heap+0x00..0x50` names only `func_0094F788`, `func_0094F818`,
`func_0094FC08` and the constructor.

So the open question is narrower than the retracted version implied: **how does
a node end up with an end pointer outside the arena**, when the code that
maintains those nodes is correctly translated and is the only thing writing
them.

#### Who writes the node fields

The bucket heads are never bad. Every value written into the bucket array over
a whole boot is either zero or a valid in-arena pointer (217 distinct values,
none outside `0x20000000..0x2ADFFF80`), and `0x200AC930` — the node the walk
trips over — is never installed as a head at all. Heads never exceed
`0x20089F20`.

So the walk starts from a good head and follows a `next` into trouble. Watching
the 32 bytes at that highest head says who touches them:

```
[ww] 0x20089F2C <- 0x0        (w8) guest-fn=0x00A0B970   <- memset
[ww] 0x20089F2C <- 0xC2C0A3D7 (w4) guest-fn=0x006C2D5C
     writers over the window: func_00A0B970 x16, func_006C2D5C x6, func_006A4400 x2
```

`0x20089F2C` is a node's `next` field. `0xC2C0A3D7` is not a pointer — as
IEEE-754 it is about `-96.3`. Float data is being written into the bytes the
allocator reads as list linkage.

And one of the three writers is **`func_006A4400`** — the arena builder whose
measuring pass and filling pass disagree by `0x468` bytes, recorded in this
document long before any of this and never explained. It writes into the same
node.

One caveat, stated because three readings were withdrawn above for exactly this
kind of gap: this shows *who writes those bytes*, not *whether the block was on
the free list at the time*. Establishing the ordering — free, then written, then
walked — is the next measurement, and it is the one that would turn this from a
strong association into a cause.

#### func_006A4400 corrupts the free list

Bracketing the suspects with a validator settles the ordering. `gt5p_freelist_bad`
walks every bucket (`heap+16..heap+76`) following `next` at `+12`, checking each
node is aligned, inside the arena, and carries an end pointer above itself.
Called before and after each candidate:

```
[flcheck] func_006A4400: free-list bad-chains 0 -> 1
[flcheck] func_006A4400: free-list bad-chains 0 -> 1
[flcheck] func_006A4400: free-list bad-chains 0 -> 1
```

Three runs, same result. **The list is intact going into `func_006A4400` and
broken coming out.** `func_006C2D5C`, the other writer, never trips it.

`func_006A4400` is not a new suspect. It is the arena builder recorded in this
document long ago for a defect nobody could connect to a symptom: its measuring
pass and its filling pass disagree by `0x468` bytes, because the measuring pass
reads back an out-pointer it never wrote and branches on it. `GT5P_ARENA_ZERO=1`
demonstrates the discrepancy and crashes. That overrun lands in a free-list
node.

So the chain is closed, and every link was measured rather than inferred:

```
func_006A4400 overruns its measured extent into a free-list node
  → the node's end pointer becomes garbage (0x42C80000, ASCII "leve")
  → func_00950650 reports 2.6 GB free
  → func_006679A0 asks for the remainder; the allocator grants it
  → the returned pointer is outside the arena; bookkeeping destroyed
  → main spins on a 264-byte allocation forever
  → the loader is never asked for anything -> no assets -> no frame
```

The fix is to make the two passes agree, which is a bounded piece of work on a
function this document already describes in detail. That is where the next
session should start, and unlike everything else tried here it is a *fix*
rather than another measurement.

#### A fix was tried and rejected

`func_006A4400` itself is correctly lifted — `scripts/audit_cmp.py` and
`scripts/audit_branch.py` both pass on it, and its two branches decode exactly
as the C reads. It is a bump allocator with **no bounds check**:

```
func_006A4400(ctx, out, size):
    if ([ctx] != 0 && out != 0):
        *out = [ctx] + [ctx+4]
        memset(*out, 0, size)
    [ctx+4] += size
```

Catching the call that breaks the list shows the shape of the damage:

```
[flcheck] func_006A4400(ctx=0xCFEFF308 out=0xCFEFF2FC size=620)
          bad-chains 0 -> 1   ctx:[base=0x20089DA0 off=0x2C4]
```

`out` is a stack slot, so `*out` is not what corrupts anything. The arena's
**base is `0x20089DA0`, and the highest free-list bucket head is `0x20089F20`**
— `base + 0x180`. The bump region overlaps memory that is still on the free
list, and the offset is already at `0x2C4`, well past it. The `memset` walks
over free-list nodes.

That is the `0x468`-byte measure/fill discrepancy showing up as a symptom at
last: the fill pass writes more than the measure pass reserved.

The obvious fix was tried. On the measuring pass the arena base is still 0, so
the write to `*out` is skipped and the caller reads an uninitialised slot —
which is the mechanism this document guessed at long ago.
`GT5P_ARENA_OUTZERO=1` writes a definite 0 into that slot on the skip path so
the measuring pass sees a stable value. It does not work:

```
control                7  108  108  108  7      (3 of 5 reach 108)
GT5P_ARENA_OUTZERO=1   7    7  108    7  7      (1 of 5)
```

Measurably worse, so it is off by default and kept only as a documented dead
end. Whatever the measuring pass is actually reading, zero is not the value
hardware gives it — or the disagreement is somewhere else entirely and the
uninitialised read is a red herring.

#### Retraction: the pass comparison summed unrelated work

The analysis in this section built on a two-pass model — one measuring pass over
the whole layout, then one filling pass — and compared their totals. Interleaving
the arena log with a shared sequence number shows that model is wrong:

```
#1..#10   measure  68, 0, 5, 3, 0, 0, 0, 0      base=0x00000000
#11..#20  fill     68, 0, 5, 3, 0, 0, 0, 0      base=0x20089C80   <- agrees exactly
#21..#30  measure  68, 12, 5, 3, 0, 0, 0, 0     base=0x00000000
```

There are **many independent measure/fill pairs**, one per object, and the
overwhelming majority agree byte for byte. Summing all the `measure` lines
against all the `fill` lines compares unrelated work, and the "16 calls versus
48 calls" figure was an artefact of that plus a 400-line print cap. The sizes
also differ between runs — one boot shows `620, 141, 9, 10`, another `2220,
160, 48` — so the specific `0x468` match, striking as it was, cannot carry the
weight put on it.

What that leaves is narrower and still worth having: **at least one
measure/fill pair disagrees**, with the measuring side counting 0 where the
filling side counts 31, and `func_006A4400` demonstrably takes the free list
from valid to invalid. Finding *which* pair disagrees needs the pairs kept
separate — matched on the arena context pointer — rather than aggregated, and
the print cap removed.

The measurements that do not depend on this model are unaffected and are listed
in the next section.

#### Paired by context, the 0x468 is real

The retraction above was right that summing all `measure` lines against all
`fill` lines compares unrelated work. It was too cautious about the number
itself. Redoing the measurement properly — every call logged with its arena
context pointer, no print cap, sequences kept separate and compared per context
— gives a clean result:

```
distinct arena contexts: 2
ctx=0xCFEFF308 DISAGREES
   measure( 8) [68, 12, 5, 3,   0, 0, 0, 0]
   fill   (40) [68, 12, 5, 3, 620, 9, 10, 7, 7, 10, 141, 11, 15, 17, 18, ...]
   totals: measure 88, fill 1216, diff 1128 (0x468)
contexts that disagree: 1 of 2
```

**One context out of two, and the difference is exactly `0x468`.** The first
four reservations agree; then the measuring pass emits four zeros and stops at
eight calls while the filling pass continues to forty. So the number this
document has carried for years is not an artefact — it belongs to a single
arena, `0xCFEFF308`, whose measuring pass enumerates nothing where its filling
pass enumerates thirty-six items.

The method matters here and is worth stating for whoever repeats it: pair on
the context pointer, drop the print cap, and compare sequences rather than
totals. Aggregating across contexts produces the same headline number by
coincidence and will mislead about everything else.

#### Why the write watch cannot see the descriptors arrive

Watching `0x20085BE0` for the copy is futile, and it is worth knowing why before
anyone spends a run on it. `LBP_WW` is built on `vm_write*`, so it sees writes
made by lifted guest code — and `cellFs` reads do not go through it:

```
bytes_read = fread(gptr(buf), 1, nbytes, s_files[fd].host_fp);
```

The read writes **straight into guest memory through the host `fread`**. Any
buffer whose contents arrive from a file is invisible to the write watch. Five
consecutive runs confirm the shape: every one reaches `count=31`, and every one
records **zero non-zero writes** to that buffer. The data is there; the watch
structurally cannot see it land.

#### What the enumerator actually sees

Logging every call in order is far more informative than watching the memory:

```
#1..#13  count=0   ""
#14      count=8   "mix0, F:-100:100, 0, Channel 0 blend, %..."
#15      count=0   ""
#16      count=8   "mix0, ..."                       <- the same descriptor again
#18      count=16  "type, L:NONE:LPF:HPF:BPF..."
#19      count=0   ""
#20      count=16  "type, ..."                       <- again
#22      count=8   "use, B, 1, Use.igain, ..."
#24      count=8   "use, ..."                        <- again
```

Two things stand out. Each descriptor is counted **twice** with an empty count
between — which is the measure/fill pairing seen from the enumerator's side.
And **the first thirteen calls are all empty**: early on the scratch buffer
never holds a descriptor at all, and only later do real ones appear.

That is the ordering problem in its plainest form. The descriptors are static
data in the ELF, so nothing has to be computed; something simply has not copied
them into scratch yet when the earliest reservations are measured. Which
objects those first thirteen belong to, and what sets their descriptor pointer,
is the next thing to find — and it is a question about object initialisation
order, not about memory corruption.

#### The descriptor virtual, and the end of the trail

`func_006A3D70` has exactly one caller, `func_006C2D5C`, and immediately before
the count there is a `bctrl`:

```
006C2DFC  bctrl                    ; obj->method(...) fills the scratch buffer
006C2E04  lwz r3, 184(r29)         ; the scratch pointer
006C2E08  bl  func_006A3D70        ; count its tokens
```

Logging the resolved target alongside each count settles what varies:

```
#5 obj=0x010CFFBC -> func_006C5CF8   count=0   ""
#6 obj=0x010CFFBC -> func_006C5CF8   count=0   ""
#7 obj=0x010CFFBC -> func_006C5CF8   count=0   ""
#8 obj=0x010CFFBC -> func_006C5CF8   count=31  "lfe-send, F:0:100, 0, LFE send level..."
```

**Same object, same method, three empty results and then the real descriptor.**
It is not a different virtual being dispatched for the early calls, and it is
not a different object — `func_006C5CF8` simply produces nothing until
something it depends on is ready. (`func_006BEE34` covers the first four calls
and behaves the same way.)

So the whole chain terminates in one function:

```
func_006C5CF8 yields an empty descriptor on early calls
  -> the token count is 0 instead of 31
  -> the reservation is sized 0 instead of 620
  -> arena 0xCFEFF308 is short by exactly 0x468
  -> the fill pass overruns a free-list node; its end pointer goes out of arena
  -> the free-space query reports 2.6 GB; the giant allocation is granted
  -> arena bookkeeping is destroyed; main spins on 264 bytes forever
  -> the loader is never asked for anything: no assets, no frame, no attract mode
```

Every arrow in that chain was measured. Two qualifications belong with it, and
the second corrects the first — both are kept because the correction is the
useful part.

The top line is an **observation, not an explanation**. `func_006C5CF8`
demonstrably yields an empty descriptor on early calls and everything below
follows, but *why* it does was pursued and not closed. Tracing upward reaches
`func_006CF50C` -> `func_006CF080` -> `func_006CD504`, and the zero those
return is fully explained: a pending flag, two `cellSpurs` imports, and the
second one's result passed straight back. Both imports resolve. A zero there
plausibly means *no work pending* rather than *rejected*.

The first version of this note then said the link to the empty descriptors "was
never established", which overstates it in the other direction. It was
established by correlation on a shared tick — `func_006CF50C` returning zero
alongside `count=0`, and returning a handle alongside `count=8` — but on **two
paired samples**, not at scale. A broader test needs the `[look]` and `[enum]`
probes re-instrumented, which the clean shipping build deliberately does not
carry.

That widening was then done, and it gives a sharper answer than either earlier
version. Pairing every enumerator call with its nearest preceding
`func_006CF50C` across a full boot:

```
CF50C == 0  and count == 0 :  6
CF50C == 0  and count >  0 :  0      <- never happens
CF50C != 0  and count == 0 :  1      <- counterexample
CF50C != 0  and count >  0 :  1
```

Eight pairs, seven agreeing. The shape matters more than the ratio: a zero from
`func_006CF50C` is **sufficient** for an empty descriptor — it never once
coincided with a populated one — but it is **not necessary**, because the
lookup also succeeded on a call whose descriptor stayed empty.

So the link is real and one-directional. When the lookup fails the descriptor is
empty and the arena under-measures; but there is at least one other route to an
empty descriptor that this work never identified. Fixing whatever makes
`func_006CF50C` return zero would therefore be necessary and possibly not
sufficient, which is worth knowing before anyone spends a session on it.

`func_006C5CF8` turns out to be a **nine-way jump-table dispatch**, one case per
parameter group:

```
cmplwi cr7, r5, 8
bgt    -> default (return without filling)
lwzx / add / bctr through a 9-entry table at 0x006C5D28
```

The obvious suspicion — that a case is missing and the method falls through —
does not hold. Every target is correctly lifted:

```
case 0  0x006C5D80  START of func_006C5D80
case 1  0x006C5E3C  START of func_006C5E3C
...
case 8  0x006C5D4C  inside func_006C5CF8 (+0x54)
```

Eight of the nine are function starts *because of the jump-table seeding earlier
in this session*, and `scripts/jumptables.py` finds the table. So the dispatch
is sound and the empty descriptors are the game's own index-dependent
behaviour, not a translation failure.

Logging the dispatch index rules that out too. The early empty calls and the
later populated ones use **the same indices**:

```
#5  index=7 -> count=0   ""
#6  index=8 -> count=0   ""
...
#14 index=8 -> count=8   "mix0, F:-100:100, 0, Channel 0 blend, %..."
#15 index=7 -> count=8   "ch0, F:0:400, 100, Channel 0 level, %..."
```

Same method, same index, empty early and populated later. So it is state, not
selection. Case 8 of the switch is `0x006C5D4C`, and what it reads is a global:

```
lwz r9, -27716(r2)
lwz r3, 6276(r9)        ; a global registry pointer
bl  0x006C5C2C          ; fetch the descriptor through it
```

That is the fact. The implication — that the pointer at `[[r2-27716]+6276]` is
not populated when the earliest reservations are measured — was flagged as an
unverified hypothesis, then checked. **It is wrong**, and the check took one
run:

```
#5 index=7 -> func_006C5CF8  registry=0x20039780  count=0   ""
#7 index=7 -> func_006C5CF8  registry=0x20039780  count=31  "lfe-send, ..."
#8 index=8 -> func_006C5CF8  registry=0x20039780  count=0   ""
```

The pointer is non-null and **identical on every call**, empty results and
populated alike. Worse for the reading, `0x20039780` is the SPURS job chain
address that appears throughout these logs — so it is not a descriptor registry
at all.

So the difference is neither the dispatch index nor that global.

`func_006C5C2C` is a shim onto `func_006C5B60`, which runs a five-call lookup.
Tracing it gives raw data and no conclusion, recorded here as the starting
point rather than dressed up as a finding:

```
[look] func_006CD570(0x20039780, 0x01079C00) -> 0x20039780
[look] func_006CF50C(0x20039780, 0x01079C00) -> 0x20039780
[look] func_006CF6A4(0x20039780, 0x00000102) -> 0x20039780
[look] func_006CF57C(0x20039780, 0x00000102) -> 0x20039780
[look] func_006CEC74(0x20039780, 0x00000102) -> 0x00000000
[look] func_006C5B60(0x20039780, 0x01079C00) -> 0x00000000
```

The chain repeats with what look like group tags in the second argument —
`0x102`, `0x104`, `0x200`, `0x201`, `0x3100` — and in every sample
`func_006CEC74` returns **0**, so `func_006C5B60` returns 0 as well.

Correlating the two probes on the shared tick — the run the previous paragraph
asked for — identifies where they part company:

```
populated (count=8):
  #196 func_006CF50C(0x20039780, 0x01079C60) -> 0x20039780     <- succeeds
  #199 func_006CEC74(0x20039780, 0x00002101) -> 0x40000000
  #200 func_006C5B60(0x20039780, 0x01079C60) -> 0x40000000
  #201 enum -> count=8   "mix0, F:-100:100, 0, Channel 0 blend, %..."

empty (count=0):
  #62  func_006CF50C(0x20039780, 0x01079C0C) -> 0x00000000     <- FAILS
  #68  enum -> count=0   ""
```

**`func_006CF50C` is the discriminator.** It returns a valid handle for the
descriptors that arrive and **zero** for the ones that do not, and the two calls
differ in their second argument: `0x01079C60` succeeds, `0x01079C0C` fails. Both
are pointers into the same static region, so this is a lookup for a *different
descriptor object*, one of which is not found.

That is a correlated observation rather than an inference, and it replaces the
"registry not populated" guess that was tested and refuted above.

Dumping the two objects identifies them outright. They are tables of
`{name, image, size}` triplets naming **SCE audio effect modules**:

```
FAILS    0x01079C0C:  socedmix    @0x00F13500 (0x8E60)
                      socelverbx  @0x00F42F80 (0x6300)
                      soceumix    @0x00F1C380 (0x4FE0)
SUCCEEDS 0x01079C60:  soceamp     @0x00F21380 (0x3610)
                      socethru    @0x00F2F680 (0x24E0)
                      soceagc_gt5 @0x00F49300 (0x3860)
```

Downmix, late reverb and upmix fail; amplifier, passthrough and automatic gain
control succeed. All six are raw SPU code images present in the ELF — none is
missing — and `func_006CF50C` forwards to `func_006CF080` with the image pointer
and a 16-aligned size, so it is an SPU module registration that returns zero for
three of the six.

The three that fail are the three **largest**, which invites an obvious guess:
that they are the SPU images this port already holds back because the SPU lifter
cannot process them, one of which is 36,448 bytes — exactly `socedmix`'s
`0x8E60`. **That is wrong.** The held images all begin with sixteen zero bytes;
they are SPURS job LS dumps, while `socedmix` begins `43 F7 3A 02 43 87 A6 82`.
Same size, different data, and one command to check.

`func_006CF080` opens with two capacity checks against the job chain:

```
[jc+17024] + 1  >= 0x80    -> reject
[jc+19096] + 3  >= 0x101   -> reject
```

Neither is the cause. Logging both with each result shows the counters idling
far below their limits — and something more useful:

```
[cap] img=0x00F13500 size=2278  count=1/128  slots=4/257  -> 0x00000000   REJECTED
[cap] img=0x00F13500 size=2278  count=1/128  slots=4/257  -> 0x20039780
[cap] img=0x00F13500 size=2278  count=1/128  slots=4/257  -> 0x00000000   REJECTED
[cap] img=0x00F13500 size=2278  count=1/128  slots=4/257  -> 0x20039780
```

**The same image at the same size is both rejected and accepted.** So the
rejection is state-dependent, not a property of the module, and no per-module
explanation can be right.

That also qualifies the section above. The sizes reaching `func_006CF080`
(`4322`, `3353`, `2278`) do not match the descriptor table's (`0x8E60`,
`0x6300`, `0x4FE0`), so the mapping from "the table entry at `0x01079C0C`" to
"these registration calls" was never established — the module *names* are solid,
the claim that `socedmix` specifically is the one failing is not.

Mapping every branch into the tail settles where the zero comes from. The
failure path at `0x006CF3C4` is reached by **exactly two** branches — and both
are the capacity checks that were just measured as untripped. So the zero return
comes from one of the other exits, and those are gated on arguments the probe
never captured:

```
0x006CF148  branch if r8  <= 0      -> 0x006CF3F0
0x006CF160  branch if r0  <  0      -> 0x006CF3F0
0x006CF1A0  branch if r10 <= 0      -> 0x006CF46C
0x006CF1B8  branch if r0  <  0      -> 0x006CF46C
0x006CF188  branch if r0 == r11     -> 0x006CF4A8
```

The obvious conclusion — that the deciding values live in `r6`-`r10`, which the
wrapper never forwarded — was tested by widening the wrapper. **It is wrong.**

```
[cf080] r6=0 r7=0 r8=0 r9=0 r10=0 -> 0x20039780
[cf080] r6=0 r7=0 r8=0 r9=0 r10=0 -> 0x00000000   REJECTED
[cf080] r6=0 r7=0 r8=0 r9=0 r10=0 -> 0x20039780
[cf080] r6=0 r7=0 r8=0 r9=0 r10=0 -> 0x00000000   REJECTED
```

Every argument register is identical across accepted and rejected calls. The
inputs really are the same, so the rejection depends on **state inside the job
chain object or in globals**, not on anything passed in.

That also corrects the branch reading above: `r8` and `r10` at those tests are
values the function has computed by then, not the arguments of the same name.
Reading a comparison's register operand and assuming it is still the incoming
argument is a mistake worth naming, because it is easy to make when skimming a
291-instruction function for its exits.

Instrumenting the blocks those branches jump to does not isolate it either.
They fire **several times within a single call**:

```
[exit] func_006CF080 leaves via 0x006CF3E4 (hit 1)
[exit] func_006CF080 leaves via 0x006CF46C (hit 1)
[cf080] ... -> 0x20039780
[exit] func_006CF080 leaves via 0x006CF3E4 (hit 2)
[exit] func_006CF080 leaves via 0x006CF3F0 (hit 1)
[exit] func_006CF080 leaves via 0x006CF4D4 (hit 1)
[cf080] ... -> 0x20039780
```

So they are not exits — they are intermediate targets inside the tail, and the
function loops through them. That is the third structural reading of this one
function to be wrong: first "gated on the capacity checks", then "gated on
arguments `r8`/`r10`", now "these blocks are the exits". Each was a reasonable
inference from a partial disassembly and each was contradicted by the first
measurement taken against it.

The honest state, and the point at which guessing about this function's control
flow was abandoned:

- `func_006CF080` returns zero for some calls and a valid handle for others
  with **identical argument registers** (`r3`-`r10` all the same).
- Its two capacity checks are not tripped (`1/128`, `4/257`).
- The branch targets in its tail are reached repeatedly within one call, so the
  control flow is a loop, not a chain of guarded exits.

Anyone continuing should treat the disassembly of this function as unread
rather than trusting the three readings above. So rather than leave that as
advice, here is the trace itself — `scripts/bbcount.py` on `func_006CF080`,
dumping at 200,000 block entries (`GT5P_BB_AT`):

```
0x006CF114  23532      0x006CF18C  11762
0x006CF298  23532      0x006CF210  11762
0x006CF3E4  23532      0x006CF46C  11762
0x006CF2AC  23531
0x006CF3F0  23530
0x006CF428  23530
0x006CF4D4  23527
```

Twelve blocks, two clean tiers: a main loop running ~23,500 iterations in the
sampled window, and three blocks entered on almost exactly half of them
(`11762` against `23532`). The blocks previously mislabelled as guarded exits —
`0x006CF3E4`, `0x006CF3F0`, `0x006CF46C`, `0x006CF4D4` — sit squarely in those
tiers, which is why instrumenting them as exits produced multiple hits per call.

Building a proper control-flow map — every branch target and fall-through,
annotated with those hit counts — overturns the premise this whole subsection
was built on:

```
block        hits     successors
0x006CF114   23532    -> 0x006CF18C
0x006CF18C   11762    -> 0x006CF46C
0x006CF210   11762    (falls through)
0x006CF298   23532    -> 0x006CF2AC
0x006CF3C4      -     -> 0x006CF114     <-- BACK EDGE
0x006CF3E4   23532    -> 0x006CF114     <-- BACK EDGE
0x006CF3F0   23530    -> 0x006CF18C     <-- BACK EDGE
0x006CF428   23530    -> 0x006CF18C     <-- BACK EDGE
0x006CF46C   11762    -> 0x006CF210     <-- BACK EDGE
0x006CF4D4   23527    -> 0x006CF18C     <-- BACK EDGE
```

**`0x006CF3C4` is not a failure path.** It branches *backward* to `0x006CF114`,
and so does every other block in the "tail". `func_006CF080` is a worker **loop**
spanning `0x006CF114`-`0x006CF4FC`, and the two comparisons at the top that were
read as capacity rejections are loop-entry conditions.

Every structural claim made about this function earlier in this section was
therefore inverted from the start: "the failure path at `0x006CF3C4`", "gated on
arguments `r8`/`r10`", "these blocks are the exits". All three followed from
reading a forward branch near the end of a listing as an exit, without building
the graph. The block-hit counts had been sitting there saying otherwise —
23,532 entries to something described as a one-shot rejection should have been
the tell.

Following that through gives the first coherent account of this function.
`0x006CF3C4`, the block both "capacity checks" jump to, is a **flush and retry**:

```
006CF3C4  bl 0x006CEC74        ; flush
006CF3C8  mr r3, r31
006CF3CC  bl 0x006CD570        ; wait / kick
006CF3E0  bc 0x006CF114        ; back into the loop
006CF3E4  li r27, 16384        ; reset the chunk size to 16 KB
006CF3EC  b  0x006CF114
```

So those two comparisons mean *"if the job chain is full, flush it and go
round again"* — not *"reject the request"*. And the whole function has exactly
**one** exit, the single `blr` at `0x006CF3C0`, reached by falling out of the
loop.

Put together with the 16 KB chunk reset and the ~23,500 iterations, this reads
as a **chunked transfer loop** that pushes an SPU image through the job chain,
flushing whenever the chain fills. That is a completely different object from
the "module registration with guarded rejections" this section assumed for
several rounds.

Tracing assignments to `r3` finishes the job. There are five in the whole
function and none is an explicit return value — the epilogue restores registers
and returns whatever `r3` already held. The value comes from `func_006CD504`,
confirmed by instrumenting both:

```
[cd504] func_006CD504(0x20039780) -> 0x20039780
[cd504] func_006CD504(0x20039780) -> 0x00000000   ZERO
[cd504] func_006CD504(0x20039780) -> 0x20039780
[cd504] func_006CD504(0x20039780) -> 0x00000000   ZERO
```

And `func_006CD504` is 27 instructions:

```
cmpwi r3, 0                 ; null -> return 0
r0 = [r3 + 20232]           ; a pending flag
if (r0 == 0) return r3      ; nothing pending -> return the chain, non-zero
bl 0x00BDF674               ; cellSpurs import, NID 0x738E40E6
mr r3, r31
bl 0x00BDF6D4               ; cellSpurs import, NID 0xA7C066DE
li r0, 0
stw r0, 20232(r31)          ; clear the flag
return                      ; r3 = whatever the second import returned
```

Both imports resolve — neither appears in the unresolved list — so this is not
a missing NID.

**And that undermines the framing this subsection was built on.** A zero return
here most likely means *"the pending flag was set, the two SPURS calls ran, and
the second reported nothing"* — that is, **no work to do** — rather than *"the
request was rejected"*. Identical arguments producing a handle sometimes and
zero other times is exactly what a drain-if-pending helper looks like.

So the correlation drawn earlier between these zero returns and the empty audio
descriptors may be coincidence. It was never tested as a causal link, only
observed alongside. That is the honest state, and it is where this stops: the
zeros are explained, and whether they have anything to do with the empty
descriptors is an open question that this work did not answer.

That is where the trail stops. The remaining question is what initialises that
registry and when — an ordinary question about the caller's loop, not
about memory corruption, the allocator, the decompressor, the loader, the SPU
path, the locks, the renderer or the online layer, every one of which was
suspected during this work and each cleared by measurement.

#### What is directly measured and stands

Independent of any pass model, each of these is a direct observation:

- `longjmp` lifted as `return`; fixing it moved assets from a deterministic 4
  to a ceiling of 108, A/B'd over many runs.
- Main spins forever retrying a 264-byte allocation
  (`func_00937EF0(size=264) -> 0`, 2000+ consecutive failures).
- The free-space query returns ~2.6 GB because a free-list node carries an end
  pointer outside the arena.
- That giant allocation is granted, returning a pointer outside the arena.
- `func_006A4400` takes the free list from valid to invalid across a single
  call, bracketed 0 -> 1 in three consecutive runs.

#### It is not a locking race

A free list that holds a live block, damaged in a different place every run,
looks exactly like broken mutual exclusion, so that was tested directly:
`GT5P_LWMUTEX_GLOBAL=1` forces every guest lwmutex onto one global critical
section, serialising all of them.

```
per-slot locks    108 files / 3 bad nodes    7 / 4    108 / 3
one global lock     0 files / 0 bad nodes    7 / 4      7 / 4
```

The same three or four corrupt nodes appear either way. Serialising every lock
in the title does not prevent it, so the damage is single-threaded logic, not a
race — and the run-to-run variation comes from *when* the walk reaches a bad
node, not from whether one gets created.

That is worth having: it removes concurrency from the search, which is the
expensive place to look.

#### What this rules in

The decoder that wrote nearly 4 MB past its 32 KB window would corrupt exactly
this structure, and that is fixed. Corruption still happens, so either the fix
did not catch every path into that loop or there is a second writer. That is a
much better question than the one this document was asking a day ago, and it is
answerable with the write watch (`LBP_WW`) pointed at a free-list node once one
is known to be live.

Reproduce with `PS3_VERBOSE=0` and the allocator instrumented
(`python scripts/instrument_alloc.py 0094FF30`); `GT5P_MAINSTACK=10` prints the
main thread's guest chain, which is the piece that was missing.


### Where It Stops Now

Two outcomes, and which one a run gets is a coin toss weighted against us —
roughly three in four stop at 7 files, the rest reach 108.

The 7-file case is a real deadlock, not slowness: five minutes of wall clock
produces the same seven files and a 370 KB log, so nothing is even spinning.
The last thing that happens is a zero-length read into the decoder's input
buffer, then the SPURS job chain settles into a permanent cycle — the main
thread receiving job-chain completions on queue 1 with `d2` walking
0, 2, 4, 6, 8, 0xA, 0xC and never asking for another asset.

What both outcomes now reach, which nothing before this phase did:

- tiled render targets, Zcull, double-buffered display, flip and VBlank
  handlers all configured;
- the D3D12 backend fully initialised — adapter, pipeline states for every
  vertex class, vertex buffer;
- a continuous SPU job loop, 113,765 dispatches in a 75-second run, zero
  dispatch misses.

What neither reaches: a second flip. The title prepares exactly one and never
submits an RSX command buffer, so the FIFO drain has nothing to do and no frame
is ever presented.

It is worth being precise about *why*, because "the FIFO is broken" and "the
title never started rendering" look identical from a `put` pointer that does not
move. Under `GCM_DRAINDBG` the control register reads the same in every run,
including the ones that load 108 assets:

```
[DRAIN] getoff=00010040 put=00010040 ref=00000000
```

`put` never leaves the value `cellGcmInit` gave it. But the title *does* call
`cellGcmGetControlRegister`, exactly once, so it holds the pointer and the path
to the FIFO is wired end to end — it simply never kicks it. It also never polls
`cellGcmGetFlipStatus`. That is not a renderer that is failing; it is a renderer
that has not been asked to do anything yet. The frame loop sits behind whatever
makes the loader stop, and there is no evidence of a separate RSX defect waiting
underneath.

The outcomes are also a spectrum rather than a switch — 7, 39 and 108 assets
have all been observed from the same binary — which fits a race rather than a
branch.

#### The Stuck Runs Ask lv2 For More Memory

The two outcomes differ in one visible way before they diverge. Stuck runs
issue lv2 syscalls **341** and **342**; the run that reaches 108 files never
does. Both are unimplemented here, and `ppu_loader.cpp`'s catch-all answers
`CELL_OK`.

The wrappers are `func_00941808` (341) and `func_00941910` (342), and 341's is
a retry loop:

```
loop:  mr   r3, r29        ; a pointer the kernel is expected to write
       mr   r4, r31        ; 0x300000 -- three megabytes
       li   r11, 341
       sc
       cmpwi cr4, r3, 0
       bne  cr4, .retry    ; anything but 0 -> back-off call, then try again
       ...success...
```

So `CELL_OK` is taken as success and the title proceeds on three megabytes it
was never given. The obvious next thought — report failure instead, and let it
take a fallback path — is wrong, and measurably so: the branch retries on any
non-zero result, so an error answer spins that loop forever.

```
stub answers CELL_OK      7, 7, 0, 7   files
stub answers ENOMEM       1, 1, 1, 1   files
```

`GT5P_SC_FAIL=<numbers>` in the runtime makes named syscalls report failure, so
that experiment is repeatable rather than a one-off patch. The conclusion is
that these have to be *implemented*, not merely answered — but they are a
symptom rather than the cause, since the runs that get furthest never call them
at all. Something makes the stuck runs need memory the good ones do not.


##### Implemented, And It Did Not Help

Syscall 341 is now implemented, because answering `CELL_OK` to an allocation
request while allocating nothing is indefensible whatever else is true. The ABI
was read off the caller rather than a header: `func_00941808` loads `r3` with a
pointer and `r4` with `0x300000`, issues the syscall, retries on any non-zero
result, and on success immediately does `lwz r29, 0(r29)` — reading back
through the pointer it passed. So `r3` receives the address and `r4` is the
size. 342 follows with the address 341 handed back, and on a flat VM there is
nothing left for it to do.

It works — four 3 MB allocations a boot, at `0x40100000` upward — and it changed
nothing:

```
before   7, 7, 0, 7      files
after    7, 3, 7, 108, 7 files
```

The theory it was meant to test is dead, and the way it died is worth keeping.
The caller is the PDI worker for device `0x20094290` — the packed-filesystem
device whose loads stall — and the sequence looked damning:

```
sys_ppu_thread_create tid=11 name="PDI:7ffffffe:20094290"
lv2_syscall 341   r4=0x300000        <- asks for 3 MB
lv2_syscall 342   r3=0x0             <- passes on a null handle
ppu_thread_join(tid=11)
sys_ppu_thread_exit(tid=11 status=0) <- worker gives up
```

A worker that asks for memory, gets none and exits, on exactly the device that
stalls. Except the run that loads 108 assets does the same thing — creates the
thread, allocates, exits, joins — so that is simply what a short-lived one-shot
worker looks like, and the resemblance to a failure was entirely in the reading.

Keep the implementation: before it, the title spent the whole boot using three
megabytes it had never been given, which is latent corruption whether or not it
is *this* stall. But the stall is still unexplained.


##### A Third Outcome, And A Theory That Did Not Survive

Some runs open **no files at all**, and they have a signature of their own:

```
[cellSpurs] chain 0x20039780: shutdown after 11 job(s)
[HOTREAD] spinning on 0x0000000B (=0xFFFFFFFF) guest cia=0x00000000 lr=0x0094FFD4
```

38,000 of those spins in one run. `lr` places the guest inside `func_0094FF30`
— the allocator — at its call to `func_00938080`, a retry loop around the
import at stub `0x00BE0774`, which is NID `0x1573DC3F`: `sys_lwmutex_lock`.
`cia=0` says the repeated read is coming from HLE code, not from lifted guest
code, and the SPURS job chain has already shut down by then.

The obvious reading is a null lwmutex — address `0x0B` looks exactly like a
struct at zero plus a field offset, and there is even a purpose-built
`FLOW_BADLOCK` locator in the runtime for that case. It does not hold up, and
both reasons are worth writing down:

- `sys_lwmutex_lock` logs a `FAIL ... -> ESRCH` whenever it is handed a mutex
  whose sleep-queue slot is unused. **Zero** such lines appear, in any run.
- `FLOW_BADLOCK` does fire, but its heuristic calls `r3 >= 0x80000000` garbage.
  This port puts guest stacks at `0xCFExxxxx`, so every stack-allocated mutex
  trips it. The hits are `r3=0xCFEFF690` and friends — ordinary stack
  addresses, not bad pointers.

So the lock is being acquired, and something else entirely is reading guest
address `0x0B` in a loop. What that is remains open; the value `0xFFFFFFFF` and
the SPURS shutdown immediately before it are the threads to pull. Recorded this
way rather than as a finding because a confident wrong answer here would cost
the next session more than an honest gap.

That still leaves a spread of outcomes from one binary. Ten consecutive runs,
`PS3_VERBOSE=0`, same build:

```
108  3  108  7  7  7  25  7  3  7
```

Median 7, best 108, against a **deterministic 4 on every run** before the
longjmp fix. So the floor moved and the ceiling moved a great deal further, but
a race now decides which you get.

| assets | what it looks like |
|---|---|
| 0-3 | SPURS chain shuts down, then an HLE read-spin on `0x0000000B` |
| 7-25 | loads, then the SPURS job chain cycles forever asking for nothing more |
| 108 | gets furthest; still never submits an RSX command |

The thread doing the loading is now named: every `cellFs` open in a boot comes
from the thread whose entry is `0x01029EC8`, the **Job Manager Event Handler**.
In a stalled run that thread is not blocked and not dead — it cycles forever on
`sys_event_queue_receive(q=1)`, taking job-chain completions (`d1=0x20039780`,
`d2` walking 0, 2, 4, 6, 8, 0xA, 0xC) and never asking for another asset. So the
loader is healthy and idle; whatever decides *what* to load next is what has
stopped.

The furthest runs reach an online layer — nine unresolved `cellHttp` NIDs plus
one `sceNp2`, which fits the `GrimURL` entry in the config table. That looked
promising: an HTTP init faked to `CELL_OK` and then waited on would stall
exactly like this. It is not that. `PS3_HLE_UNRESOLVED=fail` exists to A/B which
missing import is load-bearing, and it changes nothing — `7 7 7 7` against a
default of `7 7 7 25`. Whatever stops the boot, it is not a faked import being
believed.

`cellPad Init(max_connect=7)` is called exactly once and never polled again, so
the title never reaches an input loop either.

Nothing is *polling* in the stalled runs — `YDKJ_HOTMAP` records no hot address
at all, and the thread dump shows every PDI worker parked in a condition wait.
That rules out a spin-wait on a flag nobody sets, and means the stall is a
wakeup that never arrives. All of the outcomes are timing-dependent, which
points at initialisation or teardown order rather than three separate bugs.

A measurement note that cost real time here. The runtime turns verbose logging
on when stderr is redirected, on the reasoning that a redirected stream means
someone is capturing a log — and ps3recomp's `runtime/ps3_log.h` warns in as many words
that the per-event lines are emitted from every guest thread through one
non-fair `FILE` lock, so the logging itself changes what the title does. Every
measurement through a pipe is therefore taken on a differently-scheduled
program. Pass `PS3_VERBOSE=0` when the numbers matter. It does not remove the
7-versus-108 split, so that race is real and not an artefact, but it is the
difference between a 16 MB log and a 370 KB one.

## Phase 14 — The Switch Statements Were Invisible

> `find_functions` walks direct branches. A `bctr` through a jump table is a
> dead end for it, so every case that *only* a computed branch reaches looks
> like unreferenced bytes and never gets lifted. There are 246 such tables in
> this binary and 1,710 targets sitting in that blind spot.
>
> ```
>
> Verified on a **clean shipping build** — re-lifted from scratch, only
> `scripts/setjmp_patch.py` applied, no diagnostic probes compiled in.
> Eight consecutive runs:
>
> ```
> 108  108  7  7  7  7  108  7      unique PDIPFS assets
> ```
>
> Three of eight reach 108, median 7, against a deterministic 4 before the
> fix. The distribution matches the instrumented builds, so the probes were
> not shaping the outcome — worth confirming, since nearly every number in
> this document was taken with instrumentation compiled in.
>
> A crash was seen roughly twice in fifteen runs while this was being
> investigated, and flagged as an open risk against the `longjmp` change since
> it appeared alongside it. Soaking the clean build clears it: **12 of 12 runs
> ran to their timeout with no abnormal exit**. The crashes belonged to the
> instrumented builds — a dozen `instrument_alloc` wrappers, block counters and
> generated-code edits — not to the fix.
>                       before        after
> functions lifted      39,660        40,320
> spins on queue 0      4,398,000     0
> unresolved indirect   0             0
> SPU dispatch misses   0             0
> PDIPFS files opened   4             4
> ```
>
> The 4.4 million busy-spins on event queue 0 — a thread receiving on a queue
> id nothing ever set, blamed in this document on the Job Manager for weeks —
> were code the switch tables hid. They are gone. File progress is unchanged,
> so this buys headroom rather than a new asset. See
> [Recovering the Switch Statements](#recovering-the-switch-statements).
>
> The sixth async load is now traced the whole way down, from the file device
> to the exact frame that stops it. It ends in a decompressor that is handed a
> zero-length input buffer by an abort protocol and never comes back out. See
> [The Sixth Load, All the Way Down](#the-sixth-load-all-the-way-down).
> Still no attract mode.

### Recovering the Switch Statements

`0x009180AC` had to be seeded by hand before the boot would resolve its
indirect calls. That should have been the tell: it is not a function, it is
case 0 of a twelve-way switch in `func_00917EB0`, and eleven siblings were
sitting in the same blind spot with it.

The shape GCC emits here makes the table self-describing — it goes directly
after the `bctr`, and each entry is a signed 32-bit offset from the table's own
base:

```
cmplwi rX, 11
ble    .Ldispatch
...default arm...
.Ldispatch:
lwz    r11, table@toc(r2)
rldic  r9, r0, 2, 30
lwzx   r0, r9, r11
extsw  r0, r0
add    r0, r0, r11
mtctr  r0
bctr
.long  off0, off1, ...        <- table base == this address
```

`scripts/jumptables.py` reads entries until one stops decoding to a plausible
target, bounded above by the nearest target already seen — the compiler puts
the first case's code immediately after the table, so the table cannot run past
it. That bound is what makes it work without the guarding compare. Keying off
`cmplwi` alone misses this very function, whose compare sits **240 bytes back**,
on the far side of the default arm; a look-back window sized for the common
case finds nothing here.

Of 2,538 targets: 4 were already function starts, 824 land *inside* an
already-lifted function, and 1,710 sit in unlifted gaps. Only the 1,710 are
seeded. Seeding the 824 would split a working function in half, which is the
one way this change could do harm.

A caution earned the hard way, recorded so it is not re-chased: a 1,360-byte
run of real PPC code at `0x009159F8`, starting mid-body with no prologue, looks
exactly like a truncated function. It is not — every branch in the preceding
function was checked and none targets the gap. Unreferenced bytes that decode
cleanly are usually a jump table's cases or an exception landing pad, not
evidence of a lifting bug.

### The Sixth Load, All the Way Down

Five async loads complete; the sixth parks at state 2. The chain from there,
each step measured rather than inferred:

| Layer | What it is |
|---|---|
| `func_00917EB0` | device worker step, vtable slot 16 |
| `func_00917208` | the drain, slot 25 — moves a queued request into `dev+56` |
| `func_00916E40` | slot 26 |
| `func_00925F60` | `FileDevicePFSFSHdd` slot 29 — the packed-file read |
| `func_00916DD0` | calls slot 5 of the object at `handler+12` |
| `func_0091FEB8` | `PDISTD::FileExpandPSX` slot 5 — abort a decompression in flight |

`func_00917EB0` switches on `[req+0x64]` through the jump table above, and the
selector decides everything:

| sel | device slot | `r24` | behaviour |
|---|---|---|---|
| 0, 1 | 17 | 0 | async — queue on `dev+64`, complete on a later tick |
| 2, 3 | 18 | 1 | synchronous — completes this tick |
| 4 | 19 | 1 | synchronous — completes this tick |

That table corrects a reading this document carried for a while. The four
PFSFSHdd loads that "complete" are `sel=4`: they finish *synchronously* and
never touch the queue at all. The stalled load is the only genuinely
asynchronous request on that device, so "four succeed and one fails on the same
device" was never the paradox it looked like.

The read never gets as far as issuing I/O. Its first act is to stop any
decompression already running:

```
func_0091FEB8(obj):
    if (obj[6917] == 0) return       ; nothing in flight -- normal path
    obj[6932] = 0                    ; input buffer base
    obj[6936] = 0                    ; input buffer length
    signal(obj+6876)                 ; wake the decoder
    wait  (obj+6816)                 ; block until it unwinds   <-- never returns
    obj[6917] = 0
```

`FileExpandPSX` carries six auto-reset events at `obj+6796` stride 20, and they
pair up cleanly once you have all six:

```
6796  "start work"       waited by func_00920220, the decompressor thread loop
6816  "work done"        signalled by func_00920220, waited by the abort above
6876  "here is input"    waited by func_009200F0 (refill), signalled by the abort
6896  "buffer consumed"  signalled by func_009200F0, waited by func_0091FBA8
```

The synchronisation primitive itself is sound — a correct auto-reset event,
where a signal with no waiter parks a sticky flag at `+17` that the next wait
consumes, so wakeups are not lost. It was worth checking; it is not the bug.

Instrumenting both sides shows the handshake working right up to the end:

```
> func_0091FBA8(obj, handler)              producer starts
  > func_009200F0(obj, ...)                decoder asks for input
  signal obj+6896  waiter=1                "ready" -- producer was waiting
  wait   obj+6876  waiter=0                decoder waits for the buffer
< func_0091FBA8 ret=0x000FD303             producer returns
signal obj+6876  waiter=1                  the abort wakes the decoder
wait   obj+6816  waiter=0                  reader blocks -- forever
< func_009200F0 ret=1                      decoder wakes with base=0, len=0
```

Entry and return counts name the exact frame that does not come back:

```
func_009200F0  (refill)   1 call,  1 return
func_00956D20  (decode)   2 calls, 1 return     <--
func_00957C88  (stage)    1 call,  0 returns
```

The second `func_00956D20` gets its zero-length buffer and then neither returns,
nor calls the refill again, nor calls the output callback again. It is spinning
in pure computation — 2,280 bytes of dense bit manipulation with no blocking
primitive in it. `func_00920220` can only signal `6816` after that call returns,
so the reader waits on an event nobody will ever reach.

What has been ruled out, so the next attempt starts from here:

- **Not a lifting gap.** No `TODO`/unimplemented marker anywhere in the lifted
  `func_00956D20`; every instruction has a handler.
- **Not a missing jump table.** All nine `bctr`-class words in the decoder are
  `bctrl` — virtual calls through OPDs at vtable slots 2 and 3, not computed
  branches.
- **Not a disassembler bug.** `disasm_audit_operands.py` over the whole ELF:
  `addi`, `lwz`, `stw`, `ori`, `rlwinm` all pass with zero divergences; the four
  residual ones are float/vector *formatting* only.
- **Not a dead worker.** Every device's worker loop runs, and the decompressor
  thread is alive and reaches its refill.

Counting basic blocks inside the lifted function names the loop directly --
`scripts/bbcount.py` drops a counter on every label, and four blocks at
`0x00957100`-`0x00957118` take 49.8 million hits each. That loop is a 32 KB
circular output window: `r25` is the base, `r28 = r25 + 0x8000` the wrap, `r31`
the cursor, and the only exit is `r31 == r26`.

Sampling its registers shows it working perfectly and then falling off a cliff:

```
iteration          r28 wrap        r26 bound        r31 cursor
        1     base + 0x8000      base + 13        base + 9
    1,000     base + 0x8000      base + 1216      base + 1051
1,000,000     base + 0x8000      base + 25788     base + 25675
5,000,000     0x0112D640         0                base + 3,992,907
```

Up to a million iterations the wrap is exact and the bound tracks just ahead of
the cursor — this is a decoder doing its job. Then `r26` becomes **zero** — the
null input buffer the abort installed, propagated into the loop bound — and
`r28` becomes the object's own address. `r31 == r26` can now never hold, the
cursor never reaches the wrap either, and the loop writes bytes at steadily
climbing addresses: nearly 4 MB past the window and still going.

So this is not merely a hang. It is an unbounded write walking through guest
memory, and it is a strong candidate for the heap damage this document has
recorded for a long time without explaining — the allocator walking into
`0x42Cxxxxx`. The decoder is fully and correctly lifted; every instruction in
the loop was checked against its encoding, including the CR field mapping and
the `rldicl`/`rlwinm` masks. What it is fed is wrong, not how it was translated.

What stops this on hardware is `longjmp`. The abort does not expect the
decoder to notice the empty buffer and unwind on its own -- it jumps out of
it. That is the subject of [Phase 15](#status-phase-15--longjmp-has-to-actually-jump),
and fixing it took this port from four assets to a hundred and eight.

## Phase 13 — PDIPFS Mounts, and the Game Reads Its Own Data

> A bare run now does this:
>
> ```
> Open /dev_bdvd/PS3_GAME/PARAM.SFO   -> 1040 bytes
> Open PDIPFS/K/4D                    -> 160 bytes      (volume index)
> Open PDIPFS/5C/B2                   -> 54,842 bytes   (first real asset)
> ```
>
> **The packed filesystem is mounted.** Everything this document described as a
> wall — the missing application script, the attract object nothing would drive,
> the arena that measured an empty container — was downstream of a filesystem
> that did not exist, and it exists now. See
> [Three Bugs and a Command Line](#three-bugs-and-a-command-line).
>
> The async loader runs too. `PDIEXT::FileDelayLoad` cycles
> construct -> wait -> **complete** five times over before the sixth hangs, and
> `sys_cond_signal` — called **zero** times for the whole of this project's life
> until today — now fires 36 times a boot. Still no attract mode.
>
> `GT5P_HEAPPAD` is no longer needed and now hurts: with assets loading, zero
> allocations fail, and padding every block only shifts the layout into a worse
> one (4 files without it, 3 with). The heap still walks into `0x42Cxxxxx` —
> that corruption is real and unfixed — but it no longer wedges anything.

### Three Bugs and a Command Line

GT5P is configured entirely by its command line, and this port had never given
it a usable one.

**`argv` is an array of 64-bit pointers, not 32-bit.** The guest CRT's first act
(`func_00010368`) is

```
r10 = argv + 4;  r28 = argv;
do { r0 = [r10]; [r28] = r0; r10 += 8; r28 += 4; } while (++i < argc);
```

— read at stride 8, write at stride 4: compact an array of 64-bit pointers into
32-bit ones by keeping each low half. It does the same to `envp` straight after.
Writing 32-bit entries made it read every *other* slot, so `argv[0]` came out as
our `argv[1]` and the rest as NULL. **The title had never seen a single
argument, including its own path.**

**It needs `boot_from=<mode>`.** `func_00013C98(name, buf, len)` is a plain
`argv` scan for `name=value`, and it opens with `if (argc <= 1) return 0`. The
filesystem setup asks for `boot_from` first and returns immediately when it is
missing — which is why no file device was ever constructed. The accepted values
sit beside the key in `.rodata`:

```
0x00E98350 "boot_from"    0x00E98360 "bdvd"
                          0x00E98368 "gamedata"
                          0x00E98378 "hddgame"
```

They select different volume formats. `bdvd` looks for `USRDIR/GT.VOL`, the
retail disc layout — pick it and the game dutifully tries to open a file this
package does not contain. `gamedata` looks for PDIPFS, which is what the PSN
package ships.

**`argv[0]` must be the real path.** The setup `strcmp`s it against
`"/dev_bdvd/PS3_GAME/USRDIR/EMAIN.SELF"`. With `/app_home` it takes a different
branch and never opens the volume.

Plus a `cellFs` mapping for the relative `PDIPFS/` prefix: with
`boot_from=gamedata` the title opens `PDIPFS/K/4D` *relative*, because on
hardware its working directory is its own `USRDIR`.

`FileDeviceCellFS` and `FileDeviceGameData` are now constructed three times
each. Before this, nothing in that hierarchy was ever constructed at all.

## Phase 12 — Found the One Thing That Matters

> **GT5P's application flow is a script.** The boot's last act is to look up
> `"scripts/gt5p/Application"` — and that script lives in PDIPFS, Polyphony's
> packed filesystem, which this port has never mounted. Every other symptom in
> this document sits downstream of that one fact: no script, so the attract
> object is never driven; never driven, so `MenuGameObject::wait()` never
> returns; never returns, so the frame loop never starts and `put` stays at
> `0x10040`. The whole investigation now reduces to a single question — see
> [Root Cause](#root-cause-the-game-is-a-script-and-the-script-is-not-there).
>
> The boot is at least stable now: the intermittent crashes that dogged this
> session turned out to be the runtime writing a string over a function-pointer
> table, and six consecutive boots since the fix have not crashed once.

| Milestone | Status |
|-----------|--------|
| PKG extraction | **Done** — 3,019 files, 1.8 GB |
| SELF decryption (`EBOOT.BIN`, `EMAIN.SELF`) | **Done** — RAP-derived, validated against a known-good control |
| ELF analysis & import resolution | **Done** — 439 imports, 291 NIDs resolved (66%) |
| Function boundary detection | **Done** — 40,476 found, 38,598 in executable sections |
| PPU code lifting | **Done** — 39,660 functions, 3.4M lines, 72 instructions unlifted |
| Import resolution (NID) | **Done** — all 439 thunks lifted as `ps3_hle_call`, nothing patched at load |
| Project scaffold & build system | **Done** — clang-cl + Ninja, 70 MB executable |
| ELF loading & VM setup | **Done** — segments, PT_TLS, OPD entry, fault-commit |
| CRT initialisation | **Done** — TLS block, `r13`, argv/envp |
| LV2 syscall dispatch | **Done** — full table, 15 guest threads run |
| SPU lifting | **Done** — 12 images, 4,328 functions, zero dispatch misses |
| SPURS job chains | **Done** — created, kicked, walked, per-job completion signalled |
| RSX configuration | **Done** — GCM init, main-memory map, tiles, zcull, display buffers |
| Audio (`cellAudio` → WASAPI) | **Partial** — SGX service loop runs to completion, no output device |
| Input (`cellPad` → XInput) | **Partial** — `cellPadInit` reached |
| Filesystem | **Working** — PDIPFS mounted; volume index and assets read |
| Graphics (RSX → D3D12) | **Partial** — configured; `put` idle at `0x10040` because no frame loop runs |
| Present / vblank ticker | **Done** — `src/gt5p_present.cpp`, 60 Hz |
| PDIPFS asset loading | **Started** — index + first 54 KB asset; loads stall at `FileDelayLoad` state 1 |

### The Audio Loop That Could Not Count

The whole boot hung behind one thread. `sgx-audio-thr` held the job chain's
lightweight mutex at `jobchain + 0x200` and never released it, so the main
thread sat in `sys_lwmutex_lock` for the rest of the run — 10.4 seconds and
counting, with the guest-side owner field naming the audio thread the entire
time.

It was not stuck. It was looping, and its loop is this:

```
func_006CEC74(obj):
    lock is already held by the caller
    do {
        cellSpursJobGuardNotify(obj + 0x180)
        sys_event_queue_receive(obj->queue)      // r6 = event data2
        i = data2
        if (obj->callback[i]) obj->callback[i](obj->arg0[i], obj->arg1[i])
    } while (i + 1 < obj->queued)
    sys_lwmutex_unlock(obj + 0x200)
```

`data2` is *which job finished*. Our SPURS pushed the completion event with
`data2` hardcoded to zero:

```c
u64 d2 = 0, d3 = 0;
if (g_spurs_job_mbox_valid) { d2 = ...; d3 = ...; }   /* computed */
sys_event_queue_push_by_id(q, SPURS_EVENT_PORT, jc_ea, 0, probe());
                                                    /* ...and dropped */
```

`d2` and `d3` were computed from the SPU's outbound mailbox and then never
passed. With `data2` always 0, `i` is pinned at 0, `i + 1 < 2` is always true,
and the loop runs forever: **151,685 receives in 25 seconds, 214,702 SPU job
dispatches, no progress** — all with the mutex held.

The event now carries the mailbox value when the SPU produced one, and the job's
ordinal in the chain otherwise, which is exactly what that loop counts.
[ps3recomp#98](https://github.com/sp00nznet/ps3recomp/pull/98).

That one field was worth the whole graphics stack.

### A Detour That Was Not the Cause

`cellSpursShutdownJobChain` (NID `0x738E40E6`) was also unregistered and faked
`CELL_OK` thirteen times a boot, which made it the obvious suspect for a chain
that would not tear down. It is implemented now — chains carry a shutdown flag,
`jc_execute` honours it wherever the walk has reached, and Shutdown signals
completion so a parked thread wakes.

It did not move the boot at all. The NID was genuinely missing, which is why it
is in the PR, but the hang it was reached from had a different cause. Recorded
here because a negative result that cost a build cycle is worth the same line in
the log as a positive one.

### 363,577 Writes to Address Zero

With the audio chain finally running, its second job (`image 7`, fingerprint
`0xBE66D8D2210CDCD4`) turned out to be spilling its entire local store to guest
EA `0x0000` on every single pass — LS `0x0000`/`0x4000`/`0x8000` to EA
`0x0000`/`0x4000`/`0x8000`, 34 KB a lap. Of 364,600 SPU DMA PUTs in a 40 second
boot, 363,577 went to the null page:

| before | | after | |
|---|---|---|---|
| `ea 0x00000000` | 363,577 | `ea 0x01000000` | 197 |
| `ea 0x01000000` | 1,020 | `ea 0x20000000` | 3 |
| `ea 0x20000000` | 3 | | |

lv2 reserves the low 64 KB; an EA that small means the descriptor field holding
the real destination arrived as zero. ps3recomp already rejects malformed MFC
transfers for the same reason, so this joins them
([ps3recomp#107](https://github.com/sp00nznet/ps3recomp/pull/107)). The job
still reads its inputs from the wrong place — it also issues GETs from EAs like
`0x7801C102` — but the histogram is now readable, which it was not before.

### The Write Watch Was Lying by Omission

`LBP_WW` prints its first 64 hits and then goes silent without saying so. I read
that silence as *"nothing writes this field"* four separate times in one
session — the heap bump pointer at `0x011806BC`, the Job Manager queue id at
`0x0118C500`, and both the `f64` and state fields of the stalled file request.
The state field had **2,340 writes** in the watched window. Sixty-four were
shown. Each time, the wrong conclusion sent the investigation somewhere else for
a while.

Fixed in [ps3recomp#111](https://github.com/sp00nznet/ps3recomp/pull/111): the
watch now announces the cap and `LBP_WW_MAX` raises it (`0` = unlimited).

Uncapped, the stalled request's state machine reads straight off:

```
<- 0   func_00916730
<- 1   func_00918310    enqueue: queued on the list at dev+40
<- 0   func_00917DE8
<- 2   func_009167E0    promoted to a second, priority-sorted list at dev+64,
                        worker signalled again
       (nothing further -- the wait needs 3)
```

So the request is neither ignored nor lost: it is promoted through two queues
and parks in the second. `func_009167E0` walks that list sorted on the
`[req+0xD8]`/`[req+0xDC]` key pair, inserts, and signals `dev+76` — the same
object the worker waits on. Whatever drains `dev+64` is the next thing to find.

### Why the Two Arena Passes Disagree

The caller is a textbook measure / allocate / fill, and it checks its own work:

```
r3 = 0;         bl func_006C32A0     ; measure -> r30
bl func_006A3988(r30)                ; allocate r30 bytes
r3 = buffer;    bl func_006C32A0     ; fill
cmpw r3, r30;   beq ok               ; the two totals must agree
```

Inside, the measuring pass reads back a pointer it never wrote:

```
bl func_006A4400(arena, r1+112, 0x44)   ; base == 0 -> does NOT write *out
r4 = [r1+0x70]                          ; reads that slot anyway
...
r11 = [r1+0x70];  cmpdi r9, 0           ; and BRANCHES on it
```

`func_006A4400` only writes `*out` when `arena->base` is non-zero, so on the
measuring pass that stack slot holds whatever was there before. Forcing it to
zero makes the two passes agree:

| | measure | fill | overrun |
|---|---|---|---|
| `GT5P_ARENA_ZERO=0` | `0x58` | `0x4C0` | **0x468 bytes** |
| `GT5P_ARENA_ZERO=1` | `0x11C` | `0x114` | none |

So that stale read is what drives the mismatch. **The experiment is not a fix**,
though: blanking every measuring-pass out-pointer also blanks slots the caller
legitimately uses, and it trades the corruption for crashes — four runs each,
`ARENA_ZERO=0` gives 0 crashes and 4 allocator spins, `ARENA_ZERO=1` gives 3
crashes and 1 spin. It is off by default. What it establishes is the mechanism,
which is worth more than the workaround would have been.

### The Next Wall: a Heap That Grew Out of Its Own Region

The boot now ends in `operator new` retrying forever:

```
func_00951FA8(size):
    for (;;) {
        p = alloc(size);  if (p) return p;
        sys_timer_usleep(2000);          // func_00947F28
    }
```

A 264-byte (`0x108`) allocation fails 2,198 times in a run. The failure is not
the interesting part — the three allocations before it are:

```
func_0094FF30(heap=0x011806B0, size=0x37000, align=0x40) -> 0x42C49000
func_0094FF30(heap=0x011806B0, size=0x37000, align=0x40) -> 0x42C11FC0
func_0094FF30(heap=0x011806B0, size=0x29521, align=0x10) -> 0x42BE8A80
```

Those succeed, and they are a perfectly well-behaved downward bump allocator:
each return is the previous one minus the requested size plus the alignment.
They are simply bumping through `0x42Cxxxxx` — 1.1 GB in, where this title has
no memory at all. Read as floats they are 98.28, 96.56 and 95.27.

The heap descriptor says where it should be:

```
0x011806B0: 00F76D48 20000000 2ADFFF80 652D6E70
            vtable   base     limit    current
```

`base` and `limit` are right — the 174 MB region. `current` is `0x652D6E70`,
far outside `[base, limit)`.

Walking back from there, the free-list node the allocator carves from carries an
end pointer of **`0x42C80000`** — which is `100.0f`. `func_0094F6E8` splits a
block by taking `[node+4]` as the block's end, and every subsequent return is
that value minus the running total. The allocator itself knows the value is
wrong: the very next instruction is

```
lwz    r0, 0x8(r3)      # heap->limit = 0x2ADFFF80
cmplw  cr7, r0, r9      # r9 = 0x42C80000
blelr  cr7              # limit <= end -> bail out, skip the back-link
```

so it bails and leaves the list half-linked rather than rejecting the block.

That value propagates node to node, so an address watch only ever catches the
copy. Watching the *value* instead ([ps3recomp#108](https://github.com/sp00nznet/ps3recomp/pull/108))
found the origin in one run.

### An Arena With No End

`func_006A4400` is a bump arena:

```
r9 = arena->base;
if (r9 && out) { *out = r9 + arena->cursor; memset(*out, 0, size); }
arena->cursor += size;          /* no limit, no check, ever */
```

It is run twice. Pass one with `arena->base == 0` only accumulates sizes; the
caller then takes one CRT block that big, points the arena at it, and reruns the
identical code to fill. The two passes have to agree, and here they do not:

```
pass 1   out=0xFFFFF4FC  size=0x0      cursor 0x58    <- block sized 0x58
pass 2   out=0xFFFFF4FC  size=0x26C    cursor 0x2C4   <- and on to 0x480+
```

`0x26C` is `31 × 20`: a count that is 0 while measuring and 31 while filling.
So the arena gets a `0x58` block and writes more than a kilobyte into it,
marching 20-byte records — glyph metrics, floats defaulting to `100.0f` —
straight across the CRT's free-list nodes. That is where the heap's `next`
pointer becomes `100.0f`, and that is what eventually parks the main thread in
`operator new` forever.

The chain is confirmed end to end. `GT5P_HEAPPAD=<bytes>` adds slack to every
CRT block; with more slack than the overrun, the boot walks straight past the
retry loop:

| | `GT5P_HEAPPAD=0` | `GT5P_HEAPPAD=4096` |
|---|---|---|
| main ends at | `operator new` retry, `size=0x108` | `func_00938698`, the PDI path |
| heap reaches | `0x20017xxx` | `0x2043F510` |

That is a diagnosis, not a fix — it is a debug pad, and the real repair is
whatever makes the two passes disagree. But it moves the main thread into the
same function the six PDIPFS worker threads sit in, which is the first time this
port has had main anywhere near asset loading.

Still no file but `PARAM.SFO` opens, so that is the next wall.

### The Next Wall: Everyone Is Waiting, Nobody Is Working

Past the heap, the boot is a textbook idle deadlock. Main's chain is

```
func_00687CD8 -> func_00687F90 -> vtable[+0x04] = func_0068DA68   (start)
                                     [obj+0x44] = 1               (busy)
                                     enqueue into a priority list
                              -> vtable[+0x24] = func_0068DB00    (wait)
                                     sys_cond_wait(cond 93)
```

and it never comes back. The object is a static at `0x0107B754`; `[obj+0x44]`
is set to 1 by the start method and **never cleared by anything, all boot**.

The wake path exists and is easy to name. The engine has three sibling helpers,
each an 11-instruction prologue falling through into a 30-instruction body:

| entry | body | syscall |
|---|---|---|
| `func_00938548` | `func_00938574` | 109 `sys_cond_signal_all` |
| `func_009385F0` | `func_0093861C` | 108 `sys_cond_signal` |
| `func_00938698` | `func_009386C4` | 107 `sys_cond_wait` |

40 call sites across the binary use them. Main's waiter is `func_0068DB00`; its
counterpart is `func_0068E3E0`, reached from `func_006736A0`, which is
`main-vtable+0x10` — the task's "finish" method. **`sys_cond_signal` and
`sys_cond_signal_all` are called zero times in the entire boot.** Every waiter
waits; nothing ever finishes.

The reason is one queue. The PDI worker loop is `func_00935690`:

```
while (running) {
    rc = sys_event_queue_receive(q, &evt, 1000000);   /* 1 s */
    if (rc != 0) return;                              /* give up */
    lock(); for (n = list_head; n; n = n->next) n->vtable[+8]();  unlock();
}
```

It only drains its work list *after* an event arrives. Queue 5 is the PDI
queue — created, never cancelled, and in a 30-second boot:

| queue | receive attempts | events delivered |
|---|---|---|
| 1 | 56,784 | 25 |
| 2 | 56,669 | 18 |
| 3 | 39,387 | 21 |
| **5** | **1,901** | **0** |

Nothing is ever posted to it. The enqueue path main takes
(`func_0068DF78`) is lock, priority-insert, unlock — `func_00938BE8` is plain
`sys_lwmutex_unlock`, not a wake — so the work lands on a list whose worker is
blocked waiting for a notification that has no sender.

The task itself is queued correctly. Both scheduler lists hold it:

```
0x011BB8E8: vtable=00F6F258  head=0107B76C  tail=0107B76C  state=2
0x011BB928: vtable=00F6F278  head=0107B780  tail=0107B780  state=2
```

So nothing is lost or mislinked — the work is sitting on the right list, and no
thread ever comes to take it.

**This probably subsumes the heap bug.** The arena's measuring pass counts
entries in a container that is empty, and its filling pass finds 31 — the same
shape you get when a table is populated between the two passes. Nothing in this
port has loaded any data yet, so "empty while measuring" is exactly what an
un-started asset system produces. If that is right, the arena overrun is a
*symptom* of this deadlock rather than a separate defect, and `GT5P_HEAPPAD`
stops being needed once work actually flows. Worth confirming before spending
effort on a direct fix for the count mismatch.

Queue 5 has no port connected to it at all — the boot wires ports only to
queues 1, 2 and 6 — and the guest never calls `sys_spu_thread_bind_queue`,
`sys_spu_thread_group_connect_event` or `sys_event_port_connect_ipc` anywhere.
SPURS attaches only queue 1. So the sender for queue 5 does not exist yet
because the code that would create it has not run.

### The Binary Still Has Its RTTI

This title was never stripped. Every polymorphic class carries a live
`std::type_info` with a mangled name, and every vtable is preceded by
`{ offset_to_top, typeinfo }`. `scripts/rtti.py` walks that and recovers **1,442
vtables and 8,314 virtual functions**, which turns the whole investigation from
address archaeology into reading:

```
func_0068DB00  MENU::MenuGameObject vtable+0x24
func_006736A0  MENU::MenuGameObject vtable+0x10
func_0068DA68  PDIEXT::GameObjectBase vtable+0x1C
func_00687F90  PDIEXT::AdvertiseSimplePS3 vtable+0x60
```

So the object the whole boot is waiting on is **`PDIEXT::AdvertiseSimplePS3`** —
the attract-mode object — registered into
`PDIEXT::UpdateManagerT<GameObjectPS3>` and
`PDIEXT::RenderManagerT<GameObjectPS3>`, sitting next to `PDIEXT::MPEGStream`
and `PDIEXT::PAMFStream`. Attract mode here is a streamed movie, and the boot
sequence is: activate the object (`GameObjectBase vtable+0x1C` sets busy and
registers it with both managers), then `MenuGameObject::wait()` blocks until it
deactivates.

Nothing ticks the managers. The only loop running is tid 1's sysutil pump
(`usleep(20000)` then `cellSysutilCheckCallback`, 888 calls in 30 s); the game's
own frame loop is main, and main is inside the wait.

`analysis/rtti.json` is derived from the game binary, so it is gitignored like
everything else in `analysis/` — run `scripts/rtti.py` against your own dump.

### Confirming the Gate

`FLOW_CONDKICK=1` caps infinite condition waits and returns `CELL_OK`, which is
a lie but a useful one: the guest's wait loop exits on a zero return. With it,
main leaves the attract wait and runs on into the SGX audio teardown, where it
contends for the job chain's lwmutex and — this time — **wins it, twelve times,
after ~4 ms each**. So that is no longer a deadlock, just contention.

It then dies writing through a null object (`write at host 0x24`,
`LR=0x0096C890`), which is what a lie of this shape earns: the object was never
actually made ready. The experiment is only worth its one conclusion — the
attract wait is the gate, and everything downstream is reachable once something
legitimately completes that object.

### The Intermittent Crash Was Us, Writing on a Function-Pointer Table

Half the runs in this session died somewhere different -- a null-object write,
an `unresolved indirect call -> 0x43F73A02`, a read through a garbage `CTR`.
They were all the same bug, and it was in the runtime, not the game.

`cellDiscGameGetBootDiscInfo` was declared with three parameters. It takes one.
The HLE adapter therefore handed it whatever `r4` held, and it wrote a title-id
string there. At GT5P's call site `r4` still holds a global loaded two
instructions earlier for the `RegisterDiscChangeCallback` call -- `0x01025510`,
which is the middle of an OPD table:

```
OPD 0x01025510 -> func_0093C3D0   <- "BLES" / "0000" written over code+toc
OPD 0x01025518 -> func_0093C480   <- code pointer became 0x3000C480
OPD 0x01025520 -> func_0093C778
```

`"BLES00000\0"` is ten bytes: it destroyed one entry outright and truncated the
next. Any indirect call through either landed in nowhere.

Fixed in [ps3recomp#109](https://github.com/sp00nznet/ps3recomp/pull/109), and
the port now also feeds `cellGame` the real ids from PARAM.SFO, which it had
never done -- the boot had been calling itself `BLES00000` when PARAM.SFO says
`NPUA80075`.

**Six consecutive 20-second boots, zero crashes, zero unresolved indirect
calls.** Before this, roughly half of them died.

### Root Cause: the Game Is a Script, and the Script Is Not There

App init is three calls:

```
bl func_00011A28    ; activate the AdvertiseSimplePS3 object (busy = 1)
bl func_00013060    ; the pump -- this is what must drive it to completion
bl func_00011AC8    ; wait for it to finish   <- main dies here
```

`func_00013060` takes one argument, and it is a string:

```
0x00E97618: "scripts/gt5p/Application"
```

**GT5P's application flow is a script**, loaded by name out of Polyphony's packed
filesystem. Instrumented, the pump's entire life is one millisecond:

```
[pump] ENTER func_00013060(r3=0x00E97618)
[pump] gate func_0096DE30 -> 0            (does not take the early-out)
[pump] step func_007D1B60(0x2027F6D0) -> 0x2027F70C
       two small allocations
[pump] LEAVE func_00013060                (same millisecond)
```

**Correction to a first reading of this.** That probe only logged calls which
returned non-zero *and* had a non-zero `r4`, so a void call with a stale `r4` of
zero vanished from the log — which made the pump look like it bailed on the spot.
Traced unconditionally from the pre-hook it makes **45 calls**: it registers
script symbols (`setSignalHandler`, `setRemainMaxTime`, `MRaceDisplayFace`),
builds the path as a `std::string`, and ends with

```
func_00838688(hModule=0x2AA3092C, &"scripts/gt5p/Application")
```

`hModule` is the script VM's module handle — RTTI puts `hAny` and `hCode` either
side of it. So the script system is up and is genuinely asked for the application
script. It comes back with nothing, the pump destructs its two RAII guards, and
returns. (`func_00A03150`, which the first pass took for the lookup, is `strlen`
— word-at-a-time zero detection, `cntlzd`, the lot.)

It comes back with nothing because there is nothing mounted: the two functions that build the mount path
`/dev_bdvd/PS3_GAME/USRDIR` + `/` + `PDIPFS` — `func_0002D938` and
`func_0002E810` — are **never called once** in a boot, and the only file this
port has ever opened is `PARAM.SFO`.

So the chain runs the whole way down:

| | |
|---|---|
| PDIPFS is never mounted | proven — mount functions never called, no file opened |
| so `scripts/gt5p/Application` cannot be found | the pump returns in 1 ms |
| so the attract object is never driven | its busy byte stays 1 all boot |
| so `MenuGameObject::wait()` never returns | main parks on cond 93 |
| so the frame loop never starts | `put` stays at `0x10040`, no pixels |

I also guessed this would explain the heap corruption — that the arena's
measuring pass counted a container which was empty only because no data had
loaded. **That was wrong.** With PDIPFS mounted and assets loading, the two
passes still disagree by exactly as much as before: the measuring pass ends at
cursor `0x58`, the filling pass at `0x4C0`. The overrun is unchanged and is now
the main source of instability — the same boot variously segfaults, spins in the
CRT allocator on a near-null free-list pointer, or reaches the clean stall.

**The next question is the right one to ask, and it is a single question:** what
should call the PDIPFS mount, and why has that not run? Everything else in this
README is downstream of it.

### Older Findings

### What the Binary Looks Like

The title ships two signed executables. `EBOOT.BIN` is a 420 KB launcher that
does little more than check the network and hand off; `EMAIN.SELF` is the game.

```
EMAIN.ELF        17,230,248 bytes, ELF64 big-endian PowerPC64
Entry point      0xF9D690
Segments         1 executable (15.9 MB of code), 8 program headers
Instructions     3,997,458 disassembled
Functions        40,476  (39,299 from .opd, the rest from prologue/leaf/branch passes)
                 1,878 of those sit above the last executable section (0xBE0AF4)
                 and disassemble as .rodata; they are dropped before lifting
Imports          439 functions across 26 modules
NIDs resolved    291 / 439
Assets           USRDIR/PDIPFS — 3,019 files, 1.8 GB, Polyphony's own packed VFS
```

Import counts, largest first:

| Module | Fns | Module | Fns | Module | Fns |
|---|---|---|---|---|---|
| `sceNp` | 81 | `sys_fs` | 22 | `cellRtc` | 7 |
| `cellSysutil` | 45 | `cellSpurs` | 22 | `cellHttpUtil` | 5 |
| `cellHttp` | 31 | `cellPamf` | 14 | `cellVpost` | 4 |
| `sysPrxForUser` | 29 | `cellNetCtl` | 13 | `cellMusicUtility` | 4 |
| `cellGcmSys` | 28 | `cellAudio` | 12 | `cellSysmodule` | 3 |
| `sys_io` | 27 | `cellDmux` | 12 | `sceNp2` | 2 |
| `cellImeJpUtility` | 24 | `cellUsbd` | 12 | `cellSsl` | 2 |
| `sys_net` | 22 | `libvdec` | 8 | `cellSysutilAvconfExt` | 1 |
| | | `cellAdec` | 8 | `sceNpBasicLimited` | 1 |

`sceNp` being the single largest dependency is the shape of this title: an
online game whose servers are gone. Most of those 81 calls will need to fail
gracefully rather than work.

The 148 unresolved NIDs cluster in `cellDmux`, `cellPamf`, `libvdec`,
`cellVpost`, `cellImeJpUtility` and `cellUsbd` — the media-decode and peripheral
paths. Those are stub-or-implement decisions for later, not blockers now.

### Lifting

All 38,598 in-range functions went through `ppu_lifter.py` in about a minute on
twelve workers:

```
Input            38,598 functions (+398 recovered by splitting merged ranges)
Emitted          39,653 functions, 15,858 unique call targets
Jump tables      194 dispatchers, 2,178 case targets, all resolved internally
Output           6 chunks + header, 3,404,026 lines, 194 MB of C++
Unlifted         72 instructions  (stvrx/stvlx x33 each, vsumsws x3, vsum4sbs x3)
Embedded data    5,010 .word literals inside function ranges
Clipped          21 functions whose range ends mid-flow; each emits a halt
```

72 unlifted instructions out of 3,997,458 is a good result and a short list: two
VMX unaligned-store forms and two VMX saturating-sum forms. They will need
handling in the lifter before anything that touches them can run, but they are a
bounded, nameable problem rather than an open-ended one.

### What the First Boot Does

```
$ ./build/gt5p.exe
=== Gran Turismo 5 Prologue Recompiled ===
Built with ps3recomp | 39657 lifted functions
[ELF]  segments 0x00010000 (15.9 MB, R-X) and 0x00F50000 (RW), PT_TLS 0x01034570
[ELF]  entry OPD 0x00F9D690 -> code 0x00010230, TOC 0x010382D8
[crt]  sys_initialize_tls: block 0x0E000000, r13=0x0E007000
[SPU]  initialize(nspu=6, nrawspu=0)
[SYS]  5 guest threads created -- Job Manager Event Handler, spurs_printf_handler, 3 PDI workers
[cellSpurs]     Initialize nSpus=5, 4 workloads added (Wws_Job, pm=0x00F4CB80, 11,648 bytes)
[cellGcmSys]    Init(cmdSize=0x10000, ioSize=0x100000, ioAddr=0x40000000)
[cellVideoOut]  Configure resId=2 -> 1280x720, pitch 8192
[cellGcmSys]    3 tiles, zcull 1920x1088, display buffers 0 and 1, MapMainMemory(0x20000000, 174 MB)
```

…and then the SPU actually runs:

```
[GT5P]      SPU: Wws_Job registered (fp=0x6FFFB30E41EE17BC, 11648 bytes at 0x00F4CB80)
[cellSpurs] JobGuardInitialize(guard=0x20039900 chain=0x20039780 notify=1 autoReset=1)
[cellSpurs] wid=0 PM resolved (fp=0x6FFFB30E41EE17BC image=1)
[spurs-pm]  DMA cmd=0x40 lsa=0x00B00 ea=0x020017C00 size=0x100 tag=8
[spurs-pm]  DMA cmd=0x20 lsa=0x00B00 ea=0x020017C40 size=0x10 tag=8
[spurs-pm]  DMA cmd=0x40 lsa=0x00D00 ea=0x020017C80 size=0x80 tag=8
```

That is lifted SPU code executing on a host thread, issuing MFC transfers to pull
its workload descriptor out of guest main memory. All four of this title's SPURS
workloads carry the same program — `Wws_Job`, Sony's WWS job manager, 11,648
bytes embedded in the ELF at `0x00F4CB80`. Unlike the job binaries most titles
load from their data files, this one could be taken statically: extract, 193
functions from `find_spu_functions.py`, lift, register.

It then settles: the main thread polls at guest `0x00941EE0` on a 20 ms
`sys_timer_usleep`. The job manager reads its descriptor, finds no job to claim
and returns, so nothing advances past that.

Two things worth noting about how quiet the run is. **No NID went
unimplemented** — 487 handlers were registered from ps3recomp's libraries and the
boot path did not reach past them. And **no file was opened**: the title has not
asked for a single byte of its 1.8 GB of assets yet, which places the stall
before any content loading, not inside it.

### The Current Blocker, Precisely

Main livelocks. `GT5P_MAINSTACK=<seconds>` suspends it, unwinds its **host**
stack with the Win64 unwinder and maps each frame back through the function
table; `GT5P_PEEK=<addr>[,...]` dumps guest words with one level of pointer
indirection. Together they walk the whole chain out.

```
[hostchain]  <host>  func_00B756D0  func_0083A210  func_0083AAA0  func_007FA158
             <host>  func_00838A60  func_00A274B8  func_00A27810  func_0002FB38
             <host>  func_007D2528  func_007D6C60  func_00011B28 ... func_00010230
[mainregs]   r4..r12 = CCCCCCD4   r27 = CCCCCCD4
```

`func_00B756D0+0x11C` allocates a 24-byte node and links it into a container,
about two million times over (the refcount it bumps climbs past `0x200990`).
Every pointer it touches is `0xCCCCCCD4`, and here is where that comes from:

1. `func_008B0A38` picks size class 5 for a 24-byte request and tail-branches to
   the class allocator `func_008B0920` with `entry = pool->base + 5*80`.
2. The pool at `0x010E3760` and its 20-entry array at `0x20006458` are built
   **correctly** — `func_008B02B8` allocates `n*80+8`, sets `pool->base` to
   `block+8`, `func_008AF3B8` zeroes each 0x20-byte entry and initialises its
   lock at `+32`, and `func_008AF2C8` fills in `{+0: owner, +4: size}`. All
   verified with the runtime's store watch (`LBP_WW`).
3. The class list is empty, so `func_008B0818` refills: `func_008B0798` carves a
   chunk, `func_008AF308` links it, and the head at `entry+8` is written —
   **`0xFFFFFFFF`**.
4. The next pop follows `-1` as a pointer, reads the top of the 4 GB VM window,
   and hands back garbage. `func_008B0920` stamps `0xCCCCCCCC` into the block's
   first three words (its uninitialised-memory poison) and returns `block+16`.
   `0xCCCCCCCC + 8 = 0xCCCCCCD4`.

The refill path itself reads clean: `func_008AF978` takes a 4080-byte page from
the pool's page allocator at `pool[+0x08]`, falls back to the general allocator
if that returns 0, and initialises the chunk. Nothing there can produce `-1`.

And the store watch shows the `0xFFFFFFFF` is **transient** — the very next
write to `entry+8` is a real pointer, `0x20097900`. So `-1` looks like an
"insertion in progress" sentinel, and the failure is a **reader following it**:
`func_008B0920` takes the entry's own lock at `entry+32` (`func_00938DA0`)
before touching the head, so on hardware nobody can observe the sentinel. That
makes the per-entry lock a suspect — but not the only one.

Narrowing further: the head store is not in `func_008B0818` at all. It calls
`func_008AF340` (unlink) and `func_008AF308` (link) to move a chunk to the front
of the list, and the store watch attributes their inlined bodies to the caller.
An unlink that empties the list should write `0` — the reader's only test is
`head == 0`. Writing `-1` means the last node's *next* field is `-1` rather than
`0`, which points at the chunk initialiser `func_008AF1B8` or at the splice
itself.

Those three were checked and are lifted faithfully — `func_008AF1B8` zeroes the
node's `prev`/`next` correctly, and the splice reads clean. The corruption is
elsewhere, and it is bigger than one word.

**The entry itself is wrong.** Read at steady state, and confirmed against raw
memory (`GT5P_PEEK` prints both `vm_read32` and the mapping directly — they
agree, so the accessor is not lying):

```
entry[5] @ 0x200065E8   owner=FFFFFFFF  size=FFFFFFFF  head=20097900  tail=FFFFFFFF
                        cache=00000000  count=00000001  max=FFFFFFFF  total=0243E79A
```

`owner` should be the pool (`0x010E3760`) and `size` should be `0x18`. Both are
written at init — the store watch sees `0x200065EC <- 0x18` and
`0x200065E8 <- 0x010E3760` — and both are `-1` a second later.

That is what drives the livelock: `func_008B0920`'s only test is
`[entry+4] == 0`, meaning "this size class is unused, fall back to the general
allocator". With `size` reading `-1` it *never* takes that branch, and instead
pops from a free list whose links are garbage.

Armed at the exact instant of the init store
(`LBP_WW=0x200065E8 PPU_WW_GUARD=1`), the page guard names two writers of that
word: one through `vm_write32` — a normal lifted 32-bit store, but the guard
reports the faulting RIP inside the accessor, so the *guest* caller is not
identified — and one from inside the lifted body of `func_00494F70`.

Ruled out this round, each cheaply and definitively:

- **Not SPU DMA.** `PS3_NO_JOBCHAIN=1` stops every job and reproduces exactly.
- **Not a faked-OK import.** `PS3_HLE_UNRESOLVED=fail` reproduces exactly.
- **Not dropped writes.** `ppu_vm_size` is 0, so the bounds check is disabled and
  nothing is being silently discarded.
- **Not the `ydkj_memmove` body override** — it is env-gated and off.

### Both Writers, Named

The guard already dumped a guest call stack on a watched-line hit; it just did
not print the writing routine's **live arguments** unless the watched word went
to zero. [ps3recomp#99](https://github.com/sp00nznet/ps3recomp/pull/99) removes
that restriction, and the answer falls out immediately. Two initialisers write
the same memory, both reached from the same CRT sequencer `func_00010368`:

```
1. the allocator pool                     r3=0x200065E8 r4=0x010E3760 r5=0x00000018
   _start -> func_00010368 -> func_00010200 -> func_000119B8
          -> func_008B0F10 -> func_008B02B8

2. a 1 MB, 64 KB-aligned arena setup      r3=0xFFFFF984 r4=0x00010000 r5=0x00100000
   _start -> func_00010368 -> func_000107F8 -> func_00011A28 -> func_00013D10
          -> func_00013EF0 -> func_00668390 -> func_009BFEF8 -> func_009BFCD0
          -> func_009C02A8 -> func_009DA12C
```

The first builds the size-class table. The second — the CRT heap initialiser,
`func_009BFEF8` passes it `size=0x100000, align=1920` — runs afterwards and
writes over it. That is what leaves `owner` and `size` reading `-1`.

### It Is Not the Ordering

Traced and eliminated. `func_00010368` calls `bl 0x9377C0` — the CRT heap
initialiser — at `0x0001043C`, **before** static init at `0x0001048C` and main
at `0x000104B8`. Verified in the disassembly *and* in the lifted C, including
the `bge` that guards the loop above it. `func_00937EF0` (malloc) also calls it
lazily when the heap slot is null, and that slot is set (`*(0x0117FEA0)` =
`0x011806B0`), so it initialises exactly once. The heap exists before anything
allocates from it, as it must.

The CRT heap is the whole guest arena: object at `0x011806B0`, base from
`*(0x01180730)`, size `*(0x01180734)` = `0x0AE00000` — 174 MB, which is exactly
what `cellGcmMapMainMemory(0x20000000, 0xAE00000)` maps.

### The Allocator Is Fine, and So Is the Table

`scripts/instrument_alloc.py` wraps a lifted function in place so its arguments
and return value can be logged. That tool was the missing piece all along: the
runtime's dispatch-table override only intercepts *indirect* calls, and a `bl`
in lifted code calls `func_XXXXXXXX` directly and never looks the address up.
The wrapper has to go in beside the definition, in the generated source.

With `func_0094FF30` — the CRT heap's block allocator — wrapped, and
`src/gt5p_allocwatch.cpp` checking every returned range against every previous
one:

```
[alloc] #42 func_0094FF30(heap=0x011806B0 size=0x400000 align=4096) -> 0x2A9BF000
[alloc] #43 func_0094FF30(heap=0x011806B0 size=0x70    align=16)   -> 0x200063D0
[alloc] #44 func_0094FF30(heap=0x011806B0 size=0x648   align=16)   -> 0x20006450
[alloc] #45 func_0094FF30(heap=0x011806B0 size=0x200000 align=4096) -> 0x2A7BE000
```

495 allocations, all sane. The pool's page-allocator object (#43) and its
size-class array (#44, `0x648` = 1608 bytes = 20×80+8) are **uniquely owned** —
nothing else is handed that memory. The overlaps the detector does flag are
sub-heaps nesting inside blocks they legitimately own (#48–#52 inside #42 and
#35) and repeated returns of a small block, which the detector calls an overlap
only because it does not track frees.

The table is right too. Wrapping `func_008AF2C8`, the per-entry initialiser:

```
[alloc] #45 func_008AF2C8(entry=0x20006458 owner=0x010E3760 size=4)
[alloc] #50 func_008AF2C8(entry=0x200065E8 owner=0x010E3760 size=24)
[alloc] #58 func_008AF2C8(entry=0x20006868 owner=0x010E3760 size=56)
```

Once per entry, `size = (i+1)*4`, entry[5] getting exactly the `0x18` it should.
So `{owner, size}` are correct at construction and something overwrites them
later.

**A correction to the previous round.** The page guard captures the writing
routine's registers *mid-function*, not at entry, so reading them as arguments
was wrong. `func_009DA12C`'s real arguments are `(stack_ptr, 1, 0x40000000)` and
it is called exactly once — it is not "a 1 MB, 64 KB-aligned arena setup". Those
were reused registers.

### A Canary, and an Exact Answer

`GT5P_CANARY=<addr>:<expected>` (in `src/gt5p_allocwatch.cpp`) checks a guest
word on every wrapped call, arms itself once the word first reaches the expected
value, and reports the first call after which it changed. It runs **on the
writing thread**, so unlike every earlier probe there is no buffered-stderr
ordering to guess at:

```
[canary] 0x200065E8 reached 0x010E3760 at call #138 (func_008AF2C8)
[canary] 0x200065E8 changed 0x010E3760 -> 0xFFFFFFFF, first seen at call #577
```

Correct at call #138. Wrong by call #577. The window is inside
**`func_009BFCD0`** — the GCM / video-out setup, reached
`main → func_00013EF0 → func_00668390 → func_009BFEF8 → func_009BFCD0` —
immediately before its single call to `func_009DA12C(stack, 1, 0x40000000)`,
where `0x40000000` is the GCM `ioAddr`.

Cleared inside that window: `cellVideoOutGetDeviceInfo` writes 268 bytes at
`0x011B140C` and `cellVideoOutGetState` 16 bytes beside it — both in the data
segment, nowhere near the pool.

**A caveat worth stating**, because it cost time: `ppu_prof_resolve_host` maps a
host address to the *nearest preceding* function-table entry. A frame inside
lifted code that has no entry of its own is silently attributed to whatever
comes before it. `func_009C0098` and `func_009C02A8` both appeared in these
chains repeatedly and are, on instrumenting them, **never called**.

### Found It: the Runtime Was Writing on the Game's Heap

The corruption is `ps3recomp` publishing its GCM bookkeeping into memory this
title owns.

`VM_HLE_INJECT_BASE` is where `cellGcmSys` puts the label block, the control
register, and the two 4096-entry offset tables the guest reads through
`cellGcmGetOffsetTable` — 0x8000 bytes the runtime writes without the title
knowing. It was `0x03000000` until flOw's heap grew over it, then `0x20000000`.
And GT5P maps its own 174 MB heap exactly there:

```
[cellGcmSys] MapMainMemory(ea=0x20000000, size=0xAE00000)
```

So every `gcm_publish_offset_tables()` wrote 16 KB of `0xFFFF` through the
game's allocations at `0x20003000..0x20007000` — which is precisely the range,
the value, and the halfword granularity the page guard measured.

It landed on the allocator's size-class table. Entry 5's `size` read `-1`
instead of `0x18`, `func_008B0920`'s only test is `size == 0` ("class unused,
use the general allocator"), so it never took that branch — it popped from a
free list whose links were garbage, returned poisoned pointers, and the main
thread livelocked two million iterations deep for the entire boot.

**Fixed in [ps3recomp#104](https://github.com/sp00nznet/ps3recomp/pull/104)**,
which makes the base a variable a port can set. `src/main.cpp` moves it to
`0x03000000`, a range this title never touches and which the port already
commits. With that in place the pool survives the whole boot — a canary on the
corrupted word never fires — and the main thread progresses past the livelock.

### The Next Wall

Main no longer livelocks; it blocks. From ~20 s on it sits at
`func_006CD570+0x2C`, which is `bl` to the `sys_lwmutex_lock` import with
`r3 = jobchain + 0x200`:

```
func_006CD570 -> func_006C5B60 -> func_006C5C2C -> func_006C5CF8
              -> func_006C2D5C -> ... -> func_006952A8 -> func_00693440 -> main
```

The mutex at `0x20039980` reads `owner=6, recursive_count=1`. Guest thread 6 is
**`sgx-audio-thr`**, sitting at `func_006CEC74` — the SGX audio service loop —
where it does `JobGuardNotify` then `sys_event_queue_receive`, over and over,
**holding the chain's lock the whole time**. It is not stuck: it takes 132 laps
through that loop in 40 s and 214,702 SPU jobs dispatch behind it. It simply
never lets go, and main can never get in to tear the chain down.

`cellSpursShutdownJobChain` (NID `0x738E40E6`) was **unresolved** — faked
`CELL_OK` 13 times a boot — so it looked like the obvious culprit. It is now
implemented ([ps3recomp#98](https://github.com/sp00nznet/ps3recomp/pull/98)):
the chain carries a shutdown flag, the walker honours it, and Shutdown signals
completion so a thread parked on the queue wakes. **It does not move this
title's boot.** The audio thread still holds the lock. Committed because the NID
was genuinely missing, not because it fixed the case that found it.

Also cleared: `cellGcm_fifo_recycle` is never entered (`GCM_RECDBG` prints
nothing), so `put` sitting at `0x10040` is a consequence of main being blocked,
not a separate graphics problem.

So the question is narrower than it looks: **what makes that audio loop exit?**
It waits on an event queue and re-arms; its exit condition is some guest state
that only the teardown path sets — and the teardown path is what is blocked
behind it.

### How It Was Found

Worth recording, because none of the ordinary tools could see this write.

The store is **host-side**, so `LBP_WW` and every other store watch are blind to
it. The page guard can see it, but only if it is armed at the right instant — so
`src/gt5p_allocwatch.cpp` grew a canary: `GT5P_CANARY=<addr>:<expected>` checks
a word on every wrapped call **on the writing thread**, arms once the word
first reaches its expected value, and reports the exact call after which it
changed. That gave "correct at call #138, wrong by #577" with no cross-thread
ambiguity. `GT5P_CANARY_ARM=<call#>[:<page>]` then write-protects any page at
that call, which caught the store itself and let it be bracketed page by page to
exactly `0x20003000..0x20007000`.

Two things cost real time and are worth knowing:

- `ppu_prof_resolve_host` maps a host address to the **nearest preceding**
  function-table entry, so a frame in code with no entry of its own is silently
  attributed to whatever comes before it. `func_009C0098` and `func_009C02A8`
  appeared in these chains repeatedly and are never called.
- The page guard captures the writing routine's registers **mid-function**, not
  at entry, so reading them as arguments produces confident nonsense.

### The Fingerprint Is Not FNV-1a-64

Registering a lifted SPU image means matching it by content hash, and the obvious
move is to compute that hash offline and bake in the constant. That silently does
not work here.

`spu_workload_fingerprint` is documented as FNV-1a-64 and seeds with
`1469598103934665603` — the real offset basis, `14695981039346656037`
(`0xCBF29CE484222325`), with a digit dropped. It is self-consistent, so it is a
perfectly good hash and nothing inside the runtime notices. But every offline
FNV-1a-64 implementation disagrees, and a mismatched fingerprint is not an error:
the workload is simply logged as `PM NOT LIFTED` and never runs.

This port sidesteps the whole question by computing the fingerprint at
registration time with the runtime's own function, over the image already in
guest memory. Correct whichever value the basis holds.

### Imports Resolve Without an Import Resolver

The usual approach is to patch the guest's import table at load time — walk the
PLT, write function descriptors, hope the addresses were read correctly. This
port does none of that.

Every imported function has a `li r12,0` thunk in `.text` that the PS3 loader
would have patched at boot. `scripts/gen_hle_stubs.py` reads the ELF's own module
descriptors for the `(thunk address, NID)` pairs — 439 of them across 26 modules,
all in `0x00BDD414..0x00BE0AD4` — and hands them to the lifter's `--hle-stubs`,
which emits each thunk body as:

```c
void func_00BDD414(ppu_context* ctx) {
        ps3_hle_call(0x0B168F92u, ctx); return;  /* import stub */
}
```

Resolution is then the runtime's NID registry, decided at compile time. There is
no load-time patching to get wrong, no hardcoded slot addresses to re-derive when
the binary changes, and the mechanism is title-agnostic.

### Getting to a Plain ELF Was the First Real Problem

GT5P's SELFs are NPDRM binaries with **key revision 0x0001** and NPD **license
type 1** (network). scetool and its clones refuse the RAP path for type 1 and ask
for an IDPS and `act.dat` instead, and the decryptor inherited from the previous
port produced garbage. Four separate things were wrong:

- **`pkg_extract.py` flattened the package tree to basenames.** GT5P's PDIPFS
  stores files as `A/YG`, `B/YG`, `C/YG`… so 1,716 of 3,019 files silently
  overwrote each other and the extraction looked like it had succeeded. Fixed in
  ps3recomp — this affects every title with a directory tree, not just this one.
- **The RAP initial key was wrong** (`8640B926…`, which is also what `ps3sce`'s
  bundled keyfile carries, so it is a widely copied bad value). The correct one
  is `869F7745C13FD890CCF29188E3CC3EDF`.
- **`NP_klic_key` and `NP_klic_free` were swapped.**
- **The NPDRM layer was applied as an XOR against the appldr key.** It is not.
  The 0x40-byte encryption root header gets an AES-128-CBC pass with the
  klicensee-derived key under a zero IV, *then* the appldr AES-256-CBC pass.

The fix is checked, not assumed: run against a *different* title whose decrypted
ELF was already known good, the corrected pipeline reproduces it **byte for
byte**. Only then was it pointed at GT5P.

Deriving the metadata key is the whole trick; segment decryption and ELF
reassembly are handed to `ps3sce` via its `--meta-info` option rather than
reimplemented. Hence two small scripts instead of one large one.

