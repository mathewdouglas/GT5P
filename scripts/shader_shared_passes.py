"""Bounded, capture-free named shader pairs from embedded SHDS banks.

Names select authored pairs, not a vertex/fragment cross product. This supplies
programs only: texture bindings, translation profiles and pipeline state are
deliberately unresolved. Reports contain offsets/hashes, never program bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from shader_coverage import ROOT, MAX_FP, fp_identity


def bank_pairs(data, base):
    if base < 0 or base + 0x44 > len(data) or data[base:base + 4] != b'SHDS':
        raise ValueError('missing SHDS header')
    size = struct.unpack_from('>I', data, base + 4)[0]
    if size < 0x44 or base + size > len(data):
        raise ValueError('invalid SHDS extent')

    def span(offset, length):
        if offset < 0x44 or length <= 0 or offset + length > size:
            raise ValueError('reference outside SHDS bank')
        return base + offset

    def unpack(fmt, offset):
        return struct.unpack_from('>' + fmt, data, span(offset, struct.calcsize('>' + fmt)))

    def table(offset, count, stride):
        if not 0 < count <= 8192:
            raise ValueError('invalid SHDS table count')
        span(offset, count * stride)
        return [offset + i * stride for i in range(count)]

    nc, vc, fc = struct.unpack_from('>HHH', data, base + 0x16)
    nt, vt, ft, mt = (struct.unpack_from('>I', data, base + o)[0] for o in (0x1c, 0x20, 0x2c, 0x40))
    mc = struct.unpack_from('>H', data, base + 0x34)[0]
    vertices, fragments = table(vt, vc, 40), table(ft, fc, 72)
    maps = {}
    for entry in table(mt, mc, 32):
        descriptor, offset, length = unpack('III', entry)
        span(descriptor, 16)
        if not 0 < length <= MAX_FP:
            raise ValueError('invalid fragment size')
        span(offset, length)
        if descriptor in maps:
            raise ValueError('ambiguous compact fragment descriptor')
        maps[descriptor] = (offset, length)
    result, seen = [], set()
    previous = None
    for entry in table(nt, nc, 12):
        name_offset, tag, vi, fi = unpack('IIHH', entry)
        start = span(name_offset, 1)
        end = data.find(b'\0', start, min(base + size, start + 256))
        if end < 0:
            raise ValueError('unterminated SHDS name')
        name = bytes(data[start:end]).decode('ascii')
        key = (tag, name)
        if not name or key in seen or (previous is not None and key <= previous):
            raise ValueError('duplicate or unsorted SHDS name')
        seen.add(key)
        previous = key
        if vi >= vc or fi >= fc:
            raise ValueError('named shader index out of bounds')
        vo, vl = unpack('II', vertices[vi])
        if not 32 <= vl <= MAX_FP + 32:
            raise ValueError('invalid vertex wrapper size')
        wrapper = span(vo, vl)
        instructions = struct.unpack_from('>H', data, wrapper)[0]
        code = struct.unpack_from('>I', data, wrapper + 16)[0]
        length = instructions * 16
        if not length or length > MAX_FP or code < 32 or code % 16 or code + length > vl:
            raise ValueError('invalid vertex wrapper')
        descriptor = unpack('I', fragments[fi])[0]
        if descriptor not in maps:
            raise ValueError('missing fragment payload')
        fo, fl = maps[descriptor]
        vb, fb = data[wrapper + code:wrapper + code + length], data[span(fo, fl):base + fo + fl]
        result.append(dict(name=name, tag=tag, header=base, record=base + entry,
                           vertex_input_mask=struct.unpack_from('>I', data, wrapper + 4)[0],
                           vertex_input_source=dict(offset=wrapper + 4, size=4,
                               sha256=hashlib.sha256(data[wrapper + 4:wrapper + 8]).hexdigest()),
                           vertex_index=vi, fragment_index=fi,
                           vertex=dict(header=base, offset=wrapper + code, size=length,
                                       wrapper=wrapper, wrapper_size=vl, order='swap32',
                                       sha256=hashlib.sha256(vb).hexdigest()),
                           fragment=dict(offset=base + fo, size=fl, sha256=hashlib.sha256(fb).hexdigest()),
                           fragment_control=unpack('I', descriptor + 8)[0],
                           identity=fp_identity(fb)['identity']))
    return result


def named_pair(data, base, name, tag=0):
    matches = [p for p in bank_pairs(data, base) if (p['name'], p['tag']) == (name, tag)]
    if len(matches) != 1:
        raise ValueError('named shared pass absent or ambiguous')
    return matches[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', type=Path, required=True)
    ap.add_argument('--bank-offset', type=lambda s: int(s, 0), required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT).returncode:
        ap.error('Choose a new gitignored output file')
    data = args.elf.read_bytes()
    pairs = bank_pairs(data, args.bank_offset)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(schema=1, source=str(args.elf.resolve()),
                                     sha256=hashlib.sha256(data).hexdigest(), pairs=pairs,
                                     scope='Authored program pairs only; all draw state remains unresolved.'), indent=2))
    print(f'{len(pairs)} named shared pairs: {output}')


if __name__ == '__main__':
    main()
