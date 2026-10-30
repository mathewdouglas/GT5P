"""Automatically enumerate embedded named banks and prepare CPU vertex shaders.

No captures, car/track visits, pass names or bank offsets are inputs. Fragment
profiles/targets remain unresolved and no complete pipeline coverage is claimed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from shader_coverage import ROOT, fnv64
from shader_reconstruct import NativeCompiler, word_swap
from shader_shared_passes import bank_pairs
from prepare_material_shaders import save_code, source_key


def enumerate_banks(data):
    pairs, rejected = [], []
    start = 0
    while True:
        base = data.find(b'SHDS', start)
        if base < 0:
            return pairs, rejected
        start = base + 4
        try:
            pairs.extend(bank_pairs(data, base))
        except (ValueError, UnicodeError) as exc:
            rejected.append(dict(header=base, reason=str(exc)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', required=True, type=Path)
    ap.add_argument('--decoder', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output / 'report.json')], cwd=ROOT).returncode:
        ap.error('Choose a new ignored output directory')
    for path in (args.elf.resolve(), args.decoder.resolve()):
        if output == path or output in path.parents or path in output.parents:
            ap.error('Output must be separate from inputs')
    data = args.elf.read_bytes()
    pairs, rejected = enumerate_banks(data)
    if not pairs:
        ap.error('No supported named shader banks found')
    output.mkdir(parents=True)
    cache = output / 'shadercache'
    cache.mkdir()
    compiler = NativeCompiler(args.decoder)
    vertices, failed = {}, []
    for pair in pairs:
        vertex = pair['vertex']
        digest = vertex['sha256']
        if digest in vertices or any(f['vertex_sha256'] == digest for f in failed):
            continue
        try:
            code = data[vertex['offset']:vertex['offset'] + vertex['size']]
            if hashlib.sha256(code).hexdigest() != digest:
                raise ValueError('Vertex slice integrity failure')
            hlsl, dxbc = compiler.vertex(word_swap(code), 0)
            key = source_key(hlsl)
            save_code(cache / f'{key:016x}.dxbc', dxbc)
            vertices[digest] = dict(source_key=f'{key:016x}', bytecode_hash=f'{fnv64(dxbc):016x}',
                                    bytecode_bytes=len(dxbc), gpu_fetch=False)
        except (ValueError, OSError) as exc:
            failed.append(dict(vertex_sha256=digest, reason=str(exc)))
    report = dict(schema=1, origin='Original embedded named SHDS banks; no captures or learned profiles.',
                  source=str(args.elf.resolve()), elf_sha256=hashlib.sha256(data).hexdigest(),
                  decoder_sha256=hashlib.sha256(args.decoder.read_bytes()).hexdigest(),
                  pairs=pairs, rejected_banks=rejected, vertices=vertices, failures=failed,
                  scope='CPU vertex shader preparation only. No complete pipeline requests generated.',
                  unresolved=['Actual pass/resource ownership and later overrides',
                              'Fragment translation profile, texture binding/gamma/alias facts',
                              'Output target/depth/stencil context and full native descriptor'])
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{len(pairs)} authored pairs; {len(vertices)} CPU vertex programs prepared; {len(failed)} failures; {len(rejected)} unsupported banks')
    if failed:
        raise SystemExit('Partial vertex preparation; inspect report.json')


if __name__ == '__main__':
    main()
