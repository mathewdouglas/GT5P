# Player ZIP and first-run setup

Implementation branch: `feature/player-setup`, based on the v0.18.0 upgrade.
Worktree: `../GT5P-player-setup`. The shared working tree, runtime checkouts,
generated sources and existing build were left alone. This work was written
while Claude was active: **no compiler, test executable, game, emulator or
release packaging command has been run for it**. Compilation and the acceptance
checks below are required before distributing a player ZIP. No release asset
has been uploaded.

## Player experience

1. Extract the entire ZIP and launch **GT5P.exe**.
2. Select the extracted disc dump, or its `PS3_GAME` directory. The launcher
   checks `PARAM.SFO` for BCUS98158 / APP_VER 03.00 and requires `GT.VOL` and
   `TV.DAT`. Selecting an ISO is not supported.
3. If a matching decrypted `USRDIR/EMAIN.ELF` is present, it is reused. Otherwise
   select an existing decrypted ELF or choose an installed RPCS3 executable.
   The RPCS3 option copies `EMAIN.SELF` into the private import directory and
   invokes `rpcs3.exe --decrypt <copy>`; it never writes into the original dump.
   If CLI decryption fails, the dialog points at its logs and offers the manual
   RPCS3-decryption path on the next attempt. RPCS3, firmware and keys are not
   bundled, downloaded or configured by this launcher.
4. The ELF must match the release's SHA-256. A verified private copy and the
   selected dump path are saved. Later launches skip setup while they remain
   valid. A missing/moved/wrong-version dump reopens setup.
5. Continue using **GT5P.exe**. It starts `runtime/gt5p.exe` internally. Players
   do not need Python, a compiler, the repository, junctions or developer batch
   files. The initial preset is 720p, 16:9, 2x MSAA with async shader/pipeline
   compilation; existing settings are not overwritten. F1 changes game options.

This is one visible launch entry point with two executables internally. A
separate setup-only executable adds no benefit: `GT5P.exe --setup` changes the
installation path without duplicating startup logic. The engine EXE alone is
still a developer entry point and does not load the launcher's saved selection.

## Files and persistence

The release contains only these selected files:

```text
GT5P.exe                 native /MT launcher, no managed runtime required
release.ini              schema, target, ELF digest and engine digest
START-HERE.txt
LICENSE.txt
runtime/gt5p.exe
runtime/SDL2.dll
runtime/avcodec-61.dll
runtime/avutil-59.dll
runtime/swresample-5.dll
runtime/<app-local MSVC runtime DLLs>
assets/glyphs/...         distributable glyph art and its license
licenses/...             dependency notices and matching source/build information
```

It excludes the ELF/SELF, PARAM.SFO, ROM volumes, savedata, gamedata, existing
settings, shadercache, logs, firmware, keys, and RPCS3. The ELF's digest is
metadata, not the file. The package script never recursively copies a build or
third_party directory. ZIP inputs are explicit; assets are limited to PNG/text
and checked for expected content. EXEs/DLLs must be native Windows x64 PE files.

Mutable files live under `%LOCALAPPDATA%\GT5PRecomp`:

- `setup.ini`: selected dump path, written atomically after successful setup.
- `input/EMAIN.ELF`: verified personal copy; never part of a release.
- `gamedata`, `gt5p_settings.toml`, `shadercache`, `logs` and copied glyph assets.
- `imports`: private per-attempt RPCS3 input/output; contains personal game data.
  These import directories can be removed by the player with the game closed
  after setup; do not remove the verified `input/EMAIN.ELF`.
- `logs/play.out`, `logs/play.err`: latest game run; `logs/decrypt.*`: latest
  helper run; `logs/setup.err`: last setup/launch failure.

No existing developer save is imported automatically. A player can transfer
their save into their private `gamedata` with the game closed. Updating the ZIP
does not overwrite user data. An exclusive user-directory lock prevents a
second launch. A Windows job owns only the child the launcher created; killing
the launcher cannot leave its game running and then allow a duplicate launch.

Options:

| Option | Effect |
| --- | --- |
| `--setup` | Select a different dump; cancellation keeps the old selection |
| `--open-data` | Open user data in Explorer, including while the game runs |
| `--check` | Validate release/config/dump/ELF without dialogs or launching a child; exit 0/1 |
| `GT5P_USER_DIR=<folder>` | Separate writable user-data location/profile |
| `GT5P_LAUNCHER_SETUP=0` | Suppress automatic interactive setup and report missing/invalid configuration |

The game receives the existing `GT5P_ROOT`, `GT5P_SETTINGS`, `GT5P_GAME_DIR`,
`PS3_VFS_ROOT` and `PS3_GAMEDATA_ROOT` overrides. Its working directory is user
data, so ordinary cache/log writes work even if the install folder is read-only.
Glyph art is copied from the ZIP into that working directory on launch.

The only game-source integration change is the direct `PARAM.SFO` lookup in
`src/main.cpp`: an absolute game directory must not be prefixed by the writable
VFS root. The runtime's cellFs already handles absolute mappings. This fix
must be included in the engine build packaged with the launcher.

The engine still has ANSI/path-length limits. The launcher rejects paths that
cannot round-trip through the system code page, or exceed its conservative
length limit, with a visible error instead of a white-window failure. Full
Unicode/long-path support across the runtime is separate work.

## Maintainer build and packaging (when Claude is idle)

First integrate the small main.cpp fix with Claude's completed changes. Build
the game normally for **BCUS98158** in Release/RelWithDebInfo using its matching
local decrypted ELF. The packager relies on the maintainer supplying that same
ELF; it cannot reconstruct the game's compiled input from an arbitrary EXE.
Do not package while the game build is writing outputs.

Build only the launcher from an **x64 Visual Studio Developer Command Prompt**:

```bat
scripts\release\build_launcher.cmd C:\GT5P-release\launcher
```

The launcher uses Win32 dialogs, COM, CNG SHA-256 and a static C++ runtime.
It has no game/runtime linkage and is deliberately outside the shared CMake
game target; adding/changing it cannot invalidate lifted game-code chunks.

Prepare a notices directory containing these exact text filenames:

- `SDL.txt`: SDL license/distribution notice from the bundled SDL build.
- `FFmpeg-LGPL.txt`, `FFmpeg-GPL.txt`: full applicable license texts.
- `FFmpeg-SOURCE.md`: exact bundled FFmpeg version, binary origin, matching
  corresponding source location, patches and build instructions/configuration.
  Use the actual bundled DLL build, not an unrelated newer source tree.
- `ps3recomp-LICENSE.txt`: pinned runtime's license.
- `MSVC-NOTICE.txt`: applicable notice for app-local redistributable DLLs.

Use the x64 redistributable DLL directory matching the game's compiler, not
debug CRT DLLs or arbitrary copies from System32. Required: msvcp140.dll,
vcruntime140.dll and vcruntime140_1.dll. Known companion DLLs are also included
when present. Review dependency notices/source availability and runtime DLL
dependencies before publishing; the script checks presence, not their legal
or version correctness. It performs no dependency downloads.

```powershell
python scripts/release/package_player.py `
  --build-dir C:/path/to/completed/build `
  --launcher-exe C:/GT5P-release/launcher/GT5P.exe `
  --elf C:/path/to/matching/EMAIN.ELF `
  --vc-runtime-dir C:/path/to/VC/Redist/MSVC/version/x64/Microsoft.VC143.CRT `
  --notices-dir C:/GT5P-release/notices `
  --output C:/GT5P-release/GT5P-windows-x64.zip
```

Python is needed by the maintainer only. The packager refuses overwrite,
wrong-target/debug builds, non-ELF inputs, missing dependencies and asset links.
It detects changes to copied inputs and verifies the ZIP's actual engine digest
before committing the final filename. Only the named ZIP should be attached
to a GitHub release, never input/, gamedata/, shadercache/ or scratch/.

## Acceptance checks still required before publishing

Do these in an isolated user-data directory on a spare Windows machine/Ally,
after Claude's testing is finished. No such checks have been run in this work.
`python scripts/test/player_package.py` covers packaging rejection, input
exclusion, digest binding and preservation of an existing ZIP using synthetic
fixtures only. It is included for that later validation, not executed here.

| Check | Required result |
| --- | --- |
| Build launcher /MT x64 | No missing declarations/link symbols/manifest errors |
| Fresh extracted ZIP, no developer tools | Folder picker opens before any game window |
| Valid disc root and PS3_GAME selections | Both normalize correctly; ELF digest accepted |
| Wrong title/version, ISO, missing VOL/DAT, wrong ELF | Clear failure; no game launched |
| Cancel folder/ELF/RPCS3 picker | Clean exit; original setup remains valid |
| Existing ELF and RPCS3 helper paths | Both work; original dump hashes unchanged |
| Second launch | No setup dialog; game reaches menu using saved paths |
| Move dump / change release ELF digest | Setup shown again; no stale launch |
| Settings/save/cache/log persistence | Writes only to private user directory |
| Different drives and paths with spaces | Direct PARAM.SFO initialization reports BCUS98158 |
| Unsupported Unicode/long path | Clear path error before starting the engine |
| Read-only install folder | Works with writable Local AppData |
| Duplicate launch / terminate launcher | One owned game; no unrelated processes affected |
| `--open-data` while running, `--check` without config | Explorer opens; check fails without dialogs |
| Game early exit / helper failure | Visible error and readable logs |
| ZIP inspection | No game data, secrets, personal settings or driver cache |
| Packager interrupted / inputs changed | No final ZIP; existing releases untouched |

The release flow is intentionally not wired to automatic GitHub publishing
until these checks pass. Generated game code is not available to a public
source-only CI runner; a maintainer prepares the completed game binary locally.
