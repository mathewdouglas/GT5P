"""Prepare a template from assets into an empty cache, then paired HSR trials."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).parents[1]))
from pipeline_template import prepare
from train_pipeline_cache import isolated

ap=argparse.ArgumentParser(description=__doc__)
for name in ('template','catalog','elf','engine','decoder','fixture','output'):
    ap.add_argument('--'+name,type=Path,required=True)
ap.add_argument('--trials',type=int,choices=(2,4),default=4)
ap.add_argument('--asset-map',type=Path)
ap.add_argument('--assets',type=Path)
ap.add_argument('--fragment-mode',choices=('legacy','batch'),default='legacy')
args=ap.parse_args()
out=isolated(args.output)
if out.exists():
    ap.error('Use a new ignored output; caches are preserved')
out.mkdir(parents=True)
# Offline preparation only reads the supplied private fixture; no guest runs.
report=prepare(*(getattr(args,k).resolve() for k in ('template','catalog','elf','engine','decoder','fixture')),out/'preparation',
               asset_map=args.asset_map,assets=args.assets,fragment_mode=args.fragment_mode)
subprocess.run([sys.executable,str(Path(__file__).with_name('shader_stutter.py')),
                '--fixture',str(args.fixture.resolve()),'--engine',str(args.engine.resolve()),
                '--prepared',str(out/'preparation/shadercache'),'--output',str(out/'trials'),
                '--startup-policy','scan','--trials',str(args.trials)],check=True)
result=json.loads((out/'trials/report.json').read_text())
result['template']=dict(file_sha256=report['template_sha256'], requested=report['requested'],
                        counts=report['counts'],lookup=report['lookup'],
                        preparation_seconds=report['preparation_seconds'])
result['limitations'].append('Template preparation is timed separately; add it to the enabled first-launch wait. OS/driver caches remain warm.')
(out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
