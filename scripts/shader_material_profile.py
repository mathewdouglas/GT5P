"""Capture-free translation candidate for explicit ordinary 2D upload contexts.

This is a conditional material profile, not proof of actual draw/pass ownership.
Unknown sampled bindings fail closed, including globals with only shape known.
"""
from shader_material_textures import complete_sampler_key
from shader_texture_shapes import texture_fields, texture_shape
from shader_pass_state import object_pass_fields, native_target_fields


def ordinary_profile(definition, material, control, object_path, target_path):
    if material['stencil_enable']:
        raise ValueError('ordinary profile excludes stencil')
    sampler = complete_sampler_key(definition)
    fields = texture_fields(definition, sampling=True)
    if sampler is None or fields['unresolved_units']:
        raise ValueError('unresolved sampled texture or sampler facts')
    low = 0
    global_units = {g['unit'] for g in definition.get('globals', ())}
    for binding in definition['bindings']:
        unit = binding['unit']
        if not definition['used'] & (1 << unit) or unit in global_units:
            continue
        if 'format' in binding:
            shape = texture_shape(binding)
            texel = bool(binding['format'] & 0x4000)
        else:
            facts = binding.get('texture_facts') or {}
            shape, texel = facts.get('shape'), facts.get('unnormalized')
        if shape != '2d' or texel is None:
            raise ValueError('ordinary profile requires known 2D coordinate facts')
        if unit < 4 and texel:
            low |= 1 << unit
    wrapper = object_pass_fields(object_path, material)
    target = native_target_fields(target_path)
    return dict(exp32=int(bool(control & 0x40)),
                cube=fields['values']['cube'] | wrapper['cube_value'] | target['cube_value'],
                ghi=fields['values']['ghi'], unhi=fields['values']['unhi'],
                unnorm=(0x100 | low) if low else 0, shd=0,
                samplers=f'{sampler:016x}', blend=material['blend'], cmask=material['cmask'],
                stencil=material['depth_bits'], cull=wrapper['cull'], rtfmt=target['rtfmt'], nrt=1)


def profile_matches(profile, state):
    return all(state.get(name) == value for name, value in profile.items())


ASSUMPTIONS = [
    'successfully uploaded supported 2D textures; no target/depth-copy/mip alias redirects',
    'explicit global callback candidates; unknown sampled facts rejected',
    'prepared material, compact fragment binding and explicit object/target candidate',
    'no later binding/control/pass overrides; default renderer translation switches',
]
