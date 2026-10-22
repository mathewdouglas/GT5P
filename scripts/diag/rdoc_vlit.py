# Run inside qrenderdoc: qrenderdoc.exe --python scripts/diag/rdoc_vlit.py
# For every draw whose fragment shader reads v7 times
# fp_constants[0] (vertex-light materials), print fp_constants[0..5].
# RDOC_CAP, RDOC_OUT.
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
    dis_cache = {}
    tgt = ctrl.GetDisassemblyTargets(True)[0]
    seen = collections.Counter()
    for k, a in enumerate(draws):
        ctrl.SetFrameEvent(a.eventId, False)
        st = ctrl.GetPipelineState()
        refl = st.GetShaderReflection(rd.ShaderStage.Fragment)
        if refl is None: continue
        sid = st.GetShader(rd.ShaderStage.Fragment)
        if sid not in dis_cache:
            d = ctrl.DisassembleShader(st.GetGraphicsPipelineObject(), refl, tgt)
            dis_cache[sid] = ("v7.xyzx, fp_constants[0]" in d) or ("v7.xyzx, fp_constants[0].xyzx" in d)
        if not dis_cache[sid]: continue
        for bi, cb in enumerate(refl.constantBlocks):
            if "Constants" not in cb.name: continue
            off = None
            for v in cb.variables:
                if v.name == "fp_constants": off = v.byteOffset
            d = st.GetConstantBlock(rd.ShaderStage.Fragment, bi, 0).descriptor
            data = ctrl.GetBufferData(d.resource, d.byteOffset + (off or 0), 96)
            fl = struct.unpack_from("24f", data)
            key = tuple(round(x, 4) for x in fl[0:3])
            seen[(str(sid), key)] += 1
            if seen[(str(sid), key)] <= 2:
                p(f"draw {k} eid {a.eventId} fs {sid} off {off} c0..c5:",
                  " | ".join(" ".join(f"{x:.4g}" for x in fl[i*4:i*4+4]) for i in range(6)))
    p("summary (shader, c0.xyz): count")
    for kk, n in seen.most_common(): p(" ", kk, n)
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close(); rd.ShutdownReplay(); os._exit(0)
