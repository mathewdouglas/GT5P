# Run the game under RenderDoc and have it capture the frame RSX_CAP picks
# (RSX_RDOC=1 in the backend). Writes scratch\rdoc\<tag>_frameN.rdc.
#   scripts\test\rdcap.ps1 -Tag pit [-Hold "<PAD_HOLD>"] [-Min 1800] [-Timeout 240] NAME=VALUE ...
#   -Exe gt5.exe: another executable in build\. -Gt5Race: Gran Turismo 5's
#   race route ($GT5RaceHold with its milestone files), capturing -After ms
#   after RaceStart (default 15000).
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "cap", [string]$Hold = "", [int]$Min = 1800, [int]$Timeout = 240,
      [string]$Exe = "gt5p.exe", [switch]$Gt5Race, [int]$After = 15000,
      [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot\milestone.ps1"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$rdc = if ($env:RENDERDOC_CMD) { $env:RENDERDOC_CMD } else { "C:\Program Files\RenderDoc\renderdoccmd.exe" }
New-Item -ItemType Directory -Force "$root\scratch\rdoc" | Out-Null
$before = @(Get-ChildItem "$root\scratch\rdoc\$Tag*.rdc" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0"; GT5P_PROFVIEW = "0";
          RSX_CAP = "200:1:1"; RSX_CAP_MIN = "$Min"; RSX_CAP_DIR = "scratch/pv/cap_rd_$Tag"; RSX_RDOC = "1" }
if ($Hold) { $set.PAD_HOLD = $Hold }
if ($Gt5Race) {
    $Exe = "gt5.exe"; $set.PAD_HOLD = $GT5RaceHold; $set.PAD_MILESTONE_FILES = $GT5MilestoneFiles
    $set.RSX_CAP = "1"; $set.RSX_CAP_MIN = "0"; $set.RSX_CAP_AFTER = "RaceStart,$After"
    if ($Timeout -lt 360) { $Timeout = 360 }
}
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
try {
    Stop-Stragglers
    foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
    $p = Start-Process -FilePath $rdc -ArgumentList @("capture", "-d", $root, "-c", "$root\scratch\rdoc\$Tag", "$root\build\$Exe") `
        -PassThru -RedirectStandardOutput "$root\scratch\pv\rd_$Tag.out" -RedirectStandardError "$root\scratch\pv\rd_$Tag.err"
    foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    $sw = [Diagnostics.Stopwatch]::StartNew(); $f = $null
    while ($sw.Elapsed.TotalSeconds -lt $Timeout -and -not $f) {
        Start-Sleep -Seconds 3
        $f = Get-ChildItem "$root\scratch\rdoc\$Tag*.rdc" -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.FullName } | Select-Object -First 1
    }
    if ($f) { Start-Sleep -Seconds 8; "capture $($f.FullName) after $([int]$sw.Elapsed.TotalSeconds) s" } else { "no capture in $Timeout s" }
} finally {
    Get-Process gt5p, gt5, renderdoccmd -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Get-Content "$root\scratch\pv\rd_$Tag.out" -ErrorAction SilentlyContinue | Select-String '\[milestone\] (TopMenuTemplate|CourseSelectRoot|PitSceneRoot|DealerTopRoot|MusicDecode|RaceStart)' | ForEach-Object { $_.Line }
Get-Content "$root\scratch\pv\rd_$Tag.err" -ErrorAction SilentlyContinue | Select-String '\[rdoc\]' | ForEach-Object { $_.Line }
