"""Bounded material sampler bindings. No defaults for unresolved pass textures.

Layout research: PDTools MDL3Material/TextureKey/PGLUCellTextureInfo (MIT).
The supported SHDS sampler record layout is checked explicitly, not generalized
from unknown fields. Texture indices and unit slots are validated against draws.
"""
from collections import Counter
import struct

from shader_materials import Reader, model_pairs
from shader_coverage import fp_identity


def sampler_register(address, filtering):
    """Production default sampler bank selection for a programmed unit."""
    minimum, magnify = (filtering >> 16) & 7, (filtering >> 24) & 7
    if not minimum and not magnify and not address & 0xF0F:
        raise ValueError('unprogrammed sampler requires unit-dependent fallback')
    filtering_class = (0 if magnify == 1 and minimum in (1, 3, 5) else
                       2 if minimum in (5, 6) else 1)
    clamp_s = (address & 15) not in (0, 1, 2)
    clamp_t = ((address >> 8) & 15) not in (0, 1, 2)
    wrap = 1 if clamp_s and clamp_t else 3 if clamp_s else 2 if clamp_t else 0
    return 4 + filtering_class * 4 + wrap


def model_textures(data, base):
    r = Reader(data, base, struct.unpack_from('>I', data, base + 4)[0])
    if r.unpack('H', 12)[0] != 1:
        raise ValueError('unsupported MDL3 version')
    table, header = r.unpack('I', 0x44)[0], r.unpack('I', 0x4C)[0]
    definitions, data_count = r.unpack('HH', table)
    textures = r.table(r.unpack('I', table + 20)[0], r.unpack('H', table + 6)[0], 68)
    fragments = r.table(r.unpack('I', header + 44)[0], r.unpack('H', header + 26)[0], 72)
    pairs, _ = model_pairs(data, base)
    sampler_maps, rejected, results = {}, Counter(), []

    def name(offset):
        start = r.span(offset, 1)
        end = data.find(b'\0', start, min(start + 256, r.end))
        if end < 0:
            raise ValueError('unbounded sampler name')
        return data[start:end].decode('ascii')

    for pair in pairs:
        material = pair['material']; fp = fragments[pair['fragment_index']]
        try:
            samplers = {}
            for offset in r.table(r.unpack('I', fp + 20)[0], r.unpack('B', fp + 11)[0], 16):
                no, kind, unit, a, b, c = r.unpack('I4hI', offset)
                if kind != 0x601 or not 0 <= unit < 16 or a or b or c:
                    raise ValueError('unsupported sampler record')
                key = name(no)
                if key in samplers:
                    raise ValueError('ambiguous sampler name/unit')
                samplers[key] = unit
            globals_ = []
            for offset in r.table(r.unpack('I', fp + 56)[0], r.unpack('B', fp + 10)[0], 16):
                no, kind, unit, a, b, identifier = r.unpack('I4hI', offset)
                # Retain requirements only. Neither the kind nor the identifier
                # is used to invent texture/filter state or a registry address.
                if not 0 <= unit < 16 or a or b:
                    raise ValueError('unsupported global sampler record')
                globals_.append(dict(name=name(no), kind=kind, unit=unit, identifier=identifier))
            sampler_maps[material] = (pair, samplers, globals_)
        except (ValueError, UnicodeError) as error:
            rejected[str(error)] += 1
    for index, offset in enumerate(r.table(r.unpack('I', table + 8)[0], definitions, 52)):
        material = r.unpack('h', offset + 4)[0]
        if not 0 <= material < data_count:
            rejected['invalid material index'] += 1
            continue
        if material not in sampler_maps:
            continue
        pair, samplers, globals_ = sampler_maps[material]
        try:
            keys = {}
            for item in r.table(r.unpack('I', offset + 12)[0], r.unpack('H', offset + 10)[0], 8):
                no, texture = r.unpack('II', item)
                key = name(no)
                if key in keys:
                    raise ValueError('ambiguous texture key')
                keys[key] = texture
            bindings, unresolved = [], []
            unit_names = {}
            for key, unit in samplers.items():
                unit_names.setdefault(unit, []).append(key)
            for unit, names in unit_names.items():
                missing = [key for key in names if key not in keys]
                if missing:
                    unresolved.append(dict(names=names, unit=unit, reason='missing scalar alias binding'))
                    continue
                indices = {keys[key] for key in names}
                if len(indices) != 1:
                    raise ValueError('conflicting scalar alias textures')
                texture = indices.pop()
                if texture >= len(textures):
                    raise ValueError('texture index outside table')
                position = textures[texture]
                words = r.unpack('17I', position)
                if words[0] != 0x00201A00:
                    raise ValueError('unsupported texture record header')
                bindings.append(dict(name=names[0], aliases=names, unit=unit, texture_index=texture,
                                     image_id=words[14], offset=base + position, size=68,
                                     address=words[3], filtering=words[6], format=words[2],
                                     width=words[7] >> 16, height=words[7] & 65535,
                                     sampler=sampler_register(words[3], words[6])))
            results.append(dict(definition=index, material=material, bindings=bindings,
                                unresolved=unresolved, globals=globals_, vertex_code=pair['vertex_code'],
                                used=fp_identity(data[pair['fragment_offset']:pair['fragment_offset'] + pair['fragment_size']])['textures'],
                                fragment_identity=pair['fragment_identity']))
        except (ValueError, UnicodeError) as error:
            rejected[str(error)] += 1
    return results, rejected


def replace_known_samplers(captured, bindings, used):
    """Replace only resolved, actually sampled units; all other lanes stay explicit."""
    result, replaced = captured, []
    for binding in bindings:
        unit = binding['unit']
        if used & (1 << unit):
            result = (result & ~(15 << (4 * unit))) | (binding['sampler'] << (4 * unit))
            replaced.append(unit)
    return result, replaced


def complete_sampler_key(definition):
    if any(definition['used'] & (1 << requirement['unit']) for requirement in definition.get('globals', ())):
        return None
    key, units = replace_known_samplers(0, definition['bindings'], definition['used'])
    if not definition['used'] or sum(1 << unit for unit in units) != definition['used']:
        return None
    return key


def known_sampler_key(definition):
    """A value/mask pair, explicitly leaving global and unresolved lanes unknown."""
    globals_ = {g['unit'] for g in definition.get('globals', ())}
    bindings = [b for b in definition['bindings'] if b['unit'] not in globals_]
    key, units = replace_known_samplers(0, bindings, definition['used'])
    mask = sum(15 << (4 * unit) for unit in units)
    return key, mask


def with_global_sampler_path(definition, path=None):
    """Add measured dither/PCF candidates for an explicitly chosen binding path.

    Captures never choose the path here. Unknown signatures, duplicate global
    units and local/global overlaps stay unresolved. Only sampler state is added.
    """
    if path is None:
        return definition
    if path not in ('active', 'fallback'):
        raise ValueError('unsupported global sampler path')
    signatures = {('ditherMap', 0x601, 94), ('ditherMap', 0x801, 103),
                  ('shadowPCFMap', 0x801, 104)}
    globals_ = definition.get('globals', ())
    counts = Counter(g['unit'] for g in globals_)
    local_units = {b['unit'] for b in definition['bindings']}
    address, filtering = ((0x00030101, 0x01012000) if path == 'active' else
                          (0x60010101, 0x02022000))
    bindings, unresolved = list(definition['bindings']), []
    for g in globals_:
        signature = (g['name'], g['kind'], g['identifier'])
        if signature not in signatures or counts[g['unit']] != 1 or g['unit'] in local_units:
            unresolved.append(g)
            continue
        bindings.append(dict(g, address=address, filtering=filtering,
                             sampler=sampler_register(address, filtering), global_path=path))
    return dict(definition, bindings=bindings, globals=unresolved)


def main():
    import argparse
    from collections import defaultdict
    import json
    import mmap
    from pathlib import Path
    import re
    import subprocess
    from shader_coverage import ROOT, MAX_FP, bounded_read, fnv64
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--states', type=Path, required=True, help='State audit model inventory')
    ap.add_argument('--report', type=Path, required=True, help='Flat provenance audit')
    ap.add_argument('--trace', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--global-sampler-path', choices=('active', 'fallback'),
                    help='Conditional dither/PCF path; other globals remain unresolved')
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose a new output directory in gitignored storage')
    for path in (args.states, args.report, args.trace):
        path = path.resolve()
        if output == path or output in path.parents or path in output.parents:
            ap.error('Output must be separate from inputs')
    rows = [row for row in json.loads(args.report.read_text())['records']
            if row['status'] == 'recipe_link_verified' and row.get('vertex_input_available')]
    targets = defaultdict(dict)
    for row in rows:
        c = row['capture']; raw = c['vp_raw']
        if not re.fullmatch('[0-9a-f]{16}', raw):
            raise ValueError('invalid captured vertex identifier')
        code = bounded_read(args.trace / f'vp_{raw}.bin', MAX_FP)
        length = c['vp_identity_bytes']
        if len(code) != c['vp_bytes'] or f'{fnv64(code):016x}' != raw or not 32 <= length <= len(code):
            raise ValueError('invalid captured vertex input')
        targets[length].setdefault(code[:length], set()).add(raw)
    inventory = defaultdict(set)
    for model in json.loads(args.states.read_text())['models']:
        inventory[model['file']].add(model['model'])
    candidates, rejected, total, unresolved = defaultdict(set), Counter(), 0, 0
    global_requirements, global_signatures, sampled_globals, aliases = Counter(), Counter(), Counter(), 0
    derived_globals = 0
    for number, (filename, bases) in enumerate(sorted(inventory.items())):
        with open(filename, 'rb') as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for base in sorted(bases):
                    definitions, errors = model_textures(data, base)
                    rejected.update(errors)
                    for definition in definitions:
                        total += len(definition['bindings']); unresolved += len(definition['unresolved'])
                        aliases += sum(len(b['aliases']) > 1 for b in definition['bindings'])
                        global_units = {g['unit'] for g in definition['globals']}
                        global_requirements.update(g['name'] for g in definition['globals'])
                        global_signatures.update((g['name'], g['kind'], g['unit'], g['identifier']) for g in definition['globals'])
                        sampled_globals.update(g['name'] for g in definition['globals'] if definition['used'] & (1 << g['unit']))
                        original_binding_count = len(definition['bindings'])
                        definition = with_global_sampler_path(definition, args.global_sampler_path)
                        derived_globals += len(definition['bindings']) - original_binding_count
                        global_units = {g['unit'] for g in definition['globals']}
                        known = tuple(sorted((b['unit'], b['sampler']) for b in definition['bindings']
                                             if definition['used'] & (1 << b['unit']) and b['unit'] not in global_units))
                        if not known:
                            continue
                        for length, lookup in targets.items():
                            for raw in lookup.get(definition['vertex_code'][:length], ()):
                                candidates[raw, definition['fragment_identity']].add((definition['used'], known))
        if number % 100 == 0:
            print(f'Containers {number + 1}/{len(inventory)}; resolved bindings {total}', flush=True)
    counts, comparisons = Counter(), []
    for row in rows:
        c = row['capture']; profiles = candidates.get((c['vp_raw'], row['identity']), ())
        if not profiles:
            counts['no_known_sampled_binding'] += 1
            continue
        actual = int(c['state']['samplers'], 16)
        matching = [(used, known) for used, known in profiles
                    if all((actual >> (4 * unit)) & 15 == sampler for unit, sampler in known)]
        complete = any(used == sum(1 << unit for unit, _ in known) for used, known in matching)
        counts['known_lanes_match' if matching else 'known_lanes_mismatch'] += 1
        counts['all_sampled_units_resolved_and_match' if complete else 'partial_or_mismatch'] += 1
        comparisons.append(dict(line=row['line'], pipeline=c['pipeline'],
                                known_match=bool(matching), complete_match=complete,
                                profiles=[dict(used=used, lanes=dict(known)) for used, known in sorted(profiles)]))
    result = dict(schema=1, global_sampler_path=args.global_sampler_path,
                  resolved_bindings=total, unresolved_bindings=unresolved,
                  conditional_global_bindings=derived_globals,
                  coherent_alias_bindings=aliases, global_requirements=dict(global_requirements),
                  sampled_global_requirements=dict(sampled_globals),
                  global_signatures=[dict(name=name, kind=kind, unit=unit, identifier=identifier, references=count)
                                     for (name, kind, unit, identifier), count in sorted(global_signatures.items())],
                  rejected=dict(rejected), counts=dict(counts), comparisons=comparisons,
                  limitations=['Candidates share shader pairs; exact draw/material ownership is unproven.',
                               'Unknown global textures stay unresolved; dither/PCF candidates require the explicit path.',
                               'Only sampler-bank lanes are compared, not cube/gamma/unnormalized or pass state.'])
    output.mkdir(parents=True)
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('comparisons', 'limitations', 'global_signatures')}, indent=2))


if __name__ == '__main__':
    main()
