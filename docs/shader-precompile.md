# Offline game shader preparation

For measured asset/raw-program coverage, recipe dependency checks and the
remaining provenance gap, see [shader coverage audit](shader-coverage.md).

Phase 160 adds [named shared-pass selection and isolated state checks](shader-reconstruction.md#named-shared-passes-phase-160).
This is developer reconstruction work; shared texture/target context and native
CPU vertex layout still need recovery before independent pipeline preparation.

## Capture-free material subset (developer only)

Phase 157 adds a conditional asset-to-native preparation path that needs no live
capture or learned translation profile. It currently supports ordinary 2D uploads
with complete sampled facts, prepared material state, compact fragment binding
and explicitly selected object/target/global context. Actual pass ownership is
not established. Unknown resource bindings are rejected; absence of resource
aliases is an explicit context assumption. It does
not yet integrate with the launcher or change normal player defaults.

With the isolated patched runtime EXE and production vertex decoder already built:

```powershell
.venv\Scripts\python scripts\prepare_material_shaders.py `
  --catalog ..\GT5P\shadercache\library-v1\all `
  --engine scratch\pass-build\gt5p.exe `
  --decoder scratch\reconstruction-build\decoder.dll `
  --game-root ..\GT5P --object-pass-path ccw `
  --native-target-path rgba16-msaa2 --global-sampler-path active `
  --limit 0 --output scratch\material-preparation
```

The catalogue supplies original source-container paths, not capture state. Close
the game first. Use separate ignored output, never the original checkout or its
cache. Default `--limit 8` is a smoke run; `--limit 0` prepares all eligible
candidates. `--enumerate-only` writes the inventory and candidate manifest without
compiling. Repeat the same command with `--resume` to reuse cached fragment
bytecode and revalidate native driver pipelines; vertex translation still runs.
Changed engine, decoder or context choices require a new output directory.

`report.json` records assumptions, exclusions, individual results and timings.
`shadercache/` contains source-key DXBC, local driver blobs and warmup recipes in
the renderer's ordinary formats. Keep all generated files local. This command
does not install its output into a player's cache. Driver compatibility is checked
through native pipeline creation on every run; stale blobs use the existing
renderer fallback. A partial failure returns nonzero and preserves results.

The measured subset prepared 474 candidates into 467 distinct native pipelines.
This establishes preparation, not exhaustive coverage or measured stutter
reduction. See [the reconstruction evidence](shader-reconstruction.md#capture-free-conditional-material-preparation-phase-157).

### Explicit context unions

Use `--context-set rgba16` instead of the individual object/target/global options
to prepare both supported winding choices, both RGBA16 sample configurations and
both active/fallback global candidates in one cache:

```powershell
.venv\Scripts\python scripts\prepare_material_shaders.py `
  --catalog ..\GT5P\shadercache\library-v1\all `
  --engine scratch\pass-build\gt5p.exe `
  --decoder scratch\reconstruction-build\decoder.dll `
  --game-root ..\GT5P --context-set rgba16 --limit 0 `
  --output scratch\material-context-union
```

`--context-set supported` additionally includes RGBA8/single. The independent
candidate audit found no extra retained HSR matches from those RGBA8 choices, so
the measured preparation uses `rgba16`. These named sets explicitly enumerate
conditional variants; they do not infer which pass a material uses from capture
settings. Identical shader/state jobs are deduplicated, their supported contexts
remain in `manifest.json`, and each native request uses its own target sidecar.
`--resume` works with the same named set and executable/decoder identity.

The measured RGBA16 union prepares all 3,446 candidates into 3,402 native pipelines.
It confirms 131/1,497 retained HSR native-key matches (8.75%), up from 52 (3.47%),
with no baseline matches lost. This developer run takes 11.3 minutes and saves
204 MB of driver blobs, plus bytecode and intermediate files. That is preparation
cost on the measured machine; actual stutter reduction remains unmeasured.

To repeat the read-only candidate comparison before compiling:

```powershell
.venv\Scripts\python scripts\audit_material_variants.py `
  --catalog ..\GT5P\shadercache\library-v1\all `
  --audit scratch\provenance-snapshot-hsr-20261030\audit-final.json `
  --trace scratch\provenance-snapshot-hsr-20261030 `
  --output scratch\material-context-audit
```

This freezes asset-derived candidates before reading the oracle. Program/profile
matches are predictions. Confirm them against persisted native pipeline keys:

```powershell
.venv\Scripts\python scripts\audit_prepared_materials.py `
  --prepared scratch\material-context-union `
  --baseline scratch\capture-free-material-full-subset-20261030 `
  --audit scratch\provenance-snapshot-hsr-20261030\audit-final.json `
  --output scratch\material-context-native-audit.json
```

The native audit checks preparation results and persisted recipe checksums/blob
presence. Its denominator is the retained snapshot, not every draw or all game
content. No measured stutter reduction follows from a key-match percentage alone.

### Measuring first-visit frame times

`scripts/test/shader_stutter.py` compares fresh application caches with the
generated subset on an automated HSR route. Supply a private ignored fixture
containing copied `input/EMAIN.ELF`, `input/pkg/`, `gamedata/` and `assets/`.
Each trial copies the fixture's writable game data, uses a separate shadercache,
and shows only its owned game window. Other `gt5p.exe` processes block launch;
cleanup never stops an unrelated session. All trial files remain ignored.

```powershell
.venv\Scripts\python scripts\test\shader_stutter.py `
  --fixture scratch\shader-stutter-20261031\fixture `
  --engine scratch\pass-build\gt5p.exe `
  --prepared scratch\material-variant-union-prepare-20261030\shadercache `
  --output scratch\stutter-demand-abba --startup-policy demand --trials 4
```

The order is control/prepared/prepared/control. `--trials 2` runs one pair.
`--startup-policy demand` uses normal learned-index startup without scanning every
recipe; `scan` explicitly tests bulk startup scanning. Both use async shaders and
pipelines, VSync, 1080p/2x MSAA, `PS3_VERBOSE=0` and race prewarming disabled.
The OS and driver caches are preserved. This is a cold **application-cache** test,
not a clean-driver first-install test. It excludes offline subset preparation.

Frame CSVs, window timestamps, logs and screenshots distinguish the first 45 s
after the grid from 45-90 s and the whole presented route. The first window
includes the intentional 30-FPS rolling start; route gaps also include loading
transitions. Reports include p99/max intervals and counts over 50/100/250 ms.
Five-second compiler counters can omit a final partial interval. Used recipe
timestamps help check actual subset encounters without provenance recording.
Inspect the screenshots: higher FPS while drawing incomplete geometry is not a
visual-readiness improvement. Scripted navigation does not ensure identical draw
workloads or race progression across runs, so small differences need caution.

## Existing raw-program preparation

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


Phase 153 adds developer-only conditional object-pass winding/culling and output
gamma reconstruction. Five partial shader/native pipeline proofs pass; live
pass ownership and remaining target/translation fields are unresolved. See
[the reconstruction scope](shader-reconstruction.md#conditional-object-pass-fields-phase-153).
This does not change player preparation or release defaults.


Phase 154 adds fresh native descriptor construction for explicit developer
GPU-fetch/depth-backed target candidates. Five pipeline proofs and a zeroed
captured-descriptor check pass. Remaining shader translation and actual pass
ownership still depend on investigation; no player or release default changes.
See [the measured scope](shader-reconstruction.md#fresh-conditional-native-descriptor-construction-phase-154).


Phase 155 derives export precision from the authored compact fragment-control
word for explicit no-later-override binding candidates. Three fresh-descriptor
pipeline proofs pass; remaining global/coordinate/shadow fields and actual pass
ownership are unresolved. See
[the reconstruction scope](shader-reconstruction.md#authored-compact-fragment-export-control-phase-155).


Phase 156 proves a whole conditional ordinary-upload translation profile and
fresh native descriptor in three samples. The profile takes no captured state;
unknown sampled facts fail closed. No-alias/no-later-override context assumptions
and actual ownership still limit coverage. See
[the independent subset scope](shader-reconstruction.md#whole-independent-ordinary-upload-profile-candidate-phase-156).
Player first-run preparation and launcher integration remain unfinished.
