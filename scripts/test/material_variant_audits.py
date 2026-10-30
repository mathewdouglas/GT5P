"""Oracle integrity, link/key denominators and persisted-result checks."""
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import struct
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).parents[1]))
from audit_material_variants import compare
from audit_prepared_materials import prepared_keys
from prepare_material_shaders import request_envelope
from shader_coverage import ROOT, fnv64, fp_identity
from shader_material_variants import contexts

# Keep even synthetic shadercache fixtures in ignored storage; never delete them.
with nullcontext(tempfile.mkdtemp(prefix='material-variant-audit-test-', dir=ROOT / 'scratch')) as folder:
    root = Path(folder)
    raw = b'v' * 32
    fragment = struct.pack('>4I', 0x10000, 0, 0, 0)
    raw_hash = f'{fnv64(raw):016x}'
    vp = root / f'vp_{raw_hash}.bin';vp.write_bytes(raw)
    job = dict(fragment=fragment, vertex=raw, state=dict(cull=5), contexts=[contexts('supported')[0]])
    row = dict(status='recipe_link_verified', pipeline='0000000000000001',
               identity=fp_identity(fragment)['identity'], capture=dict(vp_raw=raw_hash,
               vp_bytes=32,vp_identity_bytes=32,vp_gpu=1,fp_flags=0,state=dict(cull=5)))
    before = copy.deepcopy(job)
    report = compare([job], [row, row], root)
    assert report['union_links'] == 2 and report['distinct_oracle_pipelines'] == 1
    assert job == before
    wrong = copy.deepcopy(row);wrong['capture']['state']['cull'] = 1
    assert compare([job], [wrong], root)['nearest_profile_mismatches'] == {'cull':1}
    vp.write_bytes(b'corrupt')
    try:
        compare([job], [row], root)
    except ValueError:
        pass
    else:
        raise AssertionError('Corrupted oracle accepted')

    cache = root / 'shadercache';warm = cache / 'warmup-v1';warm.mkdir(parents=True)
    key = '0000000000000001'
    recipe = bytearray(request_envelope(b'DXBC vertex', b'DXBC fragment'))
    struct.pack_into('<Q',recipe,16,1)
    struct.pack_into('<Q',recipe,2752,fnv64(recipe[:-8]))
    (warm / f'pso_{key}.recipe').write_bytes(recipe)
    (cache / f'pso_{key}.bin').write_bytes(b'local driver blob')
    result = dict(selected_jobs=1, jobs=[dict(id='job',status='prepared',pipeline=key,
                  native_result=dict(prepared=True,expected='0000000000000000',actual=key))])
    (root / 'report.json').write_text(json.dumps(result))
    (root / 'manifest.json').write_text(json.dumps([dict(id='job',contexts=[contexts('supported')[0]])]))
    assert prepared_keys(root)[0] == {key}
    recipe[-1] ^= 1;(warm / f'pso_{key}.recipe').write_bytes(recipe)
    try:
        prepared_keys(root)
    except ValueError:
        pass
    else:
        raise AssertionError('Corrupt persisted recipe accepted')
print('Oracle integrity, candidate immutability, distinct link/key counts and persisted recipe checks passed')
