# Gran Turismo 5 Prologue Recompiled

**The demo that was better than most finished games.**

In 2007 Polyphony Digital shipped a *prologue* — a paid, standalone slice of a
game that would not arrive for another three and a half years. Six tracks,
seventy-one cars, and a rendering pipeline that made a 2006 console look like it
had no business being that fast. It ran at 1080p. In 2008. People bought a demo
and did not feel short-changed, which is not a sentence anybody gets to write
twice.

Then it went away. GT5 Prologue was delisted, its online services were shut down
in 2013, and the PS3 store that sold it is on life support. What is left is a
1.9 GB package sitting on people's hard drives with no hardware that will
outlive them.

## Why This Exists

**Gran Turismo 5 Prologue Recompiled** is a native PC port built with
[ps3recomp](https://github.com/sp00nznet/ps3recomp) — a static recompilation
toolchain that translates PS3 PowerPC binaries into C, then compiles that into an
x86-64 executable. No emulator at runtime. No dynamic translation. The game's own
code, compiled for your machine.

This one is a step up from every ps3recomp target so far. GT5P is a full retail
engine: 42,316 lifted PPU functions, 439 imported system calls across 26 modules, an
RSX pipeline built by the studio that cared most about it, and Polyphony's own
packed filesystem holding 1.8 GB of assets. Tokyo Jungle, the previous most
complex target, is 7,924 functions.

## Status

**Pre-alpha. It boots and loads its own content. It does not draw a frame yet.**

| Area | State |
|---|---|
| PKG / SELF decrypt | Done — RAP-derived key, validated byte for byte |
| PPU lift | 42,316 functions, clean compile; one post-lift patch (`setjmp_patch.py`) |
| SPU | 12 images lifted and registered; SPURS job chains dispatch with 0 misses |
| Boot | Deterministic: **116 PDIPFS assets, 8 of 8 runs** |
| Graphics | D3D12 up; tiles, Zcull, display buffers and one prepare-flip. No command buffer submitted, no frame |
| Audio / input / menus | Not reached |

Latest phase (2026-09-28): rebuilding on current ps3recomp `master` took the boot
from a random 7–108 assets to a fixed 116, and past the heap spin that held it
since August. Main now waits somewhere new, not yet characterised. The full
investigation, phase by phase, is in [docs/progress.md](docs/progress.md); what
comes next is in [ROADMAP.md](ROADMAP.md); versions in [CHANGELOG.md](CHANGELOG.md).

## This fork: the disc build

This is a fork of [sp00nznet/GT5P](https://github.com/sp00nznet/GT5P). Upstream
targets the US PSN release, NPUA80075 v02.00. This fork adds a second target,
the **US disc release, BCUS98158 v03.00**, which is a different executable:
more code, more imports, and a single `GT.VOL` volume in place of the `PDIPFS`
tree. Everything above and below this section still describes NPUA80075 unless
it says otherwise.

**Disc build status: pre-alpha. It loads its start-up assets and then waits. It
does not draw a frame, and the boot is not yet the same on every run.**

| Area | NPUA80075 v02.00 | BCUS98158 v03.00 |
|---|---|---|
| Decrypt | RAP-derived key, `ps3sce` | RPCS3 `--decrypt`, no RAP needed |
| PPU lift | 42,316 functions | 50,075 functions, clean compile |
| Imports | 439 across 26 modules | 565 across 31 modules |
| SPU | 12 images | Policy module and 12 job images, 0 dispatch misses |
| Boot | 116 `PDIPFS` assets, 8 of 8 runs | 127 `GT.VOL` opens in 12 of 14 runs; 2 deadlock after 40 |
| Where main stops | `sys_cond_wait` | `sys_cond_wait` in the good runs |
| Graphics, audio, input | Not reached | Audio port opened, pad polled, flips cycle; no frame |

In the good runs the disc build's file activity matches an RPCS3 boot of the
same disc through about the first 11 seconds of game time: the same 24 paths in
the same order. The two builds' asset counts are not comparable, because one
counts distinct files and the other counts opens of one volume.

What the disc build needs that upstream does not:

- **Per-build constants.** Every address and boot setting that belongs to one
  executable is in [config/targets.json](config/targets.json), read by the
  scripts through `scripts/target.py` and by CMake. Select a build with
  `GT5P_TARGET`, or by writing its title id to `input/target`; the default is
  NPUA80075, so upstream's flow is unchanged.
- **Local ps3recomp changes.** The disc build does not boot on stock ps3recomp.
  The changes are in
  [patches/ps3recomp-5244db9-local.patch](patches/ps3recomp-5244db9-local.patch),
  against ps3recomp `5244db9`: per-instance SPURS event ports, a per-pass job
  index, a switch for the runtime's stand-in job-completion event, and a
  game-data check that reports new data truthfully. They have not been sent to
  ps3recomp.

Building the disc build, from a dump of your own disc:

```bash
T=../ps3recomp-gt5p-master/tools
git -C ../ps3recomp-gt5p-master apply ../GT5P/patches/ps3recomp-5244db9-local.patch
rpcs3 --decrypt <dump>/PS3_GAME/USRDIR/EMAIN.SELF     # writes EMAIN.elf beside it
cp <dump>/PS3_GAME/USRDIR/EMAIN.elf input/EMAIN.ELF
mkdir -p input/pkg && cp -r <dump>/PS3_GAME/PARAM.SFO <dump>/PS3_GAME/USRDIR input/pkg/
echo BCUS98158 > input/target

python scripts/jumptables.py --write        # config/extra_seeds_bcus98158.json
python $T/find_functions.py input/EMAIN.ELF --json --seed-json config/extra_seeds_bcus98158.json --output analysis/functions.json
python -c "import json; f=json.load(open('analysis/functions.json')); json.dump([x for x in f if int(x['start'],16) < 0xE3EC24], open('analysis/functions_code.json','w'))"
PYTHONPATH=$T python scripts/gen_hle_stubs.py input/EMAIN.ELF analysis/hle_stubs.json
python $T/ppu_lifter.py input/EMAIN.ELF --functions analysis/functions_code.json --output generated --code-end 0xE3EC24 --header-name ppu_recomp.h --source-name ppu_recomp.c --hle-stubs analysis/hle_stubs.json
python scripts/setjmp_patch.py
python $T/gen_hle_nids.py --all --out src/gen/ppu_hle_nids.cpp
scripts/build.cmd -DGT5P_TARGET=BCUS98158
```

The SPU registry for the disc build is committed
(`src/gen/spu_workloads_bcus98158.c`), but the lifted SPU sources are not, as
with everything under `generated/`. To produce them, build once, run with
`SPU_DUMP_MISS=analysis/spu/dump` to capture the job images, then run
`python scripts/lift_spu_jobs.py` and rebuild.

Tools added for this work:

| Command | What it does |
|---|---|
| `python scripts/soak.py 8 40` | 8 headless boots of 40 s; one line of counts per run. Works for either build |
| `python scripts/boot.py 40 NAME=VALUE` | One boot with a log summary; extra arguments set the game's environment |
| `python scripts/threads.py` | What each guest thread was last doing, from a boot log |
| `python scripts/cdis.py 0xADDR` | Full disassembly of a function |
| `python scripts/find_setjmp.py` | Locate the guest `setjmp`/`longjmp` in a build where they are unknown |
| `python scripts/rpcs3log.py RPCS3.log` | Summarise an RPCS3 log for comparison against a port run |

The investigation is Phase 17 of [docs/progress.md](docs/progress.md), and
[AGENTS.md](AGENTS.md) is the working brief for the disc build.

## Screenshots

None yet — the title has not presented a frame. This section gets real output
the day it does.

## Getting Started

You need your own copy of the game: the NPUA80075 PSN package and its `.rap`.
Nothing from the game is in this repository, and generated source is never
distributed — you lift it yourself, locally, into the gitignored `generated/`.

**Prerequisites:** Windows 10/11 x64, Visual Studio 2022 (C++ workload), LLVM
18+ (`clang-cl`), CMake 3.20+, Ninja, Python 3.10+, `ps3sce` or scetool, and a
[ps3recomp](https://github.com/sp00nznet/ps3recomp) checkout next to this repo
at `../ps3recomp-gt5p-master` on `master` (tested at `795ac34`).

1. `pip install -r requirements.txt`
2. Unpack the package:
   `python ../ps3recomp-gt5p-master/tools/pkg_extract.py your.pkg input/pkg`
3. Decrypt the game SELF:
   ```bash
   MI=$(python scripts/self_metainfo.py input/pkg/USRDIR/EMAIN.SELF your.rap)
   ps3sce -m $MI -d input/pkg/USRDIR/EMAIN.SELF input/EMAIN.ELF
   ```
4. Analyse, lift and patch — see [Building from source](#building-from-source).
5. `scripts/build.cmd`
6. `PS3_HEADLESS=1 PS3_VERBOSE=0 build/gt5p.exe`

Expected today: the log shows `[cellFs] Open(path=...PDIPFS...)` lines — 116
distinct files — SPURS job-chain traffic, then the boot waits. No window
content yet.

## Usage

| Command | What it does |
|---|---|
| `build/gt5p.exe` | Boot with a D3D12 window |
| `PS3_HEADLESS=1 build/gt5p.exe` | No window; vblank/flip clock and FIFO drain still run. Use over RDP |
| `bash scripts/soak.sh 8 40` | 8 headless boots of 40 s; prints unique PDIPFS assets per run |
| `GT5P_MAINSTACK=30 build/gt5p.exe` | After 30 s, print where the main thread is |

Always set `PS3_VERBOSE=0` when a number matters: verbose logging serialises
every guest thread on one stderr lock and changes what the title does.

**Settings.** Press **F1** in the game (or the PS button on a PlayStation
controller) for the settings page: arrows or the d-pad to choose, Left/Right or
Cross to change, Esc or Circle to close. Changes are saved at once; vsync and
the keyboard-as-controller switch apply immediately, the rest after a restart,
which the page offers. The settings live in `gt5p_settings.toml` beside the
game (the folder with `input\EMAIN.ELF`), written on the first start with a
comment on each: resolution (720p or 1080p), antialiasing, vsync, the shader
cache, the shader indicator, controllers and the keyboard. You can also edit
it by hand and restart.

While the game builds shaders the picture stops for a moment (several seconds
the first time a screen is seen); a "Compiling shaders" badge in the corner
says so. It can be turned off on the settings page. An environment variable for the same switch (shown in the file's
comments) wins over it; delete the file to get the defaults back.
`GT5P_SETTINGS=<path>` names another file, and `GT5P_NO_SETTINGS=1` ignores it,
as `scripts/boot.py` and `scripts/soak.py` do.

**Movies.** The opening movie is decoded with FFmpeg, loaded at run time. Run
`scripts\get_ffmpeg.ps1` once (it fetches a pinned LGPL build into
`third_party\ffmpeg`), then rebuild; without it movies play black and silent.
The movie itself is part of the game's TV content, which the title installs to
its hard-disk folder (`gamedata\dev_hdd0\game\BCUS98158\USRDIR\grim\file\contents`).
This port does not yet perform that install; copy it from an RPCS3 install of
the same game.

## Building from source

```bash
T=../ps3recomp-gt5p-master/tools
python $T/elf_parser.py     input/EMAIN.ELF --imports > analysis/imports.json
python $T/find_functions.py input/EMAIN.ELF --json     --seed-json config/extra_seeds.json --output analysis/functions.json
# drop the .rodata find_functions mistook for code
python -c "import json; f=json.load(open('analysis/functions.json'));   json.dump([x for x in f if int(x['start'],16) < 0xBE0AF4], open('analysis/functions_code.json','w'))"
python $T/ppu_lifter.py input/EMAIN.ELF --functions analysis/functions_code.json     --output generated --code-end 0xBE0AF4 --header-name ppu_recomp.h     --source-name ppu_recomp.c --hle-stubs analysis/hle_stubs.json
python scripts/setjmp_patch.py              # required after every lift
python $T/gen_hle_nids.py --all --out src/gen/ppu_hle_nids.cpp
scripts/build.cmd
```

`0xBE0AF4` is the end of the last executable section; the R-X segment runs
3.6 MB past it into read-only data. `setjmp_patch.py` makes the guest `longjmp`
actually jump — without it the LZ decoder never terminates (Phase 15 in
[docs/progress.md](docs/progress.md)). SPU jobs the runtime does not recognise
are captured with `SPU_DUMP_MISS=analysis/spu/dump build/gt5p.exe`, then
`python scripts/lift_spu_jobs.py` and rebuild.

`scripts/build.cmd` sources `vcvars64.bat` and builds Release with clang-cl +
Ninja. Set `PS3RECOMP_DIR` to build against a different toolkit checkout.

## How It Works

```
NPUA80075.pkg
    | pkg_extract.py           (finalized PKG, AES-128-CTR)
EBOOT.BIN + EMAIN.SELF + PDIPFS
    | self_metainfo.py         (RAP -> klicensee -> metadata key)
    | ps3sce --meta-info -d    (segment decrypt + ELF rebuild)
EMAIN.ELF - PowerPC64 big-endian
    | find_functions.py / ppu_disasm.py / ppu_lifter.py
Generated C++ (thousands of files)
    | clang-cl / MSVC
Native x86-64 executable
    + ps3recomp runtime (HLE OS services)
    + Graphics backend (RSX -> D3D12)
```


## Game IDs

| Region | ID | Format |
|--------|----|--------|
| NA (Digital) | NPUA80075 | PSN |
| NA (Disc) | BCUS98158 | Blu-ray |
| EU (Disc) | BCES00071 | Blu-ray |
| JP (Disc) | BCJS30017 | Blu-ray |

This port targets the **US PSN build, NPUA80075 v02.00** (`PS3_SYSTEM_VER 02.1500`).


## License

The code in this repository is MIT licensed — see [LICENSE](LICENSE). That covers
*our* code only: the port scaffold, tooling and build scripts. It does not and
cannot cover Gran Turismo 5 Prologue itself, and no game data is included here.

## Legal

This repository holds the port's own code and tooling. It contains no proprietary
Sony or Polyphony Digital code, no game assets, and no decryption keys. You must
provide your own legally obtained copy. It exists for game preservation.

This fork checks that mechanically. `scripts/check_no_game_files.py` refuses game
files by name, extension, size and content; it runs as a commit hook (enable it
with `git config core.hooksPath .githooks`) and on GitHub for every push.

**Gran Turismo** is a trademark of Sony Interactive Entertainment. This project is
not affiliated with, endorsed by, or connected to Sony or Polyphony Digital in any
way.

---

*Built with [ps3recomp](https://github.com/sp00nznet/ps3recomp)*
