"""Independent ordinary material profile; unknowns and unsupported contexts fail."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_material_profile import ordinary_profile, profile_matches
from shader_material_textures import with_global_sampler_path

material = dict(stencil_enable=0, cull_enable=1, blend=0, cmask=15, depth_bits=0x30000000)
binding = dict(unit=0, format=0x18520, address=0, width=64, height=32, control3=0,
               sampler=9)
definition = dict(used=1, bindings=[binding], globals=[])
p = ordinary_profile(definition, material, 0x02008400, 'ccw', 'rgba16-msaa2')
assert p == dict(exp32=0, cube=0x21000, ghi=0, unhi=0, unnorm=0, shd=0,
                 samplers='0000000000000009', blend=0, cmask=15, stencil=0x30000000,
                 cull=5, rtfmt=11, nrt=1)
assert profile_matches(p, dict(p, unrelated=99))
assert not profile_matches(p, dict(p, shd=1))
texel = dict(definition, bindings=[dict(binding, format=0x1c520)])
assert ordinary_profile(texel, material, 0x40, 'cw', 'rgba16-single')['unnorm'] == 0x101
assert ordinary_profile(texel, material, 0x40, 'cw', 'rgba16-single')['exp32'] == 1
active = with_global_sampler_path(dict(definition, used=0x8001, globals=[dict(name='ditherMap',kind=0x801,identifier=103,unit=15)]), 'active')
assert ordinary_profile(active, material, 0, 'ccw', 'rgba16-msaa2')['unhi'] == 0x8000
for bad in (dict(definition, used=3),
            dict(definition, globals=[dict(unit=0)]),
            dict(definition, bindings=[dict(binding, format=0x18524)]),
            dict(definition, bindings=[dict(binding, format=0x19020)]),
            dict(definition, bindings=[dict(binding, sampler_mask=12)])):
    try:
        ordinary_profile(bad, material, 0, 'ccw', 'rgba16-msaa2')
    except ValueError:
        pass
    else:
        raise AssertionError('Unknown or unsupported sampled facts accepted')
try:
    ordinary_profile(definition, dict(material, stencil_enable=1), 0, 'ccw', 'rgba16-msaa2')
except ValueError:
    pass
else:
    raise AssertionError('Stencil context accepted')
print('Whole independent ordinary profile, precision/coordinate variants and unknown-context rejection passed')
