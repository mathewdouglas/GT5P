"""Automatically enumerate embedded named banks and prepare CPU vertex shaders.

No captures, car/track visits, pass names or bank offsets are inputs. Fragment
profiles/targets remain unresolved and no complete pipeline coverage is claimed.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import subprocess

from shader_coverage import ROOT, fnv64, fp_identity, bounded_read
from shader_reconstruct import NativeCompiler, word_swap, offline_env, run_offline
from shader_shared_passes import bank_pairs
from shader_shared_profiles import DISC_SHA256, colour_correct_profile, convolution_profile, ASSUMPTIONS
from shader_pass_state import native_target_fields
from prepare_material_shaders import save_code, source_key, request_envelope, compile_fragments, read_result


def enumerate_banks(data):
    pairs, rejected = [], []
    start = 0
    while True:
        base = data.find(b'SHDS', start)
        if base < 0:
            return pairs, rejected
        start = base + 4
        try:
            pairs.extend(bank_pairs(data, base))
        except (ValueError, UnicodeError) as exc:
            rejected.append(dict(header=base, reason=str(exc)))


def prepare_pipelines(args, data, pairs, cache, vertices):
    """Enumerate only the independently supported distinct-target context rule."""
    if hashlib.sha256(data).hexdigest() != DISC_SHA256:
        raise ValueError('Shared pass rules are validated only for the measured disc ELF')
    names = ('ColorCorrect', 'Convolution_8')
    selected = [p for p in pairs if p['name'] in names and p['tag'] == 0]
    if len(selected) != len(names) or {p['name'] for p in selected} != set(names):
        raise ValueError('Expected unambiguous authored pairs for each supported shared rule')
    by_name = {p['name']: p for p in selected}
    targets = ('rgba16-single', 'rgba16-msaa2') + (('rgba8-single',) if args.context_set == 'supported' else ())
    jobs = []
    depths = (True, False) if args.depth_context == 'both' else (args.depth_context == 'backed',)
    for pair in selected:
        f = pair['fragment']
        fragment = data[f['offset']:f['offset'] + f['size']]
        if fp_identity(fragment)['textures'] != 1:
            raise ValueError('Shared sampled units differ from supported rule')
        gammas = tuple(itertools.product(range(2), range(2))) if pair['name'] == 'ColorCorrect' else ((0, 0), (1, 1))
        for target, (output_gamma, read_gamma), depth_backed in itertools.product(targets, gammas, depths):
            state = (colour_correct_profile(pair, target, output_gamma, read_gamma, depth_backed)
                     if pair['name'] == 'ColorCorrect' else convolution_profile(pair, target, read_gamma, depth_backed))
            context = dict(pass_name=pair['name'], target_path=target, output_gamma=output_gamma, read_gamma=read_gamma,
                           source='successful-rgba8-framebuffer-2d', source_equals_target=False, depth_backed=depth_backed)
            identity = dict(vertex=pair['vertex']['sha256'], fragment=f['sha256'],
                            input_mask=pair['vertex_input_mask'], state=state, context=context)
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            jobs.append(dict(id=key, state=state, context=context, used=1, fragment=fragment,
                             fragment_sha256=f['sha256']))
    root = args.output.resolve() / 'pipelines'
    root.mkdir(exist_ok=True)
    (root / 'manifest.json').write_text(json.dumps([
        {k: v for k, v in job.items() if k != 'fragment'} for job in jobs], indent=2))
    compiled, failures = compile_fragments(jobs, root, cache, args.engine.resolve(), args.game_root.resolve(),mode=args.fragment_mode)
    requests = []
    for job in jobs:
        if job['id'] in failures:
            continue
        pair = by_name[job['context']['pass_name']]
        vertex = vertices[pair['vertex']['sha256']]
        vs = bounded_read(cache / (vertex['source_key'] + '.dxbc'), 4 * 1024 * 1024)
        proof = root / job['id'] / 'pipeline'
        proof.mkdir(parents=True, exist_ok=True)
        ps_key, ps = compiled[job['id']]
        (proof / 'request.recipe').write_bytes(request_envelope(vs, ps))
        (proof / f'code_{fnv64(vs):016x}.dxbc').write_bytes(vs)
        (proof / f'code_{fnv64(ps):016x}.dxbc').write_bytes(ps)
        (proof / 'material.state').write_text('GT5P_MATERIAL_V1 0 f f0000000\n')
        (proof / 'pass.state').write_text('GT5P_PASS_V1 0\n')
        target = native_target_fields(job['context']['target_path'])
        (proof / 'target.state').write_text(f"GT5P_TARGET_V2 {target['rtfmt']} {target['sample_count']} {int(job['context']['depth_backed'])}\n")
        (proof / 'input.state').write_text(f"GT5P_INPUT_V1 {pair['vertex_input_mask']:08x}\n")
        (proof / 'result.json').write_text('{"prepared":false,"pending":true}\n')
        requests.append(job)
    (root / 'jobs.txt').write_text(''.join(j['id'] + '\n' for j in requests))
    if requests:
        env = offline_env(args.game_root.resolve(), cache)
        env.update(RSX_PSO_PREPARE_BATCH=str(root), RSX_PSO_PREPARE_MATERIAL='1',
                   RSX_PSO_RECIPE_KEEP_DAYS='0',
                   RSX_PSO_RECONSTRUCT_MATERIAL='1', RSX_PSO_RECONSTRUCT_PASS='1',
                   RSX_PSO_RECONSTRUCT_NATIVE='1', RSX_PSO_RECONSTRUCT_INPUT='1')
        run_offline(args.engine.resolve(), args.game_root.resolve(), env, root / 'native.log')
    results = []
    for job in jobs:
        try:
            if job['id'] in failures:
                raise ValueError(failures[job['id']])
            result = read_result(job, root, cache)
            if not result['native_result'].get('input_applied'):
                raise ValueError('Native engine did not reconstruct CPU inputs')
            results.append(dict(id=job['id'], context=job['context'], **result))
        except (ValueError, OSError) as exc:
            results.append(dict(id=job['id'], context=job['context'], status='failed', reason=str(exc)))
    return dict(rules=list(names), assumptions=ASSUMPTIONS, jobs=results,
                limitation='Conditional context candidates; actual draw ownership and whole-game coverage unproven.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fragment-mode',choices=('legacy','batch'),default='legacy')
    ap.add_argument('--elf', required=True, type=Path)
    ap.add_argument('--decoder', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--pipelines', action='store_true', help='Prepare supported conditional shared pipelines without captures')
    ap.add_argument('--engine', type=Path)
    ap.add_argument('--game-root', type=Path)
    ap.add_argument('--context-set', choices=('rgba16', 'supported'), default='rgba16')
    ap.add_argument('--depth-context', choices=('backed', 'colour-only', 'both'), default='both')
    ap.add_argument('--resume', action='store_true', help='Revalidate/reuse matching output and driver cache')
    args = ap.parse_args()
    if args.pipelines and (not args.engine or not args.game_root):
        ap.error('--pipelines requires --engine and --game-root')
    output = args.output.resolve()
    if args.pipelines and len(str(output)) > 100:
        ap.error('Use an output path of at most 100 characters for native compiler paths')
    if (output.exists() and not args.resume) or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose a new ignored output directory or --resume matching output')
    for path in (args.elf.resolve(), args.decoder.resolve(),
                 *([args.engine.resolve(), args.game_root.resolve()] if args.pipelines else [])):
        if output == path or output in path.parents or path in output.parents:
            ap.error('Output must be separate from inputs')
    data = args.elf.read_bytes()
    config = dict(elf_sha256=hashlib.sha256(data).hexdigest(),
                  decoder_sha256=hashlib.sha256(args.decoder.read_bytes()).hexdigest(),
                  engine_sha256=hashlib.sha256(args.engine.read_bytes()).hexdigest() if args.pipelines else None,
                  pipelines=args.pipelines, context_set=args.context_set, depth_context=args.depth_context,
                  rule_set_version=2)
    if args.resume:
        previous = json.loads((output / 'report.json').read_text())
        if previous.get('config') != config:
            ap.error('Resume ELF/decoder/engine/context configuration differs')
    pairs, rejected = enumerate_banks(data)
    if not pairs:
        ap.error('No supported named shader banks found')
    output.mkdir(parents=True, exist_ok=True)
    cache = output / 'shadercache'
    cache.mkdir(exist_ok=True)
    compiler = NativeCompiler(args.decoder)
    vertices, failed = {}, []
    for pair in pairs:
        vertex = pair['vertex']
        digest = vertex['sha256']
        if digest in vertices or any(f['vertex_sha256'] == digest for f in failed):
            continue
        try:
            code = data[vertex['offset']:vertex['offset'] + vertex['size']]
            if hashlib.sha256(code).hexdigest() != digest:
                raise ValueError('Vertex slice integrity failure')
            hlsl, dxbc = compiler.vertex(word_swap(code), 0)
            key = source_key(hlsl)
            save_code(cache / f'{key:016x}.dxbc', dxbc)
            vertices[digest] = dict(source_key=f'{key:016x}', bytecode_hash=f'{fnv64(dxbc):016x}',
                                    bytecode_bytes=len(dxbc), gpu_fetch=False)
        except (ValueError, OSError) as exc:
            failed.append(dict(vertex_sha256=digest, reason=str(exc)))
    report = dict(schema=1, config=config, origin='Original embedded named SHDS banks; no captures or learned profiles.',
                  source=str(args.elf.resolve()), elf_sha256=hashlib.sha256(data).hexdigest(),
                  decoder_sha256=hashlib.sha256(args.decoder.read_bytes()).hexdigest(),
                  pairs=pairs, rejected_banks=rejected, vertices=vertices, failures=failed,
                  scope='CPU vertex shader preparation only. No complete pipeline requests generated.',
                  unresolved=['Actual pass/resource ownership and later overrides',
                              'Fragment translation profile, texture binding/gamma/alias facts',
                              'Output target/depth/stencil context and full native descriptor'])
    pipeline_failed = False
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if args.pipelines and not failed:
        try:
            report['pipelines'] = prepare_pipelines(args, data, pairs, cache, vertices)
            report['scope'] = 'CPU vertex preparation plus explicitly conditional capture-free shared pipelines.'
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            report['pipelines'] = dict(error=str(exc), jobs=[])
            pipeline_failed = True
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{len(pairs)} authored pairs; {len(vertices)} CPU vertex programs prepared; {len(failed)} failures; {len(rejected)} unsupported banks')
    if args.pipelines:
        native_jobs = report.get('pipelines', {}).get('jobs', [])
        print(f"Shared pipeline requests: {len(native_jobs)}; prepared: {sum(j['status'] == 'prepared' for j in native_jobs)}")
    if failed or pipeline_failed or any(j['status'] != 'prepared' for j in report.get('pipelines', {}).get('jobs', ())):
        raise SystemExit('Partial shared preparation; inspect report.json')


if __name__ == '__main__':
    main()
