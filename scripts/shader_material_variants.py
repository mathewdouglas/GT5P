"""Expand independently constructed ordinary-upload jobs into explicit contexts."""
import hashlib
import json

from shader_pass_state import TARGET_PATHS, native_target_fields


def contexts(name):
    targets = tuple(TARGET_PATHS) if name == 'supported' else ('rgba16-single', 'rgba16-msaa2')
    if name not in ('supported', 'rgba16'):
        raise ValueError('Unknown material context set')
    return [dict(object_path=o, target_path=t, global_path=g)
            for g in ('active', 'fallback') for o in ('ccw', 'cw') for t in targets]


def context_name(context):
    return '/'.join(context[k] for k in ('object_path', 'target_path', 'global_path'))


def expand_job(job, context):
    # The seed was independently constructed for CCW/RGBA16-MSAA2. Its cull
    # enable comes from prepared material state; texture facts stay unchanged.
    if context not in contexts('supported'):
        raise ValueError('Unsupported explicit context')
    if (job['state']['cull'] not in (0, 5) or job['state']['rtfmt'] != 11 or
            job['state']['cube'] & (15 << 16) != 2 << 16):
        raise ValueError('Variant seed must be independent CCW/RGBA16-MSAA2 state')
    target = native_target_fields(context['target_path'])
    state = dict(job['state'],
                 cull=(5 if context['object_path'] == 'ccw' else 1) if job['state']['cull'] else 0,
                 rtfmt=target['rtfmt'],
                 cube=(job['state']['cube'] & ~target['cube_mask']) | target['cube_value'])
    metadata = dict(vertex_sha256=job['vertex_sha256'], fragment_sha256=job['fragment_sha256'], state=state)
    key = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    return dict(job, **metadata, id=key, context=context, contexts=[context])


def enumerate_variants(catalog, name, limit=0):
    # Imported lazily to keep single-context preparation and its tests usable.
    from prepare_material_shaders import enumerate_jobs
    choices, seen, inventory = contexts(name), {}, {}
    for global_path in ('active', 'fallback'):
        seeds, counts = enumerate_jobs(catalog, 'ccw', 'rgba16-msaa2', global_path, 0)
        inventory[global_path] = counts
        for seed in seeds:
            for context in choices:
                if context['global_path'] != global_path:
                    continue
                job = expand_job(seed, context)
                if job['id'] in seen:
                    known = seen[job['id']]['contexts']
                    if context not in known:
                        known.append(context)
                else:
                    seen[job['id']] = job
    jobs = list(seen.values())
    return jobs[:limit] if limit else jobs, dict(context_set=name, contexts=choices,
                                               unique_candidates=len(jobs), seeds=inventory)
