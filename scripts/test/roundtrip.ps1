# Menu -> Arcade (Track Select) -> Circle back to the menu -> shot(s), then
# four Rights to Dealerships, Cross, Cross -> dealer page -> shot(s).
# The user's report (2026-10-17): after the Arcade round trip the menu scene
# has black slabs, and the dealer's reflections show the menu's trees.
#   scripts\test\roundtrip.ps1 -Tag t [-NoArcade] NAME=VALUE ...
#   -> scratch\pv\<t>.menu.png, <t>.dealer.png
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "rt", [switch]$NoArcade, [switch]$Pit, [int]$MenuSettle = 20, [int]$DealerSettle = 20, [int]$Every = 0,
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
function Save-Shot($p, $name) {
    $p.Refresh(); $h = $p.MainWindowHandle
    $r = New-Object WinShot+RECT; [WinShot]::GetClientRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R, 16)), ([Math]::Max($r.B, 16))
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    [WinShot]::PrintWindow($h, $dc, 3) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
    $bmp.Save($name); $bmp.Dispose()
}
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = "$root\scratch\pv"; New-Item -ItemType Directory -Force $dir | Out-Null
# Times in ms after CourseSelectRoot (Arcade) or TopMenuTemplate (no Arcade).
if ($NoArcade) {
    $menuMs = 6000 + 1000 * $MenuSettle
    $hold = "@TopMenuTemplate+6000-6300:CIRCLE"
    $b = 6000 + 1000 * $MenuSettle + 1000
    foreach ($k in 0..7) { $t = $b + 350 * $k; $hold += ",@TopMenuTemplate+$t-$($t+100):RIGHT" }
    $hold += ",@TopMenuTemplate+$($b+3500)-$($b+3800):CROSS"
    $anchor = "TopMenuTemplate"
} elseif ($Pit) {
    # Daytona's Race Mode page (the pit), then Circle, Circle back to the menu.
    $hold = (Get-ToDaytona 6000) + ",@PitSceneRoot+12000-12100:RIGHT,@PitSceneRoot+12500-12600:RIGHT,@PitSceneRoot+13000-13100:RIGHT,@PitSceneRoot+14000-14300:CROSS,@PitSceneRoot+23000-23300:CIRCLE"
    $b = 23000 + 1000 * $MenuSettle + 1000
    foreach ($k in 0..3) { $t = $b + 350 * $k; $hold += ",@PitSceneRoot+$t-$($t+100):RIGHT" }
    $hold += ",@PitSceneRoot+$($b+2000)-$($b+2300):CROSS"
    $menuMs = 23000 + 1000 * $MenuSettle
    $anchor = "PitSceneRoot"
} else {
    $hold = "@TopMenuTemplate+6000-6300:CIRCLE"
    foreach ($k in 0..3) { $t = 7000 + 350 * $k; $hold += ",@TopMenuTemplate+$t-$($t+100):RIGHT" }
    $hold += ",@TopMenuTemplate+9100-9400:CROSS,@CourseSelectRoot+5000-5300:CIRCLE,@CourseSelectRoot+11000-11300:CIRCLE"
    $b = 5000 + 1000 * $MenuSettle + 1000
    foreach ($k in 0..3) { $t = $b + 350 * $k; $hold += ",@CourseSelectRoot+$t-$($t+100):RIGHT" }
    $hold += ",@CourseSelectRoot+$($b+2000)-$($b+2300):CROSS"
    $menuMs = 5000 + 1000 * $MenuSettle
    $anchor = "CourseSelectRoot"
}
$hold += ",@DealerSelectRoot+5000-5300:CROSS,@DealerSelectRoot+11000-11300!DealerTopTransition:CROSS"
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0"; PAD_HOLD = $hold; GT5P_PROFVIEW = "0" }
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
try {
Stop-Stragglers
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\$Tag.out" -RedirectStandardError "$dir\$Tag.err"
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$tl = New-LogTail "$dir\$Tag.out"
if ((Wait-Milestone $p $tl $anchor 120) -lt 0) { "$anchor not reached"; return }
if ($Every -gt 0) {
    # -Every <s>: a shot every <s> seconds from the anchor to the menu shot.
    for ($t = 0; $t -lt $menuMs; $t += 1000 * $Every) {
        Save-Shot $p ("$dir\$Tag.t{0:D3}.png" -f [int]($t / 1000)); Start-Sleep -Seconds $Every
    }
} else { Start-Sleep -Milliseconds ($menuMs - 1000) }
Save-Shot $p "$dir\$Tag.menu.png"; "menu shot"
if ((Wait-Milestone $p $tl "DealerTopRoot" 90) -lt 0) { "dealer page not reached"; return }
Start-Sleep -Seconds $DealerSettle
Save-Shot $p "$dir\$Tag.dealer.png"; "dealer shot; title: $($p.MainWindowTitle)"
} finally {
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
