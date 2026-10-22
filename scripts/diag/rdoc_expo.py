# Run inside qrenderdoc: qrenderdoc.exe --python scripts/diag/rdoc_expo.py
# RDOC_CAP, RDOC_OUT. Histogram of (x,x,x,10) vec4s in every draw's fragment
# constants: the title's main-view exposure (0.4 in High Speed Ring races).
import os, struct, traceback, collections
import renderdoc as rd
out = open(os.environ["RDOC_OUT"], "w")
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
    draws = flat(ctrl.GetRootActions(), [])
    hist = collections.Counter(); w10 = collections.Counter()
    for k, a in enumerate(draws):
        ctrl.SetFrameEvent(a.eventId, False)
        st = ctrl.GetPipelineState()
        refl = st.GetShaderReflection(rd.ShaderStage.Fragment)
        if refl is None: continue
        for bi, cb in enumerate(refl.constantBlocks):
            if "Constants" not in cb.name: continue
            d = st.GetConstantBlock(rd.ShaderStage.Fragment, bi, 0).descriptor
            if d.resource == rd.ResourceId.Null(): continue
            data = ctrl.GetBufferData(d.resource, d.byteOffset, min(d.byteSize or 4096, 4096))
            fl = struct.unpack_from(f"{len(data)//4}f", data)
            for v in range(len(fl)//4):
                x, y, z, w = fl[v*4:v*4+4]
                if abs(w - 10.0) < 1e-3 and x == y == z and 0 < x < 1000:
                    hist[round(x, 5)] += 1
                    w10[k] = 1
    p("draws", len(draws), "draws with (x,x,x,10):", len(w10))
    for x, n in hist.most_common(20): p(" x=", x, "count", n)
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close(); rd.ShutdownReplay(); os._exit(0)
