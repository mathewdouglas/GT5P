# Build/run isolated SDL virtual-controller and WASAPI recovery checks.
# No game dump needed. Requires the Windows SDK, clang-cl, SDL2.dll, and the
# patched runtime checkout, a free controller port and a working default audio
# output. Does not change the system's default audio device.
param([string]$Runtime = "", [string]$Sdl = "")
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Runtime) { $Runtime = Join-Path (Split-Path $root -Parent) "ps3recomp-gt5p-master" }
if (!$Sdl) { $Sdl = Join-Path $root "third_party/SDL2.dll" }
$dir = Join-Path $root "scratch/hotplug"
New-Item -ItemType Directory -Force $dir | Out-Null
Copy-Item -LiteralPath $Sdl -Destination "$dir/SDL2.dll" -Force
$compile = @"
@echo off
set "PATH=C:\Program Files (x86)\Microsoft Visual Studio\Installer;%PATH%"
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /Gy /MD /std:c17 /D_CRT_SECURE_NO_WARNINGS /I"$Runtime" /I"$Runtime/include" /Fo"$dir/hotplug.obj" /Fe"$dir/hotplug.exe" "$PSScriptRoot/hotplug.c" /link /OPT:REF ole32.lib user32.lib
"@
$cmd = Join-Path $dir "build.cmd"
Set-Content -LiteralPath $cmd -Value $compile -Encoding ASCII
& cmd /c $cmd
if ($LASTEXITCODE) { throw "Hotplug test build failed: $LASTEXITCODE" }
foreach ($mode in @("ports", "worker", "audio")) {
    & "$dir/hotplug.exe" $mode
    if ($LASTEXITCODE) { throw "Hotplug $mode test failed: $LASTEXITCODE" }
}
