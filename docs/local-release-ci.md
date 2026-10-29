# Building a player ZIP on this PC after pushes to main

Port release version: **v0.1**, from `VERSION`. Artifact/ZIP names include that
version and the triggering commit, while the game-data version stays 03.00.

The dedicated local runner is provisioned and validated. The first cold build
took 17m21s; a cached build including checks, packaging and upload took 1m10s.
The Windows runner uses private inputs and a private incremental cache outside
the development worktrees.

## Branch layout

The original `origin/main` is preserved at `65c75d61ade58efb4f6af5f099c3b78b64c0a8e6`
as **`archive/original-main`**, already pushed.
Current GT5P work descends from that commit, so no history rewrite/force push is
needed. Leave `gt5` separate: it is a different game, not a GT5P update branch.

On 2026-10-29, at the user's request, the current GT5P upgrade branch
(`980329a`) was merged into `feature/player-setup` as `134ce60` for promotion
to main. Its code baseline was already included; the merge adds the cleanup
records. The GT5 worktree and GT5P development worktree were left on their
existing branches. No builds/tests were run for this integration. The workflow
still requires the documented runner provisioning and enable variable.

After Claude finishes and commits/pushes its work, merge the GT5P branches into
the integration branch and review any conflicts there. At the time of preparation,
these are `upgrade/ps3recomp-v0.18.0` and `feature/player-setup`:

```powershell
# Use the separate GT5P-player-setup worktree, with no uncommitted changes.
git fetch origin
git merge origin/upgrade/ps3recomp-v0.18.0
# Resolve/review any conflicts, then perform the normal validation when idle.
git push origin feature/player-setup
# Confirm the current main is still an ancestor; stop if this fails.
git merge-base --is-ancestor origin/main HEAD
# Only after the command above exits 0 and integration validation passes:
git push origin HEAD:refs/heads/main
```

These commands are a procedure, not commands executed while Claude is active.
Do not promote this branch while it lacks Claude's final committed changes.
`git push` above is a normal fast-forward push and refuses divergent history.
If main is protected, open a pull request instead of weakening its rules.
The repository's default branch can remain `main` throughout. After migration,
make future GT5P feature branches from main and merge them back into main.
An existing development worktree can stay on its current branch until its owner
is ready to switch; changing a remote ref does not require changing that worktree.

## What runs

`.github/workflows/player-release.yml` triggers on pushes to `main` or a manual
dispatch on main. It is disabled until repository variable
`GT5P_LOCAL_RELEASE_ENABLED` equals `true` and a matching runner is online.

1. A dedicated Windows x64 runner checks out the exact pushed commit.
2. `scripts/release/ci_build.py` copies explicit local private build inputs into
   that checkout, verifies the approved ELF digest and prepares an independent,
   content-addressed pinned runtime/overlay.
3. It regenerates PPU/SPU sources and post-lift hooks, builds BCUS98158 Release
   with two compiler processes, then builds/tests the launcher and packager.
4. The existing strict packager creates a player ZIP with the launcher, engine,
   runtime DLLs, glyph assets and dependency notices. No game files are included.
5. Only the finished `out/ci-player/*.zip` is uploaded as a GitHub Actions
   artifact, retained for 14 days. Download it from the workflow run's Artifacts
   area. This does not automatically create or update a GitHub Release.

This uses a clean checkout with a private incremental build cache outside it.
The initial cold build still compiles all translated code. Later runs restore
unchanged generated code and Ninja outputs, then build changed dependencies.
The cache fingerprints the ELF, captured jobs, runtime pin/patch, lift scripts,
target/seeds/derived-registry inputs, Python/capstone and compiler/toolchain.
Changed lift/toolchain inputs require a fresh cache; ordinary native code edits
use Ninja's dependency tracking. New source files are never overwritten by the
cache. Identical tracked files have their prior timestamps restored only after
content-hash comparison, avoiding recompiles caused solely by checkout mtimes.

Cache data defaults to `C:\GT5P-CI\incremental-cache` (next to runtime-cache),
keyed by the absolute runner workspace and input fingerprint. A successful
native build updates it before packaging. Partial saves have no ready marker
and are not reused. It stays local and contains private derived game code;
never upload it. Set `GT5P_CI_CACHE=0` in the runner environment, or
`"incremental": false` in runner.json, for a cold diagnostic run. Cache locations
can be overridden with `build_cache` in runner.json, outside the checkout.

A single registered runner executes one job at a time;
there is no concurrency cancellation that deliberately discards older pushes.
The patched runtime source is cached outside the checkout. Generated code,
private inputs, build directories, logs and the runtime are never artifact paths.
The actual game is not launched by this workflow.

The PC must be awake and connected. Start the runner only when development
builds/tests are idle, or use a separate machine/account. On this 16 GB PC,
parallelism 2 avoids the memory pressure of large lifted-code compiles.

## One-time local provisioning (when Claude is idle)

Use a runner installation such as `C:\actions-runner-gt5p`, and a separate
private-input/config root such as `C:\GT5P-CI`. Never register either current
development worktree as the runner workspace: checkout cleanup runs inside its
dedicated `_work` checkout. Do not put the private inputs under `_work`.

Install/configure the runner using this repository's **Settings > Actions >
Runners > New self-hosted runner > Windows x64** instructions. Add the custom
label **`gt5p-release`**; keep its standard `self-hosted`, `Windows`, `X64` labels.
Use GitHub's displayed download, checksum and short-lived registration token,
not an old token stored in a script. The account running it needs access to
the compiler, private inputs and cache. Running `run.cmd` manually gives control
over when it consumes resources; a Windows service is optional later.

Provision Git, Python 3.11+, CMake, Ninja, clang-cl and x64 VS C++/Windows SDK
tools. Create a separate Python venv outside `_work` and install the pinned
runtime's tools requirements into it (capstone, pycryptodome, construct,
tabulate, tqdm). The workflow does not install Python packages or acquire keys.

Prepare these private copies from the known working build:

```text
C:\GT5P-CI\private-inputs\
  CI-INPUTS.txt                         marker: this is dedicated CI input data
  input\EMAIN.ELF                      supported disc build, decrypted locally
  analysis\spu\dump\spujob_*.bin        captured job images used by this port
  third_party\SDL2.dll
  third_party\ffmpeg\include\...        matching FFmpeg headers
  third_party\ffmpeg\bin\avcodec-61.dll
  third_party\ffmpeg\bin\avutil-59.dll
  third_party\ffmpeg\bin\swresample-5.dll
```

Do not copy the game volumes, ROM directory, saves, shadercache or entire
development checkout. No game files are needed on GitHub. The ELF and SPU
images stay private on the PC and transiently inside the local runner checkout.
Never upload that checkout or its build logs as a catch-all artifact.

Prepare `C:\GT5P-CI\notices` with the exact files described in
[player-setup.md](player-setup.md#maintainer-build-and-packaging-when-claude-is-idle).
The matching FFmpeg binary provenance/source/build instructions still need
maintainer review; do not substitute invented or generic notices. Use the x64
MSVC redistributable directory matching the toolchain, not DLLs from System32.

Create local `C:\GT5P-CI\runner.json` (never commit this machine-specific file):

```json
{
  "private_inputs": "C:/GT5P-CI/private-inputs",
  "runtime_cache": "C:/GT5P-CI/runtime-cache",
  "vc_runtime_dir": "C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.CRT",
  "notices_dir": "C:/GT5P-CI/notices",
  "elf_sha256": "REPLACE_WITH_SHA256_OF_YOUR_PRIVATE_EMAIN_ELF",
  "parallel_jobs": 2,
  "clang_cl": "C:/Program Files/LLVM/bin/clang-cl.exe"
}
```

Get the input digest locally using
`Get-FileHash C:\GT5P-CI\private-inputs\input\EMAIN.ELF -Algorithm SHA256`;
write it in lowercase in the config. This guards against accidentally building
one ELF and advertising the digest of another.

Add these environment variables to the runner installation's `.env` file
(or the environment used to launch `run.cmd`), then restart the runner:

```text
GT5P_CI_PYTHON=C:\GT5P-CI\venv\Scripts\python.exe
GT5P_CI_CONFIG=C:\GT5P-CI\runner.json
GT5P_CI_VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat
```

Do not give the runner the development `GT5P_USER_DIR`, diagnostic SPU/PPU
overrides or a development runtime path. The build driver sets its own runtime
and clears developer lift overrides. Private/config directories must be outside
the checkout and cannot be ancestors of it.

Once integration is ready and the runner is provisioned, enable repository
variable `GT5P_LOCAL_RELEASE_ENABLED=true` under **Settings > Secrets and
variables > Actions > Variables**. Run the workflow manually on main once;
inspect the ZIP and test a fresh extraction on the Ally before treating it as
release-ready. Later main pushes use the same process automatically.

## Trust boundary

This repository is public. GitHub recommends private repositories for
self-hosted runners because untrusted workflow code can execute on the host.
This workflow deliberately has no PR trigger, checks the origin/main ref,
pins its actions, keeps the Windows build token read-only, and never persists checkout credentials.
A separate GitHub-hosted publishing job has release-write permission only for version tags.
Only trusted maintainers should be able to push main or change workflows.
These measures do not isolate a malicious trusted commit from the PC: use a
dedicated Windows account/host if it contains other sensitive work. The existing
`No game files` PR workflow stays on GitHub-hosted Ubuntu runners.

References: [adding a self-hosted runner](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners),
[workflow artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data),
[upload-artifact](https://github.com/actions/upload-artifact).

## Automatic GitHub Releases (version tags only)

Main pushes and manual main builds produce Actions artifacts. To publish a
fixed release, set `VERSION` to the desired number, commit and push main, then
push the matching annotated tag. For example, for the first release:

```powershell
git checkout main
git pull --ff-only origin main
# VERSION must contain 0.1, and all intended changes must already be committed.
git tag -a v0.1 -m "GT5P v0.1"
git push origin v0.1
```

The tag starts the same cached local build and validation. A separate job on
GitHub's Ubuntu runner downloads only the finished ZIP, verifies its SHA-256,
and publishes it with a checksum and generated notes on the Releases page.
The local runner must be online. Tags must match `VERSION` exactly and their
commits must belong to main's history. No game inputs or build cache are uploaded.

For the next release, change `VERSION` to `0.2`, commit/push it with the changes,
and push `v0.2`. Published releases are not overwritten; use a new version for
changes. An interrupted publishing job can leave a draft; rerun that job to
finish its upload and publication. Ordinary main builds never publish releases.
