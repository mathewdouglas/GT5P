"""Compare consumed FIFO material blocks with original assets, read-only.

Only exact 40-word matches or matches differing solely in depth words are
reported. These are byte-pattern candidates, not proof of unique draw ownership.
"""
import argparse
from collections import Counter, defaultdict
import json
import mmap
from pathlib import Path
import struct
import subprocess

from shader_coverage import ROOT
from shader_material_state import decode_state, prepare_state
from shader_materials import Reader


def without_depth(words):
    result = list(words)
    result[32:35] = [0, 0, 0]
    return tuple(result)


def asset_blocks(inventory):
    groups = defaultdict(set)
    for model in inventory['models']:
        groups[model['file']].add(model['model'])
    blocks = []
    for filename, bases in sorted(groups.items()):
        with open(filename, 'rb') as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for base in sorted(bases):
                    size = struct.unpack_from('>I', data, base + 4)[0]
                    r = Reader(data, base, size)
                    if r.unpack('H', 12)[0] != 1:
                        raise ValueError('unsupported model version')
                    materials = r.unpack('I', 0x44)[0]
                    count = r.unpack('B', materials + 5)[0]
                    for index, offset in enumerate(r.table(r.unpack('I', materials + 16)[0], count, 160)):
                        words = r.unpack('40I', offset)
                        decode_state(words)
                        blocks.append(dict(file=filename, model=base, index=index,
                                           offset=base + offset, words=list(words)))
    return blocks


def compare(rows, blocks):
    exact, relaxed, prepared = defaultdict(list), defaultdict(list), defaultdict(list)
    for index, block in enumerate(blocks):
        words = block['words']
        decode_state(words)
        exact[tuple(words)].append(index)
        relaxed[without_depth(words)].append(index)
        prepared[tuple(prepare_state(words))].append(index)
    counts, functions, changes, prepared_counts, records = Counter(), Counter(), Counter(), Counter(), []
    for number, row in enumerate(rows, 1):
        try:
            if row['schema'] != 1:
                raise ValueError('unsupported schema')
            for field in ('frame', 'io', 'ea', 'call_return_io', 'header', 'depth_func', 'depth_mask', 'depth_test'):
                value = row[field]
                if type(value) is not int or value < 0 or value > (0xFFFFFFFFFFFFFFFF if field == 'frame' else 0xFFFFFFFF):
                    raise ValueError('invalid ' + field)
            words = row['material_words']
            if not isinstance(words, list) or len(words) not in (0, 40) or any(type(x) is not int or not 0 <= x <= 0xFFFFFFFF for x in words):
                raise ValueError('invalid material words')
            if row['header'] != 0x000C0A6C:
                raise ValueError('unsupported depth packet')
            functions[f"{row['depth_func']:04x}"] += 1
            if not words:
                counts['non_material_packet'] += 1
                records.append(dict(line=number, status='non_material_packet', capture=row))
                continue
            decode_state(words)
            if words[32:35] != [row['depth_func'], row['depth_mask'], row['depth_test']]:
                raise ValueError('packet and snapshot disagree')
            candidates = exact.get(tuple(words), [])
            status = 'exact' if candidates else 'depth_only_difference'
            if not candidates:
                candidates = relaxed.get(without_depth(words), [])
                if not candidates:
                    status = 'unmatched'
            counts[status] += 1
            prepared_candidates = prepared.get(tuple(words), [])
            prepared_counts['exact' if prepared_candidates else 'unmatched'] += 1
            if status == 'depth_only_difference':
                for original in {tuple(blocks[i]['words'][32:35]) for i in candidates}:
                    changes[str(original) + ' -> ' + str(tuple(words[32:35]))] += 1
            records.append(dict(line=number, status=status, capture=row, candidates=candidates,
                                prepared_candidates=prepared_candidates))
        except (ValueError, KeyError, TypeError) as error:
            counts['invalid'] += 1
            records.append(dict(line=number, status='invalid', reason=str(error)))
    return dict(schema=1, counts=dict(counts), depth_functions=dict(functions),
                depth_changes=dict(changes), asset_blocks=blocks, records=records,
                prepared_counts=dict(prepared_counts),
                limitations=['Matching byte patterns may occur in several assets; exact material ownership and the guest writer are not identified.',
                             'Unmatched packets and layouts must not be assumed to use material defaults.',
                             'The trace is bounded to selected depth packets; it is not complete pipeline coverage.'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--states', type=Path, required=True, help='State audit report, used only as model inventory')
    ap.add_argument('--commands', type=Path, required=True, help='GCM_DEPTH_PROVENANCE JSONL')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose a new output directory in gitignored storage')
    for path in (args.states, args.commands):
        path = path.resolve()
        if output == path or output in path.parents or path in output.parents:
            ap.error('Output must be separate from inputs')
    rows = []
    with args.commands.open() as stream:
        for line in stream:
            if len(line) > 16384 or len(rows) >= 4096:
                raise ValueError('depth trace exceeds recorder bounds')
            rows.append(json.loads(line))
    blocks = asset_blocks(json.loads(args.states.read_text()))
    result = compare(rows, blocks)
    output.mkdir(parents=True)
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('counts', 'prepared_counts', 'depth_functions', 'depth_changes')}, indent=2))
    if result['counts'].get('invalid'):
        raise SystemExit('Invalid trace records; inspect report')


if __name__ == '__main__':
    main()
