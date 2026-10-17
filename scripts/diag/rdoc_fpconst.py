# Run inside qrenderdoc: qrenderdoc.exe --python scripts\diag\rdoc_fpconst.py
# RDOC_CAP, RDOC_OUT. For an RPCS3 (Vulkan) capture: every draw's
# fragment-stage constant buffers, searched for a fragment program's embedded
# constants. RDOC_MATCH = "a,b,c;..." float triples that must appear in a
# block, in order (default: GT5P program 0x06C271C1's k1 0.15,0.15,0.15).
# Prints the matching draws' whole blocks (first 16 vec4s).
import os, struct, traceback
import renderdoc as rd

cap_path = os.environ["RDOC_CAP"]
out = open(os.environ.get("RDOC_OUT", cap_path + ".fpk.txt"), "w")
pat = [tuple(float(v) for v in s.split(",")) for s in os.environ.get("RDOC_MATCH", "0.15,0.15,0.15").split(";") if s]
limit = int(os.environ.get("RDOC_LIMIT", "12"))

def p(*a):
    out.write(" ".join(str(x) for x in a) + "\n"); out.flush()

def actions_flat(acts, res):
    for a in acts:
        if a.flags & rd.ActionFlags.Drawcall:
            res.append(a)
        actions_flat(a.children, res)
    return res

def near(a, b):
    return abs(a - b) <= 1e-4 * max(1.0, abs(b))

try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile()
    cf.OpenFile(cap_path, "", None)
    r, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    draws = actions_flat(ctrl.GetRootActions(), [])
    p("api", ctrl.GetAPIProperties().pipelineType, "draws", len(draws))
    found = 0
    only = os.environ.get("RDOC_DRAW")
    for k, a in enumerate(draws):
        if only and k != int(only):
            continue
        ctrl.SetFrameEvent(a.eventId, False)
        st = ctrl.GetPipelineState()
        refl = st.GetShaderReflection(rd.ShaderStage.Fragment)
        if refl is None:
            continue
        for bi, cb in enumerate(refl.constantBlocks):
            bind = st.GetConstantBlock(rd.ShaderStage.Fragment, bi, 0)
            desc = bind.descriptor
            if desc.resource == rd.ResourceId.Null():
                continue
            size = min(desc.byteSize if desc.byteSize else 4096, 4096)
            data = ctrl.GetBufferData(desc.resource, desc.byteOffset, size)
            fl = struct.unpack_from(f"{len(data)//4}f", data)
            ok = True; at = 0
            for t in pat:
                hit = -1
                for i in range(at, len(fl) - len(t) + 1):
                    if all(near(fl[i + j], t[j]) for j in range(len(t))):
                        hit = i; break
                if hit < 0:
                    ok = False; break
                at = hit + len(t)
            if not ok:
                continue
            if os.environ.get("RDOC_SCAN") and "Constants" in cb.name:
                full = ctrl.GetBufferData(desc.resource, desc.byteOffset, desc.byteSize)
                fv = struct.unpack_from(f"{len(full)//4}f", full)
                hits = 0
                for v in range(1, len(fv) // 4 - 4):
                    q = fv[v*4:v*4+4]
                    if near(q[0], 0.15) and near(q[1], 0.15) and near(q[2], 0.15) and near(q[3], 0.0):
                        hits += 1
                        if hits <= 12:
                            p(f"   fc[{v-1}..{v+3}] " + " | ".join(" ".join(f"{x:.6g}" for x in fv[u*4:u*4+4]) for u in range(v-1, v+4)))
                p(f"== scan draw {k} {cb.name}: {hits} matches of k1=(0.15,0.15,0.15,0)")
                continue
            if os.environ.get("RDOC_ALLBLOCKS"):
                p(f"== draw {k} block {bi} {cb.name} off={desc.byteOffset} size={desc.byteSize}")
                for v in range(min(int(os.environ.get("RDOC_VEC", "48")), len(fl) // 4)):
                    p(f"   [{v:3}] {fl[v*4]:.6g} {fl[v*4+1]:.6g} {fl[v*4+2]:.6g} {fl[v*4+3]:.6g}")
                continue
            found += 1
            p(f"== draw {k} eid={a.eventId} block {bi} '{cb.name}' bytes={len(data)} fs={st.GetShader(rd.ShaderStage.Fragment)}")
            for v in range(min(16, len(fl) // 4)):
                p(f"   [{v:2}] {fl[v*4]:.6g} {fl[v*4+1]:.6g} {fl[v*4+2]:.6g} {fl[v*4+3]:.6g}")
            break
        if found >= limit:
            break
    p("matched", found)
    ctrl.Shutdown(); cf.Shutdown()
except Exception:
    p(traceback.format_exc())
finally:
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
