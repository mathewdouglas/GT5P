param([int]$N = 5, [string]$Prefix = "fz")
Set-Location C:\Users\GGPC\Dev\Recomps\GT5-work
for ($i = 1; $i -le $N; $i++) {
    $t = "$Prefix$i"
    $o = powershell -NoProfile -File scripts\test\gt5boot.ps1 -Tag $t -Route race -FrameTest -Settle 50 -Gap 25 RSX_PRESENT_SYNC=0 GT5P_STALL_MS=1000 @args 2>&1 | Out-String
    $ft = ($o -split "`n" | Where-Object { $_ -match "FrameTest" }) -join " "
    $g = & .venv\Scripts\python.exe -c "import csv;r=[float(x[0]) for x in csv.reader(open(r'scratch\pv\$t.frames.csv'))];print(' '.join('%.0fs:%.0fms'%((r[i]-r[0])/1000,r[i]-r[i-1]) for i in range(1,len(r)) if r[i]-r[i-1]>1000 and (r[i]-r[0])>60000))"
    "$t $ft gaps>1s: $g"
    if ($g.Trim()) { "STALL in $t"; break }
}
