# Fetch FFmpeg's headers and the DLLs the port loads at run time to decode the
# title's movies (H.264 video, ATRAC3plus audio).
#   scripts\get_ffmpeg.ps1
# They go to third_party\ffmpeg\ (gitignored): include\ for the build, bin\
# for avcodec, avutil and swresample, which the build copies beside
# build\gt5p.exe. Re-run CMake (scripts\build.cmd) afterwards so it sees the
# headers. Without them the port still runs, and movies play black and silent.
#
# A pinned LGPL build from BtbN/FFmpeg-Builds (month-end builds are kept);
# the headers and DLLs must stay the same major versions (avcodec 61,
# avutil 59), which libs/codec/codec_ffmpeg.c names.
param(
    [string]$Tag = "autobuild-2026-07-31-14-10",
    [string]$Name = "ffmpeg-n7.1.5-12-g1fdbca85aa-win64-lgpl-shared-7.1",
    [string]$Sha256 = "0f376f96fb38554ccefb1b2ae9c7c6a7b351f0e60a372b38262c320e8392c5d0"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$dir = Join-Path $root "third_party\ffmpeg"
$tmp = Join-Path $root "third_party\ffmpeg_dl"
New-Item -ItemType Directory -Force $tmp | Out-Null
$zip = Join-Path $tmp "ffmpeg.zip"
$url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/$Tag/$Name.zip"
"Downloading $url"
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
$got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($got -ne $Sha256) { Remove-Item -Recurse -Force $tmp; throw "SHA-256 mismatch: $got" }
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = Join-Path $tmp $Name
New-Item -ItemType Directory -Force (Join-Path $dir "bin") | Out-Null
Copy-Item -Recurse -Force (Join-Path $src "include") $dir
foreach ($d in "avcodec-61.dll", "avutil-59.dll", "swresample-5.dll") {
    Copy-Item -Force (Join-Path $src "bin\$d") (Join-Path $dir "bin\$d")
}
Copy-Item -Force (Join-Path $src "LICENSE.txt") (Join-Path $dir "LICENSE.txt")
Remove-Item -Recurse -Force $tmp
if (Test-Path (Join-Path $root "build")) {
    Copy-Item (Join-Path $dir "bin\*.dll") (Join-Path $root "build") -Force
    "Copied the DLLs to build\"
}
"FFmpeg ($Name) is in third_party\ffmpeg\; re-run scripts\build.cmd"
