# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_saverts.py
# RDOC_CAP, RDOC_OUT (folder). At the end of the frame, saves every colour
# target of at least 640x360 as PNG (one-sample ones only), named by size.
import os, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]; outdir = os.environ["RDOC_OUT"]; os.makedirs(outdir, exist_ok=True)
log = open(os.path.join(outdir, "saved.txt"), "w")

def actions_flat(acts, res):
    for a in acts:
        res.append(a); actions_flat(a.children, res)
    return res

try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile(); cf.OpenFile(cap_path, "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    acts = actions_flat(ctrl.GetRootActions(), [])
    ctrl.SetFrameEvent(acts[-1].eventId, True)
    n = 0
    for t in ctrl.GetTextures():
        if t.width >= 640 and t.height >= 360 and t.msSamp <= 1 and (t.creationFlags & rd.TextureCategory.ColorTarget):
            s = rd.TextureSave(); s.resourceId = t.resourceId; s.destType = rd.FileType.PNG
            s.alpha = rd.AlphaMapping.Discard
            name = os.path.join(outdir, "rt_%d_%dx%d.png" % (int(t.resourceId), t.width, t.height))
            ctrl.SaveTexture(s, name); n += 1
            log.write(name + "\n")
    log.write("saved %d\n" % n)
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    log.write(traceback.format_exc())
finally:
    log.close(); rd.ShutdownReplay(); os._exit(0)
