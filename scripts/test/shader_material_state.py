"""State parsing, material bindings and capture mismatch accounting checks."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
import shader_material_state as m
from shader_material_state_native import words


def fixture():
    d = bytearray(2048)
    d[:4] = b'MDL3'
    def put(offset, fmt, *values):
        struct.pack_into('>' + fmt, d, offset, *values)
    put(4, 'I', len(d)); put(12, 'H', 1)
    put(0x44, 'I', 256); put(0x4C, 'I', 384)
    put(256, 'HHBBHIIII', 2, 1, 0, 2, 0, 1152, 512, 1280, 0)
    d[384:388] = b'SHDS'
    put(384 + 0x18, 'HH', 1, 1)
    for field, value in ((0x20, 640), (0x2C, 704), (0x40, 800)):
        put(384 + field, 'I', value)
    put(384 + 0x34, 'H', 1)
    put(512 + 0x24, 'I', 576); put(588, 'II', 640, 704)
    put(640, 'II', 896, 64); put(704, 'II', 1000, 32)
    put(800, 'III', 1000, 1056, 16)
    put(896, 'H', 2); put(912, 'I', 32)
    d[928:960] = bytes(range(32))
    put(1056, 'IIII', 0x10000, 0, 0, 0)
    put(1156, 'hhH', 0, 0, 1); put(1208, 'hhH', 0, 1, 3)
    put(1280, '40I', *words())
    second = words(); second[4] = 1; second[6] = 0x00010001
    put(1440, '40I', *second)
    return d


baseline = m.decode_state(words())
assert baseline['blend'] == baseline['cull_enable'] == 0
assert baseline['cmask'] == 15 and baseline['depth_bits'] == 0x10000000
w = words(); before = list(w)
p = m.prepare_state(w)
assert p[32] == 0x203 and p[39] == 1 and w == before
assert m.prepare_state(p) == p
w[1] = 1
assert not (m.prepare_state(w)[39] & 1)
w = words(); w[34] = 0
assert m.decode_state(w)['depth_bits'] == 0xF0000000
w = words(); w[33] = 0
assert m.decode_state(w)['depth_bits'] == 0x90000000
w = words(); w[38] = 0xFFFF0010
assert m.decode_state(w)['trailing_metadata'] == [0xFFFF0010, 0]

for index, value in ((0, 0), (31, 0), (35, 0), (37, 0), (4, 2),
                     (9, 2), (32, 0x208), (36, 2)):
    w = words(); w[index] = value
    try:
        m.decode_state(w)
    except ValueError:
        pass
    else:
        raise AssertionError((index, value))
w = words(); w[4] = 1; w[5] = 0xFFFF
try:
    m.decode_state(w)
except ValueError:
    pass
else:
    raise AssertionError('unknown blend factor accepted')

data = fixture()
states, bindings, rejected = m.model_states(data, 0)
assert len(states) == 2 and len(bindings[0]) == 2 and not rejected
assert bindings[0][1] == dict(definition=1, state=1, flags=3)
data = fixture(); struct.pack_into('>h', data, 1158, -1)
assert m.model_states(data, 0)[2]['invalid material/state index'] == 1
data = fixture(); struct.pack_into('>I', data, 1280, 0)
states, bindings, rejected = m.model_states(data, 0)
assert len(states) == len(bindings[0]) == 1 and rejected
data = fixture(); struct.pack_into('>I', data, 272, 2000)
try:
    m.model_states(data, 0)
except ValueError:
    pass
else:
    raise AssertionError('out-of-model state table accepted')

with tempfile.TemporaryDirectory(prefix='material-state-cli-', dir=m.ROOT / 'scratch') as folder:
    root = Path(folder)
    asset = root / 'asset'; asset.write_bytes(fixture())
    materials = root / 'inventory.json'
    # Inventory only: the CLI must recover the actual pointers and bytecode.
    materials.write_text(json.dumps(dict(pairs=[dict(file=str(asset), model=0)])))
    trace = root / 'trace'; trace.mkdir()
    pair = m.model_pairs(fixture(), 0)[0][0]
    code = pair['vertex_code']; raw = f'{m.fnv64(code):016x}'
    (trace / f'vp_{raw}.bin').write_bytes(code)
    capture = dict(vp_raw=raw, vp_bytes=len(code), vp_identity_bytes=len(code),
                   pipeline='synthetic', state=dict(blend=0, cmask=15, stencil=0x10000000, cull=0))
    row = dict(status='recipe_link_verified', vertex_input_available=True,
               identity=pair['fragment_identity'], line=1, capture=capture)
    other = json.loads(json.dumps(row)); other['line'] = 2
    other['capture']['state']['stencil'] = 0x30000000
    report = root / 'capture.json'; report.write_text(json.dumps(dict(records=[row, other])))
    output = root / 'output'
    command = [sys.executable, str(m.ROOT / 'scripts/shader_material_state.py'),
               '--materials', str(materials), '--report', str(report), '--trace', str(trace),
               '--output', str(output)]
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    subprocess.run(command, check=True, capture_output=True)
    result = json.loads((output / 'report.json').read_text())
    assert result['counts']['links_with_candidates'] == 2
    assert result['counts']['joint_match'] == result['counts']['joint_mismatch'] == 1
    assert result['counts']['depth_bits_match'] == result['counts']['depth_bits_mismatch'] == 1
    assert subprocess.run(command, capture_output=True).returncode != 0
    command[-1] = str(trace / 'bad-output')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert not (trace / 'bad-output').exists()
    assert before == {str(p): p.read_bytes() for p in root.rglob('*')
                      if p.is_file() and output not in p.parents}
    # Bad input must fail before creating its output directory.
    (trace / f'vp_{raw}.bin').write_bytes(bytes(len(code)))
    command[-1] = str(root / 'damaged-input-output')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert not Path(command[-1]).exists()

print('Material state packet bounds, bindings, pass mismatches and CLI integrity/containment passed')
