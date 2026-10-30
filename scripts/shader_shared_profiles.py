"""Independent conditional shared-pass facts for the measured disc build.

No capture input. The shared rules require a successfully initialized
ordinary RGBA8 2D FrameBuffer source, distinct target, supported target context,
real wrapper binding and no later overrides/unexpected resource redirects.
"""
from shader_pass_state import native_target_fields

DISC_SHA256 = '8ee3523e8c05d6a27d3cc32f6caeb530059473e8b9ae04ad92fdbfb677603036'


def colour_correct_descriptor(words, same, read_gamma):
    """Full 52-byte getter copy, wrapper edits and unit-zero command emission."""
    if len(words) != 13 or same not in (0, 1) or not 0 <= read_gamma <= 0xffffffff:
        raise ValueError('invalid colour-correction resource arguments')
    if any(not 0 <= word <= 0xffffffff for word in words):
        raise ValueError('invalid descriptor word')
    result = list(words)
    result[0] = (result[0] & 0xffff0000) | 0x1a00
    result[2] = (result[2] & ~0x00ff0000) | (1 << 16)
    result[3] = (result[3] & ~0x0ff00000) | ((7 if read_gamma & 255 else 0) << 20)
    result[6] = (result[6] & ~0x0fff0000) | ((1 if same else 2) << 24) | (1 << 16)
    result[9] = 0x41840
    return result


def convolution_descriptor(words, gamma):
    if len(words) != 13 or not 0 <= gamma <= 0xffffffff or any(not 0 <= w <= 0xffffffff for w in words):
        raise ValueError('invalid convolution resource arguments')
    result = list(words)
    result[0] = (result[0] & 0xffff0000) | 0x1a00
    result[2] = (result[2] & ~0x00ff0004) | 0x14000
    result[3] = (result[3] & ~0x0ff00000) | ((7 if (-gamma) & 0x80000000 else 0) << 20)
    result[6] = (result[6] & ~0x0fff0000) | 0x02020000
    result[9] = 0x41840
    return result


def _binding(pair, name, kind):
    if pair['name'] != name or pair['tag'] != 0 or pair['vertex_input_mask'] != 0x101:
        raise ValueError('unsupported shared-pass binding')
    if pair.get('sampled_units') != 1 or pair.get('global_count') != 0 or pair.get('samplers') != [dict(name='colorMap', kind=kind, unit=0, extra=[0, 0, 0])]:
        raise ValueError('unsupported shared sampler ownership')


def _screen_profile(pair, target_path, output_gamma, read_gamma, depth_backed):
    if output_gamma not in (0, 1) or read_gamma not in (0, 1):
        raise ValueError('gamma contexts must be explicit booleans')
    if depth_backed not in (0, 1):
        raise ValueError('depth attachment context must be explicit')
    target = native_target_fields(target_path)
    return dict(exp32=int(bool(pair['fragment_control'] & 0x40)),
                cube=(read_gamma << 8) | (output_gamma << 12) | target['cube_value'],
                ghi=0, unhi=0, unnorm=0, shd=0, samplers='0000000000000009',
                blend=0, cmask=15, stencil=0xf0000000 | (0 if depth_backed else 1 << 27),
                cull=0, rtfmt=target['rtfmt'], nrt=1)


def colour_correct_profile(pair, target_path, output_gamma, read_gamma, depth_backed=True):
    _binding(pair, 'ColorCorrect', 0x601)
    return _screen_profile(pair, target_path, output_gamma, read_gamma, depth_backed)


def convolution_profile(pair, target_path, gamma, depth_backed=True):
    _binding(pair, 'Convolution_8', 0x801)
    state = _screen_profile(pair, target_path, gamma, gamma, depth_backed)
    return dict(state, unnorm=0x101)


ASSUMPTIONS = [
    'Measured disc-build shared wrapper and named shader binding; no later overrides',
    'Successfully initialized RGBA8 2D FrameBuffer source; source and destination are distinct',
    'Ordinary normalized colour source; no depth/cube/volume or unexpected resource redirects',
    'Explicit source-read/output-gamma arguments and single-colour target/depth-attachment context',
    'Default renderer translation switches; per-draw constants are supplied by the live game',
]
