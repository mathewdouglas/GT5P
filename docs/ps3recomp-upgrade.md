# ps3recomp v0.18.0 integration

This branch pins upstream `v0.18.0`, commit
`4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514`, plus a GT5P compatibility
patch. The pin, repository URL, checkout directory and patch path are in
[`config/ps3recomp.json`](../config/ps3recomp.json).

## Set up and build

```powershell
.venv\Scripts\python scripts\setup_runtime.py
.venv\Scripts\python scripts\setup_runtime.py --check
$env:CMAKE_BUILD_PARALLEL_LEVEL = "2"
scripts\build.cmd -DGT5P_TARGET=BCUS98158
```

The default checkout is `../ps3recomp-gt5p-v018`. `PS3RECOMP_DIR` overrides
the path for setup, building, the lift scripts and runtime fixture tests.
Setup never resets or stashes an existing dirty checkout. It checks whether
the patch is already present before applying anything.

The older `../ps3recomp-gt5p-master` checkout and the `../ps3recomp` junction
are left alone. They also serve the GT5 branch. The original
`patches/ps3recomp-5244db9-local.patch` is retained for older GT5P branches;
do not apply it over v0.18.0.

## What was reviewed

Upstream changed 542 files relative to `5244db9`. Areas affecting this port
include the PPU/SPU lifters, generated HLE registrations, callback plumbing,
memory mapper, reservation/coherency tracking, streamed SPU dispatch,
shader interfaces, texture decoding and generic graphics backends.

The integration is not stock v0.18.0. GT5P still needs its D3D12 renderer,
FIFO/command adaptations, codec callback implementation and SPURS policy
scheduler. These contain the measured fixes for its ring-space deadlocks,
audio service and render jobs. Combining halves of the two schedulers would
be unsafe; those title-specific implementations are carried as complete
compatibility overrides. The optimized SPU helper/float and diagnostic-aware
chained-dispatch implementation is retained as well. Upstream Vulkan and
Metal are not enabled by this upgrade.

The fragment decompiler is merged with upstream's extended APIs while
preserving GT5P's operand precision handling. Its legacy packed volume-unit
mask is converted to upstream's separate volume mask at the older entry
points. Upstream's explicit volume, shadow, colour and depth-export entry
points remain available. The retained D3D12 backend unwraps upstream's WPOS
helper before applying its own native-resolution/window-position conversion;
the two constant-buffer layouts must not be mixed. The volume texture decoder is retained alongside
upstream's component interpretation helpers.

Reservation tracking uses upstream's dynamically owned context registry and
published bitmap. Lifted PPU code uses upstream's inline memory model and
that same bitmap, rather than stacking the previous port shim over it.
`GT5P_VM_INLINE=OFF` at build time and `VM_INLINE=0` at launch retain the
out-of-line rollback. The port's optional row logging is preserved. Upstream's private MFC contexts
and residency-aware lookup remain, with compatibility for the port's cached
dispatch and stack-reset registrations. The port keeps its GETLLAR snapshot
under the shared reservation lock. Its policy poll counters remain process
variables: declaring them thread-local in the merged channel code linked
successfully but crashed at dispatch, so that storage ABI is kept consistent.
Controller polling uses the upstream pad mutex consistently with the retained
SDL owner thread; it must not acquire the old lock and release a different one.

The PPU loader retains the deferred condition-callback delivery and per-thread
callback-stack override, and adds upstream's explicit-target indirect-call
entry point. Generic memory mapping uses upstream's bounded allocation paths.
The per-transfer repeat watchdog uses elapsed time, with the port's longer
120-second default to accommodate initial shader preparation.

## Regeneration and rollback

Both PPU and SPU sources must be re-lifted when changing runtime generations.
Follow the disc-build commands in README with
`T=../ps3recomp-gt5p-v018/tools`, including all four required post-lift tools:
`setjmp_patch.py`, `spin_patch.py`, `ui_mask_patch.py`, and (after the SPU
lift) `spu_native_patch.py`. Derived game code stays ignored.

For local rollback evidence, the pre-upgrade executable and generated tree
are retained in `scratch/upgrade-v018/`. Switching the Git branch alone does
not restore ignored generated code or the built executable. Restore the
matching generated tree, select the older runtime and rebuild when returning
to the older branch. Preserve `shadercache/`.

To refresh the new runtime patch, use Bash and include the index:

```bash
cd ../ps3recomp-gt5p-v018
git diff --binary HEAD > ../GT5P/patches/ps3recomp-4e8f3ca8-local.patch
git apply --check -R ../GT5P/patches/ps3recomp-4e8f3ca8-local.patch
```

## Validation

The runtime overlay applies to a clean checkout at the pinned SHA, and setup
recognizes it on repeat runs. An unrelated dirty checkout is refused. The old
shared runtime's source diff is byte-identical to its pre-upgrade backup.

The re-lift emits 50,064 PPU functions and 9,115 SPU functions. The one fewer
PPU entry is an interior epilogue now represented by a local label in its
parent; the SPU workload registry is unchanged. Spin-wait, UI-mask and native
SPU hooks were reapplied. Game-derived code and binary evidence stay ignored.

Runtime fixtures passed: volume texture decoding and GPU sampling, fragment
source-range rendering, upper-unit coordinates/samplers, depth-clear reuse,
async pipeline scheduling, shader-job table ownership, deferred condition
callbacks, SPURS job arguments, native audio math, SDL hotplug and WASAPI
recovery, and debug-export gating/fault handling. Upstream's lock-line
coherency fixture passed 195 assertions through the PPU store path.

At 1080p / 2x MSAA / VSync, the Acura page rendered at 29.5 FPS. A warmed
60-second High Speed Ring test measured 57.9 mean FPS (title median 60),
16.7 ms median frame interval, 30.6 ms p99, 200.5 ms maximum and 2.6% over
20 ms; FIFO walk was 6.25 ms/frame. This is a compatibility result, not a
claimed speedup over the earlier 59.1 FPS run. Some driver pipelines were
still first encounters. Bulk startup/race prewarm was disabled for the
steady-state measurement; the shader cache was preserved. The first race
run had much heavier new shader/recipe preparation and averaged 39.0 FPS.

Two initial startup checks had long VSync-associated GPU-fence waits. These
were not reproduced after the diagnostic rebuild in repeated live runs;
the root cause remains unproven. `RSX_PRESENT_DIAG=1` adds Present results,
call time, GPU timestamps and foreground state for further reports. The
saved pre-upgrade executable remains available for an exact local A/B.

Daytona loaded into the race and measured a title median of 58 FPS over its
20-second smoke sample. The opening movie rendered changing frames through
FFmpeg at 1080p (avcodec-61.dll). Shader-preload integration passed all four
valid/damaged, blocking/background cases. Its fixture now selects recent
recipes learned by the smoke run, rather than arbitrary oldest cache entries
which may belong to earlier root-signature generations. Invalid-input cases
remain explicit and the source cache is never modified by that fixture.

No long race soak or claim of fixing all existing stutters is made here.
Local live evidence: `scratch/pv/upgrade-v018-*`; setup/build/fixture evidence
and the pre-upgrade executable/generated tree: `scratch/upgrade-v018/`.
