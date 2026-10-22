# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_vfetch.py
# RDOC_CAP, RDOC_OUT, RDOC_DRAW. Dumps the vertex stage's constant blocks
# whose name contains RDOC_BLOCK (default "VFetch") as hex words.
import os, struct, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out = open(os.environ["RDOC_OUT"], "w")
want = int(os.environ["RDOC_DRAW"]); bname = os.environ.get("RDOC_BLOCK", "VFetch")

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
    cf = rd.OpenCaptureFile(); cf.OpenFile(cap_path, "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    draws = actions_flat(ctrl.GetRootActions(), [])
    ctrl.SetFrameEvent(draws[want].eventId, True)
    st = ctrl.GetPipelineState()
    refl = st.GetShaderReflection(rd.ShaderStage.Vertex)
    for bi, cb in enumerate(refl.constantBlocks):
        if bname not in cb.name:
            continue
        d = st.GetConstantBlock(rd.ShaderStage.Vertex, bi, 0).descriptor
        data = ctrl.GetBufferData(d.resource, d.byteOffset, min(d.byteSize or 512, 512))
        w = struct.unpack_from("<%dI" % (len(data) // 4), data)
        p("block", cb.name, "size", len(data))
        for i in range(0, len(w), 8):
            p("  [%3d] " % i + " ".join("%08X" % x for x in w[i:i+8]))
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close(); rd.ShutdownReplay(); os._exit(0)
