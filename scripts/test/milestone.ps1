# Dot-source from a run script: waits on what the title has reached instead of
# fixed sleeps. The exe prints "[milestone] <name> at <ms> ms" to stdout the
# first time the title reads each screen's .gpb (cellPad.c, pad_milestone_seen).
#   . "$PSScriptRoot\milestone.ps1"
#   $tail = New-LogTail "$dir\run1.out"
#   Wait-Milestone $p $tail "DealerTopRoot" 150     # -> $true when seen

# The save boots to the main menu; these presses reach the Car Dealer page.
# Each counts from the milestone named, so a slow boot does not miss them.
# Measured 2026-10-16: Cross 8 s after the menu template opens the manufacturer
# list, Cross 5 s after that list opens the Car Dealer page (about 29 s in all,
# against 47 s with the old fixed times 28/34/46 s). Each has two retries,
# skipped once the screen it opens has been read ("!<milestone>"): the first
# boot after a build can be slow enough for the menu to miss the +8 s press.
#
# Since a car was bought (2026-10-17) the menu opens on News under a
# "Confirmation" popup (shown every boot). Tabs, left to right: News TV Online
# Rankings Arcade 2P-Battle Events Garage Dealerships Replay Options Manual
# Save; the strip does not wrap. Held Right repeats about every 110 ms, too
# fast to let go on Dealerships by time, so: Circle closes the popup, Right
# held 2 s parks on Save, four Left taps reach Dealerships, Cross enters.
# The whole run is tried again 9 s later unless the manufacturer list opened.
function Get-ToDealers([int]$At) {
    $s = @(); $u = ""
    foreach ($try in 0, 1) {
        $t = $At + 9000 * $try
        if ($try) { $u = "!DealerSelectRoot" }
        $s += "@TopMenuTemplate+$t-$($t+300)$($u):CIRCLE"
        $s += "@TopMenuTemplate+$($t+1000)-$($t+3000)$($u):RIGHT"
        foreach ($k in 0..3) { $l = $t + 3300 + 350 * $k; $s += "@TopMenuTemplate+$l-$($l+100)$($u):LEFT" }
        $s += "@TopMenuTemplate+$($t+5000)-$($t+5300)$($u):CROSS"
    }
    $s -join ","
}
$ToDealers = Get-ToDealers 6000

$DealerHold = "$ToDealers,@DealerSelectRoot+5000-5300:CROSS," +
    "@DealerSelectRoot+11000-11300!DealerTopTransition:CROSS,@DealerSelectRoot+17000-17300!DealerTopTransition:CROSS"

# Reads a file that another process is still writing, returning only the text
# added since the last call.
function New-LogTail([string]$Path) { [pscustomobject]@{ Path = $Path; Pos = [int64]0; Text = "" } }
function Read-LogTail($t) {
    if (-not (Test-Path $t.Path)) { return "" }
    try {
        $fs = [IO.File]::Open($t.Path, 'Open', 'Read', 'ReadWrite')
        try {
            if ($fs.Length -le $t.Pos) { return "" }
            $fs.Seek($t.Pos, 'Begin') | Out-Null
            $buf = New-Object byte[] ($fs.Length - $t.Pos)
            $n = $fs.Read($buf, 0, $buf.Length)
            $t.Pos += $n
            $s = [Text.Encoding]::ASCII.GetString($buf, 0, $n)
            $t.Text += $s
            return $s
        } finally { $fs.Close() }
    } catch { return "" }
}

# Polls until the milestone line appears, the process exits or $TimeoutSec
# passes. Returns the seconds it took, or -1.
function Wait-Milestone($Proc, $Tail, [string]$Name, [int]$TimeoutSec = 150) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        Read-LogTail $Tail | Out-Null
        if ($Tail.Text -match "\[milestone\] $Name at") { return [Math]::Round($sw.Elapsed.TotalSeconds, 1) }
        $Proc.Refresh(); if ($Proc.HasExited) { return -1 }
        Start-Sleep -Milliseconds 500
    }
    return -1
}

# Polls the window title until "draws: N" is at least $MinDraws.
function Wait-Draws($Proc, [int]$MinDraws, [int]$TimeoutSec = 60) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        $Proc.Refresh(); if ($Proc.HasExited) { return -1 }
        if ($Proc.MainWindowTitle -match 'draws: (\d+)' -and [int]$Matches[1] -ge $MinDraws) {
            return [Math]::Round($sw.Elapsed.TotalSeconds, 1)
        }
        Start-Sleep -Milliseconds 500
    }
    return -1
}

# Before a launch: no other instance may run, or two games share the CPU and
# every number from the run is wrong. Kills leftovers (a killed run can take a
# few seconds to exit) and waits until they are gone.
function Stop-Stragglers {
    $left = @(Get-Process gt5p -ErrorAction SilentlyContinue)
    if ($left.Count) {
        "note: stopping $($left.Count) gt5p.exe still running (pid $(($left | ForEach-Object { $_.Id }) -join ', '))"
        $left | Stop-Process -Force -ErrorAction SilentlyContinue
        $sw = [Diagnostics.Stopwatch]::StartNew()
        while (@(Get-Process gt5p -ErrorAction SilentlyContinue).Count -and $sw.Elapsed.TotalSeconds -lt 20) { Start-Sleep -Milliseconds 250 }
    }
}

# Arcade (tab 5, four Right taps from News) opens Track Select; Right picks
# Daytona, Cross opens its Race Mode page (PitSceneRoot), Cross there opens
# Driving Options, Cross on OK loads the starting grid (Phase 66).
#   $DaytonaHold                       -> Race Mode page
#   "$DaytonaHold,$DaytonaRaceHold"    -> starting grid and race load
# Get-ToDaytona <ms>: the same, starting <ms> after the menu template opens
# (6000 by default). Under RenderDoc the menu compiles its shaders again and
# stops for seconds, and presses at +6 s are lost: use about 16000 there.
function Get-ToDaytona([int]$At = 6000) {
    $s = @("@TopMenuTemplate+$At-$($At+300):CIRCLE")
    foreach ($k in 0..3) { $t = $At + 1000 + 350 * $k; $s += "@TopMenuTemplate+$t-$($t+100):RIGHT" }
    $s += "@TopMenuTemplate+$($At+3100)-$($At+3400):CROSS"
    $s += "@CourseSelectRoot+3000-3100:RIGHT,@CourseSelectRoot+4500-4800:CROSS"
    $s -join ","
}
$DaytonaHold = Get-ToDaytona 6000
$DaytonaRaceHold = "@PitSceneRoot+10000-10300:CROSS,@DrivingOptionRoot+3000-3300:CROSS"
# On the starting grid the cursor rests on Start; Cross begins the race.
# "$DaytonaHold,$DaytonaRaceHold,$DaytonaStartHold" -> driving the race.
$DaytonaStartHold = "@QuickArcadeRoot+5000-5300:CROSS"

# The Ferrari page (Phase 60): row 2, fifth column of the manufacturer list.
# Scripted directions are D-pad only, one column a press.
$FerrariHold = "$ToDealers,@DealerSelectRoot+5000-5100:DOWN," +
    "@DealerSelectRoot+6500-6600:RIGHT,@DealerSelectRoot+8000-8100:RIGHT,@DealerSelectRoot+9500-9600:RIGHT," +
    "@DealerSelectRoot+11000-11100:RIGHT,@DealerSelectRoot+13000-13300:CROSS"

# Gran Turismo 5 (BCUS98114) reads hashed PDIPFS paths, so it has no .gpb
# milestones. Its run scripts set PAD_MILESTONE_FILES=installed00.dat (the
# first named file of every boot) and use two runtime milestones: "SaveData"
# (cellSaveData finished a save) and "MusicDecode" (cellMusicDecodeInitialize2,
# called as the main menu loads, on every boot).
# A first boot shows the install prompt, then "Installation complete", then
# Adjust Display Area, each taking Cross; an installed boot shows none of them.
# $GT5BootHold presses Cross 8 s after installed00.dat and every 5 s after,
# up to 300 s (the install takes about three minutes), each press skipped once
# the menu is loading -- so nothing is pressed on the menu itself. On an
# installed boot the presses fall on the logo/opening movie, which ignore them.
function Get-GT5Boot([int]$From = 8000, [int]$To = 300000, [int]$Every = 5000) {
    $s = @()
    for ($t = $From; $t -le $To; $t += $Every) { $s += "@installed00.dat+$t-$($t+300)!MusicDecode:CROSS" }
    $s -join ","
}
$GT5BootHold = Get-GT5Boot

# Screen milestones for GT5 (PAD_FILE_LOG=1 run, 2026-10-28): the first file
# each screen reads, as "<label>=<PDIPFS path tail>" (cellPad matches the tail
# of the full path, since PDIPFS base names are two characters). The
# difficulty and colour screens read no new file. gt5boot.ps1 always sets these.
$GT5MilestoneFiles = "installed00.dat,Arcade=9/HV/GE,TrackList=9/7B/M3,CarList=9/9U/4I," +
    "Transmission=5B/PF,RaceLoad=5K/E1,RaceStart=55/04"

# Arcade > Single Race > Beginner > High Speed Ring > car list > colour >
# transmission > race. The menu's icon bar shows for about 8 s after
# MusicDecode, then hides during the idle camera (a press then only brings it
# back), so Right goes at +5 s and the first Cross at +7 s.
# Every step after the icon bar is Cross
# on the default choice (Single Race, Beginner, High Speed Ring, the first
# car, its first colour, AT), so Cross every 3 s from +7 s until the race load
# starts walks the screens as fast as they take input: about 40 s from the
# menu, against 110 s for the old fixed 15 s steps. A Cross that falls in a
# screen's fade-in is ignored and the next one takes it.
# Get-GT5Route <milestone> stops pressing once that screen has been reached.
function Get-GT5Route([string]$Stop, [int]$Every = 3000, [int]$Until = 150000) {
    $s = @("$GT5BootHold", "@MusicDecode+5000-5100:RIGHT")
    for ($t = 7000; $t -le $Until; $t += $Every) { $s += "@MusicDecode+$t-$($t+200)!$($Stop):CROSS" }
    $s -join ","
}
$GT5CarListHold = Get-GT5Route "CarList"
$GT5GridHold = Get-GT5Route "RaceLoad"
# On into the race: the grid screen (track preview and starting grid) comes
# up 20-25 s after RaceLoad with Start selected, so Cross every 3 s from
# +15 s until the race's first files are read (RaceStart, about 2.5 s after
# the press that takes). The car then idles: nothing holds the throttle.
$GT5RaceHold = "$GT5GridHold," + ((0..20 | ForEach-Object { $t = 15000 + 3000 * $_
    "@RaceLoad+$t-$($t+200)!RaceStart:CROSS" }) -join ",")
