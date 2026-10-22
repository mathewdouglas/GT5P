# Gran Turismo 5 (BCUS98114) bring-up

This log records measurements for the retail US disc build of Gran Turismo 5,
separately from both GT5 Prologue targets. The working branch is `gt5`.
Machine-specific dump and RPCS3 paths are in the ignored `AGENTS.local.md`.

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
