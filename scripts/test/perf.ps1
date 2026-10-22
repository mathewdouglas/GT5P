# Phase 43 measurement, repeated: drive to the Car Dealer page, wait until it
# is drawn, then read the title-bar fps and CPU over -Window seconds (process
# total, live threads, threads that exited). Prints each run and the median,
# plus the top threads of the median run.
#
# Runs follow milestones, not fixed times (milestone.ps1): the page counts as
# reached when the title reads DealerTopRoot.gpb and the title bar shows over
# -MinDraws (1000; 0 with RSX_VTX_SKIP=1) draws; measuring starts -Settle seconds later. A run whose presents stop
# for a 5 s block is a stall: it ends there and is counted. -Watch <s> keeps
# watching the page for a stall that long after the window (stall testing).
#   scripts\test\perf.ps1 -Tag base [-N 3] [-Window 15] [-Settle 5] [-Watch 0]
#                    [-MaxBoot 90] [-Exe path] [-Hold <PAD_HOLD>] NAME=VALUE ...
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "run", [int]$N = 3, [int]$Window = 15, [int]$Settle = 5, [int]$Watch = 0,
      [int]$MaxBoot = 90, [string]$Exe = "", [string]$Hold = "", [string]$Page = "DealerTopRoot", [int]$MinDraws = 1000, [switch]$Ferrari,
      [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot\milestone.ps1"
Add-Type -AssemblyName System.Drawing
if (-not ("WinShot" -as [type])) {
Add-Type @'
using System; using System.Runtime.InteropServices;
public class WinShot { [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; } }
'@ }
function Save-WinShot($p, $name) {
    $p.Refresh(); $h = $p.MainWindowHandle
    $r = New-Object WinShot+RECT; [WinShot]::GetClientRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R, 16)), ([Math]::Max($r.B, 16))
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    [WinShot]::PrintWindow($h, $dc, 3) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
    $bmp.Save($name); $bmp.Dispose()
}
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $Exe) { $Exe = "$root\build\gt5p.exe" }
if (-not $Hold) { $Hold = if ($Ferrari) { $FerrariHold } else { $DealerHold } }
$dir = "$root\scratch\perf\$Tag"; New-Item -ItemType Directory -Force $dir | Out-Null

# Reads the stderr tail for $Sec seconds; returns the present counts of the
# present-prof blocks seen, and whether one was 0 (then it returns at once).
function Watch-Presents($Proc, $Tail, [double]$Sec) {
    $counts = @(); $stalled = $false
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $Sec) {
        $s = Read-LogTail $Tail; $Tail.Text = ""
        foreach ($m in [regex]::Matches($s, 'present-prof\] 5 s: ticks=\d+ presents=(\d+) \|')) {
            $c = [int]$m.Groups[1].Value; $counts += $c
            if ($c -eq 0) { $stalled = $true }
        }
        if ($stalled) { break }
        $Proc.Refresh(); if ($Proc.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    [pscustomobject]@{ Counts = $counts; Stalled = $stalled }
}

try {
$results = @(); $stalls = 0; $total = [Diagnostics.Stopwatch]::StartNew()
for ($i = 1; $i -le $N; $i++) {
    $set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0"; PAD_HOLD = $Hold; GT5P_PRESENT_PROF = "1" }
    foreach ($v in $Vars) { $k, $val = "$v" -split "=", 2; $set[$k] = $val }
    Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
    foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
    Stop-Stragglers
    $p = Start-Process -FilePath $Exe -WorkingDirectory $root -PassThru `
        -RedirectStandardOutput "$dir\run$i.out" -RedirectStandardError "$dir\run$i.err"
    foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    $to = New-LogTail "$dir\run$i.out"; $te = New-LogTail "$dir\run$i.err"
    $tPage = Wait-Milestone $p $to $Page $MaxBoot
    $tDraw = if ($tPage -ge 0) { Wait-Draws $p $MinDraws 60 } else { -1 }
    if ($tPage -lt 0 -or $tDraw -lt 0) {
        "run {0}: page not reached ({1} {2} s, drawn {3} s)" -f $i, $Page, $tPage, $tDraw
        if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }; Start-Sleep -Seconds 2; continue
    }
    Read-LogTail $te | Out-Null; $te.Text = ""          # only blocks from here on count
    $w0 = Watch-Presents $p $te $Settle
    $title = ""; $pa = 0; $a = @{}; $w1 = $null; $w2 = $null
    if (-not $w0.Stalled -and -not $p.HasExited) {
        $p.Refresh(); $title = $p.MainWindowTitle
        $proc = Get-Process -Id $p.Id
        $pa = $proc.TotalProcessorTime.TotalSeconds
        foreach ($t in $proc.Threads) { $a[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
        $ws = [Diagnostics.Stopwatch]::StartNew()
        $w1 = Watch-Presents $p $te $Window
        $span = $ws.Elapsed.TotalSeconds
        $proc = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    }
    $stalled = $w0.Stalled -or ($w1 -and $w1.Stalled)
    $pb = 0; $b = @{}; $title2 = ""
    if ($w1 -and $proc) {
        $pb = $proc.TotalProcessorTime.TotalSeconds
        foreach ($t in $proc.Threads) { $b[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
        $title2 = $proc.MainWindowTitle
        if (-not $stalled -and $Watch -gt 0) { $w2 = Watch-Presents $p $te $Watch; $stalled = $w2.Stalled }
    }
    # A window shot of the page as measured: which cars a dealer shows changes per visit.
    if (-not $p.HasExited) { try { Save-WinShot $p "$dir\run$i.png" } catch {} }
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
    Start-Sleep -Seconds 2
    if ($stalled) { $stalls++ }
    $live = 0; foreach ($id in $b.Keys) { if ($a.ContainsKey($id)) { $live += $b[$id] - $a[$id] } else { $live += $b[$id] } }
    $win = if ($w1) { [Math]::Max($span, 1) } else { 1 }
    $pp = if ($w1) { @($w1.Counts) } else { @() }
    $avg = if ($pp.Count) { [Math]::Round(($pp | Measure-Object -Sum).Sum / (5.0 * $pp.Count), 2) } else { 0 }
    $fps = if ($title -match 'FPS: ([\d.]+)') { [double]$Matches[1] } else { 0 }
    $fps2 = if ($title2 -match 'FPS: ([\d.]+)') { [double]$Matches[1] } else { 0 }
    $draws = if ($title -match 'draws: (\d+)') { [int]$Matches[1] } else { 0 }
    $names = @{}
    foreach ($l in (Select-String -Path "$dir\run$i.err", "$dir\run$i.out" -Pattern "hosttid=(\d+)")) {
        if ($l.Line -match "\[THREAD (\d+)\].*hosttid=(\d+)") { $names[[int]$Matches[2]] = "guest tid " + $Matches[1] }
        if ($l.Line -match "\[hostthread\] (\S+) hosttid=(\d+)") { $names[[int]$Matches[2]] = $Matches[1] }
    }
    $gn = @{}
    foreach ($l in (Select-String -Path "$dir\run$i.err" -Pattern 'sys_ppu_thread_create tid=(\d+) name="([^"]*)"')) {
        if ($l.Line -match 'tid=(\d+) name="([^"]*)"') { $gn["guest tid " + $Matches[1]] = $Matches[2] }
    }
    $rows = foreach ($id in $b.Keys) { $d = $b[$id] - [double]$a[$id]; if ($d -gt 0.3) {
        $w = "$($names[[int]$id])"; $w2n = if ($gn.ContainsKey($w)) { $gn[$w] } else { "" }
        "{0,4}% {1} {2}" -f [int](100 * $d / $win), $w, $w2n } }
    $r = [pscustomobject]@{ Run = $i; Avg = $avg; Fps = $fps; FpsEnd = $fps2; Draws = $draws; Stalled = $stalled
        PageSec = $tPage; DrawnSec = $tDraw
        ProcCores = [Math]::Round(($pb - $pa) / $win, 2); GoneCores = [Math]::Round(($pb - $pa - $live) / $win, 2)
        Top = (($rows | Sort-Object -Descending | Select-Object -First 6) -join " | ") }
    if ($stalled) { $r.Avg = 0 }
    $results += $r
    "run {0}: {8}avg {6} fps over the window ({7} x 5 s) | page at {9} s, drawn +{10} s | title {1} -> {2} draws {3} | process {4} cores, exited threads {5} cores" -f `
        $i, $fps, $fps2, $draws, $r.ProcCores, $r.GoneCores, $avg, $pp.Count, $(if ($stalled) { "STALLED | " } else { "" }), $tPage, $tDraw
}
$ok = $results | Where-Object { -not $_.Stalled -and $_.Draws -ge $MinDraws }
"[$Tag] {0} of {1} runs stalled; {2:N0} s in all" -f $stalls, $results.Count, $total.Elapsed.TotalSeconds
if ($ok) {
    $s = @($ok | Sort-Object Avg)
    $med = $s[[int][Math]::Floor(($s.Count - 1) / 2)]
    "[$Tag] median {0} fps (window average) over {1} runs (all: {2}); median run threads: {3}" -f $med.Avg, $s.Count, (($results | ForEach-Object { $_.Avg }) -join ", "), $med.Top
} else { "[$Tag] no run reached the page without stalling" }
$results | Export-Csv "$dir\results.csv" -NoTypeInformation
} finally {
    # Close the game however this script ends (Ctrl+C, a pipeline that stops early).
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
