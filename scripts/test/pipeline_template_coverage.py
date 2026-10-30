"""Representative overlap, marginal collection value and conflict quarantine."""
import copy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parents[1]))
from pipeline_template_coverage import analyze
from pipeline_template import SCHEMA,VERSION,SETTINGS,native_state
from prepare_material_shaders import request_envelope

r=dict(key='1'*16,vs='2'*16,ps='3'*16,vp_source='4'*16,fp_source='5'*16,
       vp=dict(sha256='6'*64,size=16),fp=dict(sha256='7'*64,size=16),vp_gpu=0,
       state={k:0 for k in ('blend','nrt','rtfmt','exp32','cmask','cull','stencil','unnorm','cube','vmask','ghi','shd','unhi')},
       native=native_state(request_envelope(b'DXBC',b'DXBC')))
r['state']['samplers']='0'*16
c=dict(abi='windows-x64-recipe-v1',key_version=1,root_signature_keyed=True,renderer_sha256='a'*64,
       renderer_settings=SETTINGS.copy(),elf_sha256='c'*64,translation_policy='default-constbuf-v1')
def document(records):
    return copy.deepcopy(dict(schema=SCHEMA,version=VERSION,compatibility=c,records=records))

state=copy.deepcopy(r);state['key']='8'*16;state['state']['blend']=1
novel=copy.deepcopy(r);novel['key']='9'*16;novel['fp']['sha256']='b'*64
baseline=document([r])
sessions={'Alpha':document([r,state]),'Beta':document([r,state,novel])}
report,delta=analyze(baseline,sessions)
assert report['union']['pipelines']==3 and report['additional_records']==2
assert report['additional_pipelines_with_existing_programs']==1 and report['additional_pipelines_needing_new_programs']==1
assert [x['key'] for x in delta['records']]==[state['key'],novel['key']]
beta=next(x for x in report['sessions'] if x['session']=='Beta')
assert beta['new_pipelines_with_existing_programs']==1 and beta['new_pipelines_needing_new_programs']==1
assert report['collection_priority']==[dict(session='Beta',additional_pipelines=2,cumulative_pipelines=3),
                                       dict(session='Alpha',additional_pipelines=0,cumulative_pipelines=3)]
assert report['pairwise'][0]['shared_pipelines']==2

bad=copy.deepcopy(state);bad['fp_source']='a'*16
conflicting={'Alpha':document([state]),'Beta':document([bad])}
try:analyze(baseline,conflicting)
except ValueError:pass
else:raise AssertionError('Conflicting new record selected')
report,delta=analyze(baseline,conflicting,quarantine_conflicts=True)
assert not delta['records'] and report['union']['pipelines']==1
assert report['quarantined_conflicts']==[dict(key=state['key'],differing_fields=['fp_source'])]
assert all(x['quarantined_records']==1 for x in report['sessions'])
bad=copy.deepcopy(r);bad['fp_source']='a'*16
report,delta=analyze(baseline,{'Older':document([bad])},quarantine_conflicts=True)
assert report['union']['pipelines']==1 and baseline['records'][0]['fp_source']==r['fp_source'] and not delta['records']
incompatible=document([novel]);incompatible['compatibility']['elf_sha256']='d'*64
try:analyze(baseline,{'OtherGame':incompatible},quarantine_conflicts=True)
except ValueError:pass
else:raise AssertionError('Incompatible game contract compared')
print('Overlap, program/state distinction, marginal ranking, strict conflicts and explicit quarantine passed')
