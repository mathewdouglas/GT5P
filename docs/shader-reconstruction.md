# Asset shader reconstruction proof

Phase 138, branch `feature/shader-coverage-audit`. This is a small developer proof,
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

The next implementation target is deriving shader pairing and rendering state
from material/pass data, so preparation no longer depends on a captured native
descriptor. Complete catalogue generation and player first-run integration are
still separate work.
