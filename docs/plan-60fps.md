# Plan: a locked 60 FPS race, with headroom for upscaling

Goal (the user's, 2026-10-21): make the port lighter and easier to run, and
hold a locked, smooth 60 FPS in races, leaving room to add upscaling later.
The rolling start is designed to run at 30 FPS and is out of scope.

"Locked" means every guest frame fits in one vblank (16.68 ms at 59.94 Hz),
including heavy scenes such as a pack of cars with the mirror active. An
average near 60 is not enough. Phase 102 established that the title's race
clock follows its own timer service, not presented frames, so dropped frames
now judder instead of slowing the race.

## Where a race frame goes (Phase 102 measurements, 1080p/2x MSAA, i5-12400F, RTX 4060)

| Part | Typical race | Heavy pack | Notes |
| --- | --- | --- | --- |
| Render-list jobs (wid0/wid1, 4 lanes) | 2.6 ms | 12-13 ms | Lifted SPU code; serial before the flip |
| FIFO walk (timeline `R`) | 9-13 ms/frame | 15-19 ms/frame | Includes time parked on SPU output; CPU share not yet split |
| GPU | 4-6 ms | 8-10 ms | Headroom for upscaling exists today |
| Guest PPU threads | about 4 logical CPUs, saturated | | Timer service spins at IDLE priority |
| Audio job chain | 80% of a core | | Own core; off the frame's critical path |
| Process memory | 3.8 GB private | | After Phase 102's 1 GB cut |

Presents per 5 s in normal racing: 199-300 (40-60 FPS).

## Status (Phase 105)

- Step 1 done: `scripts/test/race.ps1 -FrameTest` (60 s on High Speed Ring
  after the rolling start; FPS, p99, share of intervals over 20 ms, walk
  per frame). Same-build runs spread widely; compare several.
- Step 2 done: the walk is CPU work, not parked waits (CPU within 2% of
  wall time). Walk 12.5 -> 9.8 ms/frame after the method fast path and
  NOP-loop parks. About 5.6 ms of it is draw recording (uploads ~2 ms,
  constant snapshots ~1.5 ms); without draws the walk is 4.2 ms and the
  frame test shows 58.8 FPS, 3.5% late. Next: cheaper draw recording.
- Step 6 done in Phase 104.
- Phase 106 skips the title's frame-pacer pad: 57.7-58.1 FPS, 7-9% late,
  p99 28-34 ms. Before it: 54.8-55.7 FPS, 13.6-15.4% late, p99 41-45 ms (from
  51.6-51.9 FPS, 27% late, p99 46-49 ms).

## Steps, in order

Each step gets an env switch and an A/B measurement before it becomes the default.

1. **Define the target in a script.** The script reports the share of race
   frames over 16.7 ms and the 99th-percentile frame time from the F8 frame
   history, plus game speed from `race.ps1 -RaceShots`. Use a fixed route:
   High Speed Ring, with a moving car past the rolling start. Track this
   number, not title-bar FPS (which disagrees with present counts).
2. **Split the walker's time.** Separate CPU work from parked waits in the
   FIFO walk (`R`), per frame. If the walk is mostly waiting, the job lists
   are the limit (step 4); if it is mostly work, make the walk cheaper: method
   dispatch, vertex/index handling, redundant state. The sampler's DLL-unwind
   attribution is unreliable here (stale return addresses); use timeline
   events instead.
3. **Cheaper guest memory access.** `vm_read*`/`vm_write*` and
   `spu_coh_is_reserved` are a large share of guest PPU profiles. Re-measure
   `GT5P_VM_INLINE` (set aside in Phase 79, before Phases 92-102), and test a
   cheaper reservation check on PPU stores. These threads were CPU-starved
   (Phase 102), so this frees time across all of them.
4. **Faster render-list jobs.** First the cheap step: native SSE4.1/FMA
   builds of the render job images, as Phase 93 did for audio (about 15%).
   Then, only where measurement still points, write an original native
   replacement for one hot geometry routine, with a mode that runs both and
   compares the output (`docs/plan-30fps.md` lists candidates; refresh its
   percentages). Never copy decompiled code into tracked files.
5. **Frame pacing.** Once frames fit, present on the vblank consistently
   (Phase 102 made the vblank exact). Then look at removing the full GPU drain
   at frame start; it costs little now (GPU waits of 0.0-0.3 ms per frame),
   but matters once upscaling adds GPU work.
6. **Lighter memory.** Size the per-draw constant buffers (198 MB),
   raw-vertex buffers and texture slots from measured peaks, as Phase 102 did
   for vertices (F8 "Per-frame buffer peaks").
7. **Upscaling, after 1-6.** A spatial upscaler (an FSR 1-class filter with
   sharpening) needs only the final image and fits the current GPU headroom.
   Temporal upscalers need motion vectors, which the title does not provide;
   treat that as a separate investigation.

## Not worth doing first

- Replacing D3D12 or WASAPI: the cost is in the emulated work, not the APIs.
- Rewriting audio DSP: it runs on its own core.
- WaitOnAddress for the patched spin waits: they already sleep in 100 us
  steps; every writer, including lifted SPU DMA, would need hooking.
