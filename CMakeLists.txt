cmake_minimum_required(VERSION 3.20)
project(gt5p_recompiled
    VERSION 0.1.0
    DESCRIPTION "Gran Turismo 5 Prologue - Static Recompilation for PC"
    LANGUAGES C CXX
)

set(CMAKE_C_STANDARD 17)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# =============================================================================
# ps3recomp runtime
# =============================================================================
set(PS3RECOMP_DIR "${CMAKE_SOURCE_DIR}/../ps3recomp" CACHE PATH "Path to ps3recomp")

if(NOT EXISTS "${PS3RECOMP_DIR}/CMakeLists.txt")
    message(FATAL_ERROR
        "ps3recomp not found at ${PS3RECOMP_DIR}\n"
        "Clone it from https://github.com/sp00nznet/ps3recomp\n"
        "Or set -DPS3RECOMP_DIR=/path/to/ps3recomp")
endif()

# FFmpeg decodes the title's movies (PAMF: H.264 and ATRAC3plus). Its DLLs
# are loaded at run time; scripts/get_ffmpeg.ps1 fetches headers and DLLs into
# third_party/ffmpeg (gitignored). Without them movies play black and silent.
set(GT5P_FFMPEG_DIR "${CMAKE_SOURCE_DIR}/third_party/ffmpeg")
if(EXISTS "${GT5P_FFMPEG_DIR}/include/libavcodec/avcodec.h")
    set(PS3RECOMP_FFMPEG_INCLUDE "${GT5P_FFMPEG_DIR}/include")
endif()

add_subdirectory(${PS3RECOMP_DIR} ps3recomp EXCLUDE_FROM_ALL)

# =============================================================================
# Game build
# =============================================================================
# Addresses and boot settings belong to one executable. They are read from
# config/targets.json, the same file the scripts use (scripts/target.py).
set(GT5P_TARGET "NPUA80075" CACHE STRING "Title id of the build in input/EMAIN.ELF")
file(READ "${CMAKE_SOURCE_DIR}/config/targets.json" GT5P_TARGETS_JSON)
string(JSON GT5P_T ERROR_VARIABLE GT5P_T_ERR GET "${GT5P_TARGETS_JSON}" "${GT5P_TARGET}")
if(GT5P_T_ERR)
    message(FATAL_ERROR "GT5P_TARGET=${GT5P_TARGET} is not in config/targets.json")
endif()
string(JSON GT5P_CODE_END     GET "${GT5P_T}" code_end)
string(JSON GT5P_BOOT_FROM    GET "${GT5P_T}" boot_from)
string(JSON GT5P_HDD_TITLE    GET "${GT5P_T}" hdd_title)
string(JSON GT5P_SPU_REGISTRY GET "${GT5P_T}" spu_registry)
string(JSON GT5P_SYNTH_DONE   GET "${GT5P_T}" spurs_synth_job_done)
# Return address of the title's frame-pacer sleep (Phase 106); absent: none.
string(JSON GT5P_PACER_LR ERROR_VARIABLE GT5P_PACER_LR_ERR GET "${GT5P_T}" frame_pacer_sleep_lr)
if(GT5P_PACER_LR_ERR)
    set(GT5P_PACER_LR "")
endif()
# vtable of the title's mListBox widget: the settings page finds the race
# pause bar by it (Phase 117); absent: none.
string(JSON GT5P_ASPECT_ADDR ERROR_VARIABLE GT5P_ASPECT_ADDR_ERR GET "${GT5P_T}" aspect_16_9_float)
if(GT5P_ASPECT_ADDR_ERR)
    set(GT5P_ASPECT_ADDR "")
endif()
string(JSON GT5P_UI_ASPECT_ADDR ERROR_VARIABLE GT5P_UI_ASPECT_ADDR_ERR GET "${GT5P_T}" ui_aspect_16_9_float)
if(GT5P_UI_ASPECT_ADDR_ERR)
    set(GT5P_UI_ASPECT_ADDR "")
endif()
string(JSON GT5P_LISTBOX_VT ERROR_VARIABLE GT5P_LISTBOX_VT_ERR GET "${GT5P_T}" menu_listbox_vtable)
if(GT5P_LISTBOX_VT_ERR)
    set(GT5P_LISTBOX_VT "")
endif()
message(STATUS "game build: ${GT5P_TARGET} (code end ${GT5P_CODE_END}, boot_from=${GT5P_BOOT_FROM})")

# =============================================================================
# Lifted PPU code
# =============================================================================
set(GENERATED_DIR "${CMAKE_SOURCE_DIR}/generated")

file(GLOB GENERATED_SOURCES CONFIGURE_DEPENDS "${GENERATED_DIR}/ppu_recomp_*.cpp")
if(NOT GENERATED_SOURCES)
    message(FATAL_ERROR
        "No lifted sources in ${GENERATED_DIR}/.\n"
        "Run the pipeline first -- see the Building section of README.md.")
endif()
list(LENGTH GENERATED_SOURCES N_CHUNKS)
message(STATUS "lifted PPU chunks: ${N_CHUNKS}")

# Guest loads and stores inline in the lifted chunks (plan-30fps step 5a).
# ppu_vm_inline.h is force-included ahead of the generated ppu_recomp.h and
# turns each vm_read*/vm_write* call into a range test and a byte-swapped
# access, calling the out-of-line accessor only for the null page, the raw SPU
# registers, the GCM ref register and SPU-reserved lines. VM_INLINE=0 at run
# time sends every access out of line again. Changing this option recompiles
# all the chunks: set CMAKE_BUILD_PARALLEL_LEVEL=4 first.
# On by default since Phase 107: out-of-line accessors were about 65% of the
# race render thread's CPU (14.1 -> 5.8 ms a frame inline). The exe is about
# 176 MB instead of 97. -DGT5P_VM_INLINE=OFF builds the old way.
option(GT5P_VM_INLINE "Inline guest memory access in the lifted PPU code" ON)
if(GT5P_VM_INLINE)
    set(GT5P_VM_INLINE_H "${PS3RECOMP_DIR}/runtime/ppu/ppu_vm_inline.h")
    if(MSVC)
        set_source_files_properties(${GENERATED_SOURCES} PROPERTIES
            COMPILE_OPTIONS "/FI${GT5P_VM_INLINE_H}")
    else()
        set_source_files_properties(${GENERATED_SOURCES} PROPERTIES
            COMPILE_OPTIONS "SHELL:-include ${GT5P_VM_INLINE_H}")
    endif()
    message(STATUS "lifted PPU chunks: guest memory access inline")
endif()

# The runtime library does not bundle the PPU loader/HLE/VFS translation units;
# each title compiles them so it can supply its own function_table and boot
# harness.
set(PS3RECOMP_PPU_SOURCES
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_loader.cpp"   # vm + guest dispatch + traps
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_hle.cpp"      # NID -> handler dispatch
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_sysprx.cpp"   # boot-critical CRT
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_fs.cpp"       # cellFs VFS
)

# Lifted SPU images. All four of this title's SPURS workloads carry the same
# policy module (the WWS job manager), embedded in EMAIN.ELF rather than loaded
# from a data file -- see src/gen/spu_workloads.c.
option(GT5P_ENABLE_SPU "Compile and register the lifted SPU images" ON)
if(GT5P_ENABLE_SPU)
    file(GLOB GT5P_SPU_LIFTED CONFIGURE_DEPENDS
        "${CMAKE_SOURCE_DIR}/generated/spu_lifted/*/spu_recomp.c")
    list(LENGTH GT5P_SPU_LIFTED N_SPU)
    message(STATUS "lifted SPU images: ${N_SPU}")
    set(GT5P_SPU_SOURCES "${CMAKE_SOURCE_DIR}/${GT5P_SPU_REGISTRY}" ${GT5P_SPU_LIFTED})
    # The lifted sources include "spu_context.h" relative to the runtime; scope
    # the include to these TUs so the huge PPU chunks keep their cached command.
    set_source_files_properties(${GT5P_SPU_SOURCES} PROPERTIES
        INCLUDE_DIRECTORIES "${PS3RECOMP_DIR}/runtime/spu")
    # Native replacements hooked into lifted SPU blocks (scripts/spu_native_patch.py).
    set_source_files_properties(src/gt5p_spu_native.c PROPERTIES
        INCLUDE_DIRECTORIES "${PS3RECOMP_DIR}/runtime/spu")
    # SSE4.1 for the lifted SPU code only. Its helpers (spu_shufb above all)
    # have a vector form behind __SSE4_1__ and fall back to a byte loop without
    # it; that loop was a sixth of the sound job thread. Any CPU with a D3D12
    # GPU has it.
    if(CMAKE_C_COMPILER_ID MATCHES "Clang")
        set_source_files_properties(${GT5P_SPU_LIFTED} PROPERTIES COMPILE_OPTIONS "-msse4.1")
    endif()
    # The lifted job code without the local-store debug probes (SPU_LS_LOWREAD,
    # the LS watch, SPU_SMC_WATCH, the WWS policy-module probes): every LS
    # access tested them. 1.09-1.13x on the hottest render-job loop (Phase 59).
    # The runtime and interpreter keep them. GT5P_SPU_PROBES=ON restores them
    # in the lifted code too.
    option(GT5P_SPU_PROBES "Keep the local-store debug probes in lifted SPU code" OFF)
    if(NOT GT5P_SPU_PROBES)
        set_source_files_properties(${GT5P_SPU_LIFTED} PROPERTIES COMPILE_DEFINITIONS "SPU_LS_NO_PROBES")
    endif()
else()
    set(GT5P_SPU_SOURCES "")
endif()

add_executable(gt5p
    src/main.cpp
    src/gt5p_present.cpp
    src/gt5p_audio_native.cpp
    src/gt5p_spin.cpp
    src/gt5p_spu_native.c
    src/gt5p_settings.cpp
    src/gt5p_profview.cpp
    src/gt5p_debug_export.cpp
    src/gt5p_settings_ui.cpp
    src/gt5p_shaderbusy.cpp
    src/gt5p_glyphs.cpp
    src/gt5p_keymap.cpp
    src/gt5p_allocwatch.cpp
    src/gt5p_bbcount.cpp
    src/gt5p_longjmp.cpp
    ${GT5P_SPU_SOURCES}
    src/gen/ppu_hle_nids.cpp    # generated: NID -> ps3recomp lib handler
    ${PS3RECOMP_PPU_SOURCES}
    ${GENERATED_SOURCES}
)

target_include_directories(gt5p PRIVATE
    ${CMAKE_SOURCE_DIR}/src
    ${CMAKE_SOURCE_DIR}/src/compat      # <dirent.h>/<unistd.h> shims for ppu_fs.cpp
    ${CMAKE_SOURCE_DIR}/generated       # ppu_recomp.h
    ${PS3RECOMP_DIR}/include
    ${PS3RECOMP_DIR}/runtime/ppu
    ${PS3RECOMP_DIR}/runtime/memory
    ${PS3RECOMP_DIR}/runtime/syscalls
)

# Report identity only belongs to the export TU; never invalidate lifted code.
execute_process(COMMAND git describe --always --dirty --abbrev=12
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
    OUTPUT_VARIABLE GT5P_REPORT_REVISION OUTPUT_STRIP_TRAILING_WHITESPACE)
configure_file(src/gt5p_build_info.h.in gt5p_build_info.h @ONLY)
set_source_files_properties(src/gt5p_debug_export.cpp PROPERTIES
    INCLUDE_DIRECTORIES "${CMAKE_CURRENT_BINARY_DIR}")

# Scoped to main.cpp, the only file that reads them. On the whole target, any
# change to one of these recompiles every lifted chunk -- ten files of ~35 MB
# each, enough at once to exhaust memory.
set(GT5P_MAIN_DEFS
    "GT5P_TITLE_ID=\"${GT5P_TARGET}\""
    "GT5P_CODE_END=${GT5P_CODE_END}u"
    "GT5P_BOOT_FROM=\"${GT5P_BOOT_FROM}\""
    "GT5P_PACER_LR=\"${GT5P_PACER_LR}\""
    "GT5P_LISTBOX_VT=\"${GT5P_LISTBOX_VT}\""
    "GT5P_ASPECT_ADDR=\"${GT5P_ASPECT_ADDR}\""
    "GT5P_UI_ASPECT_ADDR=\"${GT5P_UI_ASPECT_ADDR}\"")
if(GT5P_HDD_TITLE)
    list(APPEND GT5P_MAIN_DEFS "GT5P_HDD_TITLE=1")
endif()
if(GT5P_SYNTH_DONE)
    list(APPEND GT5P_MAIN_DEFS "GT5P_SPURS_SYNTH_DONE=1")
else()
    list(APPEND GT5P_MAIN_DEFS "GT5P_SPURS_SYNTH_DONE=0")
endif()
set_source_files_properties(src/main.cpp PROPERTIES COMPILE_DEFINITIONS "${GT5P_MAIN_DEFS}")
# toml++ (MIT, external/tomlplusplus, v3.4.0) for gt5p_settings.toml. Scoped to
# the one file that uses it, like the definitions above, so adding it does not
# change the lifted chunks' command lines and rebuild them.
set_source_files_properties(src/gt5p_settings.cpp PROPERTIES
    INCLUDE_DIRECTORIES "${CMAKE_SOURCE_DIR}/external/tomlplusplus")

target_link_libraries(gt5p PRIVATE ps3recomp_runtime)

# Private CPU-specific copies of the profiled audio images. Derived aliases and
# lifted source stay under build/; baseline SSE images remain available.
if(GT5P_ENABLE_SPU AND GT5P_TARGET STREQUAL "BCUS98158" AND WIN32 AND CMAKE_C_COMPILER_ID MATCHES "Clang")
    set(GT5P_AUDIO_NATIVE_AVAILABLE TRUE)
    foreach(image IN ITEMS j307E5DC7 j65DD2F53 j8AAB90A4)
        set(image_dir "${CMAKE_SOURCE_DIR}/generated/spu_lifted/${image}")
        if(NOT EXISTS "${image_dir}/spu_recomp.c")
            set(GT5P_AUDIO_NATIVE_AVAILABLE FALSE)
        endif()
    endforeach()
    if(GT5P_AUDIO_NATIVE_AVAILABLE)
        foreach(image IN ITEMS j307E5DC7 j65DD2F53 j8AAB90A4)
            set(image_dir "${CMAKE_SOURCE_DIR}/generated/spu_lifted/${image}")
            file(READ "${image_dir}/spu_recomp.h" image_header)
            string(REGEX MATCHALL "gt5p_${image}_[A-Za-z0-9_]+" image_symbols "${image_header}")
            list(REMOVE_DUPLICATES image_symbols)
            set(wrapper "#define spu_register_function gt5p_audio_register_function\n")
            foreach(sym IN LISTS image_symbols)
                string(REPLACE "gt5p_j" "gt5p_audio_j" alternate "${sym}")
                string(APPEND wrapper "#define ${sym} ${alternate}\n")
            endforeach()
            string(APPEND wrapper "#include \"${image_dir}/spu_recomp.c\"\n")
            set(native_source "${CMAKE_BINARY_DIR}/audio_native_${image}.c")
            file(CONFIGURE OUTPUT "${native_source}" CONTENT "${wrapper}" @ONLY)
            target_sources(gt5p PRIVATE "${native_source}")
            set_source_files_properties("${native_source}" PROPERTIES
                COMPILE_OPTIONS "-msse4.1;-mfma"
                INCLUDE_DIRECTORIES "${PS3RECOMP_DIR}/runtime/spu")
            if(NOT GT5P_SPU_PROBES)
                set_source_files_properties("${native_source}" PROPERTIES COMPILE_DEFINITIONS "SPU_LS_NO_PROBES")
            endif()
        endforeach()
        set_source_files_properties(src/gt5p_audio_native.cpp PROPERTIES
            COMPILE_DEFINITIONS "GT5P_HAVE_AUDIO_NATIVE=1"
            INCLUDE_DIRECTORIES "${PS3RECOMP_DIR}/runtime/spu")
    endif()
endif()

if(WIN32)
    target_link_libraries(gt5p PRIVATE
        ws2_32 xinput ole32 bcrypt shell32
        d3d12 dxgi dxguid d3dcompiler)
    # SDL2.dll is loaded at run time, if present, to read controllers XInput
    # does not know. scripts/get_sdl2.ps1 fetches it into third_party/.
    if(EXISTS "${CMAKE_SOURCE_DIR}/third_party/SDL2.dll")
        add_custom_command(TARGET gt5p POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "${CMAKE_SOURCE_DIR}/third_party/SDL2.dll" "$<TARGET_FILE_DIR:gt5p>/SDL2.dll")
    endif()
    file(GLOB GT5P_FFMPEG_DLLS "${GT5P_FFMPEG_DIR}/bin/*.dll")
    foreach(dll ${GT5P_FFMPEG_DLLS})
        get_filename_component(dll_name "${dll}" NAME)
        add_custom_command(TARGET gt5p POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different "${dll}" "$<TARGET_FILE_DIR:gt5p>/${dll_name}")
    endforeach()
else()
    target_link_libraries(gt5p PRIVATE pthread m)
endif()

# =============================================================================
# Compiler settings
# =============================================================================
if(MSVC)
    target_compile_options(gt5p PRIVATE
        /W3
        /MP          # parallel compilation -- the lifted chunks are ~35 MB each
        /bigobj
        /utf-8
        # noise from generated code
        /wd4244 /wd4267 /wd4146 /wd4305 /wd4018)
    target_compile_definitions(gt5p PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
    target_compile_options(gt5p PRIVATE
        -Wall
        -Wno-unused-variable -Wno-unused-function
        -Wno-sign-compare -Wno-parentheses -Wno-unused-but-set-variable)
endif()

install(TARGETS gt5p RUNTIME DESTINATION bin)
