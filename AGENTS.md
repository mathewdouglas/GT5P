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

As of 2026-10-12 the disc build lifts, compiles, boots and issues frames.
Details and evidence are in Phases 17 to 41 of
[docs/progress.md](docs/progress.md); read 41 down to 19 in that order.
Each corrects the one before.

- **A save exists now, so the title boots straight to the main menu**
  (no agreement, no "Confirmation"). `scratch/menu.ps1` scrolls an
  agreement that is no longer shown; with the save, drive the dealership
  with `scratch\inp.ps1 90 "PAD_HOLD=28000-28300:CROSS,34000-34300:CROSS,46000-46300:CROSS"`.
  Move `gamedata/dev_hdd0` aside to get the first-boot screens back.
- **Choosing a manufacturer: frames run, the picture stays the logo
  (Phases 39-40).** The render jobs now run on five virtual SPUs, their
  blocks in the display list are waited for (`0xFFFFFFFF` = not filled yet)
  and drawn, and frames continue at about 10 a second. The title then draws
  only its environment and reflection passes. It loads the same files as
  RPCS3 (Phase 41), so it is not waiting on data; what it waits on is open.
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
  `build\gt5p.exe`. The exe finds the project root by looking for
  `input\EMAIN.ELF` upwards from its own folder (`GT5P_ROOT` to name it),
  turns verbose logging off when its output is a console, and exits when
  the window is closed. Keyboard: arrows, Z Cross, X Circle, A Square,
  S Triangle, Q/W L1/R1, 1/2 L2/R2, Enter Start, Tab Select.
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
  `SPURS_JC_SAMPLE=<chain>` with `scratch/maplook.py` and a `/MAP` link
  (where the walker's time goes).
- **Do not launch with `GT5P_MAINSTACK` set when judging sound or smoothness.**
  It suspends guest threads every N seconds; `scratch/inp.ps1` used to set
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
  and look for a fill pass larger than its dry run (`scratch/ab.py` counts
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
- `scratch/inp.ps1 <secs>` runs a windowed boot for someone to drive, with a
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
- Next: what the dealership waits for once its files are loaded (Phase 41); the dim 2D layer (Phase 37); texture units 4 and up; sound in a race, which has more
  voices than the menu; the main thread's 93% of a core at 31 frames a
  second; why the title's audio thread still stalls 14 to 30 ms (Phase 36); the
  dealership, not re-examined since Phase 33 beyond seeing it draw text on
  black at 25 frames a second without freezing; immediate-mode strips and
  fans, which are still dropped. Then which per-SPU counter the dealership's
  render thread waits on (Phase 31), and the `TV.DAT` install RPCS3 starts
  about 20 s after `BootRoot.gpb`.

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
changes in thirty-five files under `libs/`, `runtime/` and `tools/`. The disc build does not
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
| `scripts/lift_spu_jobs.py` | Lift captured SPU jobs |
| `scripts/soak.sh` | Repeated headless boots; prints assets loaded per run |
| `scripts/dis.py`, `xref.py`, `vtab.py`, `rtti.py`, `jumptables.py` | Static analysis helpers over the ELF |
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
