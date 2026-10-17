# Gran Turismo 5 (BCUS98114) bring-up

This log records measurements for the retail US disc build of Gran Turismo 5,
separately from both GT5 Prologue targets. The working branch is `gt5`.
Machine-specific dump and RPCS3 paths are in the ignored `AGENTS.local.md`.

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

### State

No lifting, build or boot has been attempted. `code_end` is provisional;
function seeds, `setjmp`/`longjmp`, SPU policy/job images, target-specific
runtime behavior and the game's use of `GT.VOL`/`MOVIE` remain unmeasured.
