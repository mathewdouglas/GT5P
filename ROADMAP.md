# Roadmap

## Next

- **Characterise the new stop.** Main waits at the same place from ≤20 s on (last
  guest frames `func_009386C4` ← `func_00954140` ← `func_00954200`), with all 116
  assets loaded. Build the control-flow graph before naming it — see the working
  rules at the top of [docs/progress.md](docs/progress.md).
- **Check headless against windowed.** Every number since 2026-09-28 is
  headless; August's were windowed. Soak once with a window (at the console,
  under offstage) to rule timing in or out.
- **Try the open rendering PRs.** ps3recomp #185 (job-chain Join waits for the
  walker; flips queued in the FIFO) and #189 (GCM ring recycle, raw-SPU fences)
  fixed "prepares a flip, never draws" shapes in Simpsons, Crazy Taxi and
  Tornado Outbreak.

## Later

- **Move onto the shared harness.** Crazy Taxi and Simpsons build from the
  toolkit's `runtime/ppu/tests/boot_main.cpp` with no port `main.cpp`, which is
  also what turns on the live NV4097→D3D12 engine (`RSX_LIVE_DRAW=1`). GT5P's own
  `main.cpp` sets a custom main stack, HLE window and argv; those need a home in
  the harness first.
- **`tools/relift.sh`** in the sibling-port shape, so a lift is one command.
- **Register in the regression gate** (`tools/regress_ports.toml`) once the boot
  reaches a stable milestone.
- **`--headless --record out.mp4`**, per the recomp house style, once there is a
  frame to record.

## Out of scope

- Online features: PSN services for this title shut down in 2013.
- Shipping any game data, keys or generated source.
