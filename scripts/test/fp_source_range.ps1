param([string]$Runtime = "")
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) 'ps3recomp-gt5p-master' }
$dir = Join-Path $root 'scratch/fp-source-range'
New-Item -ItemType Directory -Force $dir | Out-Null
@"
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$Runtime/libs/video" /c /Fo"$dir/decoder.obj" "$Runtime/libs/video/rsx_fp_decompiler.c"
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /EHsc /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$Runtime/libs/video" /Fo"$dir/" /Fe"$dir/test.exe" "$PSScriptRoot/fp_source_range.cpp" "$dir/decoder.obj" /link d3d11.lib d3dcompiler.lib
"@ | Set-Content -LiteralPath "$dir/build.cmd" -Encoding ASCII
& cmd /c "$dir/build.cmd"
if ($LASTEXITCODE) { throw 'Source-range test build failed' }
$previous = $env:RSX_FP_SOURCE_RANGE
try {
    $env:RSX_FP_SOURCE_RANGE = '1'
    & "$dir/test.exe"
    if ($LASTEXITCODE) { throw 'Experimental source-range rendering failed' }
    $env:RSX_FP_SOURCE_RANGE = '0'
    & "$dir/test.exe"
    if ($LASTEXITCODE) { throw 'Source-range rollback rendering failed' }
    $env:RSX_FP_SOURCE_RANGE = '2'
    & "$dir/test.exe"
    if ($LASTEXITCODE) { throw 'Explicit saturation-only rendering failed' }
    Remove-Item Env:RSX_FP_SOURCE_RANGE -ErrorAction SilentlyContinue
    & "$dir/test.exe"
    if ($LASTEXITCODE) { throw 'Stable default rendering failed' }
} finally {
    if ($null -eq $previous) { Remove-Item Env:RSX_FP_SOURCE_RANGE -ErrorAction SilentlyContinue }
    else { $env:RSX_FP_SOURCE_RANGE = $previous }
}
