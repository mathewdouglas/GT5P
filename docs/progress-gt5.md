# Gran Turismo 5 (BCUS98114) bring-up

This log records measurements for the retail US disc build of Gran Turismo 5,
separately from both GT5 Prologue targets. The working branch is `gt5`.
Machine-specific dump and RPCS3 paths are in the ignored `AGENTS.local.md`.

## Open race rendering bugs (user report, 2026-10-29)

Seen before the Phase 23 fixes; not caused by them.

1. About 18 s into the race (and during the rolling start) the screen
   flickers and the road turns blue for a split second. Not reproduced
   after Phases 23-25: window shots every 60-80 ms over the first 40 s
   after RaceStart (`scratch/burst/bf1`, `bf2`, ~370 shots) show only the
   intro camera, START and the bridge's shadow. Hypothesis, untested: a
   dropped SPU display list (the false park timeouts of Phase 23, frequent
   at the start) leaves a frame without its road, sky colour behind.
2. ~~A dark band lies across the road ahead.~~ Fixed, Phase 25.
3. ~~The position list shows numbers but no names.~~ Fixed, Phase 24.
4. ~~After a collision the hit car's textures break into rainbow colours.~~
   Fixed, Phase 26.

## Phase 29 — A cheaper FIFO walk; where a race frame waits (2026-10-29)

Frame test (`gt5boot.ps1 -Route race -FrameTest -Settle 50`, 720p, warm
cache), one run each, same build line:

| Change | FPS | Median | Late (>20 ms) | Walk ms/frame |
| --- | --- | --- | --- | --- |
| before (`pf1`) | 43.6 | 19.5 ms | 47% | 14.1 |
| volatile textures copied once a frame (`pf3`) | 47.0 | 18.7 ms | 37% | 10.9 |
| + method runs (`mr1`) | 47.9 | 18.2 ms | 31% | 10.0 |
| + DRAW_INDEX_ARRAY coalescing (`dc1`) | 48.8 | 17.9 ms | 28% | 8.8 |
| ceiling: every draw skipped, `RSX_VTX_SKIP=1` (`vs1`) | 54.5 | 17.5 ms | 23% | 3.8 |

- **Volatile texture snapshots** (`tex_snap_draw`): a texture seen changing
  between uploads is copied at record time, and the copy was redone at
  every draw that binds it. GT5 streams textures, so many are volatile;
  the memcpy was ~15% of the walker. Now once per frame per texture
  (`RSX_TEX_SNAP_EVERY=1`: old). The first copy is also the one a later
  NV0039 copy must not replace (Phase 28), which the re-copy undid.
- **Method runs** (`rsx_process_method_run`): `RSX_METHPROF=1` (new) gives
  the method mix: ~150-200k words a frame, a third vertex-program microcode
  (GT5 re-sends each draw's program, `0x0B80`-`0x0BFC`), a third transform
  constants. The walker now hands a header's microcode and constant words
  to one call instead of one dispatch each. Rewriting microcode with the
  same words no longer advances `vp_ucode_gen`, so the VS lookup memo
  survives the re-send (`RSX_VP_SAME=0`: old). `RSX_METHOD_RUNS=0`: off.
- **Draw coalescing** (`rsx_process_draw_index_run`): libgcm splits a draw
  into 256-index `DRAW_INDEX_ARRAY` words, ~3 a GT5 draw, and each paid the
  backend's whole per-call recording. Contiguous triangle-list words of one
  header now go as one call of up to 1024 indices (the indexed path's
  limit): backend calls ~3,900 -> ~1,700 a frame for ~1,170 records.
  `RSX_DRAW_COALESCE=0`: off. Window shots unchanged.

**Texture pool: the streaming stretch.** One 5 s stretch of every run
(the same place on the track) ran at ~100-130 frames, replay 27-38 ms a
frame. `RSX_TEXUPSTAT=1` (new: uploads per frame, new or changed, bytes,
held-texture checksum time, resource creation time, the most uploaded
textures) showed GT5 streaming the next section in: ~22-35 new textures a
frame, each creating a committed texture and a committed staging buffer,
~0.24 ms per creation, ~9 ms of replay a frame. Released texture and
staging resources now go to a pool and are reused for the same
description (`RSX_TEX_POOL=0`: off; `RSX_TEX_POOL_MB`, default 192, a
quarter of it for staging; unused 600 frames: freed). The replay drains the
GPU before recording, so pooled resources are idle. Creation in that
stretch: 22.6 -> ~1 M cycles a frame (89% pool hits).

| Run | FPS | Median | p99 | Late | Longest |
| --- | --- | --- | --- | --- | --- |
| before (`ck1`) | 48.8 | 18.0 ms | 82 ms | 28% | 237 ms |
| pool (`tp1`) | 50.0 | 18.4 ms | 35 ms | 32% | 1229 ms |
| pool (`tp2`) | 45.5 | 18.5 ms | 41 ms | 35% | 2643 ms |
| pool (`tp3`) | 52.2 | 18.1 ms | 34 ms | 29% | 75 ms |

The cluster of 150-260 ms hitches every earlier run had at 137-145 s is
gone. `tp2`'s two 2.6 s gaps are the walker parked on an unfilled SPU
block (`park at io 01055080 held 2563 ms`), the shape of Phase 23's
unexplained 2.6 s frame; `cs0` (before the pool) had one of 2.8 s. Open.

Also tried, kept as switches: `SPU_DEC_FAST` (on; decrementer reads
without 64-bit divisions, ~70 -> ~15 ns), `SPU_COH_MIRROR` (on; a packed
copy of each context's reserved line so notifies skip contexts),
`SPURS_KICK_SAME_WAKE=1` (old; a kick storing the count already there no
longer signals the kernel), `SPURS_LANE_PRIO_WIDS=<wids>` (off; lanes
above normal). Together the game thread's CPU per frame fell ~0.5 ms; no
FPS change measured from any of them alone.

**Where the frame waits** (`PS3_TIMELINE` + scratch `crit.py`). The game
thread (`gFKsE`) works ~10 ms a frame, then waits in `sys_cond_wait` for a
user command near the end of its frame's commands (~8-9 ms). With draws
recorded, the walker is busy for ~6 of those ms. With every draw skipped
(walk 3.8 ms) the wait is still 7.8 ms and the walker idle most of it:
the critical path is then workload 4 (`PDI`, a WWS job list): kicked when
the game thread wakes, its pass takes 8-25 ms, its list is walked and the
user command follows. Its lanes are ~77% idle; a hot loop at LS 0x4540-
0x4600 in body `0x0196FF40` DMAs a value, compares it with three bounds
and delays 2,400 decrementer reads between tries: it waits for the
command stream to pass a label. Which label, and what holds it, is next.

Ruled out: shader work (all from cache; `RSX_SHADER_WARMUP=1` preloads
7,325 pipelines and the per-5 s frame pattern is unchanged, so the dips
follow the track), user-command delivery (raise to handler 0.3 ms mean),
`SPURS_LANE_PIN=0` (34 FPS, multi-second stalls).

## Phase 28 — One-frame texture flashes: copies ordered with replay (2026-10-29)

User video stills of the flash: the road as purple noise, grass texture on
the road, noise in the mirror, each for one frame, with "Compiling
shaders" up. The FIFO walker performs GT5's NV0039 copies (texture moves
in VRAM, Phase 21) as it walks, but replay reads texture bytes later; a
copy in frame N+1 changed textures that frame N (still replaying) or the
earlier draws of frame N+1 itself had bound. Measured: with
`RSX_COPY_SNAP_DBG=1`, many copies of 0x55580 bytes each race land on
textures of the frame being replayed.

`rsx_d3d12_before_guest_copy` (called by the NV0039 path before it copies):
waits for the frame being replayed if it binds a texture in the range (at
most `RSX_COPY_SNAP_WAIT_MS`, 30; uncapped, waits behind a replay's
pipeline wait made 0.6-0.7 s hitches), and copies every texture the frame
being recorded binds there into its `snap` list (`RSX_TEX_SNAP`'s
mechanism; `TEX_SNAP_MAX` 16 -> 128). Each frame keeps a list of its
distinct textures (`FrameSet.ts`) so the check is cheap. `RSX_COPY_SNAP=0`:
off. Cost: walker +2 ms/frame, about 1-2 FPS (`cs11`-`cs13`: 45.2/46.9 on,
47.1 off); the waits are the game's copies of the same ranges every frame,
which the console also runs in order. Not reproduced here before or after
(cold shader cache, 720p and 1080p 2x, shots every 40 ms: `fl0`-`fl3`); the
user's run compiled 7,000+ shaders, far more replay lag than these.

## Phase 27 — 1080p race drawn at full width (2026-10-29)

User report: antialiasing looks bad at 1080p. At 1080p GT5 draws the race
into a 1280x1080 surface (`0x01980000`, surface AA mode 3, 2x side by side,
which the backend does multisample) and stretches it to 1920, as on the
console: soft, stair-stepped edges. GT5P's `RSX_RACE_FULLWIDTH` makes a
2/3-width race surface full width, but only with native scaling on
(`RSX_RENDER_HEIGHT` above the guest height: 1440p, 4K). The backend now
accepts `RSX_RENDER_HEIGHT` equal to the guest height (scaling paths on, no
extra rows), and GT5 sets it to 1080 at 1080p (`src/main.cpp`; an explicit
`RSX_RENDER_HEIGHT` or `RSX_RACE_FULLWIDTH=0` overrides). The scene target
becomes 1920x1080; HUD, mirror and list unchanged; lamp posts and barrier
edges visibly cleaner (`scratch/pv/aa_crop.png`). One run each: 48.7 FPS
(1280) against 45.8 (1920). The menu is not affected; its wavy grandstands
are the same either way (depth of field or haze, not investigated).

## Phase 26 — Rainbow noise on damaged cars (2026-10-29)

Reproduced with the chase camera (`gt5boot.ps1 -ExtraHold
"@RaceStart+3000-3200:SELECT"`, new): every car hit showed rows of
coloured noise on its body. RenderDoc pixel history (`RSX_RDOC=1`) put the
body on a draw sampling a 256x512 map whose top half held scratches and
whose bottom half was noise. Each car has such a map (`0x0xxx9100`, guest
unit 8): cleared opaque black at race load, and on a hit the game blends
the damage over it (program `0x06A41401`, viewport the whole map).

- **The map was created from main memory.** A new render target is filled
  from guest memory first; the address came from `cellGcmResolveOffset`,
  which prefers the IO mapping, and GT5 maps main memory to IO from offset
  0: the target at local `0x06A99100` was filled from `0x46A99100`. The
  damage, blended over that, left the rest as noise. Targets are now
  filled from local memory (`RSX_RT_INIT_LOCAL=0`: as before), as the
  eviction write-back already writes (Phase 21's car paint).
- **Units 4-15 read guest memory, never the live target** (the scale
  constants exist for units 0-3 only). Unit 8 now binds the target when it
  is an exact match: whole, same size, single-sample, not texel-addressed,
  not the draw's own target (`RSX_RT_TEX_HI=0`: units 0-3 only).

`RSX_CAP_RT=~<hex>` (new) captures the first frame drawing (not clearing)
to any surface whose low 16 bits match (`~9100`: any car's map).

Also open: occasional 0.4-3 s hitches in a race, a FIFO park held while a
few new shaders compile (`db3`: 2.7 s at 40 s into the race; `pn1`-`pn3`
2.6-3.0 s; `ab2` 0.24 s). Under the 3 s park timeout, so no dropped list.

## Phase 25 — Dark band ahead of the car (2026-10-29)

`RSX_SHADOW=0` (every shadow compare passes) removed it, so it was the
shadow lookup. Two faults:

- **Z16 clears read as D24S8.** The shadow map (`0x05380000`, surface
  format 0x128: depth format 1, Z16) is cleared with value `0x0000FFFF`,
  far. The clear decoded every value as D24S8 (depth = bits 8-31, stencil
  = bits 0-7): depth 1/65536, stencil 255. The scene compares with GEQUAL
  (unit address bits 28-30 = 6: lit where stored >= reference), so
  everywhere without a caster read as shadowed. Z16 clears now take the
  depth from the low 16 bits (`RSX_Z16_CLEAR=0`: as before;
  `rsx_commands.c`).
- **Three buffers for one shadow map.** GT5 stacks three cascades in the
  1024x2048 surface (rows 0-682, 682-1365, 1365-2048), each drawn with the
  target capped at its own scissor bottom, so the depth-only buffers were
  keyed 1024x682, 1024x1365 and 1024x2048; the lookup bound one, holding
  only its own cascade. A larger buffer for the same surface now serves
  smaller requests (`RSX_ZB_SHARE=0`: one per size). Alone, this made it
  worse (all three cascades present, all cleared "near"): the clear above
  had been hiding behind the missing data.

Road brightness (mean of open road, near/mid/far): no shadows 70/72/101;
before 80/87/71 (the band); shared buffer only 43/49/47; both fixes
73/74/107, with car shadows still cast.

## Phase 24 — Race position list names (2026-10-29)

**How GT5 draws a name.** At the start of a race, for each of the list's
rows, in one frame: target a 256x48 label (`0x0F445180` + 0xC000 per row,
zeta `0x01100000`) and clear it; fill each glyph's outline into the stencil
of the 2048x1080 depth surface at `0x01100000` (ZERO with write mask 0xFE
over its box, then INVERT with mask 0x80); then draw the name into the
label with program `0x0581FD41`, which samples that surface as A8R8G8B8
(remap 0xAAFF: every channel from B, the stencil byte) and uses its alpha
as coverage. The list then samples the labels every frame. The backend's
glyph-mask redirect turns the stencil fills into a colour target at
`0x01100000`; that part worked (its first row shows the glyphs).

**Three faults, each enough to empty the labels:**

- **Pipelines still compiling.** The label draws are made in one frame
  only, and replay leaves out any draw whose pipeline is still being built
  in the background (`dpso=NULL fp_pending=1`). Draws into offscreen targets
  smaller than the screen now wait for theirs: at most
  `RSX_PSO_WAIT_OFFSCREEN_MS` (500; 0: leave out) per frame in all, and a
  draw whose wait once ran out is not waited for again. Measured waits:
  15-16 ms. The first version waited for every offscreen draw, the race
  scene's 1280x720 target included, up to 500 ms each: 2.6-3.0 s hitches
  in three of three races; scoped as above, 53.6 FPS with a 240 ms worst
  frame (`ab2`, against `ab0` 52.8 FPS / 1.0 s with no wait).
- **16 render target slots.** A race frame already uses 16 before the
  labels; `off_rt_get_impl` then returned -1 and labels 2-9 had no target.
  `MAX_OFF_RTS` is 64 and `RSX_RT_SLOTS` (default 48; 16 = old) the number
  used. Targets 16 and up keep their SRVs at heap slot 32 onward
  (`RT_SRV_SLOT`; slots 21-23 are taken), and the per-draw windows moved
  up to `DRAW_SRV_BASE` 80.
- **Stale targets, once the slots stopped churning.** With 48 slots a menu
  target at `0x05A81100` (800x452) outlived its screen, and the race HUD's
  images later loaded into that memory sampled its picture: the HUD's
  labels and gauge panels disappeared. A target nothing has drawn to for
  `RSX_RT_RETIRE_FRAMES` frames (120; 0: never) is now retired through the
  eviction write-back: its pixels reach guest memory if that still holds
  what the target was made from (the labels, which the list then samples
  from memory), and it is dropped if the title has put something else
  there (the HUD's images).

Also: GT5 now waits 3 s for an unpatched FIFO park
(`GCM_PARK_TIMEOUT_MS=3000` from `src/main.cpp`; the runtime keeps 500 for
GT5P). A genuine 500 ms hold during a burst of shader compiles dropped a
list and cost a 5 s stall.

New tools: `RSX_CAP_RT=<surface>` (capture the first frame drawing to it),
`RSX_RDOC=2` with it (RenderDoc frame capture of exactly that frame),
`RSX_SKIPDBG_RT=<surface>`, `RSX_FP_OUT=<fp>:<hlsl>` (replace a program's
output, to read intermediate values from a target), `RSX_DBG_VP_FP=<fp>`,
`GCM_FTRACE_ARGS=1`, `GCM_VAL_WATCH_FT=<n>` / `_FT_HIT=<k>`.

## Phase 23 — Race freezes: two shapes (2026-10-29)

**The kick-to-dispatch delay was a measuring error.** `tl.py` charged the
kicks the game issues while a pass is running (it appends jobs, which the
running lanes take) to the next dispatch. Counting only kicks that reach an
idle workload: 0.01-0.11 ms for every workload. Fixed in `tl.py`.

**Where the game thread waits.** `gFKsE` puts a user command at the end of
its frame and waits (about 9 ms a frame) until the FIFO walker reaches it;
the pump delivers it about 0.7 ms later on the next guest HLE call. The walk
(about 11 ms of CPU a frame) is therefore the game thread's wait, on top of
its own 10.9 ms.

**Row history.** `SPU_ROWLOG_N=<n>` sets the entries per line (default 64),
each entry now carries the writer's last SPU PC, and `SPU_ROWLOG_OUT=<file>`
sends the dump to a file. 131072 entries cover about 30 s of a render list.

**The freeze: a dropped job** (`fz1`, `infl1`; both at the same place,
about 85 s into the frame test). On list `40240080` one SPU's slot took a
job (pc 0x3334) and never wrote 0xFFFF; the other lanes all leave through
0x3334 -> 0xFFFF. Just before, the log has

    [spu_interp] unimplemented op 'mpyui' (0x75340384) at LS 0x063E0
    [SPU] BRANCH-TO-0 unresolved pc=0x063E0 image=1 lr=0x0A99C

The job manager (pc trail ending 0x2C38, the job allocation) resumed a
job at 0x063E0, mid-function in body `0x016AD700` (0x63A8-0x63F8, after
an `mpyh`), where nothing is lifted. Such a resume point is an interrupt
taken while the SPU interpreter ran (it saves a precise SRR0; lifted code
only at transfers). The interpreter lacked `mpyui`, the lane's module was
abandoned with the job in its slot, and the game waited on that slot for
ever. Fixes:

- **Interpreter:** `mpyui`, `rothmi`, `rotmahi`, `mpyhhau`, `bgx` and the
  double-precision ops were decoded but had no case. `mpyhha` wrote its
  result to `rc`, which in its RR format is part of the opcode; it now
  accumulates into `rt`, as the lifter does.
- **Lifted entries:** the interpreter ran at all because body
  `0x016D2700`'s switches (LS 0x10BA8, 0x10D00, 0x11024 table) add a load
  offset they compute (`r79 = r11 - r12`) instead of r126, which
  `pic_tables` required. It now accepts any register when a `bi` follows
  (`SPU_PIC_ANYREG=0` at lift time: r126 only); 65 new entries in that body.
- `SPURS_LANE_INFLIGHT=1` (GT5P Phase 63, off) re-entered the lane, which
  left again within microseconds: the module had dropped the job. Its
  address bound (`< 0x40000000`) skipped GT5's lists at 0x402xxxxx;
  `wws_addr_ok` now accepts any committed page below 0xC0000000, queried
  and never committed (`SPURS_WWS_LOW=1`: old bound).

The lane mask keeps the old bound: GT5's headers hold four 16-bit queue
masks at +0x20..+0x2F (workload 5: `03FF 03FF 000F 000F`), so +0x2F is no
SPU mask; read as one, workload 5 ran on one lane.

**The 5-10 s stalls: a false park timeout** (`fix1`, `cv1`, `ww1`, `uc1`;
every stall). Once the dropped job was fixed, races ran on but stopped
presenting for 5-10 s a few times each. The game thread waits on an event
object at `0x01AE7E80` (`func_00D320A8` sets byte +8 each frame,
`func_00D32128` clears it from the user-command handler, on whichever
thread the pump runs; `sys_cond_wait` with a 5 s timeout). At each stall
user commands raised = delivered, but one to four fewer than frames
presented: the walker had skipped some. Every stall follows
`park at io ... unpatched for 500 ms: following put`. The park timeout
(`GCM_PARK_TIMEOUT_MS`, from GT5P) measured a hold that only reset when
the walker parked somewhere else or after a 100 ms gap. GT5's SPU lists
are the same size every frame, so the walker parks at the same io each
frame, briefly, and the hold added up across frames
(`GCM_PARK_TIMEOUT_MS=0` printed one "held 67 s" while frames ran
normally). At 500 ms the walker dropped a live list, user command
included. The hold now also resets whenever a method has been walked
since the last look (`GCM_PARK_PROGRESS=0`: old rule).
New: `PS3_COND_TRACE_ID` signal lines name the thread and lr; the stall
dump counts user commands raised and delivered.

**Boot load stuck: lanes halted as "wedged"** (`pp1`, also `pt3` on
2026-10-28). The runtime halts an SPU after 256 identical DMA transfers in
a row (`SPU_DMA_REPEAT_LIMIT`), with a 120 s grace for small reads that
poll a label, up to 16 bytes. The job manager (image 1, pc 0x2534) polls its
job queue's 128-byte line (workload 4: 0x40016000) the same way while it
waits for jobs; at boot three lanes were halted there and the load never
finished. Most race runs show one such halt on 0x01AC0C80. Reads of up to
one line now get the grace (`SPU_DMA_REPEAT_LINE=0`: 16 bytes).

**Result** (`pq1`-`pq6`, all three fixes, 100 s frame test each): six of
six reached the race and ran the window without a stall (3 s without a
present) or a halted lane. Before, about one race in three froze or
stalled.

| Run | FPS | Median | p99 | Late (>20 ms) | Walk |
| --- | --- | --- | --- | --- | --- |
| pq1 | 38.0 | 23.4 ms | 72 ms | 73% | 13.3 ms |
| pq2 | 52.1 | 17.1 ms | 56 ms | 20% | 8.7 ms |
| pq3 | 52.3 | 17.1 ms | 58 ms | 20% | 8.7 ms |
| pq4 | 52.0 | 17.1 ms | 62 ms | 20% | 8.6 ms |
| pq5 | 40.0 | 19.5 ms | 122 ms | 47% | 10.7 ms |
| pq6 | 52.5 | 17.4 ms | 53 ms | 23% | 9.0 ms |

Four runs near 52 FPS, two slower (host load is not controlled). `pq5`
has one 2.6 s frame, below the stall dump's 3 s, not yet explained.

**Ring space** (`inf1`, with that mistaken mask only). Workload 4's
three lanes spin at pc 0x04600 polling GCM labels 0x49-0x4B (guest
0x03000490..), which semaphore releases in the command stream write. The
FIFO is drained (get = put) and the game thread waits on workload 4's
progress row (0x2CB of 0x2EF): a circle. The stall dump now prints labels
0x40-0x5F.

## Phase 22 — Performance: first measurements (2026-10-29)

**Frame test.** `gt5boot.ps1 -Route race -FrameTest [-Cpu] -Settle 60`
holds Cross from RaceStart, logs every present (`GT5P_FRAME_LOG`) and
reports FPS, median/p99 interval, late share and FIFO walk over the window.
Its in-script window filter sometimes keeps only part of the log; the
reliable numbers below are over the log's last 55 s.

| Run | FPS | Median | p99 | Late (>20 ms) |
| --- | --- | --- | --- | --- |
| baseline (`perf0`) | 43.9 | 18.4 ms | 60 ms | 39% |
| inline memory on (`perf1`) | 35.3 | 24.8 ms | 91 ms | 81% |
| same build, `VM_INLINE=0` (`perf1b`) | 38.3 | 24.8 ms | 54 ms | 95% |
| + SPURS SPU count fixed (`perf2`) | 43.8 | 21.0 ms | 57 ms | 62% |

Run-to-run noise is large (the host has 26% background load); one pair is
not a verdict.

**Inline guest memory.** The sampler (`GT5P_SAMPLE=4`) had the busy guest
threads mostly in out-of-line `vm_read32`/`vm_write64`: this build's cache
had `GT5P_VM_INLINE=OFF`, though the option defaults to ON. Rebuilt ON (exe
244 MB). The one A/B within the build was 3 FPS worse inline. Unresolved:
re-measure, and look for guest spin loops that inlining makes hotter.

**SPURS SPU count (fixed).** `_cellSpursAttributeInitialize` is the library
export with `(attr, revision, sdkVersion, nSpus, ...)`; the runtime
forwarded it as `(attr, nSpus, ...)`, so the revision (2) became the SPU
count. GT5 asks for 5 (`"PDI"`, render) and 1 (`"sgx-spurs-"`, audio):
`PS3_HLE_ARGS=95180230`. Both ran as 2-SPU instances, which the policy
module and `cellSpursGetNumSpuThread` report. `SPURS_ATTR_OLD_ARGS=1`:
old reading.

**Where a frame goes** (`PS3_TIMELINE=112,6` + `tl.py --sum`, 278 frames,
21.5 ms mean):

- The game thread (`gFKsE`, guest tid 27, the one calling
  `cellGcmSetPrepareFlip`) blocks about 9 ms a frame in a condition wait
  until the present thread has presented and walked the FIFO. In a 34.7 ms
  frame that wait was one 21 ms present call.
- The FIFO walk is about 11 ms of CPU a frame; replay about 11 ms on its
  own thread.
- Render workloads 0-2 (`Wws_Job/ElemSetRenderHP`, `ElemSetRender`,
  `ElemSetUpdate`) wait 14-20 ms on average from kick to dispatch;
  4 and 5 dispatch within 0.3 ms. Not yet explained.

**Freezes.** About one race in three stops presenting.

- **Permanent kind** (`perf0`, `pp1`): `gFKsE` (and `9qstY`) spin in
  `0x00C350C4`, a loop over `func_00D1AB10` (yield `0x00C450C0` between
  tries). That function takes the minimum of a job list's progress row:
  +0x40 + 16 x queue, with +2 completed and +4.. one slot per lane, 0xFFFF
  when idle. It waits for that minimum to reach a target. In `pp1`
  workload 1's row was one short (0x669 for 0x66A): a lane slot that
  never cleared.
- **Recoverable kind** (`perf1`, `spin1`): a few seconds, then frames
  resume.
- `SPU_ROWLOG=40240080,40232080` caught a slot sitting at 0x0740 while
  the others advanced. Its 64-write ring covers only about 5 ms, too short
  to see the moment a slot freezes; a longer history is the next tool. This
  is the family of GT5P Phases 64 and 92 (`SPURS_PM_ARG64` is on and does
  not cover it).

## Phase 21 — The race runs; a faster route there (2026-10-28)

**Status.** Arcade → High Speed Ring → race, at 30 fps on the grid screen
and 40-60 fps racing. The purple road is fixed (2026-10-29, next
paragraph): asphalt, markings, kerbs, banners and mirror now draw. Still
to check against that fix: the kerbs' rainbow noise and the noisy barriers
(the shot after the fix shows neither), the livery of a car in the mirror.

**Clock wrong (fixed, 2026-10-29).** The menu clock is not built from
`cellRtc` at all (`RTC_TRACE=<n>`, new, logged no call on the way to the
menu): GT5 reads `sys_time_get_current_time` (correct) and converts it with
`sys_time_get_timezone`, syscall 144. That was an unregistered stub: it
returned CELL_OK and wrote nothing, so the conversion used whatever its two
variables held. That is why the time and date differed at boot and on each
page load (3 minutes ahead and 10 days behind in one report). Syscall 144
now writes the host's zone. Daylight saving is folded into the zone and
the flag reported as 0: with the flag set separately, GT5 showed New
Zealand summer time an hour behind, so it ignores the flag
(`PS3_TZ_HOST=2`: standard zone plus flag, `=0`: UTC). The system
parameters TIMEZONE/SUMMERTIME (were UTC, no DST) report the same
(`SYSPARAM_TZ_HOST=0` old). Measured: 12:08 shown from 12:08:38 to 12:08:58,
12:09 at 12:09:08, date 29 on the 29th.

Also found unregistered on the way, both answering a fake CELL_OK:
`cellRtcIsLeapYear` (said no for every year; now Gregorian) and
`sceNpManagerGetNetworkTime` (wrote no tick; now the host's UTC when
signed in, `SCE_NP_ERROR_OFFLINE` otherwise, `NP_NETWORK_TIME=1` always
the host time). `src/gen/ppu_hle_nids.cpp` regenerated (`--all`): those
two registrations are the only change.

**Loading-logo reflection showed the menu (fixed, 2026-10-29).** The GT
logo's moving reflection band (program `0x05809341`, logo body
`0x05807E81`) samples a 256x159 image at a scratch surface (`0x03780000`
or `0x02880000`, alternating). The game first draws the logo into that
surface's top-left corner: a 2048-pitch surface, scissor 256x160 and
viewport rectangle 1088x620, with VIEWPORT_SCALE (960, -540) and OFFSET
(128, 80), i.e. a full 1920x1080 frame centred on the corner. The backend
placed primitives by the viewport rectangle and ignored scale and offset
for x and y. The logo landed mid-rectangle, the scissor removed all of
it, and the band sampled what the menu's blur chain had left in the
corner. `RSX_VP_XFORM` (on; `=0` off) places the D3D viewport by scale and
offset whenever they describe a different rectangle (y flipped); the clip
is still the rectangle and the scissor. Only these two passes differ in
the menus and the race (`RSX_VP_XFORM_DBG=1` lists them).
`VP_VIEWDBG_RT=<offset>` limits `VP_VIEWDBG` to one surface. Found with ID
colours on the loading screen, `RSX_TEXDUMP_FP` and an `RSX_CAP` of a
loading frame.

**Speckled car paint: evicted render targets (fixed, 2026-10-29).** Every
car's paint showed multicoloured per-pixel noise, in the mirror and in the
main view. The paint program (`0x05E00A01`, found by ID colours read from
the raw scene target) takes its diffuse colour from unit 8, a 256x512
linear ARGB texture at `0x05E59100`. GT5 renders that texture once per
car at load: it is a render target. The race load then needs more than
the backend's 16 target slots and evicts it, and the contents existed only
on the GPU. Unit 8 then sampled the never-written local memory. Units 4-15
never resolve to targets by address anyway.

`RSX_RT_EVICT_WB` (on; `=0` off) reads an evicted target back into guest
local memory before releasing it. It writes only while the guest bytes
hash the same as when the target was created, so anything the title wrote
there since wins. The readback uses its own command list (the frame's list
is open mid-replay) and the eviction's existing GPU wait.
`RSX_RT_EVICT_WB_DBG=1` logs each eviction and why it was or was not
written back. Pitfall met on the way: `cellGcmResolveOffset` resolves a
local surface offset through the IO map, to main memory (`0x05E59100` gave
`0x45E59100`); the first version wrote there and hung the game. The
write-back uses `cellGcmResolveLocated(1, off)`. The target creation path
still fills new targets through `cellGcmResolveOffset` (not changed;
GT5P depends on it).

Also checked on the way: the car reflection cube (unit 14, six 256x511
linear faces with the mip chain stacked below at the same pitch, rebuilt
each frame by downsample draws) is assembled correctly by `RSX_CUBE_RT`.
`RSX_TEXALL_FP=<fp>[,n]` (new) prints every bound unit of a program's
draws with format, mips, cube, control0, filter and address.

**The black border is the game's own screen-size option** (user). GT5
draws its picture into a centred 1152x648 rectangle at `0x01AE6280`
(x 64, y 36), set by func `0x00A35DB4`.

**The purple road was a dropped copy engine (fixed, 2026-10-29).**
GT5's libgcm binds the NV0039 memory-to-memory engine to FIFO subchannel 1
(`cellGcmSetTransferData`, func `0x00D38134`: headers `0x00082184` DMA
in/out, then `0x0020230C` offset in/out, pitch in/out, line length, line
count, format `0x101`, buffer notify). The FIFO walker sent subchannel 1
to the 3D engine, a rule made for Gran Turismo 5 Prologue's SPU lists,
which put NV4097 methods there. NV0039 was not implemented at all. So
every copy was dropped, and its registers landed on NV4097's alpha-test
and blend methods (`0x30C`-`0x328`). Two things depend on those copies:

- **Texture tails.** Every texture is loaded in two parts: chunks the SPU
  inflates (lifted body `0x01788E00`), and a small-mip tail copied from a
  staging area (entry `+0`, size `+4` of the 32-byte texture table
  entries). Those tails were never copied.
- **Heap compaction.** When a texture is freed (func `0x00C28530`), the
  texture manager's tick (func `0x00A22A54`) runs the allocator's
  defragmenter (func `0x00C288D4`, 8 MB a tick). That asks the owner
  (vtable `0x01886EC8`) to start a move: `+8` = `0x01091788` issues the
  NV0039 copy through func `0x00D2A970`. Later it calls `+0x10` =
  `0x010916DC`, which repoints every material record holding the old
  offset. With the copy dropped, the records moved and the bytes did not.
  On High Speed Ring the colour texture (handle `0x816`, DXT5 512x512)
  slid into the slot of a freed 1024x512 DXT1 normal map of the same
  rounded size (`0x55580`). The road's colour layer then sampled the
  normal map: the lilac colour.

`GCM_SUBCH1_M2MF=1` (set by GT5's `main.cpp`; `=0` for the old routing)
sends subchannel 1 to a new NV0039 engine in the walker: line copies with
memmove, in the order that is safe when source and destination overlap.
Only format `0x101` (byte in, byte out) is implemented; anything else is
logged and skipped. Before the fix, every run checked had a normal map on a
colour unit; after it, none did (`RSX_TEXNM_CHECK=09B96581`).

How it was found, for the next one like it:

- `SPU_JOBDESC=<ea>` logs each inflate job's parameter block with a hash of
  its source, and flags a source rewritten under a running job. There
  were none, so a staging-buffer race was ruled out.
- `FS_READLOG=<lo>-<hi>` (`FS_READLOG_FRAMES=<n>` adds guest call chains)
  logs `cellFsRead` landing in a range.
- `PPU_WVAL=<value>` on the destination address found the allocator
  (func `0x00C28B54`, first fit, handles mapped to addresses by a hash).
  On the record offset it found the record fix-up (func `0x00A20B68`,
  key = allocator handle).
- Temporary prints in the generated loader (func `0x00A21884`, a state
  machine: queue, sorted file-key table, allocate, inflate chunks, insert)
  showed the load itself consistent.
- `GCM_VAL_WATCH=<value>` now prints the next two words, the guest address
  and the flip (`GCM_VAL_WATCH_MAX=<n>`). It showed the SPU-built ring
  setting unit 0 to the normal map's offset with the DXT5 format word.
  It also showed the stray NV0039 words on subchannel 1.
- `GT5P_MEMSNAP=RaceStart+12000` caught the allocator table after the
  compaction: handle `0x816` at the old normal map's address.
- `GCM_M2MF_DBG=<n>` logs the first n copies.

**The race load hung the GPU.** Every run reached the race loading screen
and then crawled at 1-2 fps for minutes, the bar near full. The first race
frame drew with `DEVICE_HUNG` (0x887A0006); the backend kept replaying
against a removed device, 700-950 ms a frame. The debug layer reported
nothing. DRED (new, `RSX_DRED=1`) put the fault in a `CopyTextureRegion`
reading a freed resource; logging each copy's source line per list named
the copy that fills a new offscreen render target from guest memory. That
frame evicts 17 of the 16 target slots, four resources each, into the
64-entry deferred-release list; it overflowed and released the rest while
the open command list still used them. The list now grows
(`RSX_RT_GRAVE_GROW=0`: the old fixed 64). Same frame, same fault in all
three runs before; none after.

**New diagnostics (ps3recomp):**

- `RSX_DRED=1`: DRED auto-breadcrumbs and page faults. On a removal the
  report lists each unfinished command list's ops around the last one the
  GPU completed, the source line of that copy (copies log their line per
  list, since this driver kept no marker strings) and the faulting VA.
  Draws set a marker too (record, fragment program, target).
- `PAD_FILE_LOG=1`: `[file] <path> at <ms>` on the first open or stat of
  every guest path, on the milestone clock.
- `PAD_MILESTONE_FILES` takes `<label>=<path tail>` entries: GT5's PDIPFS
  base names are two characters, so screens are named by path tail.

**Route (`scripts/test`).** GT5 has no `.gpb` screen scripts, so the route
pressed every 15 s from MusicDecode. A `PAD_FILE_LOG` run matched each
screen's first file with window shots: Arcade `9/HV/GE`, track list
`9/7B/M3`, car list `9/9U/4I`, transmission `5B/PF`, race load `5K/E1`,
race start `55/04` (difficulty and colour read nothing new). Every step
after the icon bar is Cross on the default, so the route presses Cross
every 3 s until the screen wanted:

| `gt5boot.ps1 -Route` | Reaches | After the menu |
| --- | --- | --- |
| `carlist` | car list | 19 s (was 52 s) |
| `grid` | race loading, then the grid screen | 28 s to RaceLoad (was 110 s) |
| `race` | racing (Start on the grid screen) | 59 s |

The script prints each milestone with its time; `-ShotsFrom` picks where
shots start (grid: RaceLoad, race: RaceStart).

**The purple road: textures loaded into each other's slots (superseded by the fix above;
2026-10-29).** Measured, with the scene target read raw
(`RSX_CAP_ALLRT=1`, below) instead of through tone mapping and motion blur:

- Road program `0x09B96581` blends four colour layers (units 2, 3, 1, 0),
  then lighting, specular and fog. Snapshots of each stage
  (`FP_SHOW_AT`) show the colour already blue before any lighting: the
  unit-0 layer adds it. Light vector, lightmap, shadow and constants are
  all sane (`RSX_VCB_DBG`: c462 = (2, 1, 0.5, 8), c466 the sun).
- The game's texture descriptors (68-byte records holding a prebuilt
  SET_TEXTURE block, near `0x46FD7000`; found by searching a
  `GT5P_MEMSNAP` snapshot) all agree: `0x0B3E6480` is a 512x512 DXT5 colour
  texture (sRGB), `0x0B59BF00` a 1024x512 DXT1 normal map. Video memory
  holds the opposite: a 1024x512 DXT1 normal map (road-marking panels)
  at `0x0B3E6480`, 512x512 DXT5 tyre marks at `0x0B59BF00`. With mips the
  two are 0x55570 and 0x55568 bytes, equal once rounded to 128.
- The bytes come from an SPU decompression job (lifted body `0x01788E00`)
  that inflates a compressed chunk from one staging buffer (`0x48DBA000`)
  into video memory; its descriptor is {0, 0x4FAE8520, source, source size,
  destination, output size} (`SPU_DMA_RANGE_HIST` with
  `SPU_DMA_HIST_LS=A800:80`). So the PPU paired the normal map's chunk with
  the colour texture's destination: the pairing of file chunks to
  destinations is swapped for equal-size textures, which suggests a sort
  whose tie order differs here (heap addresses or a recompiled compare).
  The job builder is called from `0x00DC6614` ← `0x00DC8184` ←
  `0x00E6775C` ← `0x002ACC74` ← `0x002AD424`; the pairing code is not
  found yet. Next: Ghidra/REA on that chain.
- Same layout in every run checked (deterministic). `RSX_TEXNM_CHECK=<fp>`
  lists every colour (sRGB) unit of a program whose DXT data averages like
  a normal map.
- Separate, open: one road draw has `0x0B4BBD00` on unit 2 as a 1024x128
  DXT5, while every command block in memory sets it on unit 3 as a
  2048x128 DXT1. Not yet known whether the game or our state tracking
  pairs them.

New diagnostics (ps3recomp): `RSX_CAP_ALLRT=1` (every live target,
16-bit UNORM supported), `FP_SHOW_AT=<n>` (the `FP_SHOW` value just
before statement n), `RSX_VCB_DBG=<vs hash>[,n]`, `RSX_VPLAN_DBG=<n>[,attr]`
(every attribute a vertex program reads, with raw bytes of the first
vertices), `RSX_TEXDUMP_FP`/`_UNIT`/`_AROUND`, `RSX_TEXNM_CHECK`.
`scripts/test/rdcap.ps1 -Gt5Race` captures a race frame in RenderDoc (it
lost the device on this machine: memory).

Earlier notes, superseded by the above:

- The road is fragment program `0x09B96581` (found by painting candidate
  programs red with `FP_SHOW`/`FP_TEX_FP`; the barriers are `0x0A779301`,
  the stands `0x0A777E01`).
- Its shader blends the sample of unit 0 into the colour by that sample's
  alpha (a lerp over the asphalt, unit 2). The game binds a 512x512 DXT5
  normal map (embossed lettering, alpha noise) to unit 0 at `0x0B3E6480`;
  that is the lilac colour and the noise. The bytes are stable (identical
  dumps 3000 binds apart) and decode cleanly as DXT5, so the binding and the
  data agree; the open question is why the program treats that unit as a
  colour layer. Earlier in the boot the same address was bound as a
  512x1024 DXT1.
- Not it: shader cache (cold cache also purple), shader pack and recipes,
  the Phase 19 border/half-float upload switches, the SRV cache, texture
  unit decoding (4-bit field), default components of short vertex arrays
  (tried (0,0,0,1): no change, reverted), the vertex colour (tc0 measured
  (1,1,1,0.75)) and the light vector (col0 measured, plausible).
- One run drew the road correctly; a repeat of the same settings did not:
  the fault is timing-dependent.
- Tools for this: `FP_IDCOLOR=4` (ID colours for the `FP_TEX_FP` list
  only; the scene's tone mapping blows flat colours to white, so threshold
  grids work better: `FP_SHOW` with `(value > column threshold) ? 1 : 0`),
  `RSX_CAP_VPC_FP=<fp>` (vertex constants of that program's draws; the
  values read look stale, so treat them with care), `RSX_TEXDUMP` with
  `RSX_TEXDUMP_SIZE` now matches both, `FPK_FP` prints up to 32 constants.
  The kerbs' rainbow noise is a separate 1024x128 DXT1 normal map (unit 5
  of the kerb draws), not yet examined.

## Phase 20 — No more car-list freezes: MFC slots leaked (2026-10-28)

**Status.** Arcade → car list → pick a car → colour → transmission → race
loading, with no freeze in 8 runs (4 idling on the car list, 4 picking a
car). The user watched one load into the High Speed Ring race. The car list
runs at about 45 fps (225 frames per 5 s, from about 40).

**Cause.** Every SPU context needs an MFC engine (DMA queue and tag state),
held in a 32-slot table (`spu_channels.c`). Only the lifted SPU thread path
released its slot. One-shot job contexts (`spu_run_lifted_job_abi`,
`spurs_job.c`) are stack locals, often on new threads, so each run took a
fresh slot. GT5's movie converter task runs every frame, so the table filled
on every boot (`more than 32 contexts hold an MFC engine`). Every context
after that shared one fallback engine: a list one of them parked on a
stall-and-notify left its tag busy for all the others, and a render lane
then waited for ever on that tag (job manager load state 3, helper
`0x22C0`, mask 2). That was the "idle loop" freeze shape of Phase 19.

**Fix (ps3recomp):**

- Job contexts release their slot when they end
  (`spu_mfc_release_job`; `SPU_MFC_RELEASE_JOBS=0`: old).
- The table holds 128 (`SPU_MFC_SLOTS=<n>` caps it), and `mfc_for` keeps a
  per-thread cache in front of the scan, invalidated by a generation count
  on every release.

The Phase 19 stall-notify deferral (`spu_sn_defer`) stays on; untested
without it now.

**Test harness:** `PAD_HOLD` held 64 timed presses, and `$GT5BootHold` alone
is 59, so presses added after the car-list route were dropped silently: the
earlier "pick a car" runs never picked one. It now holds 256 and says so
when more are given.

**The loading dip, measured (not fixed).** Entering the car list, about
2.5 s of 60-85 ms frames, then a steady 45 fps (`GT5P_FRAME_LOG`, a
`PS3_TIMELINE` across the entry, `tl.py`):

- The FIFO walk stays at 8-14 ms a frame, and no guest or host thread is
  saturated (`GT5P_SAMPLE=12`): the frames wait on SPU work.
- The render workload `Wws_Job/GPUSyncArray` (wid 4; the game allows it 4
  SPUs, `maxC=4`) takes about 65 ms a pass for those 2.5 s, then about 21 ms:
  the 21 ms is what holds the car list at 45 fps.
- `GT5P_SAMPLE_WID=4`: 65% in job body `0x0196FF40` (its software-pipelined
  loop `0xB240` alone 21%), 35% runtime (`mfc_do_transfer` 8%,
  `spu_indirect_branch` 7%, `spu_lookup_fast` 4%, `spu_drain_call_impl` 4%).
  The dip's profile is the same as the steady one: the same jobs do about
  three times the work for a while (plausibly the reflection cube built on
  entry), not different code.
- Not it: pipeline creation (about 220 new pipelines on entry; background
  creation and startup preload each change the dip little), lane pinning
  (`SPURS_LANE_PIN=0`: 41.9 fps against 45.1), `spu_fma` (no libm call).
- So the dip and the 45 fps are SPU compute. Faster needs GT5P-style work on
  this body: a native replacement for its hot loop, or cutting the dispatch
  overhead.

**Next:** the race (High Speed Ring loads), then the SPU render cost above.

## Phase 19 — Cars painted; fewer car-list freezes (2026-10-28)

**Black cars: fixed.** The cars drew glossy black: reflections, no paint.

- The paint program (`fp 0x05D90601`) takes diffuse light from unit 11, an
  8x8 half-float cube (`W16Z16Y16X16`, `0x9A`). The car's cube is built by
  job body `0x01769000` from lighting coefficients and PUT to `0x4FA46000`
  (12288 bytes). The background's cube is a static asset at `0x05C00680`.
- The backend never uploaded `0x9A` textures from memory: only 8-bit and
  DXT formats were uploaded, and other units got a null view, which samples
  0. Now uploaded as `R16G16B16A16_FLOAT` (`RSX_TEX_HALF_UPLOAD=0`: old).
- Both cubes are **border textures** (`SET_TEXTURE_FORMAT` bit 3 clear). Each
  face is a 16x16 swizzled grid holding the 8x8 image centred, with a
  one-texel border (rows and columns 3 and 12). The upload copies the image
  out of each face's grid (`RSX_TEX_BORDER=0`: old reading). Running the job
  body on the interpreter (`SPU_INTERP_OVL=40`, new) gives the same layout,
  so this is the game's format, not a lifting fault.
- The Fiat now draws painted (grey). Its thumbnail is cream, so the tint may
  still be off; unchecked.

**Car-list freezes.** Measured with `$GT5CarListHold` (new in
`milestone.ps1`: Right at +5 s, then Cross at +7, +22, +37, +52 s; the
Arcade screen has a Single Race step before the level picker).

- **FIFO watchdog.** `stuck-get` dropped an SPU list parked at its write
  head after 8 passes. `gcm_io_same_ring` counts every GT5 SPU list as the
  PPU's ring (Phase 12), so the park was never treated as a wait, and the
  lanes then waited for ever on labels in the dropped part. Now it uses the
  park rule's put window (`GCM_STUCK_PUTWIN=0`: old).
- **Stall-and-notify race.** The runtime runs DMA lists inline, so the
  list-stall interrupt can reach the job manager before it has set its load
  state. The notify is then consumed and the job ring idles for good (render
  thread `gFKsE` waits at `0x00D1AFC8` for workload 0's job count, two
  short; the lane spins in the manager's idle loop at `0x2C18`-`0x2CE4`).
  The interrupt is now held off 4 drain ticks for GT5 (`spu_sn_defer` in
  `config/targets.json`; `SPU_SN_DEFER=<n>` overrides; the slot is now per
  host thread). Car list reached: 0 freezes in 4 runs, against 4 in about 13
  before.
- **Still open: picking a car** (Cross on the list) freezes in 3 of 4 runs,
  in two shapes: the idle-loop one above, and workload 6's lanes polling the
  word the FIFO is parked on while one of its lanes is pruned. Lane pruning
  off (`SPURS_LANE_PRUNE=0`) and a longer defer (16) did not help (3 of 4).
- Measuring needs care: a freeze is intermittent, and two runs that never
  started (empty logs) looked like passes.

**Diagnostics added:** `GT5P_STALL_MEMSNAP=1` (a guest memory snapshot with
the stall dump), lane lines in the stall dump show the list-stall mask and
LS `0x12A0`, `RSX_TEX_SIZE_OVR=<hex offset>:<w>x<h>` (bind a texture at
another size), `CUBEDBG=1` prints raw cube formats.

## Phase 18 — Arcade car list: crash fixed, car models load (2026-10-28)

**Status.** Arcade → Single Race → Beginner → High Speed Ring → car list no
longer crashes. The car list draws each car's 3D model and can be browsed
(Copen, then Fiat 500). The cars draw black (open). Picking a car (Cross on
the list) then freezes on the next screen (open; see below).

**The crash.** `0xC0000028` (STATUS_BAD_STACK) on a `spurs-lane` thread, not
an access violation, so the report started at a misleading "fault chain" of
`func_00D803D4` (host addresses of lifted SPU code named as the nearest PPU
function). The host frames (`build/gt5.map`) were the job manager (image 1)
→ `spu_drain_call_impl` → `spu_indirect_branch` →
`spu_irq_regs_maybe_restore` → `longjmp` into an interrupt frame that no
longer existed. Three faults stacked up:

1. **Unlifted job-body entries.** The car-list render body `0x0173BF00`
   (141 KB) is linked at its load address 0x4000: its prologue
   (`ila r2, 0x4068; brsl r126; sf r126, r2, r126`) leaves r126 = 0, and its
   `ila` values are LS addresses. `lift_spu_jobs.py`'s `pic_tables` and
   `pic_continuations` read them as offsets from 0, so the 75-entry jump
   table at LS 0x12D3C was read from the wrong place and 25 of its 44
   handlers were never lifted. Bodies `0x0165A700` and `0x01673D80` are
   linked the same way. New in the script:
   - `link_base()` (`SPU_LINK_BASE=0` at lift time: old reading);
   - `linked_seeds()` for such bodies (`SPU_LINKED_SEEDS=0`): pointer-table
     quadwords with one pointer (LS 0x27040 → 0x7AD0), code after a `bi $r0`
     (0x21C40), and `brsl rX, +4; ai rX, rX, n` targets (0x2369C).
   At run time those handlers fell to the SPU interpreter, which has no
   `mpyui` (LS 0x17D74), and branched to 0.
2. **The drain loop ignored span-resident bodies.** `spu_drain_call_impl`
   looked up only `resident_ovl` and the current image, not the
   `resident_code` spans `spu_indirect_branch` uses. The body's return to
   its lifted entry 0x40DC missed, and `spu_restart_dispatch` unwound every
   host frame, so every return still pending in them became a lookup of a
   mid-function address. It now checks the spans (`SPU_DRAIN_SPANS=0`: old).
3. **The restart left a dangling interrupt frame.** `spu_run_with_halt`'s
   restart (`case 2`) reset `host_depth` but kept `ctx->irq_frame`, a drain
   frame it had just discarded; the next interrupt return `longjmp`'d into
   it. It now clears it (`SPU_RESTART_KEEP_IRQ_FRAME=1`: old).

**Still open: freeze after picking a car.** Render workload 4's lanes spin
at 0x4600 waiting for RSX label `0x030004C0` (ring space) with the FIFO
empty (`get == put`), the shape of Phase 11's render stall. Not
investigated.

**Diagnostics added.**

- The crash report names the exception code and host thread, and prints
  the raw host chain (`host chain (exe+)`), to resolve against
  `build/gt5.map`.
- `SPU_OVL_SPANLOG=<min span, hex>`: transfers that evict a resident body.
- The `BRANCH-TO-0` report lists the resident spans, the last drain pcs and
  the LS words around the pc. The interpreter hand-off log keeps 8 lines for
  job-body code run by image 1 (boot stubs used up the old 8).
- The restart log names its trigger (`dispatch`, `stack-reset`, `task`).

**Test route** (`gt5boot.ps1`, timings from `MusicDecode`): the main menu's
icon bar shows for about 8 s, then hides during the idle camera and only
comes back on a press, so Right goes at +5 s. Then Cross at +7 s (Arcade),
+22 s (Beginner) and +37 s (High Speed Ring). Screen loads vary by up to
8 s, so presses closer together miss screens.

## Phase 17 — Game audio plays: no stand-in job completions (2026-10-28)

**Status.** Menu music and sounds play: port 0 went from 100% to 0% silent
blocks (`AUDIO_RATE=1`, 30 s on the menu with Right/Left presses). Movie
audio is unchanged (port 1, 0% silent).

**Cause.** The runtime's job-chain walker sent a stand-in completion event
(`jc_signal_done`) after every pass of the sound chain `soc-job`
(`0x40040000`), to every queue attached to SPURS:

- queue 4 (dynamic port 16), which the sound engine reads its module replies
  from;
- queue 3 (port 1), the SPU printf service. Its thread (loop at
  `0x009E04D0`: receive, handler `0x00D49DB8`, then
  `sys_spu_thread_write_spu_mb(data1, reply)`) took `data1 = 0x40040000` as
  an SPU thread id. Over 16,000 of those mailbox writes were dropped in 40 s.

With them, the music stream decoded for about one second (175 blocks: the
AC3 job read `0x4FFA8000` only then) and stopped for good. Phase 16's
"mixer outputs zeros" was this: the mixer had nothing new to mix.

**Fix.** `spurs_synth_job_done` is now `false` for `BCUS98114-v104`, as for
GT5P's disc build. Every GT5 sound module job sends its own completion
(Phase 11). `GT5P_SPURS_SYNTH_DONE=1|0` overrides it at run time
(`src/main.cpp`); `SPURS_NO_SYNTH_DONE=1` still forces it off. The v02.00
target (`BCUS98114`) is untested and keeps `true`.

**Also.** The runtime's dropped-mailbox warning now prints the word, the
caller's `lr` and a count (at powers of two after the first 8).

## Phase 16 — Game audio silent: narrowed to the sgx mixer's input (2026-10-28)

**Status.** Movie audio plays. The sound engine (sgx) outputs only zeros:
no menu music, no effects. Not fixed. What is known so far is below.

**Output side, the same as GT5 Prologue.**

- Device-change handling (`AUDIO_HOTPLUG`, WASAPI notifications) is in this
  runtime's `cellAudio.c`, as in GT5P.
- The mixer thread now also registers with MMCSS as "Pro Audio", as GT5P's
  runtime does (`AUDIO_MMCSS=0` off).
- `cellAudioSetPortLevel` (`0x56DFE179`) was unresolved. It now sets the
  port's level, read from f1. The movie sets port 1 to 0.708.
- `PS3_MUTE` in GT5P's runtime is read but never applied, so it was not
  copied.

**Where the zeros come from (`AUDIO_RATE`, `SPU_DMA_RANGE` with `_HIST` and
`SPU_DMA_HIST_LS`, `PPU_WWATCH`, `GT5P_PEEK`).**

- Port 0 (8 channels, 16 blocks) belongs to sgx; it is 100% silent on the
  menu, with or without presses.
- The sound chain `0x40040000` runs three job images:
  - image 13 (`0x017C9800`), an AC3 decoder: its input frames start with
    `0B77`;
  - image 11, the mixer;
  - image 14, the output stage (writes port 0).
- Images 2-10, 12 and 15 run nine times each at boot and never again: those
  are the module queries.
- The menu music stream is fine:
  - the audio thread (tid 18, `func_009D894C`) writes the voice block at
    `0x4FFA8000` every block, and its source steps by 0x280 (one AC3 frame)
    every 6 blocks;
  - the decoder's output is real, quiet audio (about ±1e-3);
  - menu presses do reach the engine (fncount on 0x990000-0x9F0000) and its
    command area `0x40070000`.
- The mixer (image 11) is where the signal stops:
  - it writes the bus `0x4FF9E000`; image 14 reads that and writes port 0;
  - in 1,500 bus writes it read the voice buffers (`0x4003C0D0`,
    `0x4003D0F0`) only 172 times;
  - even then its voice input in LS was non-zero and its bus output zero;
  - its voice list is at `0x4FFA6000` (`0x22` entries for channels 2 and 3)
    and its bus commands at `0x40070010`.
- Not the lift: running image 11 on the SPU interpreter (`SPU_INTERP_IMG=11`,
  new) is just as silent. The mixer runs correctly on state that tells it
  to output nothing.

**Ruled out:**

- the audio-out configuration (6 channels reported);
- the save (a fresh save is just as silent; the original is restored);
- a second walker on the chain (create/run coalesce by address);
- unlifted DSP code (no unlifted-branch reports);
- the conversion helpers (`csflt` and `cflts` scaling are correct).

`SPURS_SYNTH_SKIP_SENT=0` (Phase 11's corruption) does not reach the menu.

**Next.**

- Work out how the mixer reads the bus routing and gains: the `0x40070010`
  command list (`0x20`, argument `0xA2`; then `0x21`, `0x23`, `0x24`, `0x30`,
  `0x40` per channel) and its module state at `0x40046000`.
- Find why the voice list is only present in about 11% of blocks.
- Compare with GT5P, whose sgx engine plays on this runtime. Its bus counts
  come from the job mailbox (commands 0x105/0x106, `cellSpurs.c`); GT5's
  jobs post no mailbox values.

**Also seen.** A run with directional presses on the menu crashed in a
recursive `func_00D803D4` chain (`scratch/pv/aud2.err`); the report was cut
short. Not investigated.

## Phase 15 — Movies play: SPURS Taskset2 and the lifted converter task (2026-10-28)

**Result.** The opening movie plays: the Polyphony Digital logo over the
Earth, then the film (user-confirmed). The menu follows. In a 30 s movie run,
all 1,428 converter tasks ran to completion (`async image=52 RETURNED`).
The frame rate held 60 during loading and 30 on the menu.

**ps3recomp (`cellSpurs.c`).** The Taskset2 API is now implemented on top of
the version-1 task path (the version-2 taskset starts with the version-1
layout):

- `_cellSpursTasksetAttribute2Initialize` and
  `_cellSpursTaskAttribute2Initialize` fill in the SDK defaults.
- `cellSpursCreateTaskset2` and `cellSpursDestroyTaskset2`.
- `cellSpursCreateTask2` takes the context and LS pattern from the version-2
  attribute.
- `cellSpursJoinTask2` waits until the task's enabled bit clears. It logs
  if a task is still running after 5 s.

`gen_hle_nids.py` registered all six NIDs.

**Two fixes in the shared task path, each with a switch.**

- `SPURS_TASK_MISS_EXIT` (on): a task whose image has no lifted code counts
  as exited at once, so a join cannot wait for ever and the task id can be
  reused.
- `SPURS_TASK_MARK_EARLY` (on, `spu_workload.c`): a task counts as running
  from dispatch. Before this, another task's exit could start it a second
  time before its own thread began.

**The converter task.**

- `SPU_DUMP_MISS=analysis/spu/taskdump` captured it:
  `spujob_CDCD962FAC770DB9_17400.bin`, an ELF linked at LS `0x3000`, entry
  `0x3050`.
- `scripts/lift_spu_jobs.py` now lifts task ELFs from `analysis/spu/taskdump`
  (`task_elf_flat`): their segments are laid out flat at their addresses,
  lifted at that base, and registered at `e_entry`. The converter is 109
  functions with no TODO lines.
- The re-lift reproduced the other 50 images and the registry unchanged.

To capture another task ELF, run with `SPU_DUMP_MISS=analysis/spu/taskdump`
and re-run the lift.

## Phase 14 — FFmpeg added; movies still black (missing SPURS Taskset2) (2026-10-28)

**Result.** The build decodes GT5's movies with FFmpeg: the H.264 video
(1920x1080, 29.97 fps) and both audio streams. The picture stays black,
because GT5 converts each decoded picture to ARGB on SPURS tasks that
ps3recomp does not implement.

**FFmpeg.** CMake and `scripts/get_ffmpeg.ps1` were already in place; only
`third_party/ffmpeg` (gitignored) was missing. GT5P's copy is the same pinned
LGPL build (avcodec 61, avutil 59) and was copied across. Rebuilding copies
the DLLs beside `build/gt5.exe`. The log shows `[cellVdec] Open(codec 1) ...
decoding with FFmpeg`. Over 25 s, `VDEC_TRACE`/`DMUX_TRACE`/`ADEC_TRACE`
showed about 900 video access units decoded into about 670 pictures, and
PCM from the audio decoder.

**Why the picture is black.**

- Each movie frame is one quad sampling a 1920x1080 ARGB texture in main
  memory (`RSX_CAP`). The texture is one slot of a ring 0x870000 apart
  (`0x42E1E280`, `0x4368E280`, `0x43EFE280`, ...). It changes every second
  flip, matching the video rate (`GCM_FTRACE`).
- That texture is all zeros (`RSX_TEXDUMP`). The pictures themselves arrive:
  the movie thread "PDI" (`func_009B61F8`) calls `cellVdecGetPicture` with
  format 3 (YUV420 planar) into staging slots (`0x4476E280`, `0x44A98280`).
- `func_009B24EC` then writes four 0x80-byte commands to the array named by
  TOC slot `0x01913410`. Seen live: command 8, slice, source = the YUV
  staging slot, destination = a ring slot, 1920x1080 in and out. It then
  calls `cellSpursCreateTask2` with the task ELF at `0x01704280` (a word at
  +4 of each worker object; TOC slot `0x01913414`, stride 0x140), and
  `cellSpursJoinTask2` on each.
- The log has `[hle] unresolved NID` for `0xE14CA62D` (`cellSpursCreateTask2`)
  and `0xA7A94892` (`cellSpursJoinTask2`), and also for `0x4A6465E3`
  (`cellSpursCreateTaskset2`), `0xC2ACDF43`
  (`_cellSpursTasksetAttribute2Initialize`) and `0x8ADADF65`
  (`_cellSpursTaskAttribute2Initialize`). No task runs, and GT5 draws the
  empty ring slot.
- Ruled out by measurement: `cellVpost` is never called (`HLE_BT_NID`); no
  SPU DMA touches 0x42000000-0x45400000 (`SPU_DMA_RANGE`, which does catch
  the audio mixer's writes); the frame's FIFO has no blit or copy methods;
  the PPU runs no conversion (`GT5P_SAMPLE`).

**To make movies play.** Implement the Taskset2 API in ps3recomp: create and
join, with the join waiting for the task to exit. Then capture the task ELF
with `SPU_DUMP_MISS` and lift it into `spu_registry`. The version-1 task path
(`cellSpursCreateTask`) carries assumptions from YDKJ and LBP: an r3 marker
read from the context, and a single global "current" taskset. Its
`cellSpursJoinTask` does not wait.

**Tools added.**

- `scripts/test/gt5boot.ps1 -Movie`: no presses; shots from
  `installed00.dat`, covering the opening movie of an installed boot.
- `RSX_TEXDUMP_SKIP=<n>`: skip the first n matching draws.
- `RSX_TEXDUMP_SIZE=<w>x<h>:<fmt hex>`: also match the format byte.

## Phase 13 — Menu buttons and badge fixed (2026-10-28)

**Result.** The main menu draws its UI correctly: the four mode icons, the
help, settings and record buttons, and the top-right badge ("12:00", level
18). Still a steady 30 fps (151 frames per 5 s idle).

**Cause.** The UI art sat inside a render target's address range, so the
backend sampled the target instead of the texture.

- `RT_TEXDBG=100` showed every UI texture in the pool at `0x0590xxxx`-
  `0x0597xxxx` (DXT5 and ARGB, 12x68 to 192x120) resolving as
  `-> target`, at a scale and origin inside the target at `0x058F1680`.
- The menu draws a 256x1 colour ramp into `0x058F1680` (surface clip 256x1,
  viewport 256x1, pitch 1024; it feeds the badge's gradient). The backend
  treated clips under 16 on a side as unset (`current_rt_off`), so the
  record carried size 0x0. `off_rt_get` then made a window-sized (1280x720)
  target, which the viewport cap could not shrink: that cap only applies to
  a known size.
- 720 rows at pitch 1024 run to `0x059A5680`, past the whole texture pool.
  `off_rt_find_in` matched each texture as a corner of that target. The
  target held one drawn row, so the stretched labels and 9-slice frames
  came out as horizontal stripes.

**Fix (ps3recomp `rsx_d3d12_backend.c`).** Clips of 1 to 15 on a side are
real sizes (`RSX_RT_SMALL_CLIP`, default on; `=0` restores the old rule).

**Ruled out first, by measurement:**

- Unsupported formats: `RSX_TEXREJ=1` rejected only a 1024x2048 depth
  texture on unit 13.
- Linear-texture pitch: `TEXFMTDBG` (now prints CONTROL3's pitch) showed the
  UI textures tightly packed (156x76 DXT5, pitch 624).
- A stale texture cache: `TEX_NOCACHE=1` was still garbled.
- Bad texture data: `RSX_TEXDUMP=05928380` decoded offline to a clean
  button shadow.

`RSX_CAP` with `RSX_CAP_AFTER` works for GT5 (milestone `MusicDecode`).
Quote the value: unquoted, PowerShell splits it at the comma and the
capture never arms.

## Phase 12 — The menu at full speed; milestone-driven GT5 tests (2026-10-28)

**Result.** The main menu holds a steady 30 fps (151 frames per 5 s over 90 s
idle; the preceding loading runs at 60) and draws its 3D background: a pit
crew in front of the Indianapolis grandstand. The menu buttons and the
top-right badge are still striped and garbled. Before this phase the menu
slid from 60 fps to about 0.4 within 15 s of loading and drew no background.

**Fixed: SPU display lists dropped by the FIFO walker.**

- The render thread (`gFKsE`, guest tid 27; it issues the flips) waits each
  frame (`func_00D30DA8` → `func_00D320A8`, timeout `0x4C4B40` = 5 s) on the
  object at `0x01AE7E80`. The user handler (`0x00D33E8C`) signals that object
  for user command 0. User commands come from the command stream
  (`GCM_SET_USER_COMMAND`, method `0xEB00`; one per frame, near the start of
  each 4 KB PPU segment at io `0x10020`/`0x11020`/...).
- `GCM_FLIPSUM=1` showed the slow frames with about 6,100-6,600 words and no
  user command. Normal menu frames have about 17,600 words and one.
- Each slow frame followed `FIFO resync (jump-park)`. The walker had found
  an SPU display list parked at its write head (io `0x00A5xxxx` or
  `0x0133xxxx`), judged it to be in the same ring as `put` (io `0x10080`),
  and jumped to `put`, dropping the rest of the frame.
- `gcm_io_same_ring` treats one contiguous run of mapped IO pages as one
  ring. GT5 maps its main memory to IO in one contiguous run, so every SPU
  list counted as the PPU's ring (Prologue's lists are at `0x095xxxxx`).
- Fix (ps3recomp `cellGcmSys.c`): `GCM_PARK_RESYNC` mode 2 also requires the
  park to lie within 64 KB of the range `put` has occupied
  (`GCM_PARK_PUTWIN`, default on; `=0` restores the old test). Resyncs fell
  from one per frame to 2-3 per run, and those are the `stuck-get` watchdog,
  which is still open.

**Also changed in ps3recomp:**

- **User commands are queued** (`GCM_USER_QUEUE`, default on; `=0` keeps
  the single slot, which let a later command overwrite an undelivered one).
  It did not change GT5's frame rate, but the overwrite was real.
- **Diagnostics:**
  - `GCM_FLIPSUM=1`: command words and user commands per flip.
  - `GCM_FTRACE_SLOW=<n>`: start `GCM_FTRACE` at the first flip of 1,000+
    words with no user command.
  - `GCM_PUMP_DBG=1`: now also counts user commands by value.
  - Timeline events: `U` for user commands raised and delivered.

**Corrections to the investigation:**

- `GCM_FLIPCB_ONTICK=1` (flip handler only at the tick) made no difference:
  the render thread waits for the user handler, not the flip handler.
- Lane re-entry (`SPURS_LANE_STAY=1`) made no difference.
- Not PSN: GT5 is told it is offline (`sceNpManagerGetStatus`), as under
  RPCS3.
- The broken movie link (below) did not cause the slowdown either: the
  opening movie plays while the game is still at 60 fps.

**Local setup: the GT5 dump moved** to `D:\Games\ROMS\PS3\...`
(`AGENTS.local.md` updated). `input/pkg/USRDIR/MOVIE` was a link into the old
location; it is now a junction to the new one. `GT.VOL` is a hard link and
was unaffected. Without the link GT5 found none of its 16 `MOVIE/*.pam`
files. The movies now open, but this build has no FFmpeg
(`third_party/ffmpeg` is missing from this tree), so `cellVdec` returns black
pictures.

**Milestone-driven GT5 tests:**

- GT5 reads hashed `PDIPFS` paths, so it had no `.gpb` milestones and the
  timed Cross presses also landed on the menu.
- ps3recomp cellPad now accepts named milestones from other libraries
  (`pad_milestone_mark`) and file milestones from
  `PAD_MILESTONE_FILES=<name>,...`. Milestones added:
  - `SaveData` / `LoadData` (cellSaveData);
  - `MusicDecode` (`cellMusicDecodeInitialize2`; GT5 calls it as the menu
    loads, on every boot).
- `scripts/test/milestone.ps1`: `$GT5BootHold` presses Cross from 8 s after
  `installed00.dat` (the first named file of every boot), every 5 s up to
  300 s. Each press is skipped once `MusicDecode` has been seen, so nothing
  is pressed on the menu.
- `scripts/test/gt5boot.ps1 -Tag t [-Settle 60] [-Gap 10] [-Fresh]
  [-FreshSave]`: boots to the menu, idles with window shots, and prints
  frames per 5 s.
- `-Fresh` runs `scripts/test/gt5_reset.py` first. It restores the
  first-boot install state; `--save` also deletes the save.

**Open, next:**

1. The garbled menu buttons and badge (texture decode or layout).
2. The `stuck-get` resyncs (2-3 per run, each a frame dip).
3. FFmpeg for this tree (movies decode to black).
4. The intermittent early stall during loading (about half of
   installed-state boots).

## Phase 11 — The heap corruption: doubled job completions (2026-10-28)

**Fixed: sound DSP state written over the menu's heap objects.** Main's
recurring `bctr to NULL` (`func_00524768`) and thread 29's null calls are
gone, and the level-meter job no longer reads pointers as sample counts.
The menu still runs at about 0.4 fps with garbled buttons and no background;
that is a separate render stall (below).

Chain of cause:

- A `PPU_WWATCH` from boot on `0x4FFF27C0` and `SPU_DMA_RANGE` showed two
  sound SPU jobs:
  - image 14 (`jFDFFAAC1`) GETs and PUTs `0x8A10` bytes at `0x4FFF2790`
    (copy loop at `0x3918`/`0x3964`, size fixed in code);
  - image 11 (`jD58063CD`) does the same with 16 KB at `0x4FFF2780`.
- These jobs ran from early boot. Main later built menu objects at
  `0x4FFF27C0`+ (`0x00544F54`).
- The sound init (`func_009EA9F0` → `009D7A6C`/`9D7CA4`/`9D7DE0`) sizes each
  module's buffers as `align16(query) + 0x10`, with
  `query = func_009D61AC(module, table, 0, 0x102 or 0x104)`. A probe showed
  the 0x102 query returning 0, so the buffers were 16 bytes apart.
- The query (`func_009D60B8` → `func_009DE758`) runs a one-job SPURS job chain
  (`soc-job`, `0x40040000`). It reads the reply from the completion event's
  `data3` (`lwz r31, 0xbc(r1)` after syscall 130); `data2` is the job index.
- Each module job answers with its own `throw_event` on port 16 (code 80, to
  queue 4; `SPURS_PORT_DBG=1` shows images 11-14 doing so). ps3recomp's
  job-chain walker also sends a stand-in completion (`jc_signal_done`, on for
  GT5 by `spurs_synth_job_done`), with `data3 = 0` for every command except
  `0x105`/`0x106`. It sends one per job, one at the chain's END, and one when
  the walker thread exits.
- So every query produced its real answer plus up to two zero answers. The
  zeros were consumed by the *next* waits: modules got zero-sized state
  buffers, and their jobs wrote 16-35 KB of state over whatever the heap
  placed there.
- `SPURS_NO_SYNTH_DONE=1` (no stand-ins at all) also cleared the null calls.
- Not the cause: the AC3 module (image 13, `jF523F26F`) really answers 0 to
  `0x102`. Its dispatch handles `0x100`, `0x104` (`0x83C0`), `0x3100`,
  `0x3101` and `0x3300` and returns 0 for anything else.

Fix (ps3recomp `cellSpurs.c`, `spu_channels.c`): `SPURS_SYNTH_SKIP_SENT`,
default on (`=0` restores the old behaviour). The walker counts user events
delivered on its thread (`g_spu_user_events_sent`, incremented when
`g_spu_user_event_hook` takes an interrupt-mailbox write). It sends no
stand-in for a job, a pass's END, or the chain's exit when the job, or that
pass's jobs, signalled for themselves. Jobs that never signal still get
stand-ins.

**Open: the menu's render stall (0.4 fps).**

- The sound thread `gFKsE` waits in `func_00D1B930` for SPU progress counters
  at `0x01AC0CC0` (`0x24 0x24 0x04`, target `0x24`: the third lags).
- The stall dump shows render workload `wid=4`, lane `spu=0`, inside job
  image `b0196FF40` at `pc 0x4600` (`int=1 evmask=2`), the `spu_rdch`
  busy-wait the sampler showed. Its last MFC transfer read 4 bytes from the
  RSX label at `0x03000480`, while the FIFO is empty (`get == put`).
- Likely the SPU render job waits for an RSX label or ring position that our
  RSX never advances. Next: find what `0x4600` waits for and who should write
  `0x03000480`.

The garbled menu buttons and missing background did not change with this fix.

**Also this phase:**

- The intermittent early stall (about half of the installed-state boots)
  remains.
- Thread 32's poll for the music-decode result (Phase 10) and the null calls
  are not seen again.

## Phase 10 — Past the install to the main menu (2026-10-28)

**Result.** From a fresh install, with Cross pressed at each prompt, GT5 shows
its install screen ("Installing data...", progress bar, time left), then
"Installation complete", Adjust Display Area, creates its save
(`BCUS98114-GAME`) and reaches the **main menu**. The menu shows the copyright
text, the "5" logo, the cursor and four buttons. Booting again from the
installed state goes straight to the menu. All 16,446 installed `PDIPFS`
files are byte-identical to RPCS3's install.

**Correction to Phase 9's "Open, next" item 1.** The "stall" after
`installed00.dat` was the confirmation prompt (its text drew once it had faded
in), waiting for Cross. Main and the workers were idle because the title was
waiting for input. Unattended runs press Cross on a timer:
`PAD_HOLD` = `20000-20300:CROSS,30000-30300:CROSS,...` (GT5 prints no
`[milestone]` lines).

**Fixed: the black screen after the save.** `n3FKY` loads module 0x53, creates
a memory container and calls `cellMusicDecodeInitialize2` (from
`func_00A5AA60`, a script native at `0x00822078`). It then polls a result slot
every 2 ms (`func_00A59EBC`/`0x00A59F98`, no timeout) until the callback posts
the initialise result. ps3recomp's music-decode stubs used names no title
imports (`cellMusicDecode2Init` and so on), so the import was unresolved, the
call returned 0, and the callback never came. GT5 imports seven:
`Initialize2, Finalize2, SelectContents2, SetDecodeCommand2,
Get/SetSelectionContext2, Read2`. They now model a console with no custom
soundtrack. `Initialize2` and `Finalize2` succeed and post their result
through `cellSysutilQueueGuestCallbackArgs` (delivered at the title's
`cellSysutilCheckCallback`). Select, decode command and selection context
post `0x8002C103` (no active content), and `Read2` returns it.
`CELL_MUSIC_DECODE2_CB=0` withholds the callbacks. `src/gen/ppu_hle_nids.cpp`
is regenerated (`gen_hle_nids.py --all`; the only change is these seven).
RPCS3 shows the same call (`LR 0x00A5AC20`), after which GT5 starts a thread
and continues.

Also resolved (offline network model, `ppu_sysprx.cpp`): `getsockname`
(AF_INET 0.0.0.0:0), `inet_pton` (dotted quads) and
`sceNpTrophySetSoundLevel` (0). Unresolved, each returned its first argument.
They did not change the menu. Still unresolved: three `cellUsbd` functions
and `sys_prx_get_module_list`.

**Open: the menu runs at 0.1-0.4 fps, its buttons are garbled and the
background scene is missing.** The cause found so far is memory corruption,
not rendering:

- The sampler (`GT5P_SAMPLE=6`) shows three threads at about 100%:
  - sound thread `gFKsE` (guest tid 27), spinning in `func_00D1B930`. That is
    a wait for SPU job progress: the minimum of eight u16 counters at
    `+0x42..+0x4E` must reach a target;
  - the job-chain thread, entirely in SPU image `jFDFFAAC1` `0x7318`;
  - an SPU lane busy-waiting in `spu_rdch`.
- `jFDFFAAC1` `0x7318` is a level meter: it sums samples `r21` times, then
  takes a square root. A probe at `0x72E4` showed `r21 = 0x4FFF0084` and
  `r23 = 0x42088000`. Both are guest addresses where a count belongs, so each
  job loops about 1.3 billion times. The struct is in local store at
  `0x90B0`.
- `SPU_DMA_RANGE=4FFF2700-4FFF2900`: a sound SPU job (image 14) GETs and PUTs
  16 KB at EA `0x4FFF2780` (local store `0x8800`, which contains `0x90B0`).
  The same span holds `0x4FFF27D4` (= `0x4FFF0084`, the only copy in memory,
  `GT5P_FIND`) and `0x4FFF27E0`.
- Main's recurring `bctr to NULL` (`func_00524768`, a recursive list walk:
  `node->next` at +4, then vtable +0xC) reaches node `0x4FFF27E0`.
  `PPU_NULL_BT=1` gives the chain `0x001748A0` → `0x005218B8` → `0x0052AB94` →
  `0x0052625C` (object `0x42088000`) → `0x005464F8` → `0x00545DB0`.

So a sound DSP context and main's menu objects share the same memory in
GT5's heap at the top of its `0x40000000` area (1 MB block `0x4FF00000`).
Either the heap hands the memory out twice or one side holds a stale pointer.
The cause is not found.

Ruled out:
- Mmapper blocks mapped over one another (new `[mmapper] OVERLAP` check; none
  seen).
- Stale data in newly mapped blocks: zeroing each block's first mapping (all
  blocks, or 1 MB blocks only) left the same values and null calls. The code
  was removed.
- Bad installed data: every file read matches RPCS3.

**Intermittent early stall.** About half the boots from the installed state
stop during loading. Each stops at a different file in `PDIPFS/K/`, before
the music-decode call, with the screen black or on the GT logo. This happened
with and without every change in this phase; the cause is not investigated.
The thread-29 null calls (`func_00985D7C`, `func_0098C458`) are still seen.

**New diagnostics:**
- `PPU_NULL_BT=1`: guest stack with the first 8 `bctr to NULL` reports.
- `[mmapper] OVERLAP`: logged for legacy blocks mapped over a mapped block.
- `GT5P_FIND`: now scans 0x10000000-0x70000000 and prints the word at −0x20.

**Next:**

1. Find who allocates the 16 KB DSP context at `0x4FFF2780` and who allocates
   the list node at `0x4FFF27E0`. Use `PPU_WWATCH` on `0x4FFF27E0` from boot
   (first writer), and trace allocations on GT5's heap object.
2. The intermittent early stall.
3. The menu's garbled textures and missing background, once the corruption
   is fixed.

## Phase 9 — Memory accounting and pager faults: the install runs to its end (2026-10-28)

**Result.** With the new defaults the first-boot install matches RPCS3 for
746 of 747 file steps (`scratch fsdiff`; the one gap is a `mkdir` of a folder
the reset tree already has). It creates `/dev_hdd1/grim2` (cache, file,
`grim007.db`) and reaches `stat installed00.dat`, where RPCS3 goes on to scan
`PDIPFS_bdmark`. From about 10 s in, GT5 draws its own panel (a dark box with
a title bar) in place of the logo; the panel has no text or contents yet.
Two of two runs behaved identically. Every run before this stopped somewhere
between `9/6L/LZ` and `car/S/1`, at a different file each time.

**Stop 1: the install spun in GT5's page compaction.** The install driver
`n3FKY` asked for 16 KB (`func_00C011B4` → `func_00C277B0`, aligned 0x80).
`func_00C276CC` retries a failed allocation for ever, running the compaction
tick (`func_00C485EC` → `func_00C4B22C`) between tries. That routine
reallocates every in-use 64 KB page of the heap into a fresh block: unmap,
map at a scratch slot, copy, free, allocate, copy back, map. Thread dumps
showed the same caller chain minutes apart with the loop index changing.
`cdis.py`'s TOC annotation is wrong for this code: the live `r2` is
`0x01919684`, and with it the allocator is `func_00C4B0D8` on the pager
object `0x01AB9ED8`.

- The allocation failed because of GT5's physical page budget, which it
  takes from `sys_memory_get_user_memory_size` (polled from `0x00C4C3DC`;
  `func_00C49988` reserves free − 1 MB). Ours answered a constant 192 MB
  free. RPCS3 answers total 0xD500000 and a free figure that moves between
  0xB860000 and about 7 MB as blocks come and go.
- Our legacy `sys_mmapper_unmap_memory` never wrote the block id back. GT5
  pre-stores −1, so the compaction then mapped and freed id −1. No block was
  ever freed either: one run made 1,075,580 `allocate_memory` calls.

Fix, `PS3_USER_MEM_ACCOUNT=1` (ps3recomp `sys_memory.c`, `ppu_sysprx.cpp`,
`ppu_loader.cpp`), default for GT5 (`=0` restores the old behaviour):

- Syscall 352 answers total (213 MB, `PS3_USER_MEM_TOTAL`) − base
  (0x1AF0000, `PS3_USER_MEM_BASE`) − everything allocated. Allocated means
  `sys_memory` blocks, memory containers and mmapper blocks; a block from a
  container is not charged twice. The base is RPCS3's first answer for GT5
  (0xB860000 free) less the 0x1B0000 GT5 had allocated by then. Our first
  answer is 0xB910000.
- With accounting on, legacy blocks record where they are mapped, unmap
  writes the real id, and free drops the block and refunds it.
- `PS3_MEMTRACE=1` also logs each free-memory answer (`[mem]`) and each
  `free_memory`.

**Stop 2: a leaked C library lock.** With accounting alone, the install got
as far as `car/S/1` in two of four runs and then deadlocked: `n3FKY` waited
for lwmutex `0x01AE8260`, owned by main, while main waited for `n3FKY`.

- `0x01AE8250` is lock 1 of the C library's lock table: count at +0, owner
  at +8, lwmutex at +0x10. It guards the `atexit` table at `0x01AED410`.
- A write watch (`PPU_WWATCH=01AE8250 PPU_WWATCH_FRAMES`) showed main taking
  it 28 times in a row through `func_00D41260`. The callers were static
  initialisers registering destructors.
- `func_00D41260`'s error path (`0x00D4137C`, taken when `func_00D411D0`
  cannot grow the table) returns without unlocking. Growth failed because
  the pager heap's `realloc` (`func_00C4BE44`) returned null once free memory
  reached 0.

Free memory reached 0 because GT5's pager never saw a page fault:

- In RPCS3, main reserves 1 MB blocks, the pager thread `MpAnk` answers
  faults in its 0x60000000 area with 64 KB pages, and the reservations are
  freed: 156 by main and 300 by `n3FKY`. All 605 of RPCS3's faults are in
  that area.
- Ours committed every fault silently, so GT5 kept all its reservations and
  free memory sat at 0 for thousands of polls.

Fix, `PS3_PAGE_FAULT=2` plus `PS3_MMAPPER_LV2_AREA=1`, both default for GT5
(`=0` for either restores the old behaviour):

- Faults on the title's notified areas reach its pager with legacy blocks
  too. A fault on an address a block is mapped over is just that block's
  first touch (legacy blocks commit lazily) and is not reported
  (`ps3_mmapper_is_mapped`). Without that check the pager got faults for its
  own heap and 14 of them timed out.
- The lv2 layout is needed as well: with the old layout the pager answered
  its faults but freed no reservations, and the run ended in the same
  deadlock at `car/S/1`.
- With both, 157 of the 1 MB reservations are freed, free memory holds near
  0x8720000, and 98 of 99 faults are answered. The exception is
  `0x3BE50004`, read by thread 29 (`9qstY`) after its null calls (below).

**Full pager mode (`PS3_MMAPPER_SHM=1 PS3_PAGE_FAULT=1`) still fails.** It
reached the same 1 MB conversion, but 2 of 3 runs crashed in the pager
object's lock (`LR 0x00C44F70`, `r3 0x01AB9ED8`) after null virtual calls on
zeroed objects at `0x3000CC68` and `0x300C8D24`. Those pages were mapped once
and never unmapped, so the mmapper did not wipe them; the cause is open.

**Other findings.**
- The request handshake between install worker `ksF3` and I/O helper `kFeqP`
  (`func_00C07AE4`: signal the event at `+0x1AA8`, wait on `+0x1B98`; event
  = lwmutex, lwcond at `+0x18`, waiting `+0x28`, signalled `+0x29`) stalled
  in 2 of the 14 runs before the fix. An `lwcond` trace of a completed
  exchange showed every signal reaching its waiter. The cause is not found.
- `GT5P_PEEK` in `main.cpp` parses with base 0: give it a `0x` prefix.
- New runtime switches: `PS3_PAGE_FAULT_LOG=<n>` (faults logged, default
  16; lines now carry the guest `lr`).

**Open, next:**

1. After `installed00.dat` main waits on an event of the object at
   `0x4FE72018` (`func_005DE308`, from `0x00773310`), and `n3FKY` threads
   32-34 wait idle for work on the same object (`0x006386A8` ← `0x0065B944`).
   RPCS3's next step is scanning `PDIPFS_bdmark`.
2. Thread 29 (`9qstY`) calls through null descriptors in `func_00985D7C+0x470`
   and `func_0098C458+0x840` (`r3=0xFFFF`), then reads unmapped
   `0x3BE50004`.
3. Main's `bctr to NULL` in `func_00524768+0x1F1` (Phase 8) still happens
   in every run.
4. The panel draws without text.
5. Seeding RPCS3's finished install (Phase 8) is still a separate option.

## Phase 8 — SQLite fixed (file open modes); the pager implemented (2026-10-27)

**Fixed: the install stopping after `PDIPFS/9/DC/DS`.** It was not memory.
Right after that file GT5 commits its first SQLite transaction on
`/dev_hdd1/game249.db`, which failed, and the title then showed (auto-dismissed
by our dialog stub, so the run looked stuck):
"Insufficient free space on Hard Disk Drive (HDD). At least 32MB required.
0x00000001 [115]".

- Cause: `cellFsOpen` mapped `RDWR|CREAT` without `TRUNC` (0x42, the db;
  0xC2, the journal) to `fopen("a+b")`. That is append mode, so every write
  went to the end of the file whatever the seek. `WRONLY|CREAT` mapped to
  `"wb"`, which truncates.
- Fix (ps3recomp `cellFs.c`): create without truncate or append opens in
  place (`"r+b"`, creating with `"w+b"` if missing). `O_CREAT|O_EXCL` fails on
  an existing file. `FS_OPEN_LEGACY_MODES=1` restores the old table.
- Found with the new `HLE_BT_NID=<hex>` switch (guest stack at each call to
  one import): the dialog is opened by a short-lived thread "PDI", and the
  message was built on `n3FKY`, the script VM thread.
- Result: SQLite transactions now succeed back to back, as in RPCS3 (68 in
  two minutes, database at 100 KB). File accesses match RPCS3 for 708-715
  operations and go on past `9/DC/DS` to `9/6L/LZ`. RPCS3 goes on to
  `9/PO/MB` and `car/*`; ours stops. The screen stays on the GRAN TURISMO 5
  logo. The main thread's `bctr to NULL` in `func_00524768` is still there.
  That function walks a linked list (recursing into `next` at +4, then
  calling virtual slot 0xC) and reaches a garbage node (`this=0x7E00165F`,
  "vtable" word `0x24004024`, which looks like a saved CR value).

**Also fixed in `cellFs`:**

- `cellFsWrite` touches each source page from user mode before `fwrite`, as
  `cellFsRead` already did. `WriteFile` from an uncommitted guest page fails
  instead of faulting (`FS_WRITE_PRETOUCH=0` off; short writes are logged).
- `cellFsFsync` and `cellFsAllocateFileAreaWithoutZeroFill` (NIDs `0x967A162B`
  and `0x7A0329A1`) were unregistered and faked CELL_OK. GT5 sizes each
  `PDIPFS/*.psctmp99999` copy with the second one. Both are implemented now:
  a real flush, and setting the file size (`FS_ALLOCATE_AREA=0` off).
  `src/gen/ppu_hle_nids.cpp` was regenerated (only these two lines change).
  The helper `cellfs_syscache_prepare` was renamed `ps3_fs_syscache_prepare`,
  because the generator registers every exported `cell*` name.

**The pager, built and working, opt-in:** `PS3_PAGE_FAULT=1` (needs
`PS3_MMAPPER_SHM=1`).

- lv2 327 records each notified 256 MB area and its queue. GT5 asks twice,
  for `0x60000000` and `0x30000000`, as in RPCS3.
- A guest PPU thread faulting inside such an area queues
  `(0xFFFE000000000000, address, thread id, 2)` and waits (10 s,
  `PS3_PAGE_FAULT_MS`) for lv2 57. Then the access is retried.
- GT5's `MpAnk` serves the faults in RPCS3's order (`0x60000000`,
  `0x60110004`, `0x60010000`, ...) and writes its page files under
  `/dev_hdd1/mem/page`.
- Why it matters: without it our fault handler commits zero pages behind the
  pager. With real blocks (`PS3_MMAPPER_SHM=1`) the pager's later map of such
  a page wiped what the game had written there.
- `search_and_map` (lv2 337) under block semantics is now a first fit inside
  the area that holds `start_addr`, reusing unmapped room. The bump counter
  never reused and rounded every block to 1 MB. GT5 never calls 337 in our
  runs, though; it maps through `sys_mmapper_map_memory` at its own
  addresses. No overlapping or double maps were found in a trace
  (`PS3_MEMTRACE=1` now logs map and unmap).
- With all three switches (`SHM`, `LV2_AREA`, `PAGE_FAULT`) runs still
  corrupt: wild reads from `0x81560000` upwards and the same NULL-list call.
  Not the default.

**Runs vary a lot.** The same build and clean data give different outcomes:

- About 1 boot in 3 dies in the first seconds in an endless recursion
  between `0x00BE20D4` and `0x00BC1870` (`func_00BC183C` ->
  `func_00BE1F2C`). It is not caused by this phase's changes: it happens with
  `FS_WRITE_PRETOUCH=0` too.
- One non-verbose 5-minute run created `USRDIR/grim2/grim007.db` (RPCS3 does
  that about 3 s after `game249.db`) but no `game249.db`, went black from
  10 s, and its policy module looped on one DMA until halted.
- A verbose run once stopped silently after `PDIPFS/K/LG` (423 operations).

**New diagnostics:**

- `GT5P_FAULT_LOG=<n>`: log the first n committed faults (24 before), now
  with the host thread and `rip exe+offset` (resolve with `build/gt5.map`).
- `HLE_BT_NID=<hex>`.
- `PS3_MEMTRACE=1`: also logs map, unmap and search_and_map.

**For later (the user asked to note it): skip the install.** GT5's
first-boot install is the game's own logic (it copies files from `GT.VOL` into
`PDIPFS` and builds `game249.db`). It can't be removed, but it can be skipped
by giving the port a finished install, as the Prologue port runs from
`gamedata`. RPCS3 has one:

- `dev_hdd0/game/BCUS98114`: 6.5 GB, 31,581 files, with `PDIPFS`,
  `PDIPFS_bdmark`, `db`, `grim2`, `installed00.dat` and `pace`;
- `dev_hdd1/caches/BCUS98114_BCUS98114`: `game249.db`, `grim2`, `mem`,
  `tmp_save_work.dat`.

To use it, copy the first to `gamedata/dev_hdd0/game/BCUS98114` and the
second's contents to `gamedata/dev_hdd1`, with `gamedata/dev_hdd1.id`
containing `BCUS98114` so the cache mount relays instead of clearing.

- Test the installed path that way first, since it is what players will run.
- Keep the from-scratch install (`reset_gd.py`) as a separate test.
- Unverified: whether GT5 accepts RPCS3's cache as relayed.

**Next:**

1. Seed the install from RPCS3 and see how far the installed boot gets.
2. The list corruption behind `func_00524768` (who links the garbage node).
3. The early recursion at `0x00BC1870`.

## Phase 7 — Computed-goto labels: past the warning to the GT5 logo (2026-10-27)

**Fixed: the black screen after the warning.**

- The script VM's state machine `func_00B52140` uses GCC computed goto. Its
  label addresses (`0x00B5248C`, `0x00B52524`, `0x00B526D8`, `0x00B521AC`)
  exist only as raw words in the TOC.
- The `bctr` through them was lifted as `ps3_indirect_tail`. The runtime
  found no lifted entry ("[ppu] indirect tail to 0x00B521AC: no lifted
  entry") and returned without the epilogue, so the caller `func_00B52768`
  got `r26 = 0` back. That `r26` is its `this`, and the NULL-object loop of
  Phases 5-6 followed.
- Found with per-call `r26` checks in the lifted caller.
- New required pre-lift step: `scripts/code_labels.py --write`. It finds the
  TOC bases from the `.opd` descriptors and seeds every word within ±32 KB of
  a TOC that points into code and is not a descriptor entry. That is 359
  labels for 01.04, merged into `config/extra_seeds_bcus98114_v104.json`;
  the lift now has 84,813 functions.
- Ruled out first: guest C++ exceptions. A log at the four libgcc
  `__builtin_eh_return` exits never fired. Note for later: those exits are
  lifted as a plain `return`, so a real guest throw would not reach its
  landing pad.

**Result:** from a clean first boot, our file accesses match RPCS3's for 699
operations. That covers the `PDIPFS` cache rebuild and the SQLite system
database `/dev_hdd1/game249.db`. The screens go warning, black, then the
**GRAN TURISMO 5 logo** (fades in about 30 s after launch), which then stays.

It stops after `PDIPFS/9/DC/DS`; RPCS3 goes on to `9/KW/PC`. The main thread
makes three `bctr to NULL` calls from `func_0052xxxx`: methods on objects in
the game's 512 MB area whose first word is garbage (`0x5A4E01C1`, not a
vtable). The failing function varies from run to run.

**Leading hypothesis: memory blocks.** liblv2's `sys_mmapper_map_memory`,
`_unmap_memory` and `_free_memory` are no-ops in the runtime
(`ppu_sysprx.cpp`):

- a block remapped elsewhere arrives empty;
- a new block mapped where an old one was shows stale data;
- RPCS3's first boot cycles about 1,950 blocks (64 KB and 1 MB).

The game imports exactly these four functions.

**Built, opt-in, not working yet:**

- `PS3_MMAPPER_SHM=1`: real block semantics. A block's contents follow it,
  unmap saves and decommits, free releases, and `search_and_map` takes part.
  With the old layout the run crashed in endless recursion on a garbage
  vcall, `this=0x2000C790`. GT5 carves liblv2 blocks with
  `search_and_map(0x20000000)`, and our first game area is also at
  `0x20000000`, so mapping zeroes live game data.
- `PS3_MMAPPER_LV2_AREA=1`: RPCS3's layout. liblv2's area is reserved at
  `0x20000000` and the `sys_memory_allocate` window moves to `0x10000000`,
  so GT5's areas land at `0x30000000`, `0x40000000` and `0x60000000`, as in
  RPCS3 (verified). With both switches the game exited about 16 s in:
  thread 32 read guest `0x1_00000000` (computed from -1 + 1) in
  `func_00CCF5E8`, called from `func_00CF2F6C`/`func_00B08F18`.
- With the layout switch alone and the old allocator rules (sys_vm window
  held back, 512 MB area at `0x70000000`) it regressed to 332 matching
  operations. Areas across `0x80000000` look unsafe; that is not
  investigated.

**Next:**

1. Run with both switches and find the call that returns -1 before the
   crash.
2. Check that `search_and_map` honours `start_addr` inside the liblv2 area.
3. The pager: implement lv2 327 (page-fault notification) and 57 (recover),
   using the event layout from Phase 6.

Defaults are unchanged for Prologue. GT5 runs the label fix only, its
best-measured state.

## Phase 6 — The 01.04 executable; system cache and address areas (2026-10-27)

**Retarget.** The port now lifts the 01.04 update executable. It was
decrypted with RPCS3 from its install of the disc's `INSDIR/DATA000.PKG`.
`BCUS98114-v104` in `config/targets.json` carries its values; CMake and
`scripts/target.py` gained `title_id`, so a config key need not be a title
id. Re-derived for 01.04:

| Value | 01.00 | 01.04 |
| --- | --- | --- |
| `code_end` | `0x0111C684` | `0x011752A4` |
| setjmp / longjmp | `0x00D00D74` / `0x00D00E98` | `0x00D49E94` / `0x00D49FB8` |
| Policy module | `0x0177F200` | `0x0182C400` (byte-identical) |
| Job bodies | 28 | 36 (11 byte-identical, moved) |
| Jump tables / seeds | 338 / 4,486 | 349 / 4,617 |
| Lifted PPU functions | 83,175 | 84,413 |
| Import stubs | 716 | 702 |

The job bodies are every 16-byte-aligned header with the `0xC0DEC0DE` magic,
the same rule that gave 01.00's list. The policy module and 11 bodies were
found in 01.04 by exact byte search. The SPU lift has 32,747 functions, the
14 job images captured under 01.00 still match, and no new job image missed.
Import changes: on-screen-keyboard and NP additions and one `cellUsbd` call;
`cellImeJp` is dropped.

**01.04 behaves like 01.00 after the warning.** The NULL object of Phase 5
appears at the same code (`func_00B5169C` in 01.04 is `func_00B128F4` in
01.00). The executable mismatch was not its cause. 01.04 stays the target
because it is what the data and RPCS3 correspond to.

**System cache (runtime fix).** `cellSysCacheMount` reported
`/dev_hdd1/cache/<id>`, and nothing mapped `/dev_hdd1`. GT5 stat'd the path,
then `/dev_hdd1`, tried to mkdir `/dev_hdd1` and gave up on its paging
directory. Now:

- `/dev_hdd1/` maps to `gamedata/dev_hdd1/`;
- the mount reports `/dev_hdd1`, as firmware and RPCS3 do;
- the same cache id mounted again keeps the contents (relayed, 1); any other
  id clears them (0). The id is stored in `gamedata/dev_hdd1.id`.

`PS3_SYSCACHE_LEGACY=1` restores the old behaviour. GT5 now creates
`/dev_hdd1/mem/page` exactly as RPCS3 does.

**Address areas (runtime fix).** `sys_mmapper_allocate_address` (lv2 330,
in `ppu_loader.cpp`) handed out addresses from a counter. GT5's 512 MB area
landed on `0x30000000`-`0x50000000`, across the runtime's own
`sys_memory_allocate` window (`0x40000000`-`0x50000000`). It now hands out
the lowest free aligned area that overlaps neither earlier areas nor the
runtime's fixed windows. `PS3_MMAPPER_AREA_LEGACY=1` restores the counter.

| Area | RPCS3 | This port now |
| --- | --- | --- |
| 256 MB | `0x30000000` | `0x20000000` |
| 512 MB | `0x40000000` | `0x50000000` |
| Pager, 256 MB | `0x60000000` | `0x30000000` |

RPCS3 also puts liblv2's own heap at `0x20000000`. Prologue's single request
still gets `0x20000000`. Its dealer page was re-checked: 30 FPS, no fault
markers.

**Still black after the warning.** From a clean first-boot state (package
files only; the old `PDIPFS` cache files from earlier runs removed), our file
accesses match RPCS3's one for one for 145-152 operations. That includes the
`PDIPFS_bdmark` rebuild, and the 32 files the title extracts are
byte-identical to RPCS3's. The stopping point then varies between runs: after
`9/QW/GV` once, after `K/AK` another time.

The main thread spins in the NULL path:

- `func_00BC22A8` takes a reference-counted pointer from `func_00B4EAB0`;
- that function allocates 0x90 bytes, constructs the object
  (`func_00B4E6AC`) and wraps it;
- its landing pad `0x00B4EAE4` deletes the object and rethrows;
- the allocator wrapper `func_00B3E4FC` retries for ever, so it cannot
  return NULL.

Hypothesis, untested: the constructor throws a guest C++ exception, and
unwinding through lifted code leaves the pointer NULL. `func_00BC22A8` then
calls its assert routine (`0x00B3FBB4`, which returns) and carries on with
NULL. That loop is the black screen. Every other thread is idle in normal
waits.

**Also measured, not yet fixed:**

- GT5 pages memory itself. It reserves a 256 MB area, calls
  `sys_mmapper_enable_page_fault_notification` (lv2 327, still a stub here),
  and its thread `MpAnk` serves the faults: it receives the event on the
  queue, maps 64 KB shared memory, loads the page from `/dev_hdd1/mem/page`
  and calls `sys_ppu_thread_recover_page_fault` (lv2 57). RPCS3 serves 605
  faults on a first boot.
- The pager's event layout, read from its code (`0x00C4784C`):
  - source is `0xFFFE000000000000`;
  - data1 is the fault address;
  - data2 is (type << 32) | thread id, with type 0 for PPU and 1 for SPU;
  - data3 & 3 == 2.
- This runtime commits any untouched page as zeros, so the pager is never
  asked. That is correct only until a page is evicted and touched again.
  `sys_mmapper_unmap_shared_memory` and `_free_shared_memory` are not
  implemented either.
- One job image (`jD58063CD`, LS `0x410`) falls back to the SPU interpreter
  8 times per boot. 01.00 did not, and the NULL path happens either way.

## Phase 5 — RPCS3 reference boot; the disc's update package (2026-10-23)

**The RPCS3 first boot.** The user drove a first boot in RPCS3. Screen order:

1. warning;
2. an install prompt the player must accept, then the install itself
   (about 5 minutes);
3. logo;
4. "adjust display area";
5. "creating GT5 system files";
6. logo;
7. opening movie;
8. main menu.

The install prompt is drawn by the title. The RPCS3 log has no
`cellMsgDialog` call.

**What runs is not the disc executable.** Before GT5 starts, RPCS3 installs
`PS3_GAME/INSDIR/DATA000.PKG`. It is a category-GD update, `APP_VER`
01.04, 201 MB. Its contents:

- `USRDIR/EBOOT.BIN`, 26,708,368 bytes. The disc's is 26,031,880, so this is
  a different executable.
- 1,330 `USRDIR/PDIPFS` files.
- `PARAM.SFO`, `ICON0.PNG`, `PS3LOGO.DAT` and `TROPDIR`.

RPCS3 then boots `/dev_hdd0/game/BCUS98114/USRDIR/EBOOT.BIN` ("Updates found
at /dev_hdd0/game/BCUS98114/"). A console also installs the disc's INSDIR
package and runs the newer executable. This port lifts the disc's 01.00
executable, which a console normally never runs.

**The 01.00 executable expects the package's files.** Right after the
warning it opens `PDIPFS/K/4D` and `PDIPFS/K/7M`; both failed here before.
The 1,330 package files were copied from RPCS3's install into
`gamedata/dev_hdd0/game/BCUS98114` (the list comes from the log's
`PKG: Created file` lines; ignored game data). The title now reads them: `K/*` and
`9/*`. The screen after the warning is still black.

The in-game install, which the player accepts, writes the rest of `PDIPFS`
(from `GT.VOL`) and creates:

- the SQLite databases `db/system.db`, `grim2/grim007.db` and
  `pace/data/pace.db`;
- `installed00.dat`;
- `/dev_hdd1/game249.db`.

The call order after the warning in RPCS3 is: `cellGameBootCheck`,
`ContentPermit`, `cellGameDataCheck(type=3)`, `ContentPermit`,
`cellSysCacheMount`, then `cellSaveDataAutoLoad2`, which fails with
`CBRESULT` because no save exists. The save is written much later with
`cellSaveDataAutoSave2` into `BCUS98114-GAME`.

**Why the screen stays black (open).** About 12 s after boot, the main thread
reaches the null branch of a NULL check in `func_00B13248`: it calls
`0x00B00E28`, which looks like an assert or throw. It then carries on with the
NULL object:

- `func_00B128F4` writes state 3 to `NULL+0x50`; the write is dropped;
- `func_00B3F930` walks a list at `NULL+0x18`, called from the virtual method
  `func_00B12DB4` (descriptor `0x018356C8`);
- that is about 10,000 NULL reads a second (1.9 M in 100 s; `[null-read]` in
  stderr).

The same happens with and without the package files, and with Cross pressed
every 3 s from 15 s. Which object is missing, and whether `0x00B00E28`
throws, is not known.

**Decision pending.** Lift the 01.04 package executable (what consoles and
RPCS3 run), or keep debugging the 01.00 disc executable. With 01.04, every
build-specific value would be re-derived for the new executable: `code_end`,
seeds, jump tables, `wws_job_bodies`, HLE stubs. The scripts from Phases 1-4
cover each step. Decrypting it needs RPCS3's Decrypt PS3 Binaries on the
installed `EBOOT.BIN`.

Evidence (ignored, local): `scratch/rpcs3/gt5-firstboot.log` (RPCS3, 136 MB),
`scratch/rpcs3/pkg_files.txt`, `scratch/gamedata-BCUS98114-before-pkg/`.

## Phase 4 — First screen: a lifter bug in split-off epilogues (2026-10-23)

**GT5 boots to its own first screen** (the epilepsy warning, drawn by the
title through the D3D12 backend, about 12 s after launch), then goes black and
keeps running: a 90 s headless boot made 5,327 flips (~60/s) with no exit, no
null calls and one unresolved indirect call (Phase 3 open item below, still
to check). What follows the warning is not investigated; the opening movie
(the disc's `MOVIE` directory) is the first suspect.

The cause of Phase 3's exit was a PPU lifter bug. A function whose tail is
a branch target (here the `lwarx`/`stwcx.` retry loop in `func_006383DC`) is
split, and the tail lifts as its own fragment (`func_00638434`). The lifter's
tail-entry optimisation snapshots the callee-saved restores (`ld r29..r31,
-0x18..-0x8(r1)`) from memory at the fragment's entry. Those restores come
after the epilogue's `addi r1,r1,0x90`, so the snapshot read 0x90 bytes too
low and returned r29-r31 as stack garbage. The caller was the static-init
walker `func_00B835A4` (a list of 24-byte nodes `{?, init OPD, fini OPD, ?,
next}` pushed by `func_00B71878`); with r31 corrupted it followed a `next`
into the RTTI tables, called a `type_info` as a function, and the title went
on to `sys_process_exit(1)`.

How it was found: logging every push (all 324 well-formed) and every node
the walker visits showed the second pass leave the list after node
`0x0190E064`; the page guard (`PPU_WWATCH` + `PPU_WW_GUARD=1`) showed no
store to that node's `next`, so the walker's own register was wrong; the
lifted fragment showed the entry snapshot.

The fix (ps3recomp `tools/ppu_lifter.py`) adds the body's cumulative `r1`
adjustment to each snapshot offset and skips the snapshot when `r1` is
written any other way (`PPU_LIFT_CS_R1DELTA=0` at lift time for the old
behaviour). It changed 20 fragments in GT5's lift. **Prologue's lift needs
the same re-lift** to pick it up; not yet done or measured there.

## Phase 3 — Merge of Prologue Phases 71-133; seven boot blockers (2026-10-23)

`bcus98158-disc-build` (Prologue Phases 71-133) was merged into `gt5`. The
two conflicts (`CMakeLists.txt`, `config/targets.json`) kept both sides: GT5's
`gcm_ctrl_base` and Prologue's optional per-target addresses. The new required
post-lift steps (`spin_patch.py`, `ui_mask_patch.py`, `spu_native_patch.py`)
report "nothing for BCUS98114" and pass. Both lifts were redone with the
current ps3recomp.

State before this phase: 2 flips, a white window, the game shutting itself
down (pads ended, callbacks unregistered, threads joined). State after: 28
flips and 96 file opens headless, then `sys_process_exit(1)` (below). Not a
visual boot yet. Each fix, in the order found, with its measurement:

1. **`cellFsRead` into uncommitted guest pages returned 0 bytes.** The port
   commits guest pages from an access-violation handler, but `ReadFile` into
   an uncommitted page fails with `ERROR_NOACCESS` instead of faulting. GT5's
   646,672-byte `GT.VOL` index read (to `0x302A2000`) returned 0, and the
   title shut down. `cellFsRead` now reads one byte per destination page
   first (`FS_READ_PRETOUCH=0` off); `ppu_fs.cpp` already prefaulted.
2. **`cellGcmMapEaIoAddressWithFlags` (`0x626E8518`) was missing**: 221
   calls, each unresolved. Added; the flags (RSX access rights) are ignored.
3. **The PPU lifter dropped four instructions**: `stdbrx` (arrives as
   `op31_x660`, 4 sites), `vpkuhum` (2), `vexptefp` (8) and `vlogefp` (9).
   Now lowered; the re-lift has no `/* TODO:` other than `.word`. Vector
   registers hold big-endian bytes, so `vpkuhum` indexes bytes.
4. **`sys_mempool_*` was missing** (four pools at boot). Implemented in
   `ppu_sysprx.cpp`.
5. **`sys_lwcond_wait` returned after 1 ms whether signalled or not, and
   every signal was a no-op.** GT5's main thread hands a worker (`ksF3`) a
   request object on its own stack and waits once; it left early, reused
   the frame, and the worker called through a dead vtable (400 null calls in
   60 s, then shutdown). `PS3_LWCOND_REAL=1` (GT5's default, set in
   `main.cpp`) gives real waits: a FIFO of per-waiter nodes, signals reach
   only queued waiters, timeouts honoured, and GCM handlers are pumped every
   2 ms while waiting (they are otherwise delivered only at HLE entry, and
   with every thread waiting none arrived). `PS3_LWCOND_TRACE=1` logs each
   wait, wake and signal. Null calls: 400 -> 0.
6. **lv2 timers refused one-shots.** `_sys_timer_start` with period 0 is a
   one-shot at `base_time` (system time, us); the runtime returned
   `EINVAL` (593 refusals in 60 s) and ignored `base_time`. GT5's timer
   threads (`MEfYS`, queue 8) use nothing else, so the 6-tick wait main
   makes on the counter at `toc+0x271C` (`func_00BD5E94`, waits for the
   counter to advance; `func_00BD5C30` ticks it) never ended. Now: one-shot
   and periodic with an absolute first expiry, `data2` from connect,
   `data3` = expiry time. `PS3_TIMER_ONESHOT=1` enables this; GT5 sets it
   in `main.cpp`, and the runtime default keeps the old timer for Prologue.
   The guest clock is shared as `ps3_system_time_us()`.
7. **No WWS job bodies were lifted.** The policy module streamed bodies into
   LS and fell to the SPU interpreter (`[spu-smc] microstep img=1
   pc=0x0AD58`), while thread 26 spun in `func_00CD29E8` (the job-list
   completion wait, a minimum over per-SPU progress halfwords). 28 bodies
   found by `scripts/diag/find_bodies.py` (now follows `GT5P_TARGET`) are in
   `wws_job_bodies`, all at LS `0x4000`: 28,467 SPU functions. After this:
   no interpreter fallbacks, flips 2 -> 21-28, opens 6 -> 56-96.

Also: `cellKbRead` (`0xFF0A21B7`) and `cellKbGetConfiguration`
(`0x1F71ECBE`) were unresolved; the runtime's reader was named
`cellKbGetData`, which no title imports. Both added.

New diagnostics: `GT5P_FIND=<value>` (scan guest memory for a word, with
each main-stack dump), `PS3_HLE_TRACE_NIDS=<hex>,...` (trace only these
imports), `PS3_LWCOND_TRACE=1`.

### Open: the exit after the cached data loads

Every run, headless or windowed, now ends in `sys_process_exit(1)` from
`func_00D19F8C`, called up from `func_00D0C6E0` / `func_01027F1C`. A fresh
PDIPFS cache (the old one is in `scratch/pdipfs-bak-1`) changes when, not
whether. The first divergence on main is earlier: `func_00B835A4` takes the
head of a context list (`func_00B71878(0)`), reads its `+4` as a function
descriptor and calls it. The head is `0x017C7BC0`, inside RTTI tables, so
the "descriptor" is a `type_info` record (`{0x017F6E90 type_info vtable,
0x01595E58 name, base}`) and the call goes to `0x017F6E90` (unresolved). A
second unresolved call lands mid-function at `0x00B13404` (from
`0x00B133A0`), which looks like a longjmp-style landing. Hypothesis, not
tested: GT5's try/exception context push is a setjmp-like path that
`setjmp_patch.py` does not cover. Main then stores instruction words as data
and exits. The window shows white throughout.

Other open items: `sgx-spurs-printf-handler` (tid 18) makes ~16,000
`sys_spu_thread_write_spu_mb` calls to `0x30040000`, an SPU thread id the
runtime does not know (the `soc-job` chain's address); unresolved imports
`cellUsbdSetThreadPriority2`, `cellUsbdRegisterExtraLdd2`,
`sys_prx_get_module_list`; lv2 syscall 327 (page-fault notification) is a
stub.

## Phase 2 — First lift, build and boot (2026-10-17)

### Baseline preparation

The first GT5 baseline reused the GT5P lift/runtime pipeline with a separate
`BCUS98114` target. `code_end` is set to `0x0111C684`; jump-table analysis
generated 4,486 seed targets from 338 tables. Function discovery produced
67,556 map entries, of which 65,015 start below the code boundary. The PPU
lifter emitted 83,175 functions, including 14,207 mid-function tail-entry
wrappers, in 11 source chunks. The setjmp/longjmp pass patched the two scanned
call sites at `0x00D00D74` and `0x00D00E98`.

The initial policy-image estimate was 11,648 bytes and 190 discovered
functions; runtime later showed that the title requests 12,032 bytes. The
corrected lift contains 194 functions. The initial registry contained only
the policy module; the follow-up below records captured runtime job images.

`lift_audit.py` completed and wrote its baseline under ignored
`analysis/gt5/`. It found 14,074 TODO markers: 14,051 `.word` data-in-text
markers and 23 other unhandled-instruction markers (`vlogefp`, `vexptefp`,
`op31_x660` and `vpkuhum`); there were no unresolved-target markers. The
heuristic audit also reported 23 fall-through-into-gap hazards, 29,238 branch
targets outside the function map, and 94,661 mid-function targets. These
counts are audit leads, not proof that all such targets are executable
functions.

The Release build succeeded through `scripts/build.cmd -DGT5P_TARGET=BCUS98114`
with `CMAKE_BUILD_PARALLEL_LEVEL=4`.

### First boot result

For one headless run, `input/pkg/PARAM.SFO` was copied from the extracted disc;
`GT.VOL` was hard-linked and `MOVIE` junctioned into the ignored staging tree,
so the 12 GB volume was not copied. The runtime read `BCUS98114` from the SFO
and loaded both ELF segments and its entry descriptor successfully.

The guest then returned immediately with `r3=0x2` and the host process exited
with status 0. The run emitted no HLE trace entries and the boot summary found
no filesystem paths touched. This is the first observed runtime blocker; its
cause is unknown. No claim is made yet about the title's actual boot path,
SPU job requirements, or frame output. The initial target choices
`spurs_synth_job_done=true`, `boot_from=bdvd`, and `hdd_title=false` remain
baseline hypotheses.

### Follow-up: launcher, policy size and captured jobs

The immediate return was caused by the custom entry setup: the ELF entry
requires its thread/TLS and LV2 page-size registers, and the top-level launcher
must drain generated tail-call trampolines after the entry returns. Seeding
those inputs and draining the trampoline queue lets startup proceed. The
runtime then showed that the policy module registered with the initial
11,648-byte size did not match the 12,032 bytes requested by the title. The
BCUS98114-only target value was corrected and the policy relifted.

With `SPU_DUMP_MISS=analysis/spu/dump` and that directory present, a 30-second
headless run captured 14 unique SPURS job images. `lift_spu_jobs.py` found
6,384 functions across them and regenerated the BCUS98114 registry. The
Release rebuild succeeded. A further bounded headless run remained alive
until the 30-second harness timeout, read `GT.VOL`, initialized graphics and
issued `SetPrepareFlip` calls. The log showed jobs returning/completing and no
SPURS `dispatch MISS` entries; this verifies the captured registry is being
used, not that the game reached a usable screen.

The BCUS98114 target now builds as `build/gt5.exe`; Prologue targets retain
`build/gt5p.exe`. The boot and soak scripts select the executable from the
same target configuration.

The remaining observed wait is not explained. The run logged
`sys_spu_thread_write_spu_mb` attempts for thread `0x30040000` that the runtime
could not resolve and therefore dropped, and the sampled main-thread path
waited on `ppu_thread_join(tid=27)`. These coincide in the run but are not yet
proven causal. No visual boot has been confirmed; trace the missing thread and
join before claiming the game has booted.

## Phase 1 — Disc and executable triage (2026-10-17)

### Disc contents and metadata

Measured from the extracted BCUS98114 disc:

| Item | Measurement |
| --- | --- |
| `TITLE_ID` / title | `BCUS98114` / Gran Turismo 5 |
| `VERSION` / `APP_VER` | `02.00` / `01.00` |
| `PS3_SYSTEM_VER` / `CATEGORY` | `03.5600` / `DG` |
| Executable layout | One retail `PS3_GAME/USRDIR/EBOOT.BIN`; no `EMAIN.SELF` |
| Data | `GT.VOL` (12,098,856,960 bytes) and a `MOVIE` directory |
| SELF | Retail SELF, key revision `0x000D` |
| Decrypted ELF | `input/EMAIN.ELF`, 26,029,448 bytes; ELF64, big-endian PPC64 ET_EXEC |

The executable was decrypted with the RPCS3 GUI's **Utilities → Decrypt PS3
Binaries** command. The output was checked for ELF magic (`7F 45 4C 46`).
The original disc image was not modified.

### Executable structure and imports

`elf_parser.py` reports two non-empty load segments. The executable section
flags identify the last executable section end at `0x111C684`, used here as a
provisional `code_end` boundary for triage. It must be confirmed against the
function listing before it is used in a lift.

| Measurement | BCUS98158 v03.00 | BCUS98114 v02.00 |
| --- | ---: | ---: |
| ELF file size | 20,452,272 bytes | 26,029,448 bytes |
| Last executable section end | `0xE3EC24` | `0x111C684` |
| `find_functions.py` total / starts below boundary | 45,324 / 43,137 | 62,989 / 60,448 |
| Unique OPD functions (`ppu_loader.py`) | not recorded | 27,012 |
| Firmware imports | 565 across 31 modules | 716 across 42 modules |

`find_functions.py` is heuristic; its count is not the same as the ELF's
unique OPD-function count. BCUS98114 imports 14 modules not present in the
BCUS98158 import list:

`cellCamera`, `cellGame`, `cellMusicDecodeUtility`, `cellPhotoUtility`,
`cellRudp`, `cellSail`, `cellSailRec`, `cellSysutilNpEula`, `cellUsbPspcm`,
`cellUserInfo`, `cellVideoExportUtility`, `sceNpCommerce2`, `sceNpTrophy`,
`sceNpUtil`.

BCUS98158 imports `cellMusicUtility`, `cellSync` and
`cellSysutilAvconfExt`, none of which appear in the BCUS98114 import list.

### State at end of Phase 1

At that point lifting, building and booting had not been attempted. Phase 2
records the baseline results; target-specific runtime behavior and the game's
use of `GT.VOL`/`MOVIE` remain unmeasured.
