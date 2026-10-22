# Run inside qrenderdoc: qrenderdoc.exe --python scripts/diag/rdoc_debugpixel.py
# RDOC_CAP, RDOC_OUT (report), RDOC_EVENT, RDOC_PIXEL ("x,y"). Optional:
# RDOC_SAMPLE (default 0), RDOC_PRIMITIVE, RDOC_FIRST_INST (default 0).
# Prints interpolated inputs and register changes from pixel debugging.
# next_instruction is the instruction AFTER the changes printed below it.
# Keep the report in scratch/: it contains values derived from game data.
import os, traceback
import renderdoc as rd

out = open(os.environ["RDOC_OUT"], "w")
ctrl = cf = trace = None

def p(*args):
    out.write(" ".join(str(a) for a in args) + "\n")
    out.flush()

try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cf = rd.OpenCaptureFile()
    status = cf.OpenFile(os.environ["RDOC_CAP"], "", None)
    if status != rd.ResultCode.Succeeded:
        raise RuntimeError("Capture open failed: " + str(status))
    status, ctrl = cf.OpenCapture(rd.ReplayOptions(), None)
    if status != rd.ResultCode.Succeeded:
        raise RuntimeError("Capture replay failed: " + str(status))
    ctrl.SetFrameEvent(int(os.environ["RDOC_EVENT"]), True)
    x, y = (int(v) for v in os.environ["RDOC_PIXEL"].split(","))
    opts = rd.DebugPixelInputs()
    opts.sample = int(os.environ.get("RDOC_SAMPLE", "0"))
    if "RDOC_PRIMITIVE" in os.environ:
        opts.primitive = int(os.environ["RDOC_PRIMITIVE"])
    trace = ctrl.DebugPixel(x, y, opts)
    if not trace.debugger:
        raise RuntimeError("Pixel debugging unavailable for this event/pixel")
    for v in trace.inputs:
        p("input", v.name, list(v.value.f32v)[:max(4, v.columns * v.rows)])
    first = int(os.environ.get("RDOC_FIRST_INST", "0"))
    while True:
        states = ctrl.ContinueDebug(trace.debugger)
        if not states:
            break
        for state in states:
            if state.nextInstruction < first:
                continue
            p("next_instruction", state.nextInstruction, "step", state.stepIndex)
            for change in state.changes:
                v = change.after
                p(" ", v.name, list(v.value.f32v)[:max(4, v.columns * v.rows)])
except Exception:
    p(traceback.format_exc())
finally:
    if ctrl:
        if trace:
            ctrl.FreeTrace(trace)
        ctrl.Shutdown()
    if cf:
        cf.Shutdown()
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
