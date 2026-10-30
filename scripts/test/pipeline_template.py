"""Template schema, numeric state, integrity and merge conflict rejection."""
import copy
import tempfile
from unittest.mock import patch
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from pipeline_template import validate, envelope, native_state, has_flow, SCHEMA, VERSION, SETTINGS, merge, bundle, read, prepare, renderer_contract
from prepare_material_shaders import request_envelope

data = bytearray(request_envelope(b'DXBC', b'DXBC'))
struct.pack_into('<I', data, 48 + 560, 1)
data[736:740] = b'ATTR'
r = dict(key='1'*16, vs='2'*16, ps='3'*16, vp_source='4'*16, fp_source='5'*16,
         vp=dict(sha256='6'*64, size=16), fp=dict(sha256='7'*64, size=16), vp_gpu=0,
         state={k: 0 for k in ('blend','nrt','rtfmt','exp32','cmask','cull','stencil','unnorm','cube','vmask','ghi','shd','unhi')},
         native=native_state(data))
r['state']['samplers'] = '0'*16
c = dict(abi='windows-x64-recipe-v1', key_version=1, root_signature_keyed=True,
         renderer_sha256='a'*64, renderer_settings=SETTINGS.copy(), elf_sha256='c'*64,
         translation_policy='default-constbuf-v1')
d = dict(schema=SCHEMA, version=VERSION, compatibility=c, records=[r])
assert validate(copy.deepcopy(d)) == d
assert native_state(envelope(r,b'DXBC',b'DXBC')) == r['native']
x=copy.deepcopy(d);x['records'].append(copy.deepcopy(r));assert len(validate(x)['records'])==1

def reject(change):
    x=copy.deepcopy(d);change(x)
    try:
        validate(x)
    except (ValueError, TypeError, KeyError):
        return
    raise AssertionError('Invalid template accepted')

reject(lambda x:x.update(version=1))
reject(lambda x:x['compatibility'].update(key_version=2))
reject(lambda x:x['compatibility']['renderer_settings'].update(RSX_ANISO='8'))
reject(lambda x:x['compatibility'].update(root_signature_keyed=False))
reject(lambda x:x['records'][0].update(source='forbidden shader source'))
reject(lambda x:x['records'][0]['vp'].update(size=32784))
reject(lambda x:x['records'][0]['state'].update(unknown=1))
reject(lambda x:x['records'][0]['native']['words'].__setitem__(0,123))
reject(lambda x:x['records'][0]['native']['words'].__setitem__(140,33))
reject(lambda x:x['records'][0]['native']['words'].__setitem__(24,1))
reject(lambda x:x['records'][0]['native']['inputs'][0].__setitem__(0,-1))
reject(lambda x:x['records'].append(dict(copy.deepcopy(r),ps='f'*16)))
reject(lambda x:x.update(records=[r]*4097))
end=struct.pack('<4I',0,0,0,1)
assert not has_flow(end)
assert has_flow(struct.pack('<4I',0,8<<27,0,1))
try:
    has_flow(bytes(16))
except ValueError:
    pass
else:
    raise AssertionError('Missing VP END accepted')
print('Template version, bounds, pointers, state, duplicate conflicts and branch rejection passed')

assert len(merge([copy.deepcopy(d)] * 5000)['records']) == 1
for bad in (None, [], {'records': 1}):
    try:
        validate(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('Malformed document accepted')
print('Multi-session merge deduplicates before enforcing the union cap')

with tempfile.TemporaryDirectory() as temporary:
    path=Path(temporary)/'bundle'
    bundle(copy.deepcopy(d),path)
    assert read(path)==d
    part=path/'part-0000.json'
    part.write_bytes(part.read_bytes()+b' ')
    try:
        read(path)
    except ValueError:
        pass
    else:
        raise AssertionError('Corrupt metadata shard accepted')
print('Metadata bundles round-trip and reject altered parts')

# Keep this synthetic rejection independent of a concurrently owned game. No
# decoder or offline engine is permitted to start when the header is invalid.
from shader_coverage import ROOT
(ROOT/'scratch').mkdir(exist_ok=True)
work=Path(tempfile.mkdtemp(prefix='template-fallback-',dir=ROOT/'scratch'))
invalid=work/'invalid.json';invalid.write_text('{"version":999}')
with patch('pipeline_template.idle'), patch('pipeline_template.NativeCompiler',side_effect=AssertionError('Decoder started for invalid header')):
    fallback=prepare(invalid,work,work/'elf',work/'engine',work/'decoder',work,work/'result',demand_fallback=True)
assert fallback['counts']=={'template-rejected':1}
assert (work/'result/shadercache/warmup-v1').is_dir()
assert not list((work/'result/shadercache/warmup-v1').iterdir())
print('Incompatible-header fallback writes no recipes and starts no compiler')

starter=ROOT/'assets/pipeline-templates/gt5p-disc-v2'
if starter.exists():
    metadata=read(starter)
    assert metadata['compatibility']['renderer_sha256']==renderer_contract()
    assert len(metadata['records'])<=4096
    print('Bundled starter metadata matches the current renderer contract')
    if (starter/'asset-map.json').exists():
        from pipeline_asset_map import read as read_map
        locations=read_map(starter/'asset-map.json')
        programs={(s,r[s]['sha256'],r[s]['size']) for r in metadata['records'] for s in ('vp','fp')}
        assert all((r['stage'],r['id'],r['size']) in programs for r in locations['records'])
        print('Supplemental asset locations reference only bundled program identifiers')
