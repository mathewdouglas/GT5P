$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = Join-Path $root ('scratch/debug-export-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $dir | Out-Null
$build = Join-Path $dir 'build.cmd'
@"
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /std:c++20 /EHsc /D_CRT_SECURE_NO_WARNINGS /I"$root/src" /I"$root/build" /I"$root/external/tomlplusplus" /Fo"$dir/" /Fe"$dir/test.exe" "$PSScriptRoot/debug_export.cpp" "$root/src/gt5p_debug_export.cpp" "$root/src/gt5p_settings.cpp" "$root/src/gt5p_keymap.cpp" /link user32.lib gdi32.lib shell32.lib
"@ | Set-Content -LiteralPath $build -Encoding ASCII
& cmd /c $build
if ($LASTEXITCODE) { throw 'Debug exporter test build failed' }
& "$root/.venv/Scripts/python.exe" "$PSScriptRoot/debug_export_check.py" "$dir/test.exe" $dir
if ($LASTEXITCODE) { throw 'Debug exporter integration checks failed' }
