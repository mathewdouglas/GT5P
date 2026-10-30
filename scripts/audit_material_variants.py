"""Compare explicit asset-derived context candidates with a retained live oracle.

Candidate construction precedes oracle loading. Matches here are whole-profile
and program-prefix candidates, not native pipeline creation proofs.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess

from shader_coverage import ROOT, MAX_FP, bounded_read, fnv64, fp_identity
from shader_material_variants import enumerate_variants, context_name


def compare(jobs, rows, trace):
    by_fragment = defaultdict(list)
    for job in jobs:
        by_fragment[fp_identity(job['fragment'])['identity']].append(job)
    matches, nearest, verified = defaultdict(set), Counter(), []
    for row in rows:
        if row['status'] != 'recipe_link_verified':
            continue
        verified.append(row)
        c = row['capture']
        if not re.fullmatch('[0-9a-f]{16}', c['vp_raw']):
            raise ValueError('Invalid oracle vertex identifier')
        raw = bounded_read(trace / f"vp_{c['vp_raw']}.bin", MAX_FP)
        if len(raw) != c['vp_bytes'] or f'{fnv64(raw):016x}' != c['vp_raw']:
            raise ValueError('Oracle vertex checksum/length mismatch')
        length = c['vp_identity_bytes']
        if not 32 <= length <= len(raw):
            raise ValueError('Invalid oracle vertex identity extent')
        prefix, best = raw[:length], None
        for job in by_fragment.get(row['identity'], ()):
            if c['vp_gpu'] != 1 or c['fp_flags'] or not job['vertex'].startswith(prefix):
                continue
            missing = tuple(k for k, v in job['state'].items() if c['state'].get(k) != v)
            if best is None or len(missing) < len(best):
                best = missing
            if not missing:
                for context in job['contexts']:
                    matches[context_name(context)].add(row['pipeline'])
        nearest['no_supported_program_pair' if best is None else ','.join(best) or 'match'] += 1
    union = set().union(*matches.values()) if matches else set()
    return dict(verified_links=len(verified), distinct_oracle_pipelines=len({r['pipeline'] for r in verified}),
                context_matches={k: sorted(v) for k, v in sorted(matches.items())},
                union_pipelines=sorted(union), union_links=sum(r['pipeline'] in union for r in verified),
                nearest_profile_mismatches=dict(nearest),
                note='Conditional program/profile candidates only; native bytecode/key creation must confirm coverage.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('catalog', 'audit', 'trace', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--context-set', choices=('supported', 'rgba16'), default='supported')
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose new ignored output storage')
    for path in (args.catalog, args.audit, args.trace):
        path = path.resolve()
        if output == path or output in path.parents or path in output.parents:
            ap.error('Output must be separate from inputs')
    jobs, inventory = enumerate_variants(args.catalog, args.context_set)
    output.mkdir(parents=True)
    # Freeze every independent candidate before the oracle is read.
    (output / 'manifest.json').write_text(json.dumps([
        {k: v for k, v in j.items() if k not in ('vertex', 'fragment')} for j in jobs], indent=2) + '\n')
    result = compare(jobs, json.loads(args.audit.read_text())['records'], args.trace)
    result['inventory'] = inventory
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(links=result['verified_links'], union_links=result['union_links'],
                          candidates=len(jobs), contexts={k:len(v) for k,v in result['context_matches'].items()},
                          nearest=result['nearest_profile_mismatches']), indent=2))


if __name__ == '__main__':
    main()
