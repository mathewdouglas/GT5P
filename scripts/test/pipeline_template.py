"""Template schema, numeric state, integrity and merge conflict rejection."""
import copy
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from pipeline_template import validate, envelope, native_state, has_flow, SCHEMA
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
         engine_sha256='a'*64, decoder_sha256='b'*64, elf_sha256='c'*64,
         translation_policy='default-constbuf-v1')
d = dict(schema=SCHEMA, version=1, compatibility=c, records=[r])
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

reject(lambda x:x.update(version=2))
reject(lambda x:x['compatibility'].update(key_version=2))
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
