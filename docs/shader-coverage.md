# Shader and pipeline coverage audit

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

Current recipes associate a native pipeline descriptor with compiled VS/PS
bytecode. The raw fragment corpus is recorded separately. Fragment profiles
are also pooled without per-program provenance. No existing record reliably
joins the original program, its exact translation state, resulting bytecode
and pipeline. Vertex-program and material/pass extraction are absent too.

The next implementation step is an opt-in provenance recorder at actual shader
translation/pipeline creation: record raw program identities and relevant
translation state together with the resulting VS/PS and pipeline identifiers.
Keep it off during normal play. That will allow the next audit to identify
which asset-backed programs and state combinations reconstruct actual pipelines,
then narrow unmatched programs by their owning draws/materials. A hash alone
cannot reconstruct an unavailable program.

Once those mappings are verified, derive states from the game's material/pass
logic rather than compiling the full shader/state cross-product. Automated
content loading can then validate coverage without manually racing every car.
This work is not yet a distributable complete catalogue or a guarantee of zero
first-use compilation.

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

The practical next step is the provenance recorder described above, followed
by ownership/fixup analysis for the unmatched programs. Extending catalogue
size or cross-multiplying pooled profiles alone cannot establish complete
pipeline reconstruction.
