# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_texsave.py
# RDOC_CAP, RDOC_OUT (a folder), RDOC_DRAW. Saves every texture the draw's
# pixel shader reads as PNG and prints resource/view mip counts as well as
# sizes and formats. File indices are reflection indices, not necessarily
# texture registers. RDOC_MIPS=1 also saves each resource's lower mip levels.
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
        p("resource_index", ub.access.index, rid, t.width, t.height, t.format.Name(),
          "resource_mips", t.mips, "view_mips", ub.descriptor.numMips,
          "first_mip", ub.descriptor.firstMip)
        s = rd.TextureSave(); s.resourceId = rid; s.destType = rd.FileType.PNG
        s.alpha = rd.AlphaMapping.Discard
        ctrl.SaveTexture(s, os.path.join(outdir, "t%d.png" % ub.access.index))
        if os.environ.get("RDOC_MIPS") == "1":
            for mip in range(1, t.mips):
                s.mip = mip
                ctrl.SaveTexture(s, os.path.join(outdir, "t%d_m%d.png" % (ub.access.index, mip)))
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    log.close(); rd.ShutdownReplay(); os._exit(0)
