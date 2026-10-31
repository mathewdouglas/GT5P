"""Generate hash/offset metadata from verified original asset slices, never bytes."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline_template import read
from pipeline_asset_map import validate,identity
from shader_reconstruct import vertex_programs,word_swap
from shader_coverage import fp_identity


def build(template,catalog,supplement):
    records=read(template)['records']
    wanted={(s,r[s]['sha256'],r[s]['size']) for r in records for s in ('vp','fp')}
    found={(r['stage'],r['id'],r['size']):r for r in supplement['records']}
    index=json.loads((catalog/'index.json').read_text())
    sources={}
    for r in index['sources']:sources.setdefault(r['file'],[]).append(r)
    for name,entries in sorted(sources.items()):
        p=Path(name)
        with p.open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            container=None
            def add(stage,code,offset,encoding):
                nonlocal container
                try:key=(stage,identity(stage,code),len(code))
                except ValueError:return
                if key not in wanted or key in found:return
                if container is None:container=hashlib.sha256(data).hexdigest()
                found[key]=dict(stage=stage,id=key[1],size=len(code),offset=offset,
                                encoding=encoding,container=container,container_size=len(data))
            for r in entries:
                raw=data[r['offset']:r['offset']+r['size']]
                if hashlib.sha256(raw).hexdigest()!=r['sha256']:raise ValueError('Original asset changed')
                try:raw=raw[:fp_identity(raw)['size']]
                except ValueError:continue
                add('fp',raw,r['offset'],'native')
            lengths={size for s,_,size in wanted-found.keys() if s=='vp'}
            if lengths:
                for r in vertex_programs(data):
                    raw=word_swap(data[r['offset']:r['offset']+r['size']])
                    for size in lengths:
                        if size<=len(raw):add('vp',raw[:size],r['offset'],'swap32')
    missing=wanted-found.keys()
    if missing:raise ValueError(f'Unresolved program locations: {len(missing)}, examples {list(missing)[:3]}')
    return validate(dict(schema='gt5p-program-locations',version=1,
                         records=[found[k] for k in sorted(wanted)]))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('template','catalog','supplement','output'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args()
    result=build(a.template,a.catalog,json.loads(a.supplement.read_text()))
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(f"Verified locations for {len(result['records'])} unique programs; metadata only")
