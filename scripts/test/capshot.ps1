# Drive to the Car Dealer page and save the game's own backbuffer (RSX_CAP),
# so desktop windows never end up in the picture.
#   scripts\test\capshot.ps1 -Tag t [-Settle 25] NAME=VALUE ...   -> scratch\pv\<t>.cap.png
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "cap", [int]$Settle = 25, [int]$Min = 1500, [int]$Zb = 200,
      [Parameter(ValueFromRemainingArguments = $true)] $Vars)
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$d = "scratch/pv/cap_$Tag"
Remove-Item -Recurse -Force "$root\$d" -ErrorAction SilentlyContinue
$all = @("RSX_CAP=100", "RSX_CAP_ZB=$Zb", "RSX_CAP_MIN=$Min", "RSX_CAP_DIR=$d", "GT5P_PROFVIEW=0") + @($Vars)
& "$PSScriptRoot\pvshot.ps1" -Tag $Tag -Settle $Settle @all
$bb = "$root\$d\frame_00\backbuffer.bmp"
if (Test-Path $bb) {
    Add-Type -AssemblyName System.Drawing
    $i = [System.Drawing.Image]::FromFile($bb)
    $i.Save("$root\scratch\pv\$Tag.cap.png", [System.Drawing.Imaging.ImageFormat]::Png); $i.Dispose()
    "saved scratch\pv\$Tag.cap.png"
} else { "no capture for $Tag" }
