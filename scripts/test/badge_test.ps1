# Shader badge: start the game on an empty shader cache, capture the badge's
# own window whenever it is visible, and print what the game logged about it.
#   scripts\test\badge_test.ps1 [-Secs 45]
param([int]$Secs = 45)
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class BW { [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
 [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string t);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h); }
'@
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = "$root\scratch\badge_t"
New-Item -ItemType Directory -Force $dir | Out-Null
Get-ChildItem $dir -Filter *.png -ErrorAction SilentlyContinue | Remove-Item
$sc = "$dir\shadercache_empty"
if (Test-Path $sc) { Remove-Item -Recurse -Force $sc }
$env:RSX_SHADER_CACHE = $sc; $env:GT5P_NO_SETTINGS = "1"; $env:PS3_VERBOSE = "0"; $env:FS_HIDE = "grim/file/contents"
Remove-Item Env:PS3_HEADLESS, Env:GT5P_SHADER_INDICATOR -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "$root\build\gt5p.exe" -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$dir\out.txt" -RedirectStandardError "$dir\err.txt"
$n = 0
try {
    for ($t = 0; $t -lt $Secs * 4; $t++) {
        Start-Sleep -Milliseconds 250
        $h = [BW]::FindWindow("gt5p_shaderbusy", [NullString]::Value)
        if ($h -ne [IntPtr]::Zero -and [BW]::IsWindowVisible($h) -and $n -lt 6) {
            $bmp = New-Object System.Drawing.Bitmap 236, 38
            $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
            [BW]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
            $bmp.Save("$dir\badge_$n.png"); $bmp.Dispose(); $n++
            "{0:N2} s: badge visible" -f ($t / 4)
        }
    }
} finally {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Remove-Item Env:RSX_SHADER_CACHE, Env:GT5P_NO_SETTINGS, Env:FS_HIDE -ErrorAction SilentlyContinue
}
Select-String -Path "$dir\err.txt" -Pattern "shader-badge" | ForEach-Object { $_.Line }
