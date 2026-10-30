# Offline game shader preparation

For measured asset/raw-program coverage, recipe dependency checks and the
remaining provenance gap, see [shader coverage audit](shader-coverage.md).

## Road to the finished precompiler

The core mechanism works: a portable template identifies programs and numeric
pipeline state, and preparation reconstructs/verifies both shaders and native
pipelines from the user's own assets. Remaining work is breadth, performance and
player integration; retained-route coverage is not whole-game coverage.

1. **Broaden representative coverage.** Merge templates from other tracks,
   dealerships, menus, cars and cameras. Report each session's additional and
   shared programs/state so further collection targets useful gaps rather than
   every car-track combination. Phase 170 adds reporting and the first session
   expansion; broader unvisited content remains open.
2. **Generate more directly from assets.** Extend material/shared-pass rules to
   derive valid pipelines without observing every draw. Recover bindings and
   actual pass state instead of multiplying every shader by every possible state.
   This is the main scaling path toward GT5.
3. **Support missing contexts/settings.** Recover branching vertex context and
   relevant renderer-setting/root-signature combinations. Reject incompatible
   entries safely and leave unsupported cases on the existing demand path.
4. **Make preparation efficient and resumable.** Reduce repeated compiler-process
   startup, reuse verified results, support cancellation/resume, and bound CPU,
   memory and storage. Developer preparation needs refinement for first launch.
5. **Demonstrate consistent stutter reduction.** Fewer runtime shader compiles have
   not yet produced a consistent frame-time win. Separate driver creation, cache
   reads, scheduling and unrelated game work; load prepared resources at useful
   times without expensive blanket startup scanning.
6. **Integrate the launcher.** Detect game/version and supported settings, show
   progress, support cancellation/resume, and handle cache compatibility. Ship
   metadata only; shader contents and GPU-specific binaries remain local.
7. **Validate the complete player path.** Exercise fresh caches, multiple GPUs,
   settings changes and representative routes. Measure loading time, memory,
   actual preparation hits and hitches; inspect rendering before enabling any
   default. No zero-stutter or complete-coverage promise follows from creation.

The immediate order is broader coverage reporting/session merging, then fixing
the measured performance bottleneck. GT5 additionally needs its asset formats
and rendering contexts verified; GT5P's template does not supply GT5 coverage.

### Compare representative sessions before more collection

Export each recorded session with `pipeline_template.py export`, then compare it
with the current verified starter. This reads metadata only and starts no game:

```powershell
.venv/Scripts/python scripts/pipeline_template_coverage.py `
  --baseline assets/pipeline-templates/gt5p-disc-v2 `
  --session HSR=scratch/hsr-template.json --session Daytona=scratch/daytona-template.json `
  --output scratch/session-coverage.json --delta-output scratch/new-candidates.json
```

The report counts shared/additional pipeline keys, program identities, observed
program pairs, source variants and translation states. It distinguishes new
pipelines reusing existing programs from those needing additional programs, and
ranks supplied sessions by marginal pipeline gain after earlier selections.
This ranks recorded content, not unvisited cars/tracks. Counts are metadata
candidates until preparation verifies them; they do not measure runtime hits.

Conflicting records fail by default. Explicit `--quarantine-conflicts` removes
all conflicting session versions and reports their keys/differing fields while
preserving the supplied baseline. It never picks a conflicting new record by
session order or majority. Incompatible renderer/game contracts always fail.
Exporter exclusions and quarantine counts must accompany coverage claims.

Prepare the delta against original assets into a fresh private cache; add only
positively verified entries to the baseline. The supplemental asset-map generator
accepts repeated `--trace` arguments for multi-session lookup. Invalid oracle
blobs are counted and skipped, never used to derive a program location. Merging
compatible templates does not require the user to drive every car-track pair;
it also does not prove that unvisited content is covered.

Phase 160 adds [named shared-pass selection and isolated state checks](shader-reconstruction.md#named-shared-passes-phase-160).
This is developer reconstruction work. CPU inputs and one conditional shared-pass
rule are now independently constructed; other shared resource/pass contexts remain open.

## Identifier-only templates (Phase 171; optional developer path)

This adapts the hash/numeric-state design in [Project Pyrrhus's template patch](https://github.com/undecuple/project-pyrrhus/blob/main/port/patches/2071-pipeline-template-prewarm.patch),
[context/key correction](https://github.com/undecuple/project-pyrrhus/blob/main/port/patches/2077-pso-key-vp-start-template-default.patch)
and [session export correction](https://github.com/undecuple/project-pyrrhus/blob/main/port/patches/2120-first-use-pipelines-hitch-count-own-template.patch).
Its [known-issues measurements](https://github.com/undecuple/project-pyrrhus/blob/main/docs/KNOWN_ISSUES.md)
concern a different game/renderer and are not GT5P evidence. No patch stack was imported.

GT5P recipes already hold native state and local bytecode; shader packs reduce
repeated disk reads, while menu/race prewarming prepares learned recipes. They
cannot ship first-run shader contents. Templates bridge that gap with identifiers
and numeric state. Original SHDS assets are available before guest boot; guest
memory scanning would wait for uploads and repeatedly scan changing memory.
This version uses bounded read-only asset lookup and the existing offline/native
preparer. Runtime-generated/unrecognized programs stay unresolved. Asset lookup
measured 48.93 s, so its cost must be included in any first-launch assessment.

All examples are developer-only; use isolated copied game data, local original
assets/catalogue and an isolated runtime EXE. First record representative play
with `RSX_PSO_PROVENANCE=<new ignored directory>` and normal recipes enabled.
Diagnostic recording is off during performance tests. Export each session:

```powershell
.venv/Scripts/python scripts/pipeline_template.py export `
  --trace scratch/session-provenance --cache scratch/session-cache `
  --elf ../GT5P/input/EMAIN.ELF --engine scratch/pass-build/gt5p.exe `
  --decoder scratch/reconstruction-build/decoder.dll --output scratch/session-template.json
.venv/Scripts/python scripts/pipeline_template.py merge --output scratch/starter-template.json `
  scratch/session-template.json scratch/another-template.json
.venv/Scripts/python scripts/pipeline_template.py prepare `
  --template scratch/starter-template.json --catalog ../GT5P/shadercache/library-v1/all `
  --elf ../GT5P/input/EMAIN.ELF --engine scratch/pass-build/gt5p.exe `
  --decoder scratch/reconstruction-build/decoder.dll `
  --game-root scratch/pipeline-training-20261031/game --output scratch/template-prepared
```

Templates contain hashes, translation state, numeric native state and canonical
ATTR inputs. No game-derived shader bytes/source/binaries are included. Keep all
experimental outputs ignored. A verified 2,334-record metadata starter is in
`assets/pipeline-templates/gt5p-disc-v2`; pass that directory to `--template`.
Game ELF, renderer source contract, explicit default settings and
schema/key/Windows x64 ABI compatibility are required. Format 2 excludes
per-install EXE/DLL timestamps; actual helper hashes stay in diagnostic reports. Rebuilt
source and bytecode identifiers and exact native keys verify settings/root
compatibility. Current export excludes branching vertices until their start-slot
context can be represented. Unknown or conflicting records fail safely; a user
can launch normally without template preparation. Individual missing/incompatible
programs are reported and remain on the asynchronous demand path. Optional
`--demand-fallback` writes an empty preparation result for invalid/incompatible
template headers without starting a compiler; strict preparation otherwise fails.

Phase 169 adds a separate version-1 program location map for code outside the
supported SHDS tables. The starter contains `asset-map.json`: now 119 locations
(4 vertex, 115 fragment), each a container SHA-256, file offset, size, encoding and
program identity. No filenames, guest addresses or shader contents are included.
Supply `--assets <original unpacked GT.VOL directory>` when preparing the bundled
starter; the map is selected automatically. For a standalone template, also pass
`--asset-map <map.json>`. Existing SHDS lookup remains available without a map.

Preparation hashes candidate-sized original containers, verifies the selected
program slices, then applies the same shader-source/bytecode/native-key checks.
Renaming or relocating identical assets is supported; changed assets cannot serve
their old locations. Missing containers stay unresolved. The measured full lookup
resolves all 2,334 retained HSR/Daytona records. Unsupported branching contexts
remain excluded; Phase 170 details export exclusions and conflict quarantine.
This closes an extraction gap, not the unknown-state problem for unseen content.

Generate a map once from representative developer provenance and original assets:

```powershell
.venv/Scripts/python scripts/pipeline_asset_map.py `
  --template scratch/starter-template.json --trace scratch/session-provenance `
  --catalog ../GT5P/shadercache/library-v1/all `
  --assets <original-unpacked-assets> --elf ../GT5P/input/EMAIN.ELF `
  --output scratch/session-program-locations
```

Captured programs supply search anchors only during map generation; each match
is reread/verified in the original asset. End users need no captures. `--catalog`
omits already supported programs. The generator uses one CPU thread, bounded
memory mappings, at most 8,192 files/1 GiB per file/16 GiB searched, a 600 s
between-candidate deadline and 4,096 anchor candidates per program/container.
Unlocated programs remain unresolved. Preparation limits map payloads to 4 MiB,
8,192 entries and 128 MiB resolved code; hashing has a 60 s between-container
deadline and 16 GiB budget. The local supplemental lookup hashed five containers
(438,542,896 bytes) in about 1.1 s with warm OS caches in Phase 169; the expanded
map hashes six containers/528,044,272 bytes in 1.54 s. No guest-memory scanning,
new live worker, asynchronous draw-policy change or player default is introduced.
Rollback is to omit `--assets`/`--asset-map` or skip optional preparation entirely.

The guarded offline persistence switch is `RSX_PSO_TEMPLATE_PREPARE=1`, default
off. Rollback: omit preparation/use the normal launcher; `=0` disables this
extension. No live draw policy or player defaults changed. Preparation uses the
existing two compiler workers, bounded queues and sequential native device owner,
then exits before play. Preparation does not invent menu/race membership indices:
normal demand consumes prepared bytecode/driver blobs, and real play learns
membership. Existing worker limits, deduplication and shutdown remain unchanged.
Offline windows stay hidden. `RSX_SHADER_LIBRARY_EXACT=1` omits unnecessary
base-profile compiles in explicit preparation only; ordinary library defaults
remain unchanged. Limits and current evidence are in Phases 166-168.

For a versioned metadata bundle (no shader contents):

```powershell
.venv/Scripts/python scripts/pipeline_template.py bundle `
  --template scratch/starter-template.json --output scratch/starter-template-bundle
```

`--template` accepts the bundle directory directly. Each part is checksum checked;
conflicting/incompatible generations are rejected.

### Exact fragment batching (opt in)

Add `--fragment-mode batch` to template preparation, conditional material
preparation or shared pipeline preparation. `legacy` remains the default and
rollback option. The runtime path is independently guarded by
`RSX_SHADER_LIBRARY_BATCH=<private work directory>` and
`GT5P_SHADER_PRECOMPILE_ONLY=1`; normal gameplay does not read batch manifests.

The preparer deduplicates exact fragment-program/profile requests, partitions
only by final-dither policy, and sends at most 4,096 requests to each offline
process. It never applies every profile to every program. The manifest names
hash-identified local programs, their raw checksums and explicit profile fields.
Header/version/counts, sorted unique identifiers, numeric widths, sampler masks,
program bounds/checksums and sampled-texture masks are validated before use.
Malformed manifests queue no work; malformed individual programs produce failed
results. Result joins require every expected ID exactly once. Missing/failed
bytecode remains unresolved; templates still verify source/bytecode identities
and the final native key before acceptance.

The existing two compiler workers, source-key deduplication, queue backpressure
and shutdown are reused. The queue is drained before returning, and no new live
worker or asynchronous draw policy is introduced. Batch metadata is bounded;
source/driver contents stay in ignored local caches. Matching intermediate inputs
can be reused by material/shared `--resume`; cache directories are preserved.

The 32-record paired empty-application-cache check produced identical bytecode
and native keys in both modes. Fragment preparation measured 37.81 s/20 processes
with legacy versus 5.64 s/2 processes batched; whole preparation was 57.40 versus
17.77 s. This is a small ordered test with warm OS/driver caches, not a universal
speedup or gameplay/stutter measurement. The full 2,334-record starter subsequently
passes every shader/native/persistence check in one empty application cache:
108.11 s fragment preparation in two processes, 467.42 s total and 57.17 s native
driver creation. Serial vertex preparation and cache verification remain part of
the total. Eleven native protocol/gating cases and all 36 shared candidates plus
cache-reusing resume pass. See Phase 171 for evidence and limitations. Template
preparation still requires fresh output; template cancellation/resume is not yet
implemented. No shadercache is cleared or moved.

Fresh application-cache paired validation:

```powershell
.venv/Scripts/python scripts/test/pipeline_template_route.py `
  --template scratch/starter-template.json --catalog ../GT5P/shadercache/library-v1/all `
  --elf ../GT5P/input/EMAIN.ELF --engine scratch/pass-build/gt5p.exe `
  --decoder scratch/reconstruction-build/decoder.dll `
  --fixture scratch/shader-stutter-20261031/fixture --output scratch/template-route --trials 4
```

It prepares from original assets into an empty cache, then runs the existing
control/prepared/prepared/control HSR route with distinct application caches.
Reports separate preparation/lookup time, runtime shader compilation, native
driver calls/cached calls, live demand jobs, warmup hits, frame hitches, grid
loading and sampled memory. Five-second counters can omit the final interval.
Inspect saved screenshots for missing draws before interpreting timing; OS and
driver caches are retained. Add offline preparation to the first-launch wait.
The Phase 168 experiment reconstructs 1,196 of 1,494 exported records; 298 remain
unresolved and three branching vertex contexts were excluded at export. Both
shader stages and exact native keys pass verification. Preparation took 723.9 s,
including lookup/translation/compiler process overhead; native creation accounted
for 26.1 s. Local driver blobs occupy 82.6 MiB. These are retained-route records,
not whole-game coverage. A fresh-cache bundled one-record smoke also passes.

Four bulk-preload trials and a final demand-only pair do not establish a consistent
stutter improvement. Runtime shader compiles fall in prepared trials, but cached
driver creation still occurs and frame-time results vary substantially. Screenshots
show later prepared scenes drawing, but differing progress prevents pixel-equal
rendering proof. See Phase 168 for counters, timings and evidence. `warm_hits`
includes startup bookkeeping; it is not an independent draw/preparation-hit count.

Benchmark trials now remove only their disposable private `game` directory after
saving results. Shader caches, logs and screenshots remain. Use
`--keep-game-copies` only when debugging requires them. Before copying, a free-space
check reserves the writable game copy, prepared cache and 2 GiB headroom. Fourteen
old copies were removed on request, freeing 54.53 GiB; their report paths remain
as historical evidence, but those disposable game directories no longer exist.

## Automatic shared vertex preparation (developer only)

Phase 162 adds a capture-free step toward shared-pass preparation. It scans the
original ELF automatically, selects only authored named SHDS pairs, deduplicates
their supported vertex programs and prepares the CPU VS cache. No game run,
manual bank offset or pass name is needed:

```powershell
.venv\Scripts\python scripts\prepare_shared_shaders.py `
  --elf ../GT5P/input/EMAIN.ELF --decoder scratch\reconstruction-build\decoder.dll `
  --output scratch\shared-vertex-preparation
```

The measured disc ELF supplies 46 pairs across five supported banks and 14
distinct CPU vertex programs, all compiled successfully. Two unhandled banks
remain reported/excluded. The output contains source-keyed runtime DXBC and an
ignored manifest of original offsets/hashes. No fragment profile or whole
pipeline is guessed. This command prepares vertex shaders only; use the explicit
pipeline mode below for the supported rule. Other shared contexts remain unresolved. It is not yet wired
into the launcher or material precompiler, and does not establish stutter impact
or compatibility with GT5's asset layouts. See
[input-layout validation](shader-reconstruction.md#automatic-shared-vertex-preparation-phase-162).

Phase 163 adds the first complete conditional shared-pass rule. Add `--pipelines`
with an isolated `--engine` and `--game-root`. Phase 164 also enumerates explicit
host depth attachment: `--context-set supported` has 24 ColorCorrect contexts
and the default `rgba16` set has 16, using `--depth-context both`:

```powershell
.venv\Scripts\python scripts\prepare_shared_shaders.py `
  --elf ../GT5P/input/EMAIN.ELF --decoder scratch\reconstruction-build\decoder.dll `
  --output scratch\shared-pipelines --pipelines --engine scratch\pass-build\gt5p.exe `
  --game-root ../GT5P --context-set supported
```

This is offline only. Source/target read/write gamma, format/samples and host
depth attachment are explicit candidates; real draw ownership is unproven. Use
`--depth-context backed` for the Phase 163 subset, or `colour-only` for targets
without depth. The
source must be a successfully initialized RGBA8 2D FrameBuffer, distinct from
the destination, with no unexpected redirects or later overrides. Unknown
resources and feedback are excluded. All 24 supported candidates create and persist, and
repeat preparation reuses their driver blobs. They do not match the retained
HSR snapshot, so no live coverage/stutter gain is claimed. Other pairs still
receive vertex preparation only. No player defaults or launcher integration.
Use the same command with `--resume` to revalidate/reuse matching output. All
outputs remain local/ignored. See the [shared rule](shader-reconstruction.md#conditional-colour-correction-pipelines-phase-163).

Phase 165 adds `Convolution_8`: `--context-set supported` now prepares 36 requests
(24 ColorCorrect plus 12 convolution); `rgba16` has 24. All 36 persist; two
convolution native keys match retained HSR evidence. Context assumptions remain.
Earlier counts above describe Phase 164.

## Automated route learning and preparation (developer only)

`scripts/train_pipeline_cache.py` provides a pragmatic alternative to recovering
each pass independently. One command drives the existing High Speed Ring and
Daytona automation, learns actual shader/pipeline requests into one private
cache, then prepares every learned native pipeline offline before returning.
It needs no manually selected shader names, material pairs, capture lines or
pipeline keys. This uses observed draw state and locally generated bytecode;
it is **not** independent reconstruction from assets or a whole-game catalogue.

```powershell
.venv\Scripts\python scripts\train_pipeline_cache.py `
  --fixture scratch\shader-stutter-20261031\fixture `
  --engine scratch\pass-build\gt5p.exe `
  --output scratch\pipeline-training
```

The fixture must contain copied `input/EMAIN.ELF`, `input/pkg/`, `assets/` and
`gamedata/` inside ignored storage in this checkout, with no links back to another
checkout. The tool copies writable data and links only the private copied disc
directory. It refuses another game and cleans up only its owned child tree.
It preserves caches, disables recipe pruning, uses `PS3_VERBOSE=0`, keeps bulk
startup scanning off while learning and runs the final preparation before play.
No runtime, launcher, release or player defaults change.

Defaults are both supported routes, 90 seconds after reaching the grid,
1080p/2x MSAA and one visit per route. `--tracks HighSpeedRing`, `--seconds 60`,
`--resolution 720p`, `--msaa 1` and `--passes 2` select an explicit sweep.
Use the same command with `--resume` after interruption. Add `--prepare-only`
to resume native preparation without driving again. Engine, fixture and route/
renderer settings must match the run's saved configuration. Failed runs retain
their cache and report rather than silently claiming partial success.

`report.json` records each completed route, newly learned recipe counts, grid
milestones and presented-frame checks. Logs and screenshots remain alongside it.
The tool checks recipe envelopes/checksums and bytecode dependencies, requires
the native warmup to accept the entire set, verifies the offline guest-entry
guard and validates every persisted driver-blob envelope/checksum. The pinned
runtime's 8,192-recipe offline cap is explicit; larger sets are rejected rather
than silently truncated. Recipes for incompatible root-signature/settings
generations are rejected by the runtime. Driver blobs are hardware/driver local.

Only the supported routes, current car and selected settings are visited. Grid
and presentation checks are not proof of complete geometry or visual readiness;
inspect the retained shots. Runtime-generated variants in unseen content still
need discovery, and short cold-cache visits can miss late asynchronous draws.
More visits can learn additional states but cannot prove completeness. This is
cache training, not a stutter-reduction benchmark. Use the separate paired test
below to measure any benefit. The resulting `shadercache/` stays local and is
not a distributable release asset.

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
