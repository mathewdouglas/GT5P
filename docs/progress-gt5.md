# Gran Turismo 5 (BCUS98114) bring-up

This log records measurements for the retail US disc build of Gran Turismo 5,
separately from both GT5 Prologue targets. The working branch is `gt5`.
Machine-specific dump and RPCS3 paths are in the ignored `AGENTS.local.md`.

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
