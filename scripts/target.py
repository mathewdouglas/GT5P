#!/usr/bin/env python3
"""Per-build constants, so one set of scripts serves more than one game build.

Every address the pipeline hard-codes belongs to one executable. They live in
config/targets.json, keyed by title id. The build in use is, in order:

  * the GT5P_TARGET environment variable;
  * the first line of input/target (gitignored, so it describes this machine's
    input/EMAIN.ELF and nothing else);
  * NPUA80075, the build upstream targets.

    from target import TARGET, addr
    TEXT_HI = addr("code_end")

    python scripts/target.py            # print the build in use
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = "NPUA80075"


def _name():
    env = os.environ.get("GT5P_TARGET", "").strip()
    if env:
        return env
    marker = ROOT / "input" / "target"
    if marker.exists():
        lines = marker.read_text(encoding="ascii", errors="replace").split()
        if lines:
            return lines[0]
    return DEFAULT


NAME = _name()
_all = json.loads((ROOT / "config" / "targets.json").read_text(encoding="utf-8"))
if NAME not in _all:
    raise SystemExit(f"unknown target {NAME!r}; config/targets.json has {sorted(_all)}")
TARGET = _all[NAME]
EXE_NAME = TARGET.get("exe_name", "gt5p")


def addr(key):
    """An address from the target as an int; exits if it is not known yet."""
    v = TARGET.get(key)
    if v is None:
        raise SystemExit(f"{key} is not set for {NAME} in config/targets.json")
    return int(v, 16) if isinstance(v, str) else int(v)


def path(key):
    return ROOT / TARGET[key]


if __name__ == "__main__":
    print(NAME)
    for k, v in TARGET.items():
        print(f"  {k} = {v}")
