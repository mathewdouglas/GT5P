# Drive a race, warm the local shader/pipeline caches, and save frame-rate
# samples plus a window shot. Nothing derived from game data is tracked.
#   scripts/test/race.ps1 -Track HighSpeedRing -Tag warm-hsr -Seconds 60
# Pass GT5P_RESOLUTION=1080p RSX_MSAA=2 to warm those settings instead.
# -IntroShots saves the first 25 s of the grid/race transition once per second,
# before collecting fps samples (useful for checking car/track occlusion).
# -LoadingShots also records the loading list at half-second intervals.
# -PitIdleSeconds / -GridIdleSeconds delay the first Enter on those pages,
# saving a window shot every ten seconds while waiting. Use -IntroShots to
# inspect whether the subsequent race actually starts (a live title is not proof).
# -Cpu also reports per-thread CPU over the sampling window, named from the log
# (guest thread names, host thread names), in scratch/pv/<tag>.cpu.txt.
[CmdletBinding(PositionalBinding = $false)]
param([ValidateSet("HighSpeedRing", "Daytona")][string]$Track = "HighSpeedRing",
      [string]$Tag = "race", [int]$Seconds = 60, [switch]$IntroShots, [switch]$LoadingShots,
      [ValidateRange(0,3600)][int]$PitIdleSeconds = 0,
      [ValidateRange(0,3600)][int]$GridIdleSeconds = 0, [switch]$Cpu,
      [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot/milestone.ps1"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = Join-Path $root "scratch/pv"
New-Item -ItemType Directory -Force $dir | Out-Null
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
function Save-RaceWindowShot($Proc, [string]$Path) {
    $Proc.Refresh(); $h = $Proc.MainWindowHandle
    $r = New-Object RaceWindowShot+Rect
    [RaceWindowShot]::GetClientRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ([Math]::Max(16,$r.Right)), ([Math]::Max(16,$r.Bottom))
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    try { [RaceWindowShot]::PrintWindow($h, $dc, 3) | Out-Null }
    finally { $g.ReleaseHdc($dc); $g.Dispose() }
    try { $bmp.Save($Path) } finally { $bmp.Dispose() }
}
function Watch-RaceIdle($Proc, [string]$Stage, [int]$Duration) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $next = 0
    while ($watch.Elapsed.TotalSeconds -lt $Duration) {
        $Proc.Refresh()
        if ($Proc.HasExited) { throw "Game exited while idling on $Stage" }
        if ($watch.Elapsed.TotalSeconds -ge $next) {
            Save-RaceWindowShot $Proc (Join-Path $dir ("$Tag.$Stage-idle{0:D4}.png" -f $next))
            "$Stage idle $next s; $($Proc.MainWindowTitle)"
            $next += 10
        }
        Start-Sleep -Milliseconds 250
    }
    Save-RaceWindowShot $Proc (Join-Path $dir "$Tag.$Stage-idle-end.png")
}
$hold = Get-ToDaytona 10000
if ($Track -eq "HighSpeedRing") { $hold = $hold.Replace("@CourseSelectRoot+3000-3100:RIGHT,", "") }
foreach ($at in @(20000, 40000, 60000, 80000)) {
    $at += 1000 * $PitIdleSeconds
    $hold += ",@PitSceneRoot+$at-$($at+300)!DrivingOptionRoot:CROSS"
}
foreach ($at in @(5000, 15000, 25000)) {
    $hold += ",@DrivingOptionRoot+$at-$($at+300)!LoadingRoot:CROSS"
}
foreach ($at in @(5000, 10000, 20000, 40000, 60000)) {
    $at += 1000 * $GridIdleSeconds
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
    if ($PitIdleSeconds -gt 0) {
        if ((Wait-Milestone $p $tail "PitSceneRoot" 180) -lt 0) { throw "Pit page not reached" }
        Watch-RaceIdle $p "pit" ($PitIdleSeconds + 19)
    }
    if ($LoadingShots) {
        if ((Wait-Milestone $p $tail "LoadingRoot" 240) -lt 0) { throw "Race loading not reached" }
        for ($s = 0; $s -lt 16; $s++) {
            $p.Refresh()
            if ($p.HasExited) { throw "Game exited during race loading" }
            Save-RaceWindowShot $p (Join-Path $dir ("$Tag.loading{0:D2}.png" -f $s))
            Start-Sleep -Milliseconds 500
        }
    }
    if ((Wait-Milestone $p $tail "QuickArcadeRoot" 240) -lt 0) { throw "Starting grid not reached" }
    if ($GridIdleSeconds -gt 0) { Watch-RaceIdle $p "grid" ($GridIdleSeconds + 4) }
    # Allow the first Start press and camera transition before sampling.
    if ($IntroShots) {
        for ($s = 0; $s -lt 25; $s++) {
            $p.Refresh()
            if ($p.HasExited) { throw "Game exited during the race introduction" }
            Save-RaceWindowShot $p (Join-Path $dir ("$Tag.intro{0:D2}.png" -f $s))
            Start-Sleep -Seconds 1
        }
    } else { Start-Sleep -Seconds 25 }
    # Ignore navigation/idle presents: only progress during sampling counts.
    $profTail = New-LogTail "$dir/$Tag.err"
    Read-LogTail $profTail | Out-Null
    $sampleLog = ""
    $rows = @()
    if ($Cpu) {
        $cpuA = @{}; foreach ($t in (Get-Process -Id $p.Id).Threads) { $cpuA[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
        $cpuP = (Get-Process -Id $p.Id).TotalProcessorTime.TotalSeconds
    }
    for ($s = 0; $s -lt $Seconds; $s++) {
        $p.Refresh()
        if ($p.HasExited) { throw "Game exited during the race" }
        $sampleLog += Read-LogTail $profTail
        if ($p.MainWindowTitle -match 'FPS: ([\d.]+).*draws: (\d+)') {
            $rows += [pscustomobject]@{ Second = $s; Fps = [double]$Matches[1]; Draws = [int]$Matches[2] }
        }
        Start-Sleep -Seconds 1
    }
    if ($Cpu) {
        $cpuB = @{}; foreach ($t in (Get-Process -Id $p.Id).Threads) { $cpuB[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
        $cpuTotal = (Get-Process -Id $p.Id).TotalProcessorTime.TotalSeconds - $cpuP
        $hostNames = @{}; $guestNames = @{}
        foreach ($f in "$dir/$Tag.out", "$dir/$Tag.err") {
            foreach ($l in (Select-String -Path $f -Pattern 'hosttid=(\d+)|sys_ppu_thread_create tid=')) {
                if ($l.Line -match '\[THREAD (\d+)\].*hosttid=(\d+)') { $hostNames[[int]$Matches[2]] = "g" + $Matches[1] }
                elseif ($l.Line -match '\[(?:hostthread\]|pso-worker\]) ?(\S*) ?hosttid=(\d+)') { $hostNames[[int]$Matches[2]] = $(if ($Matches[1]) { $Matches[1] } else { "pso-worker" }) }
                if ($l.Line -match 'sys_ppu_thread_create tid=(\d+) name="([^"]*)"') { $guestNames["g" + $Matches[1]] = $Matches[2] }
            }
        }
        $cpuRows = foreach ($id in $cpuB.Keys) {
            $d = $cpuB[$id] - [double]$cpuA[$id]
            if ($d -gt 0.05 * $Seconds / 10) {
                $n = $hostNames[$id]; if ($n -and $guestNames[$n]) { $n = "$n $($guestNames[$n])" }
                [pscustomobject]@{ Host = $id; CpuS = [Math]::Round($d, 2); PctCore = [int](100 * $d / $Seconds); Thread = $n }
            }
        }
        $cpuReport = "process CPU {0:N1} s over $Seconds s ({1:N2} cores)`n" -f $cpuTotal, ($cpuTotal / $Seconds)
        $cpuReport += ($cpuRows | Sort-Object CpuS -Descending | Select-Object -First 24 | Format-Table -AutoSize | Out-String -Width 160)
        $cpuReport | Set-Content "$dir/$Tag.cpu.txt"
        $cpuReport
    }
    $rows | Export-Csv "$dir/$Tag.fps.csv" -NoTypeInformation
    Save-RaceWindowShot $p (Join-Path $dir "$Tag.win.png")
    $presentSamples = [regex]::Matches($sampleLog, '\[present-prof\][^\r\n]*presents=(\d+)')
    if ($presentSamples.Count -gt 0 -and
        @($presentSamples | Where-Object { [int]$_.Groups[1].Value -gt 0 }).Count -eq 0) {
        throw "No frames were presented during sampling; title FPS is stale. Inspect scratch/pv/$Tag.*"
    }
    $ordered = @($rows.Fps | Sort-Object)
    if ($ordered.Count) { "$Track`: median $($ordered[[int]($ordered.Count/2)]) fps over $Seconds s" }
    "Cache warming finished for the materials seen in this run; logs and shot: scratch/pv/$Tag.*"
} finally {
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
}
