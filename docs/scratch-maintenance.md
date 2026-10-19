# Scratch cleanup record

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
