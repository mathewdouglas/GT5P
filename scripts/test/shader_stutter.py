"""Paired HSR cold-application-cache benchmark using an isolated game fixture.

The fixture must contain copied input/, gamedata/ and assets/. Original files
are never launched or written. Every trial keeps its own saves and shadercache.
OS/driver caches are deliberately preserved; this is not a driver-cold test.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def frame_stats(rows, start, end):
    selected = [r for r in rows if start <= r[0] <= end]
    intervals = [b[0] - a[0] for a,b in zip(selected,selected[1:])]
    if len(intervals) < 10 or any(v <= 0 for v in intervals):
        raise ValueError('Insufficient or non-monotonic presented-frame samples')
    ordered = sorted(intervals)
    percentile = lambda q: ordered[min(len(ordered)-1, math.ceil(q*len(ordered))-1)]
    return dict(frames=len(selected), seconds=(selected[-1][0]-selected[0][0])/1000,
                fps=len(intervals)*1000/sum(intervals), median_ms=percentile(.5),
                p99_ms=percentile(.99), max_ms=max(intervals),
                over_50_ms=sum(v>50 for v in intervals), over_100_ms=sum(v>100 for v in intervals),
                over_250_ms=sum(v>250 for v in intervals),
                hitch_excess_50_ms=sum(max(0,v-50) for v in intervals),
                walk_wall_ms=sum(r[1] for r in selected)/len(selected),
                walk_cpu_ms=sum(r[2] for r in selected)/len(selected))


def analyze_run(logs, tag, seed_keys=()):
    window = json.loads((logs/f'{tag}.window.json').read_text(encoding='utf-8-sig'))
    rows = []
    for row in csv.reader((logs/f'{tag}.frames.csv').open()):
        if len(row) == 3:
            rows.append(tuple(map(float,row)))
    err = (logs/f'{tag}.err').read_text(errors='replace')
    out = (logs/f'{tag}.out').read_text(errors='replace')
    grid = window['grid_observed_ms']
    periods = dict(grid_first_45s=(grid,grid+45000),
                   race_45_to_90s=(grid+45000,grid+90000),
                   whole_presented_route=(window['launch_ms'],window['sample_end_ms']))
    misses = re.findall(r'\[pso-time\] 5 s: (\d+) misses: hlsl ([\d.]+) ms, dxbc ([\d.]+) ms \((\d+) compiled so far\), pipeline ([\d.]+) ms',err)
    warm = re.findall(r'\[shader-warmup\].*?(?:loaded=|prepared )(\d+).*?rejected=(\d+)',err)
    metrics = re.findall(r'\[pipeline-metrics\] shader_compiles=(\d+) driver_calls=(\d+) cached_calls=(\d+) demand_queued=(\d+) demand_done=(\d+) warm_loaded=(\d+) warm_hits=(\d+) resident=(\d+)', err)
    metric_names = ('shader_compiles','driver_calls','cached_calls','demand_queued','demand_done','warm_loaded','warm_hits','resident')
    memory_path = logs / f'{tag}.memory.csv'
    memory = list(csv.DictReader(memory_path.open(encoding='utf-8-sig'))) if memory_path.exists() else []
    # The worker marks actually used recipes once per run; mere startup reads
    # leave an existing recipe's timestamp unchanged. No provenance recording.
    used = {p.stem[4:] for p in (logs.parent/'shadercache/warmup-v1').glob('pso_*.recipe')
            if p.stat().st_mtime_ns >= window['launch_ms']*1_000_000}
    return dict(window=window, periods={k:frame_stats(rows,*v) for k,v in periods.items()},
                observed_pso_misses=sum(int(m[0]) for m in misses),
                observed_hlsl_ms=sum(float(m[1]) for m in misses),
                observed_dxbc_ms=sum(float(m[2]) for m in misses),
                observed_pipeline_ms=sum(float(m[4]) for m in misses),
                compiled_so_far=max((int(m[3]) for m in misses),default=0),
                grid_seconds=(grid-window['launch_ms'])/1000,
                milestones=dict((n,int(t)) for n,t in re.findall(r'\[milestone\] (\w+) at (\d+) ms',out)),
                warmup_summaries=warm,
                pipeline_counters=dict(zip(metric_names,map(int,metrics[-1]))) if metrics else {},
                memory_peak_sampled={k:max(int(r[k]) for r in memory) for k in ('WorkingSet','PrivateBytes','PeakWorkingSet')} if memory else {},
                metrics_note='Cumulative counters sampled every five seconds; final partial interval can be omitted. Driver calls include startup preparation; demand_queued counts live async work.',
                used_native_recipes=len(used), encountered_seed_keys=sorted(used & set(seed_keys)),
                compiler_note='Five-second diagnostic summaries omit any final partial interval.',
                period_note='Early period includes grid and intended 30-FPS rolling start; route includes loading transitions.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('fixture','engine','prepared','output'):
        ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--trials',type=int,choices=(2,4),default=4)
    ap.add_argument('--startup-policy',choices=('scan','demand'),default='scan',
                    help='Scan all prepared recipes at startup, or use prepared files on demand')
    args = ap.parse_args()
    fixture,engine,prepared,output = (getattr(args,k).resolve() for k in ('fixture','engine','prepared','output'))
    if output.exists() or subprocess.run(['git','check-ignore','-q',str(output/'report.json')],cwd=ROOT).returncode:
        ap.error('Choose a new ignored output directory')
    for path in (fixture,engine,prepared):
        if path == output or path in output.parents or output in path.parents:
            ap.error('Output must be separate from all inputs')
    if not (fixture/'input/EMAIN.ELF').is_file() or not (fixture/'gamedata').is_dir():
        ap.error('Provide a complete isolated game fixture')
    if subprocess.run(['git','check-ignore','-q',str(fixture/'input/EMAIN.ELF')],cwd=ROOT).returncode:
        ap.error('The copied fixture must be in ignored storage in this checkout')
    if not (prepared/'warmup-v1').is_dir():
        ap.error('--prepared must name the generated shadercache directory')
    output.mkdir(parents=True)
    seed_keys = {p.stem[4:] for p in (prepared/'warmup-v1').glob('pso_*.recipe')}
    report = dict(engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
                  fixture=str(fixture), prepared=str(prepared), trials=[],
                  conditions='1080p/2x MSAA/VSync; async shaders/PSOs; PS3_VERBOSE=0',
                  startup_policy=args.startup_policy,
                  limitations=['Cold application caches, warm uncontrolled OS/driver caches.',
                               'ABBA order reduces order bias; two runs per condition are not statistical proof.',
                               'Early grid/rolling-start and loading transitions are separate from later racing.',
                               'Scripted navigation is repeatable, but race progress/draw workloads can differ.',
                               'Original offline subset preparation time is outside these live trial timings.'])
    order = ('control','prepared','prepared','control')[:args.trials]
    for number,condition in enumerate(order,1):
        if b'gt5p.exe' in subprocess.run(['tasklist','/FI','IMAGENAME eq gt5p.exe','/NH'],capture_output=True).stdout.lower():
            raise SystemExit('Another gt5p.exe is running; nothing was stopped')
        tag = f'{number}-{condition}'
        trial = output/tag;game = trial/'game';logs=trial/'logs';game.mkdir(parents=True);logs.mkdir()
        print('Creating isolated trial',tag,flush=True)
        shutil.copytree(fixture/'gamedata',game/'gamedata')
        shutil.copytree(fixture/'assets',game/'assets')
        (game/'input').mkdir();shutil.copy2(fixture/'input/EMAIN.ELF',game/'input/EMAIN.ELF')
        # This diagnostic EXE predates absolute game-dir handling in main().
        # A junction points only at our copied fixture, never the original dump.
        junction_env = dict(os.environ, GT5P_BENCH_LINK=str(game/'input/pkg'),
                            GT5P_BENCH_TARGET=str(fixture/'input/pkg'))
        subprocess.run(['powershell','-NoProfile','-Command',
                        'New-Item -ItemType Junction -Path $env:GT5P_BENCH_LINK -Target $env:GT5P_BENCH_TARGET | Out-Null'],
                       env=junction_env,check=True)
        cache = trial/'shadercache'
        if condition == 'prepared':
            shutil.copytree(prepared,cache)
        else:
            cache.mkdir()
        env = {k:v for k,v in os.environ.items() if not k.startswith(
            ('GT5P_','RSX_','PS3_','PAD_','FP_','VP_','SPU_','PPU_','D3D12_','CULL_'))}
        env.update(PS3_VERBOSE='0',GT5P_GAME_DIR='input/pkg/',
                   PS3_VFS_ROOT=str(game),PS3_GAMEDATA_ROOT=str(game/'gamedata'),
                   RSX_SHADER_CACHE=str(cache),RSX_SHADER_WARMUP='1',
                   RSX_SHADER_WARMUP_SCAN='1' if args.startup_policy == 'scan' else '0',
                   RSX_SHADER_WARMUP_BACKGROUND='1',RSX_PSO_ASYNC='1',RSX_SHADER_ASYNC='1',
                   RSX_RACE_PREWARM='0',RSX_PSO_PROVENANCE='0',PAD_HOLD_MERGE='0',RSX_PRESENT_SYNC='1')
        env['RSX_PIPELINE_METRICS'] = '1'
        cmd = ['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/test/race.ps1'),
               '-Track','HighSpeedRing','-Tag',tag,'-FrameTest','-Seconds','90','-SampleDelay','0',
               '-RaceShots','20','-Engine',str(engine),'-GameRoot',str(game),'-OutputDirectory',str(logs),
               'GT5P_RESOLUTION=1080p']
        print('Running',tag,flush=True)
        with (trial/'runner.log').open('wb') as stream:
            proc = subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
            try:
                if proc.wait(timeout=600):
                    raise RuntimeError('Race test failed; inspect '+str(trial/'runner.log'))
            finally:
                if proc.poll() is None:
                    subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
                    proc.wait(timeout=15)
        result = dict(tag=tag,condition=condition,**analyze_run(logs,tag,seed_keys))
        report['trials'].append(result)
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(result['periods']),flush=True)
    print('Completed paired benchmark:',output/'report.json',flush=True)


if __name__ == '__main__':
    main()
