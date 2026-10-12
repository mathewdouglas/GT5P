#!/usr/bin/env python3
"""Recognise a boot that went wrong during sound start-up.

About one BCUS98158 boot in six does (docs/progress.md, Phase 18). Such a run
says nothing about whatever is being measured, so boot.py and soak.py throw it
away and boot again rather than report it as a result.

A run is judged from its [mainstack] samples, which need GT5P_MAINSTACK set.
`lr` is the main thread's last call site:

  * some call sites are only ever reached in a bad run;
  * others are passed through by every run, and mean a stall only when main is
    still there a full sample later.
"""
import re

# lr -> what it is. Reached only when the run has already gone wrong.
ALWAYS_BAD = {
    0x007A9BE4: "runaway sound-bank fixup (func_007CA908)",
    0x00B3BBA8: "allocation retried for ever (func_00B3BB60)",
    0x00B3BA4C: "allocation retried for ever (func_00B3BA10)",
    0x00B56EDC: "lock on a corrupt object retried for ever (func_00B56EB4)",
}
# lr -> what it is. Bad only if two consecutive samples agree.
BAD_IF_STUCK = {
    0x007FEB28: "sound job event never arrives (func_007FE9E0)",
    0x00B577A0: "sleep loop under func_00BFA3C8 (func_00B57790)",
    0x0067E990: "main stalled in func_0067E930 (seen with the render thread calling a null vtable)",
}

_SAMPLE = re.compile(r"\[mainstack\] in=(func_[0-9A-F]+) sp=\S+ lr=0x([0-9A-F]+)")


def samples(err_text):
    """[(function main is in, lr)] for each main-thread sample, in order."""
    return [(m.group(1), int(m.group(2), 16)) for m in _SAMPLE.finditer(err_text)]


def bad_reason(err_text):
    """Why this run is one of the known bad boots, or None."""
    s = samples(err_text)
    if not s:
        return None
    if any(fn == "func_007CA908" for fn, _ in s):
        return ALWAYS_BAD[0x007A9BE4]
    lr = s[-1][1]
    if lr in ALWAYS_BAD:
        return ALWAYS_BAD[lr]
    if lr in BAD_IF_STUCK and len(s) >= 2 and s[-2][1] == lr:
        return BAD_IF_STUCK[lr]
    return None


def last_lr(err_text):
    s = samples(err_text)
    return "0x%08X" % s[-1][1] if s else "-"
