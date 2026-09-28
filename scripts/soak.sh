#!/usr/bin/env bash
# Boot the port N times, headless, and count unique PDIPFS files opened per run.
# That count is this port's progress measure until it presents a frame: the
# boot's asset loading is what stalls, and the number is what distinguishes one
# stall from another. PS3_VERBOSE=0 because verbose logging serialises every
# guest thread on stderr's lock and changes what the title does.
#
#   scripts/soak.sh [runs=8] [seconds=40] [exe=build/gt5p.exe]
# Logs land in scratch/soak/run<N>.log (gitignored).
set -u
runs=${1:-8}; secs=${2:-40}; exe=${3:-build/gt5p.exe}
mkdir -p scratch/soak
counts=()
for i in $(seq 1 "$runs"); do
    log=scratch/soak/run$i.log
    PS3_HEADLESS=1 PS3_VERBOSE=0 timeout "$secs" "$exe" >"$log" 2>&1
    rc=$?
    n=$(grep -o "Open(path='[^']*PDIPFS[^']*'" "$log" | sort -u | wc -l)
    flips=$(grep -c -i "flip" "$log")
    echo "run $i: rc=$rc assets=$n flip-lines=$flips"
    counts+=("$n")
done
echo "assets: ${counts[*]}"
