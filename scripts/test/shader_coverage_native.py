"""Compare the audit's bounded walk with a locally built production decoder DLL."""
import argparse
import ctypes
import importlib.util
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--decoder', required=True, type=Path)
ap.add_argument('--programs', required=True, action='append', type=Path)
ap.add_argument('--limit', type=int, default=256, help='Maximum files per folder (0 means all)')
args = ap.parse_args()
if args.limit < 0:
    ap.error('limit must be nonnegative')
spec = importlib.util.spec_from_file_location('coverage', Path(__file__).parents[1] / 'shader_coverage.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
dll = ctypes.CDLL(str(args.decoder.resolve()))
for name in ('rsx_fp_program_size', 'rsx_fp_texture_mask'):
    f = getattr(dll, name)
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    f.restype = ctypes.c_uint32
dll.rsx_fp_collect_constants.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
dll.rsx_fp_collect_constants.restype = ctypes.c_int
constants = ctypes.create_string_buffer(1024 * 1024)
checked = rejected = 0
for folder in args.programs:
    paths = sorted([*folder.glob('*.fp'), *folder.glob('fp_*.bin')])
    if args.limit:
        paths = paths[:args.limit]
    if not paths:
        raise ValueError(f'No raw programs in {folder}')
    for path in paths:
        data = m.bounded_read(path, m.MAX_FP)
        buf = ctypes.create_string_buffer(data)
        count = dll.rsx_fp_collect_constants(buf, len(data), constants)
        try:
            info = m.fp_identity(data)
        except ValueError:
            assert count < 0, f'Audit rejected a native bounded program: {path}'
            rejected += 1
            continue
        assert count == info['constants'], f'Constant-slot disagreement: {path}'
        assert dll.rsx_fp_program_size(buf, len(data)) == info['size'], f'END disagreement: {path}'
        assert dll.rsx_fp_texture_mask(buf, len(data)) == info['textures'], f'Texture-mask disagreement: {path}'
        checked += 1
assert checked
print(f'Production decoder comparison passed: {checked} programs, {rejected} jointly rejected')
