"""Synthetic direct material linkage, bounds and false-pair rejection checks."""
from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
import shader_materials as m


def fixture(base=0):
    data = bytearray(base + 2048)
    data[base:base + 4] = b'MDL3'

    def put(offset, fmt, *values):
        struct.pack_into('>' + fmt, data, base + offset, *values)

    put(4, 'I', 2048)
    put(12, 'H', 1)
    put(0x44, 'I', 256)
    put(0x4C, 'I', 384)
    put(258, 'H', 1)
    put(268, 'I', 512)
    data[base + 384:base + 388] = b'SHDS'
    put(384 + 0x18, 'HH', 1, 1)
    put(384 + 0x20, 'I', 640)
    put(384 + 0x2C, 'I', 704)
    put(384 + 0x34, 'H', 1)
    put(384 + 0x40, 'I', 800)
    put(512 + 0x24, 'I', 576)
    put(576 + 12, 'II', 640, 704)
    put(640, 'II', 896, 64)
    put(704, 'II', 1000, 32)
    put(800, 'III', 1000, 1056, 16)
    put(896, 'H', 2)
    put(912, 'I', 32)
    data[base + 928:base + 960] = bytes(range(32))
    # END instruction in halfword-swapped representation.
    put(1056, 'IIII', 0x00010000, 0, 0, 0)
    return data


for base in (0, 32):
    data = fixture(base)
    pairs, rejected = m.model_pairs(data, base)
    assert len(pairs) == 1 and not rejected
    assert pairs[0]['vertex_offset'] == base + 928
    assert pairs[0]['fragment_offset'] == base + 1056
    assert pairs[0]['vertex_code'] == m.word_swap(bytes(range(32)))
    assert list(m.scan(data))[0][3] is None

# A pointer to an adjacent/undeclared record must never generate a pair.
for offset, fmt, value, reason in [
        (588, 'I', 641, 'shader pointer outside declared table'),
        (592, 'I', 705, 'shader pointer outside declared table'),
        (800, 'I', 1004, 'ambiguous or absent fragment descriptor'),
        (804, 'I', 2048, 'out-of-model reference'),
        (912, 'I', 48, 'invalid vertex wrapper'),
        (896, 'H', 0, 'invalid vertex wrapper'),
        (1056, 'I', 0, 'no bounded END instruction')]:
    data = fixture()
    struct.pack_into('>' + fmt, data, offset, value)
    pairs, rejected = m.model_pairs(data, 0)
    assert not pairs and rejected[reason] == 1, rejected

data = fixture()
struct.pack_into('>H', data, 384 + 0x34, 2)
data[832:864] = data[800:832]
assert m.model_pairs(data, 0)[1]['ambiguous or absent fragment descriptor'] == 1

for data in (b'MDL3', fixture()[:1000]):
    assert list(m.scan(data))[0][3] is not None
for offset, fmt, value in [(4, 'I', 0), (12, 'H', 9),
                            (384 + 0x18, 'H', 8193), (384 + 0x20, 'I', 2048)]:
    data = fixture()
    struct.pack_into('>' + fmt, data, offset, value)
    assert list(m.scan(data))[0][3] is not None

assert list(m.scan(b'no model')) == []

with tempfile.TemporaryDirectory(prefix='material-cli-', dir=m.ROOT / 'scratch') as folder:
    root = Path(folder)
    catalog = root / 'catalog'; catalog.mkdir()
    trace = root / 'trace'; trace.mkdir()
    asset = root / 'asset'; asset.write_bytes(fixture())
    (catalog / 'index.json').write_text(json.dumps(dict(sources=[dict(file=str(asset))])))
    pair = m.model_pairs(fixture(), 0)[0][0]
    code = pair['vertex_code']
    raw = f'{m.fnv64(code):016x}'
    (trace / f'vp_{raw}.bin').write_bytes(code)
    report = root / 'capture.json'
    report.write_text(json.dumps(dict(records=[dict(status='recipe_link_verified',
        identity=pair['fragment_identity'], capture=dict(vp_raw=raw, vp_bytes=len(code),
                                                         vp_identity_bytes=len(code)))])))
    output = root / 'output'
    command = [sys.executable, str(m.ROOT / 'scripts/shader_materials.py'),
               '--catalog', str(catalog), '--report', str(report), '--trace', str(trace),
               '--output', str(output)]
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    subprocess.run(command, check=True, capture_output=True)
    result = json.loads((output / 'report.json').read_text())
    assert result['matched_captured_unique_pairs'] == result['material_pairs'] == 1
    assert result['state_origin'] == 'not_derived'
    assert subprocess.run(command, capture_output=True).returncode != 0
    command[-1] = str(catalog / 'bad-output')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert not (catalog / 'bad-output').exists()
    assert before == {str(p): p.read_bytes() for p in root.rglob('*')
                      if p.is_file() and output not in p.parents}

print('Material pointer linkage, model/table/payload bounds and ambiguous-pair rejection passed')
