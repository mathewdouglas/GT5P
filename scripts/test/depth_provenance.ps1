param([string]$Runtime = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) 'ps3recomp-gt5p-provenance' }
$Runtime = (Resolve-Path $Runtime).Path
$dir = Join-Path $root ('scratch/depth-provenance-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $dir | Out-Null
Set-Content -LiteralPath "$dir/existing.jsonl" -Value 'sentinel' -Encoding ASCII
@"
@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /MD /D_CRT_SECURE_NO_WARNINGS /I"$Runtime/libs/video" /Fo"$dir/test.obj" /Fe"$dir/test.exe" "$PSScriptRoot/depth_provenance.c"
if errorlevel 1 exit /b 1
"$dir/test.exe" unset "$dir/unset.jsonl"
if errorlevel 1 exit /b 1
"$dir/test.exe" zero "$dir/zero.jsonl"
if errorlevel 1 exit /b 1
"$dir/test.exe" enabled "$dir/capture.jsonl"
if errorlevel 1 exit /b 1
"$dir/test.exe" existing "$dir/existing.jsonl"
if errorlevel 1 exit /b 1
"$dir/test.exe" unmapped "$dir/unmapped.jsonl"
"@ | Set-Content -LiteralPath "$dir/build.cmd" -Encoding ASCII
& cmd /c "$dir/build.cmd"
if ($LASTEXITCODE) { throw 'Depth provenance test failed' }
if ((Test-Path "$dir/unset.jsonl") -or (Test-Path "$dir/zero.jsonl")) { throw 'Disabled recorder wrote output' }
if ((Get-Content "$dir/existing.jsonl" -Raw).Trim() -ne 'sentinel') { throw 'Existing file was overwritten' }
if ((Get-Item "$dir/unmapped.jsonl").Length -ne 0) { throw 'Unmapped packet was recorded' }
$rows = @(Get-Content -LiteralPath "$dir/capture.jsonl" | ForEach-Object { $_ | ConvertFrom-Json })
if ($rows.Count -ne 2 -or $rows[0].depth_func -ne 515 -or $rows[0].material_words.Count -ne 40 -or $rows[0].frame -ne 10) {
    throw 'Incorrect captured depth commands'
}
'Depth recorder disabled paths, milestone gate, packet filter, JSON and cap checks passed'
