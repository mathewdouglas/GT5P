"""Summarise F8 ZIP timing history without extracting or modifying the report.

Usage: python scripts/diag/debug_pacing.py logs/debug/*.zip
The profiler records render submissions, not measured scan-out timestamps.
"""
import argparse
import glob
import math
import re
import statistics
import zipfile
from pathlib import Path

HEADER = "age_s,fifo_ms,present_ms,pump_ms,vblank_ms,flip_ms,idle_wait_ms"


def frame_rows(report):
    lines = report.splitlines()
    try:
        start = lines.index(HEADER) + 1
    except ValueError:
        return []
    rows = []
    for line in lines[start:]:
        try:
            values = [float(v) for v in line.split(",")]
        except ValueError:
            break
        if len(values) != 7 or not all(math.isfinite(v) for v in values):
            break
        rows.append(values)
    return rows


def intervals(rows, window):
    # Each row's costs describe the interval ending at that submission.
    return [(1000 * (older[0] - newer[0]), newer)
            for older, newer in zip(rows, rows[1:])
            if 0 <= newer[0] <= window and older[0] > newer[0]]


def summarise(path):
    with zipfile.ZipFile(path) as archive:
        def read(name):
            info = archive.getinfo(name)
            if info.file_size > 32 * 1024 * 1024:
                raise ValueError(f"{name} exceeds diagnostic text limit")
            return archive.read(name).decode("utf-8", errors="replace")
        report = read("report.txt")
        hitches = read("hitches.txt") if "hitches.txt" in archive.namelist() else ""
    print(Path(path).name)
    for prefix in ("Source:", "Shaders:", "Logical CPUs:"):
        match = next((line for line in report.splitlines() if line.startswith(prefix)), None)
        if match:
            print("  " + match)
    rows = frame_rows(report)
    for window in (1, 5, float("inf")):
        samples = intervals(rows, window)
        if not samples:
            continue
        values = sorted(dt for dt, _ in samples)
        p95 = values[math.ceil(len(values) * .95) - 1]
        label = f"last {window:g}s" if math.isfinite(window) else "retained history"
        print(f"  {label}: n={len(values)} median={statistics.median(values):.2f}ms "
              f"p95={p95:.2f}ms max={max(values):.2f}ms "
              f">50ms={sum(v > 50 for v in values)} >250ms={sum(v > 250 for v in values)}")
    worst = sorted(intervals(rows, float("inf")), reverse=True, key=lambda v: v[0])[:5]
    for dt, row in worst:
        print(f"    gap={dt:.2f}ms age={row[0]:.3f}s fifo={row[1]:.2f}ms "
              f"submit={row[2]:.2f}ms idle={row[6]:.2f}ms")
    snapshots = re.findall(r"^=== frame .*", hitches, flags=re.M)
    print(f"  retained automatic hitch snapshots: {len(snapshots)}")
    print("  Timing is submission history; busy=0 at export does not rule out earlier compilation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+")
    args = parser.parse_args()
    files = sorted({path for pattern in args.reports for path in glob.glob(pattern)})
    if not files:
        parser.error("no reports matched")
    for path in files:
        try:
            summarise(path)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
            parser.exit(1, f"{path}: {error}\n")


if __name__ == "__main__":
    main()
