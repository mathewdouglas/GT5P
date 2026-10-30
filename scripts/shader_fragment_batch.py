"""Exact offline fragment requests through the renderer's bounded compiler queue."""
from collections import defaultdict
import hashlib
import json
import re
import subprocess
import time

from shader_coverage import bounded_read,fnv64
from shader_reconstruct import offline_env,run_offline


def compile_batch(jobs,root,cache,engine,game_root):
    from prepare_material_shaders import fragment_profile,save_code
    started=time.perf_counter()
    groups=defaultdict(dict)
    members=defaultdict(list)
    hashes={}
    job_requests={}
    for job in jobs:
        profile=fragment_profile(job)
        raw=job['fragment']
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=job['fragment_sha256']:
            raise ValueError('Fragment payload differs from declared identifier')
        if (len(raw)==0 or len(raw)>32768 or len(raw)%16 or
                any(type(v) is not int or not 0<=v<(1<<(64 if i==4 else 32)) for i,v in enumerate(profile[:-1])) or
                profile[0]>1 or profile[2]&~(1<<26) or profile[8]>65535):
            raise ValueError('Invalid bounded fragment request')
        identity=hashlib.sha256(repr((digest,profile)).encode()).hexdigest()
        if job['id'] in job_requests and job_requests[job['id']]!=identity:
            raise ValueError('Conflicting fragment job identifier')
        job_requests[job['id']]=identity
        groups[profile[-1]][identity]=(digest,raw,profile)
        members[identity].append(job['id'])
        if digest not in hashes:hashes[digest]=fnv64(raw)
    compiled,failures,pool={},{},{}
    code_bytes=0
    report=dict(mode='batch',requested_jobs=len(jobs),unique_requests=len(members),processes=0,batches=[])
    for dither,requests in sorted(groups.items()):
        items=sorted(requests.items())
        for offset in range(0,len(items),4096):
            chunk=items[offset:offset+4096]
            work=root/f'fragment-batch-{dither}-{offset//4096}';work.mkdir(exist_ok=True)
            lines=[f'GT5P_FP_BATCH_V1 {len(chunk)}\n']
            for identity,(digest,raw,profile) in chunk:
                path=work/(digest+'.fp')
                if path.exists():
                    if bounded_read(path,32768)!=raw:raise ValueError('Existing fragment batch input differs')
                else:path.write_bytes(raw)
                lines.append(f'{identity} {digest} {hashes[digest]:016x} '+ ' '.join(f'{v:x}' for v in profile[:-1])+'\n')
            (work/'jobs.txt').write_text(''.join(lines),encoding='ascii')
            env=offline_env(game_root,cache)
            env.update(RSX_SHADER_LIBRARY_BATCH=str(work),RSX_FINAL_DITHER=str(dither))
            begin=time.perf_counter();report['processes']+=1
            print(f'Compiling exact fragment batch: {len(chunk)} requests, dither={dither}',flush=True)
            try:
                log=run_offline(engine,game_root,env,work/'fragment.log',timeout=900)
                text=bounded_read(work/'compiled.tsv',4*1024**2).decode('ascii').splitlines()
                if not text or text[0]!=f'GT5P_FP_BATCH_RESULTS_V1 {len(chunk)}':
                    raise ValueError('Missing/incompatible fragment batch result header')
                rows={}
                expected={identity for identity,_ in chunk}
                for line in text[1:]:
                    fields=line.split()
                    if (len(fields)!=4 or fields[0] not in expected or fields[0] in rows or
                            any(not re.fullmatch('[0-9a-f]{16}',v) for v in fields[1:3]) or fields[3] not in ('0','1')):
                        raise ValueError('Malformed/duplicate/unexpected fragment batch result')
                    rows[fields[0]]=fields[1:]
                if set(rows)!=expected:
                    raise ValueError('Fragment batch result count mismatch')
                for identity,(digest,raw,profile) in chunk:
                    try:
                        raw_hash,key,success=rows[identity]
                        if success!='1' or int(raw_hash,16)!=hashes[digest] or int(key,16)==0:
                            raise ValueError('Production compiler rejected exact fragment request')
                        if key not in pool:
                            code=bounded_read(cache/(key+'.dxbc'),4*1024**2)
                            if not code.startswith(b'DXBC') or code_bytes+len(code)>128*1024**2:
                                raise ValueError('Invalid/oversized fragment bytecode pool')
                            pool[key]=code;code_bytes+=len(code)
                        save_code(cache/(key+'.dxbc'),pool[key])
                        for job_id in members[identity]:compiled[job_id]=(key,pool[key])
                    except (ValueError,OSError) as exc:
                        for job_id in members[identity]:failures[job_id]=str(exc)
                summary=re.search(r'\[fp-batch\] finished: requests=(\d+) rejected=(\d+) compiled=(\d+) elapsed_ms=(\d+)',log)
                if not summary:raise ValueError('Fragment batch completion summary missing')
                report['batches'].append(dict(requests=len(chunk),seconds=time.perf_counter()-begin,
                                             native_summary=list(map(int,summary.groups()))))
            except (ValueError,OSError,subprocess.SubprocessError) as exc:
                for identity,_ in chunk:
                    for job_id in members[identity]:
                        compiled.pop(job_id,None);failures[job_id]=str(exc)
                report['batches'].append(dict(requests=len(chunk),seconds=time.perf_counter()-begin,error=str(exc)))
    report.update(seconds=time.perf_counter()-started,prepared_jobs=len(compiled),failed_jobs=len(failures))
    (root/'fragment-preparation-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return compiled,failures
