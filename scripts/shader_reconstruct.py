"""Small, local asset-to-shader reconstruction proof; not a player precompiler.

Uses captured state and a recorded native descriptor as an oracle. Shader inputs
come from original asset slices, never captured raw programs or cached DXBC.
All outputs are local game-derived data and must remain in ignored storage.
"""
import argparse
import ctypes
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

from shader_coverage import ROOT, MAX_FP, bounded_read, fnv64, fp_identity


def vertex_programs(data):
    """Bounded SHDS 0x20 records with the wrapper observed in this disc build.

    Layout research: PDTools ShadersHeader/ShaderProgram_0x20 (MIT). The local
    reader validates table bounds and the observed instruction-count/code-offset
    wrapper; unsupported payloads are omitted rather than guessed as code.
    """
    start = 0
    while True:
        header = data.find(b'SHDS', start)
        if header < 0:
            return
        start = header + 4
        if header + 0x24 > len(data):
            continue
        count = struct.unpack_from('>H', data, header + 0x18)[0]
        table = struct.unpack_from('>I', data, header + 0x20)[0]
        model = data.rfind(b'MDL3', 0, header)
        for base in ([model, header] if model >= 0 else [header]):
            if not count or count > 8192 or not table or base + table + count * 40 > len(data):
                continue
            records = []
            for i in range(count):
                offset, size = struct.unpack_from('>II', data, base + table + i * 40)
                if not offset or size < 32 or size > MAX_FP + 32 or base + offset + size > len(data):
                    break
                records.append((base + offset, size))
            else:
                for offset, size in records:
                    instructions = struct.unpack_from('>H', data, offset)[0]
                    code = struct.unpack_from('>I', data, offset + 0x10)[0]
                    if not instructions or instructions > MAX_FP // 16 or code < 32 or code % 16:
                        continue
                    length = instructions * 16
                    if code + length <= size:
                        yield dict(header=header, offset=offset + code, size=length,
                                   wrapper=offset, wrapper_size=size)
                break


def word_swap(data):
    if len(data) % 4:
        raise ValueError('unaligned vertex instruction data')
    return b''.join(data[i:i + 4][::-1] for i in range(0, len(data), 4))


def discover_vertices(files, targets, progress=None):
    """Find candidates by exact instruction prefix; translation still must match."""
    matches = {}
    records = 0
    for number, path in enumerate(files):
        with path.open('rb') as stream:
            if not path.stat().st_size:
                continue
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for item in vertex_programs(data):
                    records += 1
                    body = data[item['offset']:item['offset'] + item['size']]
                    # Source bytes are big-endian words; also check native form
                    # explicitly so the report states which representation matched.
                    for order, code in [('native', body), ('swap32', word_swap(body))]:
                        for length, lookup in targets.items():
                            if len(code) >= length and code[:length] in lookup:
                                for raw_id in lookup[code[:length]]:
                                    matches.setdefault(raw_id, dict(file=str(path), order=order,
                                                                   sha256=hashlib.sha256(body).hexdigest(), **item))
        if progress and number % 100 == 0:
            progress(f'Asset containers {number + 1}/{len(files)}; vertex records {records}; matched inputs {len(matches)}')
    return matches, records


def read_slice(source):
    if source['size'] <= 0 or source['size'] > MAX_FP:
        raise ValueError('invalid asset slice size')
    with Path(source['file']).open('rb') as stream:
        stream.seek(source['offset'])
        data = stream.read(source['size'])
    if len(data) != source['size'] or hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('asset slice changed since indexing')
    return data


class NativeCompiler:
    def __init__(self, decoder):
        self.decoder = ctypes.CDLL(str(decoder.resolve()))
        for name in ('rsx_vp_decompile', 'rsx_vp_decompile_gpufetch'):
            function = getattr(self.decoder, name)
            function.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
            function.restype = ctypes.c_int
        self.compiler = ctypes.WinDLL('d3dcompiler_47.dll')
        self.compiler.D3DCompile.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p,
                                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
                                            ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
                                            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        self.compiler.D3DCompile.restype = ctypes.c_long

    @staticmethod
    def take_blob(blob):
        if not blob.value:
            return b''
        table = ctypes.cast(blob, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        pointer = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(table[3])(blob)
        size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(table[4])(blob)
        result = ctypes.string_at(pointer, size)
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(blob)
        return result

    def vertex(self, data, gpu):
        buffer = ctypes.create_string_buffer(data)
        output = ctypes.create_string_buffer(262144)
        name = 'rsx_vp_decompile_gpufetch' if gpu else 'rsx_vp_decompile'
        count = getattr(self.decoder, name)(buffer, len(data), output, len(output))
        if count <= 0:
            raise ValueError('asset vertex translation failed')
        source = output.value
        code, error = ctypes.c_void_p(), ctypes.c_void_p()
        text = ctypes.create_string_buffer(source)
        result = self.compiler.D3DCompile(text, len(source), b'guest_async', None, None,
                                          b'main', b'vs_5_0', 0, 0, ctypes.byref(code), ctypes.byref(error))
        dxbc, message = self.take_blob(code), self.take_blob(error)
        if result < 0 or not dxbc:
            raise ValueError('asset VS compilation failed: ' + message.decode(errors='replace')[:400])
        return source, dxbc


def offline_env(game_root, cache):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('FP_', 'VP_', 'RSX_', 'GT5P_', 'PAD_', 'PPU_', 'SPU_', 'D3D12_'))}
    env.pop('PS3_HEADLESS', None)
    env.update(GT5P_ROOT=str(game_root), GT5P_NO_SETTINGS='1', PS3_VERBOSE='0',
               FS_HIDE='grim/file/contents', GT5P_SHADER_PRECOMPILE_ONLY='1',
               RSX_SHADER_CACHE=str(cache), RSX_SHADER_WARMUP='1', RSX_PSO_ASYNC='0',
               RSX_SHADER_ASYNC='1', RSX_SHADER_WORKERS='2', RSX_PSO_PROVENANCE='0')
    return env


def run_offline(engine, game_root, env, log):
    with log.open('wb') as stream:
        subprocess.run([str(engine)], cwd=game_root, env=env, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)
    text = log.read_text(encoding='utf-8', errors='replace')
    if 'guest entry was not executed' not in text or '[GT5P] Executing' in text:
        raise ValueError('offline execution guard was not confirmed')
    return text


def prove_sample(row, candidate, sources, compiler, engine, game_root, cache, output):
    output.mkdir()
    capture = row['capture']
    state = capture['state']
    asset = read_slice(candidate)
    vertex = word_swap(asset) if candidate['order'] == 'swap32' else asset
    hlsl, vs = compiler.vertex(vertex, capture['vp_gpu'])
    (output / 'vertex-input.bin').write_bytes(vertex)
    (output / 'vertex.hlsl').write_bytes(hlsl)
    if f'{fnv64(hlsl):016x}' != capture['vp_hlsl']:
        raise ValueError('asset vertex HLSL differs from captured source')
    if f'{fnv64(vs):016x}' != capture['vs']:
        raise ValueError('rebuilt vertex bytecode differs from captured identifier')

    digest = row['payloads'][0]
    # Independently reread the original indexed container, not the .fp cache.
    fragment_source = dict(sources[digest][0], sha256=digest)
    fragment = read_slice(fragment_source)
    library = output / 'library'; library.mkdir()
    (library / 'asset.fp').write_bytes(fragment)
    fresh = output / 'shadercache'; fresh.mkdir()
    profiles = fresh / 'fp-profiles-v2'; profiles.mkdir()
    fields = [state['exp32'], state['cube'], state['stencil'] & (1 << 26), 0,
              int(state['samplers'], 16), state['ghi'], state['shd'], state['unhi'], fp_identity(fragment)['textures']]
    (profiles / 'captured-state.txt').write_text(' '.join(f'{x:x}' for x in fields) + '\n', encoding='ascii')
    env = offline_env(game_root, fresh)
    env.update(RSX_SHADER_LIBRARY=str(library), RSX_SHADER_LIBRARY_PROFILE_LIMIT='1')
    # The legacy offline FP entry point uses one R8 target. Reproduce the
    # captured pass's final-dither decision explicitly for other targets/MRT.
    env['RSX_FINAL_DITHER'] = '1' if state['rtfmt'] == 28 and state['nrt'] == 1 and state['cmask'] & 0xe else '0'
    log = run_offline(engine, game_root, env, output / 'fragment-compile.log')
    if not re.search(r'finished: programs=1 attempts=\d+ rejected=0 compiled=\d+', log):
        raise ValueError('offline fragment pass was incomplete or rejected inputs')
    # Require the exact translated-source key as well as the resulting bytecode
    # hash. Merely finding some matching bytecode in the startup cache is weaker.
    ps = bounded_read(fresh / (capture['fp_cache'] + '.dxbc'), 4 * 1024 * 1024)
    if f'{fnv64(ps):016x}' != capture['ps']:
        raise ValueError('fresh offline fragment bytecode did not match capture')
    # Only independently rebuilt bytes enter the proof folder. Cached DXBC is
    # never read or copied. The recorded descriptor remains an explicit oracle.
    proof = output / 'pipeline'; proof.mkdir()
    recipe = cache / 'warmup-v1' / f"pso_{capture['pipeline']}.recipe"
    shutil.copy2(recipe, proof / 'request.recipe')
    (proof / f"code_{capture['vs']}.dxbc").write_bytes(vs)
    (proof / f"code_{capture['ps']}.dxbc").write_bytes(ps)
    env = offline_env(game_root, output / 'proof-cache')
    env['RSX_PSO_RECONSTRUCT'] = str(proof)
    run_offline(engine, game_root, env, output / 'pipeline-create.log')
    result = json.loads((proof / 'result.json').read_text())
    if result['expected'] != capture['pipeline'] or result['actual'] != capture['pipeline'] or not result['created']:
        raise ValueError(f'Rebuilt pipeline key/creation failed: {result}')
    return dict(pipeline=capture['pipeline'], vertex_asset=candidate, fragment_asset=fragment_source,
                vs=capture['vs'], ps=capture['ps'], vertex_hlsl_matches=True, fragment_source_key_matches=True,
                native_result=result, state_origin='captured translation profile and native recipe',
                shader_input_origin='original asset slices; no captured raw inputs or cached DXBC used for compilation')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--report', required=True, type=Path, help='Verified provenance audit containing capture records')
    ap.add_argument('--trace', required=True, type=Path, help='Matching provenance directory (input matching only)')
    ap.add_argument('--catalog', required=True, type=Path)
    ap.add_argument('--cache', required=True, type=Path)
    ap.add_argument('--decoder', required=True, type=Path, help='Production vertex decoder DLL')
    ap.add_argument('--engine', required=True, type=Path, help='EXE supporting RSX_PSO_RECONSTRUCT')
    ap.add_argument('--game-root', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path, help='New ignored output directory')
    ap.add_argument('--samples', type=int, default=3, choices=range(1, 9))
    ap.add_argument('--start-line', type=int, default=0, help='First capture line eligible for a proof sample')
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose a new output directory in gitignored storage')
    for path in (args.trace, args.catalog, args.cache, args.game_root):
        path = path.resolve()
        if output == path or path in output.parents or output in path.parents:
            ap.error('Output must be separate from inputs/game root')
    if b'gt5p.exe' in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq gt5p.exe', '/NH'], capture_output=True).stdout.lower():
        ap.error('Close the game before offline reconstruction')
    rows = json.loads(args.report.read_text())['records']
    index = json.loads((args.catalog / 'index.json').read_text())
    sources = {}
    for item in index['sources']:
        sources.setdefault(item['sha256'], []).append(item)
    targets = {}
    for row in rows:
        if row['status'] != 'recipe_link_verified' or not row.get('vertex_input_available'):
            continue
        c = row['capture']
        raw = bounded_read(args.trace / f"vp_{c['vp_raw']}.bin", MAX_FP)
        if f'{fnv64(raw):016x}' != c['vp_raw']:
            raise ValueError('captured VP input failed integrity check')
        prefix = raw[:c['vp_identity_bytes']]
        if len(prefix) >= 32:
            targets.setdefault(len(prefix), {}).setdefault(prefix, set()).add(c['vp_raw'])
    files = [Path(p) for p in sorted({x['file'] for x in index['sources']})]
    matches, count = discover_vertices(files, targets, lambda text: print(text, flush=True))
    output.mkdir(parents=True)
    report = dict(vertex_records=count, matched_vertex_inputs=len(matches), candidates=matches, samples=[],
                  limitations=['Source container set comes from the existing FP catalogue, not an exhaustive asset inventory.',
                               'Rendering state/native descriptor is captured, not reconstructed from material definitions.',
                               'This is a bounded sample, not a complete distributable catalogue.'])
    compiler = NativeCompiler(args.decoder)
    pairs = set()
    for row in rows:
        if row['status'] != 'recipe_link_verified' or not row.get('fragment_asset_match') or row['line'] < args.start_line:
            continue
        c = row['capture']; state = c['state']
        if c['vp_raw'] not in matches or c['fp_flags'] or state['unnorm']:
            continue  # This proof's offline FP profile has these explicit limits.
        pair = (c['vs'], c['ps'])
        if pair in pairs:
            continue
        pairs.add(pair)
        number = len(report['samples'])
        print(f'Proving sample {number + 1}: {c["pipeline"]}', flush=True)
        try:
            result = prove_sample(row, matches[c['vp_raw']], sources, compiler,
                                  args.engine.resolve(), args.game_root.resolve(), args.cache.resolve(),
                                  output / f'sample-{number + 1}')
            result['status'] = 'verified'
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            result = dict(pipeline=c['pipeline'], status='failed', reason=str(exc))
        report['samples'].append(result)
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if len(report['samples']) >= args.samples:
            break
    if len(report['samples']) != args.samples or any(s['status'] != 'verified' for s in report['samples']):
        raise SystemExit(f'Partial/failed proof; inspect {output / "report.json"}')
    print(f'Verified {args.samples} independently rebuilt shader pairs and native pipeline keys/creation: {output}', flush=True)


if __name__ == '__main__':
    main()

