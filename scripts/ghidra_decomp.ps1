# Decompile functions of the target executable with Ghidra, headless.
#   scripts\ghidra_decomp.ps1 0xBAA9E8 0xBA97B0 ...
#
# Output goes to analysis\ghidra\out\func_XXXXXXXX.c. That folder is
# gitignored: the output is derived from the game binary and must not be
# committed or pasted into tracked files.
#
# REA cannot be used for this file: it rejects 64-bit PowerPC ELF as an
# unsupported architecture. This drives Ghidra directly. The first run imports
# the executable (no auto-analysis, about a minute); later runs reuse the
# project.
param([Parameter(ValueFromRemainingArguments = $true)] $Addrs)
$root = Split-Path $PSScriptRoot -Parent
$local = Get-Content "$root\AGENTS.local.md" -ErrorAction Stop
$ghidra = ($local | Select-String 'Ghidra[^`]*`([^`]+)`').Matches[0].Groups[1].Value
$jdk = ($local | Select-String 'JDK 21: `([^`]+)`').Matches[0].Groups[1].Value
$env:JAVA_HOME = $jdk
$proj = "$root\analysis\ghidra"
$out = "$proj\out"
New-Item -ItemType Directory -Force $proj, $out | Out-Null
$tgt = Get-Content "$root\config\targets.json" -Raw | ConvertFrom-Json
$name = if (Test-Path "$root\input\target") { (Get-Content "$root\input\target" -TotalCount 1).Trim() } else { "NPUA80075" }
$toc = "0x0133BC58"   # BCUS98158; read from a crash report's r2
$headless = "$ghidra\support\analyzeHeadless.bat"
$elf = "$root\input\EMAIN.ELF"
if (-not (Test-Path "$proj\gt5p_$name.rep")) {
    & $headless $proj "gt5p_$name" -import $elf -noanalysis 2>&1 | Select-String "ERROR|Import succeeded|REPORT" | ForEach-Object { $_.Line }
}
& $headless $proj "gt5p_$name" -process "EMAIN.ELF" -noanalysis -scriptPath "$root\scripts\ghidra" `
    -postScript DecompAt.java $out $toc @Addrs 2>&1 |
    Select-String "wrote |no function|ERROR|Exception" | ForEach-Object { $_.Line -replace '^.*DecompAt.java> ', '' }
