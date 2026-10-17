# Drive the F1 settings page without the desktop keyboard: start the game on a
# scratch settings file with the page open, capture the page's own window,
# post keys to it, and show what reached the file.
#   scripts\test\settings_test.ps1
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices; using System.Text;
public class SetUi {
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
 [DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string title);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; } }
'@
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = "$root\scratch\settings_t"
New-Item -ItemType Directory -Force $dir | Out-Null
$toml = "$dir\test.toml"
if (Test-Path $toml) { Remove-Item $toml }
$env:GT5P_SETTINGS = $toml; $env:GT5P_SETTINGS_UI = "1"; $env:PS3_VERBOSE = "0"; $env:FS_HIDE = "grim/file/contents"
Remove-Item Env:GT5P_NO_SETTINGS -ErrorAction SilentlyContinue
Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\out.txt" -RedirectStandardError "$dir\err.txt"
function cap($tag) {
    $h = [SetUi]::FindWindow("gt5p_settings", [NullString]::Value)
    if ($h -eq [IntPtr]::Zero) { "no settings window ($tag)"; return }
    $r = New-Object SetUi+RECT; [SetUi]::GetClientRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R,16)), ([Math]::Max($r.B,16))
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    [SetUi]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
    $bmp.Save("$dir\$tag.png"); $bmp.Dispose()
    "captured $tag (visible=$([SetUi]::IsWindowVisible($h)))"
}
function key($vk, $n = 1) {
    $h = [SetUi]::FindWindow("gt5p_settings", [NullString]::Value)
    for ($i = 0; $i -lt $n; $i++) { [SetUi]::PostMessage($h, 0x100, [IntPtr]$vk, [IntPtr]0) | Out-Null; Start-Sleep -Milliseconds 150 }
}
try {
    Start-Sleep -Seconds 15
    cap "open"
    key 0x28 2; key 0x27          # down to Vsync, right: off
    Start-Sleep -Milliseconds 300; cap "vsync_off"
    key 0x26 2; key 0x27          # up to Resolution, right: 1080
    Start-Sleep -Milliseconds 300; cap "res_1080"
    "--- file:"; Get-Content $toml | Select-String "^(resolution|msaa|vsync|shader_cache|sdl_controllers|keyboard|verbose_log) ="
    key 0x1B                      # Esc: close
    Start-Sleep -Milliseconds 500; cap "closed"
} finally {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Remove-Item Env:GT5P_SETTINGS, Env:GT5P_SETTINGS_UI, Env:FS_HIDE -ErrorAction SilentlyContinue
}
