"""Asset-local texture shape constraints; global/pass bindings stay unknown."""
from collections import Counter, defaultdict


def texture_shape(binding):
    """Supported descriptor subset, under default cube/volume renderer switches."""
    base_format = (binding['format'] >> 8) & 0x9f
    if base_format not in (0x81, 0x85, 0x86, 0x87, 0x88, 0x8b, 0x9a):
        raise ValueError('unsupported non-depth texture format')
    dimension = (binding['format'] >> 4) & 15
    cube = bool(binding['format'] & 4)
    if dimension not in (2, 3) or (cube and dimension != 2):
        raise ValueError('unsupported texture dimension/cube combination')
    if not binding['width'] or not binding['height']:
        raise ValueError('empty texture extent')
    return 'cube' if cube else 'volume' if dimension == 3 else '2d'


def texture_fields(definition, sampling=False):
    """Independent descriptor bits, plus explicitly measured global emitter facts."""
    values = dict(cube=0, ghi=0, **({'unhi': 0} if sampling else {}))
    masks = dict(values)
    known_units = 0
    unresolved = []
    global_units = {g['unit'] for g in definition.get('globals', ())}
    for binding in definition['bindings']:
        unit = binding['unit']
        if not definition['used'] & (1 << unit) or unit in global_units:
            continue
        if 'format' in binding:
            try:
                shape = texture_shape(binding)
            except ValueError as error:
                unresolved.append(dict(unit=unit, reason=str(error)))
                continue
            facts = dict(shape=shape, gamma=bool((binding['address'] >> 20) & 7) if sampling else False,
                         unnormalized=shape == '2d' and bool(binding['format'] & 0x4000))
        else:
            facts = binding.get('texture_facts')
            if not facts:
                continue
            shape = facts['shape']
        cube_bit = 1 << (unit if unit < 4 else unit + 16)
        volume_bit = 1 << (unit + 16)
        masks['cube'] |= cube_bit
        masks['ghi'] |= volume_bit
        if shape == 'cube':
            values['cube'] |= cube_bit
        if shape == 'volume':
            values['ghi'] |= volume_bit
        if sampling:
            gamma_field = 'cube' if unit < 4 else 'ghi'
            gamma_bit = 1 << (unit + 8 if unit < 4 else unit)
            masks[gamma_field] |= gamma_bit
            if facts['gamma']:
                values[gamma_field] |= gamma_bit
            if unit >= 4:
                masks['unhi'] |= 1 << unit
                if facts['unnormalized']:
                    values['unhi'] |= 1 << unit
        known_units |= 1 << unit
    return dict(values=values, masks=masks, known_units=known_units,
                unresolved_units=definition['used'] & ~known_units, rejected=unresolved)


def shape_fields(definition):
    return texture_fields(definition)


def shape_matches(fields, state):
    return bool(fields['known_units']) and all(
        state[name] & mask == fields['values'][name] for name, mask in fields['masks'].items())


def replace_shape_fields(fields, state):
    return {name: (state[name] & ~mask) | fields['values'][name]
            for name, mask in fields['masks'].items()}


def main():
    import argparse
    import json
    import mmap
    from pathlib import Path
    import re
    import subprocess
    from shader_coverage import ROOT, MAX_FP, bounded_read, fnv64
    from shader_material_textures import model_textures, with_global_sampler_path
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('states', 'report', 'trace', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--sampling-state', action='store_true', help='Also derive read gamma and upper-unit coordinate flags')
    ap.add_argument('--global-sampler-path', choices=('active', 'fallback'))
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose a new output directory in gitignored storage')
    for path in (args.states, args.report, args.trace):
        path = path.resolve()
        if output == path or output in path.parents or path in output.parents:
            ap.error('Output must be separate from inputs')
    rows = [r for r in json.loads(args.report.read_text())['records']
            if r['status'] == 'recipe_link_verified' and r.get('vertex_input_available')]
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
    candidates, shapes, rejected = defaultdict(set), Counter(), Counter()
    for number, (filename, bases) in enumerate(sorted(inventory.items())):
        with open(filename, 'rb') as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for base in sorted(bases):
                    definitions, errors = model_textures(data, base)
                    rejected.update(errors)
                    for definition in definitions:
                        for binding in definition['bindings']:
                            try:
                                shapes[texture_shape(binding)] += 1
                            except ValueError as error:
                                rejected[str(error)] += 1
                        definition = with_global_sampler_path(definition, args.global_sampler_path)
                        fields = texture_fields(definition, args.sampling_state)
                        if not fields['known_units']:
                            continue
                        profile = (fields['values']['cube'], fields['values']['ghi'],
                                   fields['masks']['cube'], fields['masks']['ghi'],
                                   fields['known_units'], fields['unresolved_units'],
                                   fields['values'].get('unhi', 0), fields['masks'].get('unhi', 0))
                        for length, lookup in targets.items():
                            for raw in lookup.get(definition['vertex_code'][:length], ()):
                                candidates[raw, definition['fragment_identity']].add(profile)
        if number % 100 == 0:
            print(f'Containers {number + 1}/{len(inventory)}', flush=True)
    counts, comparisons = Counter(), []
    for row in rows:
        profiles = candidates.get((row['capture']['vp_raw'], row['identity']), ())
        if not profiles:
            counts['no_known_shape'] += 1
            continue
        state = row['capture']['state']
        matching = [p for p in profiles if state['cube'] & p[2] == p[0] and state['ghi'] & p[3] == p[1] and state.get('unhi', 0) & p[7] == p[6]]
        counts['known_shape_match' if matching else 'known_shape_mismatch'] += 1
        complete = any(not p[5] for p in matching)
        counts['all_sampled_shapes_match' if complete else 'partial_or_mismatch'] += 1
        comparisons.append(dict(line=row['line'], known_match=bool(matching), complete_match=complete,
                                profiles=[dict(cube=p[0], ghi=p[1], cube_mask=p[2], ghi_mask=p[3],
                                               known_units=p[4], unresolved_units=p[5], unhi=p[6], unhi_mask=p[7]) for p in sorted(profiles)]))
    result = dict(schema=2, sampling_state=args.sampling_state, global_sampler_path=args.global_sampler_path, shapes=dict(shapes), rejected=dict(rejected), counts=dict(counts), comparisons=comparisons,
                  limitations=['Supported local descriptors and explicitly chosen dither/PCF paths only; other global bindings stay unknown.',
                               'Same-pair candidates do not establish unique draw ownership.',
                               'Output gamma, low-unit coordinate mapping, target/pass state and resource upload success are not reconstructed.'])
    output.mkdir(parents=True)
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'comparisons'}, indent=2))


if __name__ == '__main__':
    main()
