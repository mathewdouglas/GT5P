# Offline game shader preparation

For measured asset/raw-program coverage, recipe dependency checks and the
remaining provenance gap, see [shader coverage audit](shader-coverage.md).

`scripts/precompile_shaders.py` reads embedded `SHDS` fragment programs from
the local executable and unpacked game assets, then runs the production
translator/compiler before guest entry. It writes ordinary DXBC entries to
the same shadercache used during play. It is separate from F1's **Preload
known shaders**, which prepares previously recorded native pipelines during startup.

Keep the shader cache enabled. Close the game before compiling. All extracted
programs, bytecode, source indexes and logs remain local and must not be
committed or distributed with the port.

## Full asset pass

Use [GTToolsSharp](https://github.com/Nenkai/GTToolsSharp/releases) to unpack
your own `GT.VOL`. The tool is an external dependency; this repository does
not include its executable, keys or source. Either provide its executable:

```powershell
.venv\Scripts\python scripts\precompile_shaders.py --unpacker C:\Tools\GTToolsSharp.exe
```

Or point at an existing unpacked directory:

```powershell
.venv\Scripts\python scripts\precompile_shaders.py --assets C:\Games\GT5P-extracted
```

The wrapper's unpacker invocation writes intermediate assets and third-party
tool output into ignored `scratch/`. It does not alter the game dump. The
executable is also scanned, regardless of the assets option.

For better coverage, first play representative menus and races on this build.
The renderer learns shader-affecting state profiles in
`shadercache/fp-profiles-v2/`. The offline pass applies learned profiles to
file programs with matching texture-unit usage. This can prepare unvisited
content using states observed elsewhere. With no learned profiles, only
base 16/32-bit export variants are prepared; a base-only pass showed almost
no reduction in the measured dealership route.

Up to 64 learned profiles are used by default. For more coverage:

```powershell
.venv\Scripts\python scripts\precompile_shaders.py --compile-only --profile-limit 256
```

`--compile-only` reuses `shadercache/library-v1/all/`; extraction is unnecessary
on every run. It also resumes safely after interruption: completed DXBC
entries remain usable. Existing shadercache files are never removed.

For an even broader, substantially slower cross-product of states and programs:

```powershell
.venv\Scripts\python scripts\precompile_shaders.py --compile-only --profile-limit 256 --all-profile-combinations
```

Normal shader compiler worker configuration (`RSX_SHADER_WORKERS`) also applies.
The job table now defaults to 65,536 slots: the former 16,384 slots forced
large passes into serial compilation once full. `RSX_SHADER_JOB_SLOTS=16384`
restores that limit; values are rounded down to a power of two between
1,024 and 131,072. The table occupies a bounded amount of memory.
The source queue is bounded to about 64 jobs; parallel compilation can still
consume CPU and memory. Progress is printed in the terminal and window title.
`shadercache/precompile.log` contains the summary and bounded failure details.
The program exits after preparation; it does not start the game.

## Smaller passes and checks

```powershell
# Executable only, without unpacking assets:
.venv\Scripts\python scripts\precompile_shaders.py --scope executable

# Extract/index without compiling:
.venv\Scripts\python scripts\precompile_shaders.py --assets C:\Games\GT5P-extracted --catalog-only

# Separate cache for experiments, without touching the player's cache:
.venv\Scripts\python scripts\precompile_shaders.py --scope executable --cache scratch\shader-test

# Maximum programs in one pass (up to 16384):
.venv\Scripts\python scripts\precompile_shaders.py --compile-only --limit 128
```

Extraction records bounds-checked SHDS table entries and deduplicates identical
payloads. The local index lists source filenames and offsets for diagnosis.
The native reader separately validates file size, alignment and termination.
Failed programs/variants are skipped and reported as partial coverage.

The catalog directories for `all` and `executable` are separate. An optional
`--catalog PATH` overrides the directory. The supported layout was checked
against this disc build; other builds are unverified. The SHDS layout was
researched using [PDTools' public readers](https://github.com/Nenkai/PDTools/tree/master/PDTools.Files/Models/Shaders)
and checked against local runtime shader bytes.

Tests:

```powershell
.venv\Scripts\python scripts\test\shader_library.py
.venv\Scripts\python scripts\test\shader_library_runtime.py
.venv\Scripts\python scripts\test\shader_job_table.py
```

The first uses synthetic containers. The second requires the local game/build
and uses an isolated scratch cache to verify real compilation, repeat-cache
reuse, bad inputs and profile filtering. The third exercises the production
job-table helpers at their default, legacy and clamped capacities.

## Remaining compilation

This is not an exhaustive shader/pipeline database. Vertex programs are not
prepared by this extractor. Runtime-generated or modified programs, unsupported
records, unobserved states, different renderer settings, and native driver
pipelines can still compile during play. Some file payloads contain register
references rejected by the current translator/compiler; the authored fixups
and unsupported cases need further investigation. No claim is made that
shader preparation fixes the separately observed command-production freezes.

Environment controls for direct native use: `RSX_SHADER_LIBRARY=<catalog>`
with `RSX_SHADER_WARMUP=1`, `RSX_SHADER_ASYNC=1`, and an enabled shader cache;
`GT5P_SHADER_PRECOMPILE_ONLY=1` exits before guest entry. Library preparation
does not run during normal play unless explicitly requested.
`RSX_SHADER_LIBRARY_LIMIT`, `RSX_SHADER_LIBRARY_PROFILE_LIMIT`,
`RSX_SHADER_LIBRARY_PROFILES=base` and `RSX_SHADER_LIBRARY_BROAD=1` correspond
to the CLI controls. `RSX_SHADER_PROFILES=0` disables profile learning and
`RSX_SHADER_ERRORS=0` silences new bounded async compiler diagnostics.
`RSX_FP_CATALOG=<existing parent/dir>` is an optional raw-program diagnostic;
it is not needed for normal preparation.

Volume textures (Phase 96): learned profiles also record volume-unit bindings
in the upper half of the existing `ghi` field. Offline warmup uses those
bindings to compile Texture3D variants; older profiles remain readable and
represent 2D/cube-only states. Visiting wheel materials once learns their new
variants. `RSX_TEX3D=0` selects the older 2D interpretation for diagnostics.

## Race loading and background pipelines

The F1 settings page now offers **Background pipeline creation** and
**Prepare race pipelines**. Both default to On and apply after restart. Their
keys belong under the existing `[video]` table:

```toml
pipeline_async = true
race_preload = true
```

Driver pipelines are built by one background worker, including loads from
native driver cache blobs. The renderer retries pending draws instead of
waiting for that build. A new effect can appear late on its first encounter.
The queue owns its input data and is bounded to 256 jobs / 64 MiB of copied
shader data.

Race loading prepares the pipelines learned during earlier race visits before
entry, with a default 30-second waiting budget. The learned set includes
observed mirror, shadow and replay states across races. It is a conservative
shared race set, not an exhaustive list for the selected track or every camera.
First visits still learn; later visits reuse those recipes. Startup-wide
**Preload known shaders** remains a separate option and can be left enabled.

Membership is stored beside local recipes in
`shadercache/warmup-v1/race-v1.txt`. Preserve it with the rest of the cache.
Loading and the runtime queue share up to 4096 resident pipelines; invalid,
missing or unretained recipes remain eligible for background demand creation.
The window, audio and renderer continue while the loading caller waits. A
loading timeout releases the caller and lets preparation continue in the
background.

Direct controls: `RSX_PSO_ASYNC=0` restores synchronous driver creation;
`RSX_RACE_PREWARM=0` disables race-set learning/preparation;
`RSX_RACE_PREWARM_WAIT_MS=0` keeps preparation but removes the loading wait.
The waiting budget is clamped to 0..60000 ms. Race preparation requires the
shader cache and background pipeline creation. F8 reports include queue and
preparation counters. Tests: `scripts/test/pso_async.py`,
`scripts/test/shader_warmup.py`, `scripts/test/settings_test.ps1` and
`scripts/test/debug_export.ps1`.

## Background startup preparation

With **Preload known shaders** and **Background pipeline creation** enabled,
normal startup now queues preparation and starts the game immediately after
backend initialization. Opening screens, the movie, audio and menus run while
the existing below-normal-priority pipeline worker prepares the cache.

Live draw requests take priority at each worker turn. The worker first prepares
previously observed opening/menu recipes from `warmup-v1/menu-v1.txt`, then scans
the remaining recipes. Race-loading preparation can interrupt that scan too.
Only one native driver creation runs on the worker at a time; an active driver
call cannot be interrupted. The priority list is learned during opening screens
and main-menu visits, and stops collecting when entering dealerships or races.
It requires a visit to learn a new menu scene; unseen states can still appear
late. Preserve this index along with the shader cache.

Startup scans remain bounded to 4096 menu entries and 4096 directory records,
sharing the existing 4096-resident-pipeline limit. Progress and active startup
state appear in logs/F8 exports without replacing the movie's window title.
The `loaded` counter includes reuse in both passes, so it is not a unique
pipeline count. Unprepared records include invalid/missing recipes and recipes
that exceed the resident limit; they retain normal demand creation.

`RSX_SHADER_WARMUP_BACKGROUND=0` restores blocking startup for comparison.
Disabling **Background pipeline creation** also selects the blocking path.
The offline precompile-only command keeps its existing blocking completion
semantics. Explicit offline library compilation is still separate from this
normal-play startup preparation. No cache files are removed or invalidated.


## Asset-derived preparation research

The developer reconstruction workflow now has conditional dither/PCF, LV shadow
and framebuffer environment sampler paths; see
[shader reconstruction](shader-reconstruction.md#conditional-framebuffer-environment-samplers-phase-148).
These options require explicit pass assumptions and leave remaining translation/
pass/target state captured. They do not change this player preparation command,
launcher behavior or release contents. Capture-free catalogue generation and
first-run native pipeline preparation remain unfinished.


The developer mirror scene-copy option derives filter bits only, leaving input
wrap unresolved. Schema 2 texture audits carry per-lane masks; these partial
constraints are not complete pipeline recipes. See the
[mirror investigation](shader-reconstruction.md#partial-mirror-scene-copy-sampler-phase-149).


Developer `--material-texture-shapes` can now replace supported local cube/volume
translation bits during reconstruction proofs. Measured real asset bindings in
this subset are all 2D; global shapes and remaining translation/pass fields still
use capture state. This does not enable a new player preparation path; see the
[shape proof](shader-reconstruction.md#asset-local-texture-shape-bits-phase-150).


Developer `--material-texture-state` additionally derives supported read-gamma
and upper-coordinate bits, including conditional dither/PCF facts. It preserves
unknown global/pass fields and does not enable a player preparation path; see
[sampling-state reconstruction](shader-reconstruction.md#texture-sampling-state-bits-phase-151).


Developer `--environment-texture-path` adds an explicit initialized RGBA8
framebuffer shape candidate. It retains unknown read gamma and requires the
corresponding sampler/texture proof options; it does not enable player setup.
See [framebuffer shape](shader-reconstruction.md#conditional-initialized-framebuffer-shape-phase-152).
