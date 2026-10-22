# The quit question: Escape in the game window shows the game-style
# "Quit Gran Turismo 5 Prologue?" popup instead of closing. Posts keys (no
# desktop keyboard), shoots the game window, and checks Cancel keeps the game
# running and OK closes it.
#   scripts\test\quit_confirm.ps1 [NAME=VALUE ...]
#   -> scratch\quit_t\*.png
[CmdletBinding(PositionalBinding = $false)]
param([Parameter(ValueFromRemainingArguments = $true)] $Vars)
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class QuitT {
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
 [DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string title);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; } }
'@
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. "$PSScriptRoot\milestone.ps1"
$dir = "$root\scratch\quit_t"
New-Item -ItemType Directory -Force $dir | Out-Null
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0" }
foreach ($v in $Vars) { if (-not $v) { continue }; $k, $val = "$v" -split "=", 2; $set[$k] = $val }
function Win($cls) { [QuitT]::FindWindow($cls, [NullString]::Value) }
function Shot($tag) {
    $h = Win "ps3recomp_d3d12"
    $r = New-Object QuitT+RECT; [QuitT]::GetClientRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R,16)), ([Math]::Max($r.B,16))
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    [QuitT]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
    $bmp.Save("$dir\$tag.png"); $bmp.Dispose()
}
# Escape to the game window (WM_KEYDOWN, first press); keys to the page's
# hidden window drive the popup.
function GameEsc { [QuitT]::PostMessage((Win "ps3recomp_d3d12"), 0x100, [IntPtr]0x1B, [IntPtr]1) | Out-Null }
function Key($vk) { [QuitT]::PostMessage((Win "gt5p_settings"), 0x100, [IntPtr]$vk, [IntPtr]0) | Out-Null; Start-Sleep -Milliseconds 250 }
$fail = 0
try {
    Stop-Stragglers
    foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
    $p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
        -RedirectStandardOutput "$dir\out.txt" -RedirectStandardError "$dir\err.txt"
    Start-Sleep -Seconds 15
    GameEsc; Start-Sleep -Milliseconds 800; Shot "asked"
    if ($p.HasExited) { "FAIL: Escape closed the game"; $fail++ } else { "ok: Escape asked (game still running)" }
    Key 0x27; Start-Sleep -Milliseconds 300; Shot "ok_selected"
    Key 0x25; Key 0x0D; Start-Sleep -Milliseconds 800; Shot "cancelled"   # Left to Cancel, Enter
    if ($p.HasExited) { "FAIL: Cancel closed the game"; $fail++ } else { "ok: Cancel kept the game running" }
    GameEsc; Start-Sleep -Milliseconds 800
    Key 0x27; Key 0x0D                                                     # Right to OK, Enter
    if ($p.WaitForExit(15000)) { "ok: OK closed the game (exit $($p.ExitCode))" } else { "FAIL: OK did not close the game"; $fail++ }
} finally {
    if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
}
if ($fail) { exit 1 }
