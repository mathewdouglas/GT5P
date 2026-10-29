# Gran Turismo 5: boot to the main menu with milestone-timed presses
# (milestone.ps1, $GT5BootHold), idle there -Settle seconds with a window shot
# every -Gap seconds, and summarise the frame rate.
#   scripts\test\gt5boot.ps1 -Tag t [-Settle 60] [-Gap 10] [-Fresh] [-FreshSave] NAME=VALUE ...
#   -Fresh: first-boot install state (scripts\test\gt5_reset.py), so the
#   install prompts run; -FreshSave also removes the save (GT5 creates it).
#   -Movie: no presses; shots start at installed00.dat instead of the menu,
#   so they cover the logos and the opening movie of an installed boot.
#   -Route carlist|grid|race: drive on to the car list ($GT5CarListHold), the
#   race's grid screen ($GT5GridHold) or into the race ($GT5RaceHold); a
#   PAD_HOLD=... argument still overrides.
#   -ShotsFrom <milestone>: start the shots there instead (grid: RaceLoad,
#   race: RaceStart).
#   -FrameTest (with -Route race): hold Cross (throttle) from RaceStart, log
#   every presented frame (GT5P_FRAME_LOG) and report frames, mean FPS,
#   median/p99/max interval, late (>20 ms) share and FIFO walk ms/frame over
#   the -Settle window after -SampleDelay s (default 20), to
#   scratch\pv\<t>.frames.txt. -Cpu adds per-thread CPU over the window.
#   Each screen milestone reached is printed with its time after the menu.
#   -> scratch\pv\<t>.out/.err, <t>.menu<N>.png
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "gt5", [int]$Settle = 60, [int]$Gap = 10, [switch]$Fresh, [switch]$FreshSave, [switch]$Movie,
      [ValidateSet("menu", "carlist", "grid", "race")][string]$Route = "menu", [string]$ShotsFrom = "",
      [switch]$FrameTest, [int]$SampleDelay = 20, [switch]$Cpu,
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
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = "$root\scratch\pv"; New-Item -ItemType Directory -Force $dir | Out-Null
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0"; GT5P_PROFVIEW = "0";
          PAD_MILESTONE_FILES = $GT5MilestoneFiles; PAD_HOLD = $GT5BootHold }
if ($Route -eq "carlist") { $set.PAD_HOLD = $GT5CarListHold }
if ($Route -eq "grid") { $set.PAD_HOLD = $GT5GridHold; if (-not $ShotsFrom) { $ShotsFrom = "RaceLoad" } }
if ($Route -eq "race") { $set.PAD_HOLD = $GT5RaceHold; if (-not $ShotsFrom) { $ShotsFrom = "RaceStart" } }
if ($Movie) { $set.Remove("PAD_HOLD") }
if ($FrameTest) { $set.GT5P_FRAME_LOG = "$dir\$Tag.frames.csv"; $set.PAD_HOLD += ",@RaceStart+1000-900000:CROSS" }
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
function Stop-GT5 { Get-Process gt5 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue }
try {
Stop-Stragglers; Stop-GT5
if ($Fresh -or $FreshSave) {
    $a = @("$PSScriptRoot\gt5_reset.py"); if ($FreshSave) { $a += "--save" }
    & "$root\.venv\Scripts\python.exe" @a
}
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
$p = Start-Process -FilePath "$root\build\gt5.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\$Tag.out" -RedirectStandardError "$dir\$Tag.err"
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$tl = New-LogTail "$dir\$Tag.out"
$limit = if ($Fresh -or $FreshSave) { 600 } else { 240 }
$ms = if ($Movie) { "installed00.dat" } else { "MusicDecode" }
$tm = Wait-Milestone $p $tl $ms $limit
if ($tm -lt 0) { "$ms not reached (log: $dir\$Tag.out)" }
elseif ($ShotsFrom -and ($t2 = Wait-Milestone $p $tl $ShotsFrom $limit) -lt 0) { "$ShotsFrom not reached (log: $dir\$Tag.out)" }
else {
    "$ms at $tm s"; if ($ShotsFrom) { "$ShotsFrom $t2 s after that" }
    if ($FrameTest) { Start-Sleep -Seconds $SampleDelay }
    $tS0 = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if ($Cpu) { $p.Refresh(); $cpu0 = $p.TotalProcessorTime.TotalSeconds; $thr0 = @{}; foreach ($t in $p.Threads) { $thr0[$t.Id] = $t.TotalProcessorTime.TotalSeconds } }
    $sw = [Diagnostics.Stopwatch]::StartNew(); $i = 0
    while ($sw.Elapsed.TotalSeconds -lt $Settle) {
        Start-Sleep -Seconds $Gap; $i++
        $p.Refresh(); if ($p.HasExited) { "exited"; break }
        $h = $p.MainWindowHandle; if ($h -eq 0) { continue }
        $r = New-Object WinShot+RECT; [WinShot]::GetClientRect($h, [ref]$r) | Out-Null
        $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R, 16)), ([Math]::Max($r.B, 16))
        $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
        [WinShot]::PrintWindow($h, $dc, 3) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
        $bmp.Save("$dir\$Tag.menu$i.png"); $bmp.Dispose()
    }
    $tS1 = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if ($Cpu -and -not $p.HasExited) {
        $p.Refresh(); $span = ($tS1 - $tS0) / 1000.0
        $rows = foreach ($t in $p.Threads) { $d = $t.TotalProcessorTime.TotalSeconds - [double]$thr0[$t.Id]
            if ($d -gt 0.02 * $span) { [pscustomobject]@{ Tid = $t.Id; PctCore = [int](100 * $d / $span) } } }
        $rep = "process {0:N2} cores over {1:N0} s`n" -f (($p.TotalProcessorTime.TotalSeconds - $cpu0) / $span), $span
        $rep += ($rows | Sort-Object PctCore -Descending | Select-Object -First 20 | Format-Table -AutoSize | Out-String)
        $rep | Set-Content "$dir\$Tag.cpu.txt"; $rep
    }
    if ($FrameTest) {
        Start-Sleep -Milliseconds 1500
        $fr = @(Get-Content "$dir\$Tag.frames.csv" | ForEach-Object {
            $c = $_ -split ","; if ($c.Count -eq 3) { ,([double[]]$c) } } | Where-Object { $_[0] -ge $tS0 -and $_[0] -le $tS1 })
        $iv = @(); for ($k = 1; $k -lt $fr.Count; $k++) { $iv += $fr[$k][0] - $fr[$k - 1][0] }
        if ($iv.Count -gt 10) {
            $sorted = $iv | Sort-Object
            $pct = { param($q) $sorted[[Math]::Min($sorted.Count - 1, [int]($q * $sorted.Count))] }
            $late = @($iv | Where-Object { $_ -gt 20 }).Count
            $walk = ($fr | ForEach-Object { $_[1] } | Measure-Object -Average).Average
            $walkCpu = ($fr | ForEach-Object { $_[2] } | Measure-Object -Average).Average
            $span = ($fr[-1][0] - $fr[0][0]) / 1000.0
            $txt = "frames {0} over {1:N1} s: {2:N1} FPS; interval median {3:N1} ms, p99 {4:N1} ms, max {5:N1} ms; late (>20 ms) {6:N1}%; walk {7:N2} ms/frame (cpu {8:N2})" -f `
                $fr.Count, $span, (($fr.Count - 1) / $span), (& $pct 0.5), (& $pct 0.99), $sorted[-1], (100.0 * $late / $iv.Count), $walk, $walkCpu
            $txt | Set-Content "$dir\$Tag.frames.txt"; "FrameTest: $txt"
        } else { "FrameTest: too few frames in the window ($($fr.Count))" }
    }
}
} finally { Stop-GT5 }
# Screen milestones, in seconds after the menu (MusicDecode).
$mt = @{}; Select-String -Path "$dir\$Tag.out" -Pattern '^\[milestone\] (\S+) at (\d+) ms' |
    ForEach-Object { $mt[$_.Matches[0].Groups[1].Value] = [int]$_.Matches[0].Groups[2].Value }
if ($mt.MusicDecode) {
    ($mt.GetEnumerator() | Where-Object { $_.Value -gt $mt.MusicDecode } | Sort-Object Value |
        ForEach-Object { "{0} +{1:N1}" -f $_.Key, (($_.Value - $mt.MusicDecode) / 1000) }) -join ", "
}
# Frames per 5 s from the present thread, oldest first.
$f = Select-String -Path "$dir\$Tag.err" -Pattern 'present-thread\] 5 s: (\d+) frames' |
     ForEach-Object { $_.Matches[0].Groups[1].Value }
"frames per 5 s: $($f -join ' ')"
