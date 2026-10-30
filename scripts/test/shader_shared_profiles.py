"""Conditional profile ownership/prerequisite checks; no captured state."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_shared_profiles import colour_correct_profile, colour_correct_descriptor
from shader_pass_state import TARGET_PATHS

pair = dict(name='ColorCorrect', tag=0, vertex_input_mask=0x101, fragment_control=0,
            sampled_units=1, global_count=0,
            samplers=[dict(name='colorMap', kind=0x601, unit=0, extra=[0, 0, 0])])
for path, (format, samples) in TARGET_PATHS.items():
    for read in (0, 1):
        for write in (0, 1):
            state = colour_correct_profile(pair, path, write, read)
            assert state['rtfmt'] == format and state['nrt'] == 1
            assert state['cube'] == read * 256 + write * 4096 + (samples * 65536 if samples > 1 else 0)
            assert state['samplers'] == '0000000000000009'
            assert state['stencil'] == 0xf0000000 and state['cull'] == state['blend'] == state['unnorm'] == 0
            assert state['cmask'] == 15 and state['exp32'] == 0
for key, value in (('name', 'SimpleBias'), ('tag', 1), ('vertex_input_mask', 1),
                   ('global_count', 1), ('sampled_units', 2), ('samplers', [])):
    try:
        colour_correct_profile(dict(pair, **{key: value}), 'rgba16-single', 0, 0)
    except ValueError:
        pass
    else:
        raise AssertionError('Unsupported ownership accepted: ' + key)
for gamma in (-1, 2, None):
    try:
        colour_correct_profile(pair, 'rgba16-single', gamma, 0)
    except ValueError:
        pass
    else:
        raise AssertionError('Unresolved gamma accepted')
for words, same, mode in (([], 0, 0), ([0] * 13, 2, 0), ([0] * 13, 0, -1)):
    try:
        colour_correct_descriptor(words, same, mode)
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid resource arguments accepted')
result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'prepare_shared_shaders.py'),
                         '--elf', 'absent', '--decoder', 'absent', '--output', 'absent', '--pipelines'], capture_output=True, text=True)
assert result.returncode != 0 and 'requires --engine and --game-root' in result.stderr
print('Shared context enumeration, unresolved ownership/gamma and pipeline prerequisites passed')
