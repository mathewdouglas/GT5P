# Drive to the Car Dealer page and keep it there -Settle seconds after it is
# drawn (milestone.ps1), for a capture switch such as RSX_CAP to act in. It
# takes no screenshot itself: desktop grabs can show other windows.
#   scripts\test\pvshot.ps1 -Tag t [-Settle 25] NAME=VALUE ...
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "shot", [int]$Settle = 25,
      [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot\milestone.ps1"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = "$root\scratch\pv"; New-Item -ItemType Directory -Force $dir | Out-Null
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0"; PAD_HOLD = $DealerHold; GT5P_PROFVIEW = "1" }
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
try {
Stop-Stragglers
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\$Tag.out" -RedirectStandardError "$dir\$Tag.err"
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$tl = New-LogTail "$dir\$Tag.out"
$tp = Wait-Milestone $p $tl "DealerTopRoot" 90
if ($tp -lt 0 -or (Wait-Draws $p 1000 60) -lt 0) { "page not reached" }
else {
    Start-Sleep -Seconds $Settle
    $p.Refresh(); "page at $tp s; title: $($p.MainWindowTitle)"
}
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
} finally {
    # Close the game however this script ends (Ctrl+C, a pipeline that stops early).
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
