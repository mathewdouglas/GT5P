# Scan input/EMAIN.ELF for SPU job bodies: the 0xC0DEC0DE magic at +0x20 of a
# 16-byte-aligned header. Prints EA, the header's entry and size words, and
# whether config/targets.json already lists it.
import json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
elf = (ROOT / "input" / "EMAIN.ELF").read_bytes()
phoff, = struct.unpack_from(">Q", elf, 0x20)
phentsz, phnum = struct.unpack_from(">HH", elf, 0x36)
segs = []
for i in range(phnum):
    o = phoff + i * phentsz
    ptype, flags, off, vaddr, paddr, filesz, memsz, align = struct.unpack_from(">IIQQQQQQ", elf, o)
    if ptype == 1 and filesz:
        segs.append((off, vaddr, filesz))
sys.path.insert(0, str(ROOT / "scripts"))
import target                                  # follows GT5P_TARGET / input/target
cfg = target.TARGET
known = {int(e, 16) for e, _, _ in cfg.get("wws_job_bodies", [])}
pm = int(cfg["wws_job_pm_ea"], 16)
dumps = ROOT / "analysis" / "spu" / "dump"
pos = 0
while True:
    pos = elf.find(b"\xc0\xde\xc0\xde", pos)
    if pos < 0:
        break
    h = pos - 0x20
    pos += 4
    if h % 16:
        continue
    for off, va, fs in segs:
        if off <= h < off + fs:
            ea = va + (h - off)
            break
    else:
        continue
    w = struct.unpack_from(">12I", elf, h)
    tag = "known body" if ea in known else ("policy module" if ea == pm else "")
    print(f"ea=0x{ea:08X} entry=0x{w[4]:05X} size=0x{w[5]:05X} ({w[5]}) w6=0x{w[6]:X} w7=0x{w[7]:X} "
          f"w10=0x{w[10]:X} w11=0x{w[11]:X} {tag}")
print("captured job images:", len(list(dumps.glob("spujob_*.bin"))) if dumps.exists() else 0)
