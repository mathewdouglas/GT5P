# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_vsall.py
# RDOC_CAP, RDOC_OUT, RDOC_LAST (how many of the last draws, default 60).
# For each draw: viewport, target size, and every post-VS output of its
# first vertex (all floats of the stride), to read interpolants such as
# the vertex colour.
import os, struct, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out = open(os.environ.get("RDOC_OUT", cap_path + ".vsall.txt"), "w")
last = int(os.environ.get("RDOC_LAST", "60"))

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
    cf.OpenFile(cap_path, "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    draws = actions_flat(ctrl.GetRootActions(), [])
    p("draws", len(draws))
    names = {}
    for t in ctrl.GetTextures():
        names[t.resourceId] = f"{t.width}x{t.height}"
    for k in range(max(0, len(draws) - last), len(draws)):
        a = draws[k]
        ctrl.SetFrameEvent(a.eventId, True)
        st = ctrl.GetPipelineState()
        outs = st.GetOutputTargets()
        rt = outs[0].resource if outs else rd.ResourceId.Null()
        vp = st.GetViewport(0)
        mesh = ctrl.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        line = f"draw {k} eid={a.eventId} n={a.numIndices} rt={names.get(rt, rt)} vp=({vp.x:.0f},{vp.y:.0f},{vp.width:.0f}x{vp.height:.0f})"
        if mesh.vertexResourceId == rd.ResourceId.Null() or not mesh.vertexByteStride:
            p(line, "no post-VS data"); continue
        data = ctrl.GetBufferData(mesh.vertexResourceId, mesh.vertexByteOffset, mesh.vertexByteStride)
        fl = struct.unpack_from(f"{len(data)//4}f", data)
        p(line, "v0:", " ".join(f"{x:.4g}" for x in fl))
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
