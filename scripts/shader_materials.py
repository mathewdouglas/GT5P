"""Read-only MDL3 material shader-pair audit. Outputs must stay local/ignored.

Layout research: PDTools ModelSet3/Materials and Shaders readers (MIT).
Field interpretations are deliberately narrower than a complete material parser:
no draw/pass state is inferred, and ambiguous pointer joins are rejected.
"""
import argparse
from collections import Counter, defaultdict
import json
import mmap
from pathlib import Path
import re
import struct
import subprocess

from shader_coverage import ROOT, MAX_FP, bounded_read, fnv64, fp_identity
from shader_reconstruct import word_swap


class Reader:
    def __init__(self, data, base, size):
        self.data, self.base, self.end = data, base, base + size
        if size < 0xE4 or self.end > len(data):
            raise ValueError('invalid model extent')

    def span(self, offset, size):
        start = self.base + offset
        if offset <= 0 or size <= 0 or start + size > self.end:
            raise ValueError('out-of-model reference')
        return start

    def unpack(self, fmt, offset):
        return struct.unpack_from('>' + fmt, self.data,
                                  self.span(offset, struct.calcsize('>' + fmt)))

    def table(self, offset, count, stride):
        if count > 8192:
            raise ValueError('table count exceeds bound')
        if not count:
            return []
        self.span(offset, count * stride)
        return [offset + i * stride for i in range(count)]

    def payload(self, offset, size):
        if size > MAX_FP + 32:
            raise ValueError('oversized shader')
        p = self.span(offset, size)
        return self.data[p:p + size]


def model_pairs(data, base):
    """Return pairs justified by direct material pointers, never a cross product."""
    size = struct.unpack_from('>I', data, base + 4)[0]
    r = Reader(data, base, size)
    version = r.unpack('H', 12)[0]
    if version != 1:
        raise ValueError('unsupported MDL3 version')
    materials, header = r.unpack('I', 0x44)[0], r.unpack('I', 0x4C)[0]
    if data[r.span(header, 0x44):r.base + header + 4] != b'SHDS':
        raise ValueError('missing SHDS')
    vc, fc = r.unpack('HH', header + 0x18)
    vtable = r.table(r.unpack('I', header + 0x20)[0], vc, 0x28)
    ftable = r.table(r.unpack('I', header + 0x2C)[0], fc, 0x48)
    fragment_map = defaultdict(list)
    for item in r.table(r.unpack('I', header + 0x40)[0],
                        r.unpack('H', header + 0x34)[0], 0x20):
        descriptor, offset, length = r.unpack('III', item)
        fragment_map[descriptor].append((offset, length))
    count = r.unpack('H', materials + 2)[0]
    records = r.table(r.unpack('I', materials + 12)[0], count, 0x28)
    results, rejected = [], Counter()
    for index, material in enumerate(records):
        try:
            extra = r.unpack('I', material + 0x24)[0]
            if not extra:
                rejected['no_direct_shader_reference'] += 1
                continue
            vp, fp = r.unpack('II', extra + 12)
            if vp not in vtable or fp not in ftable:
                raise ValueError('shader pointer outside declared table')
            descriptor = r.unpack('I', fp)[0]
            r.span(descriptor, 16)  # Compact binding header must be wholly inside the model.
            fragments = fragment_map[descriptor]
            if len(fragments) != 1:
                raise ValueError('ambiguous or absent fragment descriptor')
            vo, vl = r.unpack('II', vp)
            body = r.payload(vo, vl)
            if len(body) < 32:
                raise ValueError('short vertex wrapper')
            n = struct.unpack_from('>H', body)[0]
            code = struct.unpack_from('>I', body, 16)[0]
            if not n or code < 32 or code % 16 or code + n * 16 > len(body):
                raise ValueError('invalid vertex wrapper')
            fo, fl = fragments[0]
            identity = fp_identity(r.payload(fo, fl))['identity']
            results.append(dict(model=base, material=index, reference=base + extra,
                                vertex_index=vtable.index(vp), fragment_index=ftable.index(fp),
                                vertex_offset=base + vo + code, vertex_size=n * 16,
                                fragment_offset=base + fo, fragment_size=fl,
                                fragment_identity=identity,
                                fragment_control_offset=r.span(descriptor + 8, 4),
                                fragment_control=r.unpack('I', descriptor + 8)[0],
                                vertex_code=word_swap(body[code:code + n * 16])))
        except (ValueError, KeyError, struct.error) as error:
            rejected[str(error)] += 1
    return results, rejected


def scan(data):
    start = 0
    while True:
        base = data.find(b'MDL3', start)
        if base < 0:
            return
        start = base + 4
        try:
            pairs, rejected = model_pairs(data, base)
            yield base, pairs, rejected, None
        except (ValueError, KeyError, struct.error) as error:
            yield base, [], {}, str(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True,
                        help='Flat verified provenance audit report')
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.output.exists() or subprocess.run(
            ['git', 'check-ignore', '-q', str(args.output / 'report.json')], cwd=ROOT).returncode:
        parser.error('Choose a new output directory in gitignored storage')
    for path in (args.catalog, args.report, args.trace):
        path = path.resolve()
        if args.output == path or path in args.output.parents or args.output in path.parents:
            parser.error('Output must be separate from inputs')
    rows = json.loads(args.report.read_text())['records']
    targets, expected = defaultdict(dict), set()
    for row in rows:
        if row['status'] != 'recipe_link_verified':
            continue
        c = row['capture']
        if not c['vp_bytes']:
            continue
        if not re.fullmatch('[0-9a-f]{16}', c['vp_raw']):
            raise ValueError('invalid captured vertex identifier')
        code = bounded_read(args.trace / f"vp_{c['vp_raw']}.bin", MAX_FP)
        if len(code) != c['vp_bytes']:
            raise ValueError('captured vertex size mismatch')
        if f'{fnv64(code):016x}' != c['vp_raw']:
            raise ValueError('captured vertex checksum mismatch')
        length = c['vp_identity_bytes']
        if not 32 <= length <= len(code):
            raise ValueError('invalid captured vertex identity extent')
        targets[length].setdefault(code[:length], set()).add(c['vp_raw'])
        expected.add((c['vp_raw'], row['identity']))
    index = json.loads((args.catalog / 'index.json').read_text())
    files = sorted({str(Path(item['file']).resolve()) for item in index['sources']})
    counters, rejects, errors, entries, matched = Counter(), Counter(), Counter(), [], set()
    for number, filename in enumerate(files):
        with Path(filename).open('rb') as stream:
            if not Path(filename).stat().st_size:
                continue
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for base, pairs, rejected, error in scan(data):
                    counters['model_candidates'] += 1
                    if error:
                        errors[error] += 1
                        continue
                    counters['parsed_models'] += 1
                    rejects.update(rejected)
                    for pair in pairs:
                        code = pair.pop('vertex_code')
                        ids = set()
                        for length, lookup in targets.items():
                            ids.update(lookup.get(code[:length], ()))
                        hits = sorted(raw for raw in ids if (raw, pair['fragment_identity']) in expected)
                        matched.update((raw, pair['fragment_identity']) for raw in hits)
                        entries.append(dict(file=filename, **pair, captured_pair_matches=hits))
        if number % 100 == 0:
            print(f'Containers {number + 1}/{len(files)}; direct material pairs {len(entries)}', flush=True)
    result = dict(schema=1, state_origin='not_derived', containers=len(files),
                  counts=dict(counters), rejected_materials=dict(rejects), rejected_models=dict(errors),
                  material_pairs=len(entries), captured_unique_pairs=len(expected),
                  matched_captured_unique_pairs=len(matched), pairs=entries)
    args.output.mkdir(parents=True)
    (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'pairs'}, indent=2))


if __name__ == '__main__':
    main()
