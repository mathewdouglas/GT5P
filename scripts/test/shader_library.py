"""Synthetic tests of the production SHDS extractor; no game files required."""
import importlib.util
from pathlib import Path
import struct
import tempfile

spec = importlib.util.spec_from_file_location('precompile', Path(__file__).parents[1] / 'precompile_shaders.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def bundle(base=0, header=0, count=1, size=16, offset=256):
    data = bytearray(512)
    if base != header: data[base:base+4] = b'MDL3'
    data[header:header+4] = b'SHDS'
    struct.pack_into('>H', data, header + 0x34, count)
    struct.pack_into('>I', data, header + 0x40, 128)
    struct.pack_into('>III', data, base + 128, 0, offset, size)
    return data


assert list(module.fragment_programs(bundle())) == [(0, 256, bytes(16))]
assert list(module.fragment_programs(bundle(base=16, header=64))) == [(64, 272, bytes(16))]
for data in (b'SHDS', bundle(count=8193), bundle(size=32784), bundle(size=15),
             bundle(offset=1024), bundle(size=0), bundle(count=2)):
    assert list(module.fragment_programs(data)) == []
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    for name in ('a', 'b'): (root / name).write_bytes(bundle())
    assert module.extract([root / 'a', root / 'b'], root / 'out') == (1, 2)
    assert len(list((root / 'out').glob('*.fp'))) == 1
print('SHDS bounds, enclosing model, deduplication and output checks passed')
