"""Real offline manifest bounds, gating, program checks and cache reuse.

Inputs/outputs stay local. No guest execution or live-game policy changes.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).parents[1]))
from shader_reconstruct import offline_env,run_offline
from train_pipeline_cache import isolated,idle

ap=argparse.ArgumentParser(description=__doc__)
for name in ('engine','game-root','batch','output'):
    ap.add_argument('--'+name,type=Path,required=True)
args=ap.parse_args();idle();out=isolated(args.output)
if out.exists():ap.error('Use a fresh ignored output')
out.mkdir(parents=True)
source=(args.batch/'jobs.txt').read_text().splitlines()[1].split()
assert len(source)==12
raw=(args.batch/(source[1]+'.fp')).read_bytes()
rows=[]
cases=('version','overflow','duplicate','path','profile','trailing','raw-hash','textures','oversized','disabled','valid')
for case in cases:
    work=out/case;work.mkdir();cache=work/'shadercache';cache.mkdir()
    fields=source.copy();header='GT5P_FP_BATCH_V1 1\n';tail='';body=raw
    if case=='version':header='GT5P_FP_BATCH_V2 1\n'
    if case=='overflow':header='GT5P_FP_BATCH_V1 4294967297\n'
    if case=='path':fields[1]='../'+fields[1]
    if case=='profile':fields[3]='2'
    if case=='trailing':tail='unexpected trailing data\n'
    if case=='raw-hash':fields[2]=f'{int(fields[2],16)^1:016x}'
    if case=='textures':fields[-1]=f'{int(fields[-1],16)^1:x}'
    if case=='oversized':body=raw+bytes(32784-len(raw))
    line=' '.join(fields)+'\n'
    if case=='duplicate':header='GT5P_FP_BATCH_V1 2\n';line+=line
    (work/'jobs.txt').write_text(header+line+tail)
    (work/(source[1]+'.fp')).write_bytes(body)
    env=offline_env(args.game_root.resolve(),cache)
    env.update(RSX_SHADER_LIBRARY_BATCH='0' if case=='disabled' else str(work),RSX_FINAL_DITHER='1')
    text=run_offline(args.engine.resolve(),args.game_root.resolve(),env,work/'native.log')
    result=work/'compiled.tsv'
    if case in ('raw-hash','textures','oversized'):
        assert result.exists() and result.read_text().splitlines()[1].split()[-1]=='0'
        assert not list(cache.glob('*.dxbc'))
    elif case!='valid':
        assert not result.exists() and not list(cache.glob('*.dxbc'))
    else:
        first=result.read_bytes()
        assert first.decode().splitlines()[1].split()[-1]=='1' and list(cache.glob('*.dxbc'))
        second=run_offline(args.engine.resolve(),args.game_root.resolve(),env,work/'repeat.log')
        assert result.read_bytes()==first
        assert re.search(r'\[fp-batch\] finished: requests=1 rejected=0 compiled=0 ',second)
    rows.append(dict(case=case,passed=True))
(out/'report.json').write_text(json.dumps(rows,indent=2)+'\n')
print('Native batch schema/bounds/gating, program integrity, texture mask and cache reuse passed')
