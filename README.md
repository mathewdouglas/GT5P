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

*This section is upstream's PSN build (NPUA80075), as last measured on
2026-09-28. This fork's disc build (BCUS98158) is much further along: it runs
from the menus into a race. See [This fork: the disc build](#this-fork-the-disc-build).*

**NPUA80075: pre-alpha. It boots and loads its own content. It does not draw a frame yet.**

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

**Disc build status (2026-10-18, Phase 80): playable from the menus into a
race.** It boots to the main menu, the dealerships draw, and Arcade reaches
Daytona's Race Mode page with an animated pit crew. A Single Race loads and
drives. Dealerships run at about 22 to 30 fps; steady 60 fps in races remains
open. The race-start freeze and the 1080p
menu's black tree rectangles are fixed. MSAA depth now reaches depth of
field, the crowd has coloured spectators, and race textures have more cache
capacity. High Speed Ring's road filtering and cars appearing over the bridge
are fixed, and native pipeline compilation is cached between sessions.
Distant scenery now uses its mip chain to reduce grain, and loading-screen
car names no longer lose glyph parts or show solid blocks.
The rest of this section and
[AGENTS.md](AGENTS.md) ("Start here") give the details and what is open.

| Area | NPUA80075 v02.00 | BCUS98158 v03.00 |
|---|---|---|
| Decrypt | RAP-derived key, `ps3sce` | RPCS3 `--decrypt`, no RAP needed |
| PPU lift | 42,316 functions | 50,065 functions, clean compile |
| Imports | 439 across 26 modules | 565 across 31 modules |
| SPU | 12 images | Policy module, 12 job images and 7 job bodies (9,115 functions), 0 dispatch misses |
| Boot | 116 `PDIPFS` assets, 8 of 8 runs | Main menu in about 14 s |
| Graphics | Not reached | D3D12: menus, dealer showroom, pit, race; MSAA, shadow maps, sRGB, cube maps |
| Audio, input, video | Not reached | Menu music; pads through SDL2, XInput or the keyboard; the opening movie through FFmpeg |

Settings (resolution, MSAA, vsync and more) are in `gt5p_settings.toml` at
the root and on an in-game page (F1). F3 shows a profiler.

The table above this section is upstream's and still describes NPUA80075.

What the disc build needs that upstream does not:

- **Per-build constants.** Every address and boot setting that belongs to one
  executable is in [config/targets.json](config/targets.json), read by the
  scripts through `scripts/target.py` and by CMake. Select a build with
  `GT5P_TARGET`, or by writing its title id to `input/target`; the default is
  NPUA80075, so upstream's flow is unchanged.
- **Local ps3recomp changes.** The disc build does not boot on stock ps3recomp.
  The changes are in
  [patches/ps3recomp-5244db9-local.patch](patches/ps3recomp-5244db9-local.patch),
  against ps3recomp `5244db9`. They touch 58 files and cover:
  - SPURS and the job manager;
  - the PPU and SPU lifters (jump tables, `bisl`, vector stores);
  - the D3D12 RSX backend (render targets, MSAA, shadow compares, samplers,
    vertex fetch);
  - cellGcm, cellPad, the codecs, and the diagnostics the progress log
    names.

  Each change has an environment switch that undoes it. They have not been
  sent to ps3recomp.

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
`python scripts/lift_spu_jobs.py` and rebuild. The job bodies come straight
from the executable (`wws_job_bodies` in `config/targets.json`). Re-run both
lifts whenever ps3recomp's lifters change: Phases 69 and 72 fixed lifter
bugs that only a re-lift picks up.

Optional run-time pieces, fetched into `third_party/` (gitignored) and
copied beside the exe by the build:

- `scripts\get_sdl2.ps1`: controllers through SDL2;
- `scripts\get_ffmpeg.ps1`: the opening movie.

Then run `play.cmd`.

Tools added for this work:

| Command | What it does |
|---|---|
| `python scripts/soak.py 8 40` | 8 headless boots of 40 s; one line of counts per run. Works for either build |
| `python scripts/boot.py 40 NAME=VALUE` | One boot with a log summary; extra arguments set the game's environment |
| `scripts\test\*.ps1` | Drive the game by milestones to a page (dealer, pit, race) and shoot or measure it; see [AGENTS.md](AGENTS.md) |
| `scripts\diag\*.py` | Log readers, call-count instrumenters for lifted code, RenderDoc scripts |
| `python scripts/threads.py` | What each guest thread was last doing, from a boot log |
| `python scripts/cdis.py 0xADDR` | Full disassembly of a function |
| `python scripts/find_setjmp.py` | Locate the guest `setjmp`/`longjmp` in a build where they are unknown |
| `python scripts/rpcs3log.py RPCS3.log` | Summarise an RPCS3 log for comparison against a port run |

The investigation is Phases 17 to 76 of [docs/progress.md](docs/progress.md)
(newest first), and [AGENTS.md](AGENTS.md) is the working brief for the disc
build. Its "Start here" section is the current state.

## Screenshots

None are committed: they are pictures of the game's own assets. The disc
build presents frames, from the menus to a race.

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

Controllers can be disconnected and reconnected while playing; SDL device
discovery runs independently of the game's input calls. Windows audio follows
the default output within about half a second and retries if an output becomes
unavailable. Diagnostic overrides: `PAD_HOTPLUG=0` uses polling on the calling
thread; `AUDIO_HOTPLUG=0` keeps the initially opened output.

While the game builds shaders the picture stops for a moment (several seconds
the first time a screen is seen); a "Compiling shaders" badge in the corner
says so. It can be turned off on the settings page. An environment variable for the same switch (shown in the file's
comments) wins over it; delete the file to get the defaults back.
`GT5P_SETTINGS=<path>` names another file, and `GT5P_NO_SETTINGS=1` ignores it,
as `scripts/boot.py` and `scripts/soak.py` do.

**Warming race shaders.** Run `scripts/test/race.ps1 -Track HighSpeedRing
-Tag warm-hsr -Seconds 60` in PowerShell to load the pit and race and populate
the local caches before playing. `-Track Daytona` selects Daytona instead;
append `GT5P_RESOLUTION=1080p RSX_MSAA=2` for that configuration. The helper
closes the game when finished. It warms materials seen during the run; other
cars, views or tracks can still need new shaders on their first appearance.
Add `-IntroShots` to save the race-start transition once per second for
graphics checks; these shots finish before fps sampling begins.
Both shader bytecode and driver-compiled pipelines are cached locally.
Driver updates invalidate pipeline blobs safely; rejected entries are rebuilt.
`RSX_PSO_DISK=0` disables the driver cache, and disabling the shader cache in
settings disables both. Keep `shadercache/`; do not download another machine's
pipeline blobs.
Repeated bytecode used by pipeline variants is also retained in memory, up to
64 MiB (`RSX_DXBC_MEM=0` disables that layer). Loading a saved native pipeline
does not count as compiling work on the badge.

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
