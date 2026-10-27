param([string]$Runtime = "")
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = $env:PS3RECOMP_DIR; if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) "ps3recomp-gt5p-v018" } }
$dir = Join-Path $root "scratch/unnorm-hi"
New-Item -ItemType Directory -Force $dir | Out-Null
& "$root/.venv/Scripts/python.exe" "$PSScriptRoot/unnorm_hi_extract.py" $Runtime "$dir/backend_helpers.h"
if ($LASTEXITCODE) { throw "Backend helper extraction failed" }
$cmd = Join-Path $dir "build.cmd"
@"
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /std:c17 /W4 /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$dir" /Fo"$dir/test.obj" /Fe"$dir/test.exe" "$PSScriptRoot/unnorm_hi.c"
"@ | Set-Content -LiteralPath $cmd -Encoding ASCII
& cmd /c $cmd
if ($LASTEXITCODE) { throw "Upper-unit test build failed: $LASTEXITCODE" }
$saved = @{}
foreach ($key in "RSX_UNNORM_HI", "RSX_NO_UNNORM") {
    $saved[$key] = [Environment]::GetEnvironmentVariable($key)
    Remove-Item "Env:$key" -ErrorAction SilentlyContinue
}
try {
    & "$dir/test.exe"
    if ($LASTEXITCODE) { throw "Default upper-unit checks failed" }
    $env:RSX_UNNORM_HI = "0"
    & "$dir/test.exe"
    if ($LASTEXITCODE) { throw "Upper-unit bypass checks failed" }
    Remove-Item Env:RSX_UNNORM_HI
    $env:RSX_NO_UNNORM = "1"
    & "$dir/test.exe"
    if ($LASTEXITCODE) { throw "Global unnormalised bypass checks failed" }
} finally {
    foreach ($key in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($key, $saved[$key])
    }
}



