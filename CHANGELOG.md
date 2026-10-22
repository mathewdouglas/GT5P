# Changelog

All notable changes to this port. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/). Nothing is tagged yet.

## [Unreleased]

### Disc build (BCUS98158), October 2026: Phases 17 to 72

Summarised here; the evidence is in [docs/progress.md](docs/progress.md).

- A second target, the US disc release. Its per-build constants are in
  `config/targets.json`, and its ps3recomp changes are in `patches/`.
- It boots to the main menu, with the 3D scene, menu music and pads (SDL2,
  XInput, keyboard). The opening movie plays through FFmpeg.
- Dealerships draw, with car materials, shadows and cube maps; the page
  freezes are fixed. Daytona's Race Mode page draws with an animated crew,
  and a race loads and drives. Frame rates run from about 22 to 30 fps.
- A settings file and an in-game settings page (F1), a profiler (F3), and a
  "Compiling shaders" badge. Shaders compile on a worker pool and are
  cached on disk.
- Lifter fixes found on the way, which apply to any title:
  - PPU: `stvlx`, `stvrx`, `lswi`, `stswi` and `vsum4sbs` were lifted as
    no-ops; jump tables behind seeded case starts were dropped.
  - SPU: `bisl $r0,$r0` wrote the link before reading the target;
    indirect branch targets kept their low bits; loop entries reached only
    through an address table were never lifted.
- Test drivers in `scripts/test/` and diagnostics in `scripts/diag/`.

### Changed
- Build against current ps3recomp `master` (`795ac34`) instead of the August
  snapshot branch `wip/gt5p-session-diagnostics`. Every toolkit PR this port
  opened (#97–#112) has since merged. Boot went from a random 7–108 PDIPFS assets
  to **116 in 8 of 8 runs**, and main no longer spins on the 264-byte allocation.
  A/B: the August lift on the new runtime gives 107 in 6 of 6 runs, so the
  runtime removed the nondeterminism and the re-lift (42,316 functions, up from
  40,320) accounts for 107 → 116. Toolkit changes from sibling ports that plausibly
  apply here, none yet shown to be the specific cause: per-thread TLS blocks
  (`cbeae9b`, found by Guitar Hero III), one callee-save snapshot per register in
  the lifter (`135b95a`, GH3), dropped NULL-page stores (`7228188`, GH3).
- `src/gen/ppu_hle_nids.cpp` regenerated from the toolkit under build (`--all`,
  1,094 handlers).
- README restructured to the house order; the phase-by-phase investigation moved
  to `docs/progress.md`.

### Added
- `PS3_HEADLESS=1`: no window, but the vblank/flip clock and FIFO drain still run.
  For RDP and unattended runs.
- `scripts/soak.sh`: N headless boots, unique PDIPFS assets per run.
- `ROADMAP.md`, `CHANGELOG.md`.

### Earlier
Phases 1–15 predate this file; see [docs/progress.md](docs/progress.md). Highlights:
NPDRM SELF decryption from a RAP, the `--hle-stubs` import path, SPU job capture
and lift, jump-table recovery (`scripts/jumptables.py`), and the `longjmp`
fix (`scripts/setjmp_patch.py`).
