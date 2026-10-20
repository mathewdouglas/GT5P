# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_gputime.py
# RDOC_CAP, RDOC_OUT. GPU time per event (RenderDoc's EventGPUDuration
# counter), summed per output target and by action kind, plus the costliest
# events -- where a frame's GPU time actually goes.
import os, traceback, collections
import renderdoc as rd

out = open(os.environ["RDOC_OUT"], "w")

def flat(acts, res):
    for a in acts:
        res.append(a)
        flat(a.children, res)
    return res

def kind(a):
    f = a.flags
    if f & rd.ActionFlags.Drawcall: return "draw"
    if f & rd.ActionFlags.Clear: return "clear"
    if f & rd.ActionFlags.Copy: return "copy"
    if f & rd.ActionFlags.Resolve: return "resolve"
    if f & rd.ActionFlags.Dispatch: return "dispatch"
    if f & rd.ActionFlags.Present: return "present"
    return "other"

try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile(); cf.OpenFile(os.environ["RDOC_CAP"], "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    acts = {a.eventId: a for a in flat(ctrl.GetRootActions(), [])}
    res = ctrl.FetchCounters([rd.GPUCounter.EventGPUDuration])
    times = {c.eventId: c.value.d * 1000.0 for c in res}   # ms
    total = sum(times.values())
    out.write("events with GPU time: %d, total %.3f ms\n" % (len(times), total))
    by_kind = collections.Counter(); n_kind = collections.Counter()
    by_target = collections.Counter(); n_target = collections.Counter(); idx = collections.Counter()
    for e, t in times.items():
        a = acts.get(e)
        if not a: continue
        k = kind(a); by_kind[k] += t; n_kind[k] += 1
        o = int(a.outputs[0]) if len(a.outputs) and a.outputs[0] != rd.ResourceId.Null() else 0
        d = int(a.depthOut) if a.depthOut != rd.ResourceId.Null() else 0
        key = "rt=%d depth=%d" % (o, d)
        by_target[key] += t; n_target[key] += 1; idx[key] += a.numIndices
    out.write("\nby kind:\n")
    for k, t in by_kind.most_common():
        out.write("  %-9s %8.3f ms  %5d events\n" % (k, t, n_kind[k]))
    out.write("\nby output target (top 25):\n")
    for k, t in by_target.most_common(25):
        out.write("  %-28s %8.3f ms  %5d events  %9d indices\n" % (k, t, n_target[k], idx[k]))
    out.write("\ncostliest events (top 40):\n")
    for e, t in sorted(times.items(), key=lambda x: -x[1])[:40]:
        a = acts.get(e)
        name = a.GetName(ctrl.GetStructuredFile()) if a else "?"
        o = int(a.outputs[0]) if a and len(a.outputs) else 0
        out.write("  ev %6d %7.3f ms  %-8s idx=%-7d inst=%-4d rt=%d  %s\n" % (
            e, t, kind(a) if a else "?", a.numIndices if a else 0, a.numInstances if a else 0, o, name[:60]))
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    out.write(traceback.format_exc())
finally:
    out.close(); rd.ShutdownReplay(); os._exit(0)
