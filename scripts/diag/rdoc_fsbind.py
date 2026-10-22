# Run inside qrenderdoc: lists, for draws RDOC_FIRST..+RDOC_N, the fragment
# shader's constant blocks and read-only / read-write resources by name, and
# the output target, to learn where a capture keeps fragment constants.
import os, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out = open(os.environ.get("RDOC_OUT", cap_path + ".fsbind.txt"), "w")
first = int(os.environ.get("RDOC_FIRST", "0")); count = int(os.environ.get("RDOC_N", "6"))

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
    sf = ctrl.GetStructuredFile()
    for k in range(first, min(first + count, len(draws))):
        a = draws[k]
        ctrl.SetFrameEvent(a.eventId, False)
        st = ctrl.GetPipelineState()
        refl = st.GetShaderReflection(rd.ShaderStage.Fragment)
        outs = st.GetOutputTargets()
        p(f"== draw {k} eid={a.eventId} {a.GetName(sf)} n={a.numIndices} rt={outs[0].resource if outs else None}")
        if refl is None:
            p("   no fragment shader"); continue
        for i, cb in enumerate(refl.constantBlocks):
            p(f"   cblock {i} '{cb.name}' bytes={cb.byteSize} vars={[v.name for v in cb.variables][:8]}")
        for i, ro in enumerate(refl.readOnlyResources):
            p(f"   ro {i} '{ro.name}' {ro.textureType}")
        for i, rw in enumerate(refl.readWriteResources):
            p(f"   rw {i} '{rw.name}' {rw.textureType}")
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
