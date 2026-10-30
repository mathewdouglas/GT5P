"""Explicit conditional object-wrapper state; captures only validate candidates.

00306290 sets BACK, winding from its low-byte argument, and output gamma before
model draw. Prepared material state supplies cull enable. Using this candidate
assumes successful entry through that wrapper and no later face/gamma overrides.
"""

def object_pass_fields(path, material):
    if path not in ('ccw', 'cw'):
        raise ValueError('unknown object pass path')
    enable = material['cull_enable']
    if enable not in (0, 1):
        raise ValueError('invalid material cull enable')
    return dict(path=path, cull=(5 if path == 'ccw' else 1) if enable else 0,
                cube_value=1 << 12, cube_mask=1 << 12,
                assumptions=['00306290 model entry with explicit winding argument',
                             'prepared material cull enable applies; no later face/output-gamma override',
                             'default renderer culling and output-gamma switches'])


def pass_matches(fields, state):
    return (state['cull'] == fields['cull'] and
            state['cube'] & fields['cube_mask'] == fields['cube_value'])


def replace_pass_fields(fields, state):
    return dict(state, cull=fields['cull'],
                cube=(state['cube'] & ~fields['cube_mask']) | fields['cube_value'])


TARGET_PATHS = {'rgba16-single': (11, 1), 'rgba16-msaa2': (11, 2), 'rgba8-single': (28, 1)}


def native_target_fields(path):
    if path not in TARGET_PATHS:
        raise ValueError('unknown native target path')
    format, samples = TARGET_PATHS[path]
    return dict(path=path, rtfmt=format, nrt=1, sample_count=samples,
                cube_mask=15 << 16, cube_value=(samples if samples > 1 else 0) << 16,
                assumptions=['GPU-fetch vertex path with no native input layout',
                             'one explicit depth-backed colour target; no stencil or mask redirect',
                             'default renderer depth/cull/blend switches'])


def target_matches(fields, capture):
    state = capture['state']
    return (capture['vp_gpu'] == 1 and state['rtfmt'] == fields['rtfmt'] and state['nrt'] == 1 and
            not state['stencil'] & 0x0fffffff and
            state['cube'] & fields['cube_mask'] == fields['cube_value'])


def replace_target_fields(fields, state):
    return dict(state, rtfmt=fields['rtfmt'], nrt=fields['nrt'],
                cube=(state['cube'] & ~fields['cube_mask']) | fields['cube_value'])
