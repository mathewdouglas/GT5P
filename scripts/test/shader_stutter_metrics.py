"""Check hitch thresholds and strict sampling-window boundaries."""
from shader_stutter import frame_stats

# Most frames take 10 ms, with three deliberately different hitch classes.
times = [0.0]
for interval in [10]*20 + [60,110,300] + [10]*20:
    times.append(times[-1]+interval)
rows = [(t,2,1) for t in times]
stats = frame_stats(rows,0,times[-1])
assert (stats['over_50_ms'],stats['over_100_ms'],stats['over_250_ms']) == (3,2,1)
assert stats['hitch_excess_50_ms'] == 320 and stats['median_ms'] == 10 and stats['max_ms'] == 300
assert stats['walk_wall_ms'] == 2 and stats['walk_cpu_ms'] == 1
late = frame_stats(rows,times[-20],times[-1])
assert late['over_50_ms'] == 0 and late['max_ms'] == 10
try:
    frame_stats([(1,0,0)]*20,0,2)
except ValueError:
    pass
else:
    raise AssertionError('Duplicate/non-monotonic timestamps accepted')
print('Hitch thresholds, window boundaries and timestamp rejection passed')
