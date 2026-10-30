"""Synthetic tests of bounded asset vertex discovery and original-slice checks."""
from pathlib import Path
import struct
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

print('SHDS vertex bounds, wrapper offsets, word order, exact matching and source mutation checks passed')
