"""Synthetic tests of bounded asset vertex discovery and original-slice checks."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
import shader_reconstruct as m


def bundle(base=0, header=0):
    data = bytearray(512)
    if base != header:
        data[base:base + 4] = b'MDL3'
    data[header:header + 4] = b'SHDS'
    struct.pack_into('>H', data, header + 0x18, 1)
    struct.pack_into('>I', data, header + 0x20, 128)
    struct.pack_into('>II', data, base + 128, 256, 80)
    struct.pack_into('>H', data, base + 256, 3)
    struct.pack_into('>I', data, base + 256 + 0x10, 32)
    data[base + 288:base + 336] = bytes(range(48))
    return data


plain = bundle()
result = list(m.vertex_programs(plain))
assert result == [dict(header=0, offset=288, size=48, wrapper=256, wrapper_size=80)]
assert list(m.vertex_programs(bundle(16, 64)))[0]['offset'] == 304
for offset, fmt, value in [(0x18, '>H', 8193), (0x20, '>I', 1024),
                            (256, '>H', 0), (256, '>H', 2049),
                            (272, '>I', 31), (272, '>I', 1024)]:
    data = bundle()
    struct.pack_into(fmt, data, offset, value)
    assert list(m.vertex_programs(data)) == []
assert list(m.vertex_programs(b'SHDS')) == []
assert m.word_swap(m.word_swap(bytes(range(48)))) == bytes(range(48))
try:
    m.word_swap(b'123')
except ValueError:
    pass
else:
    raise AssertionError('unaligned words accepted')

with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'synthetic-asset'
    path.write_bytes(plain)
    code = m.word_swap(plain[288:336])
    matches, count = m.discover_vertices([path], {48: {code: {'synthetic-id'}}})
    assert count == 1 and matches['synthetic-id']['order'] == 'swap32'
    assert matches['synthetic-id']['size'] == 48
    candidate = matches['synthetic-id']
    assert m.read_slice(candidate) == plain[288:336]
    path.write_bytes(bytes(len(plain)))
    try:
        m.read_slice(candidate)
    except ValueError:
        pass
    else:
        raise AssertionError('changed original asset accepted')
    # An empty file must not be mapped; an absent matching prefix isn't a hit.
    path.write_bytes(b'')
    assert m.discover_vertices([path], {48: {code: {'synthetic-id'}}}) == ({}, 0)

values = dict(blend=0, cmask=15, depth_bits=0x30000000, cull_enable=1, stencil_enable=0)
capture = dict(state=dict(blend=0, cmask=15, stencil=0x30000000, cull=5))
assert m.material_state_matches(values, capture)
for field, value in [('blend', 1), ('cmask', 14), ('depth_bits', 0x10000000),
                     ('cull_enable', 0), ('stencil_enable', 1)]:
    changed = dict(values); changed[field] = value
    assert not m.material_state_matches(changed, capture)
for stencil in (0x30000001, 0x34000000):
    changed = dict(state=dict(capture['state'], stencil=stencil))
    assert not m.material_state_matches(values, changed)

# Pass paths cannot silently enter a proof without explicit material samplers.
command = [sys.executable, str(Path(m.__file__))]
for flag in ('report', 'trace', 'catalog', 'cache', 'decoder', 'engine', 'game-root', 'output'):
    command += ['--' + flag, 'unused-test-input']
for flag, path in (('--environment-sampler-path', 'framebuffer-single'),
                   ('--environment-sampler-path', 'framebuffer-mipped'),
                   ('--mirror-sampler-path', 'scene-copy')):
    result = subprocess.run(command + [flag, path], capture_output=True, text=True)
    assert result.returncode != 0 and 'require a material sampler proof' in result.stderr

for flag in ('--material-texture-shapes', '--material-texture-state'):
    result = subprocess.run(command + [flag], capture_output=True, text=True)
    assert result.returncode != 0 and 'requires a material sampler proof' in result.stderr

result = subprocess.run(command + ['--environment-texture-path', 'framebuffer-cube'], capture_output=True, text=True)
assert result.returncode != 0 and 'requires framebuffer sampler and texture reconstruction options' in result.stderr

print('SHDS bounds, source integrity and prepared material-state eligibility checks passed')

from shader_pass_state import object_pass_fields, pass_matches, replace_pass_fields
for path, enabled_key in (('ccw', 5), ('cw', 1)):
    for enable in (0, 1):
        fields = object_pass_fields(path, dict(cull_enable=enable))
        state = dict(cull=enabled_key if enable else 0, cube=0x80011000, ghi=7)
        assert pass_matches(fields, state)
        assert replace_pass_fields(fields, dict(state, cull=7, cube=0x80010000)) == state
        assert not pass_matches(fields, dict(state, cube=state['cube'] ^ 4096))
        assert not pass_matches(fields, dict(state, cull=7))
result = subprocess.run(command + ['--object-pass-path', 'ccw'], capture_output=True, text=True)
assert result.returncode != 0 and 'requires --prepared-material-state' in result.stderr
print('Conditional object-pass selection, independent replacement and prerequisites passed')
