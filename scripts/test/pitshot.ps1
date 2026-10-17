# Drive to the Daytona Race Mode page (the pit), wait -Settle seconds, and
# save the game window's own contents (PrintWindow: no desktop grab).
#   scripts\test\pitshot.ps1 -Tag t [-Settle 20] [-Shots 1] [-Gap 2] NAME=VALUE ...
#   -> scratch\pv\<t>.win.png (and <t>.win2.png ... with -Shots)
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "win", [int]$Settle = 20, [int]$Shots = 1, [int]$Gap = 2,
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
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0"; PAD_HOLD = $DaytonaHold; GT5P_PROFVIEW = "0" }
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
try {
Stop-Stragglers
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\$Tag.out" -RedirectStandardError "$dir\$Tag.err"
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$tl = New-LogTail "$dir\$Tag.out"
$tp = Wait-Milestone $p $tl "PitSceneRoot" 120
if ($tp -lt 0) { "page not reached" }
else {
    Start-Sleep -Seconds $Settle
    for ($i = 1; $i -le $Shots; $i++) {
        $p.Refresh(); $h = $p.MainWindowHandle
        $r = New-Object WinShot+RECT; [WinShot]::GetClientRect($h, [ref]$r) | Out-Null
        $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R, 16)), ([Math]::Max($r.B, 16))
        $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
        [WinShot]::PrintWindow($h, $dc, 3) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
        $name = if ($i -eq 1) { "$dir\$Tag.win.png" } else { "$dir\$Tag.win$i.png" }
        $bmp.Save($name); $bmp.Dispose()
        if ($i -lt $Shots) { Start-Sleep -Seconds $Gap }
    }
    "page at $tp s; title: $($p.MainWindowTitle)"
}
} finally {
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
