"""Capture-free request format and bytecode key/collision checks."""
from pathlib import Path
import struct
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_material_shaders as m
vs, ps = b'DXBC synthetic vertex', b'DXBC synthetic pixel'
r = m.request_envelope(vs, ps)
assert len(r) == 2760 and struct.unpack_from('<QII', r) == (0x31574d5241503547, 1, 2760)
assert struct.unpack_from('<QQQII', r, 16) == (0, m.fnv64(vs), m.fnv64(ps), len(vs), len(ps))
assert struct.unpack_from('<Q', r, 64)[0] == len(vs)
assert struct.unpack_from('<Q', r, 80)[0] == len(ps)
state = bytearray(r[48:704]);state[16:24] = bytes(8);state[32:40] = bytes(8)
assert not any(state), 'Native state was supplied rather than reconstructed'
assert struct.unpack_from('<Q', r, 2752)[0] == m.fnv64(r[:-8])
assert m.source_key(b'synthetic') == (m.fnv64(b'syntheticvs_5_0') * 1099511628211) & 0xffffffffffffffff
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'test.dxbc'
    m.save_code(path, vs);m.save_code(path, vs)
    try:
        m.save_code(path, ps)
    except ValueError:
        pass
    else:
        raise AssertionError('Existing differing bytecode overwritten')
print('Capture-free envelope, zero native state, production source key and collision preservation passed')
