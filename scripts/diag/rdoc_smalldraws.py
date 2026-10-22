# Run inside qrenderdoc: qrenderdoc.exe --python scripts/diag/rdoc_smalldraws.py
# RDOC_CAP, RDOC_OUT. Every draw whose viewport covers at most RDOC_MAXPX
# pixels (default 1024): its viewport, colour target, the target's size and
# format, and its bound textures. Finds a title's luminance reduction chain,
# whose last levels the CPU reads back.
import os, traceback
import renderdoc as rd
out = open(os.environ["RDOC_OUT"], "w")
maxpx = int(os.environ.get("RDOC_MAXPX", "1024"))
def p(*a):
    out.write(" ".join(str(x) for x in a) + "\n"); out.flush()
def flat(acts, res):
    for a in acts:
        if a.flags & rd.ActionFlags.Drawcall: res.append(a)
        flat(a.children, res)
    return res
try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile(); cf.OpenFile(os.environ["RDOC_CAP"], "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    tex = {t.resourceId: t for t in ctrl.GetTextures()}
    for k, a in enumerate(flat(ctrl.GetRootActions(), [])):
        ctrl.SetFrameEvent(a.eventId, False)
        st = ctrl.GetPipelineState()
        vp = st.GetViewport(0)
        if vp.width * vp.height > maxpx: continue
        outs = [o for o in st.GetOutputTargets() if o.resource != rd.ResourceId.Null()]
        desc = []
        for o in outs:
            t = tex.get(o.resource)
            desc.append(f"{o.resource} {t.width}x{t.height} {t.format.Name()}" if t else str(o.resource))
        srcs = []
        for s in st.GetReadOnlyResources(rd.ShaderStage.Fragment):
            t = tex.get(s.descriptor.resource)
            if t: srcs.append(f"{s.descriptor.resource} {t.width}x{t.height} {t.format.Name()}")
        p(f"draw {k} eid {a.eventId} vp {vp.x:.0f},{vp.y:.0f} {vp.width:.0f}x{vp.height:.0f} "
          f"-> {'; '.join(desc)} <- {'; '.join(srcs)}")
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close(); rd.ShutdownReplay(); os._exit(0)
