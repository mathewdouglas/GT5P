"""Read a PS3_TIMELINE dump.
   python scripts/diag/tl.py <timeline.csv> <run.err> [frame_index] [--sum]
Names threads from the run log, splits the window into frames at the title's
SetPrepareFlip (F .. 0), prints one frame's events in order, and with --sum a
per-frame summary of where the main thread and PDI:1 waited and how long each
workload pass took."""
import re, sys, collections

csv, log = sys.argv[1], sys.argv[2]
fi = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].lstrip('-').isdigit() else 3
summ = '--sum' in sys.argv

names = {}
for path in (log, log.replace('.err', '.out')):
    try:
        for l in open(path, errors='replace'):
            m = re.search(r'\[THREAD (\d+)\].*hosttid=(\d+)', l)
            if m: names[int(m.group(2))] = 'g%s' % m.group(1)
            m = re.search(r'\[hostthread\] (\S+) hosttid=(\d+)', l)
            if m: names[int(m.group(2))] = m.group(1)
    except OSError:
        pass
gname = {}
for l in open(log, errors='replace'):
    m = re.search(r'sys_ppu_thread_create tid=(\d+) name="([^"]*)"', l)
    if m: gname['g' + m.group(1)] = m.group(2)
for l in open(csv, errors='replace'):
    m = re.match(r'#thread (\d+) (.*)', l)
    if m and int(m.group(1)) not in names and m.group(2).strip() != '?':
        names[int(m.group(1))] = m.group(2).strip()

def who(tid):
    n = names.get(tid)
    if n is None: return 'lane%d' % (tid % 1000)
    if n in gname: return gname[n][:16]
    return n

ev = []
for l in open(csv, errors='replace'):
    if l.startswith('#'): continue
    us, tid, k, a, b = l.strip().split(',')
    ev.append((int(us), int(tid), k, int(a), int(b)))
ev.sort()
flips = [e[0] for e in ev if e[2] == 'F' and e[4] == 0]

SC = {82: 'evflag_wait', 92: 'sema_wait', 102: 'mutex_lock', 107: 'cond_wait',
      130: 'eq_receive', 141: 'usleep', 142: 'sleep', 95: 'lwmutex', 97: 'lwcond_wait'}

def desc(e):
    us, tid, k, a, b = e
    if k == 'Y': return 'syscall %s %d us' % (SC.get(a, str(a)), b)
    if k == 'H': return 'hle 0x%08X %d us' % (a, b)
    if k == 'K': return 'kick wid%d =%d' % (a, b)
    if k == 'D': return 'dispatch wid%d lanes=%d' % (a, b)
    if k == 'E': return 'end wid%d %s' % (a, ('%d us' % b) if b else '')
    if k == 'L': return 'lane wid%d spu%d ran %d us' % (a >> 8, a & 255, b)
    if k == 'W': return 'info wid%d cont=%d ready=%d' % (a, b >> 8, b & 255)
    if k == 'F': return 'flip buf%d %s' % (a, 'prepare' if b == 0 else 'fifo')
    if k == 'P': return 'present %d us' % b
    if k == 'R': return 'fifo walk %d us (cpu %d us)' % (b, a)
    if k == 'S': return 'usleep asked %d us, slept %d us' % (a, b)
    if k == 'C': return 'frame cpu %d us of %d us wall since last prepare' % (a, b)
    if k == 'Q': return 'spin-wait sleep %d us (iteration %d)' % (b, a)
    if k == 'V': return 'vblank tick'
    return '%s %d %d' % (k, a, b)

if not summ:
    if fi + 1 >= len(flips): sys.exit('only %d frames' % len(flips))
    t0, t1 = flips[fi], flips[fi + 1]
    print('frame %d: %.1f ms' % (fi, (t1 - t0) / 1000))
    for e in ev:
        if t0 <= e[0] < t1:
            print('%8.2f %-18s %s' % ((e[0] - t0) / 1000, who(e[1]), desc(e)))
    sys.exit()

# Summary over all frames
print('%d frames, mean %.1f ms' % (len(flips) - 1, (flips[-1] - flips[0]) / 1000 / max(1, len(flips) - 1)))
waits = collections.Counter()   # (thread, what) -> us
cnt = collections.Counter()
for us, tid, k, a, b in ev:
    if k in 'YH' and flips[0] <= us < flips[-1]:
        key = (who(tid), SC.get(a, str(a)) if k == 'Y' else 'hle 0x%08X' % a)
        waits[key] += b; cnt[key] += 1
span = (flips[-1] - flips[0]) / 1000.0
print('\nblocked time per frame (ms), by thread and call:')
for (t, w), v in waits.most_common(30):
    print('  %-18s %-22s %6.2f ms/frame  (%d calls)' % (t, w, v / 1000.0 / (len(flips) - 1), cnt[(t, w)]))
# Workload passes
print('\nworkload passes (dispatch -> end):')
open_d = {}
passes = collections.defaultdict(list)
kick_lat = collections.defaultdict(list)
last_kick = {}
for us, tid, k, a, b in ev:
    if k == 'K': last_kick.setdefault(a, us)
    if k == 'D':
        open_d[a] = us
        if a in last_kick: kick_lat[a].append(us - last_kick.pop(a))
    if k == 'E' and a in open_d: passes[a].append(us - open_d.pop(a))
for w in sorted(passes):
    p = passes[w]
    kl = kick_lat.get(w, [])
    print('  wid%d: %d passes, mean %.2f ms, max %.2f ms, total %.1f ms/frame; kick->dispatch mean %.2f ms (%d)' % (
        w, len(p), sum(p) / len(p) / 1000, max(p) / 1000, sum(p) / 1000 / (len(flips) - 1),
        (sum(kl) / len(kl) / 1000) if kl else 0, len(kl)))
lanes = collections.defaultdict(list)
for us, tid, k, a, b in ev:
    if k == 'L': lanes[(a >> 8, a & 255)].append(b)
print('\nlane runs:')
for key in sorted(lanes):
    v = lanes[key]
    print('  wid%d spu%d: %d runs, %.2f ms/frame, mean %.2f ms' % (key[0], key[1], len(v), sum(v) / 1000 / (len(flips) - 1), sum(v) / len(v) / 1000))
pr = [b for us, tid, k, a, b in ev if k == 'P']
fw = [b for us, tid, k, a, b in ev if k == 'R']
fc = [a for us, tid, k, a, b in ev if k == 'R']
print('\npresent thread: present %.1f ms/frame, fifo walk %.1f ms/frame (cpu %.1f)' % (sum(pr) / 1000 / (len(flips) - 1), sum(fw) / 1000 / (len(flips) - 1), sum(fc) / 1000 / (len(flips) - 1)))
