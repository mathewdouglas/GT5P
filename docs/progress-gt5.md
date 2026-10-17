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

The target's SPU policy image was lifted from `0x0177F200` (11,648 bytes,
190 discovered functions). No runtime job bodies have been captured yet; the
registry contains only the policy module.

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
