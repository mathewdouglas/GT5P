# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_texsave.py
# RDOC_CAP, RDOC_OUT (a folder), RDOC_DRAW. Saves every texture the draw's
# pixel shader reads (t0..t15) as PNG and prints their sizes and formats.
import os, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
outdir = os.environ["RDOC_OUT"]; os.makedirs(outdir, exist_ok=True)
want = int(os.environ["RDOC_DRAW"])
log = open(os.path.join(outdir, "textures.txt"), "w")

def p(*a):
    log.write(" ".join(str(x) for x in a) + "\n"); log.flush()

def actions_flat(acts, res):
    for a in acts:
        if a.flags & rd.ActionFlags.Drawcall:
            res.append(a)
        actions_flat(a.children, res)
    return res

try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile(); cf.OpenFile(cap_path, "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    draws = actions_flat(ctrl.GetRootActions(), [])
    ctrl.SetFrameEvent(draws[want].eventId, True)
    st = ctrl.GetPipelineState()
    texs = {t.resourceId: t for t in ctrl.GetTextures()}
    for ub in st.GetReadOnlyResources(rd.ShaderStage.Pixel):
        rid = ub.descriptor.resource
        if rid == rd.ResourceId.Null() or rid not in texs:
            continue
        t = texs[rid]
        p("slot", ub.access.index, rid, t.width, t.height, t.format.Name())
        s = rd.TextureSave(); s.resourceId = rid; s.destType = rd.FileType.PNG
        s.alpha = rd.AlphaMapping.Discard
        ctrl.SaveTexture(s, os.path.join(outdir, "t%d.png" % ub.access.index))
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    log.close(); rd.ShutdownReplay(); os._exit(0)
