"""Exact block comparison and depth-only differences must stay distinct."""
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
import shader_depth_commands as m
from shader_material_state_native import words


def row(w):
    return dict(schema=1, frame=10, io=124, ea=0x1000 + 124, call_return_io=1000,
                header=0x000C0A6C, depth_func=w[32], depth_mask=w[33],
                depth_test=w[34], material_words=w)


original = words()
block = dict(file='synthetic', model=0, index=0, offset=1280, words=original)
changed = list(original); changed[32] = 0x203
unrelated = list(changed); unrelated[38] ^= 16
non_material = row(original); non_material['material_words'] = []
invalid = row(original); invalid['depth_func'] = 0x203
result = m.compare([row(original), row(changed), row(unrelated), non_material, invalid], [block])
assert result['counts'] == dict(exact=1, depth_only_difference=1, unmatched=1, non_material_packet=1, invalid=1)
assert result['records'][1]['candidates'] == [0]
assert result['records'][2]['candidates'] == []
assert result['depth_changes'] == {'(513, 1, 1) -> (515, 1, 1)': 1}
assert result['prepared_counts'] == dict(unmatched=3)
assert m.compare([row(m.prepare_state(original))], [block])['prepared_counts'] == dict(exact=1)
duplicate = dict(block, file='second-container')
assert m.compare([row(changed)], [block, duplicate])['records'][0]['candidates'] == [0, 1]
for key, value in [('material_words', [0]), ('io', -1), ('ea', True), ('header', 0), ('schema', 2)]:
    damaged = row(original); damaged[key] = value
    assert m.compare([damaged], [block])['counts'] == dict(invalid=1)

with tempfile.TemporaryDirectory(prefix='depth-commands-cli-', dir=m.ROOT / 'scratch') as folder:
    root = Path(folder)
    data = bytearray(1024); data[:4] = b'MDL3'
    struct.pack_into('>I', data, 4, len(data))
    struct.pack_into('>H', data, 12, 1)
    struct.pack_into('>I', data, 0x44, 256)
    data[261] = 1
    struct.pack_into('>I', data, 272, 512)
    struct.pack_into('>40I', data, 512, *original)
    asset = root / 'asset'; asset.write_bytes(data)
    inventory = root / 'states.json'; inventory.write_text(json.dumps(dict(models=[dict(file=str(asset), model=0)])))
    commands = root / 'commands.jsonl'; commands.write_text(json.dumps(row(changed)) + '\n')
    output = root / 'output'
    command = [sys.executable, str(m.ROOT / 'scripts/shader_depth_commands.py'),
               '--states', str(inventory), '--commands', str(commands), '--output', str(output)]
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    subprocess.run(command, check=True, capture_output=True)
    assert json.loads((output / 'report.json').read_text())['counts'] == dict(depth_only_difference=1)
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file() and output not in p.parents}
    commands.write_text('{truncated')
    command[-1] = str(root / 'bad-output')
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert not Path(command[-1]).exists()

print('FIFO block exact/depth-only/unmatched joins, ambiguity, malformed traces and CLI integrity passed')
