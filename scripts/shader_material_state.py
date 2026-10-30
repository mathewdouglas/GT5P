"""Audit authored material state against captured draws; no player/runtime changes.

MDL3 table layout research: PDTools (MIT). Register addresses and key packing
follow this port's rsx_commands.h and rsx_d3d12_backend.c, not RPCS3 code.
Only the observed fixed command-list prefix is decoded. Pass state is unknown.
"""
import argparse
from collections import Counter, defaultdict
import json
import mmap
from pathlib import Path
import re
import subprocess

from shader_coverage import ROOT, MAX_FP, bounded_read, fnv64
from shader_materials import Reader, model_pairs


def decode_state(words):
    """Decode the three measured packets, stopping before return/metadata."""
    if len(words) != 40 or (words[0], words[31], words[35], words[37]) != (
            0x00780304, 0x000C0A6C, 0x0004183C, 0x00020000):
        raise ValueError('unsupported material command layout')
    registers = {}
    for start, method, count in ((1, 0x304, 30), (32, 0xA6C, 3), (36, 0x183C, 1)):
        registers.update({method + i * 4: words[start + i] for i in range(count)})
    # Reject enums outside the understood subset, rather than inheriting the
    # renderer's compatibility fallbacks for unknown guest values.
    def factor(value, alpha=False):
        if value in (0, 1):
            return value + 1  # D3D ZERO/ONE
        values = {0x300: 5 if alpha else 3, 0x301: 6 if alpha else 4,
                  0x302: 5, 0x303: 6, 0x304: 7, 0x305: 8,
                  0x306: 7 if alpha else 9, 0x307: 8 if alpha else 10,
                  0x308: 11, 0x8001: 14, 0x8002: 15, 0x8003: 14, 0x8004: 15}
        if value not in values:
            raise ValueError('unsupported blend factor')
        return values[value]

    def operation(value):
        # A zero alpha-half occurs in twenty measured blocks; this backend
        # explicitly treats an unset equation as ADD.
        values = {0: 1, 0x8006: 1, 0x8007: 4, 0x8008: 5, 0x800A: 2, 0x800B: 3}
        if value not in values:
            raise ValueError('unsupported blend equation')
        return values[value]

    if any(registers[m] not in (0, 1) for m in (0x310, 0xA70, 0xA74, 0x183C)):
        raise ValueError('unsupported boolean register')
    blend = 0
    if registers[0x310]:
        sf, df, eq = (registers[m] for m in (0x314, 0x318, 0x320))
        if sf == df == 0:
            raise ValueError('unprogrammed blend factors')
        blend = (1 | factor(sf & 65535) << 1 | factor(df & 65535) << 6 |
                 factor(sf >> 16, True) << 11 | factor(df >> 16, True) << 16 |
                 operation(eq & 65535) << 21 | operation(eq >> 16) << 24)
    mask = registers[0x324]
    if mask & ~0x01010101:
        raise ValueError('unsupported colour mask bits')
    cmask = sum(bit for flag, bit in ((0x10000, 1), (0x100, 2), (1, 4), (0x1000000, 8)) if mask & flag)
    if not registers[0xA74]:
        depth = 0xF0000000
    else:
        compare = registers[0xA6C]
        if not 0x200 <= compare <= 0x207:
            raise ValueError('unsupported depth comparison')
        depth = (compare - 0x200) << 28 | (0 if registers[0xA70] else 0x80000000)
    return dict(blend=blend, cmask=cmask, depth_bits=depth,
                cull_enable=registers[0x183C], stencil_enable=registers[0x328],
                alpha_test_enable=registers[0x304], alpha_func=registers[0x308],
                alpha_ref=registers[0x30C], trailing_metadata=list(words[38:]),
                registers={f'{method:04x}': value for method, value in registers.items()})


def prepare_state(words):
    """Observed disc-build material preparation, independently expressed.

    This bounded offline transform is different from arbitrary pass overrides.
    Differential tests execute the local lifted preparation routine as oracle.
    Original input is retained unchanged; the remaining metadata stays opaque.
    """
    decode_state(words)
    prepared = list(words)
    prepared[39] &= ~1
    if not words[1] and not words[4] and not (words[38] & 0xF0) and words[33]:
        prepared[39] |= 1
    if prepared[32] == 0x201:
        prepared[32] = 0x203
    return prepared


def model_states(data, base, prepare=False):
    """Keep material definitions separate from shader-bearing material data."""
    import struct
    r = Reader(data, base, struct.unpack_from('>I', data, base + 4)[0])
    if r.unpack('H', 12)[0] != 1:
        raise ValueError('unsupported MDL3 version')
    table = r.unpack('I', 0x44)[0]
    definitions, data_count = r.unpack('HH', table)
    count = r.unpack('B', table + 5)[0]
    states, rejected = {}, Counter()
    for index, offset in enumerate(r.table(r.unpack('I', table + 16)[0], count, 160)):
        try:
            words = r.unpack('40I', offset)
            states[index] = decode_state(prepare_state(words) if prepare else words)
        except ValueError as error:
            rejected[str(error)] += 1
    bindings = defaultdict(list)
    for index, offset in enumerate(r.table(r.unpack('I', table + 8)[0], definitions, 52)):
        material, state, flags = r.unpack('hhH', offset + 4)
        if not 0 <= material < data_count or not 0 <= state < count:
            rejected['invalid material/state index'] += 1
            continue
        if state in states:
            bindings[material].append(dict(definition=index, state=state, flags=flags))
    return states, dict(bindings), rejected


FIELDS = ('blend', 'cmask', 'depth_bits', 'cull_enable')


def captured_state(capture):
    state = capture['state']
    return dict(blend=state['blend'], cmask=state['cmask'],
                depth_bits=state['stencil'] & 0xF0000000, cull_enable=state['cull'] & 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--materials', type=Path, required=True, help='Material audit report (model inventory only)')
    ap.add_argument('--report', type=Path, required=True, help='Flat provenance audit')
    ap.add_argument('--trace', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--prepare-materials', action='store_true',
                    help='Apply the independently tested disc-build preparation transform before comparing')
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose a new output directory in gitignored storage')
    for path in (args.materials, args.report, args.trace):
        path = path.resolve()
        if path == output or path in output.parents or output in path.parents:
            ap.error('Output must be separate from inputs')
    inventory = defaultdict(set)
    for pair in json.loads(args.materials.read_text())['pairs']:
        inventory[pair['file']].add(pair['model'])
    rows = [row for row in json.loads(args.report.read_text())['records']
            if row['status'] == 'recipe_link_verified' and row.get('vertex_input_available')]
    targets = defaultdict(dict)
    for row in rows:
        capture = row['capture']; raw = capture['vp_raw']
        if not re.fullmatch('[0-9a-f]{16}', raw):
            raise ValueError('invalid captured vertex identifier')
        code = bounded_read(args.trace / f'vp_{raw}.bin', MAX_FP)
        length = capture['vp_identity_bytes']
        if len(code) != capture['vp_bytes'] or f'{fnv64(code):016x}' != raw or not 32 <= length <= len(code):
            raise ValueError('invalid captured vertex input')
        targets[length].setdefault(code[:length], set()).add(raw)
    candidates = defaultdict(set)
    profiles, models, errors = [], [], Counter()
    for number, (filename, bases) in enumerate(sorted(inventory.items())):
        with open(filename, 'rb') as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for base in sorted(bases):
                    pairs, _ = model_pairs(data, base)
                    states, bindings, rejected = model_states(data, base, args.prepare_materials)
                    errors.update(rejected)
                    model = dict(file=filename, model=base, states=states, bindings=bindings)
                    models.append(model)
                    ids = {}
                    for index, state in states.items():
                        ids[index] = len(profiles)
                        profiles.append(dict(file=filename, model=base, index=index,
                                             **{f: state[f] for f in FIELDS}))
                    for pair in pairs:
                        code = pair['vertex_code']
                        for length, lookup in targets.items():
                            for raw in lookup.get(code[:length], ()):
                                key = (raw, pair['fragment_identity'])
                                candidates[key].update(ids[b['state']] for b in bindings.get(pair['material'], ()))
        if number % 100 == 0:
            print(f'Containers {number + 1}/{len(inventory)}; state blocks {len(profiles)}', flush=True)
    counts, compared = Counter(), []
    for row in rows:
        capture = row['capture']
        possible = candidates.get((capture['vp_raw'], row['identity']), set())
        if not possible:
            counts['no_material_state_candidate'] += 1
            continue
        counts['links_with_candidates'] += 1
        actual = captured_state(capture)
        matches = [i for i in possible if all(profiles[i][f] == actual[f] for f in FIELDS)]
        counts['joint_match' if matches else 'joint_mismatch'] += 1
        for field in FIELDS:
            counts[field + ('_match' if any(profiles[i][field] == actual[field] for i in possible) else '_mismatch')] += 1
        compared.append(dict(pipeline=capture['pipeline'], capture_line=row['line'], actual=actual,
                             candidate_profiles=sorted(possible), joint_matches=matches))
    result = dict(schema=1, state_origin=('prepared asset command prefix' if args.prepare_materials else 'authored command prefix') + '; pass overrides unknown',
                  material_preparation=args.prepare_materials,
                  fields=list(FIELDS), counts=dict(counts), rejected=dict(errors),
                  profiles=profiles, models=models, comparisons=compared,
                  limitations=['Same shader pair can be shared by several materials; a candidate match is not exact draw ownership.',
                               'Cull direction/winding, full stencil, target formats, texture state and pass overrides are not derived.',
                               'Trailing words after RETURN are retained as uninterpreted metadata, not executed.'])
    output.mkdir(parents=True)
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(models=len(models), state_blocks=len(profiles), counts=counts, rejected=errors), indent=2))


if __name__ == '__main__':
    main()
