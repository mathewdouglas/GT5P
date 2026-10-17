# Launch the game (TV content visible unless -Hide) and, every second for -Secs
# seconds, check whether its window answers a message (SendMessageTimeout,
# WM_NULL, 500 ms). Prints one line per check.
#   scripts\test\winping.ps1 [-Secs 20] [-Hide] NAME=VALUE ...
[CmdletBinding(PositionalBinding = $false)]
param([int]$Secs = 20, [switch]$Hide, [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot\milestone.ps1"
if (-not ("WinPing" -as [type])) {
Add-Type @'
using System; using System.Runtime.InteropServices;
public class WinPing { [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr h, uint m, IntPtr w, IntPtr l, uint f, uint t, out IntPtr r); }
'@ }
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = "$root\scratch\pv"
$set = @{ GT5P_NO_SETTINGS = "1"; PS3_VERBOSE = "0"; GT5P_PROFVIEW = "0" }
if ($Hide) { $set["FS_HIDE"] = "grim/file/contents" }
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
try {
Stop-Stragglers
Remove-Item Env:FS_HIDE -ErrorAction SilentlyContinue
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\ping.out" -RedirectStandardError "$dir\ping.err"
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
for ($i = 1; $i -le $Secs; $i++) {
    Start-Sleep -Seconds 1
    $p.Refresh(); if ($p.HasExited) { "exited"; break }
    $h = $p.MainWindowHandle
    $r = [IntPtr]::Zero
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $ok = [WinPing]::SendMessageTimeout($h, 0, [IntPtr]::Zero, [IntPtr]::Zero, 2, 500, [ref]$r)
    "{0,3}s window {1}: {2} ({3} ms)" -f $i, $h, $(if ($ok -ne [IntPtr]::Zero) { "answers" } else { "NO ANSWER" }), $sw.ElapsedMilliseconds
}
} finally {
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
