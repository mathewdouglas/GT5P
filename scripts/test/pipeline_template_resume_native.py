"""Interrupt after real shader preparation, resume without compiles, recheck PSOs."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]))
import pipeline_template as tool
from train_pipeline_cache import isolated,idle

def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('template','catalog','elf','engine','decoder','game-root','assets','asset-map','output'):
        ap.add_argument('--'+name,type=Path,required=True)
    args=ap.parse_args();idle();base=isolated(args.output)
    if base.exists():ap.error('Use a fresh ignored test output')
    base.mkdir()
    common=[getattr(args,k).resolve() for k in ('catalog','elf','engine','decoder','game_root')]
    options=dict(assets=args.assets.resolve(),asset_map=args.asset_map.resolve())
    document=tool.read(args.template)
    template=args.template.resolve();run=base/'run'
    original=tool.compile_fragments
    def interrupted(*a,**kw):
        compiled,failures=original(*a,**kw)
        assert compiled and not failures
        raise KeyboardInterrupt()
    with patch('pipeline_template.compile_fragments',side_effect=interrupted):
        try:tool.prepare(template,*common,run,**options)
        except KeyboardInterrupt:pass
        else:raise AssertionError('Expected controlled interruption')
    state=json.loads((run/'preparation-state.json').read_text())
    assert state['phase']=='interrupted'
    cache_ids=lambda:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (run/'shadercache').glob('*.dxbc')}
    before=cache_ids()
    def no_fragment_work(jobs,*a,**kw):
        assert not jobs,'Completed fragment shaders were submitted again'
        return original(jobs,*a,**kw)
    reports=[]
    for attempt in (2,3):
        with (patch('pipeline_template.NativeCompiler',side_effect=AssertionError('Vertex compiler restarted')),
              patch('pipeline_template.compile_fragments',side_effect=no_fragment_work)):
            report=tool.prepare(template,*common,run,resume=True,**options)
        assert report['counts']=={'prepared':len(document['records'])}
        assert report['resume']['attempt']==attempt and report['resume']['vertex_programs_compiled']==0
        assert report['resume']['fragment_jobs_reused']==len(document['records'])
        assert report['fragment_preparation']['processes']==0
        assert cache_ids()==before
        state=json.loads((run/'preparation-state.json').read_text())
        assert state['phase']=='complete' and state['attempt']==attempt
        native=(run/'native.log').read_text(errors='replace')
        calls=re.search(r'requests=(\d+) created=(\d+) driver_calls=(\d+) cached_blob_calls=(\d+)',native)
        assert calls and list(map(int,calls.groups()[:3]))==[len(document['records'])]*3
        assert int(calls[4])==(len(document['records']) if attempt==3 else 0)
        reports.append(dict(attempt=attempt,seconds=report['preparation_seconds'],resume=report['resume'],
                            native_counts=list(map(int,calls.groups()))))
        (base/f'completed-attempt-{attempt}.json').write_text(json.dumps(report,indent=2)+'\n')
    previous_state=(run/'preparation-state.json').read_bytes()
    bad=copy.deepcopy(document);bad['records'][0]['state']['cube']^=1
    other=base/'different-template.json';other.write_text(json.dumps(bad))
    with patch('pipeline_template.NativeCompiler',side_effect=AssertionError('Compiler started')):
        try:tool.prepare(other,*common,run,resume=True,**options)
        except ValueError:pass
        else:raise AssertionError('Changed template resumed')
    assert (run/'preparation-state.json').read_bytes()==previous_state and cache_ids()==before
    # Separate output holds a deliberately corrupt copy. Keep the successful
    # cache intact; never delete/move shadercache directories to simulate loss.
    corrupt=base/'corrupt-copy'
    with patch('pipeline_template.locate',side_effect=KeyboardInterrupt):
        try:tool.prepare(template,*common,corrupt,**options)
        except KeyboardInterrupt:pass
    source=document['records'][0]['vp_source']+'.dxbc'
    data=bytearray((run/'shadercache'/source).read_bytes());data[-1]^=1
    (corrupt/'shadercache'/source).write_bytes(data)
    with (patch('pipeline_template.NativeCompiler',side_effect=AssertionError('Compiler started')),
          patch('pipeline_template.run_offline',side_effect=AssertionError('Native process started'))):
        try:tool.prepare(template,*common,corrupt,resume=True,**options)
        except ValueError as exc:assert 'resume verification' in str(exc)
        else:raise AssertionError('Corrupted bytecode resumed')
    assert (corrupt/'shadercache'/source).read_bytes()==data and cache_ids()==before
    (base/'validation.json').write_text(json.dumps(dict(interrupted_resume=True,zero_shader_compiles=True,
        native_revalidated=True,changed_template_rejected=True,corrupt_cache_preserved=True,attempts=reports),indent=2)+'\n')
    print('Interrupted resume, zero shader recompiles, native revalidation, contract and corrupt-cache rejection passed')


if __name__=='__main__':main()
