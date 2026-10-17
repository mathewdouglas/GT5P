# Drive a race, warm the local shader/pipeline caches, and save frame-rate
# samples plus a window shot. Nothing derived from game data is tracked.
#   scripts/test/race.ps1 -Track HighSpeedRing -Tag warm-hsr -Seconds 60
# Pass GT5P_RESOLUTION=1080p RSX_MSAA=2 to warm those settings instead.
[CmdletBinding(PositionalBinding = $false)]
param([ValidateSet("HighSpeedRing", "Daytona")][string]$Track = "HighSpeedRing",
      [string]$Tag = "race", [int]$Seconds = 60,
      [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot/milestone.ps1"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = Join-Path $root "scratch/pv"
New-Item -ItemType Directory -Force $dir | Out-Null
$hold = Get-ToDaytona 10000
if ($Track -eq "HighSpeedRing") { $hold = $hold.Replace("@CourseSelectRoot+3000-3100:RIGHT,", "") }
foreach ($at in @(20000, 40000, 60000, 80000)) {
    $hold += ",@PitSceneRoot+$at-$($at+300)!DrivingOptionRoot:CROSS"
}
foreach ($at in @(5000, 15000, 25000)) {
    $hold += ",@DrivingOptionRoot+$at-$($at+300)!LoadingRoot:CROSS"
}
foreach ($at in @(5000, 10000, 20000, 40000, 60000)) {
    $hold += ",@QuickArcadeRoot+$at-$($at+300):CROSS"
}
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0";
          GT5P_PROFVIEW = "0"; PAD_HOLD = $hold; GT5P_RESOLUTION = "720p";
          RSX_MSAA = "2"; GT5P_PRESENT_PROF = "1"; RSX_PSO_TIMING = "1" }
foreach ($v in $Vars) { if ($v) { $k, $val = "$v" -split "=", 2; $set[$k] = $val } }
try {
    Stop-Stragglers
    foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
    $p = Start-Process -FilePath "$root/build/gt5p.exe" -WorkingDirectory $root -PassThru `
        -RedirectStandardOutput "$dir/$Tag.out" -RedirectStandardError "$dir/$Tag.err"
    foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    $tail = New-LogTail "$dir/$Tag.out"
    if ((Wait-Milestone $p $tail "QuickArcadeRoot" 240) -lt 0) { throw "Starting grid not reached" }
    # Allow the first Start press and camera transition before sampling.
    Start-Sleep -Seconds 25
    $rows = @()
    for ($s = 0; $s -lt $Seconds; $s++) {
        $p.Refresh()
        if ($p.HasExited) { throw "Game exited during the race" }
        if ($p.MainWindowTitle -match 'FPS: ([\d.]+).*draws: (\d+)') {
            $rows += [pscustomobject]@{ Second = $s; Fps = [double]$Matches[1]; Draws = [int]$Matches[2] }
        }
        Start-Sleep -Seconds 1
    }
    $rows | Export-Csv "$dir/$Tag.fps.csv" -NoTypeInformation
    Add-Type -AssemblyName System.Drawing
    if (-not ("RaceWindowShot" -as [type])) {
        Add-Type @'
using System; using System.Runtime.InteropServices;
public class RaceWindowShot {
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out Rect r);
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left,Top,Right,Bottom; }
}
'@
    }
    $p.Refresh(); $h = $p.MainWindowHandle
    $r = New-Object RaceWindowShot+Rect
    [RaceWindowShot]::GetClientRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ([Math]::Max(16,$r.Right)), ([Math]::Max(16,$r.Bottom))
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    try { [RaceWindowShot]::PrintWindow($h, $dc, 3) | Out-Null }
    finally { $g.ReleaseHdc($dc); $g.Dispose() }
    $bmp.Save("$dir/$Tag.win.png"); $bmp.Dispose()
    $ordered = @($rows.Fps | Sort-Object)
    if ($ordered.Count) { "$Track`: median $($ordered[[int]($ordered.Count/2)]) fps over $Seconds s" }
    "Cache warming finished for the materials seen in this run; logs and shot: scratch/pv/$Tag.*"
} finally {
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
}
