"""Summarise exported GT5P reports without extracting game images or assets.

Accept ZIP files or a folder, optionally --pid N and --json. Supports both
frame-history layouts; v1 does not measure idle, vblank or flip work separately.
"""
import argparse
import csv
import io
import json
from pathlib import Path
import re
import statistics
import zipfile


def summarise(path):
    with zipfile.ZipFile(path) as archive:
        text = archive.read("report.txt").decode("utf-8", errors="replace")
        match = re.search(r"^age_s,[^\r\n]+", text, re.M)
        rows = []
        if match:
            lines = text[match.start():].splitlines()
            for line in lines[1:]:
                if not re.fullmatch(r"[-\d.,]+", line):
                    break
                rows.append(line)
            rows = list(csv.DictReader(io.StringIO(lines[0] + "\n" + "\n".join(rows))))
        frames = [{key: float(value) for key, value in row.items()} for row in rows]
        intervals = []
        for older, newer in zip(frames, frames[1:]):
            dt = 1000 * (older["age_s"] - newer["age_s"])
            if dt <= 0:
                continue
            measured = sum(v for k, v in newer.items() if k.endswith("_ms"))
            intervals.append(dict(newer, interval_ms=dt, other_ms=dt - measured))
        values = sorted(row["interval_ms"] for row in intervals)
        details = {key: next((line[len(prefix):] for line in text.splitlines() if line.startswith(prefix)), "")
                   for key, prefix in (("source", "Source: "), ("settings", "Loaded settings: "),
                                       ("shaders", "Shaders: "), ("present", "Total presents: "))}
        has_history = "hitches.txt" in archive.namelist()
        history = archive.read("hitches.txt").decode("utf-8", errors="replace") if has_history else ""
        hitches = []
        for entry in re.split(r"(?=^=== frame \d+ )", history, flags=re.M)[1:]:
            head = re.search(r"=== frame (\d+) age_ms=([\d.]+) since_enable_ms=(\d+)", entry)
            shaders = re.search(r"Shaders: busy=(\d+) pending=(\d+) compiled=(\d+) pipelines=(\d+)", entry)
            fifo = re.search(r"fifo get io=([0-9A-Fa-f]+).*?park_ea=([0-9A-Fa-f]+) word=([0-9A-Fa-f]+)", entry)
            if head:
                hitches.append(dict(frame=int(head[1]), sample_age_ms=float(head[2]), since_enable_ms=int(head[3]),
                    shaders=dict(zip(('busy', 'pending', 'compiled', 'pipelines'), map(int, shaders.groups()))) if shaders else None,
                    fifo=dict(zip(('get_io', 'park_ea', 'word'), fifo.groups())) if fifo else None))
        return dict(file=str(path), **details, intervals=len(values),
                    median_ms=statistics.median(values) if values else None,
                    p95_ms=values[int((len(values) - 1) * .95)] if values else None,
                    max_ms=max(values) if values else None,
                    over_100ms=sum(value > 100 for value in values),
                    worst=sorted(intervals, key=lambda row: row["interval_ms"], reverse=True)[:5],
                    hitch_history_available=has_history,
                    automatic_hitches=len(re.findall(r"^=== frame \d+ ", history, re.M)), hitches=hitches)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    files = sorted({file for path in args.paths for file in
                    (path.glob("gt5p-debug-*.zip") if path.is_dir() else [path])})
    if args.pid is not None:
        files = [file for file in files if re.search(rf"-{args.pid}-\d+\.zip$", file.name)]
    results = [summarise(file) for file in files]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for row in results:
            print(Path(row["file"]).name)
            if row["intervals"]:
                print(f'  {row["intervals"]} intervals: median {row["median_ms"]:.2f} ms, '
                      f'p95 {row["p95_ms"]:.2f} ms, max {row["max_ms"]:.2f} ms; '
                      f'{row["over_100ms"]} over 100 ms')
            else:
                print("  No frame history")
            print("  " + row["shaders"])
            if row["hitch_history_available"]:
                print(f'  Retained hitch snapshots: {row["automatic_hitches"]}')
            for hitch in row['hitches']:
                print(f'    Frame {hitch["frame"]}: sample age {hitch["sample_age_ms"]:.1f} ms, '
                      f'shaders={hitch["shaders"]}, fifo={hitch["fifo"]}')
            for frame in row["worst"][:3]:
                print(f'  {frame["age_s"]:.3f} s before snapshot: {frame["interval_ms"]:.2f} ms gap, '
                      f'FIFO {frame["fifo_ms"]:.2f}, present {frame["present_ms"]:.2f}, '
                      f'idle {frame.get("idle_wait_ms", 0):.2f}, other {frame["other_ms"]:.2f} ms')
        print("Each report covers a short window; paused previews and racing are not equivalent workloads.")


if __name__ == "__main__":
    main()
