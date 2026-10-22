# Run inside qrenderdoc --python. RDOC_CAP, RDOC_OUT (text report),
# RDOC_DRAWS (comma-separated draw indices). Reports physical texture bytes,
# not a PNG's displayed RGB or a remapped shader sample. Payload stays in the
# capture; only hashes and small frequency summaries are written to the report.
# RDOC_BYTES_MAX defaults to 4096: larger resources are described but not read.
import collections
import hashlib
import os
import traceback

import renderdoc as rd


def draws(actions):
    for action in actions:
        if action.flags & rd.ActionFlags.Drawcall:
            yield action
        yield from draws(action.children)


out = open(os.environ['RDOC_OUT'], 'w', encoding='utf-8')
capture = controller = None
try:
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    capture = rd.OpenCaptureFile()
    status = capture.OpenFile(os.environ['RDOC_CAP'], '', None)
    if status != rd.ResultCode.Succeeded:
        raise RuntimeError('OpenFile: ' + str(status))
    status, controller = capture.OpenCapture(rd.ReplayOptions(), None)
    if status != rd.ResultCode.Succeeded:
        raise RuntimeError('OpenCapture: ' + str(status))
    selected = [int(n) for n in os.environ['RDOC_DRAWS'].split(',')]
    limit = int(os.environ.get('RDOC_BYTES_MAX', '4096'))
    textures = {t.resourceId: t for t in controller.GetTextures()}
    actions = list(draws(controller.GetRootActions()))
    for index in selected:
        action = actions[index]
        controller.SetFrameEvent(action.eventId, True)
        state = controller.GetPipelineState()
        reflection = state.GetShaderReflection(rd.ShaderStage.Pixel)
        out.write(f'draw={index} event={action.eventId}\n')
        for binding in state.GetReadOnlyResources(rd.ShaderStage.Pixel):
            descriptor = binding.descriptor
            texture = textures.get(descriptor.resource)
            if texture is None:
                continue
            slot = binding.access.index
            name = reflection.readOnlyResources[slot].name if reflection else str(slot)
            out.write(f'  {name}: {texture.resourceId} {texture.width}x{texture.height}x{texture.depth}'
                      f' format={texture.format.Name()} mips={texture.mips}'
                      f' view_mip={descriptor.firstMip} view_mips={descriptor.numMips}\n')
            # Conservative bound avoids reading large or compressed textures
            # merely to report that they exceed the limit. Their dimensions
            # and bindings are still useful in the report.
            if texture.width * texture.height * texture.depth * 4 > limit:
                continue
            data = bytes(controller.GetTextureData(
                texture.resourceId, rd.Subresource(descriptor.firstMip, 0, 0)))
            if len(data) > limit:
                continue
            words = collections.Counter(data[i:i + 4].hex()
                                        for i in range(0, len(data), 4))
            out.write(f'    bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()}'
                      f' distinct_4byte_groups={len(words)} common={words.most_common(4)}\n')
        out.flush()
except Exception:
    traceback.print_exc(file=out)
finally:
    if controller:
        controller.Shutdown()
    if capture:
        capture.Shutdown()
    out.close()
    rd.ShutdownReplay()
    os._exit(0)
