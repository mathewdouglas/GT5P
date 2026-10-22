# Run inside qrenderdoc (it carries the renderdoc module):
#   qrenderdoc.exe --python scripts\diag\rdoc_vsout.py
# Reads RDOC_CAP (capture path), RDOC_OUT (report path), RDOC_FIRST/RDOC_N
# (which draw actions, by index among draws), and writes for each draw its
# vertex count, render target, and the first vertices' clip-space position
# out of the vertex shader (post-VS data), plus their NDC.
import os, struct, sys, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out_path = os.environ.get("RDOC_OUT", cap_path + ".txt")
first = int(os.environ.get("RDOC_FIRST", "0"))
count = int(os.environ.get("RDOC_N", "8"))
out = open(out_path, "w")

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
    r = cf.OpenFile(cap_path, "", None)
    if r != rd.ResultCode.Succeeded:
        p("open failed", r); raise SystemExit
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    if r != rd.ResultCode.Succeeded:
        p("replay failed", r); raise SystemExit
    draws = actions_flat(ctrl.GetRootActions(), [])
    p("draw actions:", len(draws))
    for k in range(first, min(first + count, len(draws))):
        a = draws[k]
        ctrl.SetFrameEvent(a.eventId, True)
        st = ctrl.GetPipelineState()
        outs = st.GetOutputTargets()
        rt = outs[0].resource if outs else None
        vp = st.GetViewport(0)
        mesh = ctrl.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        line = f"draw {k} eid={a.eventId} n={a.numIndices} rt={rt} vp=({vp.x},{vp.y},{vp.width}x{vp.height})"
        if mesh.vertexResourceId == rd.ResourceId.Null():
            p(line, "no post-VS data"); continue
        data = ctrl.GetBufferData(mesh.vertexResourceId, mesh.vertexByteOffset, mesh.vertexByteStride * 4)
        vs = []
        for i in range(min(4, len(data) // max(mesh.vertexByteStride, 1))):
            x, y, z, w = struct.unpack_from("4f", data, i * mesh.vertexByteStride)
            ndc = (x / w, y / w, z / w) if w else (float("nan"),) * 3
            t3 = struct.unpack_from("4f", data, i * mesh.vertexByteStride + 112)
            t8 = struct.unpack_from("4f", data, i * mesh.vertexByteStride + 192)
            vs.append(f"ndc({ndc[0]:.3g},{ndc[1]:.3g}) tc3=({t3[0]:.4g},{t3[1]:.4g},{t3[2]:.4g},{t3[3]:.4g}) tc8=({t8[0]:.3g},{t8[1]:.3g},{t8[2]:.3g})")
        p(line, "stride", mesh.vertexByteStride, " ".join(vs))
    ctrl.Shutdown(); cf.Shutdown()
except SystemExit:
    pass
except Exception:
    p(traceback.format_exc())
finally:
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
