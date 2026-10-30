"""Compare independent CPU input construction with production packing/layout."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parents[1]))
from shader_coverage import ROOT


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtime', type=Path, required=True)
    args = ap.parse_args()
    source = (args.runtime / 'libs/video/rsx_d3d12_backend.c').read_text()
    start = source.index('static void vp_stage_mask(')
    end = source.index('\n}', start) + 2
    stage = source[start:end]
    marker = source.index('il[_i].SemanticName = "ATTR"')
    start = source.rfind('    D3D12_INPUT_ELEMENT_DESC il[16];', 0, marker)
    end = source.index('    D3D12_GRAPHICS_PIPELINE_STATE_DESC pd', marker)
    layout = source[start:end]
    folder = ROOT / 'scratch' / ('input-native-' + uuid.uuid4().hex)
    folder.mkdir()
    prefix = '''#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <d3d12.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned u32;
typedef struct {u32 vertex_attrib_input_mask;} rsx_state;
static u32 s_cur_vmask,s_cur_vstride;
'''
    prefix += '#include "' + str((args.runtime / 'libs/video/rsx_input_reconstruct.h').resolve()).replace('\\', '/') + '"\n'
    suffix = '''
__declspec(dllexport) unsigned check(void) {
 for(unsigned raw=0;raw<65536;raw++) {
  rsx_state st={raw};vp_stage_mask(&st);u32 s_pso_vmask=s_cur_vmask;
  D3D12_INPUT_ELEMENT_DESC independent[16];pso_input_layout(raw,independent);
''' + layout + '''
  for(unsigned i=0;i<16;i++) {
   if(strcmp(il[i].SemanticName,independent[i].SemanticName))return raw+1;
   il[i].SemanticName=independent[i].SemanticName=NULL;
   if(memcmp(&il[i],&independent[i],sizeof il[i]))return raw+1;
  }
 }
 return 0;
}
'''
    (folder / 'oracle.c').write_text(prefix + stage + suffix)
    vc = 'C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'
    (folder / 'build.cmd').write_text('@echo off\ncall "' + vc + '" >nul\nif errorlevel 1 exit /b 1\n'
        '"C:/Program Files/LLVM/bin/clang-cl.exe" /nologo /O2 /MD /LD /Fooracle.obj /Feoracle.dll oracle.c\n')
    subprocess.run(['cmd', '/c', str(folder / 'build.cmd')], cwd=folder, check=True)
    dll = ctypes.CDLL(str(folder / 'oracle.dll'))
    os.environ.pop('RSX_VTX_MASK', None)
    dll.check.restype = ctypes.c_uint32
    assert dll.check() == 0, 'Independent input layout differs from production'
    report = dict(masks=65536, elements=65536 * 16,
                  assumption='Default RSX_VTX_MASK and shader wrapper binding with no later input-mask override')
    (folder / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(**report, report=str(folder / 'report.json'))))


if __name__ == '__main__':
    main()
