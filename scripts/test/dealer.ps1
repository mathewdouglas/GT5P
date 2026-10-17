# Boot to the manufacturer list, press -Moves (comma list of UP/DOWN/LEFT/RIGHT,
# one every -Step ms starting 5 s after DealerSelectRoot), optionally Cross, then
# take window shots every -Gap s for -Secs s.
#   scripts\test\dealer.ps1 -Tag fer -Moves "RIGHT,RIGHT" [-Enter] [-Secs 40] NAME=VALUE ...
#   -> scratch\pv\<tag>.out/.err, scratch\pv\<tag>.sNN.png
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "dlr", [string]$Moves = "", [switch]$Enter, [int]$Secs = 40, [int]$Gap = 4,
      [int]$Step = 1200, [int]$Press = 100, [switch]$UseSettings, [Parameter(ValueFromRemainingArguments = $true)] $Vars)
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
Remove-Item "$dir\$Tag.s*.png" -ErrorAction SilentlyContinue
$hold = $ToDealers
$t = 5000
foreach ($m in ($Moves -split ",")) { if (-not $m) { continue }; $hold += ",@DealerSelectRoot+$t-$($t+$Press):$m"; $t += $Step }
if ($Enter) { $t += 1000; $hold += ",@DealerSelectRoot+$t-$($t+300):CROSS" }
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0"; PAD_HOLD = $hold; GT5P_PROFVIEW = "1" }
if ($UseSettings) { $set.Remove("GT5P_NO_SETTINGS") }   # play with gt5p_settings.toml
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
function Shot($p, $name) {
    $p.Refresh(); $h = $p.MainWindowHandle
    $r = New-Object WinShot+RECT; [WinShot]::GetClientRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R, 16)), ([Math]::Max($r.B, 16))
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    [WinShot]::PrintWindow($h, $dc, 3) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
    $bmp.Save($name); $bmp.Dispose()
}
try {
Stop-Stragglers
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\$Tag.out" -RedirectStandardError "$dir\$Tag.err"
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$tl = New-LogTail "$dir\$Tag.out"
$ts = Wait-Milestone $p $tl "DealerSelectRoot" 120
if ($ts -lt 0) { "list not reached" }
else {
    "list at $ts s"
    $sw = [Diagnostics.Stopwatch]::StartNew(); $i = 0
    while ($sw.Elapsed.TotalSeconds -lt $Secs) {
        Start-Sleep -Seconds $Gap; $i++
        Shot $p ("$dir\$Tag.s{0:D2}.png" -f $i)
        "{0,3}s {1}" -f [int]$sw.Elapsed.TotalSeconds, $p.MainWindowTitle
    }
    Read-LogTail $tl | Out-Null
    ($tl.Text -split "`n" | Select-String '\[milestone\]') -join "`n"
}
} finally {
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
