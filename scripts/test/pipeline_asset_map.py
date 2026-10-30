"""Verify local-asset map generation, portable lookup and fail-closed checks."""
import copy
from pathlib import Path
import struct
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).parents[1]))
from pipeline_asset_map import build,resolve,validate,identity,digest,merge
from shader_coverage import fnv64
from shader_reconstruct import word_swap

with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);assets=root/'assets';assets.mkdir();trace=root/'trace';trace.mkdir()
    fp=bytes(16)+struct.pack('>4I',0x10000,0,0,0)
    vp=struct.pack('<4I',3,4,5,1)
    elf=root/'game.elf';elf.write_bytes(b'original elf')
    # A matching first instruction is insufficient: reject the decoy slice.
    payload=b'prefix'+fp[:16]+bytes(32)+b'gap'+fp+b'other'+word_swap(vp)
    (assets/'unknown-format').write_bytes(payload)
    for stage,code in [('vp',vp),('fp',fp)]:
        (trace/f'{stage}_{fnv64(code):016x}.bin').write_bytes(code)
    record={stage:dict(sha256=identity(stage,code),size=len(code)) for stage,code in [('vp',vp),('fp',fp)]}
    doc,stats=build([record],trace,assets,elf)
    assert stats['located']==2 and stats['unresolved']==0
    assert all(set(r)=={'stage','id','size','container','container_size','offset','encoding'} for r in doc['records'])
    assert next(r for r in doc['records'] if r['stage']=='vp')['encoding']=='swap32'
    assert merge([doc,doc])==doc
    changed=copy.deepcopy(doc);changed['records'][0]['offset']+=1
    try:merge([doc,changed])
    except ValueError:pass
    else:raise AssertionError('Conflicting location map silently selected')
    other=root/'other-trace';other.mkdir()
    (trace/f'vp_{fnv64(vp):016x}.bin').replace(other/f'vp_{fnv64(vp):016x}.bin')
    (other/'fp_0000000000000000.bin').write_bytes(b'corrupt oracle')
    combined,stats=build([record],[trace,other],assets,elf)
    assert combined==doc and stats['invalid_oracles']==1 and stats['located']==2
    # No filenames or captured bytes are needed during preparation.
    for p in trace.iterdir():p.unlink()
    (assets/'unknown-format').rename(assets/'renamed-local-asset')
    wanted={(s,record[s]['sha256'],record[s]['size']) for s in ('vp','fp')}
    v,f,lookup=resolve(doc,assets,elf,wanted)
    assert v=={identity('vp',vp):vp} and f=={identity('fp',fp):fp}
    assert lookup['containers_matched']==1
    empty,stats=build([record],trace,assets,elf,wanted)
    assert not empty['records'] and stats['requested']==0
    bad=copy.deepcopy(doc);bad['records'][0]['offset']=0
    try:resolve(bad,assets,elf,wanted)
    except ValueError:pass
    else:raise AssertionError('Incorrect program slice accepted')
    for mutate in (lambda x:x.update(version=2),lambda x:x['records'].append(x['records'][0]),
                   lambda x:x['records'][0].update(offset=-1),lambda x:x['records'][0].update(size=32784),
                   lambda x:x['records'][0].update(source='forbidden'),lambda x:x['records'][0].update(container_size=True)):
        bad=copy.deepcopy(doc);mutate(bad)
        try:validate(bad)
        except ValueError:pass
        else:raise AssertionError('Malformed location accepted')
    (assets/'renamed-local-asset').write_bytes(payload[:-1]+b'x')
    v,f,lookup=resolve(doc,assets,elf,wanted)
    assert not v and not f
    v,f,lookup=resolve(doc,assets,elf,wanted,seconds=0)
    assert not v and not f and lookup['containers_hashed']==0
    # Entries outside this template never cause hashing or code materialization.
    v,f,lookup=resolve(doc,assets,elf,set())
    assert not v and not f and lookup['containers_hashed']==0
print('Asset-only lookup, endian conversion, decoy rejection, integrity, version/bounds and scan timeout passed')
