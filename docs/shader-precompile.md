# Offline game shader preparation

`scripts/precompile_shaders.py` reads embedded `SHDS` fragment programs from
the local executable and unpacked game assets, then runs the production
translator/compiler before guest entry. It writes ordinary DXBC entries to
the same shadercache used during play. It is separate from F1's **Preload
known shaders**, which prepares previously recorded native pipelines.

Keep the shader cache enabled. Close the game before compiling. All extracted
programs, bytecode, source indexes and logs remain local and must not be
committed or distributed with the port.

## Full asset pass

Use [GTToolsSharp](https://github.com/Nenkai/GTToolsSharp/releases) to unpack
your own `GT.VOL`. The tool is an external dependency; this repository does
not include its executable, keys or source. Either provide its executable:

```powershell
.venv\Scripts\python scripts\precompile_shaders.py --unpacker C:\Tools\GTToolsSharp.exe
```

Or point at an existing unpacked directory:

```powershell
.venv\Scripts\python scripts\precompile_shaders.py --assets C:\Games\GT5P-extracted
```

The wrapper's unpacker invocation writes intermediate assets and third-party
tool output into ignored `scratch/`. It does not alter the game dump. The
executable is also scanned, regardless of the assets option.

For better coverage, first play representative menus and races on this build.
The renderer learns shader-affecting state profiles in
`shadercache/fp-profiles-v2/`. The offline pass applies learned profiles to
file programs with matching texture-unit usage. This can prepare unvisited
content using states observed elsewhere. With no learned profiles, only
base 16/32-bit export variants are prepared; a base-only pass showed almost
no reduction in the measured dealership route.

Up to 64 learned profiles are used by default. For more coverage:

```powershell
.venv\Scripts\python scripts\precompile_shaders.py --compile-only --profile-limit 256
```

`--compile-only` reuses `shadercache/library-v1/all/`; extraction is unnecessary
on every run. It also resumes safely after interruption: completed DXBC
entries remain usable. Existing shadercache files are never removed.

For an even broader, substantially slower cross-product of states and programs:

```powershell
.venv\Scripts\python scripts\precompile_shaders.py --compile-only --profile-limit 256 --all-profile-combinations
```

Normal shader compiler worker configuration (`RSX_SHADER_WORKERS`) also applies.
The job table now defaults to 65,536 slots: the former 16,384 slots forced
large passes into serial compilation once full. `RSX_SHADER_JOB_SLOTS=16384`
restores that limit; values are rounded down to a power of two between
1,024 and 131,072. The table occupies a bounded amount of memory.
The source queue is bounded to about 64 jobs; parallel compilation can still
consume CPU and memory. Progress is printed in the terminal and window title.
`shadercache/precompile.log` contains the summary and bounded failure details.
The program exits after preparation; it does not start the game.

## Smaller passes and checks

```powershell
# Executable only, without unpacking assets:
.venv\Scripts\python scripts\precompile_shaders.py --scope executable

# Extract/index without compiling:
.venv\Scripts\python scripts\precompile_shaders.py --assets C:\Games\GT5P-extracted --catalog-only

# Separate cache for experiments, without touching the player's cache:
.venv\Scripts\python scripts\precompile_shaders.py --scope executable --cache scratch\shader-test

# Maximum programs in one pass (up to 16384):
.venv\Scripts\python scripts\precompile_shaders.py --compile-only --limit 128
```

Extraction records bounds-checked SHDS table entries and deduplicates identical
payloads. The local index lists source filenames and offsets for diagnosis.
The native reader separately validates file size, alignment and termination.
Failed programs/variants are skipped and reported as partial coverage.

The catalog directories for `all` and `executable` are separate. An optional
`--catalog PATH` overrides the directory. The supported layout was checked
against this disc build; other builds are unverified. The SHDS layout was
researched using [PDTools' public readers](https://github.com/Nenkai/PDTools/tree/master/PDTools.Files/Models/Shaders)
and checked against local runtime shader bytes.

Tests:

```powershell
.venv\Scripts\python scripts\test\shader_library.py
.venv\Scripts\python scripts\test\shader_library_runtime.py
.venv\Scripts\python scripts\test\shader_job_table.py
```

The first uses synthetic containers. The second requires the local game/build
and uses an isolated scratch cache to verify real compilation, repeat-cache
reuse, bad inputs and profile filtering. The third exercises the production
job-table helpers at their default, legacy and clamped capacities.

## Remaining compilation

This is not an exhaustive shader/pipeline database. Vertex programs are not
prepared by this extractor. Runtime-generated or modified programs, unsupported
records, unobserved states, different renderer settings, and native driver
pipelines can still compile during play. Some file payloads contain register
references rejected by the current translator/compiler; the authored fixups
and unsupported cases need further investigation. No claim is made that
shader preparation fixes the separately observed command-production freezes.

Environment controls for direct native use: `RSX_SHADER_LIBRARY=<catalog>`
with `RSX_SHADER_WARMUP=1`, `RSX_SHADER_ASYNC=1`, and an enabled shader cache;
`GT5P_SHADER_PRECOMPILE_ONLY=1` exits before guest entry. Library preparation
does not run during normal play unless explicitly requested.
`RSX_SHADER_LIBRARY_LIMIT`, `RSX_SHADER_LIBRARY_PROFILE_LIMIT`,
`RSX_SHADER_LIBRARY_PROFILES=base` and `RSX_SHADER_LIBRARY_BROAD=1` correspond
to the CLI controls. `RSX_SHADER_PROFILES=0` disables profile learning and
`RSX_SHADER_ERRORS=0` silences new bounded async compiler diagnostics.
`RSX_FP_CATALOG=<existing parent/dir>` is an optional raw-program diagnostic;
it is not needed for normal preparation.
