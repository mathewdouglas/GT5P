"""Compile/exercise the actual async job-table helpers without GPU/game data."""
import os
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[2]
runtime = Path(os.environ.get('PS3RECOMP_DIR', root.parent / 'ps3recomp-gt5p-v018'))
source = (runtime / 'libs/video/rsx_d3d12_backend.c').read_text(encoding='utf-8')
folder = root / 'scratch/shader-job-table'
folder.mkdir(parents=True, exist_ok=True)


def function(name):
    start = source.index(name)
    start = source.rfind('static ', 0, start)
    brace = source.index('{', start)
    depth = 1; end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


cap = re.search(r'enum \{ SHC_TAB = (\d+) \}', source)[1]
code = '''#include <stdint.h>
#include <stdlib.h>
#include <assert.h>
#include <stdio.h>
typedef uint64_t u64; typedef uint32_t u32; typedef uint8_t u8;
'''
code += f'enum {{ SHC_TAB = {cap} }};\nstatic u64 s_shc_key[SHC_TAB]; static u8 s_shc_st[SHC_TAB];\n'
code += function('shc_capacity(void)') + '\n' + function('shc_slot(u64')
code += '''
int main(int argc, char** argv) {
    assert(argc == 2); u32 expected = (u32)atoi(argv[1]);
    assert(shc_capacity() == expected);
    for (u32 i = 1; i <= expected; i++) {
        u8* slot = shc_slot(i, 1); assert(slot); *slot = 3;
    }
    for (u32 i = 1; i <= expected; i++) assert(*shc_slot(i, 0) == 3);
    assert(!shc_slot((u64)expected + 1, 1));
    printf("job slots %u: filled, found and bounded correctly\\n", expected);
}
'''
(folder / 'test.c').write_text(code, encoding='utf-8')
build = folder / 'build.cmd'
build.write_text(f'''@echo off
call "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul
"C:\\Program Files\\LLVM\\bin\\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /Fo"{folder}/test.obj" /Fe"{folder}/test.exe" "{folder}/test.c"
''', encoding='ascii')
subprocess.run(['cmd', '/c', str(build)], cwd=root, check=True)
for value, expected in ((None, 65536), ('16384', 16384), ('20', 1024), ('999999', 131072)):
    env = os.environ.copy(); env.pop('RSX_SHADER_JOB_SLOTS', None)
    if value is not None: env['RSX_SHADER_JOB_SLOTS'] = value
    subprocess.run([str(folder / 'test.exe'), str(expected)], env=env, check=True)
