# Experimental Vulkan support for GT5P

Assessment: 2026-10-19, against GT5P `2732024` and the current local runtime.
This is a proposed implementation plan. No Vulkan option or backend is enabled
by this documentation change.

## Feasibility and existing code

Feasible, with a substantial renderer integration and parity effort. The runtime
already contains `libs/video/rsx_vulkan_backend.c` (about 3,200 lines), the
shared `rsx_draw_engine` / register-file dispatcher, and an HLSL-to-SPIR-V
translator (`rsx_shader_spirv.cpp`). The current runtime README reports passing
synthetic host scenes, including render-to-texture, MRT and depth-texture cases;
these tests were not rerun for this assessment. It explicitly does not claim a
recompiled title running on Vulkan. Some older CMake/header comments describe
only a clear/present prototype and understate the implementation.

The existing build is deliberately Linux-only: CMake rejects WIN32, the C
implementation is excluded under `_WIN32`, and it uses `dlopen`/`dlsym`, SDL2
window creation and SDL Vulkan presentation. GT5P's `src/gt5p_present.cpp`
selects D3D12 or the experimental D3D12 live engine directly. Its settings UI
calls the D3D12 vsync setter, and profiler/export snapshots and shader counters
also reference D3D12. These are integration points, not merely linker changes.

The Vulkan implementation submits and waits synchronously for each operation.
Its engine path has textures, mip uploads, samplers, blending and MRT, but the
actual code rejects cube textures, rejects non-RGBA8 colour pipelines, skips
zero-colour-target draws and hard-codes single-sample pipelines. Stencil state
is translated but its depth formats have no stencil aspect. These are important
GT5P features: text construction, car reflections, shadows and post-processing
would not have parity just by turning the backend on.

The normal GT5P backend also contains title-tested logic for depth retention,
MSAA depth copies, sRGB, texture-coordinate conversion, fog inputs, signed
texture expansion, dynamic textures, tiny-target guest writeback and frame
submission. Audit each against the shared engine rather than assuming that
shared shader decompilers carry every fix across. The shared engine already
keys surfaces/textures by location and offset; retain that distinction so the
Phase 87 missing-map bug does not recur.

## Proposed implementation order

| Milestone | Work | Acceptance gate |
| --- | --- | --- |
| 1. Windows bring-up | Optional build dependencies; Windows Vulkan loader; shared/native game window and Vulkan surface/swapchain; backend init/pump/present/shutdown selection | Synthetic clear and textured draw work on Windows; clean window close; an ordinary D3D12 launch still works |
| 2. Guest shaders and UI | Compile generated HLSL to SPIR-V, verify resource bindings/constant layout and coordinate conventions; integrate GT5P FIFO/display handling; stencil-capable depth and text path | Opening screens and main-menu text render correctly at 720p and 1080p, with validation output retained |
| 3. Scene correctness | Cube textures and render-target cube faces; FP16/other required targets; depth-only passes and shadow comparisons; MSAA/resolves/depth sampling; audit GT5P-specific semantics above | Menu and dealership cars/reflections, pit crew, loading text and race/HUD match selected D3D12 references; track map stays visible |
| 4. Practical frame submission | Batch commands, per-frame upload/descriptor storage, explicit synchronization and safe resource retirement; remove unconditional normal-frame CPU readback; separate persistent shader/pipeline caches | Warm race runs without per-draw fence waits, validation errors or resource reuse corruption; cold-cache and window/device failure paths exercised |
| 5. User-facing experiment | F1 renderer selector marked Experimental with restart requirement; renderer-neutral vsync/shader busy/profiler/debug exports; diagnostic backend override | D3D12 remains default; Vulkan failures are clear; reports identify the active backend, GPU, shader compiler and cache state |

Proposed runtime override: `GT5P_RENDERER=d3d12|vulkan`, with D3D12 the default.
This name is a proposal, not a working setting. Keep backend choice fixed for
the process lifetime. Do not attempt to hot-switch renderer ownership of an
active game. Until the scene gates pass, describe Vulkan as a developer
experiment, not a playable renderer. If initialization fails, report the error
and permit an explicit D3D12 relaunch; do not silently mix renderers mid-run.

Reuse the existing Vulkan backend and shared engine where practical, extending
them with measured missing semantics. Avoid copying the entire 12,000-line
D3D12 backend into a second implementation. If the engine audit exposes a
structural incompatibility, isolate the needed GT5P frame/state logic behind a
shared interface before duplicating it. Preserve a D3D12 comparison run for
each meaningful change. Runtime modifications continue to be backed up in the
tracked cumulative patch as required by AGENTS.md.

## Dependencies and shader compiler decision

A Windows development setup needs Vulkan headers, validation tools/layers and
a shader compiler build/package. This machine has `System32/vulkan-1.dll`;
that alone is not an SDK or a verified Vulkan device test. No SDK was found at
`C:/VulkanSDK` or through `VULKAN_SDK`, and no `dxc`/`glslangValidator` command
was found on PATH. No packages were installed for this assessment. Players
should use the driver loader plus packaged runtime/compiler dependencies;
they should not need to install a development SDK.

The existing translator uses glslang's HLSL frontend. Its upstream README now
states that this frontend is deprecated as of April 2026. For a maintained
Windows path, evaluate DXC's SPIR-V output against the generated HLSL corpus;
do not assume drop-in compatibility. A pinned, tested glslang version is an
option for an initial prototype if it reduces integration risk. Either route
needs validated descriptor bindings, stage linkage, constant packing and
separate shader cache identity by backend/compiler/options. Existing DXBC and
native D3D12 pipeline cache files are not Vulkan cache inputs. Do not move or
delete `shadercache/`; use a separate Vulkan subdirectory or configured cache.

Primary references checked for this assessment:

- [Khronos Win32 surface documentation](https://docs.vulkan.org/refpages/latest/refpages/source/vkCreateWin32SurfaceKHR.html): Vulkan can present through a Win32 HWND; window-message ownership must be respected.
- [glslang upstream README](https://github.com/KhronosGroup/glslang): HLSL frontend deprecation and migration warning.
- [DXC SPIR-V documentation](https://github.com/microsoft/DirectXShaderCompiler/blob/main/docs/SPIR-V.rst): HLSL-to-SPIR-V compiler support and binding/layout options.

## Validation and expected benefit

Start with the runtime's synthetic renderer harness, then GT5P opening screens,
menu, Acura/Ferrari dealerships, pit, loading list, High Speed Ring and Daytona.
Use window-only captures and no tracked game-derived data. Exercise menu/pit/
dealer round trips, a long grid idle, ordinary driving, pause/replay controls,
tunnel views, cold/warm caches and 720p/1080p. Extend the existing opt-in export
with Vulkan state and validation errors; retain its settings gate. Report CPU,
GPU and actual frame-delivery timings separately with `PS3_VERBOSE=0`.

Vulkan could provide another backend/platform path and potentially different
submission/driver costs. It does not establish a fix for the current SPU/FIFO
stalls, missing replay controls, dark tunnel or 60-fps target. Those issues need
their own evidence. The current per-operation synchronous Vulkan prototype is
not a plausible performance upgrade before milestone 4.

This is a multi-session project. A Windows clear/triangle prototype is a much
smaller deliverable than a playable GT5P race. Give a calendar estimate only
after Windows bring-up and a generated-shader compatibility test expose the
actual remaining work. The next concrete implementation task would be
milestone 1, with a separate build so it cannot replace the working executable.
