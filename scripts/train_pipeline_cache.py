"""Automatically visit supported routes and prepare their learned pipelines.

This pragmatic developer workflow uses real draw state, not independent state
reconstruction. It cannot discover scenes it never visits. All writes are in a
private ignored output; the fixture must already be a copied local game dump.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

from shader_coverage import ROOT, bounded_read, fnv64
from shader_reconstruct import offline_env, run_offline

TRACKS = ('HighSpeedRing', 'Daytona')


def save_report(path, report):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(path)


def idle():
    if b'gt5p.exe' in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq gt5p.exe', '/NH'], capture_output=True).stdout.lower():
        raise ValueError('Another gt5p.exe is running; nothing was stopped')


def isolated(path):
    path = path.resolve()
    if ROOT not in path.parents or subprocess.run(
            ['git', 'check-ignore', '-q', str(path / 'report.json')], cwd=ROOT).returncode:
        raise ValueError('Use a private gitignored path inside this audit checkout')
    return path


def writable_tree(path, output):
    """Reject redirected resume paths before starting any child or cache write."""
    if output not in path.resolve().parents:
        raise ValueError('Writable path escapes this run: ' + str(path))
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            item = Path(current) / name
            if item.is_symlink() or item.is_junction():
                raise ValueError('Writable run directories must not contain links: ' + str(item))


def validate_recipe(path, codes=None):
    data = bounded_read(path, 16384)
    if (len(data) != 2760 or struct.unpack_from('<QII', data) != (0x31574d5241503547, 1, 2760) or
            struct.unpack_from('<Q', data, 2752)[0] != fnv64(data[:-8])):
        raise ValueError('Invalid pinned Windows x64 recipe envelope/checksum')
    key, vs, ps, vlen, plen = struct.unpack_from('<QQQII', data, 16)
    if not key or path.name != f'pso_{key:016x}.recipe':
        raise ValueError('Recipe filename/key mismatch')
    for code, length in ((vs, vlen), (ps, plen)):
        if not 0 < length <= 4 * 1024 * 1024:
            raise ValueError('Invalid bytecode length')
        if codes is not None and (code, length) in codes:
            continue
        payload = bounded_read(path.parent / f'code_{code:016x}.dxbc', 4 * 1024 * 1024)
        if len(payload) != length or not payload.startswith(b'DXBC') or fnv64(payload) != code:
            raise ValueError('Missing or mismatched recipe bytecode')
        if codes is not None:
            codes.add((code, length))
    return f'{key:016x}'


def inventory(cache, validate_blobs=False):
    keys, rejected, codes = [], [], set()
    for path in sorted((cache / 'warmup-v1').glob('*.recipe')):
        try:
            keys.append(validate_recipe(path, codes))
        except (ValueError, OSError) as exc:
            rejected.append(dict(file=path.name, reason=str(exc)))
    blobs = []
    for key in keys if validate_blobs else ():
        path = cache / f'pso_{key}.bin'
        try:
            data = bounded_read(path, 32 * 1024 * 1024)
            if len(data) > 24:
                magic, size, checksum = struct.unpack_from('<QQQ', data)
                if magic == 0x31534f5035505447 and size == len(data) - 24 and fnv64(data[24:]) == checksum:
                    blobs.append(key)
        except (ValueError, OSError):
            pass
    return dict(recipes=keys, valid_driver_blobs=blobs, rejected=rejected)


def route_result(logs, tag):
    out = (logs / f'{tag}.out').read_text(errors='replace')
    window = json.loads((logs / f'{tag}.window.json').read_text(encoding='utf-8-sig'))
    milestones = dict(re.findall(r'\[milestone\] (\w+) at (\d+) ms', out))
    if 'QuickArcadeRoot' not in milestones or window['sample_end_ms'] <= window['sample_start_ms']:
        raise ValueError('Route did not confirm a grid and completed sampling window')
    rows = (logs / f'{tag}.frames.csv').read_text().splitlines()
    times = [float(row.split(',')[0]) for row in rows if len(row.split(',')) == 3]
    presented = [t for t in times if window['sample_start_ms'] <= t <= window['sample_end_ms']]
    if len(presented) < 10 or any(b <= a for a, b in zip(presented, presented[1:])):
        raise ValueError('Route did not confirm ongoing frame presentation')
    return dict(milestones=milestones, presented_samples=len(presented), window=window,
                limitation='Grid/presentation checks do not prove every scene rendered correctly or all variants were encountered.')


def prepare(engine, game, cache, log):
    before = inventory(cache)
    if before['rejected'] or not before['recipes']:
        raise ValueError('Cannot prepare an empty or damaged learned recipe set')
    if len(before['recipes']) > 8192:
        raise ValueError('Recipe set exceeds this runtime offline cap (8192); no partial-success claim')
    env = offline_env(game, cache)
    env.update(RSX_SHADER_WARMUP_BACKGROUND='0', RSX_PSO_RECIPE_KEEP_DAYS='0',
               RSX_SHADER_WARMUP_SCAN='1', RSX_PSO_RECIPES='1')
    text = run_offline(engine, game, env, log, timeout=1200)
    match = re.search(r'\[shader-warmup\] finished: loaded=(\d+) rejected=(\d+) elapsed_ms=(\d+)', text)
    if not match or int(match[1]) != len(before['recipes']) or int(match[2]):
        raise ValueError('Native preparation did not accept every learned recipe; inspect ' + str(log))
    after = inventory(cache, validate_blobs=True)
    if after['rejected'] or set(after['recipes']) != set(before['recipes']) or set(after['valid_driver_blobs']) != set(after['recipes']):
        raise ValueError('Native preparation did not preserve recipes and persist every driver blob')
    return dict(loaded=int(match[1]), rejected=int(match[2]), elapsed_ms=int(match[3]),
                persisted_driver_blobs=len(after['valid_driver_blobs']), guest_entry_executed=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('fixture', 'engine', 'output'):
        ap.add_argument('--' + name, required=True, type=Path)
    ap.add_argument('--tracks', nargs='+', choices=TRACKS, default=list(TRACKS))
    ap.add_argument('--seconds', type=int, default=90, help='Sampling seconds after the grid (30..900)')
    ap.add_argument('--passes', type=int, default=1, help='Visits per route (1..4); more visits can catch late async draws')
    ap.add_argument('--resolution', choices=('720p', '1080p'), default='1080p')
    ap.add_argument('--msaa', choices=('1', '2'), default='2')
    ap.add_argument('--resume', action='store_true', help='Continue this output with matching engine/settings/fixture')
    ap.add_argument('--prepare-only', action='store_true', help='With --resume, rebuild every learned pipeline without driving')
    args = ap.parse_args()
    if not 30 <= args.seconds <= 900 or not 1 <= args.passes <= 4:
        ap.error('Use --seconds 30..900 and --passes 1..4')
    if args.prepare_only and not args.resume:
        ap.error('--prepare-only requires --resume')
    fixture, output, engine = isolated(args.fixture), isolated(args.output), args.engine.resolve()
    if fixture == output or fixture in output.parents or output in fixture.parents:
        ap.error('Output must be separate from the copied fixture')
    if len(str(output)) > 130:
        ap.error('Use an output path of at most 130 characters for native cache paths')
    isolated(engine.parent)
    for name in ('input/EMAIN.ELF', 'input/pkg/PARAM.SFO', 'gamedata', 'assets'):
        if not (fixture / name).exists():
            ap.error('Incomplete copied fixture: ' + name)
    # Reject junctions/symlinks in the supplied fixture: all game writes must
    # resolve within the copied audit fixture, including writable game data.
    for current, dirs, files in os.walk(fixture, followlinks=False):
        for name in dirs + files:
            path = Path(current) / name
            if path.is_symlink() or path.is_junction():
                ap.error('The supplied fixture must contain copies, not links: ' + str(path))
    idle()
    config = dict(engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
                  fixture=str(fixture), elf_sha256=hashlib.sha256((fixture / 'input/EMAIN.ELF').read_bytes()).hexdigest(),
                  tracks=args.tracks, seconds=args.seconds, passes=args.passes,
                  resolution=args.resolution, msaa=args.msaa)
    report_path = output / 'report.json'
    if args.resume:
        report = json.loads(report_path.read_text())
        if report['config'] != config:
            ap.error('Resume engine/fixture/route/settings differ from the saved run')
    else:
        if output.exists():
            ap.error('Use a new output or --resume; no files were removed')
        output.mkdir(parents=True)
        report = dict(schema=1, config=config, routes=[], status='initializing',
                      origin='Automatically learned real draw state and local bytecode, not independent asset reconstruction.',
                      limitations=['Only the supported routes/current car and selected settings are visited.',
                                   'No whole-game coverage or stutter-reduction guarantee.',
                                   'Driver blobs are local to this hardware/driver; retain recipes and code.',
                                   'Preparation finishes before play; do not bulk scan this cache during a benchmark.'])
        save_report(report_path, report)
        game = output / 'game'
        game.mkdir()
        shutil.copytree(fixture / 'gamedata', game / 'gamedata')
        shutil.copytree(fixture / 'assets', game / 'assets')
        (game / 'input').mkdir()
        shutil.copy2(fixture / 'input/EMAIN.ELF', game / 'input/EMAIN.ELF')
        link_env = dict(os.environ, GT5P_TRAIN_LINK=str(game / 'input/pkg'), GT5P_TRAIN_TARGET=str(fixture / 'input/pkg'))
        subprocess.run(['powershell', '-NoProfile', '-Command',
                        'New-Item -ItemType Junction -Path $env:GT5P_TRAIN_LINK -Target $env:GT5P_TRAIN_TARGET | Out-Null'],
                       env=link_env, check=True)
    game, cache, logs = output / 'game', output / 'shadercache', output / 'logs'
    for path in (game / 'gamedata', game / 'assets', cache, logs):
        writable_tree(path, output)
    if (game / 'input/pkg').resolve() != (fixture / 'input/pkg').resolve():
        ap.error('Run disc junction no longer points to the copied fixture')
    cache.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)

    def save():
        save_report(report_path, report)

    try:
        if not args.prepare_only:
            for number in range(1, args.passes + 1):
                for track in args.tracks:
                    tag = f'{number}-{track}'
                    if any(r['tag'] == tag and r['status'] == 'visited' for r in report['routes']):
                        continue
                    idle()
                    before = set(inventory(cache)['recipes'])
                    report['status'] = 'visiting ' + tag
                    save()
                    env = {k: v for k, v in os.environ.items() if not k.startswith(
                        ('GT5P_', 'RSX_', 'PS3_', 'PAD_', 'FP_', 'VP_', 'SPU_', 'PPU_', 'D3D12_', 'CULL_'))}
                    env.update(PS3_VERBOSE='0', GT5P_GAME_DIR='input/pkg/', PS3_VFS_ROOT=str(game),
                               PS3_GAMEDATA_ROOT=str(game / 'gamedata'), RSX_SHADER_CACHE=str(cache),
                               RSX_SHADER_WARMUP='1', RSX_SHADER_WARMUP_SCAN='0', RSX_SHADER_WARMUP_BACKGROUND='1',
                               RSX_PSO_ASYNC='1', RSX_SHADER_ASYNC='1', RSX_PSO_RECIPES='1',
                               RSX_PSO_RECIPE_KEEP_DAYS='0', RSX_RACE_PREWARM='1',
                               RSX_RACE_PREWARM_WAIT_MS='0', RSX_PSO_PROVENANCE='0', PAD_HOLD_MERGE='0', RSX_PRESENT_SYNC='1')
                    cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'scripts/test/race.ps1'),
                           '-Track', track, '-Tag', tag, '-Seconds', str(args.seconds), '-SampleDelay', '0',
                           '-FrameTest', '-RaceShots', '30', '-Engine', str(engine), '-GameRoot', str(game),
                           '-OutputDirectory', str(logs), 'GT5P_RESOLUTION=' + args.resolution, 'RSX_MSAA=' + args.msaa]
                    print('Automatically visiting', tag, flush=True)
                    with (logs / (tag + '.runner.log')).open('wb') as stream:
                        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
                        try:
                            if proc.wait(timeout=args.seconds + 480):
                                raise ValueError('Route failed; inspect ' + str(logs / (tag + '.runner.log')))
                        finally:
                            if proc.poll() is None:
                                # This exact child tree belongs to this invocation.
                                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
                                proc.wait(timeout=15)
                    result = route_result(logs, tag)
                    after = inventory(cache)
                    if after['rejected']:
                        raise ValueError('Learned recipe dependencies are damaged; inspect the cache')
                    route = dict(tag=tag, status='visited', new_recipes=len(set(after['recipes']) - before),
                                 total_recipes=len(after['recipes']), **result)
                    report['routes'].append(route)
                    save()
                    print(f"{tag}: {route['new_recipes']} new / {route['total_recipes']} learned recipes", flush=True)
        report['status'] = 'preparing'
        save()
        print('Preparing every learned native pipeline before play', flush=True)
        started = time.monotonic()
        report['preparation'] = prepare(engine, game, cache, output / 'prepare.log')
        report['preparation']['wall_seconds'] = time.monotonic() - started
        report['status'] = 'complete'
        report.pop('error', None)
        save()
        print('Completed:', report_path, flush=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report.update(status='failed', error=str(exc))
        save()
        raise


if __name__ == '__main__':
    main()
