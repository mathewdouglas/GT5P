# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_pixhist.py
# RDOC_CAP, RDOC_OUT, RDOC_RT (resource id number of the target),
# RDOC_PIXELS ("x,y;x,y;..."). For each pixel, every event that touched it in
# the frame and why each fragment was or was not written.
import os, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out = open(os.environ.get("RDOC_OUT", cap_path + ".pix.txt"), "w")
rt_num = int(os.environ["RDOC_RT"])
pixels = [tuple(int(v) for v in s.split(",")) for s in os.environ.get("RDOC_PIXELS", "640,360").split(";") if s]

def p(*a):
    out.write(" ".join(str(x) for x in a) + "\n"); out.flush()

FLAGS = ["sampleMasked", "backfaceCulled", "depthClipped", "depthBoundsFailed", "viewClipped",
         "scissorClipped", "shaderDiscarded", "depthTestFailed", "stencilTestFailed",
         "predicationSkipped", "unboundPS", "directShaderWrite", "postMod"]

try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile()
    cf.OpenFile(cap_path, "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    tex = None
    for t in ctrl.GetTextures():
        if int(t.resourceId) == rt_num:
            tex = t
    if tex is None:
        p("no texture", rt_num); raise SystemExit
    last = ctrl.GetRootActions()[-1]
    ctrl.SetFrameEvent(last.eventId, True)
    for (x, y) in pixels:
        sub = rd.Subresource(0, 0, 0)
        hist = ctrl.PixelHistory(tex.resourceId, x, y, sub, rd.CompType.Typeless)
        p(f"== pixel {x},{y}: {len(hist)} modifications")
        for m in hist[:40]:
            why = [f for f in FLAGS if getattr(m, f, False)]
            post = m.postMod.col.floatValue
            p(f"  eid={m.eventId} prim={m.primitiveID} passed={m.Passed()} {' '.join(why)} "
              f"post=({post[0]:.3f},{post[1]:.3f},{post[2]:.3f},{post[3]:.3f}) depth={m.postMod.depth:.4f}")
    ctrl.Shutdown(); cf.Shutdown()
except SystemExit:
    pass
except Exception:
    p(traceback.format_exc())
finally:
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
