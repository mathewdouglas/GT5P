# Gran Turismo 5: boot to the main menu with milestone-timed presses
# (milestone.ps1, $GT5BootHold), idle there -Settle seconds with a window shot
# every -Gap seconds, and summarise the frame rate.
#   scripts\test\gt5boot.ps1 -Tag t [-Settle 60] [-Gap 10] [-Fresh] [-FreshSave] NAME=VALUE ...
#   -Fresh: first-boot install state (scripts\test\gt5_reset.py), so the
#   install prompts run; -FreshSave also removes the save (GT5 creates it).
#   -> scratch\pv\<t>.out/.err, <t>.menu<N>.png
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "gt5", [int]$Settle = 60, [int]$Gap = 10, [switch]$Fresh, [switch]$FreshSave,
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
          PAD_MILESTONE_FILES = "installed00.dat"; PAD_HOLD = $GT5BootHold }
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
$tm = Wait-Milestone $p $tl "MusicDecode" $limit
if ($tm -lt 0) { "menu not reached (log: $dir\$Tag.out)" }
else {
    "menu loading at $tm s"
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
}
} finally { Stop-GT5 }
# Frames per 5 s from the present thread, oldest first.
$f = Select-String -Path "$dir\$Tag.err" -Pattern 'present-thread\] 5 s: (\d+) frames' |
     ForEach-Object { $_.Matches[0].Groups[1].Value }
"frames per 5 s: $($f -join ' ')"
