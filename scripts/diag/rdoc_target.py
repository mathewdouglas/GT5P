# Inspect the first draws writing a target: RDOC_CAP, RDOC_OUT (directory),
# RDOC_TARGET (numeric resource id) or RDOC_DRAWS (draw indices), RDOC_N
# (default 2). Derived dumps stay
# in the ignored output directory, never beside this script.
import os, struct, traceback
import renderdoc as rd

folder = os.environ["RDOC_OUT"]
os.makedirs(folder, exist_ok=True)
log = open(os.path.join(folder, "report.txt"), "w")
def p(*args):
    log.write(" ".join(str(a) for a in args) + "\n")
    log.flush()
def flatten(actions):
    result = []
    for a in actions:
        if a.flags & rd.ActionFlags.Drawcall:
            result.append(a)
        result.extend(flatten(a.children))
    return result
try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile()
    cf.OpenFile(os.environ["RDOC_CAP"], "", None)
    status, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    textures = {t.resourceId: t for t in ctrl.GetTextures()}
    want = int(os.environ.get("RDOC_TARGET", "0"))
    indices = {int(i) for i in os.environ.get("RDOC_DRAWS", "").split(",") if i}
    selected = [(i,a) for i,a in enumerate(flatten(ctrl.GetRootActions()))
                if (i in indices if indices else any(int(o) == want for o in a.outputs))]
    p("draws", [(i,a.eventId,a.numIndices) for i,a in selected])
    shaders = set()
    for i,a in selected[:int(os.environ.get("RDOC_N", "2"))]:
        ctrl.SetFrameEvent(a.eventId, True)
        st = ctrl.GetPipelineState()
        p("draw", i, "event", a.eventId)
        for stage in (rd.ShaderStage.Vertex, rd.ShaderStage.Pixel):
            refl = st.GetShaderReflection(stage)
            if refl is None or refl.resourceId in shaders:
                continue
            shaders.add(refl.resourceId)
            p(stage, ctrl.DisassembleShader(st.GetGraphicsPipelineObject(), refl, ""))
        for ub in st.GetReadOnlyResources(rd.ShaderStage.Pixel):
            rid = ub.descriptor.resource
            if rid not in textures:
                continue
            t = textures[rid]
            p("texture", ub.access.index, rid, t.width, t.height, t.format.Name())
            s = rd.TextureSave()
            s.resourceId = rid
            s.destType = rd.FileType.PNG
            s.alpha = rd.AlphaMapping.Discard
            ctrl.SaveTexture(s, os.path.join(folder, f"d{i}_t{ub.access.index}.png"))
        refl = st.GetShaderReflection(rd.ShaderStage.Pixel)
        if refl:
            for bi,cb in enumerate(refl.constantBlocks):
                d = st.GetConstantBlock(rd.ShaderStage.Pixel, bi, 0).descriptor
                if d.resource == rd.ResourceId.Null():
                    continue
                data = ctrl.GetBufferData(d.resource, d.byteOffset, min(d.byteSize, cb.byteSize, 4352))
                vals = struct.unpack(f"{len(data)//4}f", data)
                p("constants", cb.name, vals)
    ctrl.SetFrameEvent(ctrl.GetRootActions()[-1].eventId, True)
    for rid,t in textures.items():
        if int(rid) == want:
            s = rd.TextureSave()
            s.resourceId = rid
            s.destType = rd.FileType.PNG
            s.alpha = rd.AlphaMapping.Discard
            ctrl.SaveTexture(s, os.path.join(folder, "target.png"))
    ctrl.Shutdown()
    cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    log.close()
    rd.ShutdownReplay()
    os._exit(0)
