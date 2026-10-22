# Boot with the TV content visible (the opening movie plays) and save the game
# window's own contents (PrintWindow) at the given seconds after launch.
#   scripts\test\movshot.ps1 -Tag t [-At 10,13,16] NAME=VALUE ...
#   -> scratch\pv\<t>.mov<s>.png
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "mov", [string]$At = "10,13,16",
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
$set = @{ GT5P_NO_SETTINGS = "1"; PS3_VERBOSE = "0"; GT5P_PROFVIEW = "0" }
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
try {
Stop-Stragglers
Remove-Item Env:FS_HIDE -ErrorAction SilentlyContinue
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\$Tag.out" -RedirectStandardError "$dir\$Tag.err"
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$sw = [Diagnostics.Stopwatch]::StartNew()
foreach ($t in ($At -split "," | ForEach-Object { [int]$_ })) {
    while ($sw.Elapsed.TotalSeconds -lt $t) { Start-Sleep -Milliseconds 100 }
    $p.Refresh(); if ($p.HasExited) { "exited"; break }
    $h = $p.MainWindowHandle
    $r = New-Object WinShot+RECT; [WinShot]::GetClientRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R, 16)), ([Math]::Max($r.B, 16))
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    [WinShot]::PrintWindow($h, $dc, 3) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
    $bmp.Save("$dir\$Tag.mov$t.png"); $bmp.Dispose()
}
"title: $($p.MainWindowTitle)"
} finally {
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
