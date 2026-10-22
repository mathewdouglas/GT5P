param([string]$Runtime = "")
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) "ps3recomp-gt5p-master" }
$dir = Join-Path $root "scratch/rsx-textures"
New-Item -ItemType Directory -Force $dir | Out-Null
$cmd = Join-Path $dir "build.cmd"
@"
@echo off
set "PATH=C:\Program Files (x86)\Microsoft Visual Studio\Installer;%PATH%"
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /std:c17 /D_CRT_SECURE_NO_WARNINGS /I"$Runtime" /I"$Runtime/include" /Fo"$dir/test.obj" /Fe"$dir/test.exe" "$PSScriptRoot/rsx_textures.c"
"@ | Set-Content -LiteralPath $cmd -Encoding ASCII
& cmd /c $cmd
if ($LASTEXITCODE) { throw "Texture test build failed: $LASTEXITCODE" }
& "$dir/test.exe"
if ($LASTEXITCODE) { throw "Texture test failed: $LASTEXITCODE" }
