param([string]$Runtime = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = $env:PS3RECOMP_DIR; if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) 'ps3recomp-gt5p-v018' } }
$dir = Join-Path $root 'scratch/volume-textures'
New-Item -ItemType Directory -Force $dir | Out-Null
@"
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$Runtime/libs/video" /c /Fo"$dir/decoder.obj" "$Runtime/libs/video/rsx_fp_decompiler.c"
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$Runtime/libs/video" /c /Fo"$dir/layout.obj" "$Runtime/libs/video/rsx_texture_layout.c"
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /EHsc /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$Runtime/libs/video" /Fo"$dir/" /Fe"$dir/test.exe" "$PSScriptRoot/volume_textures.cpp" "$dir/decoder.obj" "$dir/layout.obj" /link d3d11.lib d3dcompiler.lib
if errorlevel 1 exit /b 1
"$dir/test.exe"
"@ | Set-Content -LiteralPath "$dir/build.cmd" -Encoding ASCII
& cmd /c "$dir/build.cmd"
if ($LASTEXITCODE) { throw 'Volume texture regression failed' }
