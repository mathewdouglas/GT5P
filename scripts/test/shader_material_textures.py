"""Bounded sampler-name/unit/texture-index joins; unknown lanes stay unknown."""
from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
import shader_material_textures as m
from shader_coverage import ROOT, fnv64


def fixture():
    data = bytearray(4096)
    def put(offset, fmt, *values):
        struct.pack_into('>' + fmt, data, offset, *values)
    data[:4] = b'MDL3'; put(4, 'I', len(data)); put(12, 'H', 1)
    put(0x44, 'I', 256); put(0x4C, 'I', 384)
    put(256, 'HHBBHIIII', 1, 1, 0, 0, 2, 1152, 512, 0, 1536)
    data[384:388] = b'SHDS'; put(384 + 0x18, 'HH', 1, 1)
    for offset, value in ((0x20, 640), (0x2C, 704), (0x40, 800)):
        put(384 + offset, 'I', value)
    put(384 + 0x34, 'H', 1)
    put(548, 'I', 576); put(588, 'II', 640, 704)
    put(640, 'II', 896, 64); put(704, 'II', 1000, 32)
    put(800, 'III', 1000, 1056, 16)
    put(896, 'H', 2); put(912, 'I', 32); data[928:960] = bytes(range(32))
    instruction = 0x17000001 | (2 << 17)
    put(1056, 'IIII', ((instruction << 16) | (instruction >> 16)) & 0xFFFFFFFF, 0, 0, 0)
    data[715] = 1; put(724, 'I', 1280)
    put(1280, 'I4hI', 1400, 0x601, 2, 0, 0, 0)
    data[1400:1418] = b'diffuseMapSampler\0'
    put(1156, 'hhHHI', 0, 0, 1, 1, 1440)
    put(1440, 'II', 1400, 1)
    for index in range(2):
        words = [0] * 17
        words[0], words[2], words[3], words[6], words[7], words[14] = (
            0x00201A00, 0x00018829, 0x303, 0x02060000, 0x00400040, 1 if index == 0 else 42)
        put(1536 + index * 68, '17I', *words)
    return data


data = fixture(); definitions, rejected = m.model_textures(data, 0)
assert not rejected and len(definitions) == 1
d = definitions[0]; b = d['bindings'][0]
assert b['unit'] == 2 and b['texture_index'] == 1 and b['image_id'] == 42
assert b['sampler'] == 13 and d['used'] == 4
assert m.complete_sampler_key(d) == 13 << 8
assert m.replace_known_samplers(0x1234, d['bindings'], 4) == (0x1D34, [2])
assert m.replace_known_samplers(0x1234, d['bindings'], 1) == (0x1234, [])
assert m.complete_sampler_key(dict(d, used=5)) is None
assert m.known_sampler_key(dict(d, used=5)) == (13 << 8, 15 << 8)
assert m.complete_sampler_key(dict(d, used=0)) is None

for name, kind, identifier in (('ditherMap', 0x601, 94), ('ditherMap', 0x801, 103),
                               ('shadowPCFMap', 0x801, 104)):
    g = dict(name=name, kind=kind, identifier=identifier, unit=15)
    definition = dict(d, used=d['used'] | (1 << 15), globals=[g])
    assert m.with_global_sampler_path(definition) is definition
    for path, sampler in (('active', 4), ('fallback', 8)):
        resolved = m.with_global_sampler_path(definition, path)
        assert not resolved['globals'] and len(definition['globals']) == 1
        assert m.complete_sampler_key(resolved) == (13 << 8) | (sampler << 60)
        for field, value in (('name', 'unknown'), ('kind', 0x901), ('identifier', 999)):
            bad = dict(definition, globals=[dict(g, **{field: value})])
            assert m.complete_sampler_key(m.with_global_sampler_path(bad, path)) is None
        duplicate = dict(definition, globals=[g, g])
        assert m.complete_sampler_key(m.with_global_sampler_path(duplicate, path)) is None
        overlap = dict(definition, globals=[dict(g, unit=2)])
        assert m.known_sampler_key(m.with_global_sampler_path(overlap, path)) == (0, 0)
try:
    m.with_global_sampler_path(definition, 'guessed')
    raise AssertionError('unknown global path accepted')
except ValueError:
    pass

for name, identifier in (('realTimeShadowMap', 87), ('realTimeShadowMapColor', 96)):
    g = dict(name=name, kind=0x601, identifier=identifier, unit=13)
    definition = dict(d, bindings=[b], used=(1 << b['unit']) | (1 << 13), globals=[g])
    resolved = m.with_global_sampler_path(definition, shadow_path='shadow-lv')
    assert m.complete_sampler_key(resolved) == (13 << 8) | (9 << 52)
    assert m.complete_sampler_key(m.with_global_sampler_path(definition, 'active')) is None
    for field, value in (('name', 'envMapSampler'), ('kind', 0x801), ('identifier', 71)):
        bad = dict(definition, globals=[dict(g, **{field: value})])
        assert m.complete_sampler_key(m.with_global_sampler_path(bad, shadow_path='shadow-lv')) is None
try:
    m.with_global_sampler_path(definition, shadow_path='all-shadows')
    raise AssertionError('unknown shadow pass accepted')
except ValueError:
    pass

for offset, fmt, value, reason in [(1444, 'I', 42, 'texture index outside table'),
                                  (1284, 'h', 0x602, 'unsupported sampler record'),
                                  (1286, 'h', 16, 'unsupported sampler record'),
                                  (1604, 'I', 0, 'unsupported texture record header')]:
    data = fixture(); struct.pack_into('>' + fmt, data, offset, value)
    definitions, rejected = m.model_textures(data, 0)
    assert rejected[reason] == 1 and not definitions, rejected
data = fixture(); struct.pack_into('>H', data, 1162, 0)
d = m.model_textures(data, 0)[0][0]
assert not d['bindings'] and len(d['unresolved']) == 1 and m.complete_sampler_key(d) is None
data = fixture(); data[715] = 2; data[1296:1312] = data[1280:1296]
assert m.model_textures(data, 0)[1]['ambiguous sampler name/unit'] == 1
data = fixture(); data[715] = 2
data[1464:1482] = b'ambientMapSampler\0'
struct.pack_into('>I4hI', data, 1296, 1464, 0x601, 2, 0, 0, 0)
struct.pack_into('>H', data, 1162, 2)
struct.pack_into('>II', data, 1448, 1464, 1)
d = m.model_textures(data, 0)[0][0]
assert len(d['bindings']) == 1 and d['bindings'][0]['aliases'] == ['diffuseMapSampler', 'ambientMapSampler']
assert m.complete_sampler_key(d) == 13 << 8
struct.pack_into('>I', data, 1452, 0)  # Even identical sampler settings do not justify different image records.
assert m.model_textures(data, 0)[1]['conflicting scalar alias textures'] == 1
struct.pack_into('>H', data, 1162, 1)
d = m.model_textures(data, 0)[0][0]
assert not d['bindings'] and d['unresolved'][0]['reason'] == 'missing scalar alias binding'
data = fixture(); data[714] = 1
struct.pack_into('>I', data, 760, 1800)
struct.pack_into('>I4hI', data, 1800, 1856, 0x601, 2, 0, 0, 87)
data[1856:1866] = b'shadowMap\0'
d = m.model_textures(data, 0)[0][0]
assert d['globals'] == [dict(name='shadowMap', kind=0x601, unit=2, identifier=87)]
assert m.complete_sampler_key(d) is None  # Global settings must never inherit a local alias's defaults.
assert m.known_sampler_key(d) == (0, 0)
data = fixture(); struct.pack_into('>I', data, 276, 4090)
try:
    m.model_textures(data, 0)
except ValueError:
    pass
else:
    raise AssertionError('out-of-model texture table accepted')

with tempfile.TemporaryDirectory(prefix='material-textures-cli-', dir=ROOT / 'scratch') as folder:
    root = Path(folder)
    asset = root / 'asset'; asset.write_bytes(fixture())
    inventory = root / 'states.json'; inventory.write_text(json.dumps(dict(models=[dict(file=str(asset), model=0)])))
    d = m.model_textures(fixture(), 0)[0][0]
    trace = root / 'trace'; trace.mkdir()
    code = d['vertex_code']; raw = f'{fnv64(code):016x}'
    (trace / f'vp_{raw}.bin').write_bytes(code)
    c = dict(vp_raw=raw, vp_bytes=len(code), vp_identity_bytes=len(code), pipeline='synthetic',
             state=dict(samplers='0000000000000d00'))
    row = dict(status='recipe_link_verified', vertex_input_available=True,
               capture=c, identity=d['fragment_identity'], line=1)
    changed = json.loads(json.dumps(row)); changed['line'] = 2
    changed['capture']['state']['samplers'] = '0000000000000c00'
    report = root / 'audit.json'; report.write_text(json.dumps(dict(records=[row, changed])))
    output = root / 'output'
    command = [sys.executable, str(ROOT / 'scripts/shader_material_textures.py'), '--states', str(inventory),
               '--report', str(report), '--trace', str(trace), '--output', str(output)]
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    subprocess.run(command, check=True, capture_output=True)
    result = json.loads((output / 'report.json').read_text())
    assert result['counts']['known_lanes_match'] == result['counts']['known_lanes_mismatch'] == 1
    assert result['counts']['all_sampled_units_resolved_and_match'] == 1
    assert subprocess.run(command, capture_output=True).returncode != 0
    command[-1] = str(trace / 'bad-output')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert not (trace / 'bad-output').exists()
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file() and output not in p.parents}
    (trace / f'vp_{raw}.bin').write_bytes(bytes(len(code)))
    command[-1] = str(root / 'bad-input-output')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert not Path(command[-1]).exists()

print('Sampler slots, texture-index identity, partial coverage and malformed binding checks passed')
