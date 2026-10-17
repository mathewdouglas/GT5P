# Gran Turismo 5 (BCUS98114) bring-up

This log records measurements for the retail US disc build of Gran Turismo 5,
separately from both GT5 Prologue targets. The working branch is `gt5`.
Machine-specific dump and RPCS3 paths are in the ignored `AGENTS.local.md`.

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
