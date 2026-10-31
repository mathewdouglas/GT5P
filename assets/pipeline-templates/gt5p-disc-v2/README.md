This optional developer starter contains 2,334 verified pipeline records for
BCUS98158 version 3. It contains program identifiers and numeric translation/native
state only. It contains no shader microcode, source, DXBC or driver binaries.

The records came from local menu/High Speed Ring/Daytona play. Both shader stages were
reconstructed from original assets, their identifiers checked, and all 2,334
native keys reproduced and pipelines created on the test machine. Unsupported
or unavailable programs and branching vertex contexts are excluded. This is an
observed-state template, not independent recovery of material/pass ownership or
whole-game coverage.

`index.json` verifies the metadata shards. Format 2 pins the renderer source
contract, Windows x64 recipe/key ABI, explicit default settings and original ELF.
The preparer verifies locally rebuilt shaders and actual root-signature/native
keys before accepting anything. Incompatibilities remain on the demand path.
Driver results are constructed locally for the user's GPU and stay local.

The current renderer contract supports exact fragment batching. All
2,334 records passed a single empty-application-cache reconstruction/native proof
after that change; record contents and expected keys are unchanged. Developer
preparation uses batching by default; `--fragment-mode legacy` is the rollback.
Matching checkpointed template output supports `--resume`, verifying cached
shader identifiers and revalidating native pipelines before acceptance.

`asset-map.json` is a separately versioned hash/offset map for 119 programs outside
the supported SHDS tables. Supply `--assets <original unpacked GT.VOL directory>`
to select it automatically. It contains container/program hashes, file offsets,
sizes and byte order only. Container hashes and program identities are verified
locally before compilation; captured programs are not needed by users.

See [the preparation workflow](../../../docs/shader-precompile.md). Pass this
directory to `scripts/pipeline_template.py prepare --template`. Nothing loads it
by default. The optional v0.2 player helper uses `player-map.json`, a complete
hash/offset map for all 976 unique programs in this starter, and requires only
the user's original unpacked assets and verified ELF, without a developer
catalogue. The smaller `asset-map.json` remains the supplemental developer map.
Templates do not establish menu/race preload ownership; preparation
does not fabricate those membership indices. No launcher/release default or
zero-stutter claim is made.
