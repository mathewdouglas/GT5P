"""Small, local asset-to-shader reconstruction proof; not a player precompiler.

Uses remaining captured state and a recorded native descriptor as an oracle. Shader inputs
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
           if not k.startswith(('FP_', 'VP_', 'RSX_', 'GT5P_', 'PAD_', 'PPU_', 'SPU_', 'D3D12_', 'CULL_'))}
    env.pop('PS3_HEADLESS', None)
    env.update(GT5P_ROOT=str(game_root), GT5P_NO_SETTINGS='1', PS3_VERBOSE='0',
               FS_HIDE='grim/file/contents', GT5P_SHADER_PRECOMPILE_ONLY='1',
               RSX_SHADER_CACHE=str(cache), RSX_SHADER_WARMUP='1', RSX_PSO_ASYNC='0',
               RSX_SHADER_ASYNC='1', RSX_SHADER_WORKERS='2', RSX_PSO_PROVENANCE='0')
    return env


def run_offline(engine, game_root, env, log, timeout=180):
    if b'gt5p.exe' in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq gt5p.exe', '/NH'], capture_output=True).stdout.lower():
        raise ValueError('Another gt5p.exe is running; offline preparation did not start')
    with log.open('wb') as stream:
        subprocess.run([str(engine)], cwd=game_root, env=env, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)
    text = log.read_text(encoding='utf-8', errors='replace')
    if 'guest entry was not executed' not in text or '[GT5P] Executing' in text:
        raise ValueError('offline execution guard was not confirmed')
    return text


def material_state_matches(values, capture):
    from shader_material_state import captured_state, FIELDS
    expected = captured_state(capture)
    return (not values['stencil_enable'] and not (capture['state']['stencil'] & ((1 << 26) | 1)) and
            all(values[f] == expected[f] for f in FIELDS))


def prove_sample(row, candidate, sources, compiler, engine, game_root, cache, output, material=None,
                 prepared=None, material_samplers=False, sampler_lanes=False, global_sampler_path=None,
                 shadow_sampler_path=None, environment_sampler_path=None, mirror_sampler_path=None, material_texture_shapes=False, material_texture_state=False, environment_texture_path=None, object_pass_path=None, native_target_path=None, material_fragment_control=False, independent_profile_path=None):
    output.mkdir()
    capture = row['capture']
    state = dict(capture['state'])
    sampler_origin = None
    shape_origin = None
    pass_origin = None
    target_origin = None
    fragment_control_origin = None
    independent_origin = None
    if prepared:
        from shader_material_state import prepare_state, decode_state
        raw = read_slice(prepared['source'])
        values = decode_state(prepare_state(struct.unpack('>40I', raw)))
        if not material_state_matches(values, capture):
            raise ValueError('reparsed prepared material state differs from captured oracle')
        state.update(blend=values['blend'], cmask=values['cmask'],
                     stencil=(state['stencil'] & 0x0FFFFFFF) | values['depth_bits'])
    if object_pass_path:
        from shader_pass_state import object_pass_fields, pass_matches, replace_pass_fields
        if not prepared:
            raise ValueError('Object pass proof requires prepared material state')
        pass_origin = object_pass_fields(object_pass_path, values)
        if not pass_matches(pass_origin, capture['state']):
            raise ValueError('conditional object pass differs from captured oracle')
        state = replace_pass_fields(pass_origin, state)
    if native_target_path:
        from shader_pass_state import native_target_fields, target_matches, replace_target_fields
        if not pass_origin:
            raise ValueError('Native construction requires an explicit object pass')
        target_origin = native_target_fields(native_target_path)
        if not target_matches(target_origin, capture):
            raise ValueError('explicit native target differs from captured oracle')
        state = replace_target_fields(target_origin, state)
    if material_samplers or sampler_lanes:
        from shader_material_textures import model_textures, complete_sampler_key, known_sampler_key, with_global_sampler_path
        # Reparse the original definition and bindings. A saved audit/captured
        # sampler value is never used to construct the replacement key.
        with Path(candidate['file']).open('rb') as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                definitions, _ = model_textures(data, material['model'])
                definition = next((d for d in definitions if d['definition'] == prepared['definition'] and
                                   d['material'] == material['material']), None)
                if definition is None:
                    raise ValueError('selected material texture definition is no longer available')
                original_globals = definition['globals']
                definition = with_global_sampler_path(definition, global_sampler_path, shadow_sampler_path, environment_sampler_path, mirror_sampler_path, environment_texture_path)
                if material_texture_shapes or material_texture_state:
                    from shader_texture_shapes import texture_fields, shape_matches, replace_shape_fields
                    shape_origin = texture_fields(definition, material_texture_state)
                    if not shape_matches(shape_origin, capture['state']):
                        raise ValueError('reparsed texture shape bits differ from captured oracle')
                    state.update(replace_shape_fields(shape_origin, state))
                known, mask = known_sampler_key(definition)
                captured_key = int(capture['state']['samplers'], 16)
                if sampler_lanes and not mask:
                    raise ValueError('selected material no longer resolves any sampled sampler lanes')
                key = ((captured_key & ~mask) | known) if sampler_lanes else complete_sampler_key(definition)
                sampler_origin = dict(definition=definition['definition'], used=definition['used'],
                                      bindings=definition['bindings'], globals=original_globals,
                                      unresolved_globals=definition['globals'], global_sampler_path=global_sampler_path,
                                      shadow_sampler_path=shadow_sampler_path, environment_sampler_path=environment_sampler_path, mirror_sampler_path=mirror_sampler_path,
                                      partial=bool(sampler_lanes), derived_lane_mask=mask,
                                      unresolved_sampled_mask=sum(15 << (4 * unit) for unit in range(16)
                                                                  if definition['used'] & (1 << unit)) & ~mask,
                                      captured_lane_mask=(0xFFFFFFFFFFFFFFFF ^ mask) if sampler_lanes else 0)
        if key is None or key != int(capture['state']['samplers'], 16):
            raise ValueError('reconstructed sampler key differs from captured oracle')
        state['samplers'] = f'{key:016x}'
    if material_fragment_control:
        if not material:
            raise ValueError('Fragment control requires an original material pair')
        control_source = material['fragment_control_source']
        control = struct.unpack('>I', read_slice(control_source))[0]
        exp32 = int(bool(control & 0x40))
        if exp32 != capture['state']['exp32']:
            raise ValueError('authored compact fragment export precision differs from captured oracle')
        state['exp32'] = exp32
        fragment_control_origin = dict(source=control_source, control=control, exp32=exp32,
                                       assumption='compact descriptor binding with no later shader-control override')
    if independent_profile_path:
        from shader_material_profile import ordinary_profile, profile_matches, ASSUMPTIONS
        independent = ordinary_profile(definition, values, control, object_pass_path, native_target_path)
        if not profile_matches(independent, capture['state']):
            raise ValueError('independent conditional translation profile differs from captured oracle')
        state = independent  # No captured state survives in the constructed profile.
        independent_origin = dict(path=independent_profile_path, state=independent, assumptions=ASSUMPTIONS)
    asset = read_slice(candidate)
    vertex = word_swap(asset) if candidate['order'] == 'swap32' else asset
    hlsl, vs = compiler.vertex(vertex, 1 if target_origin else capture['vp_gpu'])
    (output / 'vertex-input.bin').write_bytes(vertex)
    (output / 'vertex.hlsl').write_bytes(hlsl)
    if f'{fnv64(hlsl):016x}' != capture['vp_hlsl']:
        raise ValueError('asset vertex HLSL differs from captured source')
    if f'{fnv64(vs):016x}' != capture['vs']:
        raise ValueError('rebuilt vertex bytecode differs from captured identifier')

    digest = row['payloads'][0]
    # Independently reread the original indexed container, not the .fp cache.
    fragment_source = (material['fragment'] if material else dict(sources[digest][0], sha256=digest))
    fragment = read_slice(fragment_source)
    library = output / 'library'; library.mkdir()
    (library / 'asset.fp').write_bytes(fragment)
    fresh = output / 'shadercache'; fresh.mkdir()
    profiles = fresh / 'fp-profiles-v2'; profiles.mkdir()
    fields = [state['exp32'], state['cube'], state['stencil'] & (1 << 26), state['unnorm'] & ~0x100,
              int(state['samplers'], 16), state['ghi'], state['shd'], state['unhi'], fp_identity(fragment)['textures']]
    (profiles / ('independent-state.txt' if independent_origin else 'captured-state.txt')).write_text(' '.join(f'{x:x}' for x in fields) + '\n', encoding='ascii')
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
    if prepared:
        (proof / 'material.state').write_text(
            f"GT5P_MATERIAL_V1 {values['blend']:x} {values['cmask']:x} {values['depth_bits']:x}\n", encoding='ascii')
    if pass_origin:
        (proof / 'pass.state').write_text(f"GT5P_PASS_V1 {pass_origin['cull']:x}\n", encoding='ascii')
    if target_origin:
        (proof / 'target.state').write_text(
            f"GT5P_TARGET_V1 {target_origin['rtfmt']} {target_origin['sample_count']}\n", encoding='ascii')
    (proof / f"code_{capture['vs']}.dxbc").write_bytes(vs)
    (proof / f"code_{capture['ps']}.dxbc").write_bytes(ps)
    env = offline_env(game_root, output / 'proof-cache')
    env['RSX_PSO_RECONSTRUCT'] = str(proof)
    if prepared:
        env['RSX_PSO_RECONSTRUCT_MATERIAL'] = '1'
    if pass_origin:
        env['RSX_PSO_RECONSTRUCT_PASS'] = '1'
    if target_origin:
        env['RSX_PSO_RECONSTRUCT_NATIVE'] = '1'
    run_offline(engine, game_root, env, output / 'pipeline-create.log')
    result = json.loads((proof / 'result.json').read_text())
    if result['expected'] != capture['pipeline'] or result['actual'] != capture['pipeline'] or not result['created']:
        raise ValueError(f'Rebuilt pipeline key/creation failed: {result}')
    if prepared and not result.get('material_applied'):
        raise ValueError('engine did not replace native descriptor fields from material state')
    if pass_origin and not result.get('pass_applied'):
        raise ValueError('engine did not replace native cull fields from pass candidate')
    if target_origin and not result.get('native_applied'):
        raise ValueError('engine did not construct a fresh native descriptor')
    return dict(pipeline=capture['pipeline'], vertex_asset=candidate, fragment_asset=fragment_source,
                vs=capture['vs'], ps=capture['ps'], vertex_hlsl_matches=True, fragment_source_key_matches=True,
                native_result=result,
                material_state=({**prepared, 'values': values} if prepared else None),
                sampler_origin=sampler_origin, texture_shape_origin=shape_origin, object_pass_origin=pass_origin, native_target_origin=target_origin,
                fragment_control_origin=fragment_control_origin, independent_profile_origin=independent_origin,
                native_descriptor_origin='fresh independent construction' if target_origin else 'captured with reported replacements',
                replaced_translation_fields=(['sampler_lanes'] if sampler_lanes else ['samplers'] if material_samplers else []) +
                                            (['texture_sampling_bits'] if material_texture_state else ['texture_shape_bits'] if material_texture_shapes else []) + (['output_gamma_bit'] if pass_origin else []) +
                                            (['target_sample_bits'] if target_origin else []) +
                                            (['export_precision'] if fragment_control_origin else []) +
                                            (['whole_translation_profile'] if independent_origin else []),
                replaced_descriptor_fields=(['blend', 'colour_write_mask', 'depth_compare', 'depth_write_mask'] if prepared else []) +
                                           (['cull_mode', 'front_counter_clockwise'] if pass_origin else []) +
                                           (['all_other_native_descriptor_fields'] if target_origin else []),
                state_origin=('independent conditional translation profile and fresh native descriptor' if independent_origin else
                              'prepared material and reported conditional fields; native descriptor fresh when requested; remaining translation state captured'
                              if prepared else 'captured translation profile and native recipe'),
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
    ap.add_argument('--materials', type=Path, help='Require an authored pair from shader_materials.py report')
    ap.add_argument('--prepared-material-state', action='store_true',
                    help='Require material state and replace native blend/write-mask/depth fields')
    ap.add_argument('--material-samplers', action='store_true',
                    help='Require every sampled unit resolved by the same material and derive its sampler key')
    ap.add_argument('--material-sampler-lanes', action='store_true',
                    help='Partial proof: derive known material lanes; retain other lanes explicitly from capture')
    ap.add_argument('--global-sampler-path', choices=('active', 'fallback'),
                    help='Conditional dither/PCF binding path; never inferred from captured state')
    ap.add_argument('--shadow-sampler-path', choices=('shadow-lv',),
                    help='Conditional LV shadow-pass sampler settings; not assumed for every draw')
    ap.add_argument('--environment-sampler-path', choices=('framebuffer-single', 'framebuffer-mipped'),
                    help='Conditional successful framebuffer setup; no later sampler overrides')
    ap.add_argument('--mirror-sampler-path', choices=('scene-copy',),
                    help='Partial mirror filter bits; wrap stays unresolved')
    ap.add_argument('--material-texture-shapes', action='store_true',
                    help='Derive supported local cube/volume bits; retain unknown shape and unrelated bits explicitly')
    ap.add_argument('--material-texture-state', action='store_true',
                    help='Derive shape, read gamma and upper-unit coordinate bits under default switches')
    ap.add_argument('--environment-texture-path', choices=('framebuffer-2d', 'framebuffer-cube'),
                    help='Explicit successfully initialized framebuffer shape; incoming gamma stays unknown')
    ap.add_argument('--object-pass-path', choices=('ccw', 'cw'),
                    help='Conditional object wrapper winding/output gamma; no later overrides')
    from shader_pass_state import TARGET_PATHS
    ap.add_argument('--native-target-path', choices=tuple(TARGET_PATHS),
                    help='Construct fresh GPU-fetch, depth-backed single-target descriptor for explicit candidate')
    ap.add_argument('--material-fragment-control', action='store_true',
                    help='Derive export precision from authored compact fragment descriptor; no later override')
    ap.add_argument('--independent-profile-path', choices=('ordinary-uploads',),
                    help='Build whole conditional translation profile from assets and explicit context; reject unknowns')
    args = ap.parse_args()
    if args.independent_profile_path and not (args.native_target_path and args.material_fragment_control and
                                              args.material_texture_state and args.material_samplers):
        ap.error('Independent profile requires native target, fragment control, texture state and complete samplers')
    if args.material_fragment_control and not args.materials:
        ap.error('Material fragment control requires --materials')
    if args.native_target_path and not args.object_pass_path:
        ap.error('Native target construction requires --object-pass-path')
    if args.object_pass_path and not args.prepared_material_state:
        ap.error('Object pass requires --prepared-material-state')
    if args.environment_texture_path and (not args.environment_sampler_path or not (args.material_texture_shapes or args.material_texture_state)):
        ap.error('Environment texture path requires framebuffer sampler and texture reconstruction options')
    if (args.material_texture_shapes or args.material_texture_state) and not (args.material_samplers or args.material_sampler_lanes):
        ap.error('Texture state reconstruction requires a material sampler proof')
    if args.prepared_material_state and not args.materials:
        ap.error('--prepared-material-state requires --materials')
    if (args.material_samplers or args.material_sampler_lanes) and not args.prepared_material_state:
        ap.error('Material sampler proofs require --prepared-material-state')
    if args.material_samplers and args.material_sampler_lanes:
        ap.error('Choose complete samplers or partial sampler lanes, not both')
    if (args.global_sampler_path or args.shadow_sampler_path or args.environment_sampler_path or args.mirror_sampler_path) and not (args.material_samplers or args.material_sampler_lanes):
        ap.error('Global/shadow/environment/mirror sampler paths require a material sampler proof')
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose a new output directory in gitignored storage')
    for path in (args.trace, args.catalog, args.cache, args.game_root, args.report,
                 *([args.materials] if args.materials else [])):
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
    materials = {}
    if args.materials:
        # Reparse each selected material from the original asset, rather than
        # trusting offsets or match claims in a saved diagnostic report.
        from shader_materials import model_pairs
        from shader_material_state import model_states
        from shader_material_textures import model_textures, complete_sampler_key, known_sampler_key, with_global_sampler_path
        for item in json.loads(args.materials.read_text())['pairs']:
            if not item['captured_pair_matches']:
                continue
            key = (item['file'], item['model'])
            if key not in materials:
                with Path(item['file']).open('rb') as stream:
                    with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                        parsed, _ = model_pairs(data, item['model'])
                        if args.prepared_material_state:
                            states, bindings, _ = model_states(data, item['model'], prepare=True)
                            base = item['model']
                            table = struct.unpack_from('>I', data, base + 0x44)[0]
                            state_table = struct.unpack_from('>I', data, base + table + 16)[0]
                        texture_shapes = {}
                        texture_keys = {}
                        texture_lanes = {}
                        texture_definitions = {}
                        if args.material_samplers or args.material_sampler_lanes:
                            textures, _ = model_textures(data, item['model'])
                            textures = [with_global_sampler_path(d, args.global_sampler_path, args.shadow_sampler_path, args.environment_sampler_path, args.mirror_sampler_path, args.environment_texture_path) for d in textures]
                            from shader_texture_shapes import texture_fields, shape_matches
                            if args.material_texture_shapes or args.material_texture_state:
                                texture_shapes = {d['definition']: texture_fields(d, args.material_texture_state) for d in textures}
                            texture_definitions = {d['definition']: d for d in textures}
                            texture_keys = {d['definition']: complete_sampler_key(d) for d in textures}
                            texture_lanes = {d['definition']: known_sampler_key(d) for d in textures}
                        candidates = []
                        for pair in parsed:
                            def source(offset, size):
                                body = data[offset:offset + size]
                                return dict(file=item['file'], offset=offset, size=size,
                                            sha256=hashlib.sha256(body).hexdigest())
                            state_options = []
                            if args.prepared_material_state:
                                for binding in bindings.get(pair['material'], ()):
                                    independent = None
                                    if args.independent_profile_path and binding['definition'] in texture_definitions:
                                        from shader_material_profile import ordinary_profile
                                        try:
                                            independent = ordinary_profile(texture_definitions[binding['definition']], states[binding['state']],
                                                                           pair['fragment_control'], args.object_pass_path, args.native_target_path)
                                        except ValueError:
                                            pass  # Unknown facts exclude this candidate; never borrow captured fields.
                                    state_options.append(dict(**binding, independent_profile=independent, values=states[binding['state']],
                                                              texture_shapes=texture_shapes.get(binding['definition']),
                                                              sampler_key=texture_keys.get(binding['definition']),
                                                              sampler_lanes=texture_lanes.get(binding['definition'], (0, 0)),
                                                              source=source(base + state_table + binding['state'] * 160, 160)))
                            candidates.append(dict(vertex=dict(order='swap32', **source(pair['vertex_offset'], pair['vertex_size'])),
                                                   fragment=source(pair['fragment_offset'], pair['fragment_size']),
                                                   fragment_control_source=source(pair['fragment_control_offset'], 4),
                                                   fragment_control=pair['fragment_control'],
                                                   identity=pair['fragment_identity'], code=pair['vertex_code'],
                                                   model=item['model'], material=pair['material'], states=state_options))
                        materials[key] = candidates
    output.mkdir(parents=True)
    report = dict(vertex_records=count, matched_vertex_inputs=len(matches), candidates=matches, samples=[],
                  limitations=['Source container set comes from the existing FP catalogue, not an exhaustive asset inventory.',
                               ('Whole selected translation profile and native descriptor are constructed independently under explicit ordinary-upload/pass assumptions.' if args.independent_profile_path else
                                'Prepared material and explicit conditional fields are reconstructed; native descriptor is fresh only with native_target_path; other translation fields remain captured.'
                                if args.prepared_material_state else 'Rendering state/native descriptor is captured, not reconstructed from material definitions.'),
                               'This is a bounded sample, not a complete distributable catalogue.'])
    report['independent_profile_path'] = args.independent_profile_path
    report['material_fragment_control'] = args.material_fragment_control
    report['native_target_path'] = args.native_target_path
    report['object_pass_path'] = args.object_pass_path
    report['environment_texture_path'] = args.environment_texture_path
    report['material_texture_state'] = args.material_texture_state
    report['material_texture_shapes'] = args.material_texture_shapes
    report['material_samplers'] = args.material_samplers
    report['partial_material_sampler_lanes'] = args.material_sampler_lanes
    report['global_sampler_path'] = args.global_sampler_path
    report['shadow_sampler_path'] = args.shadow_sampler_path
    report['environment_sampler_path'] = args.environment_sampler_path
    report['mirror_sampler_path'] = args.mirror_sampler_path
    from shader_pass_state import object_pass_fields, pass_matches, native_target_fields, target_matches
    from shader_material_profile import profile_matches
    compiler = NativeCompiler(args.decoder)
    pairs = set()
    for row in rows:
        if row['status'] != 'recipe_link_verified' or not row.get('fragment_asset_match') or row['line'] < args.start_line:
            continue
        c = row['capture']; state = c['state']
        if args.native_target_path and not target_matches(native_target_fields(args.native_target_path), c):
            continue
        if c['vp_raw'] not in matches or c['fp_flags'] or state['unnorm']:
            continue  # This proof's offline FP profile has these explicit limits.
        pair = (c['vs'], c['ps'])
        if pair in pairs:
            continue
        material = None
        prepared = None
        candidate = matches[c['vp_raw']]
        if args.materials:
            for group in materials.values():
                eligible = (p for p in group if p['identity'] == row['identity'] and
                                 any(p['code'].startswith(prefix) and c['vp_raw'] in ids
                                     for lookup in targets.values() for prefix, ids in lookup.items()))
                for option in eligible:
                    if args.material_fragment_control and int(bool(option['fragment_control'] & 0x40)) != c['state']['exp32']:
                        continue
                    selected = next((s for s in option['states'] if material_state_matches(s['values'], c) and
                                     (not args.independent_profile_path or (s['independent_profile'] is not None and profile_matches(s['independent_profile'], c['state']))) and
                                     (not args.object_pass_path or pass_matches(object_pass_fields(args.object_pass_path, s['values']), c['state'])) and
                                     (not (args.material_texture_shapes or args.material_texture_state) or shape_matches(s['texture_shapes'], c['state'])) and
                                     (not args.material_samplers or s['sampler_key'] == int(c['state']['samplers'], 16)) and
                                     (not args.material_sampler_lanes or (s['sampler_lanes'][1] and
                                      (int(c['state']['samplers'], 16) & s['sampler_lanes'][1]) == s['sampler_lanes'][0]))), None)
                    if args.prepared_material_state and selected is None:
                        continue
                    material, prepared = option, selected
                    break
                if material:
                    break
            if material is None:
                continue
            candidate = material['vertex']
        pairs.add(pair)
        number = len(report['samples'])
        print(f'Proving sample {number + 1}: {c["pipeline"]}', flush=True)
        try:
            result = prove_sample(row, candidate, sources, compiler,
                                  args.engine.resolve(), args.game_root.resolve(), args.cache.resolve(),
                                  output / f'sample-{number + 1}', material, prepared, args.material_samplers,
                                  args.material_sampler_lanes, args.global_sampler_path, args.shadow_sampler_path, args.environment_sampler_path, args.mirror_sampler_path, args.material_texture_shapes, args.material_texture_state, args.environment_texture_path, args.object_pass_path, args.native_target_path, args.material_fragment_control, args.independent_profile_path)
            result['pairing_origin'] = ('reparsed direct material pointers' if material else 'captured shader pair')
            if material:
                result['material'] = dict(model=material['model'], index=material['material'])
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

