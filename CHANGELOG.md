# Changelog

All notable changes to this port. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/). Nothing is tagged yet.

## [Unreleased]

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
