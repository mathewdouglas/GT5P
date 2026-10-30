"""Hash-only locations for programs outside supported SHDS tables.

Developer generation uses captured programs only as search/validation oracles.
Preparation reads verified slices from the user's original assets. Maps contain
no filenames, guest addresses, shader bytes, source or compiled binaries.
"""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import time

from shader_coverage import MAX_FP, bounded_read, fp_identity, fnv64
from shader_reconstruct import word_swap

SCHEMA = 'gt5p-program-locations'
MAX_FILES = 8192
MAX_CONTAINER = 1024**3
MAX_RECORDS = 8192


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(stage, data):
    return digest(data) if stage == 'vp' else fp_identity(data)['identity']


def validate(document):
    try:
        if (set(document) != {'schema','version','records'} or document['schema'] != SCHEMA or
                type(document['version']) is not int or document['version'] != 1 or
                not isinstance(document['records'],list) or len(document['records']) > MAX_RECORDS):
            raise ValueError('Incompatible program location map')
        seen = set()
        for r in document['records']:
            if (set(r) != {'stage','id','size','container','container_size','offset','encoding'} or
                    r['stage'] not in ('vp','fp') or r['encoding'] not in ('native','swap32') or
                    (r['stage'] == 'fp' and r['encoding'] != 'native')):
                raise ValueError('Unsupported program location')
            for field in ('id','container'):
                if not isinstance(r[field],str) or len(r[field]) != 64 or any(c not in '0123456789abcdef' for c in r[field]):
                    raise ValueError('Invalid location identifier')
            if (any(type(r[k]) is not int for k in ('size','offset','container_size')) or
                    not 16 <= r['size'] <= MAX_FP or r['size'] % 16 or
                    not 0 < r['container_size'] <= MAX_CONTAINER or
                    not 0 <= r['offset'] <= r['container_size'] - r['size']):
                raise ValueError('Invalid bounded asset location')
            key = (r['stage'],r['id'])
            if key in seen:
                raise ValueError('Duplicate program location')
            seen.add(key)
        return document
    except (TypeError,KeyError) as exc:
        raise ValueError('Malformed program location map') from exc


def read(path):
    return validate(json.loads(bounded_read(path,4*1024**2)))


def files(assets, elf):
    if not assets.is_dir() or assets.is_symlink() or assets.is_junction():
        raise ValueError('Use an original asset directory without redirection')
    result = {elf.resolve()}
    for p in assets.rglob('*'):
        if p.is_symlink() or p.is_junction():
            raise ValueError('Asset roots must not contain redirected paths')
        if p.is_file():
            result.add(p.resolve())
            if len(result) > MAX_FILES:
                raise ValueError('Asset file-count budget exceeded')
    return sorted(result)


def resolve(document, assets, elf, wanted, seconds=60):
    """Hash only candidate-sized containers; verify every selected program."""
    validate(document)
    records = [r for r in document['records'] if (r['stage'],r['id'],r['size']) in wanted]
    if sum(r['size'] for r in records) > 128*1024**2:
        raise ValueError('Resolved program memory budget exceeded')
    sizes = {r['container_size'] for r in records}
    containers = {}
    for r in records:
        containers.setdefault(r['container'],[]).append(r)
    found = {'vp':{},'fp':{}}
    stats = dict(containers_hashed=0,bytes_hashed=0,containers_matched=0,programs_found=0)
    started = time.perf_counter()
    for p in files(assets,elf) if records else []:
        if time.perf_counter()-started > seconds:
            break
        size = p.stat().st_size
        if size not in sizes:
            continue
        if stats['bytes_hashed'] + size > 16*1024**3:
            break
        with p.open('rb') as stream, mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            key = digest(data)
            stats['containers_hashed'] += 1
            stats['bytes_hashed'] += size
            if key not in containers:
                continue
            stats['containers_matched'] += 1
            for r in containers.pop(key):
                raw = data[r['offset']:r['offset']+r['size']]
                code = word_swap(raw) if r['encoding'] == 'swap32' else raw
                if len(code) != r['size'] or identity(r['stage'],code) != r['id']:
                    raise ValueError('Asset location failed program verification')
                found[r['stage']][r['id']] = code
                stats['programs_found'] += 1
        if not containers:
            break
    stats['seconds'] = time.perf_counter()-started
    return found['vp'],found['fp'],stats


def build(records, trace, assets, elf, known=()):
    """Search original files, emitting only independently verified locations."""
    wanted = {(s,r[s]['sha256'],r[s]['size']) for r in records for s in ('vp','fp')} - set(known)
    targets = {}
    for stage in ('vp','fp'):
        for p in sorted(trace.glob(stage+'_*.bin')):
            raw = bounded_read(p,MAX_FP)
            if p.stem != f'{stage}_{fnv64(raw):016x}':
                raise ValueError('Captured program integrity failed')
            lengths = {size for s,_,size in wanted if s == stage and size <= len(raw)}
            for size in lengths:
                code = raw[:size]
                try:
                    key = (stage,identity(stage,code),size)
                except ValueError:
                    continue
                if key in wanted:
                    targets.setdefault(key,code)
    rows = []
    searched = scanned = 0
    started = time.perf_counter()
    for number,p in enumerate(files(assets,elf)):
        if time.perf_counter()-started > 600:
            break
        size = p.stat().st_size
        if not 0 < size <= MAX_CONTAINER:
            continue
        if scanned + size > 16*1024**3:
            break
        searched += 1
        scanned += size
        container = None
        with p.open('rb') as stream, mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            for key,code in list(targets.items()):
                if time.perf_counter()-started > 600:
                    break
                stage,program_id,length = key
                variants = [('native',code)] if stage == 'fp' else [('swap32',word_swap(code)),('native',code)]
                matched = False
                for encoding,needle in variants:
                    pos = 0
                    # Repetitive data must not turn one anchor into an
                    # unbounded Python candidate walk. A skipped match remains
                    # unresolved rather than weakening verification.
                    for attempt in range(4096):
                        pos = data.find(needle[:16],pos)
                        if pos < 0:
                            break
                        raw = data[pos:pos+length]
                        candidate = word_swap(raw) if encoding == 'swap32' else raw
                        try:
                            valid = len(candidate) == length and identity(stage,candidate) == program_id
                        except ValueError:
                            valid = False
                        if valid:
                            if container is None:
                                container = digest(data)
                            rows.append(dict(stage=stage,id=program_id,size=length,container=container,
                                             container_size=size,offset=pos,encoding=encoding))
                            del targets[key]
                            matched = True
                            break
                        pos += 1
                    if matched:
                        break
        if number % 100 == 0:
            print(f'Asset lookup {number}: {len(rows)} verified programs; {time.perf_counter()-started:.1f}s',flush=True)
        if not targets:
            break
    return validate(dict(schema=SCHEMA,version=1,records=rows)),dict(requested=len(wanted),located=len(rows),
        unavailable_oracle=len(wanted)-len(rows)-len(targets),unresolved=len(targets),
        containers_searched=searched,bytes_searched=scanned,seconds=time.perf_counter()-started)


def main():
    from pipeline_template import read as read_template,locate
    from train_pipeline_cache import isolated,save_report
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('template','trace','assets','elf','output'):
        ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--catalog',type=Path,help='Omit programs already found by the SHDS lookup')
    args = ap.parse_args()
    output = isolated(args.output)
    if output.exists():
        ap.error('Use a fresh ignored output')
    records = read_template(args.template)['records']
    known = set()
    if args.catalog is not None:
        v,f,_ = locate(records,args.catalog,args.elf)
        known = {(s,r[s]['sha256'],r[s]['size']) for r in records for s,found in (('vp',v),('fp',f))
                 if r[s]['sha256'] in found}
    document,stats = build(records,args.trace,args.assets,args.elf,known)
    output.mkdir(parents=True)
    save_report(output/'asset-map.json',document)
    save_report(output/'report.json',stats)
    print(json.dumps(stats))


if __name__ == '__main__':
    main()
