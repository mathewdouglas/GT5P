"""Extract SHDS fragment programs and prepare the renderer's real DXBC cache.

All game-derived files stay local under shadercache/ or scratch/. For assets,
pass --assets pointing to an unpacked GT.VOL, or --unpacker pointing to the
GTToolsSharp executable (https://github.com/Nenkai/GTToolsSharp). No keys or
third-party unpacker source are included here. The executable is always read.
This prepares base and previously observed shader states, not every possible
pipeline/vertex shader/state combination.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_CODE = 32768


def fragment_programs(data):
    """Read bounded SHDS fragment tables relative to SHDS or enclosing MDL3.

    Layout reference: Nenkai/PDTools (MIT), Models/Shaders/ShadersHeader.cs
    and ShaderProgram_0x40.cs. This reader only handles bounded code records;
    no material, texture or relocation data is interpreted.
    """
    start = 0
    while True:
        header = data.find(b'SHDS', start)
        if header < 0: return
        start = header + 4
        if header + 0x44 > len(data): continue
        count = struct.unpack_from('>H', data, header + 0x34)[0]
        table = struct.unpack_from('>I', data, header + 0x40)[0]
        if not count or count > 8192: continue
        model = data.rfind(b'MDL3', 0, header)
        for base in ([model, header] if model >= 0 else [header]):
            if not table or base + table + count * 0x20 > len(data): continue
            programs = []
            for i in range(count):
                _, offset, size = struct.unpack_from('>III', data, base + table + i * 0x20)
                if not offset or not size or size > MAX_CODE or size % 16 or base + offset + size > len(data):
                    break
                programs.append((header, base + offset, data[base + offset:base + offset + size]))
            else:
                yield from programs
                break


def extract(inputs, output):
    output.mkdir(parents=True, exist_ok=True)
    unique, sources = {}, []
    for path in inputs:
        data = path.read_bytes()
        for header, offset, program in fragment_programs(data):
            digest = hashlib.sha256(program).hexdigest()
            if digest not in unique:
                name = digest + '.fp'
                (output / name).write_bytes(program)
                unique[digest] = name
            sources.append(dict(file=str(path), header=header, offset=offset, size=len(program), sha256=digest))
    (output / 'index.json').write_text(json.dumps(dict(unique=len(unique), sources=sources), indent=2), encoding='utf-8')
    return len(unique), len(sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, help='Existing unpacked GT.VOL folder')
    parser.add_argument('--unpacker', type=Path, help='GTToolsSharp executable; extracts local GT.VOL to ignored scratch/')
    parser.add_argument('--scope', choices=('all', 'executable'), default='all')
    parser.add_argument('--cache', type=Path, default=ROOT / 'shadercache')
    parser.add_argument('--catalog', type=Path, help='Catalog destination (default: CACHE/library-v1/SCOPE)')
    parser.add_argument('--catalog-only', action='store_true')
    parser.add_argument('--compile-only', action='store_true', help='Reuse an existing extracted catalog; useful after interruption')
    parser.add_argument('--limit', type=int, default=16384, help='Maximum programs per compiler pass (1..16384)')
    parser.add_argument('--base-profiles', action='store_true', help='Only base 16/32-bit output variants; omit learned states')
    parser.add_argument('--profile-limit', type=int, default=64, help='Maximum learned state profiles (0..256); more takes longer')
    parser.add_argument('--all-profile-combinations', action='store_true', help='Apply every learned state to every program, including different texture-unit usage; much slower')
    args = parser.parse_args()
    if not 1 <= args.limit <= 16384: parser.error('--limit must be 1..16384')
    if not 0 <= args.profile_limit <= 256: parser.error('--profile-limit must be 0..256')
    cache = args.cache.resolve(); catalog = (args.catalog or cache / 'library-v1' / args.scope).resolve()
    assets = args.assets.resolve() if args.assets else None
    if not args.compile_only and args.scope == 'all' and assets is None:
        if not args.unpacker: parser.error('For all assets, supply --assets or --unpacker; use --scope executable for an executable-only pass')
        assets = ROOT / 'scratch' / 'shader-assets'
        assets.mkdir(parents=True, exist_ok=True)
        log = assets.parent / 'shader-unpack.log'
        print('Unpacking local game assets; progress log:', log, flush=True)
        with log.open('w', encoding='utf-8') as out:
            subprocess.run([str(args.unpacker.resolve()), 'unpack', '-i', str(ROOT / 'input/pkg/USRDIR/GT.VOL'),
                            '-o', str(assets), '--no-print', '-l', str(assets.parent / 'shader-unpack-files.log')],
                           stdout=out, stderr=subprocess.STDOUT, cwd=assets.parent, check=True)
    if assets is not None and not assets.is_dir(): parser.error('--assets must name an existing directory')
    paths = [ROOT / 'input/EMAIN.ELF']
    if args.scope == 'all' and not args.compile_only:
        paths.extend(sorted(p for p in assets.rglob('*') if p.is_file()))
    if args.compile_only:
        unique = sum(1 for _ in catalog.glob('*.fp'))
    else:
        print('Extracting embedded fragment programs...', flush=True)
        unique, records = extract(paths, catalog)
        print(f'Extracted {unique} distinct payloads from {records} records into {catalog}', flush=True)
    if not unique: raise SystemExit('No supported SHDS programs found')
    if args.catalog_only: return
    if b'gt5p.exe' in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq gt5p.exe', '/NH'], capture_output=True).stdout.lower():
        raise SystemExit('Close the running game before offline compilation')
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ('PS3_HEADLESS', 'GT5P_NO_PRESENT', 'RSX_LIVE_DRAW'): env.pop(key, None)
    env.update(GT5P_NO_SETTINGS='1', PS3_VERBOSE='0', FS_HIDE='grim/file/contents', RSX_SHADER_WARMUP='1',
               RSX_SHADER_ASYNC='1', RSX_SHADER_CACHE=str(cache), RSX_SHADER_LIBRARY=str(catalog),
               RSX_SHADER_LIBRARY_LIMIT=str(args.limit), GT5P_SHADER_PRECOMPILE_ONLY='1')
    env['RSX_SHADER_LIBRARY_PROFILE_LIMIT'] = str(args.profile_limit)
    env['RSX_SHADER_LIBRARY_BROAD'] = '1' if args.all_profile_combinations else '0'
    if args.base_profiles: env['RSX_SHADER_LIBRARY_PROFILES'] = 'base'
    else: env.pop('RSX_SHADER_LIBRARY_PROFILES', None)
    log = cache / 'precompile.log'
    print('Preparing shaders before guest execution. This can take several minutes; log:', log, flush=True)
    with log.open('w', encoding='utf-8') as out:
        proc = subprocess.Popen([str(ROOT / 'build/gt5p.exe')], cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
        try:
            last = 0
            while proc.poll() is None:
                time.sleep(.5)
                with log.open(encoding='utf-8', errors='replace') as reader:
                    reader.seek(last); fresh = reader.read(); last = reader.tell()
                for line in fresh.splitlines():
                    if '[shader-library]' in line: print(line, flush=True)
            if proc.returncode: raise SystemExit(f'Compiler exited with {proc.returncode}; inspect {log}')
        finally:
            if proc.poll() is None: proc.terminate(); proc.wait()
    text = log.read_text(encoding='utf-8', errors='replace')
    summary = re.search(r'\[shader-library\] finished: programs=(\d+) attempts=(\d+) rejected=(\d+) compiled=(\d+)', text)
    if not summary: raise SystemExit(f'Compilation did not finish; inspect {log}')
    if int(summary[3]): print(f'Partial coverage: {summary[3]} input/variant failures were skipped; inspect {log}.', flush=True)
    print('Pass complete. Keep this cache enabled when playing. New vertex shaders, states and pipelines may still compile.', flush=True)


if __name__ == '__main__': main()
