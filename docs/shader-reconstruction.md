# Asset shader reconstruction proof

Phases 138-149, branch `feature/shader-coverage-audit`. This is a small developer proof,
not first-run setup or a complete shader catalogue. It follows the
[coverage/provenance work](shader-coverage.md).

**Measured result:** seven sampled shader pairs were rebuilt from original
asset slices, matched captured VS/PS bytecode identifiers, reproduced the exact
native pipeline key and successfully created a D3D12 pipeline. Three are small
executable programs, three use car LOD assets with GPU vertex fetching, and one
uses car LOD assets with a 16-bit colour target.

The original proof uses rendering state and a native descriptor from a diagnostic
capture. Phase 142 below replaces blend/write-mask/depth fields from prepared
material data; other descriptor/pass fields still come from the capture. No
recorded raw shader or cached DXBC is used as input to shader compilation. This
proves a limited asset-to-bytecode path using known state, not independent
reconstruction of every pipeline the game can need.

## How it works

`scripts/shader_reconstruct.py` takes a verified provenance audit and the existing
fragment catalogue's source index. It scans those original source containers
read-only with memory mapping; it does not unpack or rewrite them.

The SHDS table at offset 0x20 has a count at 0x18 and 0x28-byte entries. The
observed disc-build vertex payload has a 32-byte wrapper: a big-endian 16-bit
instruction count at zero and a big-endian code offset at 0x10. Removing that
wrapper and reversing bytes within each 32-bit instruction word gives native
decoder input. Tables, payloads and code spans are bounds checked. Layout
research used the local copy of
[PDTools' public shader readers](https://github.com/Nenkai/PDTools/tree/master/PDTools.Files/Models/Shaders)
(MIT); wrapper interpretation was checked against captured inputs and production
translation. Other builds/formats are unverified.

Exact instruction-prefix matches identify candidates. The captured VS input can
include unrelated trailing microcode, so the recorded identity extent is used
for discovery. A candidate is not a proven equivalent shader until the sample
checks below pass:

1. Reread the candidate's original asset slice and verify its SHA-256. Translate
   the asset program with the production normal or GPU-fetch vertex decoder.
   Its generated HLSL identifier must match the capture. Compile it with the
   Windows D3D compiler and compare resulting bytecode identifiers.
2. Reread the indexed fragment payload from its original asset container and
   verify SHA-256. Run the production offline translator/compiler with the
   captured profile into a **new, empty** shader cache. Require a successful
   one-program pass, the exact captured source-cache key, and the expected
   compiled PS identifier.
3. Copy only the captured descriptor recipe and the **newly rebuilt** VS/PS
   bytes into a private proof folder. The offline renderer validates the recipe
   envelope/checksum and shader checksums, restores the descriptor's input
   semantics and current root signature, recomputes the normal pipeline hash,
   and requires equality before calling D3D12 creation.

The native proof bypasses the application's driver-blob lookup and supplies no
cached pipeline blob. It does not clear the GPU driver's internal caches, and
does not make claims about cold-driver compilation time.

## Running it

Use an isolated runtime with this branch's overlay. Build an EXE against it;
an older EXE will not support the native proof mode. Close the game first.
The tools launch offline compilation processes sequentially and verify the log
confirms guest entry was not executed. The original cache is read only; all
compilation/proof outputs go into a new ignored directory.

Build a developer decoder DLL from that runtime in an x64 VS developer prompt.
For example, substitute your actual patched runtime path:

```powershell
$runtimePath = (Resolve-Path ../ps3recomp-gt5p-provenance).Path
New-Item -ItemType Directory -Force scratch/reconstruction-build | Out-Null
& 'C:/Program Files/LLVM/bin/clang-cl.exe' /nologo /O2 /MD /LD /D_CRT_SECURE_NO_WARNINGS "/I$runtimePath/include" "/I$runtimePath/libs/video" /Foscratch/reconstruction-build/vp.obj /Fescratch/reconstruction-build/decoder.dll "$runtimePath/libs/video/rsx_vp_decompiler.c" /link /EXPORT:rsx_vp_decompile /EXPORT:rsx_vp_decompile_gpufetch
```

Run the proof with your local paths. The game root supplies normal private
initialization inputs but guest gameplay is never started:

```powershell
.venv/Scripts/python scripts/shader_reconstruct.py --report scratch/provenance-hsr/audit-final.json --trace scratch/provenance-hsr --catalog shadercache/library-v1/all --cache shadercache --decoder scratch/reconstruction-build/decoder.dll --engine build/gt5p.exe --game-root . --output ../GT5P-player-setup/scratch/reconstruction-proof --samples 3
```

The output must be new, ignored, and outside the input/cache/game-root trees;
use the isolated audit worktree's scratch directory when the game root is the
main development checkout. The report requires the flat `records` from an
individual provenance audit result (such as the measured `audit-final.json`),
not the top-level multi-route coverage report. `--start-line N` selects later
capture records. Samples are distinct VS/PS pairs; failures remain in the report
and cause a nonzero exit rather than being silently skipped.

Current sample limits: zero pixel compiler flags, zero unnormalized-key state,
available asset candidates and verified provenance links. The offline FP entry
point has a fixed target description; the tool explicitly reproduces the
captured pass's final-dither decision for other target formats, MRT or colour
masks. It still requires exact resulting source-key/bytecode matches. Other
missing translation state causes a failed proof, not an inferred success.

## Offline native mode

`RSX_PSO_RECONSTRUCT=<proof folder>` is honored only with
`GT5P_SHADER_PRECOMPILE_ONLY=1`, during backend startup preparation. Otherwise
it has no effect on normal library preparation. The folder contains:

- `request.recipe`: captured native descriptor used as the explicit state oracle.
- `code_<expected VS/PS identifier>.dxbc`: independently rebuilt shader bytes.
- `result.json`: expected/actual pipeline identifiers, creation result and HRESULT.

The mode does not read cached DXBC from the player's cache, delete inputs or
start guest gameplay. It is default-off and has no player setting. All asset
slices, generated source, bytecode, recipes and reports remain local; nothing
is added to the release ZIP.

## Validation on 2026-10-30

The discovery pass visited the 601 containers referenced by the existing FP
index (approximately 2.9 GB), finding 7,265 bounded vertex payloads. It found
exact instruction-prefix candidates for 211 of the snapshot capture's 216
vertex-input identifiers. These are candidate counts, not 211 completed
reconstruction proofs; the container set is not an exhaustive game inventory.

Seven selected samples passed the compilation/key/creation proof:

| Sample group | Samples | Vertex translation | Target format |
| --- | ---: | --- | --- |
| Executable programs | 3 | Normal, 3/4/7 instructions | R8G8B8A8_UNORM |
| Car LOD assets | 3 | GPU fetch, 23/23/24 instructions | R8G8B8A8_UNORM |
| Car LOD assets | 1 | GPU fetch, 37 instructions | R16G16B16A16_UNORM |

The car cases include vertex programs sourced from a different car LOD file
than the fragment program. Identical rebuilt results demonstrate reuse for
these samples; they do not establish coverage of every car or material.

Local reports in the audit worktree:

- `scratch/shader-reconstruction-20261030/report.json`
- `scratch/shader-reconstruction-cars-20261030/report.json`
- `scratch/shader-reconstruction-hdr-20261030/report.json`

The changed backend was compiled and relinked into the separate diagnostic EXE;
the normal game binary and shared runtime changes were left untouched. The
overlay was reapplied/checked against its pinned base. Synthetic tests cover
wrapper/table bounds, enclosing model bases, word order, exact candidate matches
and source mutation. Native negative tests rejected truncated recipes, modified
DXBC and a checksum-valid recipe with the wrong pipeline key, without entering
guest gameplay.

```powershell
.venv/Scripts/python scripts/test/shader_reconstruct.py
.venv/Scripts/python scripts/test/shader_reconstruct_native.py --engine build/gt5p.exe --game-root . --sample <verified sample folder>
```

## Material-derived pairings (Phase 139)

`scripts/shader_materials.py` reads original MDL3 version-1 material-data records
and follows their direct shader references. The chain measured on this build is:

1. The model's material table points to 0x28-byte material-data entries.
2. A material-data entry's +0x24 reference points to a structure whose +0x0C
   and +0x10 fields point into the declared SHDS vertex and fragment tables.
3. The fragment-table record's payload pointer joins the first field of a
   SHDS 0x40 record; that record provides the fragment instruction offset/size.

This uses actual pointer relationships, not every possible VP/FP combination.
The reader bounds all tables/payloads to the enclosing model's declared size,
requires exact table membership and a unique fragment-descriptor join, and
rejects unsupported versions and malformed shader bodies. Layout research used
PDTools' MIT-licensed readers; their unknown field names remain unknown here.
No blend, depth, target, sampler or other rendering state is inferred.

The 601 indexed containers contain 1,106 parseable model candidates and
**16,768 accepted direct material-data pairs**. Another 122 entries were rejected:
9 invalid vertex wrappers, 93 fragment programs without bounded END, and 20
truncated inline constants. These are material records, not distinct pipelines.

The HSR snapshot has 562 distinct captured vertex-input/fragment-instruction
pairs. Authored material references supplied candidates for **452 (80.4%)** of
them, appearing in 3,440 material records across 427 source containers. Vertex
matching uses the recorded instruction identity extent; fragment matching
normalizes inline constants as in the coverage audit. This is structural
pair coverage, not compiled-pipeline coverage. The capture includes boot/menu/pit
content, and the container inventory is still inherited from the FP catalogue.
The remaining 110 pairs need investigation; this does not prove they are absent
from all game assets.

```powershell
.venv/Scripts/python scripts/shader_materials.py --catalog <library-v1/all> --report <flat provenance audit.json> --trace <matching trace folder> --output scratch/material-audit
```

Add `--materials scratch/material-audit/report.json` to the reconstruction
command to require a material-derived pair. The proof reparses material pointers
from the original container, rereads both shader slices from that same model,
and checks translation/bytecode/native creation against the captured oracle.
It does not trust the saved report's pairing assertions or shader offsets.

Two samples (a character material and a car-interior material) passed this
stronger path, matching bytecode/source keys and native pipeline keys and
successfully creating D3D12 pipelines. State still came from captured profiles
and descriptors. Local evidence:

- `scratch/shader-materials-prefix-20261030/report.json`
- `scratch/shader-material-proof-20261030/report.json`

Synthetic checks in `scripts/test/shader_materials.py` cover embedded models,
table/payload bounds, exact pointer membership, ambiguous descriptors, malformed
shaders, CLI joining, output containment/no-overwrite, and unchanged inputs.
Existing vertex checks passed; native negative checks again rejected truncated
recipes, damaged code and a checksum-valid wrong pipeline key without executing
guest gameplay. No runtime behavior changed and no shared build was replaced.

## Material state audit (Phase 140)

`scripts/shader_material_state.py` follows material definitions' material-data
and GCM-state indices, keeping those separate from the shader-bearing data
records. It reparses original models and rematches verified vertex inputs and
fragment identities; the previous material report supplies only a model inventory.
No saved pairing or state assertions are trusted as decoded state.

The observed 0xA0-byte state block is a short RSX command list:

| Word | Meaning used by the reader |
| --- | --- |
| 0 | `0x00780304`: 30 incrementing writes starting at alpha-test enable |
| 31 | `0x000C0A6C`: depth compare, depth write mask, depth-test enable |
| 35 | `0x0004183C`: cull enable |
| 37 | `0x00020000`: return; decoding stops here |
| 38–39 | Preserved as uninterpreted trailing metadata |

The reader requires this exact packet layout, checks model/table extents and
material indices, and rejects unsupported values rather than guessing their
meaning. The zero/unset alpha blend-equation half observed in twenty blocks
maps to ADD, following this backend. The four comparable outputs are packed
blend key, colour write mask, depth bits, and cull-enable. Cull direction/winding,
full stencil state, texture state, targets and pass overrides remain unresolved.

The inventory with accepted shader pairs spans 599 containers / 1,098 models.
All **3,644** state blocks in that subset decoded with no rejected blocks or
invalid binding indices. This subset excludes models without accepted pairs;
it is not a count of every state block in the game.

Among the snapshot's 1,497 verified pipeline links, 1,164 had authored state
candidates through the same structural shader pair. Candidate comparisons were:

| Field | Links with a matching candidate / 1,164 |
| --- | ---: |
| Blend key | 1,163 |
| Colour mask | 1,146 |
| Cull enable | 1,164 |
| Depth bits | 13 |
| All four in the same candidate block | 9 |

Of links whose candidates matched blend/mask/cull-enable together, 1,110 had
authored LESS with writes on against live LEQUAL with writes on. Another 24
showed the same compare difference with writes off. This is measured disagreement,
**not proof of its cause**: shader pairs can belong to several materials, and
the audit does not identify exact draw ownership or the command that changed
depth. A pass override or runtime material patch remains a hypothesis. Do not
silently replace authored LESS with LEQUAL or treat these candidates as complete
pipeline recipes.

```powershell
.venv/Scripts/python scripts/shader_material_state.py --materials <material audit.json> --report <flat provenance audit.json> --trace <matching trace folder> --output scratch/material-state-audit
.venv/Scripts/python scripts/test/shader_material_state.py
.venv/Scripts/python scripts/test/shader_material_state_native.py --runtime <isolated runtime> --state-report scratch/material-state-audit/report.json
```

The native differential test extracts this runtime's own blend/depth/cull key
functions into a scratch DLL, compiles them with clang-cl and calls them without
starting the game or a GPU. **2,048 varied synthetic cases plus all 3,644 decoded
blocks matched (5,692 checks)**. Synthetic tests also cover packet signatures,
invalid enums/indices, table bounds, missing state, depth mismatch accounting,
captured-input integrity, output containment/no-overwrite and unchanged inputs.

Local evidence: `scratch/material-state-20261030/final/report.json`. No shared
runtime or game build was modified; this adds developer audit tools only.

The Phase 141 preparation proof below supersedes the unresolved common depth
difference. Exact draw ownership and additional pass overrides remain open.

## Material preparation and consumed commands (Phase 141)

The isolated runtime adds `GCM_DEPTH_PROVENANCE=<new JSONL file>`. It samples
only three-word depth packets on subchannel zero and, when the surrounding
layout matches, snapshots the entire 40-word material block before processing.
Each row includes the frame, FIFO/guest address, CALL return offset and depth
arguments. Every snapshot word must have an IO mapping. No guest state is written.

- Unset or `0`: disabled, with no trace reads/writes.
- `GCM_DEPTH_PROVENANCE_AFTER=<milestone>,<ms>`: optional delayed start.
- `GCM_DEPTH_PROVENANCE_LIMIT=<n>`: 512 by default, bounded to 1..4096.
- Parent directory must exist; an existing output file is refused. Each row is
  flushed; the recorder stops reading/writing once its cap is reached.

A 1080p/2x-MSAA HSR run used the separate diagnostic EXE and gated recording at
`QuickArcadeRoot,30000`. The final window capture confirmed the racing HUD.
512 records covered parts of three frames and 63 packet addresses; all were
material-shaped packets inside CALLs and all supplied LEQUAL. Against original
asset blocks, 17 matched all 40 words exactly, 242 differed only in the three
depth words and 253 were unmatched. The latter were six distinct live patterns;
nearest-block inspection found differences involving the trailing flag word or
alpha reference as well as depth. Similarity alone was not accepted as a match.

The local lifted function at `0x00834968` was then identified as a candidate
material-preparation routine. `prepare_state()` independently expresses its
bounded transformation for these blocks:

- Convert LESS to LEQUAL; preserve other comparison modes.
- Recompute bit zero of the final metadata word from alpha-test/blend enable,
  the measured metadata mask and depth-write enable. Other metadata stays opaque.

This is a tested material-preparation step, **not a global depth override**.
The optional native test extracts the original lifted function and its rotate/
shift helpers into an ignored scratch DLL, executes it on private block copies,
and compares every output word. It patches no generated source and starts no
game process. All **3,644 real blocks + 2,048 varied synthetic blocks matched**.
The test also checks input preservation. Game-derived oracle source/binaries
remain local and are not part of tracked files or release packages.

With preparation enabled, the preceding snapshot comparison changes as follows:

| Field | Raw candidates / 1,164 | Prepared candidates / 1,164 |
| --- | ---: | ---: |
| Blend | 1,163 | 1,163 |
| Colour mask | 1,146 | 1,146 |
| Depth bits | 13 | 1,164 |
| Cull enable | 1,164 | 1,164 |
| All four together | 9 | 1,146 |

The prepared 40-word blocks also matched **467/512** consumed FIFO snapshots
exactly, versus 17 without preparation; 45 remain unmatched. These are
byte-pattern candidates across assets, not unique material ownership or proof
that this particular guest function was the writer on every live call. The
independent oracle and FIFO evidence corroborate the transformation's relevance
without claiming a complete pipeline recipe.

```powershell
.venv/Scripts/python scripts/shader_material_state.py --materials <material audit.json> --report <flat provenance audit.json> --trace <matching trace folder> --prepare-materials --output scratch/prepared-state-audit
.venv/Scripts/python scripts/shader_depth_commands.py --states <state audit.json> --commands <depth JSONL> --output scratch/depth-command-audit
.venv/Scripts/python scripts/test/shader_material_prepare_native.py --generated <local generated/ppu_recomp_005.cpp> --states <state audit.json>
scripts/test/depth_provenance.ps1 -Runtime <isolated runtime>
.venv/Scripts/python scripts/test/shader_depth_commands.py
```

The command audit rereads original assets from the state report's model
inventory, compares exact/depth-only/prepared patterns, retains ambiguous
candidates and reports malformed/contradictory records separately. It does not
normalize unrelated differences away. Its transition histogram can count
several original depth variants for one captured block; do not sum it as unique
events. Synthetic checks cover these distinctions and damaged input. Recorder
tests cover disabled paths, milestone timing, packet filtering, mapped bounds,
the record cap, JSON and refusal to overwrite existing output.

Local evidence in this worktree:

- `scratch/depth-live-hsr-20261030/{commands.jsonl,prepared-audit/report.json}`
- `scratch/material-state-20261030/prepared/report.json`
- `scratch/depth-build/`: isolated backend/FIFO compilation and relink logs.

Window shots/logs are in the original checkout's
`scratch/pv/depth-live-hsr-20261030.*`. The isolated backend and FIFO unit were
compiled and linked with existing application/runtime objects, not rebuilt from
scratch. This diagnostic run is not a performance benchmark. The normal EXE
and shared runtime were untouched. The updated overlay was checked/reapplied
against its pinned base.

## Partial native descriptor reconstruction (Phase 142)

Add `--prepared-material-state` together with `--materials <material audit.json>`
to the existing reconstruction command. The tool reparses material definitions,
state indices and original 0xA0-byte source blocks. It applies the tested
preparation rule, selects same-pair candidates whose checked state agrees with
the captured oracle, then re-reads the selected source block with its SHA-256
check before using it. Stencil-enabled/mask passes are excluded from this proof.

The rebuilt shaders still come from original slices in that material's model.
The proof writes `pipeline/material.state`, a bounded versioned text file with
the derived blend key, colour mask and depth bits. No generated bytecode is
copied from the player's shader cache.

`RSX_PSO_RECONSTRUCT_MATERIAL=1` enables native replacement within the existing
guarded `GT5P_SHADER_PRECOMPILE_ONLY=1` / `RSX_PSO_RECONSTRUCT` proof path. It is
default-off and has no normal-play call site or player setting. The helper:

1. Validates the state file's size, version, enums and ranges and rejects
   unsupported stencil/depth-disabled descriptor cases.
2. Overwrites blend factors/equations/enable and colour-write masks on each
   active target, plus depth comparison and depth-write mask.
3. Recomputes the production pipeline key, requires the captured oracle key,
   then calls D3D12 pipeline creation without a persisted driver blob.

The helper replaces fields rather than only comparing existing values. A
well-formed altered colour mask was applied and produced a different key, so
creation was refused. Missing/malformed state was also rejected. Explicit `0`
ignored malformed state and preserved the legacy proof path.

**Six selected samples passed** source/bytecode/key checks and actual D3D12
creation: three opaque character cases, a blended character case, a blended car
menu material with depth writes off, and an opaque car-interior case. Native
results explicitly report `material_requested` and `material_applied`.

This is partial reconstruction. Culling direction/winding, alpha-to-coverage,
targets/formats, full stencil, input layout and remaining pass/texture state
are still captured; the checked cull-enable bit is an eligibility check, not
replacement of the culling descriptor. Candidate selection still uses captured
identifiers/state, so these results do not establish exact draw ownership or
capture-free first-run preparation.

Local reports:

- `scratch/prepared-pipeline-proof-20261030/report.json` (three samples)
- `scratch/prepared-pipeline-blend-proof-20261030/report.json` (one sample)
- `scratch/prepared-pipeline-car-proof-20261030/report.json` (two samples)

```powershell
scripts/test/material_reconstruct.ps1 -Runtime <isolated runtime>
.venv/Scripts/python scripts/test/shader_reconstruct.py
.venv/Scripts/python scripts/test/shader_reconstruct_native.py --engine <isolated diagnostic EXE> --game-root <development checkout> --sample <prepared proof sample folder>
```

The native descriptor test checks field replacement across three render targets,
preservation of unrelated culling/format fields, malformed values and unsupported
stencil rejection. Existing integrity and wrong-key tests passed alongside the
new material-file cases. All engine proof runs confirmed guest entry was not
executed. The isolated backend/FIFO units were compiled/relinked against existing
objects; no full clean build or race performance measurement was required.
The overlay reapplied against its pinned base; shared runtime/normal EXE remain
unchanged. These tools are not included in player release preparation yet.

## Asset-derived sampler selection (Phase 143)

`scripts/shader_material_textures.py` adds a bounded reader for one measured
binding layout. SHDS fragment records' 0x14 table supplies named sampler records
of kind `0x601`, with a supported unit field and zero remaining unknown fields.
Material definitions bind those names to indices into the model's 0x44-byte
texture-info table. Those indices are distinct from each texture's image ID.
The reader follows name/index references and bounds strings/tables to the model.
The initial Phase 143 reader rejected duplicate names/unit aliases, unsupported
records and invalid indices. Phase 144 below adds a measured coherent-alias
subset; unsupported relocation/array layouts are still not guessed.

Texture-info records supply authored filter and wrap registers. Sampler-bank
selection uses the current backend's default mapping. **2,048 varied cases
matched the production `rsx_samp_key` function** in an isolated DLL, without
starting the game or GPU. The existing native blend/depth/cull checks also
passed in that harness.

In the existing 599-container / 1,098-model inventory, the supported subset
contains **72,645 definition texture bindings**. There were 5,505 rejected
shader-data groups with ambiguous sampler names/units and 468 with unsupported
sampler records. The accepted groups had no missing definition names, but this
does not cover globally bound or otherwise undeclared units sampled by a shader.

Of 1,497 captured links, 349 had supported known sampled-lane candidates; all
349 matched those known lanes. Only **16 links** had every sampled unit resolved
and matching. The other 333 were partial. Another 1,148 had no known sampled
binding from this reader. These are same-pair candidates, not exact ownership
or complete texture/pipeline coverage. Matching filters do not prove the sampled
image contents or the other texture-dependent translation fields.

Add `--material-samplers` to the prepared-material reconstruction command to
require the complete supported subset. It selects the same material definition
as the state proof, reparses its bindings from the original model during proof,
and constructs the effective sampler key from zero using only resolved sampled
units. The captured sampler key is an equality oracle, not construction input;
there is no captured/default fallback for missing sampled units. The new key is
used for production FP translation and compilation before native creation.

Two selected car samples passed rebuilt source/bytecode identifiers, native
pipeline keys and D3D12 creation:

| Asset family | Sampled units | Derived sampler |
| --- | --- | --- |
| Car menu material | Unit 0 | Trilinear repeat, bank register 12 |
| Car LOD material | Unit 0 | Trilinear clamp, bank register 13 |

Both also used prepared material blend/write-mask/depth replacement. Other
texture-dependent fields (cube/gamma/unnormalized/shadow), targets/pass state,
and culling orientation remain captured. The state block writes only cull
enable; PGL setup has separate face-control commands whose control flow and
incoming winding context have not been reconstructed. Do not assume the most
common captured cull key is a universal asset default.

```powershell
.venv/Scripts/python scripts/shader_material_textures.py --states <state audit.json> --report <flat provenance audit.json> --trace <matching trace folder> --output scratch/material-texture-audit
.venv/Scripts/python scripts/test/shader_material_textures.py
.venv/Scripts/python scripts/test/shader_material_state_native.py --runtime <isolated runtime>
```

Tests cover unit/index identity (including a distinct image ID), unsupported
records/aliases, missing bindings, partial versus complete coverage, intact
unrelated sampler lanes, bad table bounds, deliberate capture mismatches,
input integrity, output containment/no-overwrite and unchanged inputs.

Local reports:

- `scratch/material-textures-20261030/report.json`
- `scratch/material-sampler-proof-20261030/report.json`
- `scratch/material-sampler-clamp-proof-20261030/report.json`

No runtime sources/builds changed for this stage. The two proofs used the existing
isolated diagnostic EXE in offline mode, never guest gameplay. Shared runtime,
normal binary and player defaults remain untouched.

## Coherent aliases and global requirements (Phase 144)

The scalar sampler layout includes distinct names assigned to the same unit.
The reader now groups them by unit and derives one binding only if **every
name is present and selects the exact same texture-info index**. Different
indices are rejected even when their sampler settings happen to match. A
missing alias leaves the entire lane unresolved. Duplicate identical names
and unsupported array/relocation record kinds remain rejected.

The same inventory now provides 160,461 resolved unit bindings, including 52,407
coherent alias groups. The remaining 659 rejected shader-data groups have
unsupported sampler records. This count differs from Phase 143 because removing
the earlier alias rejection exposes unsupported records that it previously hid.
The accepted subset still has no missing names, which is not a claim that all
sampled units in the game have material bindings.

Known sampled-lane candidates match **843 of 1,497 captured links**, versus 349
before. Each of these links has at least one matching candidate; this does not
mean every candidate for that link agrees. 827 are partial and 16 have every
sampled unit resolved. Another 654 have no known sampled binding. Complete
coverage did not increase: the remaining global/pass-bound units are a separate
dependency, and same-pair candidates do not identify unique draw ownership.

The SHDS fragment record's separate 0x38 table supplies global requirement
names, unit fields, kind values and identifiers. The reader records these as
metadata, not texture addresses or sampler defaults. In this supported inventory:

| Requirement | Unit field | Identifier |
| --- | --- | --- |
| `ditherMap` | 15 | 103, with a smaller different-kind group using 94 |
| `envMapSampler` | 14 | 71 |
| `realTimeShadowMap` | 13 | 87 |
| `realTimeShadowMapColor` | 12 | 96 |
| `shadowPCFMap` | 11 | 104 |
| `mirrorMapSampler` | 0–3 | 115 |

These identifiers' runtime lookup semantics are not established. The report
retains exact name/kind/unit/identifier signatures and reference counts, plus
which declared units the fragment instructions sample. Reference counts include
many material definitions sharing programs and must not be read as unique jobs
or pipeline counts. A unit declared global never inherits local settings merely
because a local binding has the same unit field.

For a developer **partial** proof, use `--material-sampler-lanes` instead of
`--material-samplers`, together with `--prepared-material-state` and `--materials`.
It reparses the original model, builds a known-lane value/mask from assets, and
replaces only those lanes in the captured key. Other lanes remain explicitly
captured; the report records derived/captured masks and global requirements.
No unresolved lane receives a guessed default. The complete mode still rejects
missing sampled units, and the CLI rejects selecting both modes together.

A character material with `alphaMapSampler` and `emissionMapSampler` aliased to
one texture rebuilt the local lane successfully. Generated shader source and
VS/PS bytecode matched, the native key matched, and D3D12 created the pipeline.
The dither lane remained captured; prepared blend/write-mask/depth replacement
was also active. This is an additional partial proof, not a new complete one.

Synthetic checks cover identical versus conflicting aliases, missing alias
names, global/local overlap, exclusion of unknown lanes and previous malformed
reference/integrity/output checks. Existing reconstruction eligibility checks
passed. No runtime source or normal-game build changed, and the isolated proof
never executed guest gameplay.

Local evidence:

- `scratch/material-sampler-global-signatures-20261030/report.json`
- `scratch/material-alias-lane-proof-20261030/report.json`

Next: trace the global requirement identifiers to their initialization/binding
records, starting with dither and shadow samplers. Array/relocation layouts,
texture-dependent translation fields and culling/pass/target context remain
separate work. Complete catalogue generation and player first-run integration
are still not implemented.

## Global callback initialization (Phase 145)

The global record identifier's low 16 bits select callback slots, rather than
directly identifying a texture-info record. A native oracle now executes the
local lifted initializer `00830050` with the measured disc ELF loaded into
private memory. It never starts the game or modifies the original generated
files. The table is BSS at `015fa4e0`, reached through the TOC pointer at
`TOC-66f8` and its `-7fe0` cell. Emit slots begin at `+388`, lookup slots at
`+7b0`, each with four-byte OPD pointers.

| Identifier | Requirement | Emit code | Lookup code |
| --- | --- | --- | --- |
| 71 | environment | `00d6caa0` | `00d6ad38` |
| 87 | shadow | `00d6d930` | `00d6de98` |
| 94 | dither, alternate kind | `00d77cc0` | `00d6de78` |
| 96 | shadow color | `00d6d898` | `00d6de98` |
| 103 | dither | `00d77c20` | `00d6de78` |
| 104 | PCF | `00d77a90` | `00d6de78` |
| 115 | mirror | `00d6d9c0` | `00d6deb8` |

All fourteen OPDs resolved to nonzero code addresses with the expected TOC.
The initializer requires its first argument to equal 1 and the second to equal
`0000ffff`; negative gate checks left selected slots empty. Its fallback-value
helper was stubbed, and two different return values produced identical callback
slots. The real memory-fill routine was included. Trampoline draining is omitted
only for extracted routines checked not to schedule trampolines. This verifies
the selected callback initialization under those conditions, not the entire
renderer initialization or actual runtime dispatch.

Two real lookup callbacks were executed separately on private sentinel fields:
dither/PCF read registry `+70`; shadow/color-shadow read the object reached via
the same TOC root's `-8000` cell, at object `+1cb0`. Ten checks, including
high-bit-set values, passed. These are lookup values used by the binding path;
they have not been established as texture addresses or sampler registers.

Read-only structural inspection of emit callbacks suggests dither and PCF route
through `0081f0f0` with different packed arguments, while shadow routes a dynamic
texture object through `00ba6cf0`, with a fallback path when absent. These emit
paths have **not** been executed in this oracle. Their packed arguments must not
be treated as proven sampler keys. Next: trace and execute those helpers with
controlled texture descriptors, then compare the emitted commands with captured
state. No new global lane is currently derived; complete coverage stays at 16.

Run locally with x64 VS/LLVM available:

```powershell
python scripts/test/shader_global_registry_native.py --generated ../GT5P/generated --elf ../GT5P/input/EMAIN.ELF
```

The test requires the measured ELF checksum, rejects other builds, and leaves
extracted source, DLL and report under a unique ignored scratch directory. No
game-derived source or payload is packaged. Successful evidence this session:
`scratch/global-registry-10a6cace5f564692be405b7c78172b7b/report.json`.
Only the developer oracle and documentation changed; no player setting, runtime
behavior, shared checkout, game build or catalogue-generation default changed.

## Conditional dither/PCF samplers (Phase 146)

The oracle now executes both branches of the three dither/PCF emitters, their
real texture-state helpers and command writer. The active resource providers
are controlled stubs supplying a private resource descriptor; the shader
callbacks, packed arguments, sampler reset/set operations and command emission
are real extracted routines. The fallback uses real default-texture creation,
descriptor copying and binding, with initially zero private BSS. No gameplay
or original generated source is changed.

Across identifiers 94/103/104, sixteen units, three widths/addresses and two
branches, **288 emitted address/filter pairs** match an independent sampler
implementation:

| Path | Address register | Filter register | Effective bank register |
| --- | --- | --- | --- |
| active resource | `00030101` | `01012000` | 4 (nearest/repeat) |
| default fallback | `60010101` | `02022000` | 8 (linear/repeat) |

Identifiers 94 and 103 differ in other texture-format behavior; this change
derives their sampler settings only. Resource sizes and addresses do not change
these measured sampler pairs. The fallback default is conditional on that
initialized template; this is not a claim that arbitrary dynamic textures have
those settings.

Both `shader_material_textures.py` and `shader_reconstruct.py` accept developer
option `--global-sampler-path active|fallback`. Reconstruction requires either
`--material-samplers` or `--material-sampler-lanes` plus prepared material state.
The path is an explicit conditional input. It is never silently selected from
captured samplers. A future catalogue may enumerate both variants, but this
change does not establish which path any particular draw owns.

Only exact supported name/kind/identifier signatures resolve. Unknown kinds,
names or identifiers, duplicate global units and local/global overlaps remain
unresolved. Reports preserve original global requirements and show derived
bindings, the chosen path and remaining unresolved globals. Default behavior
without the option retains the earlier local-only proof.

For the same 1,497-link corpus, active-path candidates yield 1,030 known-lane
matches, 14 mismatches and 453 links with no known sampled binding. 122 have
every sampled sampler lane covered. Fallback candidates match 30 links, 26
with complete sampled-lane coverage. Their unions are 1,044 known-lane matches
and 132 complete sampled-lane matches, with 16 overlapping complete matches.
These are existence-of-candidate counts; exact material/draw ownership remains
unproven. They do not mean 132 complete native pipeline descriptions are derived.

Eight active-path and two fallback-path samples rebuilt source/VS/PS bytecode,
matched native keys and created D3D12 pipelines. The character alpha/emission
alias sample now derives its entire sampler key, including dither, rather than
retaining the dither lane from capture. Prepared blend/write-mask/depth fields
also remain independently replaced. Other translation fields and pass/target
descriptor fields are still captured.

Validation includes the 288 native command checks, synthetic unknown-signature,
overlap/duplicate/path-selection checks, existing input-integrity checks and
the ten successful native pipeline proofs. No runtime overlay, normal game
binary, player setting or release payload changed. Local evidence:

- `scratch/global-registry-09d70a278aa94677a5bcd6f07fde4119/report.json`
- `scratch/global-sampler-{active,fallback}-audit-20261030/report.json`
- `scratch/global-sampler-eight-proof-20261030/report.json`
- `scratch/global-sampler-fallback-proof-20261030/report.json`

Next: recover dynamic shadow/environment/mirror texture descriptors and the
remaining translation/pass/target context. Their emit wrappers largely bind
supplied descriptors, so dither's fixed sampler rules cannot be generalized to
them. Complete catalogue generation and player first-run integration remain
unfinished.

## Conditional LV shadow pass (Phase 147)

The environment, shadow, shadow-color and mirror emit callbacks were executed
with 1,024 varied synthetic supplied descriptors (four identifiers, sixteen
units, four wrap settings and four filter settings). They preserve the supplied
address/filter words and other descriptor fields, replacing the unit-specific
command headers. Another 64 absent-resource checks use the real initialized
fallback descriptor, selecting sampler 8. These tests do not establish the
contents of any real dynamically constructed resource.

The measured dynamic dependency locations are environment object `+1c34` for
selector zero, shadow `+1c44`, mirror `+1c48`, and the separate shadow-color
pointer returned by `0082c748`. Nonzero environment selectors have not been
exercised by this oracle. The callbacks' sampler settings cannot be derived
from their identifiers alone.

Further structural tracing found the LV shadow pass `008103f0` writes sampler
settings before passing its resource to `0082e330`. The expanded native oracle
executes that full pass with private resource descriptors. Scene rendering,
render-state helpers and virtual resource access are mocked; the sampler
writes, shadow descriptor setter, memory copying and color-descriptor format
conversion are real extracted code. No GPU work or guest game entry runs.

Across four input address words and all 8x8 min/mag filter combinations, **256
enabled cases** force S/T wrap nibbles to 4 and min/mag fields to 2. Both shadow
and shadow-color descriptors consequently select **sampler 9 (linear/clamp)**.
Another 256 cases with the pass's early-exit gate set leave the supplied input
sampler fields untouched. This is a conditional pass-setup proof; it does not
show that every draw uses the LV shadow resource or that scene rendering is
correct with these mocks.

Both audit and reconstruction accept developer option
`--shadow-sampler-path shadow-lv`, independently of the dither/PCF path. Only
exact `realTimeShadowMap`/`realTimeShadowMapColor` kind/identifier signatures
qualify, with the same overlap/duplicate rejection as other global lanes.
Derived binding records carry `address_mask=00000f0f` and
`filtering_mask=07070000`: only those sampler-relevant bits are known. They are
not complete raw address/filter registers and must not supply gamma, LOD or
other texture translation fields. The caller explicitly selects this variant;
the capture is an oracle, not the source of the chosen settings.

With active dither plus this shadow variant, the same corpus has 336 matching
complete sampled-sampler candidates, up from 122 for active dither alone.
Known lanes match on 861 links, disagree on 183, and 453 have no known sampled
binding. Adding a conditional shadow constraint can eliminate candidates that
only matched their local/dither lanes previously. The disagreements are retained,
not hidden by dropping the shadow requirement. These remain candidate counts;
pass/draw ownership is unresolved.

Four newly eligible car-interior samples rebuilt shaders and their complete
sampler keys, matched native keys and created D3D12 pipelines. All contain an
actual sampled shadow requirement, alongside dither and local texture bindings.
Prepared material blend/write-mask/depth replacement was active; other shader
translation and pass/target descriptor fields still came from capture. Synthetic
unknown-signature/pass-selection tests also pass. Local evidence:

- `scratch/global-registry-7c9d3138c4f04a999fc6b903c199ccf7/report.json`
- `scratch/shadow-lv-sampler-audit-20261030/report.json`
- `scratch/shadow-lv-sampler-proof-20261030/report.json`

The next concrete trace is the environment descriptor assigned by `0082e240`,
including the dynamic environment path `00810f20` and its framebuffer resource.
The local RTTI table identifies the shared FrameBuffer/CubeFrameBuffer texture
getter at `008293a8`; its descriptor is at object `+54`. This last structural
lead has not yet been executed in the oracle. Environment/mirror setup, other
shadow pass variants, unsupported sampler layouts and remaining translation,
culling/target/pass fields still prevent complete catalogue generation and
player first-run integration. Normal game behavior and the runtime overlay
remain unchanged.


## Conditional framebuffer environment samplers (Phase 148)

`--environment-sampler-path framebuffer-single|framebuffer-mipped` is a new
explicit developer input to the texture audit and reconstruction proof. It
applies only to the measured `envMapSampler` / kind `0x901` / identifier 71
signature. It assumes successful framebuffer texture setup with respectively
one or multiple mip levels, and **no later sampler override**. It never chooses
that assumption from captured filtering. Unknown signatures, duplicate global
units and local/global overlap remain unresolved; mirror requirements receive
no new rule.

The local native oracle executes the real texture-setup helper `00BA1080`,
shared framebuffer getter `008293A8` (descriptor at object +0x54), descriptor
assignment `0082E240`, and environment emitter `00D6CAA0` on private memory.
The allocation helper `00BA08B8` and address conversions are controlled stubs;
this tests post-allocation setup, not real resource allocation or rendering.
Structural callers `00829BB0` / `0082A210` reach this setup helper. Dynamic
environment rendering `00810F20` obtains a descriptor through the framebuffer's
virtual getter and assigns it after rendering; that full render path has not
been executed by this oracle.

Across mip counts 1/2/4/8, four environment slots, sixteen texture units and
four poisoned initial descriptors, **1,024 successful checks** match independently
expressed sampler-relevant address/filter bits. One mip selects linear/clamp
(bank 9); multiple mips select trilinear/clamp (bank 13). The getter refreshes
dimensions without changing these bits; assignment updates the selected slot
and generation counter, and emission preserves the sampler. Another **1,024
allocation-failure checks** leave the descriptor's address/filter words untouched.
Previous registry, dynamic-emission, dither/PCF and shadow checks also pass.
Only S/T wrap and min/mag filter bits are derived; LOD, format, image identity,
cube/gamma/unnormalized/shadow masks and all other translation state stay unknown.

With explicit active dither and LV shadow paths, the mipmapped environment
candidate covers every sampled sampler lane for **861 of 1,497** retained links
(previously 336). There are 183 known-lane mismatches and 453 links without
known sampled bindings. The single-mip candidate retains 336 complete matches
and has 708 mismatches. These are conditional same-pair candidates, not exact
draw ownership or full pipeline coverage. Mismatches must not trigger automatic
path guessing. No observed environment lane in this snapshot validates the
single-mip candidate; its support comes from the controlled native setup check.

Four environment-using samples, selected from the newly complete links, rebuild
asset shaders, match source/bytecode/native keys, and create D3D12 pipelines.
They derive complete sampled sampler keys and prepared blend/write-mask/depth
fields; other translation/target/pass fields remain captured. A separate initial
four-sample run contains one environment sample and three regression samples.
Native negative checks reject truncated recipes, damaged code, wrong keys and
missing/malformed/wrong material state; explicit material mode 0 retains its
prior behavior. No proof process executes guest entry.

Local evidence:

- `scratch/global-registry-94b3734c9c74404cb3181afa06e50b09/report.json`
- `scratch/environment-{single,mipped}-sampler-audit-20261030/report.json`
- `scratch/environment-proof-input-20261030.json`: unmodified source audit rows
  restricted to links newly complete under the explicitly selected mipped path.
- `scratch/environment-only-sampler-proof-20261030/report.json`
- `scratch/environment-mipped-sampler-proof-20261030/report.json` (initial run)

Repeat the existing audit/proof commands with the new option; proofs also require
`--prepared-material-state --material-samplers --materials <material report>`.
Synthetic checks cover both choices, missing choices, signature mismatches,
duplicate/overlapping units, input preservation and invalid choices. The original
checkout and shared runtime/build remain untouched. No runtime source, normal
player behavior or release packaging changed.

Next: independently establish which live render paths supply these descriptors,
including later overrides and the mirror resource's construction/assignment.
The min-filter write near `00808210` in `008079EC` remains a structural lead,
not a verified universal environment rule. Recover the remaining texture-dependent
translation and pass/target fields before generating capture-free native recipes.


## Partial mirror scene-copy sampler (Phase 149)

The mirror descriptor has a separate producer: `00705FC0` obtains a scene
buffer's descriptor by its virtual copy getter, changes the copy, and assigns
it through `0082DF70`. The real setter writes registry +0x1C48 and its generation
at +0x1C98. Emitter `00D6D9C0` uses that supplied descriptor. A native oracle now
executes the full consumer, the real copy getter `00827DD0`, framebuffer getter
`008293A8`, setter and emitter. Controlled scene/camera/render providers,
viewport setters, memory copy and plane normalization are stubbed. This proves
controlled descriptor processing, not actual mirror rendering or the identity
of the live resource supplying that virtual getter.

**4,096 checks** vary four S/T wrap combinations, all 64 min/mag filter pairs
and sixteen texture units. The consumer forces linear min/mag but preserves
incoming S/T wrapping. The original source descriptor's sampler is unchanged;
viewport dimensions and the camera field modified during the call are restored.
The checked generation/pointer updates precede emission. This rules out claiming
an identifier-wide clamp rule from the consumer alone.

New explicit developer input `--mirror-sampler-path scene-copy` applies only to
`mirrorMapSampler` / kind `0x601` / identifier 115. It derives **two bits** of the
sampler-bank nibble: value 8 under mask 12. Wrap bits under mask 3 remain unknown.
The option never obtains wrap from a capture or selects a path from capture.
Unknown signatures, duplicate global units and local/global overlaps retain the
previous unresolved behavior.

The audit and reconstruction helpers now carry a per-binding `sampler_mask`.
Existing complete bindings default to mask 15. `known_sampler_key()` returns an
exact value/bit-mask pair. Partial proofs replace only those measured bits;
complete proofs reject any sampled bit left unknown. This lets the consumer's
filter rule contribute without pretending that its input wrap has been recovered.
Texture audit schema **2** adds `lane_masks` alongside each profile's `lanes`;
consumers must honor those masks. A mirror-only profile with mask 12 is never a
complete sampler profile, even if its representative value equals a capture.

Synthetic tests exercise all four retained wrap combinations, filter-bit
replacement, full-key rejection, unsupported signatures/paths, overlap/duplicates,
and CLI comparisons where different wraps match the same measured filter bits.
The production native oracle compares its emissions against the independent
partial binding. Prior registry/dither/shadow/environment checks still pass.
An environment shader/native pipeline reconstruction regression also passes
with the new mask handling; it is not a mirror shader proof.

The asset inventory contains 63 mirror requirements, but the retained HSR
snapshot has **no same-pair authored mirror candidate**. Its complete matching
sampler coverage therefore stays at 861/1,497, with 183 known-lane mismatches and
453 links without known sampled bindings. No new captured mirror shader/native
pipeline proof or coverage increase is claimed. The new conditional path can be
used when a matching mirror pair is independently linked later.

Local evidence:

- `scratch/global-registry-ab8b1d3d66fa46c4a5fe1542eaf2bfb2/report.json`
- `scratch/mirror-scene-sampler-audit-20261030/report.json`
- `scratch/mirror-mask-environment-regression-20261030/report.json`

Repeat the oracle/audit commands above with `--mirror-sampler-path scene-copy`
on the audit. For a partial reconstruction, combine it with
`--prepared-material-state --material-sampler-lanes --materials <report>`.
Full sampler mode remains available for candidates with all bits derived.
No runtime or player defaults changed; generated sources and all game-derived
oracle outputs remain ignored. The original checkout/shared runtime were read
only. Next trace the actual mirror source's creation and wrapping, obtain an
independent mirror pair link, and recover remaining texture-dependent translation
and target/pass state.
