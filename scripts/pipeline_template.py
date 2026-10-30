"""Versioned identifier/numeric-state templates; shader data stays local.

Export consumes local provenance and recipes, never copies their shader bytes.
Preparation resolves original SHDS assets before guest entry. This intentionally
does not scan guest memory or introduce another renderer worker/queue owner.
"""
import argparse
from collections import Counter
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct
import time

from shader_coverage import ROOT, bounded_read, fnv64, fp_identity, MAX_FP
from shader_reconstruct import NativeCompiler, vertex_programs, word_swap, offline_env, run_offline
from prepare_material_shaders import compile_fragments, save_code, source_key, request_envelope
from train_pipeline_cache import isolated, idle, inventory, validate_recipe, save_report

SCHEMA = 'gt5p-pipeline-template'
VERSION = 2
SETTINGS = {'RSX_ANISO': '16', 'RSX_PSO_KEY_RS': '1', 'FP_CONSTBUF': '1'}
MAX_RECORDS = 4096
MAX_FILE = 32 * 1024 * 1024
STATE = {'blend', 'nrt', 'rtfmt', 'exp32', 'cmask', 'cull', 'stencil',
         'unnorm', 'cube', 'vmask', 'samplers', 'ghi', 'shd', 'unhi'}
HEX = re.compile('[0-9a-f]{16}')
SHA = re.compile('[0-9a-f]{64}')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def renderer_contract():
    manifest = json.loads((ROOT / 'config/ps3recomp.json').read_text())
    patch = (ROOT / manifest['patch']).read_bytes().replace(b'\r\n', b'\n')
    patch = b'\n'.join(b'' if line == b' ' else line for line in patch.split(b'\n'))
    return sha(manifest['commit'].encode() + b'\n' + patch)


def compatibility(engine, decoder, elf):
    # Pin the distributable renderer source contract, not per-install executable
    # or DLL timestamps. Exact source/bytecode/native hashes still gate reuse.
    if not engine.is_file() or not decoder.is_file():
        raise ValueError('Engine/decoder missing')
    return dict(abi='windows-x64-recipe-v1', key_version=1, root_signature_keyed=True,
                renderer_sha256=renderer_contract(), renderer_settings=SETTINGS.copy(),
                elf_sha256=sha(elf.read_bytes()), translation_policy='default-constbuf-v1')



def native_state(data):
    """Only numeric descriptor fields and renderer-defined ATTR semantics."""
    words = list(struct.unpack_from('<164I', data, 48))
    # All pointers, unused shader stages/stream output and cached blobs must be
    # zero in this pinned, explicitly versioned serialization.
    for off in (0, 8, 24, 40, 48, 56, 64, 72, 80, 88, 104, 552, 632, 640):
        if struct.unpack_from('<Q', data, 48 + off)[0]:
            raise ValueError('Unsupported pointer/stage in numeric descriptor')
    if any(words[i] for i in (24, 25, 28, 29)) or words[140] > 32:
        raise ValueError('Unsupported stream output/input count')
    inputs = []
    for i in range(words[140]):
        offset = 704 + i * 64
        if data[offset:offset + 8] != bytes(8) or data[offset + 32:offset + 64] != b'ATTR' + bytes(28):
            raise ValueError('Unsupported vertex semantic')
        inputs.append(list(struct.unpack_from('<6I', data, offset + 8)))
    return dict(words=words, inputs=inputs)


def _validate(document):
    if set(document) != {'schema', 'version', 'compatibility', 'records'} or document['schema'] != SCHEMA or document['version'] != VERSION:
        raise ValueError('Incompatible template schema/version')
    c = document['compatibility']
    if (set(c) != {'abi', 'key_version', 'root_signature_keyed', 'renderer_sha256', 'renderer_settings', 'elf_sha256', 'translation_policy'} or
            c['abi'] != 'windows-x64-recipe-v1' or c['key_version'] != 1 or c['root_signature_keyed'] is not True or
            c['translation_policy'] != 'default-constbuf-v1' or c['renderer_settings'] != SETTINGS or
            any(not isinstance(c[k], str) or not SHA.fullmatch(c[k]) for k in ('renderer_sha256', 'elf_sha256'))):
        raise ValueError('Incompatible template key/translator ABI')
    if not isinstance(document['records'], list) or len(document['records']) > MAX_RECORDS:
        raise ValueError('Template record limit exceeded')
    seen = {}
    for r in document['records']:
        if set(r) != {'key', 'vp', 'fp', 'vs', 'ps', 'vp_source', 'fp_source', 'vp_gpu', 'state', 'native'}:
            raise ValueError('Unknown record fields')
        for k in ('key', 'vs', 'ps', 'vp_source', 'fp_source'):
            if not isinstance(r[k], str) or not HEX.fullmatch(r[k]) or int(r[k], 16) == 0:
                raise ValueError('Invalid pipeline/shader identifier')
        for stage in ('vp', 'fp'):
            p = r[stage]
            if set(p) != {'sha256', 'size'} or not SHA.fullmatch(p['sha256']) or type(p['size']) is not int or not 16 <= p['size'] <= MAX_FP or p['size'] % 16:
                raise ValueError('Invalid bounded program identifier')
        if type(r['vp_gpu']) is not int or r['vp_gpu'] not in (0, 1) or set(r['state']) != STATE:
            raise ValueError('Invalid translation state')
        for k, v in r['state'].items():
            if k == 'samplers':
                if not isinstance(v, str) or not HEX.fullmatch(v):
                    raise ValueError('Invalid sampler state')
            elif type(v) is not int or not 0 <= v <= 0xffffffff:
                raise ValueError('Invalid numeric translation state')
        n = r['native']
        if set(n) != {'words', 'inputs'} or len(n['words']) != 164 or len(n['inputs']) > 32 or any(len(i) != 6 for i in n['inputs']):
            raise ValueError('Invalid native state layout')
        if any(type(v) is not int or not 0 <= v <= 0xffffffff for v in n['words'] + [v for i in n['inputs'] for v in i]):
            raise ValueError('Invalid native state word')
        # Round-trip through the same pointer/stage/semantic rejection used on export.
        data = envelope(r, b'DXBC', b'DXBC', check_lengths=False)
        if native_state(data) != n:
            raise ValueError('Noncanonical native state')
        if r['key'] in seen and seen[r['key']] != r:
            raise ValueError('Conflicting duplicate pipeline key')
        seen[r['key']] = r
    document['records'] = list(seen.values())
    return document


def validate(document):
    try:
        return _validate(document)
    except (TypeError, KeyError, struct.error, OverflowError) as exc:
        raise ValueError('Malformed template record') from exc


def merge(documents):
    if not documents:
        raise ValueError('No templates supplied')
    first = validate(documents[0])
    records = {}
    for document in documents:
        document = validate(document)
        if document['compatibility'] != first['compatibility']:
            raise ValueError('Cannot merge incompatible generations')
        for record in document['records']:
            key = record['key']
            if key in records and records[key] != record:
                raise ValueError('Conflicting duplicate pipeline key')
            records[key] = record
            if len(records) > MAX_RECORDS:
                raise ValueError('Merged template record limit exceeded')
    return validate(dict(first, records=list(records.values())))


def read(path):
    if path.is_dir():
        index = json.loads(bounded_read(path / 'index.json', 65536))
        if (set(index) != {'schema','version','parts'} or index['schema'] != SCHEMA + '-bundle' or
                index['version'] != VERSION or not isinstance(index['parts'],list) or not 1 <= len(index['parts']) <= 32):
            raise ValueError('Incompatible template bundle')
        documents, seen, total = [], set(), 0
        for part in index['parts']:
            if set(part) != {'file','sha256'} or not re.fullmatch(r'part-\d{4}\.json',part['file']) or part['file'] in seen:
                raise ValueError('Invalid/duplicate bundle part')
            seen.add(part['file'])
            payload = bounded_read(path / part['file'], MAX_FILE)
            total += len(payload)
            if total > MAX_FILE or sha(payload) != part['sha256']:
                raise ValueError('Template bundle size/checksum mismatch')
            documents.append(validate(json.loads(payload)))
        return merge(documents)
    return validate(json.loads(bounded_read(path, MAX_FILE)))


def template_digest(path):
    if path.is_dir():
        # read() separately verifies every referenced part checksum.
        return sha(bounded_read(path / 'index.json',65536))
    return sha(bounded_read(path,MAX_FILE))


def bundle(document, output):
    document = validate(document)
    if output.exists():
        raise ValueError('Bundle output exists; nothing was overwritten')
    parts = []
    payloads = []
    records = document['records']
    for start in range(0,max(1,len(records)),128):
        name = f'part-{len(parts):04d}.json'
        data = (json.dumps(dict(document,records=records[start:start+128]),separators=(',',':'))+'\n').encode()
        if len(data) > 1_000_000:
            raise ValueError('Metadata shard exceeds repository text limit')
        parts.append(dict(file=name,sha256=sha(data)))
        payloads.append((name,data))
    output.mkdir(parents=True)
    for name,data in payloads:
        (output/name).write_bytes(data)
    save_report(output/'index.json',dict(schema=SCHEMA+'-bundle',version=VERSION,parts=parts))


def envelope(record, vs, ps, check_lengths=True):
    data = bytearray(request_envelope(vs, ps))
    struct.pack_into('<Q', data, 16, int(record['key'], 16))
    struct.pack_into('<164I', data, 48, *record['native']['words'])
    if check_lengths and (struct.unpack_from('<Q', data, 64)[0] != len(vs) or struct.unpack_from('<Q', data, 80)[0] != len(ps)):
        raise ValueError('Rebuilt shader length differs from template')
    for i, fields in enumerate(record['native']['inputs']):
        struct.pack_into('<6I', data, 704 + i * 64 + 8, *fields)
        data[736 + i * 64:740 + i * 64] = b'ATTR'
    struct.pack_into('<Q', data, 2752, fnv64(data[:-8]))
    return bytes(data)


def has_flow(code):
    for off in range(0, len(code), 16):
        _, a, _, b = struct.unpack_from('<4I', code, off)
        if (a >> 27) & 31 in (8, 9, 10, 11, 12, 17, 18):
            return True
        if b & 1:
            return False
    raise ValueError('Vertex program lacks bounded END')


def export(trace, cache, compat):
    records, rejected, codes = {}, Counter(), set()
    for path in sorted(trace.glob('links_*.jsonl')):
        with path.open() as stream:
            for line in stream:
                try:
                    if len(line) > 16384:
                        raise ValueError('oversized provenance record')
                    c = json.loads(line)
                    key = c['pipeline']
                    recipe = cache / 'warmup-v1' / f'pso_{key}.recipe'
                    validate_recipe(recipe, codes)
                    data = bounded_read(recipe, 2760)
                    if (struct.unpack_from('<QQ', data, 24) != (int(c['vs'], 16), int(c['ps'], 16)) or c['fp_flags'] != 0):
                        raise ValueError('Unsupported compiler flags or recipe join')
                    vp = bounded_read(trace / f"vp_{c['vp_raw']}.bin", MAX_FP)
                    fp = bounded_read(trace / f"fp_{c['fp_raw']}.bin", MAX_FP)
                    if f'{fnv64(vp):016x}' != c['vp_raw'] or f'{fnv64(fp):016x}' != c['fp_raw']:
                        raise ValueError('Program integrity failed')
                    vp = vp[:c['vp_identity_bytes']]
                    if has_flow(vp):
                        raise ValueError('Branching vertex context not yet exported')
                    f = fp_identity(fp)
                    r = dict(key=key, vp=dict(sha256=sha(vp), size=len(vp)),
                             fp=dict(sha256=f['identity'], size=f['size']), vs=c['vs'], ps=c['ps'],
                             vp_source=c['vp_cache'], fp_source=c['fp_cache'], vp_gpu=c['vp_gpu'],
                             state=c['state'], native=native_state(data))
                    if key in records and records[key] != r:
                        raise ValueError('Conflicting provenance for pipeline key')
                    records[key] = r
                    if len(records) > MAX_RECORDS:
                        raise ValueError('Template record limit exceeded')
                except (ValueError, OSError, KeyError) as exc:
                    rejected[str(exc).split(':')[0]] += 1
    if len(records) > MAX_RECORDS:
        raise ValueError('Template exceeds record cap')
    return validate(dict(schema=SCHEMA, version=VERSION, compatibility=compat, records=list(records.values()))), dict(rejected)


def locate(records, catalog, elf, asset_map=None, assets=None):
    """One bounded, read-only container pass, no address-space polling."""
    index = json.loads(bounded_read(catalog / 'index.json', 64 * 1024 * 1024))
    wanted_fp = {r['fp']['sha256'] for r in records}
    wanted_vp = {r['vp']['size'] for r in records}
    vertex_ids = {r['vp']['sha256'] for r in records}
    vertices, fragments = {}, {}
    for p in catalog.glob('*.fp'):
        raw = bounded_read(p, MAX_FP)
        if sha(raw) != p.stem:
            raise ValueError('Corrupt local SHDS catalogue payload')
        try:
            identity = fp_identity(raw)['identity']
        except ValueError:
            continue
        if identity in wanted_fp:
            fragments.setdefault(identity, raw)
    files = sorted({str(elf.resolve())} | {s['file'] for s in index['sources']})
    if len(files) > 8192:
        raise ValueError('Asset container count exceeds lookup budget')
    visited = size = wrappers = 0
    scan_started = time.perf_counter()
    for name in files:
        if time.perf_counter() - scan_started > 60:
            break
        p = Path(name)
        if not 0 < p.stat().st_size <= 1024 * 1024 * 1024:
            continue
        with p.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            visited += 1
            size += len(data)
            for source in vertex_programs(data):
                wrappers += 1
                raw = word_swap(data[source['offset']:source['offset'] + source['size']])
                for length in wanted_vp:
                    if length <= len(raw):
                        code = raw[:length]
                        identity = sha(code)
                        if identity in vertex_ids:
                            vertices.setdefault(identity, code)
        if len(vertices) == len(vertex_ids):
            break
    extra = {}
    if asset_map is not None:
        from pipeline_asset_map import read as read_map, resolve
        if assets is None:
            raise ValueError('An asset root is required with a program location map')
        wanted = {(stage,r[stage]['sha256'],r[stage]['size']) for r in records for stage,found in
                  (('vp',vertices),('fp',fragments)) if r[stage]['sha256'] not in found}
        mapped_vp,mapped_fp,extra = resolve(read_map(asset_map),assets,elf,wanted)
        vertices.update(mapped_vp)
        fragments.update(mapped_fp)
    return vertices, fragments, dict(containers=visited, addressable_bytes=size, vertex_wrappers=wrappers,
                                     vertex_found=len(vertices), fragment_found=len(fragments),asset_map=extra)


def cached_shaders(document,cache):
    """Reuse only expected source-key files with exact bytecode IDs and lengths."""
    expected={}
    for r in document['records']:
        for source,code,index in (('vp_source','vs',4),('fp_source','ps',8)):
            length=r['native']['words'][index] | (r['native']['words'][index+1]<<32)
            value=(r[code],length)
            if r[source] in expected and expected[r[source]]!=value:
                raise ValueError('Template source/bytecode mapping conflicts')
            expected[r[source]]=value
    found={};total=0
    for key,(code_id,length) in expected.items():
        path=cache/(key+'.dxbc')
        if not path.exists():continue
        data=bounded_read(path,4*1024**2)
        if not data.startswith(b'DXBC') or len(data)!=length or f'{fnv64(data):016x}'!=code_id:
            raise ValueError('Cached shader failed resume verification; cache preserved: '+key)
        total+=len(data)
        if total>128*1024**2:raise ValueError('Resume shader memory budget exceeded')
        found[key]=data
    return found


def prepare(template, catalog, elf, engine, decoder, game_root, output, demand_fallback=False, asset_map=None, assets=None, fragment_mode='batch', resume=False):
    idle()
    output = isolated(output)
    if output.exists() and not resume:
        raise ValueError('Use a fresh ignored output or --resume; existing caches are preserved')
    try:
        document = read(template)
        if document['compatibility'] != compatibility(engine, decoder, elf):
            raise ValueError('Template renderer/game/settings mismatch')
    except (ValueError,OSError,TypeError,KeyError) as exc:
        if not demand_fallback or resume:
            raise
        (output/'shadercache/warmup-v1').mkdir(parents=True)
        report = dict(schema=1,template_sha256=None,requested=0,records=[],counts={'template-rejected':1},
                      lookup={},preparation_seconds=0,reason=str(exc),
                      policy='Template rejected; empty cache retained for existing asynchronous demand path')
        save_report(output/'report.json',report)
        print('Template rejected; using demand fallback:',exc,flush=True)
        return report
    if asset_map is None and assets is not None and template.is_dir() and (template/'asset-map.json').is_file():
        asset_map = template/'asset-map.json'
    map_id=None
    if asset_map is not None:
        from pipeline_asset_map import read as read_map
        map_id=sha(json.dumps(read_map(asset_map),sort_keys=True,separators=(',',':')).encode())
    contract=dict(template=sha(json.dumps(document,sort_keys=True,separators=(',',':')).encode()),
                  engine=sha(engine.read_bytes()),decoder=sha(decoder.read_bytes()),
                  asset_map=map_id)
    from preparation_checkpoint import Checkpoint
    started=time.perf_counter()
    with Checkpoint(output,contract,resume) as checkpoint:
        checkpoint.stage('checking-cache')
        checked=time.perf_counter()
        reused=cached_shaders(document,output/'shadercache') if resume else {}
        return prepare_document(document,template,catalog,elf,engine,decoder,game_root,output,
                                asset_map,assets,fragment_mode,checkpoint,reused,started,time.perf_counter()-checked)


def prepare_document(document,template,catalog,elf,engine,decoder,game_root,output,
                     asset_map,assets,fragment_mode,checkpoint,reused,started,cache_seconds):
    cache=output/'shadercache';cache.mkdir(exist_ok=True)
    checkpoint.stage('lookup')
    lookup_started=time.perf_counter()
    vertices, fragments, lookup = locate(document['records'], catalog, elf,asset_map,assets)
    lookup['seconds'] = time.perf_counter() - lookup_started
    report = dict(schema=1, template_sha256=template_digest(template), lookup=lookup,
                  requested=len(document['records']), records=[], preparation_seconds=None,
                  engine_sha256=checkpoint.contract['engine'], decoder_sha256=checkpoint.contract['decoder'],
                  resume=dict(attempt=checkpoint.state['attempt'],verified_cached_sources=len(reused),
                              cache_verification_seconds=cache_seconds,
                              vertex_programs_reused=0,vertex_programs_compiled=0,fragment_jobs_reused=0),
                  policy='Offline before guest entry; default renderer translation; demand fallback for missing/rejected entries')
    save_report(output / 'report.json', report)
    compiler = None
    vs_cache, jobs, by_id = {}, [], {}
    vs_bytes=0
    checkpoint.stage('vertex',completed=0,total=len(document['records']))
    for number, r in enumerate(document['records'],1):
        if number % 128 == 0:
            print(f"Vertex/state validation {number}/{len(document['records'])}; unique vertex variants {len(vs_cache)}",flush=True)
            checkpoint.stage('vertex',completed=number-1,total=len(document['records']))
        try:
            v = vertices[r['vp']['sha256']]
            f = fragments[r['fp']['sha256']]
            identity = (r['vp']['sha256'], r['vp_gpu'])
            if identity not in vs_cache:
                if r['vp_source'] in reused:
                    code=reused[r['vp_source']]
                    source_id,code_id=r['vp_source'],r['vs']
                    report['resume']['vertex_programs_reused']+=1
                else:
                    if compiler is None:compiler=NativeCompiler(decoder)
                    source,code=compiler.vertex(v,bool(r['vp_gpu']))
                    source_id,code_id=f'{source_key(source):016x}',f'{fnv64(code):016x}'
                    report['resume']['vertex_programs_compiled']+=1
                vs_bytes+=len(code)
                if vs_bytes > 128 * 1024 * 1024:
                    raise ValueError('Vertex translation memory budget exceeded')
                vs_cache[identity]=(source_id,code_id,code)
            source_id,code_id,code = vs_cache[identity]
            if code_id != r['vs'] or source_id != r['vp_source']:
                raise ValueError('Rebuilt vertex identifier differs')
            save_code(cache / (r['vp_source'] + '.dxbc'), code)
            job_id = sha(r['key'].encode())
            job = dict(id=job_id, fragment=f, fragment_sha256=sha(f), state=r['state'], used=fp_identity(f)['textures'])
            jobs.append(job)
            by_id[job_id] = (r, code)
        except KeyError:
            report['records'].append(dict(key=r['key'], status='unresolved-program'))
        except ValueError as exc:
            report['records'].append(dict(key=r['key'], status='incompatible', reason=str(exc)))
    root = output / 'requests'
    root.mkdir(exist_ok=True)
    checkpoint.stage('fragment',requested=len(jobs))
    compiled={};pending=[]
    for job in jobs:
        r,_=by_id[job['id']]
        if r['fp_source'] in reused:
            compiled[job['id']]=(r['fp_source'],reused[r['fp_source']])
            report['resume']['fragment_jobs_reused']+=1
        else:pending.append(job)
    fresh,failures=compile_fragments(pending,root,cache,engine,game_root,mode=fragment_mode)
    compiled.update(fresh)
    report['fragment_preparation']=json.loads((root/'fragment-preparation-report.json').read_text())
    requests = []
    for job in jobs:
        r, vs = by_id[job['id']]
        try:
            if job['id'] in failures:
                raise ValueError(failures[job['id']])
            key, ps = compiled[job['id']]
            if key != r['fp_source'] or f'{fnv64(ps):016x}' != r['ps']:
                raise ValueError('Rebuilt fragment identifier differs')
            proof = root / job['id'] / 'pipeline'
            proof.mkdir(parents=True,exist_ok=True)
            (proof / 'request.recipe').write_bytes(envelope(r, vs, ps))
            for code in (vs, ps):
                (proof / f'code_{fnv64(code):016x}.dxbc').write_bytes(code)
            (proof/'result.json').write_text('{"pending":true}\n')
            requests.append(job['id'])
        except ValueError as exc:
            report['records'].append(dict(key=r['key'], status='incompatible', reason=str(exc)))
    (root / 'jobs.txt').write_text(''.join(i + '\n' for i in requests))
    if requests:
        checkpoint.stage('native',requested=len(requests))
        env = offline_env(game_root, cache)
        env.update(RSX_PSO_PREPARE_BATCH=str(root), RSX_PSO_TEMPLATE_PREPARE='1', RSX_PSO_RECIPE_KEEP_DAYS='0')
        run_offline(engine, game_root, env, output / 'native.log', timeout=900)
    for identity in requests:
        r = by_id[identity][0]
        result = json.loads((root / identity / 'pipeline/result.json').read_text())
        passed = result.get('created') and result.get('actual') == result.get('expected') == r['key']
        report['records'].append(dict(key=r['key'], status='prepared' if passed else 'key-rejected', result=result))
    checkpoint.stage('verifying-cache')
    report['inventory'] = inventory(cache, True)
    report['counts'] = dict(Counter(r['status'] for r in report['records']))
    prepared = {r['key'] for r in report['records'] if r['status'] == 'prepared'}
    if not prepared <= set(report['inventory']['valid_driver_blobs']) or report['inventory']['rejected']:
        raise ValueError('Prepared native cache validation failed')
    # Observed recipes do not establish menu/race ownership. Keep the prepared
    # disk cache without fabricating a menu preload index; the existing demand
    # owner consumes it, and real play can learn its own membership indices.
    (cache / 'warmup-v1').mkdir(exist_ok=True)
    report['preparation_seconds'] = time.perf_counter() - started
    save_report(output / 'report.json', report)
    checkpoint.stage('complete',counts=report['counts'])
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    e = sub.add_parser('export')
    e.add_argument('--trace', type=Path, required=True)
    e.add_argument('--cache', type=Path, required=True)
    for parser in (e,):
        for name in ('engine', 'decoder', 'elf', 'output'):
            parser.add_argument('--' + name, type=Path, required=True)
    m = sub.add_parser('merge')
    m.add_argument('--output', type=Path, required=True)
    m.add_argument('templates', type=Path, nargs='+')
    p = sub.add_parser('prepare')
    p.add_argument('--fragment-mode',choices=('batch','legacy'),default='batch',help='Exact-request batching by default; legacy rollback')
    p.add_argument('--resume',action='store_true',help='Resume a matching checkpoint and revalidate native pipelines')
    p.add_argument('--asset-map',type=Path,help='Optional verified hash/offset map for non-SHDS programs')
    p.add_argument('--assets',type=Path,help='Original unpacked asset root used with --asset-map')
    p.add_argument('--demand-fallback',action='store_true',help='Report incompatible templates and provide an empty demand cache')
    for name in ('template', 'catalog', 'elf', 'engine', 'decoder', 'game-root', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    b = sub.add_parser('bundle',help='Write verified identifier/numeric metadata shards; no shader contents')
    b.add_argument('--template',type=Path,required=True)
    b.add_argument('--output',type=Path,required=True)
    args = ap.parse_args()
    if args.command == 'bundle':
        bundle(read(args.template),args.output)
        return
    if args.command == 'prepare':
        result = prepare(*(getattr(args, k).resolve() for k in ('template', 'catalog', 'elf', 'engine', 'decoder', 'game_root', 'output')),
                         demand_fallback=args.demand_fallback,asset_map=args.asset_map,assets=args.assets,fragment_mode=args.fragment_mode,resume=args.resume)
        print(json.dumps(dict(counts=result['counts'], lookup=result['lookup'], seconds=result['preparation_seconds'])))
        return
    if args.output.exists():
        ap.error('Output exists; choose another filename')
    if args.command == 'export':
        result, rejected = export(args.trace, args.cache, compatibility(args.engine, args.decoder, args.elf))
        print('Export exclusions:', json.dumps(rejected))
    else:
        result = merge([read(path) for path in args.templates])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_report(args.output, result)
    print(len(result['records']), 'template records:', args.output)


if __name__ == '__main__':
    main()
