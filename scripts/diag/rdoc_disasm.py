# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_disasm.py
# RDOC_CAP, RDOC_OUT, RDOC_DRAW (index among draw actions).
# Writes the vertex and fragment shader disassembly of that draw, and the
# vertex inputs of its first vertex.
import os, struct, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out = open(os.environ.get("RDOC_OUT", cap_path + ".dis.txt"), "w")
want = int(os.environ["RDOC_DRAW"])

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
    a = draws[want]
    ctrl.SetFrameEvent(a.eventId, True)
    st = ctrl.GetPipelineState()
    targets = ctrl.GetDisassemblyTargets(True)
    p("targets", list(targets))
    pipe = st.GetGraphicsPipelineObject()
    for stage in (rd.ShaderStage.Vertex, rd.ShaderStage.Fragment):
        refl = st.GetShaderReflection(stage)
        if refl is None:
            p("no", stage); continue
        p("=====", stage, "inputs:", [(s.semanticName, s.semanticIndex, s.regIndex) for s in refl.inputSignature])
        p("outputs:", [(s.semanticName, s.semanticIndex, s.regIndex) for s in refl.outputSignature])
        p(ctrl.DisassembleShader(pipe, refl, targets[0]))
    mesh = ctrl.GetPostVSData(0, 0, rd.MeshDataStage.VSIn)
    p("vsin stride", mesh.vertexByteStride)
    for vb in st.GetVBuffers():
        if vb.resourceId != rd.ResourceId.Null():
            d = ctrl.GetBufferData(vb.resourceId, vb.byteOffset, min(vb.byteStride * 2 or 64, 256))
            p("vb", vb.resourceId, "stride", vb.byteStride, d.hex())
    for ia in st.GetVertexInputs():
        p("vin", ia.name, ia.vertexBuffer, ia.byteOffset, ia.format.Name(), "generic" if ia.genericEnabled else "", list(ia.genericValue.f32v) if ia.genericEnabled else "")
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
