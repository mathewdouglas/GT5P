# Roadmap

For the disc build (BCUS98158), the current state is maintained in
[AGENTS.md](AGENTS.md) under "Start here", with evidence in
[docs/progress.md](docs/progress.md). This file lists the work ahead. It was
updated 2026-10-18, after Phase 72.

## Next (disc build)

- **Texture-load warning.** When a texture cannot be read (an unmapped
  address, an unsupported format or no free slot), show an on-screen badge
  like "Compiling shaders" and write a log line.
- **The menu after the Race Mode page.** Coming back from the pit leaves
  black slabs in the menu scene, and then the dealer floor reflects the
  menu's trees. This is parked while the user tries to reproduce it;
  `scripts\test\roundtrip.ps1 -Pit` drives the route.
- **Re-check two older reports**, made before Phase 69: black slabs in the
  Kyoto menu scene, and loading-screen text with letters dropped or
  swapped.
- **Frame rate.** Menus, the pit and the race run at about 30 fps; some
  dealer pages drop to 20 to 28 fps. The plan is in
  [docs/plan-30fps.md](docs/plan-30fps.md).

## Later

- The dim 2D layer (Phase 37), the dealer floor reflection (Phase 46.4), and
  texture units 4 and up in fragment programs.
- Sound in a race, which has more voices than the menu.
- The `TV.DAT` install that RPCS3 runs at first boot; this port uses
  RPCS3's installed copy of the content.
- Send the local ps3recomp changes
  ([patches/](patches/ps3recomp-5244db9-local.patch)) upstream as separate
  pull requests.
- **Upstream build (NPUA80075):** it still stops in `sys_cond_wait` after
  its 116 assets (2026-09-28). The disc build's fixes may apply once
  measured there.
- **Move onto the shared harness** (`runtime/ppu/tests/boot_main.cpp`), the
  regression gate (`tools/regress_ports.toml`) and a one-command re-lift.

## Out of scope

- Online features: PSN services for this title shut down in 2013.
- Shipping any game data, keys or generated source.
