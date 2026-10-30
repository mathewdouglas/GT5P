"""Compare persisted, prepared native pipeline keys with a retained live oracle.

This is validation only. Never supplies state or programs to preparation.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess

from shader_coverage import ROOT, bounded_read, fnv64
from shader_material_variants import context_name


def prepared_keys(root):
    report = json.loads((root / 'report.json').read_text())
    manifest = {j['id']: j for j in json.loads((root / 'manifest.json').read_text())}
    keys, contexts, failures = set(), {}, []
    for job in report['jobs']:
        if job['status'] != 'prepared':
            failures.append(job['id'])
            continue
        result = job['native_result']
        key = job['pipeline']
        if (not re.fullmatch('[0-9a-f]{16}', key) or not result.get('prepared') or
                result.get('expected') != '0000000000000000' or result.get('actual') != key):
            raise ValueError('Invalid capture-free preparation result')
        cache = root / 'shadercache'
        recipe = bounded_read(cache / 'warmup-v1' / f'pso_{key}.recipe', 16384)
        if (len(recipe) != 2760 or struct.unpack_from('<QIIQ', recipe) !=
                (0x31574d5241503547, 1, 2760, int(key, 16)) or
                struct.unpack_from('<Q', recipe, 2752)[0] != fnv64(recipe[:-8])):
            raise ValueError('Invalid persisted recipe')
        if not (cache / f'pso_{key}.bin').stat().st_size:
            raise ValueError('Missing persisted native driver blob')
        keys.add(key)
        candidate = manifest[job['id']]
        selected = candidate.get('contexts') or [dict(object_path=report['object_path'],
                    target_path=report['target_path'], global_path=report['global_path'] or 'none')]
        for context in selected:
            contexts.setdefault(context_name(context), set()).add(key)
    if len(report['jobs']) != report['selected_jobs']:
        raise ValueError('Incomplete preparation report')
    return keys, contexts, failures


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prepared', type=Path, required=True)
    ap.add_argument('--baseline', type=Path)
    ap.add_argument('--audit', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git','check-ignore','-q',str(output)], cwd=ROOT).returncode:
        ap.error('Choose a new ignored output file')
    for path in (args.prepared, args.baseline, args.audit):
        if path and (path.resolve() == output or path.resolve() in output.parents):
            ap.error('Output must be separate from inputs')
    keys, contexts, failures = prepared_keys(args.prepared)
    baseline = prepared_keys(args.baseline)[0] if args.baseline else set()
    rows = [r for r in json.loads(args.audit.read_text())['records'] if r['status'] == 'recipe_link_verified']
    oracle = {r['pipeline'] for r in rows}
    result = dict(verified_links=len(rows), distinct_oracle_pipelines=len(oracle),
                  prepared_native_keys=len(keys), failed_jobs=failures,
                  matched_links=sum(r['pipeline'] in keys for r in rows),
                  baseline_matched_links=sum(r['pipeline'] in baseline for r in rows),
                  added_links=sum(r['pipeline'] in keys - baseline for r in rows),
                  lost_baseline_links=sum(r['pipeline'] in baseline - keys for r in rows),
                  context_matches={k:len(v & oracle) for k,v in sorted(contexts.items())},
                  matched_pipelines=sorted(keys & oracle),
                  note='Retained snapshot native-key matches, not whole-game coverage or measured stutter reduction.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'matched_pipelines'}, indent=2))


if __name__ == '__main__':
    main()
