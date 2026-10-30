This optional developer starter contains 1,196 verified pipeline records for
BCUS98158 version 3. It contains program identifiers and numeric translation/native
state only. It contains no shader microcode, source, DXBC or driver binaries.

The records came from local menu/High Speed Ring play. Both shader stages were
reconstructed from original assets, their identifiers checked, and all 1,196
native keys reproduced and pipelines created on the test machine. Unsupported
or unavailable programs and branching vertex contexts are excluded. This is an
observed-state template, not independent recovery of material/pass ownership or
whole-game coverage.

`index.json` verifies the metadata shards. Format 2 pins the renderer source
contract, Windows x64 recipe/key ABI, explicit default settings and original ELF.
The preparer verifies locally rebuilt shaders and actual root-signature/native
keys before accepting anything. Incompatibilities remain on the demand path.
Driver results are constructed locally for the user's GPU and stay local.

See [the preparation workflow](../../../docs/shader-precompile.md). Pass this
directory to `scripts/pipeline_template.py prepare --template`. Nothing loads it
by default. Templates do not establish menu/race preload ownership; preparation
does not fabricate those membership indices. No launcher/release default or
zero-stutter claim is made.
