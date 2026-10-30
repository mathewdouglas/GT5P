"""Compare representative templates and emit only newly observed candidates.

This measures metadata overlap, not shader reconstruction, native preparation
or draw/stutter coverage. All sessions must share the same renderer/game contract.
"""
import argparse
import json
from pathlib import Path
import re

from pipeline_template import merge,read,validate
from train_pipeline_cache import isolated,save_report


def footprint(document):
    r = document['records']
    return dict(pipelines={x['key'] for x in r},
                vp={(x['vp']['sha256'],x['vp']['size']) for x in r},
                fp={(x['fp']['sha256'],x['fp']['size']) for x in r},
                pairs={(x['vp']['sha256'],x['fp']['sha256']) for x in r},
                vertex_variants={x['vp_source'] for x in r},
                fragment_variants={x['fp_source'] for x in r},
                translation_states={json.dumps(x['state'],sort_keys=True,separators=(',',':')) for x in r})


def analyze(baseline,sessions,quarantine_conflicts=False):
    if not 1 <= len(sessions) <= 16 or any(not re.fullmatch('[A-Za-z0-9_-]{1,64}',label) for label in sessions):
        raise ValueError('Supply 1..16 uniquely named sessions')
    baseline=validate(baseline)
    inputs={label:len(document['records']) for label,document in sessions.items()}
    seen={r['key']:r for r in baseline['records']}
    conflicts={}
    for label,document in sessions.items():
        validate(document)
        # Check compatibility even when every record is later quarantined.
        merge([baseline,dict(document,records=[])])
        for r in document['records']:
            if r['key'] in seen and r != seen[r['key']]:
                conflicts.setdefault(r['key'],set()).update(k for k in r if r[k]!=seen[r['key']][k])
            else:seen.setdefault(r['key'],r)
    if conflicts and not quarantine_conflicts:
        raise ValueError('Conflicting session records; inspect or explicitly quarantine them')
    # Preserve the supplied baseline, discard all conflicting session versions.
    # Never choose between conflicting new records by session/order/majority.
    sessions={label:dict(d,records=[r for r in d['records'] if r['key'] not in conflicts]) for label,d in sessions.items()}
    union = merge([baseline,*sessions.values()])
    base = footprint(baseline)
    footprints = {label:footprint(document) for label,document in sessions.items()}
    rows = []
    for label,document in sessions.items():
        f = footprints[label]
        new = [r for r in document['records'] if r['key'] not in base['pipelines']]
        existing = sum((r['vp']['sha256'],r['vp']['size']) in base['vp'] and
                       (r['fp']['sha256'],r['fp']['size']) in base['fp'] for r in new)
        rows.append(dict(session=label,input_records=inputs[label],quarantined_records=inputs[label]-len(document['records']),
                         totals={k:len(v) for k,v in f.items()},
                         shared_with_baseline={k:len(v & base[k]) for k,v in f.items()},
                         additional_to_baseline={k:len(v - base[k]) for k,v in f.items()},
                         new_pipelines_with_existing_programs=existing,
                         new_pipelines_needing_new_programs=len(new)-existing))
    current = set(base['pipelines'])
    remaining = set(sessions)
    order = []
    while remaining:
        label = min(remaining,key=lambda name:(-len(footprints[name]['pipelines']-current),name))
        added = len(footprints[label]['pipelines']-current)
        current.update(footprints[label]['pipelines'])
        order.append(dict(session=label,additional_pipelines=added,cumulative_pipelines=len(current)))
        remaining.remove(label)
    delta = validate(dict(union,records=[r for r in union['records'] if r['key'] not in base['pipelines']]))
    reused=sum((r['vp']['sha256'],r['vp']['size']) in base['vp'] and
               (r['fp']['sha256'],r['fp']['size']) in base['fp'] for r in delta['records'])
    report = dict(schema='gt5p-template-coverage',version=1,
                  policy='Observed metadata overlap only; delta candidates require asset/shader/native verification. No whole-game or stutter claim.',
                  baseline={k:len(v) for k,v in base.items()},
                  union={k:len(v) for k,v in footprint(union).items()},
                  additional_records=len(delta['records']),additional_pipelines_with_existing_programs=reused,
                  additional_pipelines_needing_new_programs=len(delta['records'])-reused,
                  sessions=rows,collection_priority=order,
                  quarantined_conflicts=[dict(key=k,differing_fields=sorted(fields)) for k,fields in sorted(conflicts.items())],
                  pairwise=[dict(left=a,right=b,shared_pipelines=len(footprints[a]['pipelines'] & footprints[b]['pipelines']),
                                 shared_program_pairs=len(footprints[a]['pairs'] & footprints[b]['pairs']))
                            for i,a in enumerate(sorted(sessions)) for b in sorted(sessions)[i+1:]])
    return report,delta


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline',type=Path,required=True)
    ap.add_argument('--session',action='append',required=True,help='Unique label=template path; repeat per session')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--delta-output',type=Path,help='Optional template of candidates absent from the baseline')
    ap.add_argument('--quarantine-conflicts',action='store_true',help='Exclude all conflicting session records; preserve the supplied baseline')
    args=ap.parse_args()
    if not 1 <= len(args.session) <= 16:
        ap.error('Supply 1..16 representative sessions')
    outputs=[isolated(p) for p in (args.output,args.delta_output) if p is not None]
    if len(set(outputs))!=len(outputs) or any(p.exists() for p in outputs):
        ap.error('Use distinct fresh ignored output files; existing data is preserved')
    sessions={}
    for item in args.session:
        label,separator,name=item.partition('=')
        if not separator or label in sessions:
            ap.error('Sessions require unique labels and label=template paths')
        sessions[label]=read(Path(name))
    report,delta=analyze(read(args.baseline),sessions,args.quarantine_conflicts)
    for p in outputs:p.parent.mkdir(parents=True,exist_ok=True)
    save_report(outputs[0],report)
    if args.delta_output is not None:save_report(outputs[1],delta)
    print(json.dumps(dict(union=report['union'],additional_records=report['additional_records'],
                          collection_priority=report['collection_priority'])))


if __name__=='__main__':
    main()
