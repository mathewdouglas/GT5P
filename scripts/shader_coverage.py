"""Audit local SHDS/raw-FP coverage and recorded pipeline dependencies.

Reads inputs without compiling, launching the game, or changing its cache.
Reports contain local game-derived identifiers: keep them in ignored storage.
Raw shader matches are NOT proof of shader translation or PSO coverage.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAX_FP = 32768
MAX_CODE = 4 * 1024 * 1024
MAGIC = 0x31574D5241503547


def bounded_read(path, maximum):
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('oversized input')
    return data


def fp_identity(data):
    """Hash instruction bytes through END, replacing inline constants with zeros.

    Match the current decoder's halfword-swapped instruction representation.
    Keep constant-slot positions and instruction bits; ignore only values and
    trailing container padding. This is a bounded structural comparison, not a
    validator for opcode semantics, branch targets, or compiler support.
    """
    if not data or len(data) > MAX_FP or len(data) % 16:
        raise ValueError('unaligned, empty or oversized fragment program')
    normalized = bytearray()
    offset = 0
    textures = 0
    constants = 0
    while offset + 16 <= len(data):
        instruction = data[offset:offset + 16]
        words = struct.unpack('>4I', instruction)
        words = [((w << 16) | (w >> 16)) & 0xffffffff for w in words]
        normalized.extend(instruction)
        offset += 16
        op = (words[0] >> 24) & 63
        if op in (0x17, 0x18, 0x19, 0x2f, 0x31):
            textures |= 1 << ((words[0] >> 17) & 15)
        # Matches rsx_fp_program_size/collect_constants. Branch decoding is a
        # separate limitation: this tool never claims semantic equivalence.
        if any((w & 3) == 2 for w in words[1:]):
            if offset + 16 > len(data):
                raise ValueError('truncated inline constant')
            normalized.extend(bytes(16))
            constants += 1
            offset += 16
        if words[0] & 1:
            return dict(identity=hashlib.sha256(normalized).hexdigest(),
                        size=offset, constants=constants, textures=textures)
    raise ValueError('no bounded END instruction')


def fnv64(data):
    value = 1469598103934665603  # Renderer seed (deliberately not standard FNV offset).
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


def asset_catalog(catalog):
    index = json.loads(bounded_read(catalog / 'index.json', 64 * 1024 * 1024))
    sources = defaultdict(list)
    for source in index['sources']:
        digest = source['sha256']
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('invalid source digest in catalogue')
        sources[digest].append(source)
    programs = defaultdict(list)
    failures = []
    for path in sorted(catalog.glob('*.fp')):
        try:
            data = bounded_read(path, MAX_FP)
            digest = hashlib.sha256(data).hexdigest()
            if path.stem != digest:
                raise ValueError('payload filename does not match SHA-256')
            if digest not in sources:
                raise ValueError('payload has no source index entry')
            info = fp_identity(data)
            programs[info['identity']].append(dict(payload=digest, **info))
        except (ValueError, OSError) as exc:
            failures.append(dict(file=path.name, reason=str(exc)))
    return programs, sources, failures


def audit_live(folder, programs, sources):
    records = []
    for path in sorted(folder.glob('fp_*.bin')):
        try:
            data = bounded_read(path, MAX_FP)
            info = fp_identity(data)
            matches = programs.get(info['identity'], [])
            exact = hashlib.sha256(data).hexdigest()
            records.append(dict(file=path.name, **info,
                                match='exact' if any(m['payload'] == exact for m in matches) else
                                      'instructions' if matches else 'unmatched',
                                payloads=[m['payload'] for m in matches],
                                source_files=sorted({s['file'] for m in matches
                                                     for s in sources[m['payload']]})))
        except (ValueError, OSError) as exc:
            records.append(dict(file=path.name, match='invalid', reason=str(exc)))
    counts = Counter(r['match'] for r in records)
    return dict(folder=str(folder), files=len(records), counts=dict(counts),
                unique_instruction_programs=len({r['identity'] for r in records if 'identity' in r}),
                records=records)


def audit_recipes(folder, verify_hashes=False, progress=None):
    """Check v1 envelopes/dependencies; do not interpret ABI-dependent D3D structs."""
    code_results = {}
    records = []

    def code(hash_value, size):
        key = (hash_value, size)
        if key not in code_results:
            try:
                if not 0 < size <= MAX_CODE:
                    raise ValueError('invalid bytecode size')
                path = folder / f'code_{hash_value:016x}.dxbc'
                if path.stat().st_size != size:
                    raise ValueError('bytecode length mismatch')
                with path.open('rb') as f:
                    if f.read(4) != b'DXBC':
                        raise ValueError('not a DXBC container')
                if verify_hashes and fnv64(bounded_read(path, MAX_CODE)) != hash_value:
                    raise ValueError('bytecode hash mismatch')
                code_results[key] = None
            except (ValueError, OSError) as exc:
                code_results[key] = str(exc)
        return code_results[key]

    for path in sorted(folder.glob('*.recipe')):
        record = dict(file=path.name)
        try:
            data = bounded_read(path, 16384)
            if len(data) < 56:
                raise ValueError('truncated recipe')
            magic, version, size, pipeline, vs, ps, vb, pb = struct.unpack_from('<QIIQQQII', data)
            if magic != MAGIC or version != 1 or size != len(data):
                raise ValueError('unsupported recipe envelope')
            if path.name != f'pso_{pipeline:016x}.recipe':
                raise ValueError('recipe filename/hash mismatch')
            if verify_hashes and fnv64(data[:-8]) != struct.unpack_from('<Q', data, len(data) - 8)[0]:
                raise ValueError('recipe checksum mismatch')
            record.update(pipeline=f'{pipeline:016x}', vs=f'{vs:016x}', ps=f'{ps:016x}')
            failures = [f'{stage}: {error}' for stage, h, n in [('vs', vs, vb), ('ps', ps, pb)]
                        if (error := code(h, n))]
            record['status'] = 'dependency_error' if failures else 'dependencies_present'
            if failures:
                record['errors'] = failures
        except (ValueError, OSError, struct.error) as exc:
            record.update(status='invalid', errors=[str(exc)])
        records.append(record)
        if progress and len(records) % 5000 == 0:
            progress(f'Checked {len(records)} pipeline recipes')
    by_pipeline = {r['pipeline']: r for r in records if 'pipeline' in r}
    memberships = {}
    for name in ('menu-v1.txt', 'race-v1.txt'):
        path = folder / name
        if not path.exists():
            memberships[name] = dict(present=False)
            continue
        ids = set()
        invalid = 0
        for line in bounded_read(path, 4 * 1024 * 1024).decode('ascii').splitlines():
            text = line.strip()
            if not text:
                continue
            if re.fullmatch('[0-9a-fA-F]{1,16}', text):
                ids.add(f'{int(text, 16):016x}')
            else:
                invalid += 1
        memberships[name] = dict(present=True, unique_entries=len(ids), invalid_lines=invalid,
                                 missing_recipes=sum(h not in by_pipeline for h in ids),
                                 dependencies_present=sum(by_pipeline.get(h, {}).get('status') ==
                                                          'dependencies_present' for h in ids))
    return dict(folder=str(folder), hash_verification=verify_hashes,
                files=len(records), counts=dict(Counter(r['status'] for r in records)),
                unique_vs=len({r['vs'] for r in records if 'vs' in r}),
                unique_ps=len({r['ps'] for r in records if 'ps' in r}),
                memberships=memberships, records=records)


def audit_profiles(folder, programs):
    """Inventory learned FP states without inventing program/state pairings."""
    records = []
    masks = Counter(p[0]['textures'] for p in programs.values())
    for path in sorted(folder.glob('*.txt')):
        try:
            fields = bounded_read(path, 4096).decode('ascii').split()
            if len(fields) != 9:
                raise ValueError('expected nine profile fields')
            values = [int(value, 16) for value in fields]
            if any(v < 0 or v > (0xffffffffffffffff if i == 4 else 0xffffffff)
                   for i, v in enumerate(values)):
                raise ValueError('profile field out of range')
            if values[0] > 1 or values[2] & ~(1 << 26) or values[8] > 0xffff:
                raise ValueError('profile rejected by offline loader constraints')
            records.append(dict(file=path.name, fields=values, textures=values[8],
                                candidate_instruction_programs=masks[values[8]], status='valid'))
        except (ValueError, OSError) as exc:
            records.append(dict(file=path.name, status='invalid', reason=str(exc)))
    return dict(files=len(records), counts=dict(Counter(r['status'] for r in records)),
                applicability='texture-mask candidates only; no observed shader/profile association',
                records=records)


def audit_provenance(folder, programs, sources, recipes):
    """Join actual translation requests to local raw inputs and saved recipes.

    Input blobs always get integrity checks. A recipe link verifies identifiers
    and dependencies, not that this run completed GPU creation or can recreate
    the shaders from authored materials without recorded local data.
    """
    by_pipeline = {r['pipeline']: r for r in recipes['records'] if 'pipeline' in r}
    blobs = {}
    records = []
    hash_fields = ('pipeline', 'vs', 'ps', 'fp_raw', 'fp_identity', 'fp_hlsl', 'fp_cache',
                   'vp_raw', 'vp_hlsl', 'vp_cache')
    state_fields = ('blend', 'nrt', 'rtfmt', 'exp32', 'cmask', 'cull', 'stencil',
                    'unnorm', 'cube', 'vmask', 'ghi', 'shd', 'unhi')

    def blob(kind, digest):
        key = (kind, digest)
        if key not in blobs:
            data = bounded_read(folder / f'{kind}_{digest}.bin', MAX_CODE)
            if f'{fnv64(data):016x}' != digest:
                raise ValueError(f'{kind} input checksum mismatch')
            # Retain metadata, not every HLSL/VP payload, for large captures.
            metadata = dict(bytes=len(data))
            if kind == 'fp':
                metadata['info'] = fp_identity(data)
            blobs[key] = metadata
        return blobs[key]

    for path in sorted(folder.glob('links_*.jsonl')):
        with path.open('rb') as stream:
            number = 0
            while line := stream.readline(65537):
                number += 1
                record = dict(file=path.name, line=number)
                try:
                    if len(line) > 65536:
                        raise ValueError('oversized trace record')
                    item = json.loads(line)
                    if item['schema'] != 1 or item['request'] not in ('queued', 'ready'):
                        raise ValueError('unsupported provenance schema/request')
                    if any(not isinstance(item[f], str) or not re.fullmatch('[0-9a-f]{16}', item[f])
                           for f in hash_fields):
                        raise ValueError('invalid provenance identifier')
                    for field in ('fp_bytes', 'vp_bytes', 'vp_identity_bytes', 'vp_gpu', 'fp_flags'):
                        if type(item[field]) is not int or not 0 <= item[field] <= 0xffffffff:
                            raise ValueError('invalid provenance size/flags')
                    state = item['state']
                    if any(type(state[f]) is not int or not 0 <= state[f] <= 0xffffffff for f in state_fields):
                        raise ValueError('invalid translation state')
                    if not re.fullmatch('[0-9a-f]{16}', state['samplers']):
                        raise ValueError('invalid sampler state')
                    raw = blob('fp', item['fp_raw'])
                    if raw['bytes'] != item['fp_bytes']:
                        raise ValueError('fragment input size mismatch')
                    info = raw['info']
                    matches = programs.get(info['identity'], [])
                    blob('fphlsl', item['fp_hlsl'])
                    vertex = item['vp_raw'] != '0000000000000000'
                    if vertex:
                        data = blob('vp', item['vp_raw'])
                        if data['bytes'] != item['vp_bytes'] or not 0 < item['vp_identity_bytes'] <= data['bytes']:
                            raise ValueError('vertex input extent mismatch')
                        blob('vphlsl', item['vp_hlsl'])
                    elif item['vp_bytes'] or item['vp_identity_bytes'] or item['vp_hlsl'] != '0000000000000000':
                        raise ValueError('inconsistent unavailable vertex input')
                    record.update(pipeline=item['pipeline'], vs=item['vs'], ps=item['ps'],
                                  request=item['request'], vertex_input_available=vertex,
                                  fragment_asset_match=bool(matches), identity=info['identity'],
                                  payloads=[m['payload'] for m in matches],
                                  source_files=sorted({s['file'] for m in matches for s in sources[m['payload']]}),
                                  capture=item)
                    recipe = by_pipeline.get(item['pipeline'])
                    if not recipe:
                        record['status'] = 'recipe_missing'
                    elif recipe['vs'] != item['vs'] or recipe['ps'] != item['ps']:
                        record['status'] = 'recipe_bytecode_mismatch'
                    elif recipe['status'] != 'dependencies_present':
                        record['status'] = 'recipe_dependencies_missing'
                    else:
                        record['status'] = 'recipe_link_verified'
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    record.update(status='invalid', reason=str(exc))
                records.append(record)
                if len(line) > 65536:
                    break  # Do not reinterpret fragments of an oversized line.
    linked = [r for r in records if r['status'] == 'recipe_link_verified']
    return dict(folder=str(folder), records=records, counts=dict(Counter(r['status'] for r in records)),
                verified_links=len(linked), unique_linked_pipelines=len({r['pipeline'] for r in linked}),
                asset_fragment_links=sum(r['fragment_asset_match'] for r in linked),
                vertex_input_links=sum(r['vertex_input_available'] for r in linked),
                note='Links retain local inputs/HLSL; asset vertex/material reconstruction and GPU completion remain unproven.')


def summary(report):
    lines = ['Shader coverage audit',
             f"Asset payloads: {report['assets']['payloads']}; instruction identities: "
             f"{report['assets']['instruction_identities']}; rejected: {report['assets']['rejected']}"]
    for live in report['live']:
        lines.append(f"Live {live['folder']}: {live['files']} files, "
                     f"{live['unique_instruction_programs']} instruction identities; {live['counts']}")
    recipes = report['recipes']
    lines.append(f"Pipeline recipes: {recipes['files']}; {recipes['counts']}; "
                 f"unique compiled VS/PS: {recipes['unique_vs']}/{recipes['unique_ps']}")
    lines.append(f"Learned fragment profiles: {report['profiles']['files']}; {report['profiles']['counts']}")
    for trace in report.get('provenance', []):
        lines.append(f"Provenance {trace['folder']}: {trace['verified_links']} verified recipe links; "
                     f"asset-backed FP {trace['asset_fragment_links']}; vertex inputs {trace['vertex_input_links']}; "
                     f"{trace['counts']}")
    lines.append('Full asset-to-pipeline reconstruction: UNKNOWN (vertex/material extraction and replay not validated).')
    lines.append('Matches exclude inline constant values; they do not prove successful translation or complete state coverage.')
    lines.append('Recipe checks cover envelopes and bytecode dependencies, not current renderer/GPU compatibility.')
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--catalog', type=Path, required=True, help='Existing extracted catalogue with index.json')
    ap.add_argument('--live', type=Path, action='append', required=True, help='RSX_FP_CATALOG folder; repeat per route')
    ap.add_argument('--cache', type=Path, required=True, help='Cache containing warmup-v1 recipes')
    ap.add_argument('--output', type=Path, required=True, help='New report directory inside gitignored storage')
    ap.add_argument('--verify-hashes', action='store_true', help='Verify renderer FNV checksums too (slower)')
    ap.add_argument('--provenance', type=Path, action='append', default=[],
                    help='RSX_PSO_PROVENANCE directory; verify input blobs and join to recipes')
    args = ap.parse_args()
    for path in [args.catalog, *args.live, *args.provenance, args.cache / 'warmup-v1']:
        if not path.is_dir():
            ap.error(f'Input directory not found: {path}')
    output = args.output.resolve()
    ignored = subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT)
    if ignored.returncode != 0:
        ap.error('Reports must be written to gitignored storage such as scratch/; they contain local identifiers')
    if output.exists():
        ap.error('Choose a new output directory; existing reports are never overwritten')
    for source in [args.catalog, *args.live, *args.provenance, args.cache]:
        source = source.resolve()
        if output == source or output in source.parents or source in output.parents:
            ap.error('Output must be separate from input catalogue/capture/cache directories')
    print('Indexing extracted fragment programs...', flush=True)
    programs, sources, rejected = asset_catalog(args.catalog)
    print('Comparing live programs...', flush=True)
    live = [audit_live(folder, programs, sources) for folder in args.live]
    print('Checking pipeline dependencies (large caches can take several minutes)...', flush=True)
    recipes = audit_recipes(args.cache / 'warmup-v1', args.verify_hashes,
                            lambda text: print(text, flush=True))
    print('Joining provenance records...', flush=True)
    provenance = [audit_provenance(folder, programs, sources, recipes) for folder in args.provenance]
    report = dict(schema=1, created_utc=datetime.now(timezone.utc).isoformat(),
                  assets=dict(catalog=str(args.catalog.resolve()), payloads=sum(map(len, programs.values())),
                              indexed_payloads=len(sources), instruction_identities=len(programs),
                              rejected=len(rejected), failures=rejected),
                  live=live, recipes=recipes,
                  profiles=audit_profiles(args.cache / 'fp-profiles-v2', programs),
                  provenance=provenance,
                  full_pipeline_reconstruction='unknown_vertex_material_reconstruction' if provenance
                                               else 'unknown_missing_provenance',
                  limitations=['No vertex-program or material-state extraction.',
                               'Live corpora contain unique recorded programs, not draw counts or exhaustive track coverage.',
                               'Provenance links require an explicit capture; legacy recipes have no original input mapping.',
                               'Structural matches do not validate semantic equivalence or compiler acceptance.',
                               'Existing recipe sets may include previous renderer versions/settings.'])
    output.mkdir(parents=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    text = summary(report)
    (output / 'summary.txt').write_text(text, encoding='utf-8')
    print(text, end='')
    print('Local report:', output)


if __name__ == '__main__':
    main()
