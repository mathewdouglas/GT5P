"""Check variant expansion against independent construction for every context."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_material_profile import ordinary_profile
from shader_material_textures import with_global_sampler_path
from shader_material_variants import contexts, expand_job
from prepare_material_shaders import write_job
import tempfile

binding = dict(unit=0, format=0x18520, address=0, width=64, height=32, control3=0, sampler=9)
definition = dict(used=0x8001, bindings=[binding],
                  globals=[dict(name='ditherMap',kind=0x801,identifier=103,unit=15)])
assert len(contexts('supported')) == 12 and len(contexts('rgba16')) == 8
for enabled in (0, 1):
    material = dict(stencil_enable=0, cull_enable=enabled, blend=0, cmask=15, depth_bits=0x30000000)
    for context in contexts('supported'):
        selected = with_global_sampler_path(definition, context['global_path'])
        seed = dict(vertex_sha256='v', fragment_sha256='f',
                    state=ordinary_profile(selected, material, 0, 'ccw', 'rgba16-msaa2'))
        job = expand_job(seed, context)
        assert job['state'] == ordinary_profile(selected, material, 0,
                                                context['object_path'], context['target_path'])
        assert seed['state']['rtfmt'] == 11 and seed['state']['cube'] & (15 << 16) == 2 << 16
        if not enabled:
            other = dict(context, object_path='cw' if context['object_path']=='ccw' else 'ccw')
            assert job['id'] == expand_job(seed, other)['id']

# Multi-context jobs must use their own target, even when no single CLI target exists.
class Compiler:
    def vertex(self, code, gpu):
        return b'hlsl', b'DXBC vertex'
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder);cache = root / 'cache';cache.mkdir()
    job = expand_job(seed, contexts('supported')[6])
    job.update(vertex=b'vertex')
    write_job(job, root, cache, Compiler(), {}, ('ps',b'DXBC pixel'), None)
    assert (root/job['id']/'pipeline/target.state').read_text().strip() == 'GT5P_TARGET_V1 11 1'
try:
    expand_job(dict(seed,state=dict(seed['state'],cull=1)), contexts('supported')[0])
except ValueError:
    pass
else:
    raise AssertionError('Wrong seed context accepted')
print('All 24 independently constructed variants, cull-disabled deduplication and per-job native targets passed')
