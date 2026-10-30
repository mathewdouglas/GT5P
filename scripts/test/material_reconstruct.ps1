param([string]$Runtime = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) 'ps3recomp-gt5p-provenance' }
$Runtime = (Resolve-Path $Runtime).Path
$dir = Join-Path $root ('scratch/material-descriptor-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $dir | Out-Null
@"
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/libs/video" /Fo"$dir/test.obj" /Fe"$dir/test.exe" "$PSScriptRoot/material_reconstruct.c"
if errorlevel 1 exit /b 1
"$dir/test.exe" "$dir"
"@ | Set-Content -LiteralPath "$dir/build.cmd" -Encoding ASCII
& cmd /c "$dir/build.cmd"
if ($LASTEXITCODE) { throw 'Material descriptor reconstruction test failed' }
