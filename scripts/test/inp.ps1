# Run the port with a window for up to N seconds while someone uses it.
# Captures the window every 5 s to scratch\inp_NNN.png, logs to scratch\inp.out/.err,
# and reports when the process exits by itself.
#   scripts\test\inp.ps1 180 NAME=VALUE ...
[CmdletBinding(PositionalBinding = $false)]
param([Parameter(Position = 0)][int]$Secs = 180, [string]$Exe = "", [Parameter(ValueFromRemainingArguments = $true)] $Vars)
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class WinCap2 { [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; } }
'@
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Remove-Item "$root\scratch\inp_*.png" -ErrorAction SilentlyContinue
# GT5P_MAINSTACK=5 used to be set here. It suspends the main thread every 5 s
# to print its call chain, and the title's sound stops for as long (an 85 ms
# dropout every 5 s). Pass it explicitly when the call chain is wanted.
$set = @{ GT5P_NO_SETTINGS = "1"; FS_HIDE = "grim/file/contents"; PS3_VERBOSE = "0" }
foreach ($v in $Vars) { $k, $val = "$v" -split "=", 2; $set[$k] = $val }
Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
foreach ($k in $set.Keys) { Set-Item "Env:$k" $set[$k] }
if (-not $Exe) { $Exe = "$root\build\gt5p.exe" }
$p = Start-Process -FilePath $Exe -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput "$root\scratch\inp.out" -RedirectStandardError "$root\scratch\inp.err"
for ($s = 5; $s -le $Secs; $s += 5) {
    Start-Sleep -Seconds 5; $p.Refresh()
    if ($p.HasExited) { "exited by $s s"; break }
    $h = $p.MainWindowHandle
    # PrintWindow blocks for ever on a window that has stopped answering.
    if ($h -ne 0 -and -not $p.Responding) { "$s s: window not responding"; continue }
    if ($h -ne 0) {
        $r = New-Object WinCap2+RECT; [WinCap2]::GetClientRect($h, [ref]$r) | Out-Null
        $bmp = New-Object System.Drawing.Bitmap ([Math]::Max($r.R, 16)), ([Math]::Max($r.B, 16))
        $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
        [WinCap2]::PrintWindow($h, $dc, 3) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
        $bmp.Save(("$root\scratch\inp_{0:d3}.png" -f $s)); $bmp.Dispose()
        "$s s: $($p.MainWindowTitle -replace '.*\| FPS','FPS')"
    }
}
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force; "still alive at $Secs s; stopped" }
foreach ($k in $set.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
"flips: " + ((Get-Content "$root\scratch\inp.out") | Select-String "SetPrepareFlip").Count
