"""Prepare a conditional material subset from original assets, without captures.

Developer-only: ordinary 2D uploads, explicit pass/global/target candidates.
Unresolved contexts are excluded. Outputs contain game-derived data; keep local.
"""
import argparse
from collections import Counter
import hashlib
import json
import mmap
from pathlib import Path
import struct
import subprocess
import time

from shader_coverage import ROOT, fnv64, bounded_read
from shader_materials import scan
from shader_material_state import model_states
from shader_material_textures import model_textures, with_global_sampler_path
from shader_material_profile import ordinary_profile, ASSUMPTIONS
from shader_pass_state import TARGET_PATHS, native_target_fields
from shader_reconstruct import NativeCompiler, offline_env, run_offline


def source_key(hlsl, target=b'vs_5_0'):
    return (fnv64(hlsl + target) * 1099511628211) & 0xffffffffffffffff  # flags=0


def request_envelope(vs, ps):
    """Pinned Windows x64 recipe V1: no captured native descriptor or expected key."""
    data = bytearray(2760)
    struct.pack_into('<QIIQQQII', data, 0, 0x31574d5241503547, 1, len(data),
                     0, fnv64(vs), fnv64(ps), len(vs), len(ps))
    struct.pack_into('<Q', data, 64, len(vs))
    struct.pack_into('<Q', data, 80, len(ps))
    struct.pack_into('<Q', data, len(data) - 8, fnv64(data[:-8]))
    return data


def save_code(path, code):
    if path.exists():
        if bounded_read(path, 4 * 1024 * 1024) != code:
            raise ValueError('Existing bytecode differs at content/source key: ' + str(path))
    else:
        path.write_bytes(code)


def enumerate_jobs(catalog, object_path, target_path, global_path, limit):
    index = json.loads((catalog / 'index.json').read_text())
    files = sorted({str(Path(s['file']).resolve()) for s in index['sources']})
    counts, rejected, seen, jobs = Counter(), Counter(), set(), []
    for number, filename in enumerate(files):
        with open(filename, 'rb') as stream:
            if not Path(filename).stat().st_size:
                continue
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for base, pairs, pair_rejected, error in scan(data):
                    counts['models'] += 1
                    if error:
                        rejected['model: ' + error] += 1
                        continue
                    rejected.update(pair_rejected)
                    try:
                        states, bindings, state_rejected = model_states(data, base, prepare=True)
                        textures, texture_rejected = model_textures(data, base)
                    except (ValueError, struct.error) as exc:
                        rejected['material tables: ' + str(exc)] += 1
                        continue
                    rejected.update(state_rejected); rejected.update(texture_rejected)
                    definitions = {d['definition']: with_global_sampler_path(d, global_path) for d in textures}
                    for pair in pairs:
                        for binding in bindings.get(pair['material'], ()):
                            counts['material_candidates'] += 1
                            definition = definitions.get(binding['definition'])
                            if definition is None:
                                rejected['missing texture definition'] += 1
                                continue
                            values = states[binding['state']]
                            try:
                                state = ordinary_profile(definition, values, pair['fragment_control'], object_path, target_path)
                            except ValueError as exc:
                                rejected[str(exc)] += 1
                                continue
                            fragment = bytes(data[pair['fragment_offset']:pair['fragment_offset'] + pair['fragment_size']])
                            vertex = pair['vertex_code']
                            metadata = dict(vertex_sha256=hashlib.sha256(vertex).hexdigest(),
                                            fragment_sha256=hashlib.sha256(fragment).hexdigest(), state=state)
                            key = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
                            counts['eligible_material_candidates'] += 1
                            if key in seen:
                                counts['duplicate_candidates'] += 1
                                continue
                            seen.add(key); counts['unique_candidates'] += 1
                            if not limit or len(jobs) < limit:
                                jobs.append(dict(id=key, **metadata, vertex=vertex, fragment=fragment,
                                                 source=dict(file=filename, model=base, material=pair['material'],
                                                             definition=binding['definition']), used=definition['used']))
        if number % 100 == 0:
            print(f'Containers {number + 1}/{len(files)}; eligible unique candidates {len(seen)}', flush=True)
    return jobs, dict(containers=len(files), counts=dict(counts), rejected=dict(rejected))


def compile_fragments(jobs, root, cache, engine, game_root):
    groups = {}
    for job in jobs:
        state = job['state']
        fields = [state['exp32'], state['cube'], 0, state['unnorm'] & ~0x100,
                  int(state['samplers'], 16), state['ghi'], state['shd'], state['unhi'], job['used']]
        dither = int(state['rtfmt'] == 28 and bool(state['cmask'] & 14))
        groups.setdefault(tuple(fields) + (dither,), []).append(job)
    compiled, failures = {}, {}
    for number, (key, members) in enumerate(groups.items()):
        print(f'Compiling profile {number + 1}/{len(groups)}: {len(members)} candidates', flush=True)
        group_id = hashlib.sha256(repr(key).encode()).hexdigest()
        work = root / group_id; work.mkdir(exist_ok=True)
        library = work / 'library'; library.mkdir(exist_ok=True)
        fresh = work / 'shadercache'; fresh.mkdir(exist_ok=True)
        profiles = fresh / 'fp-profiles-v2'; profiles.mkdir(exist_ok=True)
        for job in members:
            (library / (job['fragment_sha256'] + '.fp')).write_bytes(job['fragment'])
        (profiles / 'independent-state.txt').write_text(' '.join(f'{x:x}' for x in key[:-1]) + '\n', encoding='ascii')
        env = offline_env(game_root, fresh)
        env.update(RSX_SHADER_LIBRARY=str(library), RSX_SHADER_LIBRARY_PROFILE_LIMIT='1',
                   RSX_SHADER_LIBRARY_RESULT=str(work / 'compiled.tsv'), RSX_FINAL_DITHER=str(key[-1]))
        try:
            run_offline(engine, game_root, env, work / 'fragment.log')
            rows = [line.split() for line in (work / 'compiled.tsv').read_text().splitlines()]
            for job in members:
                try:
                    selected = [r for r in rows if len(r) == 5 and r[0] == 'GT5P_LIBRARY_V1' and
                                r[1] == f"{fnv64(job['fragment']):016x}" and r[2] == '2' and r[4] == '1']
                    if len(selected) != 1:
                        raise ValueError('Production compiler did not identify one independent profile result')
                    ps_key = selected[0][3]
                    ps = bounded_read(fresh / (ps_key + '.dxbc'), 4 * 1024 * 1024)
                    if not ps.startswith(b'DXBC'):
                        raise ValueError('Production result is not DXBC')
                    save_code(cache / (ps_key + '.dxbc'), ps)
                    compiled[job['id']] = (ps_key, ps)
                except (ValueError, OSError) as exc:
                    failures[job['id']] = str(exc)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            failures.update((job['id'], str(exc)) for job in members)
    return compiled, failures


def write_job(job, root, cache, compiler, vertices, compiled, target_path):
    work = root / job['id']; work.mkdir(exist_ok=True)
    state = job['state']
    if job['vertex_sha256'] not in vertices:
        vertices[job['vertex_sha256']] = compiler.vertex(job['vertex'], 1)
    hlsl, vs = vertices[job['vertex_sha256']]
    save_code(cache / f'{source_key(hlsl):016x}.dxbc', vs)
    ps_key, ps = compiled
    proof = work / 'pipeline'; proof.mkdir(exist_ok=True)
    (proof / 'request.recipe').write_bytes(request_envelope(vs, ps))
    (proof / f'code_{fnv64(vs):016x}.dxbc').write_bytes(vs)
    (proof / f'code_{fnv64(ps):016x}.dxbc').write_bytes(ps)
    (proof / 'material.state').write_text(
        f"GT5P_MATERIAL_V1 {state['blend']:x} {state['cmask']:x} {state['stencil']:x}\n", encoding='ascii')
    (proof / 'pass.state').write_text(f"GT5P_PASS_V1 {state['cull']:x}\n", encoding='ascii')
    target = native_target_fields(job.get('context', {}).get('target_path', target_path))
    (proof / 'target.state').write_text(f"GT5P_TARGET_V1 {target['rtfmt']} {target['sample_count']}\n", encoding='ascii')
    return dict(id=job['id'], vs=f'{fnv64(vs):016x}', ps=f'{fnv64(ps):016x}',
                vs_source=f'{source_key(hlsl):016x}', ps_source=ps_key)


def read_result(job, root, cache):
    result = json.loads((root / job['id'] / 'pipeline/result.json').read_text())
    if not (result.get('prepared') and result.get('native_applied') and result['expected'] == '0000000000000000'):
        raise ValueError('Capture-free native preparation failed: ' + str(result))
    pipeline = result['actual']
    blob = cache / f'pso_{pipeline}.bin'
    recipe = cache / 'warmup-v1' / f'pso_{pipeline}.recipe'
    if not blob.is_file() or not recipe.is_file():
        raise ValueError('Native pipeline created without a persistent driver blob and recipe')
    return dict(status='prepared', pipeline=pipeline, native_result=result, driver_blob_bytes=blob.stat().st_size)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('catalog', 'engine', 'decoder', 'game-root', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--object-pass-path', choices=('ccw', 'cw'))
    ap.add_argument('--native-target-path', choices=tuple(TARGET_PATHS))
    ap.add_argument('--global-sampler-path', choices=('active', 'fallback'))
    ap.add_argument('--context-set', choices=('supported', 'rgba16'),
                    help='Prepare the explicit supported context union instead of a single context')
    ap.add_argument('--limit', type=int, default=8, help='Unique candidates to prepare (0: all eligible; default 8)')
    ap.add_argument('--enumerate-only', action='store_true')
    ap.add_argument('--resume', action='store_true', help='Reuse shader bytecode; always validate driver pipelines again')
    args = ap.parse_args()
    if args.context_set:
        if args.object_pass_path or args.native_target_path or args.global_sampler_path:
            ap.error('--context-set cannot be combined with individual context choices')
    elif not args.object_pass_path or not args.native_target_path:
        ap.error('Choose --context-set or explicit --object-pass-path and --native-target-path')
    output = args.output.resolve()
    if len(str(output)) > 105:
        ap.error('Choose an output path of at most 105 characters for bounded Windows runtime paths')
    if args.limit < 0 or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Use a nonnegative limit and ignored output storage')
    for path in (args.catalog, args.engine, args.decoder, args.game_root):
        path = path.resolve()
        if path == output or path in output.parents or output in path.parents:
            ap.error('Output must be separate from all inputs and game root')
    if output.exists() and not args.resume:
        ap.error('Output already exists; choose a new directory or --resume')
    if b'gt5p.exe' in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq gt5p.exe', '/NH'], capture_output=True).stdout.lower():
        ap.error('Close the game before material preparation')
    identity = dict(schema=1, engine=hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                    decoder=hashlib.sha256(args.decoder.read_bytes()).hexdigest(), object_path=args.object_pass_path,
                    target_path=args.native_target_path, global_path=args.global_sampler_path)
    if args.context_set:
        identity.update(schema=2, context_set=args.context_set)
    if output.exists() and json.loads((output / 'identity.json').read_text()) != identity:
        ap.error('Preparation engine/decoder/context changed; choose a new output directory')
    started = time.perf_counter()
    if args.context_set:
        from shader_material_variants import enumerate_variants
        jobs, inventory = enumerate_variants(args.catalog, args.context_set, args.limit)
    else:
        jobs, inventory = enumerate_jobs(args.catalog, args.object_pass_path, args.native_target_path,
                                         args.global_sampler_path, args.limit)
    enumeration_seconds = time.perf_counter() - started
    output.mkdir(parents=True, exist_ok=True)
    (output / 'identity.json').write_text(json.dumps(identity, indent=2) + '\n')
    report = dict(**identity, inventory=inventory, selected_jobs=len(jobs), assumptions=ASSUMPTIONS,
                  timings_seconds=dict(enumeration=enumeration_seconds),
                  limitations=['Conditional ordinary-upload subset; actual live pass ownership is not established.',
                               'Catalogue source containers are not an exhaustive game asset inventory.',
                               'No claim of complete first-run coverage or measured stutter reduction.'], jobs=[])
    (output / 'manifest.json').write_text(json.dumps([
        {k: v for k, v in job.items() if k not in ('vertex', 'fragment')} for job in jobs], indent=2) + '\n')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not args.enumerate_only and not jobs:
        raise SystemExit('No eligible material candidates; inspect report.json')
    if not args.enumerate_only:
        cache = output / 'shadercache'; cache.mkdir(exist_ok=True)
        compiler = NativeCompiler(args.decoder.resolve())
        root = output / 'jobs'; root.mkdir(exist_ok=True)
        shader_root = output / 'shader-work'; shader_root.mkdir(exist_ok=True)
        phase_started = time.perf_counter()
        compiled, failures = compile_fragments(jobs, shader_root, cache, args.engine.resolve(), args.game_root.resolve())
        report['timings_seconds']['fragment_preparation'] = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        vertices, requests = {}, []
        for job in jobs:
            if job['id'] in failures:
                continue
            try:
                requests.append(write_job(job, root, cache, compiler, vertices, compiled[job['id']], args.native_target_path))
            except (ValueError, OSError) as exc:
                failures[job['id']] = str(exc)
        report['timings_seconds']['vertex_and_requests'] = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        for offset in range(0, len(requests), 4096):
            chunk = requests[offset:offset + 4096]
            (root / 'jobs.txt').write_text(''.join(r['id'] + '\n' for r in chunk), encoding='ascii')
            for request in chunk:
                (root / request['id'] / 'pipeline/result.json').write_text('{"prepared":false,"pending":true}\n')
            env = offline_env(args.game_root.resolve(), cache)
            env.update(RSX_PSO_PREPARE_BATCH=str(root), RSX_PSO_PREPARE_MATERIAL='1',
                       RSX_PSO_RECONSTRUCT_MATERIAL='1', RSX_PSO_RECONSTRUCT_PASS='1', RSX_PSO_RECONSTRUCT_NATIVE='1')
            print(f'Preparing {len(chunk)} native pipelines in one offline process', flush=True)
            try:
                run_offline(args.engine.resolve(), args.game_root.resolve(), env, output / f'pipeline-batch-{offset // 4096}.log',
                            timeout=max(180, min(3600, len(chunk) * 5)))
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                failures.update((request['id'], str(exc)) for request in chunk)
        report['timings_seconds']['native_preparation'] = time.perf_counter() - phase_started
        by_id = {r['id']: r for r in requests}
        for job in jobs:
            try:
                if job['id'] in failures:
                    raise ValueError(failures[job['id']])
                result = dict(**by_id[job['id']], **read_result(job, root, cache))
            except (ValueError, OSError) as exc:
                result = dict(id=job['id'], status='failed', reason=str(exc))
            report['jobs'].append(result)
    report['timings_seconds']['total'] = time.perf_counter() - started
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(selected=len(jobs), results=dict(Counter(j['status'] for j in report['jobs'])),
                          inventory=inventory), indent=2))
    if any(j['status'] != 'prepared' for j in report['jobs']):
        raise SystemExit('Partial material preparation; inspect report.json')


if __name__ == '__main__':
    main()
