param([string]$Runtime = "")
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = $env:PS3RECOMP_DIR; if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) 'ps3recomp-gt5p-v018' } }
$dir = Join-Path $root 'scratch/depth-clear-reuse'
New-Item -ItemType Directory -Force $dir | Out-Null
@'
from pathlib import Path
import sys
s = Path(sys.argv[1]).read_text(encoding='utf-8')
pieces = []
for name, end in [('rsx_stencil_mask_pass', '/* The guest\'s depth test'),
                  ('depth_clear_flags', 'static u32 current_rt_off')]:
    start = s.index('static ' + ('int ' if name.startswith('rsx_') else 'u32 ') + name + '(')
    pieces.append(s[start:s.index(end, start)])
Path(sys.argv[2]).write_text('\n'.join(pieces), encoding='utf-8')
'@ | & "$root/.venv/Scripts/python.exe" - "$Runtime/libs/video/rsx_d3d12_backend.c" "$dir/clear_helpers.h"
if ($LASTEXITCODE) { throw 'Helper extraction failed' }
@"
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /std:c17 /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$Runtime/libs/video" /I"$dir" /Fo"$dir/test.obj" /Fe"$dir/test.exe" "$PSScriptRoot/depth_clear_reuse.c"
"@ | Set-Content -LiteralPath "$dir/build.cmd" -Encoding ASCII
& cmd /c "$dir/build.cmd"
if ($LASTEXITCODE) { throw 'Clear test build failed' }
$old = $env:RSX_DEPTH_CLEAR_REUSE
$oldMask = $env:RSX_NO_STENCIL_MASK_RT
try {
    Remove-Item Env:RSX_NO_STENCIL_MASK_RT -ErrorAction SilentlyContinue
    foreach ($mode in @($null, '0')) {
        if ($null -eq $mode) { Remove-Item Env:RSX_DEPTH_CLEAR_REUSE -ErrorAction SilentlyContinue }
        else { $env:RSX_DEPTH_CLEAR_REUSE = $mode }
        & "$dir/test.exe"
        if ($LASTEXITCODE) { throw 'Clear regression check failed' }
    }
} finally {
    if ($null -eq $old) { Remove-Item Env:RSX_DEPTH_CLEAR_REUSE -ErrorAction SilentlyContinue }
    else { $env:RSX_DEPTH_CLEAR_REUSE = $old }
    if ($null -eq $oldMask) { Remove-Item Env:RSX_NO_STENCIL_MASK_RT -ErrorAction SilentlyContinue }
    else { $env:RSX_NO_STENCIL_MASK_RT = $oldMask }
}
