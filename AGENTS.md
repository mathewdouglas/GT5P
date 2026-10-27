# AGENTS.md

Context for AI agents working in this repository. Read this before touching the
pipeline; the README describes the upstream port, and this file describes what
this fork is doing differently.

Paths that belong to one machine (the game dump, RPCS3, Ghidra) are kept out of
this file. They live in `AGENTS.local.md`, which is gitignored; read it if it
exists, and create it on a new machine.

## What this repo is

A static recompilation of Gran Turismo 5 Prologue (PS3) to native Windows x86-64,
built on [ps3recomp](https://github.com/sp00nznet/ps3recomp). The game's PowerPC
executable is lifted to C, compiled with clang-cl, and linked against the
ps3recomp runtime, which stands in for the PS3 operating system.

- `origin` is the working fork, `mathewdouglas/GT5P`.
- `upstream` is `sp00nznet/GT5P`.

Upstream status is pre-alpha: it boots, loads 116 assets from the game's packed
filesystem, and then the main thread parks in a wait. It has never drawn a frame.
See [README.md](README.md), [ROADMAP.md](ROADMAP.md) and
[docs/progress.md](docs/progress.md).

## The goal of this fork

Upstream targets one build only: **NPUA80075 v02.00**, the US PSN release.

The copy available here is **BCUS98158, version 3**, the US disc release. It is a
different build, so the upstream pipeline does not apply to it unchanged. The
work in this fork is to reverse engineer the disc build far enough to re-derive
everything the pipeline hard-codes for v02.00, then get it to at least the same
boot milestone upstream reaches.

Treat every statement about BCUS98158 as a hypothesis unless it appears under
"Measured on the disc build" below.

## Start here: state of play (2026-10-21, Phase 108)

Read this section first when picking the work up in a new session on this
machine. Everything below it is the long record; [docs/progress.md](docs/progress.md)
has the evidence, newest phase first (Phase 108 is the latest).

### What works now

- Boots to the main menu (a save exists; a "Confirmation" popup shows on
  News every boot), with the 3D scene behind it, about 30 fps.
- Dealerships: every manufacturer page draws, cars and floor, 22 to 30 fps;
  the page freeze is fixed (Phase 64).
- Arcade, then Daytona: the Race Mode page (the "pit") draws, and the crew
  walk and kneel (Phase 72), about 29 to 30 fps.
- Single Race loads, and the track, ground and stands draw; about 30 fps
  (Phases 69 and 70).
- The opening movie plays when the TV content is visible (Phases 50, 67).
  Menu sound plays.
- 1080p is multisampled, and shadows are softened (Phase 71).
- The 1080p Kyoto menu's black tree rectangles are fixed (Phase 74).
- MSAA depth reaches depth of field, fixing excess menu blur (Phase 75;
  `RSX_MSAA_DEPTH_COPY=0` restores the wrong, empty depth source).
- The race crowd has coloured spectators (Phase 76, `RSX_FOG=0` restores
  raw-coordinate replication). The texture cache now uses 1024 slots by
  default; 512 dropped race texture binds (`RSX_TEX_SLOTS=512` to compare).
- Controller discovery now runs on an SDL owner thread; detached handles are
  retired before rescanning. WASAPI follows default-output changes and retries
  lost devices (Phase 77). `PAD_HOTPLUG=0` and `AUDIO_HOTPLUG=0` disable these
  paths. Isolated recovery checks: `scripts/test/hotplug.ps1`.
- High Speed Ring's heavily speckled road is improved by correct samplers on
  all 16 units and authored compressed-texture mips (Phase 78). Pipeline keys
  ignore unused texture bindings and share identical fragment code across
  addresses; native driver pipelines now persist beside DXBC in `shadercache/`.
  `scripts/test/race.ps1 -Track HighSpeedRing` warms a local race cache.
- Cars no longer draw over the High Speed Ring bridge (Phase 79): scene
  depth survives shadow/colour-only passes, with real guest depth clears
  kept in order. `RSX_DEPTH_KEEP=0` restores the fault. Verified at 1080p/2x
  MSAA; `race.ps1 -IntroShots` captures the introduction. Shared shader
  bytecode also stays in a bounded memory cache (`RSX_DXBC_MEM=0` bypasses).
- Distant grass, hills and road now use the uploaded mip chain in per-draw
  views (Phase 80); previously those views exposed only level zero.
  `RSX_TEX_MIP_VIEWS=0` restores the grain. Loading-list fonts also reset
  reused shadow-pass state before building their glyph atlas
  (`RSX_MASK_STATE_RESET=0` restores missing glyph parts and white blocks).
  `race.ps1 -LoadingShots` captures the list before it disappears.

- Road normal maps now honour TEX `_bx2`, with typed per-channel expansion,
  and compressed road textures stop at their valid mip count on the shorter
  axis (Phase 81). Switches: `RSX_TEX_EXPAND=0`, `RSX_BC_MIP_LIMIT=0`.

- Opening copyright, Sony and Polyphony screens now appear at 1080p (Phase
  82). Size alone no longer substitutes the black frame copy for their
  1920x1080 uploads. `SCREEN_AS_TEX=1` restores the old heuristic; actual
  render-target/display sampling still resolves by address.

- Dark areas no longer pulse together with the title's dither noise (Phase
  83): texel-addressed 2D textures on units 4-15 now receive coordinate
  conversion too. `RSX_UNNORM_HI=0` restores the dark dealership-floor flicker.
  Verified at 1080p/2x MSAA, with menu, 720p and opening-logo checks.
  `scripts/test/unnorm_hi.ps1` checks the actual backend helpers without a GPU.

### Open work, in the order the user left it

**Latest: anisotropic filtering (Phase 133).** The title asks for none
(TEXTURE_CONTROL0 max-aniso 0). The bank's linear and trilinear samplers
are now `D3D12_FILTER_ANISOTROPIC` (`RSX_ANISO`, default 16; F1 GAME >
Texture filtering, `game.anisotropy`). The root signature is part of the
pipeline key, so the first run after changing it rebuilds every pipeline:
captures then show missing draws. That is the rebuild, not a fault.

**Cockpit mirrors (Phase 132).** The cockpit view stamps its
mirror shapes into the scene's stencil (REPLACE, ref 1/3) and draws each
mirror through a stencil test. The glyph-mask redirect
(`rsx_stencil_mask_pass`) took those stamps. It now applies only to the
text's fill and erase ops (INVERT, INCR/DECR_WRAP, ZERO;
`RSX_STENCIL_MASK_ANY=1` old). Draws that test stencil keep their zeta
(`RSX_STENCIL_ZETA=0` old).

**No dither, no banding (Phase 131).** The title's 8-bit colour
targets are kept at 16 bits per channel (`RSX_HIGH_PRECISION`, `rsx_hp()`,
`R16G16B16A16_UNORM`). Guest-memory fills, write-backs and readbacks
convert. The title's dither noise is neutral (a sample of 0.5, expanding to
0): unit 15 in materials, unit 1 in the final tone map
(`RSX_GAME_DITHER=1` keeps it). Draws into the 8-bit display add a +-1-step
triangular noise per host pixel (`RSX_FINAL_DITHER=0` off). Setting: F1
GAME > Smooth colour (`game.smooth_colour`). Open, not caused by this: the
cockpit view's mirrors are black in 8-bit too.

**Race at full width, labels, dither (Phase 130).**

- **Race at full width:** at 1440p and 4K the race scene (the title's
  1280-wide surface, stretched to 1920) is rendered at the full host width.
  Targets record the guest width they hold (`OffRT.gw`, `rt_gw()`), since
  1280 and 1920 now have one host size (`RSX_RACE_FULLWIDTH=0` off).
- **My Page labels:** the cut-off is fixed by the new required post-lift
  step `scripts/ui_mask_patch.py`. `func_00768340` subtracted 1.0 instead
  of the layout's share of the screen.
- **Dither noise:** sampled at host pixels (`RSX_WPOS_NOISE_HOST=0` off).

**4K (Phase 129).** `"2160p"` / `"4k"` renders natively at
3840x2160 (5120x2160 at 21:9, 64/27). Depth buffers and the depth copy grow
past 2048 rows, and zb surfaces may be up to 8192 per side. Warm HSR frame
test: 59.2 FPS (59.3 ultrawide).

**Native 1440p (Phase 128).** `"1440p"` now renders natively
(`RSX_RENDER_HEIGHT=1440`): stage B's scaling is applied in y as well
(`uw_host_h`/`uw_guest_h`, `rs_on()`), and WPOS y goes through
`rsx_alphatest.w`. The game still lays out at 1080p, so the field of view is
unchanged. `GT5P_RENDER_NATIVE=0` renders 1080p and upscales instead.

**Borderless fullscreen and 1440p (Phase 127).** F1 VIDEO > Window
(`video.window`, `RSX_WINDOW_MODE=borderless`) and Resolution 2560 x 1440
(`"1440p"`, 3440x1440 at 21:9). The backend's output pass scales the
render into a swap chain of another size (`RSX_OUTPUT_SIZE`,
`RSX_OUTPUT_PASS=0` off, `RSX_OUTPUT_FILTER=linear`). 1440p renders at
1080p (2580x1080 ultrawide: `RSX_ULTRAWIDE_ASPECT`, aspect 43/18).

**Ultrawide scene cameras and opening screens (Phase 126).**
The menu background, dealer and pit cameras take 16/9 from
`scene_camera_aspect_16_9_float` (`0x01280924`), now patched too
(`GT5P_ULTRAWIDE_CAM=0` off). Full-screen images uploaded to main memory
(copyright, Sony, Polyphony) are pillarboxed by the vertex shader
(`vp_posoffset.w = -0.75`, `RSX_ULTRAWIDE_PILLAR=0` off).

**Ultrawide renders natively (Phase 125).** For 21:9 the
backend makes the title's full-screen targets 4/3 wider (`uw_host_w`,
`s_gw`/`s_gh` are the guest's display), scales viewports, scissors, depth
clears, readbacks and WPOS, and presents 2560x1080 1:1 (`RSX_ULTRAWIDE=2`;
`GT5P_ULTRAWIDE=anamorphic` is stage A).

**Ultrawide setting (Phase 124).** F1 VIDEO > Aspect ratio, or
`video.aspect = "21:9"`, turns ultrawide on (restart needed).

**Ultrawide step 3 (Phase 123).** `GT5P_ULTRAWIDE=1` also patches
the menus' UI aspect (`ui_aspect_16_9_float`), so the game centres menus at
16:9. Full-screen dims and fades are stretched to the 21:9 edges by the
vertex shader (`vp_posoffset.w`, `RSX_ULTRAWIDE_EDGES`). Open: the My Page
label cut-off, and the F1 page and movie still stretched.

**Ultrawide stage A (Phase 122).** Run it with
`GT5P_ULTRAWIDE=1 GT5P_RESOLUTION=1080p`. The port patches the aspect at load
and the backend makes the window 21:9 (`RSX_ULTRAWIDE`); the swap chain
stretches the 16:9 frame over it. Races and the dealer are correct and
nothing is culled at the edges. Menu 2D is stretched (step 3). Native-width
targets are stage B.

**Ultrawide step 1 (Phase 121).** The game's aspect ratio is one
table entry, `aspect_16_9_float` (`0x01287DD0`), read once at boot by
`func_007AE548`. Writing 64/27 there at load (`GT5P_POKE_BOOT=01287DD0=4017B426`)
gives the race camera a 21:9 projection with the same vertical field of view,
and the race HUD then lays itself out centred. Menus keep their full-width 2D
layout. Next steps are in [docs/plan-ultrawide.md](docs/plan-ultrawide.md).
New tools: `GT5P_POKE`, `GT5P_POKE_BOOT`, `RSX_CAP_VPFULL`.

**Rebindable keyboard (Phase 120).** The settings file has a
`[keyboard]` section and the F1 page a Keyboard tab (Cross/Enter, then the
key; a key in use swaps; Defaults). Both go through `PAD_KEYMAP`
(`cross=Z,...`). The code is `src/gt5p_keymap.*` and cellPad's
`pad_keyboard_set_vk`. The key art follows the bindings.

**Button prompts follow the controller (Phase 119).** Kenney's
CC0 art (`assets/glyphs/kenney/`) is painted over the game's button
textures, which are listed by content hash in `assets/glyphs/textures.txt`:
the 52x52 Cross by "Enter", the 460x720 button-assignment diagram and
its 14 red highlight rings (redrawn around the new icons). The
backend hook is `rsx_tex_set_replacer`, and the cellPad device is
`g_pad_device_family`. A PlayStation pad keeps the original art.
Switches:

- `GT5P_GLYPHS=auto|playstation|xbox|nintendo|keyboard|0` (F1: INPUT >
  Button prompts);
- `RSX_TEX_REPL_DUMP=<dir>` finds new hashes;
- `GT5P_GLYPHS_CYCLE` tests the live switch.

**Tunnel lighting fixed (Phase 118).** The title meters exposure from
a 16x8 block it blits (NV3089) out of a GPU-only surface; our blit copied
stale guest memory, so adaptation never ran. Such blits now record a
readback in command order (`RSX_BLIT_READBACK=0` off). Draw records are
reused: new draws must clear `readback`. Non-window-sized targets get their
own depth buffer when they depth-test (`RSX_RT_OWN_DEPTH=0`), fixing the car
reflection probe; its cube copies a face skipped while bound later in the
frame (`RSX_CUBE_RT_ONCE=1` old). Tools: `rdoc_expo.py`, `rdoc_vlit.py`, `rdoc_smalldraws.py`,
`GT5P_WATCH=addr>off`, `RSX_SKIPDBG_FP`.

**Settings in a race pause it (Phase 117).** Opening the page
while racing presses Start for the title (cellPad `g_pad_inject_buttons`),
unless a pause bar or grid menu is shown: found by scanning guest memory for
mListBox (`menu_listbox_vtable`). `GT5P_SETTINGS_PAUSE=0` off. New
diagnostics: `GT5P_MEMSNAP` + `scripts/diag/memsnap_diff.py` (find state
variables by memory diff), `GT5P_WATCH`, `GT5P_SETTINGS_TOGGLE_AT`,
`race.ps1 -ExtraHold`.

**Settings page as a game settings popup (Phase 116).** Copies the
game's "Steering Settings" popup (value boxes, drop-down buttons and lists),
pages switched with L1/R1. `settings_test.ps1` presses Page Down to reach
the Shaders page.

**Game-style settings page; Escape asks (Phase 115).** The page
copied the game's Options screen and pill buttons, measured from 1080p
shots; Escape shows a copy of its Confirmation popup ("Quit Gran Turismo 5
Prologue?", `GT5P_ESC_CONFIRM=0` closes at once). Test:
`scripts/test/quit_confirm.ps1`.

**Settings page in the game's picture (Phase 114).** F1/PS now
draws the page into the frame (backend `rsx_d3d12_overlay_set`, blended
before present), styled like the game's popups; on the game's own Options
screen a "SELECT PC settings" tag opens it with Select. Escape no longer
closes the game while it is up. Switches: `GT5P_SETTINGS_UI_LEGACY=1` /
`RSX_OVERLAY=0` (old window), `GT5P_OPTIONS_HINT=0`, `GT5P_SETTINGS_UI_ALPHA`;
`GT5P_SETTINGS_UI_DBG=1` prints each screen script. `settings_test.ps1
[-Legacy]`. Still open: the dark tunnel interior.

**Barrier fixed; stale pipeline blobs found (Phase 113).** The
native pipeline blob key left out the root signature (static samplers), so
blobs from older builds served old sampler setups: this, not saturation, was
the road streaking of Phases 94/97. The key now includes it
(`RSX_PSO_KEY_RS=0` old key); fragment source saturation is the default
(`RSX_FP_SOURCE_RANGE=0` legacy), fixing the black barrier (user-confirmed).
The tunnel interior is still dark. Diagnostics: `RSX_FP_SATLOG`,
`RSX_FP_SAT_OPS`, `RSX_FP_SAT_PROG`, `RSX_FP_SAT_VIS`.

**Native sorted walk; SPU interrupts measured (Phase 111).** The
race workloads' sorted-list insertion (body 0x0133A700, 0x43E8) now runs
natively (`src/gt5p_spu_native.c`, hooked by the new required post-lift step
`scripts/spu_native_patch.py`): workloads 5/6 ~11.2 -> ~9.2 ms a pass in an
A/B within one boot; `GT5P_SPU_NATIVE=2` checks every walk against the
lifted code (0 mismatches in millions). The dealer's SPU interrupts are only
~2.5% of render-lane CPU (`SPU_IRQSTAT=1` now reports cycles): not worth
reworking. The rest of its 40% runtime share is call/return dispatch.

**SPU profile, where rewrites would pay (Phase 110).** Ferrari
dealer render workloads 0/1 take ~29-30 ms a lane pass (SPU-bound at 30
FPS): 60% body b01376080 (0xF8C0 18%, rest spread), 40% runtime, with ~33,000
SPU interrupts/s from the job manager's tag-update events. Race workloads 5/6
are 90% body 0x0133A700, 40% in one sorted-list walk at 0x43E8/0x43E0 (68-byte
nodes, float key at +60). `spu_fi` is now SSE (bit-identical, `-DSPU_FI_SCALAR`
for the old): race workloads 5/6 11.0-11.4 -> 10.0-10.5 ms. New tools:
`SPU_IRQSTAT=1`, `SPU_EXP_AB=1` with `g_spu_exp` (`abcyc.py --key exp`),
`scripts/diag/widprof.py` (sums `GT5P_SAMPLE_WID` tables by function and image). See Phase 110 for the plan.

**Hood-camera audio fixed; controller during tests (Phase 109).**
Sound cut out in the hood camera: the mixer's IIR filter (image j65DD2F53,
0x1E8) ran on denormal floats, which x86 computes ~100x slower and the SPU
flushes. Threads that run SPU code now set MXCSR FTZ/DAZ (`SPU_FTZ=0` off):
hood camera 35-42% silent blocks and ~6 underruns/s -> 0. Backward transfers
in job images and bodies are now direct tail calls too (`lift_spu_jobs.py`;
`SPU_CHAIN_BACK=0` at lift or run time off): workloads 5/6 ~14% less lane
time. Test runs merge a connected controller and the keyboard into the
`PAD_HOLD` script (`PAD_HOLD_MERGE=0` script only). Open: the post-race
replay shows about four overlaid frames and a noise strip on the right edge
(F8 reports from process 34220).

**FIFO walk trimmed (Phase 108).** Changes, each with an off switch:

- Hot data methods (immediate vertex data, transform constants) skip the
  dispatcher's long test chain (`RSX_HOT_METHODS=0`).
- Immediate vertices copy only the attributes the vertex program reads
  (`RSX_IMM_MASK=0`).
- Fragment constants no longer clear a 32 KB block on every draw
  (`RSX_FPK_FAST=0`).

Walk 7.75 -> 6.65 ms per frame. The frame test is now at its ceiling:
59.5 FPS, median 16.6 ms, p99 20 ms, 1% of frames late. `RSX_DRAWPROF=1`
splits draw recording by stage.

**Inline memory access, chained SPU bodies (Phase 107).** The build
now defaults to `GT5P_VM_INLINE=ON`. Out-of-line `vm_read*`/`vm_write*` were
about 65% of the race render thread's CPU (14.1 -> 5.8 ms a frame). The exe is
176 MB, and changing the option recompiles every lifted chunk.
`lift_spu_jobs.py` now chains forward transfers in job bodies as well as job
images (`--chain` updates an existing `generated/`; `SPU_CHAIN_BODIES=0`
skips). This cut the race's one-SPU workloads 5/6 (body `0x0133A700`, the
frame's critical path) from 17 to ~6 ms. Frame test: 59 FPS, 3% late, p99
~27 ms. `GT5P_SAMPLE_WID=<wid>` profiles one workload's SPU code.

**The title's frame pacer (Phase 106).** The render thread pads each
frame with a sleep up to the slowest of its last four once one passes a
vblank (`func_007AF300`, sleep returns to `0x00B24AF4`). Our ms-scale jitter
made it copy every hitch onto the next frames. That sleep is now skipped
(`frame_pacer_sleep_lr` in `config/targets.json`; `GT5P_PACER_PAD=1` keeps
it). Frame test 55 -> ~58 FPS, ~14% -> 7-9% late, p99 ~43 -> ~30 ms. Game
speed is unchanged, and the rolling start still runs at 30.
`scripts/diag/rtsplit.py` splits render-thread frames (timeline `C`/`Q`).

**Frame-time test and a cheaper FIFO walk (Phase 105).**
`race.ps1 -FrameTest` is the 60-FPS pass/fail number: 60 s of HSR racing
after the rolling start, with FPS, p99, % of intervals over 20 ms and walk
per frame (`GT5P_FRAME_LOG`). The walk is CPU work, not waiting. A method
fast path (`GCM_WALK_FAST=0` off) and NOP-loop parks (`GCM_NOP_PARK=0` off)
take it from 12.5 to 9.8 ms/frame. The SPU jobs park the walker on 31 NOPs
plus a JUMP back, which it used to lap ~5,500 times a frame; never skip
those runs fast (the circling watchdog then drops the SPU lists). Frame
test: 51.6 -> ~55 FPS, 27% -> ~14% late. Remaining walk: ~5.6 ms of draw
recording (`RSX_VTX_SKIP=1` drops draws: 4.2 ms walk, 58.8 FPS). The
resident pipeline cap is 8192; menus have their own shader pack.

**Memory (Phase 104).** Private bytes overstate RAM: the NVIDIA
driver backs every GPU allocation with equal page-file commit that is never
resident, so read the working set (F8 now leads with it). Per-frame buffers
follow measured peaks: `RSX_DRAW_CAP` 6144 (was 12288) and raw vertices 48 MB
(`RSX_VTXGPU_MB`, was 96). Race working set 2.84 -> 2.59 GB, FPS unchanged.
The 1 GB mapped view in the process is NVIDIA's own shader cache file.

**Race-start stalls (Phase 103).** The user's 0.6-1.3 s race-start
stalls were the replay thread reading shader bytecode one file at a time from
a 54,000-file cache: 4.9 ms per cold read, with little RAM free to keep them
warm. Races now record their shaders into `shadercache/race-shaders-v1.pack`
and read it back in one read at loading (`RSX_SHADER_PACK=0` off): replay
shader reads 9.1 s -> 0.8 s per run. Race preparation was also turned away by
the 4096 resident cap (menu 1449 + race 3922); `RSX_PSO_RACE_EVICT=1` makes room
but adds 12.6 s of loading, so it is opt-in. See Phase 103.

**Race slow motion fixed (Phase 102).** The race clock ran at
0.38-0.55 of real time: the title advances its simulation from a timer that
its IDLE-priority timer service ("Main Thread", loop at `0x913270`) fires, and
two guest CPUs left it too little time. Guest threads now get both hardware
threads of two cores (`PS3_PPU_CORES=topo-ht`, default; `=topo` previous):
clock 0.97. **The rolling start is meant to be 30 FPS (user).** Vblank ticks
run on their own thread (`GT5P_VBLANK_THREAD=0` reverts); they had waited out
13-17 ms FIFO walks. The generic vertex buffer is 64 MB per half
(`RSX_VPVB_MB`; 320 old): about 1 GB less private memory. F8 reports add
process memory and buffer peaks. `race.ps1 -RaceShots <n>` with the HUD timer
measures game speed. Race windows of 40-56 FPS remain. See Phase 102.
The roadmap to a locked 60 with upscaling headroom is
[docs/plan-60fps.md](docs/plan-60fps.md).

**Toward 60 FPS in races (Phase 101), not reached yet.** One-SPU SPURS
workloads now run on lane threads instead of blocking the kernel
(`SPURS_SINGLE_ASYNC=0`). Guest spin waits on SPU progress yield via a new
required post-lift step, `scripts/spin_patch.py` (`GT5P_SPIN_YIELD=0`); they
had starved Main Thread (host IDLE priority) on the two guest CPUs. Per-frame
vertex/index/constant buffers are mirrored in video memory by a copy list each
frame (`RSX_VRAM_FRAME=0`). Timeline frames 25.8 -> 17.5 ms in a race window;
introduction GPU time 12-15 -> 6-10 ms. The introduction still locks to 30 FPS
(render list passes ~14 ms, FIFO walk ~17 ms/frame). `race.ps1 -Cpu` and
`scripts/diag/rdoc_gputime.py` are the new measurement tools. See Phase 101.

**Review fixes (Phase 100).** Startup preload now prepares the learned
menu set, then the race set, and stops; race loading cancels it
(`RSX_SHADER_WARMUP_SCAN=1` restores the full directory scan). Draw-miss
pipelines no longer stay in the resident set (`RSX_PSO_RETAIN_DEMAND=1`);
`RSX_PSO_RESIDENT_MAX` lowers the cap. Recipes unused for 14 days of play are
pruned and both indexes compacted newest-first at worker start
(`RSX_PSO_RECIPE_KEEP_DAYS=0` disables). Texture staging buffers are freed
after 120 idle frames (`RSX_TEX_UPLOAD_KEEP=0` keeps them). Audio uses device
notifications instead of 500-ms polling (`AUDIO_HOTPLUG_POLL=1`). Measured at
1080p/2x HSR with preload on: about 265 MB less mean private memory, startup
preparation 9.3 s instead of 36.7 s, no race recipes rejected. The open
rendering bugs below were deliberately left alone. See Phase 100.

**Background startup warmup (Phase 99).** With startup warmup and async
pipelines enabled, the present owner queues the preparation pass and releases
startup immediately. The existing below-normal worker services live draws
first, learned opening/menu recipes next, then the remaining recipes. Race
loading interrupts the remaining startup pass. Membership:
`shadercache/warmup-v1/menu-v1.txt`, learned during boot/menu visits; preserve it.
`RSX_SHADER_WARMUP_BACKGROUND=0` or `RSX_PSO_ASYNC=0` selects legacy blocking
startup. Precompile-only completion remains blocking. No new F1 toggle: existing
Preload known shaders help now describes background behavior. One native call
cannot be preempted; first visits still learn and may show late details.
`pso99-movie` shows copyright and movie frames while preparation runs for 27 s;
`pso99-menu-priority`/`pso99-menu-ui` prepare 132 menu records first, then reach
visible Kyoto/menu UI. WARP scheduler/shutdown, four real preload fixtures and
23 settings/export checks pass. See Phase 99 for limits and evidence.

**Latest: race loading preparation / async pipelines (Phase 98).** F1 now has
Background pipeline creation (`video.pipeline_async`, `RSX_PSO_ASYNC`) and
Prepare race pipelines (`video.race_preload`, `RSX_RACE_PREWARM`), both default
On. Guest native pipeline creation uses one bounded worker; pending draws use
the existing asynchronous-shader policy. Limits: 256 queue jobs, 64 MiB copied
sources, 4096 resident pipelines. Both switches accept 0 for rollback.
The loading script waits up to 30 s for the learned race set while render/audio
continue (`RSX_RACE_PREWARM_WAIT_MS=0` disables waiting). This is a shared set
of observed race states, not per-track exhaustive discovery; first visits can
still show late details. Index: `shadercache/warmup-v1/race-v1.txt`; preserve it.
The learn run records 1059 recipes; `pso98-warm2` makes all ready with zero
rejections during loading, reaches gameplay at 1080p/2x. The user accidentally
closed the preceding warm run; do not diagnose it as a crash. FPS samples are
not controlled benchmarks. Synthetic production-queue WARP, settings/export,
F1/restart, startup-preload and texture/mirror regressions pass. F8 now reports
queue state and copied-source memory; pipeline counts include cached driver
creations. See Phase 98 for ownership, timeout, shutdown and validation limits.

**Latest: rolling-start reports and saturation (Phase 97).** Five F8 ZIPs
from process 1592 are in `logs/debug/` (19:23:58-19:25:32). Intro submission
gaps reach 852 ms; the final report has a 704 ms gap and 118 new pipelines
without additional completed bytecode. `scripts/diag/debug_pacing.py` reads
the ZIPs directly. Cached driver calls now enter busy/timing diagnostics;
`RSX_PSO_HITCH_MS` defaults to 50 ms (0 disables log lines). Phase 98 adds
asynchronous driver creation; this earlier phase was diagnosis. User warmup is
on; measurement scripts
normally disable settings and must explicitly enable it for comparisons.
Source saturation can now be tested independently: `RSX_FP_SOURCE_RANGE=0`
or unset is legacy, `1` full experimental ranges, `2` saturation only. The
saturation-only run still streaks roads; rollback has normal asphalt. Keep
both candidates opt-in. GPU arithmetic tests pass, not full rendering acceptance. Exact barrier appearance and tunnel lighting remain open; road streaks
also remain. Retained RPCS3 road replay is not a matching tunnel reference.

**Latest: wheel volume textures (Phase 96).** The Golf's spinning-wheel
material uses 32x16x8 and 64x64x8 textures. The backend previously uploaded
only their first plane and sampled XY. It now decodes/uploads full volumes,
uses Texture3D/XYZ and keys profiles by volume units (`RSX_TEX3D=0` rollback;
`RSX_TEX_DIMDBG=1` traces dimensions). CPU and WARP tests pass; a live race
capture confirms full resources and wheel bindings. Close Golf side-view
acceptance is still required; a fully covered wheel-centre pixel is not proof
of correct gaps. See Phase 96 and `scripts/test/volume_textures.ps1`.
Tunnel lighting remains open; keep the existing tunnel captures.

**Latest: mirror depth-clear reuse (Phase 95).** The speed-hint glyph mask
reuses scene depth at `02420000`; stale cached mask ownership discarded the
mirror-protecting depth-zero clear. Real scene depth clears now survive that
reuse (`RSX_DEPTH_CLEAR_REUSE=0` rolls back). Helper regression and all 17
export cases pass; a live post-bridge shot retains the mirror sky. Bounded
trace: `RSX_CLEAR_TRACE=1`. Tunnel lighting and blue Golf rims remain open.
Retained tunnel captures are `scratch/rdoc/graphics94-manual_frame{10164,10650}.rdc`;
do not ask for another tunnel drive. The exit capture's wheel shader uses
procedural spinning-wheel coverage and is a different material from the Golf.
The user supplied two Golf captures (`graphics95-golf_frame{7330,8018}.rdc`). Since Phase 109 a connected controller
and the focused window's keys play over a `PAD_HOLD` script (`PAD_HOLD_MERGE=0`: script only).
`RSX_FP_SOURCE_RANGE=1` remains experimental. A default-off run also showed
road streaks, so Phase 94's apparent correlation was not exclusive evidence.
Tests: `scripts/test/depth_clear_reuse.ps1`, `scripts/test/debug_export.ps1`.

**Latest: audio worker headroom (Phase 93).** Profiling identifies three hot
audio images, especially image 4's DSP loops. Windows/Clang builds compile
private FMA copies of images 4/7/9, selected before SPU workers start only when
CPU and OS support AVX/FMA. `GT5P_AUDIO_NATIVE=0` restores the portable images.
A quiet HSR race measured 78.2% of a core on the sound worker against 92.0%
portable in 25-second CPU windows. See Phase 93 for underrun and FPS limits.
Native arithmetic matches scalar `fmaf` across six million tested lanes;
dispatch/registry tests cover unsupported hardware and exact image matching.
No generated source is tracked; wrappers live under `build/`.
The user's screenshots show about 12 GB RAM in use without the game, 15 GB
with it on this 16 GB system. Memory pressure may contribute to pauses, but
the screenshots do not prove paging caused a particular freeze.

**Latest: captured render-queue corruption fixed (Phase 92).** The runtime
duplicated the workload pointer into both halves of SPU r4, accidentally
enabling WWS profiling against the live job queue. Lane 4's final profiling
write clipped the first two job pointers from `2A...` to `0A...`; those jobs
then left unfilled FIFO blocks. A retained pause capture identifies the exact
missing block, descriptor, profiling writeback address and matching payload.
Passing the actual argument high/low words disables profiling when its high
word is zero, preserving the queue. `SPURS_PM_ARG64=0` restores the defect.
`scripts/test/spurs_arg.py` reproduces both progress-row/first-job overwrites
and clipped pointer bits with the real lifted routines and synthetic memory;
corrected/default modes and a separate valid profiling buffer pass.
Corrected 1080p/2x HSR reached ResultRoot after the driven two-lap race,
with no 350-ms stall snapshot in 240 seconds of sampling. The user reports
that it ran much better. A default-path Daytona run completed 180 seconds
without the ring deadlock, with one brief caught-up-FIFO gap; the car ended
stopped off-track, so its 60-FPS median is not a driving benchmark.
Earlier Phase 64's "bookkeeping" interpretation
was incomplete: those writes are optional profiling with a bad pointer.
Read Phase 92 before revisiting ring-size/shared-ring theories. Phase 93 reduces
sound-worker load; remaining audio underruns and stable 60 FPS are open.

**Loading freezes and core placement before Phase 92 (Phase 91).** An inline graphics
callback could signal before syscall 107 queued its waiter. It now pumps after
queuing/releasing the mutex (`PS3_COND_DEFER_GCM=0` restores old ordering);
`scripts/test/cond_callback.py` reproduces the old defect and passes the fix.
At that phase loading freezes and one/two/one-second driving pauses still occurred.
The user reports driving freezes later in lap two and just before lap one's
finish line; a fixed lap-transition trigger is unproven. `snapshot91`'s final
shot reaches lap 2 at 0'23.088 without a stall snapshot, but not a full finish.
Follow output-ring head/label ownership and the parked command's producer next;
never skip unfilled FIFO commands. Default PPU placement is now
`PS3_PPU_CORES=topo`; `=3` restores the previous shared-core placement.
Individual 1080p HSR medians: 33.50 FPS legacy, 46.50 topology, 54.07 topology
plus callback fix; these sample changing scenes, not a precise A/B gain.
Modern dealership checks remain about 30 FPS either way. Priority mapping stays
enabled. Diagnostics: `GT5P_STALL_MS=350`, `GT5P_STALL_STACKS=1`,
`PS3_SC_CONTEXT=1`, `PS3_COND_TRACE_ID=106`. Read Phase 91 before repeating
experiments; failed FMA/label-wait experiments were removed.

**Eiger lag, audio chopping and recurring freeze (Phase 90).** Report
process 40872 reproduces London's 1/2/1-second command-production gaps with
shader busy/pending both zero and no device loss. Its `spurs-jc` thread is
97-99% of a core. This run also captured 156 MB of verbose per-job logging;
`PS3_VERBOSE` was unset, so redirected IDE/export output enabled it implicitly.
Startup now defaults `PS3_VERBOSE=0` for every output type; F1 Runtime log On
or explicit `PS3_VERBOSE=1` still restores full tracing. Debug export remains
useful with Runtime log Auto/Off. Paired 1080p dealer runs recorded 25 audio
underruns with verbose logging versus zero with the corrected default, and
chain job time fell from roughly 80-98% to 40-50%. These are not Eiger FPS
measurements. A quiet 1080p High Speed Ring race still reaches 95-98% chain
busy with five audio underruns, so race-mixer throughput is also open. Quiet
runs still hit unfinished FIFO blocks: the rendering freeze is open and must
not be described as fixed by logging/precompilation.

**Xbox/keyboard prompt assessment:** [docs/plan-input-glyphs.md](docs/plan-input-glyphs.md)
records current bindings and the proposed asset/input/settings work. No prompt
atlas or font codepoint has been identified yet, and no glyph setting is enabled.
Keyboard currently acts as a fallback only; automatic device switching also
requires input arbitration while a controller stays connected.

**Experimental Vulkan feasibility:** [docs/plan-vulkan.md](docs/plan-vulkan.md)
assesses the existing Linux-only runtime backend, Windows integration, GT5P
feature gaps and acceptance gates. This is a plan, not an enabled renderer.
The next proposed task is isolated Windows bring-up; D3D12 remains the default.


**Offline game-shader preparation (Phase 89).**
`scripts/precompile_shaders.py` and [docs/shader-precompile.md](docs/shader-precompile.md)
are the workflow. SHDS fragment tables were located in the ELF and unpacked
MDL3 assets. The disc inventory has 14465 records / 8142 distinct raw payloads
in 1115 bundles; the executable alone has 52 records / 51 payloads. Do not
track catalogs, bytecode, external unpacker source/keys or the source index.
GTToolsSharp is an external local unpacker, not a source dependency.

Preparation uses the real backend text generator/async compiler before guest
entry and exits (`GT5P_SHADER_PRECOMPILE_ONLY=1`). Normal play learns source-state
profiles in `shadercache/fp-profiles-v2/` (`RSX_SHADER_PROFILES=0` disables).
The default offline pass applies up to 64 learned profiles with matching
texture-unit usage; `--profile-limit 256` increases coverage and
`--all-profile-combinations` is a slower broad cross-product. Base-only
preparation barely helped the dealership test: do not claim that inventory
size proves useful cache coverage. The same decoded programs with observed
states avoided compiler work: a paired 1080p dealership route with an offline
scene catalog produced 191 new DXBC entries versus 294 without it (35% fewer).
Both used 15 s settle; this is not an FPS benchmark or London verification.
The player's normal cache now has about 35000 newly prepared DXBC entries.
Native PSOs,
vertex programs, runtime-generated/fixed-up programs and unseen states remain
open. Some raw payloads fail validation or have out-of-bounds register
references; these are logged/skipped, not complete coverage.

`RSX_FP_CATALOG` optionally records live raw programs for local matching. Its
hot-path seen cache is essential; an initial filesystem lookup on every draw
dropped throughput badly and was fixed before shipping. It defaults off.
Tests: `scripts/test/shader_library.py` (synthetic) and
`scripts/test/shader_library_runtime.py` (real compiler, isolated scratch cache).
`--compile-only` resumes an existing catalog, preserving completed entries.

**London pauses and startup preload (Phase 88).** Two exports from
process 13712 (`27320247aa00`) overlap the same stall sequence. Early hitch
samples often have shader compilation active; the later 1/2/1-second gaps
have busy=0/pending=0, almost all time in idle waiting, and a FIFO parked on
an unfinished `FFFFFFFF` command block. Render SPURS groups are idle with no
ready work. This narrows the long freeze to command production, not a proven
shader or GPU fault; the producer/guest scheduling cause remains open. Do not
skip the unfinished block to force progress. Use
`scripts/diag/debug_reports.py logs/debug --pid 13712` for the evidence.

F1 VIDEO now offers **Preload known shaders**, default Off,
`video.shader_warmup` / `RSX_SHADER_WARMUP=1`; restart required. Normal play
records derived pipeline recipes under `shadercache/warmup-v1/` (never track
them); `RSX_PSO_RECIPES=0` disables recipes. Preload prepares up to 4096 known
pipelines before guest execution and retains them for normal lookups. New
variants still compile later; this is not exhaustive shader discovery. Keep
the shader cache enabled. Old caches learn recipes on the first new-build run.
The old "Precompile shaders" option is now "Background shader compilation";
its TOML key/behavior is unchanged. Verified: 333 known PSOs loaded in 344 ms,
256+ memory hits en route to a working 1080p dealership; invalid recipe and
truncated bytecode safely skipped. More startup time and RAM; leave opt-in.
Checks: `scripts/test/shader_warmup.py`, `scripts/test/settings_test.ps1`,
`scripts/test/debug_export.ps1`. Full London race comparison still needed.

**Earlier test reports (Phase 87):** the user reports stutters and a recoverable
black/frozen image during ordinary driving while physics continues, missing
replay controls even after input, and a dark High Speed Ring tunnel. These are
open. Five exports from process 35540 show both expensive early presents and
later 1/2/1-second delivery gaps not explained by the old timing categories.
Do not call either a shader-compilation diagnosis. New exports include
`hitches.txt`: up to eight live state samples during gaps over 250 ms, only
while Debug export is On (`GT5P_HITCH_CAPTURE=0` disables). Report v2 adds idle,
vblank and flip timings. `scripts/diag/debug_reports.py logs/debug --pid 35540`
summarises the original reports without extracting game images.

The missing 1080p track-map outline has a measured fix: MAIN texture offsets
must not alias LOCAL render targets (`RSX_RT_LOCATION=0` restores the fault).
The source outline was intact; the GPU sampled an old 1920x1080 target instead.
A moving 1080p race now shows the outline. Replay controls and tunnel lighting
have not been verified fixed by this change.

**Also open: High Speed Ring at 1080p can corrupt during the grid preview.** The
user's new screenshots show large pale planes and broken grid text after an
initially correct preview. This is still open; the screenshots alone cannot
establish whether presents stopped or which data became corrupt. Phase 86 adds
an opt-in diagnostic export: F1 settings, DEBUG, Debug export On; then F3,
Export debug report (or F8 while F3 is visible). Attach the ZIP from
`logs/debug/`. Enable it before reproducing to retain recent logs. It applies
live and defaults Off; `GT5P_DEBUG_EXPORT=0` disables it, and no environment
value can enable it without the settings option. Tests: `scripts/test/debug_export.ps1`.

**High Speed Ring water appearance is closed (Phase 85):** the user compared
it with RPCS3 and confirmed the same dark appearance there. No colour or
filtering change was shipped. Capture diagnostics now save sampler registers
with each draw rather than consulting later live state; see Phase 85.

The preceding Daytona idle-grid blackout stopped
reproducing for the user once heavy shader compilation ended. A warm three-minute
grid idle followed by a moving Daytona race passed (Phase 84); cold-cache
reliability is unverified. High Speed Ring still reproduced the older race-start
stall. `race.ps1 -GridIdleSeconds 180 -IntroShots` records the idle/entry sequence
and now rejects an FPS sample interval with no actual presents.

The previous report is **menu/dealership flicker**, most apparent in the dark
lower-left dealership floor. Phase 83 corrects the spatial dither coordinates:
a ten-frame control restores the broad near-black pulses; the fixed patch's
brightness range is about 91% smaller. This fixes coherent brightness flicker;
ordinary fine-edge aliasing at 2x MSAA is a separate quality limit. Read Phase
83 for the GPU evidence and comparison commands.

The previous report is **High Speed Ring's remaining road-surface bands**,
compared with RPCS3 (ignore the reference screenshot's HDR brightness).
Phase 81 fixes ignored TEX `_bx2` normal expansion (`RSX_TEX_EXPAND=0`
restores it) and excess compressed mip levels (`RSX_BC_MIP_LIMIT=0`).
The lighting atlas itself matches RPCS3. Its reusable local reference is
`scratch/rdoc/hsrroad-reference.rrc.gz`: replay it with RPCS3's
`--rsx-capture` option instead of repeating live race navigation. It was
saved with Alt+C and inspected under RenderDoc. Read Phase 81 for exact
pixels, diagnostic files and validation limits. The final 1080p preview
capture verifies signed normal decoding and reference mip counts; full-race
verification was blocked by start stalls, also seen with both switches off.
Earlier reports were **pixelly backgrounds and broken loading fonts**,
following High Speed Ring's loading/compilation, 60 fps and race graphics
request (Phases 78-80). The font atlas, scenery mip views, bridge
occlusion, road corruption and redundant pipeline builds have
fixes; a verified 720p/2x-MSAA race measured a median 41 fps over 25 s, not 60.
Other black materials/geometry in the race remain to investigate. Beware
benchmarking the starting-grid preview: Start at `QuickArcadeRoot+5000`, with
retries, and inspect the final shot for the racing HUD. Dropping all draws
also removes the HUD, so that alone cannot confirm the race actually started.
The PPU-inline experiment was not adopted then; since Phase 107 the build
defaults to `GT5P_VM_INLINE=ON`. Phase 79 records the earlier observations.

0. **Phases 76 to 73 (2026-10-18), read them first.** The race start froze every
   time; fixed in the walker (11 of 12 races clean at 1080p). The user's
   four reports, by state:
   - **1080p menu black slab**: fixed in Phase 74. The title sets A2C
     without the AA bit (`0xFFFF0010`); the cutout substitute now follows
     A2C alone (`RSX_A2C_REQUIRE_AA=1` restores the old rule). Phase 73's
     contrary trace never reached the menu scene; do not use it as evidence.
   - **Dealer floor reflects the menu's trees**: not visible on one direct
     menu-to-Acura visit after Phase 74's fix; pit round trip still unverified.
   - **Race crowd smeared**: fixed in Phase 76. Missing fixed-function
     `FOGC.y` turned the generated spectator atlas into fog-colour silhouettes.
     A separate 512-slot texture limit dropped race binds; default is now 1024.
   - **Race freeze and noise**: fixed, except for a rarer second shape
     (Phase 73, "Open").
   Test at the user's settings: `GT5P_RESOLUTION=1080p RSX_MSAA=2`. Drive
   into the race with `"PAD_HOLD=$DaytonaHold,$DaytonaRaceHold,$DaytonaStartHold"`.
1. **Texture-load warning (promised to the user, not started).** When a
   texture cannot be read, show an on-screen badge like "Compiling shaders"
   and log a line. Cases: an unmapped address, an unsupported format, slot
   exhaustion. The badge to copy is `src/gt5p_shaderbusy.cpp`, which reads
   `g_rsx_shader_busy` from the backend. It needs an env switch, like every
   new behaviour.
2. **Parked; the user is trying to reproduce it.** Go to the Race Mode page,
   then back to the main menu: black slabs appear in the menu scene. Then
   the dealer floor reflects the menu's trees. That suggests stale render
   targets or cube faces reused by address; this is unverified.
   `scripts\test\roundtrip.ps1 -Pit` drives menu, pit, menu, dealer. Its
   Circle to close the menu popup (`@PitSceneRoot+23000`) comes too early,
   so move it later. On the last runs, an Arcade round trip alone showed
   nothing.
3. **Loading-screen text fixed in Phase 80:** glyph-mask draws inherited
   `zonly` from reused shadow draw records and went to depth-only targets.
   A warm shader cache did not prevent it. The 720p and 1080p lists now draw
   completely; see Phase 80 for captures and the switches that were ruled out.
4. **Speed and long-standing items:** the "Next" bullet at the end of the
   list below, and [docs/plan-30fps.md](docs/plan-30fps.md).

### Local state of this machine

- **ps3recomp** is at `../ps3recomp-gt5p-master`, based on `5244db9`, with
  local changes in 63 files. `patches/ps3recomp-5244db9-local.patch` is
  their backup. After every change there, refresh it with bash, not
  PowerShell, whose `>` re-encodes the file:

  ```bash
  cd ../ps3recomp-gt5p-master && git diff > ../GT5P/patches/ps3recomp-5244db9-local.patch \
    && git apply --check -R ../GT5P/patches/ps3recomp-5244db9-local.patch
  ```

- **`generated/` is current.** It was lifted with the PPU lifter of
  Phase 69 and the SPU lifter of Phase 72, and `build/gt5p.exe` is built
  from it. A ps3recomp lifter change needs a re-lift:
  - PPU: the README steps, then `scripts/setjmp_patch.py`,
    `scripts/spin_patch.py` and `scripts/ui_mask_patch.py` (all required;
    `--check` reports);
  - SPU: `.venv\Scripts\python scripts\lift_spu_jobs.py`, which takes
    about 20 s and rewrites `src/gen/spu_workloads_bcus98158.c` (diff it),
    then `scripts/spu_native_patch.py` (required; also after `--chain`).

  Then grep `generated/` for `/* TODO:` lines other than `.word`.
- **Instrumentation helpers patch `generated/` in place.** Before any real
  build, check that no `generated/*.fnc_orig`, `*.spc_orig` or
  `generated/spu_lifted/*/*.sfc_orig` files are left; `--restore` puts the
  originals back.
- **`shadercache/`**: never move or delete it. For a cold test, use
  `RSX_SHADER_CACHE=<empty dir>`.
- **`scratch/`** is gitignored working space:
  - Cleanup on 2026-10-19 sent 14.38 GiB of redundant output/backups to the
    Recycle Bin. Some historical capture paths no longer exist; see
    [docs/scratch-maintenance.md](docs/scratch-maintenance.md). Reusable RPCS3
    references, recent race evidence and shader caches were preserved.
  - `scratch/pv/` holds run logs and shots.
  - It also holds the old copies of the scripts now in `scripts/test` and
    `scripts/diag`. **The tracked copies are canonical.**
  - One-off hooks written for Phase 72 (`palette_hook.py`,
    `palcopy_hook.py`, `bonemat_hook.py`) have guest addresses baked in.
- **`analysis/`** holds:
  - `rtti.json` (class names for vtables);
  - `b01376080.bin` and `.dis` (the SPU geometry job and its disassembly);
  - `spu/body_*.bin` (the job bodies).
- **Another session owns** `scripts/instrument_alloc.py` and
  `src/gt5p_allocwatch.cpp`: never stage those.

### Build, play, test

- Build: `$env:CMAKE_BUILD_PARALLEL_LEVEL="4"; cmd /c "scripts\build.cmd -DGT5P_TARGET=BCUS98158"`
  (PowerShell). Never put a compile definition on the whole target.
- Play: `play.cmd`. F1 opens settings, F3 the profiler.
- Automated runs: `scripts\test\*.ps1`. Each one launches the exe with
  `GT5P_NO_SETTINGS=1`, `FS_HIDE=grim/file/contents` and `PS3_VERBOSE=0`.
  Each follows `[milestone]` lines, not fixed sleeps, and kills the game in
  a `finally`. Logs and shots go to `scratch\pv\<tag>.*`. Any extra
  `NAME=VALUE` argument becomes an environment variable for the game. Quote
  values that contain commas (`"PPU_WWATCH_REGS=26,27"`): PowerShell splits
  them otherwise.

| Script | Drives to | Use |
| --- | --- | --- |
| `milestone.ps1` | (library) | `$ToDealers`, `$DealerHold`, `$DaytonaHold`, `$DaytonaRaceHold`, `$FerrariHold`, `Wait-Milestone`, `Stop-Stragglers` |
| `winshot.ps1` | Acura dealer page | `-Tag t -Settle 20 -Shots 3 -Gap 3`: window shots (PrintWindow) |
| `pitshot.ps1` | Daytona Race Mode page | The same. For the race: `"PAD_HOLD=$DaytonaHold,$DaytonaRaceHold"` after dot-sourcing `milestone.ps1`, with `-Settle 70` |
| `roundtrip.ps1` | menu, Arcade or pit, menu, dealer | `-Pit`, `-Every 3` (a shot every 3 s), `-NoArcade`, `-MenuOnly` (stop after menu shot) |
| `dealer.ps1`, `revisit.ps1` | any dealer, or N in a row | `-Moves "DOWN,RIGHT,..." -Enter`; Ferrari is `DOWN,RIGHT,RIGHT,RIGHT,RIGHT` |
| `perf.ps1` | dealer page | fps and CPU, median of `-N` runs; `-Ferrari`, `-Watch <s>` for stalls |
| `cpu3.ps1` | dealer page | CPU per host thread, named by guest thread |
| `pvshot.ps1`, `capshot.ps1` | dealer page | hold a page for `RSX_CAP`; `capshot` saves the backbuffer |
| `rdcap.ps1` | any (`-Hold`) | a RenderDoc capture of the `RSX_CAP` frame (`RENDERDOC_CMD` overrides the path) |
| `movshot.ps1`, `winping.ps1` | boot with the movie | movie frames; whether the window answers messages |
| `settings_test.ps1`, `settings_restart_test.ps1`, `badge_test.ps1` | F1 page, shader badge | UI checks |
| `inp.ps1` | none | a windowed run for someone to drive, with a shot every 5 s |
| `race.ps1` | High Speed Ring race | `-FrameTest` (60 s pass/fail frame times), `-RaceShots <n>` (HUD timer, game speed), `-Cpu`, `-IntroShots`, `-LoadingShots` |

`scripts\diag\` holds the helpers:

- Log readers:
  - `maplook.py` and `lanesum.py`: sample profiles against `build/gt5p.map`;
  - `tl.py`: `PS3_TIMELINE`;
  - `abcyc.py`: `SPU_FAST_AB` runs;
  - `ab.py`: A/B boots.
- Instrumenters (all with `--restore`):
  - `fncount_patch.py <lo-hi>...`: per-10-s call counts for PPU functions
    in an address range;
  - `spufn_count.py <body>`: the same for every lifted function of one SPU
    body;
  - `spcheck_patch.py <func>...`: callees that leak a stack frame.
- `find_bodies.py`: finds SPU job bodies.
- `rdoc_*.py`: run inside `qrenderdoc --python`, with `RDOC_CAP` and
  `RDOC_OUT` set.

### How the last bugs were found (Phases 68 to 72)

Measure first, then narrow. These were the steps:

1. Call counters, to see whether code runs at all.
2. `SPU_DMA_RANGE` with `_AFTER`, `_HIST` and `HIST_LS`, to see what an SPU
   job reads and writes.
3. `PPU_WWATCH*`, to find who stores a value.
4. `RSX_CAP` with `RSX_CAP_AFTER=<milestone>,<ms>` manifests (`a0=`, `fp=`,
   textures per draw), to see what a draw used.
5. RenderDoc, for pixel history.
6. A perturbation test: halve the palette and see whether the picture
   changes. That one separates "data wrong" from "data unused".

Three bugs this way were lifter bugs that compile cleanly and fail
silently. A dropped jump table and `bisl $r0,$r0` were found by asking
"does this code ever run?", not by reading it.

### The user's standing rules

- Commit **and push** to `origin` at the end of every turn.
- No game data, keys, decrypted executables, generated source or decompiled
  code in tracked files. Never `--no-verify`, never `git add -f`.
- RPCS3 is GPLv2: learn from it, never copy from it.
- Use `PS3_VERBOSE=0` for anything measured.
- One `gt5p.exe` at a time.
- Never pipe a run script into `Select-Object -First`.
- No desktop screen grabs; shoot the game window (PrintWindow).
- Every new behaviour gets an env switch.
- Never arm the page guard from boot on a hot page: the menus drop to
  11 fps.
- Don't spawn sub-agents unless asked.
- Use they/them for the user. Give short status updates during long work.

## Measured on the disc build

Measured 2026-10-12 with ps3recomp `master` tools. The game dump is at
the path recorded in `AGENTS.local.md`.
`EMAIN.SELF`, `EBOOT.BIN` and `PARAM.SFO` are copied to `input/disc/`, and the
decrypted game is `input/disc/USRDIR/EMAIN.elf`. Analysis output is in
`analysis/disc/`.

| | v02.00 (upstream) | BCUS98158 v03.00 |
| --- | --- | --- |
| `PS3_SYSTEM_VER` | 02.1500 | 02.6000 |
| Executable layout | `EBOOT.BIN` launcher + `EMAIN.SELF` | Same split |
| SELF type | NPDRM, needs `.rap` | Plain disc SELF, no `.rap` |
| End of last executable section | `0xBE0AF4` | `0xE3EC24` |
| Functions found | 42,316 | 43,137 below the code end (45,324 before filtering) |
| Imports | 439 across 26 modules | 565 across 31 modules |
| Game data | `PDIPFS` tree of loose files | `GT.VOL` (2.05 GB) and `TV.DAT` (2.12 GB), single files |

- The function count was taken with no seed file, so it is not like for like
  with upstream's, which used `config/extra_seeds.json`.
- Modules the disc build imports that v02.00 does not: `cellSysutilAvc2`,
  `cellRec`, `cellSaveData`, `cellKey2char`, `cellSync`, `cellOskExtUtility`.
  v02.00 imports `cellVpost`; the disc build does not. No file named for
  `cellRec` or `cellOskExtUtility` exists under ps3recomp's `libs/`; whether
  that means they are unimplemented is not checked.
- The game data difference is the largest unknown. Upstream's boot milestone is
  counted in `PDIPFS` file opens, and this dump has no `PDIPFS` tree. How the
  disc build reads `GT.VOL` is not yet investigated.
- `USRDIR/GAMEDATA.ESP` is 304 bytes larger than `EMAIN.SELF`, and its first 16
  bytes are the bitwise complement of a SELF header. Its purpose is unknown.
- RPCS3 decrypts from the command line:
  `rpcs3.exe --decrypt <path>` (install path in `AGENTS.local.md`),
  writing `<name>.elf` beside the input. `EBOOT.BIN` passed in the same call
  produced no output file; not investigated.

## GT5 bring-up (BCUS98114)

Initial triage measured 2026-10-17 on the US disc dump, PARAM.SFO version
02.00 (`APP_VER` 01.00, `PS3_SYSTEM_VER` 03.5600, category `DG`). Unlike
GT5P, its `PS3_GAME/USRDIR` has one retail `EBOOT.BIN` rather than a separate
`EMAIN.SELF`; the decrypted ELF is 26,029,448 bytes. The dump has a 12 GB
`GT.VOL` and a `MOVIE` directory. Decryption was done with RPCS3's GUI utility.

| Measurement | BCUS98158 v03.00 | BCUS98114 v02.00 |
| --- | ---: | ---: |
| Last executable section end | `0xE3EC24` | `0x111C684` |
| `find_functions.py` total / below code end | 45,324 / 43,137 | 62,989 / 60,448 |
| Unique OPD functions (`ppu_loader.py`) | not recorded | 27,012 |
| Imports | 565 across 31 modules | 716 across 42 modules |

The function-finder count is heuristic and differs from the number of unique
OPD functions. Compared with BCUS98158, GT5 imports these additional modules:
`cellCamera`, `cellGame`, `cellMusicDecodeUtility`, `cellPhotoUtility`,
`cellRudp`, `cellSail`, `cellSailRec`, `cellSysutilNpEula`, `cellUsbPspcm`,
`cellUserInfo`, `cellVideoExportUtility`, `sceNpCommerce2`, `sceNpTrophy` and
`sceNpUtil`; GT5 does not import `cellMusicUtility`, `cellSync` or
`cellSysutilAvconfExt`.

BCUS98114 has its own lift and Release build (`build\gt5.exe`). As of
Phase 3 (2026-10-23, after merging Prologue Phases 71-133) a boot reads
`GT.VOL`, builds its PDIPFS cache and runs 28 lifted WWS job bodies. Since
Phase 4 it **shows its first screen** (the epilepsy warning), then a black
screen while it keeps running at ~60 flips/s; what follows is open. Phase 3 fixed seven runtime/lifter blockers
(uncommitted-page reads, missing imports, real lwcond waits, lv2 one-shot
timers, job bodies); Phase 4 fixed a PPU lifter bug (split-off epilogue
fragments restored r29-r31 from the wrong stack offset); Prologue needs a
re-lift to pick that up. Read
[docs/progress-gt5.md](docs/progress-gt5.md) Phase 3 before continuing.
GT5 sets `PS3_LWCOND_REAL=1` and `PS3_TIMER_ONESHOT=1` by default; Prologue
keeps the old runtime behaviour for both.

**Since Phase 6 (2026-10-27) the target is the 01.04 update executable,**
`BCUS98114-v104` in `config/targets.json` (`title_id` keeps the game id
BCUS98114). That is what consoles and RPCS3 run: the disc's
`INSDIR/DATA000.PKG` installs it to the hard disk before the first boot.
`input/EMAIN.ELF` is its decrypted `EBOOT.BIN`. The 01.00 disc executable is
kept in `input/disc/EBOOT.elf`, and its lift in `analysis/v100-generated/`.
Build with `scripts\build.cmd -DGT5P_TARGET=BCUS98114-v104`.

`gamedata/dev_hdd0/game/BCUS98114` must hold the package's 1,330 `PDIPFS`
files. They are copied from RPCS3's install; the list is
`scratch/rpcs3/pkg_files.txt`. Since Phase 7 GT5 reaches its **logo** after the warning. Required
pre-lift step: `scripts/code_labels.py --write` (computed-goto labels).
Read [docs/progress-gt5.md](docs/progress-gt5.md) Phase 7 first.

## What is tied to v02.00

These are the known build-specific inputs. Each one has to be re-derived or
re-verified against the disc executable.

| Item | Where | Why it is build-specific |
| --- | --- | --- |
| Code boundary `0xBE0AF4` | README lift commands (`--code-end`, the `functions_code.json` filter) | End of the last executable section in v02.00 |
| Function seeds | [config/extra_seeds.json](config/extra_seeds.json) | Function start addresses from v02.00 |
| `setjmp`/`longjmp` patch | [scripts/setjmp_patch.py](scripts/setjmp_patch.py), [src/gt5p_longjmp.cpp](src/gt5p_longjmp.cpp) | Patches specific lifted functions; required after every lift |
| SPU workloads | [src/gen/spu_workloads.c](src/gen/spu_workloads.c), [scripts/lift_spu_jobs.py](scripts/lift_spu_jobs.py) | SPU images are embedded in the executable at v02.00 offsets |
| Import list | [config/gt5p.toml](config/gt5p.toml) `[modules]`, `src/gen/ppu_hle_nids.cpp` | 439 imports across 26 modules in v02.00; the disc build may differ |
| Instrumentation | [src/gt5p_allocwatch.cpp](src/gt5p_allocwatch.cpp), [src/gt5p_bbcount.cpp](src/gt5p_bbcount.cpp), `scripts/instrument_alloc.py` | Refer to guest addresses by number |
| Function names in docs | `func_009386C4` and similar in ROADMAP and progress log | Named by v02.00 address; they will not match |

## Where the disc build stands

This is the running record, oldest findings first, newest at the end of
the list (Phase 72). For the current state, read "Start here" above. Some
bullets near the top describe stages long since passed. They are kept
because later phases refer to them; where they conflict with a later
bullet, the later one is right.

- **A save exists, so the title boots straight to the main menu** (no
  agreement). Since a car was bought, a "Confirmation" popup shows on News
  every boot. The routes in `scripts\test\milestone.ps1` close it
  (`$ToDealers`, `$DaytonaHold`). Move `gamedata/dev_hdd0` aside to get the
  first-boot screens back. The old `scratch/menu.ps1` and
  `scratch/auto.ps1` drive those first-boot screens and are not tracked.
- **The Car Dealer page draws (Phase 42).** Choosing a manufacturer shows
  the cars on the showroom floor with the page's 2D layer, as on RPCS3. The
  backend had been dropping about 4,000 of each frame's 4,300 draws: its
  per-frame vertex and draw caps were too small (`FRAME_BUDGET=<frame>`
  shows requested against kept). Fragment programs over 4 KB and with more
  than 64 constants are handled now. Compiled shaders are kept in
  `shadercache/` (gitignored), so only a first-ever entry stalls (about
  9 s). Generic vertices are stored with only
  the attributes the program reads (`RSX_VTX_MASK=0` for all 16).
  Phases 39-41 describe the logo-only stage it replaces.
- **Dealership frame rate (Phase 43): 17.5 fps, up from 7.4.** The title's
  own threads cap it at about 20 (`RSX_VTX_SKIP=1` drops every draw and still
  only reaches 20). **The serial limit is the present thread (Phase 45):**
  per frame about 37 ms of FIFO walk, 39% of it `read_vp_vertex`, plus 9 ms of
  present, all on one thread, with `PDI:1` and main close behind. The SPU
  render jobs (Phase 43's "critical path") wait on it for ring space;
  making their code faster gained nothing (Phases 44.2, 45.1, 45.2).
  `GT5P_PRESENT_SLEEP=<ms>` (outer sleep, default 4) and
  `RSX_PRESENT_SYNC=0` (no vsync wait) are measurement switches.
  `SPU_REGCACHE=1` lifts SPU code with registers in locals: correct, slower.
  **Phase 46:** indexed draws keep an index buffer (`RSX_VTX_INDEXED=0` to
  expand as before; `RSX_VTXSTAT=1` for per-path upload stats), about 19.5
  fps. **The dealership stall (Phase 54) is down to about 1 run in 12** from
  about 1 in 5: the title's kicks of its one-SPU workload
  (`cellSpursReadyCountStore`) were lost to a race with the policy module's
  `PUTLLC`; ready-count stores now take the lock line (`SPURS_READY_COH=0`
  undoes it). The stalls left are unexplained; `SPURS_KEVLOG=4`,
  `GT5P_THREADS=2` and `GT5P_PEEK=016FA5E0,0139A880` are the tools.
  **Test runs follow milestones (Phase 54):** `[milestone] <screen>` lines,
  `PAD_HOLD` presses relative to one (`@TopMenuTemplate+8000-8300:CROSS`,
  `!<other>` for a retry), and `scripts\test\milestone.ps1` (`$DealerHold`,
  `Wait-Milestone`) used by `perf.ps1`, `cpu3.ps1` and `capshot.ps1`. The
  page is up about 29 s after launch; `perf.ps1` counts and cuts short
  stalled runs (`-Watch <s>` to look for them).
  Car materials: cube maps on units 4-15 (`RSX_CUBE_HI=0`), cubes whose faces
  are render targets (`RSX_CUBE_RT=0`), constant remaps (`RSX_REMAP_CONST=0`),
  sRGB decode on units 4-15 (`RSX_GAMMA_HI=0`); `FP_IDCOLOR=3` and `FP_SHOW`
  trace a material (46.4); depth test follows the title (`RSX_DEPTH_STATE=0`);
  **the rims now draw (Phase 47)**: ps3recomp's PPU lifter emitted `stvlx`,
  `stvrx`, `lswi`, `stswi` and `vsum4sbs` as no-ops; with them lowered the
  rims are drawn and the title issues its shadow pass. **The shadow map
  works (Phase 49)**: a pass with colour target NONE draws into its own
  depth buffer (`RSX_ZONLY=0` to undo), and units bound to it with a depth
  format compare in the shader (`RSX_SHADOW=0`: always lit;
  `RSX_SHADOW_SHOW=1..6` views the term; `RSX_CAP` dumps the map;
  `RSX_CAP_ZB=<n>` and `scripts\test\capshot.ps1` capture a dealership frame).
  Debug views must skip programs that only have the unit bound, and the car
  pass writes three targets (`_out.t0`). Also from Phase 49:

  - one-pixel viewports are honoured (`RSX_VP_MIN2=1` for the old 2x2
    minimum);
  - draws of up to 16 pixels are written back into guest memory a frame
    later (`RSX_RT_WB=0` to stop).

  After any re-lift,
  grep `generated/` for `/* TODO:` other than `.word`; frame captures
  that ignore desktop windows: `CELLMARK_DUMP*` (46.5);
  `RSX_TEXUNITDBG=<n>` lists every bound unit of the first n programs.
  **F3 in the game window shows a live profiler** (`GT5P_PROFVIEW=1` shows
  it at start, `=0` disables it): fps, frame intervals by vblank count, the
  present thread's split per frame, CPU per named thread (Phase 45.4).
  Frames are quantised to vblanks, so present-thread work must drop below
  about 33 ms for 30 fps.
  The job lanes are threads made per dispatch, so a
  per-thread CPU table misses about 3 cores: use `scripts/test/cpu3.ps1` and
  `GT5P_SAMPLE=all` (or `GT5P_SAMPLE=4` for the busiest live threads), then
  `scripts/diag/maplook.py build/gt5p.map <log>`. `scripts/test/perf.ps1 -Tag <t> -N 3`
  repeats the Phase 43 measurement and prints the median (Phase 44).
- Guest PPU threads stay on mask 3 (both hardware threads of core 0): it
  measured faster than two separate cores or no pinning (Phase 44.1).
  `PS3_PPU_CORES=<hex>|topo` to change it, `PS3_HOST_AVOID_PPU=1` keeps the
  present thread and lanes off those CPUs (within noise).
  Switches that undo the speed-ups: `RSX_VFAST=0` (`=check` compares),
  `VM_SLOW=1`, `HLE_ROUTE_MEMO=0`; `getenv` is cached per call site in hot
  files (`include/ps3emu/getenv_cache.h`, ps3recomp), so a switch must be
  set before launch.
- `GCM_FTRACE=<flip>,<n>`: every command header the FIFO walker decodes
  between `SetPrepareFlip` calls, with its first argument. This title writes
  no flip words, so frame boundaries come from those calls.
- `boot_from=gamedata` (`GT5P_ARGS`) runs from an installed
  `dev_hdd0/game/BCUS98158`; the default `bdvd` reads `GT.VOL` (Phase 42).
- Logs: stdout and stderr are flushed every second (`GT5P_FLUSH_MS`), so a
  killed run keeps its tail. Before Phase 41 the last 64 KB was lost.
- The game's TV/news files (RPCS3's `grim/file/contents`, 2 GB) are not in
  `gamedata/`. With them the title plays a PAMF movie at boot, and the run
  crashes in `func_0099CAA0` (Phase 41).
- Antialiasing: a target that asks for it is drawn multisampled, shaded per
  sample, and resolved when read (`RSX_MSAA=<n>`, default 4, 1 turns it off;
  `RSX_SSAA=0` shades per pixel).
- Controllers: `SDL2.dll` beside the exe is loaded at run time and reads
  every controller (DualSense included); `scripts/get_sdl2.ps1` fetches it
  into `third_party/` (gitignored) and the build copies it. Without it,
  XInput and the keyboard. `PAD_NO_SDL=1` ignores it. A `PAD_HOLD` script
  now wins over a connected controller.
- **Menus and scene now match RPCS3 in content (Phase 37, 2026-10-14).**
  Menu images were immediate-mode strips and fans, which were dropped; shade
  was black because sRGB decode on read (`SET_TEXTURE_ADDRESS` bits 20-22)
  and encode on write (method `0x1FEC`) were ignored; the road was black
  because fragment inputs TEX8 and TEX9 were zero. `0x1D7C` is the
  antialiasing control, not the gamma enable. Switches: `IMM_QUADS_ONLY=1`,
  `RSX_NO_GAMMA=1`.
- Also Phase 37: strips, fans and polygons split over several draw
  batches of one `BEGIN`/`END` are now continued (`STRIP_NOCONT=1`); the
  alpha test is now really applied in generated shaders (`FP_NO_ATEST=1`)
  and alpha-to-coverage is stood in for by a test at one half
  (`RSX_NO_A2C=1`).
- Open from Phase 37: the 2D layer is about 0.55 times as bright as
  RPCS3's. This build draws exactly what the vertex colours and blend
  state say; what RPCS3 does differently is not found. Coverage, colour
  byte order and the scene are ruled out. Fragment programs get only
  texture units 0 to 3.
- Samplers follow the title's filter and wrap settings from a bank of
  twelve static samplers in s4 to s15 (`RSX_SAMP_FIXED=1` for the old fixed
  ones, `RSX_SAMPDBG=1` to list what the title sets). A `ps_5_0` shader has
  sixteen sampler registers; do not declare one past s15.
- **To play it:** `play.cmd` in the project root, or double-click
  `build\gt5.exe` for BCUS98114 (`build\gt5p.exe` for Prologue targets). The
  exe finds the project root by looking for
  `input\EMAIN.ELF` upwards from its own folder (`GT5P_ROOT` to name it),
  turns verbose logging off when its output is a console, and exits when
  the window is closed. Keyboard: arrows, Z Cross, X Circle, A Square,
  S Triangle, Q/W L1/R1, 1/2 L2/R2, Enter Start, Tab Select.
  `gt5p_settings.toml` (written at the root on first start, Phase 48) sets
  resolution, MSAA, vsync, shader cache and input. An environment variable
  wins over it. Measurement scripts set `GT5P_NO_SETTINGS=1`; new ones must
  too.
- `RSX_METHHIST=<n>` prints every RSX method sent in the first n, with
  counts and first values: the way to find a register nothing reads.
  `RSX_GAMMADBG=1`, `GCM_REPORTDBG=<n>`. Capture manifests print `gam=` and
  `sw=` per draw.
- **The 3D scene shows behind the main menu (Phase 34, 2026-10-14).** A
  street of half-timbered houses, captioned "Altstadt, Ahrweiler". It takes
  about 30 s after the menu appears to reach full brightness, and some
  surfaces stay black; neither is investigated. Eight faults in ps3recomp's
  D3D12 path were behind the black window; Phase 34 lists them with the
  switch that undoes each. "Nothing is drawn behind the text" further down
  is history.
- **The one-frame-a-second menu is fixed (Phase 35).** The backend stopped
  presenting on flips for good once a single display clear had ended a
  frame, and this title stops clearing the display at the menu. 8 of 8
  boots good afterwards. A title bar stuck at `draws: 2048` means frames
  are piling up unpresented, not that the title is slow.
- **Sound (Phases 35 and 36).** The menu music had 40 to 49% of its blocks
  empty; a 330 s run now has none and no underrun. The mixer's job chain
  runs at full rate (3,190 jobs a second on the menu) at 58% of a core, and
  the audio mixer follows the blocks the title has written through a small
  jitter buffer instead of reading at a fixed place. Measured on the menu
  only, and nobody has listened yet.
- Sound diagnostics: `AUDIO_RATE=1` (empty-block share, underruns, mixer
  tick jitter), `AUDIO_GAPDBG=1` (each dropout with the ring at that
  moment), `AUDIO_LEADDBG=1` (where the title writes), `SPURS_JC_STATS=1`
  (job rate and cost), `SPURS_JG_GAPDBG=<ms>` (late guard notifies),
  `SPURS_JC_SAMPLE=<chain>` with `scripts/diag/maplook.py` and a `/MAP` link
  (where the walker's time goes).
- **Do not launch with `GT5P_MAINSTACK` set when judging sound or smoothness.**
  It suspends guest threads every N seconds; `scripts/test/inp.ps1` used to set
  it to 5 and that alone was an 85 ms dropout every 5 s.
- `scripts/lift_spu_jobs.py` now post-processes the job images it lifts
  (forward transfers become direct tail calls); `--chain` applies that to
  images already in `generated/`. Re-lifting without it puts the sound
  walker back to about 80% of a core.
- The menu runs at 31 frames a second with the main thread at 93% of a
  core. The console runs it at 60.
- `scratch/menu.ps1 <dir>` drives a windowed boot to the menu and stays
  there (`PAD_HOLD_STOP_DRAWS`); `-Late 30000` for a boot slowed by
  `D3D12_DBG=1`. Earlier timed scripts either stuck on "Confirmation" or
  pressed Cross once more and left for the dealership before the menu had
  faded in.
- `FRAME_CUT_OP=<n>` with `RSX_CAP` shows the display as record `n` left it.
  `FPK_FP=<hex program>` prints a fragment program's constants as uploaded.
  `RT_TEXDBG=<n>` prints how each texture over a render target resolved.
- Fragment-program debug switches that rewrite the shader text
  (`FP_SHOW`, `FP_IDCOLOR`) look for the text `_po.c0 =`; the decompiler in this
  tree ends with `float4 _o = h[0]` (or `r[0]`). Check they took effect.

- **The bad boot is found and fixed (Phase 33).** It was never a heap fault.
  ps3recomp left a job chain's walker thread alive after
  `cellSpursShutdownJobChain`, the title re-creates its sound chain at the
  same address many times, and two walkers then ran one job twice. The extra
  completion event made a later query return before its job had run; a block
  sized from that empty answer was overrun, and the overrun wrote floats into
  the allocator's free list. "Allocation retried for ever", "runaway
  sound-bank fixup" and at least one unflagged short boot are all this.
  The entries below about that fault are history; keep them for the record of
  what was ruled out.
- To test for it, do not rely on `bootcheck`: run with `GT5P_ARENA_TRACE=1`
  and look for a fill pass larger than its dry run (`scripts/diag/ab.py` counts
  them). `SPURS_JG_TRACE=1` prints each guard notify, guard opening and job.

- 20 of 20 boots: 129 `GT.VOL` opens, 27 paths, about 610 flips in 20 s. The
  last three paths are `BootRoot.gpb` (RPCS3's next step), `AgreementRoot.gpb`
  and `serverlist2_us.xml`.
- Main sitting in `sys_cond_wait` at `lr=0x00B391F4` is normal. It has handed a
  request to a script thread. It is not the stop, and was never a deadlock.
- Three cellGcm defects in ps3recomp were behind the old "stop": 16 IO mapping
  slots, two handlers stored but never called, and user commands routed to a
  path with no listener.
- About 1 boot in 6 used to go wrong during sound start-up (Phase 18). After
  the cellGcm fixes that is 1 in 29. Its cause is not found. `boot.py` and
  `soak.py` recognise such a boot and run again
  ([scripts/bootcheck.py](scripts/bootcheck.py)); `SOAK_KEEP_BAD=1` keeps them.
- Ruled out for that fault, by measurement: a held mutex, a spurious condition
  wake, stack overflow, main's missing thread id, the cellFs descriptor table,
  the lightweight mutex on the heap. Do not re-test these without a new reason.
- Frames now run for the whole boot: about 1,180 flips in 60 s, 13 a second
  once the per-frame SPU job starts (Phase 21). Until Phase 21 they stopped at
  about 610.
- With a window the title now shows its first screen, the "Online User
  Agreement", with readable text (Phase 25). It draws text by filling glyph
  outlines into the stencil buffer with colour writes off, then sampling the
  depth-stencil surface as a texture (Phase 23); the backend sends those draws
  to a colour target instead. Three ps3recomp faults hid the result: texture
  coordinates given in texels were not scaled, immediate-mode draws
  (`SET_VERTEX_DATA2F_M` between `BEGIN` and `END`) were dropped, and the
  guest scissor was not applied.
- Nothing is drawn behind the text yet.
- Keyboard input reaches the title: down to the end of the agreement, right,
  Z accepts, and a "Confirmation" screen about auto-save follows; Z again
  starts the top menu loading (`TopRoot.gpb`, `TopMenuTemplate.gpb`, then
  scene scripts, a character and motions). "Confirmation" takes its OK only
  once that load has finished. Then comes the main menu, and Cross on it
  enters Dealerships ("ACURA"); text only on black in both (Phase 28).
- The dealership is not usable. A good boot ends there one of two ways,
  about evenly (Phase 30): a frame every 4 s, with the job manager's policy
  module walking its command list without end on the SPURS kernel thread; or
  a device removal (`DXGI_ERROR_DEVICE_HUNG`) on the first frame that adds the
  scene's post-processing targets, after which the window is frozen at
  `draws: 167`. Neither cause is found; Phase 30 lists what is ruled out.
  None of the 3D scene is visible in either.
- `scratch/cpu.ps1` drives to the dealership and prints per-thread CPU with
  the threads named. Use it before guessing which side is slow.
- A windowed run whose title shows well under 1 frame a second: look for
  `PSO FAIL` in the log before anything else, and run with `D3D12_DBG=1` to
  get the reason printed beside it.
- A windowed boot that shows dark blue and `draws: 0` is the Phase 22 heap
  fault, about 1 boot in 4 with a window. Dark blue is the backend's default
  clear colour. Retry it; do not read anything else into it.
- The crash that used to follow was `cellHttpUtilParseUri` zero-filling 2.7 KB
  of guest stack (Phase 27). When an HLE function takes a guest structure,
  check its size against the SDK before trusting a host-side `memset`.
- `scripts/test/inp.ps1 <secs>` runs a windowed boot for someone to drive, with a
  capture every 5 s. `scratch/auto.ps1 <tag>` builds and drives it unattended
  with `PAD_HOLD` (timed button presses, no keyboard or focus needed).
- Frame rate was bounded by Windows timer granularity; `src/main.cpp` now
  calls `timeBeginPeriod(1)` (`GT5P_TIMER_RES=0` to undo). 62 frames a second
  on the confirmation screen against 20 before.
- Lifted vector stores do not reach `PPU_WWATCH`. For "who cleared this",
  use `PPU_WW_GUARD=1`, with `PPU_WW_GUARD_FN=<fn>` to arm it late.
- A `bctr` the lifter cannot match to a jump table is now a tail call
  (`ps3_indirect_tail`), not a nested call. If `[ppu] recursion cap` ever
  prints, treat the run as corrupt from that line on: the runtime has skipped
  a guest call.
- A windowed run someone is typing into is not a clean measurement. Say so
  when asking for one, or use `PS3_HEADLESS=1`.
- `FP_ONE`, `FP_SHOW` and the other switches that rewrite `_po.c0 = ` in the
  generated shader may do nothing: the decompiler in this tree ends with
  `float4 _o = ...`. Only `FP_ONE` has been fixed. Check that a switch took
  effect before reading a result from it.
- Diagnostics that write files (`VTX_DUMP`, `VP_DUMP`, `CELLMARK_DUMP`) put
  them in the working directory unless told otherwise. Move them to `scratch/`;
  they are derived from the running game.
- A bad boot is a heap allocation that comes back empty and is not checked
  (Phase 22). Guest threads are now scheduled by PS3 priority on two cores
  (`PS3_PPU_PRIO_SCHED=2`, set in `src/main.cpp`), and with that 1 boot in 52
  went bad against about 1 in 4 without. Why the heap is empty is not known.
  `PS3_PPU_PRIO_SCHED=0` brings the fault back for study.
- The job manager's policy module must be lifted at `0xA00`, where SPURS loads
  it, not at 0. `scripts/lift_spu_jobs.py` now does that, and also lifts the
  job bodies the module streams into its own local store
  (`wws_job_bodies` in `config/targets.json`). Before this the SPURS kernel
  thread was stuck in workload 0 for the whole run.
- A new job body shows up as `[spu-smc] microstep ... handing to the
  interpreter`. Do not trust the interpreter with it: dump it with
  `SPU_DUMP_OVL`, add it to `wws_job_bodies` and re-lift.
- Phase 31's all-boots-fail observation was superseded on 2026-10-13:
  later runs again showed mixed outcomes (Phase 32 in `docs/progress.md`). A
  six-run, 20-second headless soak had three normal 129-open boots and three
  known-bad signatures; a second soak had one suspicious low-progress run.
  The 2 KB allocator failure is still unexplained.
- REA cannot open the executable (64-bit PowerPC ELF is "unsupported").
  `scripts\ghidra_decomp.ps1 0xADDR ...` runs Ghidra headless on chosen
  functions instead; its first import is slow and unproven. Do not run it
  while booting the title.
- The device removal is fixed (Phase 33, last subsection): a render target
  recreated mid-frame was released while the open command list still used
  it, and pipelines declared a depth buffer where none was bound. What is
  left there is a different stop: the dealership shows one new picture (text
  on solid green) and then no more frames, and the main menu stops answering
  a few seconds after the first Right press. `wait_for_gpu STUCK` is printed
  to stdout, not stderr; keep both streams.
- Compare brightness with RPCS3 from its framebuffer in a RenderDoc capture, never from screenshots: they can be taken in HDR (Phase 49.4, a false lead).
- **The opening movie plays (Phase 50).** It is the TV content under
  `gamedata/.../grim/file/contents` (RPCS3's install; this port does not run
  the title's own `TV.DAT` install). Decoding needs FFmpeg:
  `scripts\get_ffmpeg.ps1`, then rebuild. Measurement runs must set
  `FS_HIDE=grim/file/contents` (`boot.py`, `soak.py` and `scratch\*.ps1` do):
  with the content visible the movie plays and the menu misses the scripted
  presses. Switches: `PAMF_OFF`, `CODEC_FFMPEG=0`, `VDEC_PTS_FILL=0`,
  `DMUX_PTS_FILL=0`, `RSX_TEX_SNAP=0`; traces `DMUX_TRACE`, `VDEC_TRACE`,
  `ADEC_TRACE`, `RSX_TEX_SNAPDBG`. A job body the SPU interpreter runs can
  stall a title silently: grep for `[spu-smc]` first.
- **F1 settings page (Phase 52)**, `src/gt5p_settings_ui.cpp`: a GDI window
  over the game like the F3 profiler; the PS button opens it too. A new
  setting is a field, its TOML key and one row in `items()`. While it is open
  the title sees every pad at rest (`g_pad_input_blocked`, cellPad.c).
  `GT5P_SETTINGS_UI=0` none, `=1` open at start; `scripts\test\settings_test.ps1`
  drives it with posted keys against a scratch settings file. The
  "Compiling shaders" badge (`src/gt5p_shaderbusy.cpp`, 52.1) reads
  `g_rsx_shader_busy` from the backend; `GT5P_SHADER_INDICATOR=0` hides it.
  Windows over the game must not call synchronous `SetWindowPos` each tick:
  the game window's thread is the present thread, often busy.
- **Car paint, glass (Phase 51).** `LG2` takes `|x|` (`RSX_LG2_ABS=0`): a
  NaN from `log2` of a negative turned whole panels black. The blend
  constant (`0x031C`) reaches D3D12 now (`RSX_BLEND_COLOR=0`): the glass
  blends with it. The dealership alternates car colours per visit; compare
  captures by colour name. `TEXRACE_FP=<fp>` checksums a program's bound
  textures at each draw.
- **Phase 56 (lanes, GPU vertex fetch):** SPU lanes are a per-workload thread
  pool woken by events (`SPURS_LANE_POOL`), the kernel wakes on kicks
  (`SPURS_KERN_WAKE`), idle lanes are pruned, stagger is 1 ms: title-only
  23 to 29 fps. Indexed uploads copy raw guest vertex bytes and the VS decodes
  them (`RSX_VTX_GPU`, `=0` for the CPU path, `=check` to verify): 15.7 to
  17.2 fps with drawing. A triangle list split over records must carry its
  leftover indices (256-index batches): never let a batch become its own
  record without that. `PS3_TIMELINE` + `scripts/diag/tl.py` show what a frame
  waits on; `scripts\test\winshot.ps1` captures the game window at the page.
  Never pipe a run script into `Select-Object -First` (it skipped closing the
  game; the scripts now close it in a `finally`).
- **Phase 57 (cross-frame vertex cache):** vertex streams that repeat from
  frame to frame are copied once into a persistent area of `s_vraw`;
  `RSX_VTXCACHE=0` turns it off, `RSX_VTXCACHE_VERIFY=draw` compares every
  draw. It gives about 19.6 fps. Half of each frame's indexed draws are the
  SPU's output ring, new every frame. `RSX_XFSTAT=1` measures repetition.
- **Phase 58 (present):**
  - per-draw SRV writes the slot already holds are skipped
    (`RSX_SRV_CACHE=0` writes them all);
  - replay and present run on a `present-replay` thread
    (`RSX_PRESENT_THREAD=0`: on the walker).

  The walker records into one `FrameSet` (reached as `FR`) while the thread
  replays the other. Per-frame record state must live in `FrameSet`, never in
  a plain global. That gives 25.1 fps. The frame is now about 8 ms of flip
  wait plus a 30 ms SPU pass; the title alone does 29.3.
  `scripts\test\movshot.ps1` captures the opening movie, and
  `scripts\test\winping.ps1` checks that the window answers messages.
- **Phase 59:** `GT5P_PRESENT_SLEEP` defaults to 1 ms, and lifted SPU code is
  built with `SPU_LS_NO_PROBES` (`-DGT5P_SPU_PROBES=ON` keeps the probes).
  That gives about 30.6 fps at the page. Never evict by shifting a cache that
  others index by slot: the vertex-shader cache (4,096) never evicts, and the
  pipeline cache (8,192, hashed) is emptied whole at a frame start when full.
  Cache sizes print on the `[present-thread]` line.
- **Phase 60 (dealers other than Acura):** they froze on entry. Three
  fixes:
  - a fourth job body (`0x01371A00`) is in `wws_job_bodies`;
  - the FIFO walker no longer abandons an SPU display list parked at its
    write head (`GCM_PARK_RESYNC=1` for the old rule);
  - there are 512 texture slots (`RSX_TEX_SLOTS`).

  Mercedes and Ferrari now run at 22-23 fps. `scripts\test\dealer.ps1 -Moves
  "DOWN,RIGHT,RIGHT,RIGHT,RIGHT" -Enter` is Ferrari. Scripted directions are
  D-pad only (`PAD_HOLD_STICK=1`): the stick doubled every move.
- **Phase 61 (Ferrari):** the cars change per visit, and with them the frame
  rate: 20 to 28 fps. The SPU render pass costs 30.5 to 41 ms of CPU per
  lane, against about 31 ms for 30 fps. `perf.ps1 -Ferrari` saves a window
  shot per run. Changes:
  - the contention byte is stored under the lock line (`SPURS_CONT_COH=0`);
    this was a stall;
  - texture-slot views sit past the per-draw windows;
  - three more job bodies are lifted (`scripts/diag/find_bodies.py`);
  - the vblank runs at 59.94 Hz (`GT5P_VBLANK_HZ`);
  - the walker wakes on the SPU write it waits for (`GCM_WALK_WAKE=0`).

  `SPURS_JL_SPU3`, `SPURS_LANE_CPUS` and `SPURS_LANE_STAGGER_US` are
  experiments that stall; leave them off.
- **Phase 62 (SPU runtime):** the bookkeeping around lifted SPU code has
  fast paths behind `g_spu_fast` (`SPU_FAST=0` for the old ones): render
  lanes need 1.15 times less CPU, and Ferrari runs at a median 25 fps.
  - Measure SPU changes within one boot: `SPU_FAST_AB=1 SPURS_LANE_CYC=1`,
    then `scripts/diag/abcyc.py`. Across boots the car pair changes the numbers
    more than any change does.
  - Profile with `GT5P_SAMPLE=all GT5P_SAMPLE_GRAIN=16 GT5P_SAMPLE_TOP=1500`
    and `scripts/diag/lanesum.py`; 256-byte buckets misname functions.
  - The SPU lifter turns `ila $rN,X; bi $rN` into a direct transfer
    (`SPU_LIFT_CONST_BI=0` at lift time to stop).
- **Phase 63:**
  - Render lanes pinned to their own cores run 1.14 times faster
    (`SPURS_LANE_PIN=2`, "SPU lanes on own cores" in settings), but the
    dealer page then freezes about 1 visit in 5. It stays off.
  - `GT5P_STALL_DUMP` (on) prints threads, workloads, lanes and the FIFO
    walker 3 s and 8 s into any stall.
  - The freezes are the ring-space deadlock (lanes spinning at `0x4560`) or
    a list whose lanes all left with jobs queued; see Phase 63.
- **Phase 64: the dealer-page freeze is fixed** (0 in 20 Ferrari visits).
  - A WWS job list's header names its allowed SPUs at `+0x2F` (the render
    lists say `0xEF`, no SPU 3). Each SPU writes a bookkeeping row at
    `+0x40 + 16 * spuNum` with plain `PUT`s, and SPU 3's is queue 3's
    progress row. Lanes outside the mask are no longer sent
    (`SPURS_LANE_MASK=0` sends them).
  - The SPU coherence registry holds 32 contexts (`SPU_COH_CTX_MAX`); it held
    8 and this title has 17.
  - Lane pinning is the default (`SPURS_LANE_PIN=2` from `src/main.cpp`,
    Strict in settings): Ferrari median 28.2 fps against 24.8, 0 freezes
    in 20. `SPURS_LANE_PIN=0` for the scheduler's placement.
  - `RSX_GPU_TIME` (on): the GPU's time per frame, on `[present-prof]` and in
    F3. `SPU_ROWLOG=<line>,...` logs the writes to a line for the stall dump.
  - The lifter's `stvx`, `stvlx`, `stvrx` and `dcbz` still bypass the
    lock-line lock: suspect them if an SPU line ever loses a PPU write.
- **Phase 65: dealers visited one after another no longer slow down.** The
  pipeline cache thrashed once a 128-entry list of texel-addressed programs
  ran out (`RSX_UNNORM_KEYFIX=0` for the old way). `PSOMISSDBG=2` names the
  key field behind pipeline misses; `scripts\test\revisit.ps1` visits N dealers
  in a row (a 2 s Circle backs out, after any other press on the page).
  - **Shaders not on disk compile on a worker pool** (`RSX_SHADER_ASYNC=1`,
    set by `src/main.cpp`; settings "Precompile shaders", on). Draws wait
    out of the frame meanwhile. An empty cache's first dealer page shows
    within about 3 s instead of over a minute. Test cold with
    `RSX_SHADER_CACHE=<empty dir>`, never by moving `shadercache/`.
    `RSX_PSO_TIMING=1` splits miss time.
  - `RSX_SHADER_ASYNC_HOLD=1` (hold the last full picture) brings Phase
    63's first deadlock shape back in 2 of 3 cold visits: that race is
    still there, only rare.
- **Phase 66 (a track):** with a car bought the menu opens on News under a
  popup; `$ToDealers` in `scripts/test/milestone.ps1` (Circle, hold Right to the
  end, four Lefts, Cross) is the route now, `$DaytonaHold` drives Arcade to
  Daytona. Daytona froze on its logo: a render job the job manager suspended
  at an interrupt point and resumed in a later run returned through
  addresses with no lifted code. The lift now adds resume entries for those
  (`--resume-funcs`, `SPU_RESUME_SEEDS=0` to lift without). Open: the track
  behind the race menus is black, and the race load stops after
  `[ppu] bctr to NULL` calls (Phase 66).
- **Phase 67:** the opening movie played to its end now lets the game go
  on: a demuxer reset is always answered with DEMUX_DONE
  (`DMUX_RESET_DONE=0`), and the video decoder gives a picture per AU
  (`VDEC_IDLE_DRAIN`, `VDEC_EOS_DRAIN`). "Skip opening movie" in settings
  (`PAD_SKIP_MOVIE=MovieRoot`). The game window has its own message thread,
  so dragging or clicking it no longer stops the picture
  (`RSX_WINDOW_THREAD=0` undoes it). The settings page is two columns. A
  stall dump from a game started by hand goes to `logs\stall-*.log`
  (`GT5P_STALL_LOG=0`): ask for that file when someone reports a freeze.
- **Phase 68: the track behind the race menus shows.**
  `SET_VERTEX_DATA3F_M` has a 16-byte slot per attribute; it was decoded
  with 12, so the screen copy's diffuse colour was a UI panel's leftover
  black (`RSX_VDATA3F_STRIDE12=1` for the old decode).
  - Judge a scene 30 s or more after it opens: the pages fade in.
    `RSX_CAP_AFTER=<milestone>,<ms>` captures late.
  - The store watch now takes `PPU_WWATCH_AFTER`, `_REGS` and `_PEEK`
    (`_PEEK_REG`, `_PEEK_DEREF`).
  - The page guard takes `PPU_GUARD_LINE`, `PPU_GUARD_LATE`,
    `PPU_GUARD_SKIP_LR` and `PPU_GUARD_AFTER`. Never arm it from boot on a
    hot page: the menus drop to 11 fps.
  - Open: no ground or track on the starting grid.
- **Phase 69: the race loads and runs (30 fps).** A switch whose table base
  is loaded through a prologue register, behind seeded case starts, lifted
  as an unresolved tail jump. Its function's epilogue never ran, so a render
  thread leaked 0x150 bytes per call and sank into the next thread's stack.
  - The lifter now retries such bases from the real entry. **Re-lift after
    updating ps3recomp.**
  - `PPU_STACK_CHECK=1` and `scripts/diag/spcheck_patch.py` find a leaking
    callee. `[ppu] indirect tail to ...: no lifted entry` names a dropped
    jump.
  - Library callbacks run on the caller's stack (`PPU_CB_SHARED_STACK=1` for
    the old shared one).
- **Phase 70: the race's ground and track draw.**
  - A depth surface wins over a stale colour target at the same address
    (`RT_DEPTH_FIRST=0`).
  - A target is sized no larger than its draws' viewport and scissor
    (`RSX_RT_CAP_VP=0`). The race's 1440-row clip had dropped the depth
    buffer.
- **Phase 71: 1080p antialiasing and softer shadows.**
  - At 1080p the title asks for no antialiasing. The window-sized scene
    target is multisampled anyway (`RSX_MSAA_FORCE=0` to stop).
  - Shadow compares average four 2x2 compares (`RSX_SHADOW_SOFT=0`).
  - The pit crew's bind pose is open: motions load and `CMotionEx` runs,
    but the SPU skins with bind-pose matrices.
- **Phase 72: the pit crew animate.** The SPU skinning never ran.
  - The SPU lifter's `bisl $r0, $r0` wrote the link before reading the
    target (`SPU_LIFT_BISL_LINKFIRST=1` at lift time for the old order).
  - Indirect branch targets now drop their two low bits, as the hardware
    does (`SPU_BI_LOWBITS=1` keeps them).
  - `lift_spu_jobs.py` seeds the targets of absolute code-address tables
    (`SPU_ABS_TABLES=0` without).
  - **Re-lift the SPU code after updating ps3recomp.**
  - `SPU_DMA_RANGE_HIST` shows a job's inputs.
  - Open, left at the user's request: the menu's black slabs after the
    Race Mode page, and the menu's trees reflected on the dealer floor
    (`scripts/test/roundtrip.ps1 -Pit`).
- Next, as of Phase 72 (the user's own order is under "Start here"):
  - the texture-load warning;
  - the menu after the Race Mode page, and the dealer reflection;
  - re-check the Kyoto slabs and the loading-screen text.

  Then the older items, none re-measured since the phase named:
  - the 30 fps plan, `docs/plan-30fps.md`. Phase 55 put the title's ceiling
    in the SPU job pipeline, so step 5b and the job lists' critical path
    are next;
  - Ferrari-class dealer pages at 20 to 28 fps (Phase 61);
  - the floor reflection (46.4);
  - the dim 2D layer (Phase 37);
  - texture units 4 and up in fragment programs;
  - sound in a race, which has more voices than the menu;
  - the audio thread's 14 to 30 ms stalls (Phase 36);
  - the `TV.DAT` install that RPCS3 starts about 20 s after `BootRoot.gpb`.

Diagnostics added for this: `GT5P_THREADS=1` (every guest thread and held
mutex with each main-thread sample), `PS3_SYNCLOG=1` (failed locks, with the
lock object), `PS3_LWM_CHECK=1` (two threads inside one lightweight mutex).
`PS3_LWM_TRACE=<guest address>` logs acquisition and release order for one
guest lwmutex (see Phase 32); it filters out main-thread events to preserve
space for other guest threads.
For the job manager: `SPURS_PM_TRACE=1` (each policy-module run and how it
ended), `SPURS_PM_FLOW=1 SPURS_PM_FLOW_ALL=1` (the control-flow trail of a run
still going after 5 s; add `SPURS_PM_FLOW_FREEZE=<hex pc>` to keep the
transfers around one address), `SPU_DUMP_OVL=<existing dir>,0x4000` (each job body the
module streams in). Do not set `SPU_ATOM_EA`: it ignores its line cap and wrote
1.8 GB in 30 s.

Build note: `GT5P_*` compile definitions are scoped to `src/main.cpp`. Do not
put a definition on the whole `gt5p` target; changing one recompiles all ten
lifted chunks at once and exhausts memory. If a full rebuild is needed, set
`CMAKE_BUILD_PARALLEL_LEVEL=4` first.

The ps3recomp checkout at `../ps3recomp-gt5p-master` carries local, uncommitted
changes in 63 files under `include/`, `libs/`, `runtime/` and `tools/` (2026-10-20). The disc build does not
boot without the ones in `libs/spurs/cellSpurs.c`, `libs/system/cellGame.c`
`runtime/syscalls/lv2_register.c` and `libs/video/cellGcmSys.*`, and `src/main.cpp` no longer compiles
without the ones in `runtime/syscalls/sys_ppu_thread.*`.
A copy is kept in `patches/ps3recomp-5244db9-local.patch`; refresh it after any
further change there, and do not reset that checkout without it.

### RPCS3 as a reference

RPCS3 (install path in `AGENTS.local.md`) runs this build, and its log
is the reference for what a correct boot does.

- Boot: `rpcs3.exe --no-gui "<dump>\PS3_GAME\USRDIR\EBOOT.BIN"`. A game window
  opens. The first boot compiles for about four minutes before the game starts.
- The log is `log\RPCS3.log`. RPCS3 locks it while running; close RPCS3 first.
- `python scripts/rpcs3log.py <log> --copy scratch/rpcs3.log` summarises it.
- RPCS3 is GPLv2. Read it and its logs to learn behaviour; do not copy its code
  into this repo or into ps3recomp.
- RPCS3's hard disk now holds the game's own install at
  `dev_hdd0\game\BCUS98158` (4,345 files, 4.0 GB, possibly incomplete),
  including a `PDIPFS` tree.

Useful commands:

- `python scripts/soak.py 6 40` runs six boots and prints counts per run.
- `python scripts/boot.py 40 NAME=VALUE ...` runs one boot and summarises the
  log. `PS3_HLE_TRACE=200000 PS3_SCTRACE=1` traces imports and syscalls.
- `python scripts/cdis.py 0xADDR` disassembles a function.
- On a crash the port prints the faulting thread's guest call chain and
  registers.

## Plan

Steps 1 to 5 have been done once; step 6 is where the work is.

1. **Get a plain ELF.** Done: `input/disc/USRDIR/EMAIN.elf`.
2. **Measure the gap.** Done.
3. **Load it into Ghidra** and build the function database. Use it to locate the
   disc-build counterparts of the v02.00 functions the patches depend on.
4. **Re-derive the build-specific inputs** in the table above, one at a time.
   Do not carry a v02.00 address across without confirming the function at the
   new address is the same code.
5. **Lift, patch and build** with the README pipeline, using the new values.
6. **Compare boot behaviour** with upstream's milestone: 116 PDIPFS assets,
   deterministic across runs (`bash scripts/soak.sh 8 40`).

Keep disc-build values separate from upstream's so the fork can still merge from
`upstream`. Prefer new config files or parameters over editing v02.00 values in
place.

## Per-build constants

Addresses and boot settings that belong to one executable live in
[config/targets.json](config/targets.json), keyed by title id. Add a new
build-specific value there, not in a script or source file.

- Scripts read it through [scripts/target.py](scripts/target.py). The build in
  use is `GT5P_TARGET`, else the first line of `input/target`, else `NPUA80075`.
  On this machine `input/target` says `BCUS98158`.
- CMake reads the same file. Pass the build explicitly:
  `scripts\build.cmd -DGT5P_TARGET=BCUS98158`.
- `scripts/jumptables.py --write`, `scripts/setjmp_patch.py` and
  `scripts/lift_spu_jobs.py` follow the target. `lift_spu_jobs.py` also cuts the
  policy module out of the executable and lifts it.
- `scripts/find_setjmp.py` locates the guest `setjmp`/`longjmp` by instruction
  shape, for a build where their addresses are not known.

Layout this machine uses for the disc build:

- `input/EMAIN.ELF` is the decrypted disc executable.
- `input/pkg/` holds `PARAM.SFO` and `USRDIR/`. The large files in `USRDIR` are
  NTFS hard links to the dump, not copies. Deleting them is safe; writing to
  them changes the dump.
- `../ps3recomp` is a junction to `../ps3recomp-gt5p-master`, because several
  scripts look for the toolkit under that name.

## Tools

### In this repo

Run Python through the repo's virtual environment: `.venv\Scripts\python`.

| Script | Purpose |
| --- | --- |
| `scripts/build.cmd` | Configure and build Release with clang-cl and Ninja |
| `scripts/self_metainfo.py`, `scripts/decrypt_self.py` | SELF decryption helpers; need a `data/keys` file that is not in the repo |
| `scripts/setjmp_patch.py` | Post-lift patch, required after every lift |
| `scripts/spin_patch.py` | Post-lift patch, required after every lift: guest spin waits on SPU progress yield (`spin_waits` in `config/targets.json`) |
| `scripts/ui_mask_patch.py` | Post-lift patch, required after every lift: menu label fade mask centred in ultrawide (`ui_label_mask_func`; `GT5P_UI_MASK_FIX=0` off) |
| `scripts/spu_native_patch.py` | Post-SPU-lift patch, required: hooks native replacements (`src/gt5p_spu_native.c`) into lifted SPU blocks (`spu_native_hooks`); `GT5P_SPU_NATIVE=0` off, `=2` check |
| `scripts/lift_spu_jobs.py` | Lift the policy module, the captured job images and the job bodies; writes `src/gen/spu_workloads_bcus98158.c` |
| `scripts/soak.sh`, `soak.py`, `boot.py` | Repeated or single headless boots with a summary |
| `scripts/test/*.ps1` | Drive the game to a page and measure or shoot it (table under "Start here") |
| `scripts/diag/*.py` | Log readers, call-count instrumenters, RenderDoc scripts (under "Start here") |
| `scripts/dis.py`, `cdis.py`, `xref.py`, `vtab.py`, `rtti.py`, `jumptables.py` | Static analysis helpers over the ELF (`cdis.py 0xADDR` disassembles a function, `xref.py 0xADDR` lists callers, `vtab.py 0xVTABLE` lists slots) |
| `scripts/audit_branch.py`, `audit_cmp.py`, `bbcount.py` | Lifter audits and basic-block counting |

### ps3recomp

Checked out at `../ps3recomp-gt5p-master`, on `master`. The README was tested at
commit `795ac34`; if a build misbehaves, check that commit out before debugging
anything else. `scripts/build.cmd` finds it by that path, or set `PS3RECOMP_DIR`.

Its `tools/` folder holds `pkg_extract.py`, `elf_parser.py`,
`find_functions.py`, `ppu_lifter.py` and `gen_hle_nids.py`.

### RPCS3

Used for decryption only: **Utilities > Decrypt PS3 Binaries**. It writes a
`.elf` next to the file it was given. This replaces the `ps3sce` step in the
README, which needs a tool with no prebuilt Windows release and a keys file.
Upstream validated its pipeline with `ps3sce`, not RPCS3, so if a lift looks
wrong, suspect the decrypted file first.

### Ghidra

Ghidra 12.1.4 is installed; its path is in `AGENTS.local.md`.
It needs JDK 21, which is at `C:\Program Files\Java\jdk-21.0.4`. The `java` on
PATH is Java 8, so point Ghidra at the JDK 21 folder explicitly.

The target is a 64-bit big-endian PowerPC ELF. Keep the Ghidra project outside
the repo, or under a gitignored folder such as `analysis/`.

### REA

[morluto/rea](https://github.com/morluto/rea) is an MCP server and CLI that lets
an agent drive a reverse-engineering backend, here Ghidra, and returns findings
with their evidence.

- Installed globally as `rea` (6.4.0, `npm install --global rea-agents`) and
  registered with Claude Code as the `rea` MCP server in `~/.claude.json`. Its
  skill, `reverse-engineer-anything`, is in `~/.claude/skills/`.
- The server entry sets `JAVA_HOME` (JDK 21) and `GHIDRA_INSTALL_DIR`. When
  running `rea` from a terminal, set `JAVA_HOME` to the JDK 21 folder first,
  because the default `java` is Java 8 and REA rejects it.
- Check health with `rea doctor --client claude_code --provider ghidra` and
  `rea mcp doctor`.
- On Windows the Ghidra provider is read-only: REA reports that it does not
  allow database changes such as renaming or annotating. Do those in the Ghidra
  GUI.

Use REA for questions about the binary: what a function does, who calls it,
where a value comes from. Use the ps3recomp tools for anything that feeds the
lift, so the pipeline's inputs stay reproducible from scripts.

### Build toolchain

Visual Studio 2022 Community (C++ workload), LLVM 23 at `C:\Program Files\LLVM`,
CMake, Ninja, Python 3.13. All installed. `scripts/build.cmd` hard-codes the
Visual Studio and LLVM paths.

## Working rules

- **Measure before concluding.** The upstream log records that structural
  readings of lifted code were wrong far more often than the measurements under
  them. Before stating a conclusion, run the command that would falsify it.
  Label anything untested as a hypothesis in the text itself.
- **Set `PS3_VERBOSE=0` when a number matters.** Verbose logging serialises every
  guest thread on one lock and changes what the title does.
- **Use `PS3_HEADLESS=1`** for automated runs.
- **Host backtraces mis-attribute frames.** Do not treat a repeated function in
  a backtrace as a finding.
- **Record findings** in [docs/progress.md](docs/progress.md), newest phase
  first, leaving earlier readings in place when later ones correct them.

## What must never be committed

No game data, keys, decrypted executables or generated source. `.gitignore`
already covers `input/`, `generated/`, `analysis/`, `data/keys`, `build/` and the
game file extensions. Ghidra databases and decompiler output derived from the
game binary belong in those ignored folders too. Do not paste decompiled game
code into tracked files; describe behaviour and cite addresses.

This is enforced, not just asked for:

- `scripts/check_no_game_files.py` refuses files by name, extension, directory,
  size and magic bytes, so a renamed or force-added game file is still caught.
- `.githooks/pre-commit` runs it on every commit. Enable it once per clone with
  `git config core.hooksPath .githooks`. It is enabled on this machine.
- `.github/workflows/no-game-files.yml` runs it on GitHub for every push.
- Never bypass it with `git commit --no-verify` or `git add -f`. If it refuses a
  file that is legitimately ours, change the rule in the script and say why.
