# Visit -N dealers in a row from the top of the list: enter, wait, back out
# (Right, Left, then a 2 s Circle: the page ignores Circle until it has had
# input), Right to the next dealer, enter. Prints the title bar every -Gap s.
#   scripts\test\revisit.ps1 -Tag rv [-N 4] [-Stay 22000] [-UseSettings] NAME=VALUE ...
[CmdletBinding(PositionalBinding = $false)]
param([string]$Tag = "rv", [int]$N = 4, [int]$Stay = 22000, [int]$Gap = 3, [switch]$UseSettings,
      [Parameter(ValueFromRemainingArguments = $true)] $Vars)
. "$PSScriptRoot\milestone.ps1"
$h = $ToDealers
$t = 6000
foreach ($v in 1..$N) {
    $h += ",@DealerSelectRoot+$t-$($t+300):CROSS"; $a = $t + $Stay
    $h += ",@DealerSelectRoot+$a-$($a+150):RIGHT,@DealerSelectRoot+$($a+1500)-$($a+1650):LEFT,@DealerSelectRoot+$($a+3500)-$($a+5500):CIRCLE,@DealerSelectRoot+$($a+10000)-$($a+10150):RIGHT"
    $t = $a + 12000
}
$secs = [int](($t + 4000) / 1000)
$args2 = @("-File", "$PSScriptRoot\dealer.ps1", "-Tag", $Tag, "-Secs", $secs, "-Gap", $Gap)
if ($UseSettings) { $args2 += "-UseSettings" }
$args2 += "PAD_HOLD=$h"
foreach ($v in $Vars) { if ($v) { $args2 += "$v" } }
& powershell @args2 | ForEach-Object { $_ -replace 'Gran Turismo 5 Prologue \(ps3recomp\) \| ', '' }
