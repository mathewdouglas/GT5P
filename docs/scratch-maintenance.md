# Scratch cleanup record

## 2026-10-29

### Resolved-bug runs

At the user's request, matched old outputs against documented fixes and recycled
a further 1,028 files / 3,395,411,649 bytes (3.16 GiB). This leaves approximately
22.32 GiB in scratch (79,233 files before the final summary manifest).

- Phase 118: superseded tunnel exposure/reflection runs and two older tunnel
  GPU captures; kept `tunnel118g`, `tunrefl118b_frame9640.rdc`,
  `graphics94-manual_frame10650.rdc` and `meter118_frame6123.rdc`.
- Phase 113: superseded barrier/road saturation experiments; kept `satcold2`,
  `satvis4` and both saturation GPU captures for reference.
- Phases 75/79/80/81: old depth, font, mip-view and normal-map runs;
  kept representative 1080p validation and fixed depth captures.
- Phases 72/76/82/83: old pit-crew, crowd, opening-logo and flicker runs;
  kept the later crew/crowd captures, logo control/fix outputs and
  `flickerunhigpu_frame2037.rdc`.
- Phases 123/125/126/130/132: superseded ultrawide dim-layer captures,
  cockpit-mirror and label runs; kept `uwdim3`, `cock4` and `lblfix2`.

Golf rim captures remain: Phase 96 still lacks final visual acceptance. Also
preserved the RPCS3 reference captures, current upgrade validation, outstanding
freeze/stutter evidence, shader caches, rollback trees, scripts and original
`logs/debug/` exports. No game or build/test process was launched.

Targets were checked for absolute containment, reparse points, matching size
and modification time, moved into a checked scratch staging folder, then sent
to the Recycle Bin as `_resolved-runs-recycle-20261029`. All original target
paths were verified absent, and 15 named retained artifacts/directories checked
present. Audit files: `scratch/cleanup-20261029-resolved-{plan,result,summary}.json`.
The recycled folder retains its `pv/` and `rdoc/` structure for recovery.
Disk space is not reclaimed until the Recycle Bin is emptied.

### Reproducible fixtures

Recycled 71 reproducible test-output directories containing 2,829 files /
2,950,404,433 bytes (2.75 GiB). These were `debug-export-test-*`,
`audio-native-*`, `audio-math-*`, `cond-callback-*` and `spurs-arg-*`
fixtures; their canonical sources remain under `scripts/test/`. Every selected
directory predated October 28 and was checked again for changes before recycling.

After cleanup, `scratch/` contained 80,257 files / 27,356,550,288 bytes
(25.48 GiB), before writing the final small summary manifest. Recycled data
remains recoverable; disk space is reclaimed only when the Recycle Bin is emptied.

Preserved all GPU captures, reference frames, race reports, shader caches,
unique diagnostic helpers and investigation outputs. In particular,
`upgrade-v018/` (including runtime worktrees and rollback files),
`gen-prerelift/`, `rdoc/`, `renderdoc/`, `pv/` and `shader89/` remain intact.
No builds, tests or game launches were performed during cleanup.

Every target was resolved beneath the exact workspace `scratch/` directory,
restricted to the fixture prefixes above, and checked for reparse points and
protected capture/cache files. File counts and sizes were matched against the
plan, and all 71 target paths were verified absent afterwards. Local audit files
are `scratch/cleanup-20261029-{plan,result,summary}.json` (gitignored).

## 2026-10-19

The user requested removal of unneeded scratch data. The folder contained
29,329 files / 25,279,624,018 bytes (23.54 GiB) before cleanup.

Sent 15,439,331,542 bytes (14.38 GiB), across 1,880 file/directory targets, to
the Windows Recycle Bin. Afterwards `scratch/` contained approximately
20,610 files / 9.16 GiB, including the small local cleanup manifests. This is
a reduction in the working folder, not a claim that disk space was reclaimed;
the Recycle Bin must be emptied to reclaim its occupied space. Automatic
approval review blocked the initial permanent bulk deletion with the generic
reason "blocked by policy"; recoverable recycling succeeded instead.

Removed from the working folder:

- Obsolete scratch-only generated-code snapshots and old executable baselines.
- Historical device-removal image/log dumps and the old `cap41b` capture set.
- Repeated `scratch/pv/cap_*` output, except `cap_hudnative87` and
  `cap_rd_racehudpin87` retained for the recent map investigation.
- Reproducible `debug-export-test-*` fixture directories and old performance
  output. The diagnostic source `scratch/perf/f8c0.c` was preserved.
- Top-level historical `.out`/`.err` logs, old `ppu_recomp*.orig` copies and
  the before-inline executable/map.
- Failed/superseded RPCS3 road captures: `rpcroad_frame11673.rdc` and
  `rpcroadnext_frame5228..5231.rdc`, plus the duplicate water frame 4112.
  Historical progress entries can still refer to these removed artifacts.

Preserved:

- `scratch/rdoc/hsrroad-reference.rrc.gz` and its useful RenderDoc replay
  `rpcroadreplay_frame187.rdc`.
- Other standalone RenderDoc captures, including the recent race/map capture,
  and all three original reference captures under `scratch/renderdoc/`.
- Recent race images/logs, extracted process-35540 reports, diagnostic helper
  scripts and the remaining small investigations.
- All shader-cache directories, including isolated test caches under scratch.
- Original debug exports under `logs/debug/`, the current `build/`, active
  `generated/`, original game data and tracked files.

Every target was resolved and checked to be a descendant of the exact workspace
`scratch` directory before recycling; reparse points were rejected. The local
plan/result are in `scratch/cleanup-20261019-{plan,result}.json` (gitignored).
No running game was found. Existing RenderDoc processes were left alone.

For future cleanup, preserve reusable reference frames and current open-bug
evidence first. Test fixtures and duplicate capture outputs can be regenerated;
unique helpers and captures should be inspected before removal. Existing
historical documentation is evidence of earlier measurements, not a guarantee
that every scratch artifact remains on disk.
