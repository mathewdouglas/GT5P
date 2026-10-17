# Drive the title to the dealership with PAD_HOLD, then report which host
# threads used CPU over a window, mapped to guest threads from the log.
# Waits for the page by milestone (milestone.ps1), then -Settle seconds.
#   scripts\test\cpu3.ps1 [-Settle 5] [-Window 12] NAME=VALUE ...
[CmdletBinding(PositionalBinding = $false)]
param([int]$Settle = 5, [int]$Window = 12, [int]$MinDraws = 1000, [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot\milestone.ps1"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$hold = $DealerHold
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0"; PAD_HOLD = $hold }
foreach ($v in $Vars) { $k, $val = "$v" -split "=", 2; $set[$k] = $val }
Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
try {
Stop-Stragglers
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$root\scratch\cpu2.out" -RedirectStandardError "$root\scratch\cpu2.err"
$tl = New-LogTail "$root\scratch\cpu2.out"
$tp = Wait-Milestone $p $tl "DealerTopRoot" 90
if ($tp -lt 0 -or (Wait-Draws $p $MinDraws 60) -lt 0) { "page not reached"; if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }; return }
Start-Sleep -Seconds $Settle
$p.Refresh()
if ($p.HasExited) { "exited on the page"; return }
"page at $tp s; title: $($p.MainWindowTitle -replace '.*\| FPS','FPS')"
$pa = (Get-Process -Id $p.Id).TotalProcessorTime.TotalSeconds; $a = @{}; foreach ($t in (Get-Process -Id $p.Id).Threads) { $a[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
Start-Sleep -Seconds $Window
$pb = (Get-Process -Id $p.Id).TotalProcessorTime.TotalSeconds; $b = @{}; foreach ($t in (Get-Process -Id $p.Id).Threads) { $b[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
Stop-Process -Id $p.Id -Force; $live = 0; foreach ($id in $b.Keys) { $live += $b[$id] - [double]$a[$id] }; "process cpu {0:N1} s, live threads {1:N1} s, gone threads {2:N1} s over $Window s" -f ($pb - $pa), $live, ($pb - $pa - $live)
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$names = @{}
foreach ($f in "cpu2.err", "cpu2.out") {
    foreach ($l in (Select-String -Path "$root\scratch\$f" -Pattern "hosttid=(\d+)|host tid[ =](\d+)|tid=(\d+) name=")) {
        if ($l.Line -match "\[THREAD (\d+)\].*hosttid=(\d+)") { $names[[int]$Matches[2]] = "guest tid " + $Matches[1] }
        if ($l.Line -match "\[hostthread\] (\S+) hosttid=(\d+)") { $names[[int]$Matches[2]] = $Matches[1] }
    }
}
$gn = @{}
foreach ($l in (Select-String -Path "$root\scratch\cpu2.err" -Pattern 'sys_ppu_thread_create tid=(\d+) name="([^"]*)"')) {
    if ($l.Line -match 'tid=(\d+) name="([^"]*)"') { $gn["guest tid " + $Matches[1]] = $Matches[2] }
}
$rows = foreach ($id in $b.Keys) { $d = $b[$id] - [double]$a[$id]; if ($d -gt 0.05) { [pscustomobject]@{ Host = $id; Cpu = [Math]::Round($d, 2); Pct = [int](100 * $d / $Window); Who = "$($names[$id]) $($gn[$names[$id]])" } } }
$rows | Sort-Object Cpu -Descending | Select-Object -First 12 | Format-Table -AutoSize | Out-String -Width 160
} finally {
    # Close the game however this script ends (Ctrl+C, a pipeline that stops early).
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
