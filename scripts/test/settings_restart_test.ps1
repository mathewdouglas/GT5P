# Settings page "Restart now": change a restart-only setting, press the row,
# and check the old process is gone and a new one is running.
Add-Type @'
using System; using System.Runtime.InteropServices;
public class K2 { [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
 [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string t); }
'@
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$env:GT5P_SETTINGS = "$root\scratch\settings_t\test.toml"; $env:GT5P_SETTINGS_UI = "1"; $env:FS_HIDE = "grim/file/contents"
Remove-Item Env:GT5P_NO_SETTINGS, Env:PS3_VERBOSE, Env:PS3_HEADLESS -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$root\scratch\settings_t\out.txt" -RedirectStandardError "$root\scratch\settings_t\err.txt"
try {
    Start-Sleep 15
    $h = [K2]::FindWindow("gt5p_settings", [NullString]::Value); "window $h"
    function k($vk) { [K2]::PostMessage($h, 0x100, [IntPtr]$vk, [IntPtr]0) | Out-Null; Start-Sleep -Milliseconds 200 }
    k 0x28; k 0x27            # Antialiasing, next value
    (Get-Content "$root\scratch\settings_t\test.toml") -match "^msaa"
    k 0x26; k 0x26; k 0x26    # Resolution, Close (wraps), Restart now
    k 0x0D
    Start-Sleep 5
    "old process alive: " + (-not $p.HasExited)
    Get-Process gt5p -ErrorAction SilentlyContinue | ForEach-Object { "running: pid $($_.Id) started $($_.StartTime)" }
} finally {
    Get-Process gt5p -ErrorAction SilentlyContinue | Stop-Process -Force
    Remove-Item Env:GT5P_SETTINGS, Env:GT5P_SETTINGS_UI, Env:FS_HIDE -ErrorAction SilentlyContinue
}
