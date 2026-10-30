# Shader and pipeline coverage audit

For the subsequent asset-to-bytecode and native pipeline proof, see
[shader reconstruction](shader-reconstruction.md). It verifies a small sample
using captured state; full material/pass reconstruction remains open.

`scripts/shader_coverage.py` compares extracted SHDS fragment programs against
raw programs recorded by the renderer. It also inventories learned fragment
state profiles and checks recorded native-pipeline bytecode dependencies.
This is a developer diagnostic, not a new player precompiler.

The tool does not start the game, compile shaders, remove cache files or change
the renderer. All reports contain local game-derived identifiers/source paths
and must stay in gitignored storage. Do not package the reports or raw corpus.

## Repeating the audit

First create an asset catalogue using the existing
[offline preparation tool](shader-precompile.md). Its `index.json` identifies
asset filenames and payload offsets. The catalogue is a snapshot; the audit
checks each extracted payload's SHA-256 but does not verify the original game
version or reread every source container.

Record representative routes using the current game build, one process at a
time. `RSX_FP_CATALOG` is an existing diagnostic switch; leave it unset during
normal play because recording adds file I/O. For example, in the development
checkout containing the game build and save:

```powershell
scripts/test/race.ps1 -Track HighSpeedRing -Tag coverage-hsr -Seconds 25 -RaceShots 20 PS3_VERBOSE=0 RSX_FP_CATALOG=scratch/coverage-hsr
scripts/test/race.ps1 -Track Daytona -Tag coverage-daytona -Seconds 25 -RaceShots 20 PS3_VERBOSE=0 RSX_FP_CATALOG=scratch/coverage-daytona
```

Inspect the final window images to confirm the race HUD is visible. These
routes include boot, menu and pit shaders as well as the race; they are not
track-only corpora. Use a new corpus directory for each run, and close the game
before taking the cache inventory so files do not change during the audit.

```powershell
.venv/Scripts/python scripts/shader_coverage.py --catalog shadercache/library-v1/all --live scratch/coverage-hsr --live scratch/coverage-daytona --cache shadercache --output scratch/coverage-report
```

The output directory must be new, gitignored, and separate from all inputs.
`summary.txt` is a short summary; `report.json` contains every match, source
filename, rejected input, pipeline dependency problem and menu/race membership
count. `--verify-hashes` additionally checks the renderer's 64-bit recipe and
bytecode checksums; on a large cache this is slower. Without that option,
dependency checks cover bytecode size and DXBC signature, not byte integrity.

## What the numbers mean

- **Exact:** the live file equals an indexed, available asset payload.
- **Instructions:** instruction bytes match through END after zeroing inline
  constant values and ignoring trailing container padding. Constant slot
  positions remain part of the identity. Different live files can share an
  instruction identity, so the report gives both file and unique counts.
- **Unmatched:** no matching instruction identity in this catalogue. This does
  not distinguish missing extraction, authored fixups, generated programs,
  mismatched content or an unsupported record format.
- **Invalid:** a bounded program walk or input-integrity check failed. This
  does not prove the game itself has a malformed shader.
- **Dependencies present:** the recipe envelope identifies available VS/PS
  DXBC containers of the expected size. This is not a successful native PSO
  creation, renderer-version check, or validation of the ABI-specific D3D12
  descriptor. Optional hashes check integrity, not compatibility.

Profile applicability means matching texture-unit masks, just as the current
offline pass filters profiles. It is not evidence that each candidate material
uses that state. The audit never multiplies these counts into a claimed number
of prepared or reconstructable pipelines.

## Missing link to full preparation

Legacy recipes associate a native pipeline descriptor with compiled VS/PS
bytecode but lack the original input mapping. The optional recorder below now
captures that mapping for new diagnostic runs. Authored vertex-program and
material/pass extraction and independent reconstruction remain absent. A hash
alone cannot reconstruct an unavailable program.

Once those mappings are verified, derive states from the game's material/pass
logic rather than compiling the full shader/state cross-product. Automated
content loading can then validate coverage without manually racing every car.
This work is not yet a distributable complete catalogue or a guarantee of zero
first-use compilation.

## Optional pipeline provenance recorder (Phase 137)

Apply this branch's runtime overlay with `scripts/setup_runtime.py` and build
against that runtime. Merely checking out the audit Python script does not add
recording to an older EXE. There is no new F1 setting; normal play leaves this
diagnostic off.

Set **`RSX_PSO_PROVENANCE` to a local output directory**, preferably an absolute
path under ignored `scratch/`, before launching the game. Its parent must
already exist. Unset it or use `0` to disable it. For example, substitute your
actual checkout path:

```powershell
$capturePath = "$PWD/scratch/provenance-hsr"
scripts/test/race.ps1 -Track HighSpeedRing -Tag provenance-hsr -Seconds 25 -RaceShots 20 PS3_VERBOSE=0 "RSX_PSO_PROVENANCE=$capturePath"
```

Each process creates its own `links_<pid>_<clock>.jsonl`, flushed per link. The
following `.bin` files are deduplicated by the renderer's 64-bit content hash:

- `fp_…`: bounded fragment input snapshot used for translation, including inline
  constants. Snapshotting happens only on misses with recording enabled.
- `vp_…`: vertex input range passed to the per-draw translator, including any
  trailing microcode store. The link separately records the identity extent
  used by the vertex cache and whether GPU input fetching was selected.
- `fphlsl_…` / `vphlsl_…`: final generated source submitted to compilation.

Links record those input/source identifiers, compiler-cache keys, pixel compile
flags, shader-affecting key state (including sampler/texture masks), resulting
VS/PS DXBC identifiers and the native pipeline request identifier. The bytecode
and native descriptor remain in the normal `warmup-v1` recipes. Compiler date
is diagnostic build metadata, not a stable renderer version identifier.

Only actual per-draw guest-FP pipeline requests are recorded. Pending shader
compiles, translation failures and independent fixed/internal pipelines are not
complete links. The legacy primary VS fallback has no per-draw input provenance;
it is represented by zero vertex identifiers, never guessed from current state.
`queued` means driver creation was requested asynchronously; `ready` means the
request returned successfully. The first record is retained, so a queued record
does not later become ready in the log. The audit checks the resulting recipe
independently; a queued request alone is not pipeline-creation success.

`RSX_PSO_PROVENANCE_LIMIT` bounds unique links per process (default 8192,
clamped to 1..16384). Duplicate pipeline/program/vertex combinations are
suppressed. Reaching the cap or an I/O failure logs an incomplete-capture warning.
Vertex blobs can also be written for successful VS compiles before a linked
pixel shader is ready; their count is bounded by the existing vertex cache.
This diagnostic performs hashing, copying and disk writes and must stay off
when judging normal-play performance. Nothing is added to the release ZIP.

After closing the game, add one or more captures to the audit:

```powershell
.venv/Scripts/python scripts/shader_coverage.py --catalog shadercache/library-v1/all --live scratch/provenance-hsr --cache shadercache --provenance scratch/provenance-hsr --output scratch/provenance-report
```

The audit verifies input/source-blob hashes, compares each fragment input to
assets, and joins each pipeline to its recipe and exact VS/PS identifiers.
Missing recipes, absent dependencies, bytecode mismatches and malformed records
are separate statuses. Full recipe/bytecode checksum verification still requires
`--verify-hashes`. The report keeps the original captured fields for analysis.
It retains only metadata while checking source blobs rather than keeping all
HLSL payloads in memory.

**A verified recipe link is not full asset reconstruction.** It can still depend
on a locally recorded vertex input or HLSL. The next step is to locate those
vertex programs and material/pass states in authored assets, then rebuild a
small sample independently and compare its resulting bytecode/pipeline keys.

Checks: `scripts/test/pso_provenance.ps1 -Runtime <patched-runtime>` exercises the
real serializer without a GPU/game: default-off, explicit `0`, valid JSON,
duplicate suppression and a one-link cap. `scripts/test/shader_coverage.py`
also checks provenance joins, missing recipes, mismatched bytecode IDs, damaged
input blobs, invalid identifiers and truncated JSON.

### Recorder validation on 2026-10-30

An isolated backend compile/relink produced a separate test EXE; the normal
development binary and Claude's shared runtime were not replaced. Initial
1080p/2x-MSAA HSR and Daytona samples recorded 1,763 / 1,943 links. The audit
detected 2 / 7 raw-fragment checksum mismatches, exposing a hash/write race
against guest memory in the first implementation. Those initial captures are
retained as diagnostic evidence, not treated as clean preparation inputs.

The final pre-translation snapshot implementation was recompiled and checked
with another HSR race sample (15 seconds of sampling after the introduction).
Its **1,497 links all joined verified recipe identifiers/dependencies, with
zero input/source integrity failures**. All had captured vertex inputs; 1,204
links also had a structural fragment match in the asset catalogue. Four new
recipes absent from the preceding inventory were separately copied and checked
with full recipe/bytecode checksums, then included in the join. The remaining
recipe inventory used the earlier envelope/size/DXBC-signature checks. These
numbers do not imply full-cache checksum verification or complete race coverage.

Final local report in this worktree:
`scratch/provenance-snapshot-hsr-20261030/audit-final.json`. The preceding
two-route audit is `scratch/shader-provenance-audit-20261030/report.json`.
Window shots with racing HUDs and logs are under the development checkout's
`scratch/pv/provenance-{hsr,daytona,snapshot-hsr}-20261030.*`. Native serializer
checks cover off/unset, explicit `0`, duplicate suppression, a one-link cap and
JSON parsing. No complete precompile catalogue is packaged by this change.

Synthetic checks: `.venv/Scripts/python scripts/test/shader_coverage.py`.

An optional differential check accepts a locally compiled decoder DLL exporting
`rsx_fp_program_size`, `rsx_fp_texture_mask` and `rsx_fp_collect_constants` from
the current runtime's `rsx_fp_decompiler.c`. Build it with the normal x64 VS
environment and clang-cl `/LD /O2 /MD`, the runtime `include` and `libs/video`
include paths, and `/link /EXPORT:<name>` for each function. Keep DLL/object
outputs under scratch. It does not initialize D3D or run the game:

```powershell
.venv/Scripts/python scripts/test/shader_coverage_native.py --decoder scratch/shader-coverage-native/decoder.dll --programs shadercache/library-v1/all --programs scratch/coverage-hsr --programs scratch/coverage-daytona --limit 0
```

## Measured on 2026-10-30

The audit implementation is on `feature/shader-coverage-audit`, in the isolated
`GT5P-player-setup` worktree. The original development worktree and runtime
sources were unchanged. The existing development EXE was used for two 1080p,
2x-MSAA runs; each sampled 25 seconds after its default 25-second race-start
delay. Final window images confirmed the race HUD on both tracks. These short
samples do not cover a complete lap, every camera, or every car.

| Sample | Recorded FP files / instruction identities | Exact asset match | Instruction match | Unmatched |
| --- | ---: | ---: | ---: | ---: |
| High Speed Ring | 553 / 553 | 3 | 481 | 69 |
| Daytona | 586 / 586 | 3 | 532 | 51 |

Thus 87.5% and 91.3% of these recorded programs respectively have structural
asset matches. This is **not** a pipeline preparation success rate. Corpora
overlap and include boot/menu/pit content; do not sum them as unique race shaders.

The existing asset snapshot contains 8,142 payloads: 8,069 pass the bounded
walk, representing 5,864 instruction identities. The other 73 comprise 62
without a bounded END and 11 with a truncated constant slot. A separately
compiled production decoder agreed on all 9,208 accepted files across the
catalogue and both live corpora and jointly rejected the same 73. Actual HLSL
translation/compilation acceptance was not tested by this comparison.

The accumulated cache contains 49,060 recipe envelopes, all with expected-size
VS/PS DXBC dependencies present: 1,223 distinct compiled VS identifiers and
17,488 PS identifiers. Menu/race indices reference 6,234 / 8,469 recipes, none
missing. These accumulated records include past renderer configurations; the
counts are not current-version compatibility or resident-pipeline guarantees.
Full-cache checksums were not enabled. A separate 64-recipe sample and all its
referenced bytecode passed the renderer's checksum calculation.

There are 836 readable learned fragment profiles. The current offline compiler
uses at most 64 by default or 256 when requested, so this pooled profile count
must not be mistaken for the set applied by a normal preparation pass.

Local evidence:

- Development checkout: `scratch/pv/coverage-{hsr,daytona}-20261030.*` and
  the corresponding `scratch/coverage-{hsr,daytona}-20261030/` raw corpora.
- Audit worktree: `scratch/shader-coverage-20261030/{report.json,summary.txt}`.
- Audit worktree: `scratch/shader-coverage-hash-sample-20261030/result.json`
  and `scratch/shader-coverage-native/decoder.dll`.

The provenance recorder and sampled asset reconstruction are now implemented;
see [shader-reconstruction.md](shader-reconstruction.md) for material pairings
and the subsequent state audit/preparation proof. A measured preparation rule
now accounts for the common LESS-to-LEQUAL difference. The current next step is
establishing exact draw ownership and the remaining pass/target/texture state;
six native pipeline proofs now replace blend/write-mask/depth fields from
prepared assets rather than retaining those fields from captures. This remains
a partial reconstruction. Phase 143 also derives complete effective sampler
keys for two car-material proofs; most links still need alias/global bindings
or pass context. Phase 144 accepts coherent scalar aliases and inventories the
global requirements; known-lane candidates increase to 843 links, while complete
sampled-unit coverage remains 16. Unmatched programs also need analysis. Extending
catalogue size or cross-multiplying pooled profiles alone cannot establish
complete pipeline reconstruction.

Phase 145 resolves the seven global identifiers to their initialized callback
pairs in a private-memory native oracle. Two lookup handlers also pass ten
sentinel checks. The emit callbacks and their eventual sampler settings remain
unverified, so the coverage figures above are unchanged. See the
[callback trace](shader-reconstruction.md#global-callback-initialization-phase-145).

Phase 146 derives conditional dither/PCF sampler lanes, checked against 288
native command emissions. Explicit active/fallback candidates cover every
sampled sampler lane for 122/26 links (132 union), versus the preceding 16.
Eight active and two fallback samples recreate native pipelines. These figures
remain sampler coverage under a chosen path, not complete pipeline or game
coverage. Other global textures, pass/target state and unmatched programs remain
unresolved; no complete first-run catalogue is ready to package.

Phase 147 adds an explicit LV shadow-pass variant. Its setup forces linear/clamp
sampling, verified under controlled inputs with the real pass routine. Together
with active dither, matching candidates cover every sampled sampler lane for 336
links; four shadow-using car-interior samples rebuild native pipelines. This
remains conditional sampler coverage, with other pipeline fields still captured.
Environment/mirror descriptors and remaining pass/translation state are open.


Phase 148 adds explicit framebuffer environment sampler candidates, verified by
1,024 controlled successful setup/getter/assignment/emitter checks and 1,024
allocation-failure checks. With active dither/LV shadow, the mipped candidate
completes sampled sampler lanes for 861 retained links; four environment-using
native pipeline proofs pass. Live path ownership, mirror setup and other
translation/pass/target fields remain unresolved. See the
[conditional environment proof](shader-reconstruction.md#conditional-framebuffer-environment-samplers-phase-148).


Phase 149 measures a mirror scene-copy filter override and adds partial masks
within sampler-bank lanes. Audit schema 2 includes per-profile `lane_masks`;
wrap bits remain unknown. No authored mirror pair links to the retained HSR
capture, so its coverage totals are unchanged. See the
[partial mirror proof](shader-reconstruction.md#partial-mirror-scene-copy-sampler-phase-149).


Phase 150 adds a separate local texture-shape audit and partial shape translation
proof. Known local shape bits match 843 retained links, with 16 complete for all
sampled shapes. This supported inventory is all 2D; global shapes remain unknown.
Four pipeline proofs derive local shape bits, with two explicitly retaining a
global environment cube. These counts are separate from sampler coverage and
do not establish capture-free pipelines. See
[local shape reconstruction](shader-reconstruction.md#asset-local-texture-shape-bits-phase-150).


Phase 151 extends masked texture comparisons to read gamma, upper-coordinate
flags and explicit dither/PCF texture facts. Active-path known bits match 1,028
links; 122 cover every sampled unit for the selected fields. Other translation/
pass state remains captured. See [sampling-state proof](shader-reconstruction.md#texture-sampling-state-bits-phase-151).


Phase 152 adds explicit initialized RGBA8 framebuffer shape candidates. With
active dither and cube creation selected, known shapes match 1,044 links, 265
complete for shapes alone. Read gamma and other pass state remain unresolved;
three native pipeline proofs derive the environment cube bit. See
[framebuffer shape](shader-reconstruction.md#conditional-initialized-framebuffer-shape-phase-152).


Phase 153 adds developer-only conditional object-pass winding/culling and output
gamma reconstruction. Five partial shader/native pipeline proofs pass; live
pass ownership and remaining target/translation fields are unresolved. See
[the reconstruction scope](shader-reconstruction.md#conditional-object-pass-fields-phase-153).
This does not change player preparation or release defaults.
