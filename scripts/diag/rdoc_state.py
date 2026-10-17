# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_state.py
# RDOC_CAP, RDOC_OUT, RDOC_DRAWS (comma list of draw indices among draw
# actions). Writes the D3D12 state that can stop a draw from reaching its
# target: viewports, scissors, rasterizer, depth-stencil, blend, targets.
import os, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out = open(os.environ.get("RDOC_OUT", cap_path + ".state.txt"), "w")
want = [int(x) for x in os.environ.get("RDOC_DRAWS", "0").split(",") if x.strip()]

def p(*a):
    out.write(" ".join(str(x) for x in a) + "\n"); out.flush()

def dump(obj, name, depth=0, seen=None):
    """Print an object's public, non-callable attributes, a few levels deep."""
    if depth > 3:
        return
    pad = "  " * depth
    for k in dir(obj):
        if k.startswith("_"):
            continue
        try:
            v = getattr(obj, k)
        except Exception:
            continue
        if callable(v):
            continue
        if isinstance(v, (int, float, str, bool)) or v is None or type(v).__name__ in ("ResourceId",) or "Enum" in type(v).__bases__[0].__name__ if type(v).__bases__ else False:
            p(f"{pad}{name}.{k} = {v}")
        elif isinstance(v, (list, tuple)):
            for i, e in enumerate(v[:4]):
                if isinstance(e, (int, float, str, bool)):
                    p(f"{pad}{name}.{k}[{i}] = {e}")
                else:
                    dump(e, f"{name}.{k}[{i}]", depth + 1)
        else:
            dump(v, f"{name}.{k}", depth + 1)

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
    for k in want:
        a = draws[k]
        ctrl.SetFrameEvent(a.eventId, True)
        d3 = ctrl.GetD3D12PipelineState()
        p(f"===== draw {k} eid={a.eventId} {a.GetName(ctrl.GetStructuredFile())}")
        texs = {t.resourceId: t for t in ctrl.GetTextures()}
        def tex(rid):
            t = texs.get(rid)
            return f"{rid} {t.width}x{t.height} ms={t.msSamp} {t.format.Name()}" if t else f"{rid} (none)"
        for i, v in enumerate(d3.rasterizer.viewports):
            p(f"viewport[{i}] x={v.x} y={v.y} w={v.width} h={v.height} depth={v.minDepth}..{v.maxDepth} enabled={v.enabled}")
        for i, s in enumerate(d3.rasterizer.scissors):
            p(f"scissor[{i}] x={s.x} y={s.y} w={s.width} h={s.height} enabled={s.enabled}")
        st = d3.rasterizer.state
        p(f"rast cull={st.cullMode} depthClip={st.depthClip} sampleMask=0x{d3.rasterizer.sampleMask:X}")
        om = d3.outputMerger
        for i, rt in enumerate(om.renderTargets):
            if rt.resource != rd.ResourceId.Null():
                p(f"rt[{i}] {tex(rt.resource)} view fmt={rt.format.Name()}")
        p(f"depth {tex(om.depthTarget.resource)} view fmt={om.depthTarget.format.Name()} "
          f"test={om.depthStencilState.depthEnable} func={om.depthStencilState.depthFunction} "
          f"write={om.depthStencilState.depthWrites} stencil={om.depthStencilState.stencilEnable}")
        for i, b in enumerate(om.blendState.blends[:2]):
            p(f"blend[{i}] enabled={b.enabled} writeMask=0x{b.writeMask:X}")
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
