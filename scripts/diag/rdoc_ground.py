# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_ground.py
# RDOC_CAP, RDOC_OUT, RDOC_PIXELS ("x,y;..."). Finds the colour target the
# most draws write, then prints each pixel's history on it: every event that
# touched it, pass/fail reasons, the shader output and the value after.
import os, traceback, collections
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out = open(os.environ.get("RDOC_OUT", cap_path + ".ground.txt"), "w")
pixels = [tuple(int(v) for v in s.split(",")) for s in os.environ.get("RDOC_PIXELS", "640,600").split(";") if s]
FLAGS = ["sampleMasked", "backfaceCulled", "depthClipped", "viewClipped", "scissorClipped",
         "shaderDiscarded", "depthTestFailed", "stencilTestFailed", "unboundPS"]

def p(*a):
    out.write(" ".join(str(x) for x in a) + "\n"); out.flush()

def actions_flat(acts, res):
    for a in acts:
        if a.flags & rd.ActionFlags.Drawcall:
            res.append(a)
        actions_flat(a.children, res)
    return res

try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile()
    cf.OpenFile(cap_path, "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    draws = actions_flat(ctrl.GetRootActions(), [])
    cnt = collections.Counter(); ev2idx = {}
    for k, a in enumerate(draws):
        ev2idx[a.eventId] = k
        for o in a.outputs:
            if o != rd.ResourceId.Null():
                cnt[o] += 1
    texs = {t.resourceId: t for t in ctrl.GetTextures()}
    for rid, n in cnt.most_common(6):
        t = texs.get(rid)
        p("target", rid, n, "draws", t and (t.width, t.height, t.msSamp))
    rid = cnt.most_common(1)[0][0]
    ctrl.SetFrameEvent(draws[-1].eventId, True)
    for (x, y) in pixels:
        hist = ctrl.PixelHistory(rid, x, y, rd.Subresource(0, 0, 0), rd.CompType.Typeless)
        p(f"== pixel {x},{y}: {len(hist)} modifications")
        for m in hist[-25:]:
            why = [f for f in FLAGS if getattr(m, f, False)]
            sh = m.shaderOut.col.floatValue; post = m.postMod.col.floatValue
            p(f"  draw#{ev2idx.get(m.eventId,'?')} eid={m.eventId} passed={m.Passed()} {' '.join(why)}"
              f" shader=({sh[0]:.3f},{sh[1]:.3f},{sh[2]:.3f},{sh[3]:.3f}) post=({post[0]:.3f},{post[1]:.3f},{post[2]:.3f},{post[3]:.3f})"
              f" depth={m.shaderOut.depth:.7f} preZ={m.preMod.depth:.7f} postZ={m.postMod.depth:.7f}")
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close(); rd.ShutdownReplay(); os._exit(0)
