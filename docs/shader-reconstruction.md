# Asset shader reconstruction proof

Phases 138–141, branch `feature/shader-coverage-audit`. This is a small developer proof,
not first-run setup or a complete shader catalogue. It follows the
[coverage/provenance work](shader-coverage.md).

**Measured result:** seven sampled shader pairs were rebuilt from original
asset slices, matched captured VS/PS bytecode identifiers, reproduced the exact
native pipeline key and successfully created a D3D12 pipeline. Three are small
executable programs, three use car LOD assets with GPU vertex fetching, and one
uses car LOD assets with a 16-bit colour target.

Rendering state and the native pipeline descriptor still come from a diagnostic
capture. They are not yet derived from authored material/pass definitions. No
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

Next: integrate prepared material state into the reconstruction proof, then
resolve the remaining colour-mask/blend cases and pass/target/texture state.
Complete catalogue generation and player first-run integration remain separate.
