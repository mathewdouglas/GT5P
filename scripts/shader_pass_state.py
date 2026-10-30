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
