"""Shape masks, unsupported layouts and original-input audit integrity checks."""
from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_texture_shapes import texture_shape, texture_fields, shape_fields, shape_matches, replace_shape_fields
from shader_material_textures import model_textures
from shader_coverage import ROOT, fnv64


def binding(unit, fmt):
    return dict(unit=unit, format=fmt, control3=8 << 20, width=64, height=32)


for unit in range(16):
    cube_bit = 1 << (unit if unit < 4 else unit + 16)
    volume_bit = 1 << (unit + 16)
    for fmt, shape in ((0x18829, '2d'), (0x1882d, 'cube'), (0x18839, 'volume')):
        b = binding(unit, fmt)
        assert texture_shape(b) == shape
        d = dict(bindings=[b], globals=[], used=1 << unit)
        f = shape_fields(d)
        assert f['masks'] == dict(cube=cube_bit, ghi=volume_bit)
        assert f['values'] == dict(cube=cube_bit if shape == 'cube' else 0,
                                   ghi=volume_bit if shape == 'volume' else 0)
        captured = dict(cube=0xffffffff, ghi=0xffffffff)
        replaced = replace_shape_fields(f, captured)
        assert shape_matches(f, replaced)
        assert replaced['cube'] & ~cube_bit == captured['cube'] & ~cube_bit
        assert replaced['ghi'] & ~volume_bit == captured['ghi'] & ~volume_bit
        assert not shape_matches(f, dict(replaced, cube=replaced['cube'] ^ cube_bit))
        assert not shape_matches(f, dict(replaced, ghi=replaced['ghi'] ^ volume_bit))
        assert not f['unresolved_units']
    for fmt in (0, 0x18819, 0x1883d, 0x18029, 0x19029):
        f = shape_fields(dict(bindings=[binding(unit, fmt)], globals=[], used=1 << unit))
        assert f['known_units'] == 0 and f['unresolved_units'] == 1 << unit and f['rejected']
    d = dict(bindings=[binding(unit, 0x18829)], globals=[dict(unit=unit)], used=1 << unit)
    assert shape_fields(d)['known_units'] == 0  # Global overlap cannot inherit local dimensions.
assert shape_fields(dict(bindings=[dict(unit=0, global_path='active')], globals=[], used=1))['known_units'] == 0
assert shape_fields(dict(bindings=[binding(0, 0x18829)], globals=[], used=2))['known_units'] == 0


for unit in range(16):
    for gamma in (0, 1, 7):
        for unnormalized in (0, 1):
            b = dict(binding(unit, 0x18829 | (unnormalized << 14)), address=gamma << 20)
            f = texture_fields(dict(bindings=[b], globals=[], used=1 << unit), sampling=True)
            gfield = 'cube' if unit < 4 else 'ghi'
            gbit = 1 << (unit + 8 if unit < 4 else unit)
            assert bool(f['values'][gfield] & gbit) == bool(gamma)
            assert bool(f['values']['unhi'] & (1 << unit)) == bool(unit >= 4 and unnormalized)
            assert f['masks']['unhi'] == (1 << unit if unit >= 4 else 0)
            assert not f['masks']['cube'] & 0x000f1000  # Output gamma/sample count stay unknown.
            assert not f['masks']['ghi'] & 15  # Low units' gamma lives in cube, not ghi.

from shader_material_textures import with_global_sampler_path
for path, cube_value in (('framebuffer-2d', 0), ('framebuffer-cube', 1 << 30)):
    d = dict(bindings=[], globals=[dict(name='envMapSampler', kind=0x901, identifier=71, unit=14)], used=1 << 14)
    resolved = with_global_sampler_path(d, environment_path='framebuffer-mipped', environment_texture_path=path)
    f = texture_fields(resolved, sampling=True)
    assert f['values']['cube'] == cube_value and f['masks']['cube'] == 1 << 30
    assert not f['masks']['ghi'] & (1 << 14)  # Incoming environment read gamma is still unknown.
    assert f['unresolved_units'] == 1 << 14
    assert shape_fields(resolved)['unresolved_units'] == 0
try:
    with_global_sampler_path(d, environment_texture_path='framebuffer-cube')
    raise AssertionError('shape without framebuffer setup accepted')
except ValueError:
    pass

def fixture():
    data = bytearray(4096)
    def put(offset, fmt, *values):
        struct.pack_into('>' + fmt, data, offset, *values)
    data[:4] = b'MDL3'; put(4, 'I', len(data)); put(12, 'H', 1)
    put(0x44, 'I', 256); put(0x4c, 'I', 384)
    put(256, 'HHBBHIIII', 1, 1, 0, 0, 1, 1152, 512, 0, 1536)
    data[384:388] = b'SHDS'; put(408, 'HH', 1, 1)
    put(416, 'I', 640); put(428, 'I', 704); put(448, 'I', 800); put(436, 'H', 1)
    put(548, 'I', 576); put(588, 'II', 640, 704)
    put(640, 'II', 896, 64); put(704, 'II', 1000, 32); put(800, 'III', 1000, 1056, 16)
    put(896, 'H', 2); put(912, 'I', 32); data[928:960] = bytes(range(32))
    instruction = 0x17000001 | (2 << 17)
    put(1056, 'IIII', ((instruction << 16) | (instruction >> 16)) & 0xffffffff, 0, 0, 0)
    data[715] = 1; put(724, 'I', 1280); put(1280, 'I4hI', 1400, 0x601, 2, 0, 0, 0)
    data[1400:1418] = b'diffuseMapSampler\0'
    put(1156, 'hhHHI', 0, 0, 1, 1, 1440); put(1440, 'II', 1400, 0)
    words = [0] * 17
    words[0], words[2], words[3], words[6], words[7], words[10] = 0x201a00, 0x18839, 0x303, 0x02060000, 0x00400020, 8 << 20
    put(1536, '17I', *words)
    return data


with tempfile.TemporaryDirectory(prefix='texture-shapes-cli-', dir=ROOT / 'scratch') as folder:
    root = Path(folder)
    data = fixture(); definition = model_textures(data, 0)[0][0]
    asset = root / 'asset'; asset.write_bytes(data)
    inventory = root / 'states.json'; inventory.write_text(json.dumps(dict(models=[dict(file=str(asset), model=0)])))
    code = definition['vertex_code']; raw = f'{fnv64(code):016x}'
    trace = root / 'trace'; trace.mkdir(); (trace / f'vp_{raw}.bin').write_bytes(code)
    fields = shape_fields(definition)
    rows = []
    for index, state in enumerate((dict(cube=0, ghi=4 << 16), dict(cube=0, ghi=0))):
        rows.append(dict(status='recipe_link_verified', vertex_input_available=True, line=index + 1,
                         identity=definition['fragment_identity'],
                         capture=dict(vp_raw=raw, vp_bytes=len(code), vp_identity_bytes=len(code), state=state)))
    report = root / 'audit.json'; report.write_text(json.dumps(dict(records=rows)))
    command = [sys.executable, str(ROOT / 'scripts/shader_texture_shapes.py'), '--states', str(inventory),
               '--report', str(report), '--trace', str(trace), '--output', str(root / 'output')]
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    subprocess.run(command, check=True, capture_output=True)
    result = json.loads((root / 'output/report.json').read_text())
    assert result['counts'] == dict(known_shape_match=1, all_sampled_shapes_match=1,
                                     known_shape_mismatch=1, partial_or_mismatch=1)
    assert subprocess.run(command, capture_output=True).returncode != 0
    command[-1] = str(trace / 'nested')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file() and root / 'output' not in p.parents}
    (trace / f'vp_{raw}.bin').write_bytes(bytes(len(code)))
    command[-1] = str(root / 'damaged')
    assert subprocess.run(command, capture_output=True).returncode != 0 and not Path(command[-1]).exists()
print('Texture shape masks, unknown/global exclusion and CLI integrity checks passed')
