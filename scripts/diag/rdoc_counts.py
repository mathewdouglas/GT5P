# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_counts.py
# RDOC_CAP, RDOC_OUT. One line per draw: index, eventId, numIndices, first
# output target id -- to align a RenderDoc capture with an RSX manifest.
import os, traceback
import renderdoc as rd

out = open(os.environ["RDOC_OUT"], "w")

def actions_flat(acts, res):
    for a in acts:
        if a.flags & rd.ActionFlags.Drawcall:
            res.append(a)
        actions_flat(a.children, res)
    return res

try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile(); cf.OpenFile(os.environ["RDOC_CAP"], "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    for k, a in enumerate(actions_flat(ctrl.GetRootActions(), [])):
        o = a.outputs[0] if len(a.outputs) else rd.ResourceId.Null()
        out.write("%d %d %d %d\n" % (k, a.eventId, a.numIndices, int(o)))
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    out.write(traceback.format_exc())
finally:
    out.close(); rd.ShutdownReplay(); os._exit(0)
