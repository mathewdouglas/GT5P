# Run with qrenderdoc --python. RDOC_CAP, RDOC_OUT.
# Sample depth resources at frame end to distinguish real scene depth from
# an untouched single-sample buffer when the scene uses MSAA.
import os, traceback
import renderdoc as rd

out = open(os.environ["RDOC_OUT"], "w")
try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile()
    cf.OpenFile(os.environ["RDOC_CAP"], "", None)
    status, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    ctrl.SetFrameEvent(ctrl.GetRootActions()[-1].eventId, True)
    for t in ctrl.GetTextures():
        if not (t.creationFlags & rd.TextureCategory.DepthTarget):
            continue
        vals = []
        for y in (t.height // 4, t.height // 2, t.height * 3 // 4):
            for x in (t.width // 4, t.width // 2, t.width * 3 // 4):
                p = ctrl.PickPixel(t.resourceId, x, y, rd.Subresource(0, 0, 0), rd.CompType.Typeless)
                vals.append(float(p.floatValue[0]))
        out.write(f"{t.resourceId} {t.width}x{t.height} ms={t.msSamp} {t.format.Name()} {vals}\n")
        out.flush()
    ctrl.Shutdown()
    cf.Shutdown()
except Exception:
    out.write(traceback.format_exc())
finally:
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
