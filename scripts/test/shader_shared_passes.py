"""Named-pair parsing rejects malformed banks and unsupported wrappers."""
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_shared_passes import bank_pairs, named_pair
from prepare_shared_shaders import enumerate_banks


def fixture(base=0):
    data = bytearray(base + 1024)
    data[base:base + 4] = b'SHDS'

    def put(offset, fmt, *values):
        struct.pack_into('>' + fmt, data, base + offset, *values)

    put(4, 'I', 1024)
    put(0x16, 'HHH', 2, 2, 2)
    for offset, value in ((0x1c, 80), (0x20, 128), (0x2c, 208), (0x40, 352)):
        put(offset, 'I', value)
    put(0x34, 'H', 2)
    put(80, 'IIHH', 416, 0, 1, 0)
    put(92, 'IIHH', 432, 0, 0, 1)
    data[base + 416:base + 422] = b'Alpha\0'
    data[base + 432:base + 437] = b'Beta\0'
    for i in range(2):
        put(128 + i * 40, 'II', 512 + i * 64, 64)
        put(512 + i * 64, 'H', 2)
        put(528 + i * 64, 'I', 32)
        put(208 + i * 72, 'I', 704 + i * 16)
        put(352 + i * 32, 'III', 704 + i * 16, 768 + i * 16, 16)
        put(768 + i * 16, 'IIII', 0x00010000, 0, 0, 0)
    return data


checks = 0
for base in (0, 37):
    pairs = bank_pairs(fixture(base), base)
    assert [(p['name'], p['vertex_index'], p['fragment_index']) for p in pairs] == [('Alpha', 1, 0), ('Beta', 0, 1)]
    assert named_pair(fixture(base), base, 'Alpha')['vertex']['offset'] == base + 608
    checks += 2
    for name, tag in (('Absent', 0), ('Alpha', 1)):
        try:
            named_pair(fixture(base), base, name, tag)
        except ValueError:
            checks += 1
        else:
            raise AssertionError('unlisted pair selected')

for offset, fmt, value in (
        (4, 'I', 1025), (4, 'I', 16), (0x16, 'H', 8193), (0x1c, 'I', 1008),
        (80, 'I', 1024), (88, 'H', 2), (90, 'H', 2), (92, 'I', 416),
        (352, 'I', 720), (356, 'I', 1024), (360, 'I', 0),
        (208, 'I', 700), (576, 'H', 0), (592, 'I', 31),
        (592, 'I', 0x2a00030), (768, 'I', 0)):
    data = fixture()
    struct.pack_into('>' + fmt, data, offset, value)
    try:
        bank_pairs(data, 0)
    except ValueError:
        checks += 1
    else:
        raise AssertionError(f'malformed bank accepted: {offset:x}')

for data in (b'SHDS', fixture()[:1000]):
    try:
        bank_pairs(data, 0)
    except ValueError:
        checks += 1
    else:
        raise AssertionError('truncated bank accepted')
print(f'{checks} named shared-pair checks passed')
combined = fixture() + b'junk' + fixture() + b'SHDS'
pairs, rejected = enumerate_banks(combined)
assert len(pairs) == 4 and len(rejected) == 1
assert {p['header'] for p in pairs} == {0, 1028}
assert all(p['vertex_input_mask'] == 0 for p in pairs)
print('Automatic multi-bank enumeration and unsupported-header isolation passed')
