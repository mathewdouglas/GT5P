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
# -RaceShots <n> saves a window shot every n seconds of sampling; the file
# times against the HUD race timer show whether game time keeps up with real
# time (the title advances its clock per frame, so a slow frame rate is slow motion).
# -FrameTest is the standard frame-time test: it starts sampling 45 s after
# the grid appears (past the rolling start, which the title runs at 30 FPS),
# samples 60 s with a shot every 20 s, and writes scratch/pv/<tag>.frames.txt:
# frames, mean FPS, median/p99/max frame interval, the share of frames later
# than 20 ms (one vblank missed), and the FIFO walk's wall and CPU ms per
# frame (from GT5P_FRAME_LOG). -SampleDelay <s> moves the start.
# -ExtraHold "<PAD_HOLD entries>" appends presses to the drive (e.g.
# "@QuickArcadeRoot+75000-75200:START").
# -Engine/-GameRoot/-OutputDirectory support isolated audit runs. Another game
# makes launch fail; cleanup stops only this script's own process.
# -Cpu also reports per-thread CPU over the sampling window, named from the log
# (guest thread names, host thread names), in scratch/pv/<tag>.cpu.txt.
[CmdletBinding(PositionalBinding = $false)]
param([ValidateSet("HighSpeedRing", "Daytona")][string]$Track = "HighSpeedRing",
      [string]$Tag = "race", [int]$Seconds = 60, [switch]$IntroShots, [switch]$LoadingShots,
      [ValidateRange(0,3600)][int]$PitIdleSeconds = 0,
      [ValidateRange(0,3600)][int]$GridIdleSeconds = 0, [switch]$Cpu,
      [ValidateRange(0,3600)][int]$RaceShots = 0, [switch]$FrameTest,
      [ValidateRange(0,3600)][int]$SampleDelay = 25,
      [string]$Engine = "", [string]$GameRoot = "", [string]$OutputDirectory = "",
      [switch]$PlayerLauncher,
      [switch]$NoPrepared,
      [string]$ExtraHold = "",
      [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot/milestone.ps1"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root "scratch/pv" }
if (-not $Engine) { $Engine = Join-Path $root "build/gt5p.exe" }
if (-not $GameRoot) { $GameRoot = $root }
$Engine = [IO.Path]::GetFullPath($Engine)
$GameRoot = [IO.Path]::GetFullPath($GameRoot)
New-Item -ItemType Directory -Force $dir | Out-Null
Add-Type -AssemblyName System.Drawing
if (-not ("RaceWindowShot" -as [type])) {
    Add-Type @'
using System; using System.Runtime.InteropServices;
public class RaceWindowShot {
 public delegate bool EnumCallback(IntPtr h,IntPtr data);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumCallback callback,IntPtr data);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,System.Text.StringBuilder text,int count);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int how);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 public static IntPtr GameWindow(int pid) {
  IntPtr result=IntPtr.Zero;
  EnumWindows((h,data)=>{uint owner;GetWindowThreadProcessId(h,out owner);
   var text=new System.Text.StringBuilder(512);GetWindowText(h,text,512);
   if(owner==pid && (text.ToString().Contains("Gran Turismo") || text.ToString().Contains("Project Tourline Prologue"))){result=h;return false;}return true;},IntPtr.Zero);
  return result;
 }
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
if ($ExtraHold) { $hold += ",$ExtraHold" }
if ($FrameTest) {
    if (-not $PSBoundParameters.ContainsKey("SampleDelay")) { $SampleDelay = 45 }
    if (-not $PSBoundParameters.ContainsKey("Seconds")) { $Seconds = 60 }
    if (-not $PSBoundParameters.ContainsKey("RaceShots")) { $RaceShots = 20 }
}
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0";
          GT5P_PROFVIEW = "0"; PAD_HOLD = $hold; GT5P_RESOLUTION = "720p";
          RSX_MSAA = "2"; GT5P_PRESENT_PROF = "1"; RSX_PSO_TIMING = "1" }
$set['GT5P_ROOT'] = $GameRoot
if ($FrameTest) { $set["GT5P_FRAME_LOG"] = (Join-Path $dir "$Tag.frames.csv") }
foreach ($v in $Vars) { if ($v) { $k, $val = "$v" -split "=", 2; $set[$k] = $val } }
$p = $null
$launcherOwner = $null
$gameOut = "$dir/$Tag.out"
$gameErr = "$dir/$Tag.err"
try {
    if (@(Get-Process gt5p -ErrorAction SilentlyContinue).Count) { throw "Another gt5p.exe is running; no process was stopped" }
    foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
    $launchMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $launch = @{FilePath=$Engine;WorkingDirectory=$GameRoot;PassThru=$true;WindowStyle='Hidden';
                RedirectStandardOutput="$dir/$Tag.out";RedirectStandardError="$dir/$Tag.err"}
    if ($NoPrepared) {
        if (-not $PlayerLauncher) { throw '-NoPrepared requires -PlayerLauncher' }
        $launch.ArgumentList = '--no-prepared'
    }
    $p = Start-Process @launch
    if ($PlayerLauncher) {
        $launcherOwner = $p
        $p = $null
        $expectedGame = [IO.Path]::GetFullPath((Join-Path (Split-Path $Engine -Parent) 'runtime/gt5p.exe'))
        $childWait = [Diagnostics.Stopwatch]::StartNew()
        while (-not $p -and $childWait.Elapsed.TotalSeconds -lt 30) {
            $owned = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($launcherOwner.Id)" |
                Where-Object { $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath) -eq $expectedGame })
            if ($owned.Count -eq 1) { $p = Get-Process -Id $owned[0].ProcessId }
            else { Start-Sleep -Milliseconds 100 }
        }
        if (-not $p) { throw 'Player launcher did not create its expected owned game child' }
        $gameOut = Join-Path $GameRoot 'logs/play.out'
        $gameErr = Join-Path $GameRoot 'logs/play.err'
    }
    # Keep the console hidden, but show the owned game window for representative
    # presentation timing and visual validation. Never touch another process.
    $windowWait = [Diagnostics.Stopwatch]::StartNew()
    $gameWindow = [IntPtr]::Zero
    while ($gameWindow -eq [IntPtr]::Zero -and $windowWait.Elapsed.TotalSeconds -lt 20) {
        $gameWindow = [RaceWindowShot]::GameWindow($p.Id)
        if ($gameWindow -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 100 }
    }
    if ($gameWindow -eq [IntPtr]::Zero) { throw "Owned game window was not created" }
    [RaceWindowShot]::ShowWindow($gameWindow,5) | Out-Null
    [RaceWindowShot]::SetForegroundWindow($gameWindow) | Out-Null
    foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    $tail = New-LogTail $gameOut
    if ($PlayerLauncher) {
        if ((Wait-Milestone $p $tail 'TopMenuTemplate' 180) -lt 0) { throw 'Player menu not reached' }
        Start-Sleep -Seconds 2
        Save-RaceWindowShot $p (Join-Path $dir "$Tag.menu.png")
    }
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
    $gridMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if ($GridIdleSeconds -gt 0) { Watch-RaceIdle $p "grid" ($GridIdleSeconds + 4) }
    # Allow the first Start press and camera transition before sampling.
    if ($IntroShots) {
        for ($s = 0; $s -lt 25; $s++) {
            $p.Refresh()
            if ($p.HasExited) { throw "Game exited during the race introduction" }
            Save-RaceWindowShot $p (Join-Path $dir ("$Tag.intro{0:D2}.png" -f $s))
            Start-Sleep -Seconds 1
        }
        if ($SampleDelay -gt 25) { Start-Sleep -Seconds ($SampleDelay - 25) }
    } else { Start-Sleep -Seconds $SampleDelay }
    # Ignore navigation/idle presents: only progress during sampling counts.
    $profTail = New-LogTail $gameErr
    Read-LogTail $profTail | Out-Null
    $sampleLog = ""
    $tS0 = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $rows = @()
    $memoryRows = @()
    if ($Cpu) {
        $cpuA = @{}; foreach ($t in (Get-Process -Id $p.Id).Threads) { $cpuA[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
        $cpuP = (Get-Process -Id $p.Id).TotalProcessorTime.TotalSeconds
    }
    for ($s = 0; $s -lt $Seconds; $s++) {
        $p.Refresh()
        if ($p.HasExited) { throw "Game exited during the race" }
        $sampleLog += Read-LogTail $profTail
        $memoryRows += [pscustomobject]@{ Second=$s; WorkingSet=$p.WorkingSet64; PrivateBytes=$p.PrivateMemorySize64; PeakWorkingSet=$p.PeakWorkingSet64 }
        if ($RaceShots -gt 0 -and ($s % $RaceShots) -eq 0) {
            Save-RaceWindowShot $p (Join-Path $dir ("$Tag.race{0:D3}.png" -f $s))
        }
        if ($p.MainWindowTitle -match 'FPS: ([\d.]+).*draws: (\d+)') {
            $rows += [pscustomobject]@{ Second = $s; Fps = [double]$Matches[1]; Draws = [int]$Matches[2] }
        }
        Start-Sleep -Seconds 1
    }
    if ($Cpu) {
        $cpuB = @{}; foreach ($t in (Get-Process -Id $p.Id).Threads) { $cpuB[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
        $cpuTotal = (Get-Process -Id $p.Id).TotalProcessorTime.TotalSeconds - $cpuP
        $hostNames = @{}; $guestNames = @{}
        foreach ($f in $gameOut, $gameErr) {
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
    $tS1 = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    @{ launch_ms = $launchMs; grid_observed_ms = $gridMs; sample_start_ms = $tS0;
       sample_end_ms = $tS1; engine = $Engine; game_root = $GameRoot; pid = $p.Id;
       track = $Track; seconds = $Seconds; sample_delay = $SampleDelay } |
        ConvertTo-Json | Set-Content (Join-Path $dir "$Tag.window.json")
    $rows | Export-Csv "$dir/$Tag.fps.csv" -NoTypeInformation
    $memoryRows | Export-Csv "$dir/$Tag.memory.csv" -NoTypeInformation
    if ($FrameTest) {
        Start-Sleep -Milliseconds 1500   # the log is flushed every 30 frames
        $fr = @(Get-Content (Join-Path $dir "$Tag.frames.csv") | ForEach-Object {
            $c = $_ -split ","; if ($c.Count -eq 3) { ,([double[]]$c) } } | Where-Object { $_[0] -ge $tS0 -and $_[0] -le $tS1 })
        $iv = @(); for ($i = 1; $i -lt $fr.Count; $i++) { $iv += $fr[$i][0] - $fr[$i - 1][0] }
        if ($iv.Count -gt 10) {
            $sorted = $iv | Sort-Object
            $pct = { param($q) $sorted[[Math]::Min($sorted.Count - 1, [int]($q * $sorted.Count))] }
            $late = @($iv | Where-Object { $_ -gt 20 }).Count
            $walk = ($fr | ForEach-Object { $_[1] } | Measure-Object -Average).Average
            $walkCpu = ($fr | ForEach-Object { $_[2] } | Measure-Object -Average).Average
            $span = ($fr[-1][0] - $fr[0][0]) / 1000.0
            $txt = "frames {0} over {1:N1} s: {2:N1} FPS; interval median {3:N1} ms, p99 {4:N1} ms, max {5:N1} ms; late (>20 ms) {6:N1}%; walk {7:N2} ms/frame (cpu {8:N2})" -f `
                $fr.Count, $span, (($fr.Count - 1) / $span), (& $pct 0.5), (& $pct 0.99), $sorted[-1], (100.0 * $late / $iv.Count), $walk, $walkCpu
            $txt | Set-Content (Join-Path $dir "$Tag.frames.txt")
            "FrameTest: $txt"
        } else { "FrameTest: too few frames in the sampling window ($($fr.Count))" }
    }
    Save-RaceWindowShot $p (Join-Path $dir "$Tag.win.png")
    $presentSamples = [regex]::Matches($sampleLog, '\[present-prof\][^\r\n]*presents=(\d+)')
    if ($presentSamples.Count -gt 0 -and
        @($presentSamples | Where-Object { [int]$_.Groups[1].Value -gt 0 }).Count -eq 0) {
        throw "No frames were presented during sampling; title FPS is stale. Inspect scratch/pv/$Tag.*"
    }
    $ordered = @($rows.Fps | Sort-Object)
    if ($ordered.Count) { "$Track`: median $($ordered[[int]($ordered.Count/2)]) fps over $Seconds s" }
    "Cache warming finished for the materials seen in this run; logs and shot: $dir/$Tag.*"
} finally {
    if ($launcherOwner) {
        $launcherOwner.Refresh()
        if (-not $launcherOwner.HasExited) { $launcherOwner.Kill(); $launcherOwner.WaitForExit(10000) | Out-Null }
    }
    if ($p) { $p.Refresh(); if (-not $p.HasExited) { $p.Kill(); $p.WaitForExit(10000) | Out-Null } }
    if ($PlayerLauncher) {
        if (Test-Path $gameOut) { Copy-Item -LiteralPath $gameOut -Destination "$dir/$Tag.out" }
        if (Test-Path $gameErr) { Copy-Item -LiteralPath $gameErr -Destination "$dir/$Tag.err" }
    }
    foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
}
