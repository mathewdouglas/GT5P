# Roadmap

## Next

- **Characterise the new stop.** Main is in `sys_cond_wait` (syscall 107,
  no timeout) from ≤20 s on, under `func_009386C4` ← `func_00954140` ←
  `func_00954200`, with all 116 assets loaded. Find the cond and its signaller. Build the control-flow graph before naming it — see the working
  rules at the top of [docs/progress.md](docs/progress.md).
- **Check headless against windowed.** Every number since 2026-09-28 is
  headless; August's were windowed. Soak once with a window (at the console,
  under offstage) to rule timing in or out.
- **Retry ps3recomp #185 and #189 once there is a frame loop.** Tried
  2026-09-28: no effect, because the boot stops before any per-frame work
  (Join is never called). Branches `gt5p/pr185`, `gt5p/pr189` in the toolkit clone.

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
