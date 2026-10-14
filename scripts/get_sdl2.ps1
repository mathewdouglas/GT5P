# Fetch SDL2.dll, which the port loads at run time to read controllers that
# XInput does not know (DualSense, DualShock 4, Switch Pro, ...).
#   scripts\get_sdl2.ps1
# It goes to third_party\ (gitignored) and is copied beside build\gt5p.exe;
# the build copies it there again whenever it links. Without the DLL the port
# still runs, with XInput controllers and the keyboard.
param([string]$Version = "2.30.9")
$root = Split-Path $PSScriptRoot -Parent
$dir = Join-Path $root "third_party"
New-Item -ItemType Directory -Force $dir | Out-Null
$zip = Join-Path $dir "sdl2.zip"
$url = "https://github.com/libsdl-org/SDL/releases/download/release-$Version/SDL2-$Version-win32-x64.zip"
"Downloading $url"
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $dir -Force
Remove-Item $zip
if (Test-Path (Join-Path $root "build")) {
    Copy-Item (Join-Path $dir "SDL2.dll") (Join-Path $root "build\SDL2.dll") -Force
    "Copied to build\SDL2.dll"
}
"SDL2 $Version is in third_party\"
