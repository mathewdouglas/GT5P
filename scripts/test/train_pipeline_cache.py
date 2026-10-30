"""Learned-recipe/dependency and completed-route validation checks."""
import json
from pathlib import Path
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
import train_pipeline_cache as m


def envelope(key, vs, ps):
    data = bytearray(2760)
    struct.pack_into('<QIIQQQII', data, 0, 0x31574d5241503547, 1, 2760, key,
                     m.fnv64(vs), m.fnv64(ps), len(vs), len(ps))
    struct.pack_into('<Q', data, 2752, m.fnv64(data[:-8]))
    return data


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    cache = root / 'shadercache'
    warm = cache / 'warmup-v1'
    warm.mkdir(parents=True)
    vs, ps = b'DXBC-test-vertex', b'DXBC-test-fragment'
    for payload in (vs, ps):
        (warm / f'code_{m.fnv64(payload):016x}.dxbc').write_bytes(payload)
    recipe = warm / 'pso_0000000000000001.recipe'
    data = envelope(1, vs, ps)
    recipe.write_bytes(data)
    assert m.validate_recipe(recipe) == '0000000000000001'
    assert m.inventory(cache)['recipes'] == ['0000000000000001']
    assert not m.inventory(cache, True)['valid_driver_blobs']
    blob = b'local-test-driver-blob'
    native = cache / 'pso_0000000000000001.bin'
    native.write_bytes(struct.pack('<QQQ', 0x31534f5035505447, len(blob), m.fnv64(blob)) + blob)
    assert m.inventory(cache, True)['valid_driver_blobs'] == ['0000000000000001']
    native.write_bytes(native.read_bytes()[:-1])
    assert not m.inventory(cache, True)['valid_driver_blobs']
    for offset in (0, 8, 12, 16, 40, 2752):
        damaged = bytearray(data)
        damaged[offset] ^= 1
        recipe.write_bytes(damaged)
        assert len(m.inventory(cache)['rejected']) == 1
        assert not m.inventory(cache)['recipes']
    recipe.write_bytes(data)
    code = warm / f'code_{m.fnv64(vs):016x}.dxbc'
    code.write_bytes(b'DXBC-bad-hash')
    assert len(m.inventory(cache)['rejected']) == 1
    code.write_bytes(vs)
    assert not m.inventory(cache)['rejected']
    logs = root / 'logs'
    logs.mkdir()
    window = dict(sample_start_ms=1000, sample_end_ms=2000)
    (logs / 'route.window.json').write_text(json.dumps(window))
    (logs / 'route.out').write_text('[milestone] QuickArcadeRoot at 900 ms\n')
    (logs / 'route.frames.csv').write_text('\n'.join(f'{t},1,1' for t in range(1000, 2001, 20)))
    assert m.route_result(logs, 'route')['presented_samples'] == 51
    (logs / 'route.frames.csv').write_text('1000,1,1\n900,1,1\n')
    try:
        m.route_result(logs, 'route')
    except ValueError:
        pass
    else:
        raise AssertionError('Insufficient presented frames accepted')
    assert recipe.exists() and native.exists(), 'Validation must never delete damaged cache files'
    m.writable_tree(cache, root)
    try:
        m.writable_tree(cache, logs)
    except ValueError:
        pass
    else:
        raise AssertionError('Escaping writable path accepted')
    report = root / 'report.json'
    m.save_report(report, dict(status='visiting'))
    m.save_report(report, dict(status='complete'))
    assert json.loads(report.read_text()) == dict(status='complete')
print('Recipe checksums/dependencies, driver envelopes, route validation and preservation checks passed')
