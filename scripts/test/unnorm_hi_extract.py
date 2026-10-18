"""Extract the actual backend helpers for the CPU regression executable."""
import re
import sys
from pathlib import Path

source = (Path(sys.argv[1]) / "libs/video/rsx_d3d12_backend.c").read_text()


def structure(name):
    end = source.index("} " + name + ";") + len("} " + name + ";")
    start = source.rfind("typedef struct {", 0, end)
    assert start >= 0
    return source[start:end]


def function(name):
    match = re.search(r"^static (?:int|u32) " + name + r"\(", source, re.M)
    assert match, name
    start = source.index("{", match.start())
    # Ignore braces in C strings, character literals and comments.
    tokens = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*|[{}]'
    depth = 0
    for token in re.finditer(tokens, source[start:], re.S):
        if token[0] == "{":
            depth += 1
        elif token[0] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():start + token.end()]
    raise ValueError("Unterminated function: " + name)


prefix = """#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ps3emu/ps3types.h>
#include <ps3emu/getenv_cache.h>
#define RSX_TEX_UNITS 16
typedef struct ID3D12PipelineState ID3D12PipelineState;
"""
parts = [structure("D3D12DrawRecord"), structure("VPFPEntry")]
parts += [function(name) for name in (
    "dr_unnorm_hi", "fp_scale_unit", "pso_code_share", "fp_key_hash", "fp_key_eq"
)]
Path(sys.argv[2]).write_text(prefix + "\n\n".join(parts), encoding="utf-8")
