# Project Tourline Prologue v0.2

Adds optional experimental preparation of known shaders and pipelines before
play. Normal launching and asynchronous draw compilation remain available.

The player entry point is **tourline-prologue.exe** and the game window title is
**Project Tourline Prologue**. Existing storage/saves/settings remain compatible.

- Run **Prepare shaders.cmd** after completing normal game setup. Select your
  own GT.VOL directory unpacked with GTToolsSharp. The unpacker/assets are not
  supplied; selecting the extracted disc folder alone is insufficient.
- A bundled standalone helper reconstructs both shader stages and native
  pipelines on the local machine. No separate Python/compiler installation is
  required. Shader bytes, generated code and GPU driver blobs stay in storage.
- Exact fragment batching, progress, cancellation and verified resume are
  supported. Only a fully verified preparation is selected for subsequent play.
- The starter describes 2,334 observed menu/High Speed Ring/Daytona pipeline
  records. This is partial observed coverage; it does not cover every car,
  track, camera or renderer setting, or independently recover every pass.

Preparation may take several minutes and uses additional local disk space.
It targets the supported disc ELF and default translation/root-signature
settings. Missing/incompatible entries and different settings use normal demand
compilation. Windows compiler/driver differences can reject preparation safely.
Consistent gameplay stutter reduction is not established. No zero-stutter claim
is made.

Cancellation retains completed work. Abrupt interruption can leave a partial
artifact that fails verification on retry; automatic cache repair is not
provided. Keep the logs/cache for inspection and use normal launching or
`--no-prepared` if preparation cannot complete.

Extract the complete new ZIP into its own folder, close the old game and use the
new tourline-prologue.exe. Existing selected storage/saves/settings are retained. To roll back
cache selection, run `tourline-prologue.exe --no-prepared`; keep all cache directories. Older
release binaries can still be used from their separate installation.

The package includes only the launcher/engine/dependencies, licensed art, the
standalone tool, notices and validated identifier/numeric-state metadata. It
contains no personal game files, decrypted ELF/SELF, raw shaders or cache files.

BCUS98158 v03.00 original game files are required and are not included. Validation
evidence and remaining limitations are recorded in docs/progress.md. Preparation
scripts do not create release tags or publish assets themselves.
