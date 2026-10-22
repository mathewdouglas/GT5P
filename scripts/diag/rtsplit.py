"""rtsplit.py <timeline.csv>: split the flip-preparing (render) thread's frames
   into CPU, syscall waits, frame-pacer sleeps, spin-wait sleeps and time not
   running, from PS3_TIMELINE events C, Y, S and Q (Phase 106)."""
import sys, statistics, bisect
ev=[l.strip().split(',') for l in open(sys.argv[1]) if not l.startswith('#')]
ev=[(int(a),int(b),c,int(d),int(e)) for a,b,c,d,e in ev]; ev.sort()
C=[e for e in ev if e[2]=='C']; rt=C[0][1]
mine=[e for e in ev if e[1]==rt]; ts=[e[0] for e in mine]
rows=[]
for e in C:
    t1=e[0]; t0=t1-e[4]
    seg=mine[bisect.bisect_right(ts,t0):bisect.bisect_right(ts,t1)]
    blk=sum(x[4] for x in seg if x[2]=='Y')/1000
    slp=sum(x[4] for x in seg if x[2]=='S')/1000
    spn=sum(x[4] for x in seg if x[2]=='Q')/1000
    rows.append((e[4]/1000,e[3]/1000,blk-0,slp,spn))
def show(r): return '%5.1f %5.1f %6.1f %6.1f %6.1f %6.1f'%(r[0],r[1],r[2]-r[3],r[3],r[4],r[0]-r[1]-r[2]-r[4])
print('frames',len(rows),'late',sum(1 for r in rows if r[0]>20))
print(' wall   cpu  waits pacer   spin  rest(not running)')
for r in [r for r in rows if r[0]>20][:30]: print(show(r))
ok=[r for r in rows if r[0]<=20]
m=[statistics.mean(x) for x in zip(*ok)]
print('normal mean', show(m))
rest=[r[0]-r[1]-r[2]-r[4] for r in rows]
print('rest>3ms frames', sum(1 for x in rest if x>3), 'of', len(rows))
