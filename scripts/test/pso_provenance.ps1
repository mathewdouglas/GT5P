param([string]$Runtime = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) 'ps3recomp-gt5p-provenance' }
$Runtime = (Resolve-Path $Runtime).Path
$dir = Join-Path $root ('scratch/provenance-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $dir | Out-Null
@"
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$Runtime/libs/video" /Fo"$dir/decoder.obj" /c "$Runtime/libs/video/rsx_fp_decompiler.c"
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/include" /I"$Runtime/libs/video" /Fo"$dir/" /Fe"$dir/test.exe" "$PSScriptRoot/pso_provenance.c" "$dir/decoder.obj"
if errorlevel 1 exit /b 1
"$dir/test.exe" unset
if errorlevel 1 exit /b 1
"$dir/test.exe" 0
if errorlevel 1 exit /b 1
"$dir/test.exe" "$dir/capture"
"@ | Set-Content -LiteralPath "$dir/build.cmd" -Encoding ASCII
& cmd /c "$dir/build.cmd"
if ($LASTEXITCODE) { throw 'Provenance serializer regression failed' }
$links = @(Get-ChildItem "$dir/capture/links_*.jsonl")
if ($links.Count -ne 1) { throw 'Expected one trace file' }
$rows = @(Get-Content -LiteralPath $links[0].FullName)
if ($rows.Count -ne 1) { throw 'Expected one deduplicated link' }
$record = $rows[0] | ConvertFrom-Json
if ($record.schema -ne 1 -or $record.request -ne 'queued' -or $record.pipeline -ne '000000000000000a') {
    throw 'Incorrect serialized provenance'
}
"Serializer, disabled paths and cap checks passed: $dir"

