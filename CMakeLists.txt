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
    # SSE4.1 for the lifted SPU code only. Its helpers (spu_shufb above all)
    # have a vector form behind __SSE4_1__ and fall back to a byte loop without
    # it; that loop was a sixth of the sound job thread. Any CPU with a D3D12
    # GPU has it.
    if(CMAKE_C_COMPILER_ID MATCHES "Clang")
        set_source_files_properties(${GT5P_SPU_LIFTED} PROPERTIES COMPILE_OPTIONS "-msse4.1")
    endif()
else()
    set(GT5P_SPU_SOURCES "")
endif()

add_executable(gt5p
    src/main.cpp
    src/gt5p_present.cpp
    src/gt5p_settings.cpp
    src/gt5p_profview.cpp
    src/gt5p_settings_ui.cpp
    src/gt5p_shaderbusy.cpp
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

# Scoped to main.cpp, the only file that reads them. On the whole target, any
# change to one of these recompiles every lifted chunk -- ten files of ~35 MB
# each, enough at once to exhaust memory.
set(GT5P_MAIN_DEFS
    "GT5P_TITLE_ID=\"${GT5P_TARGET}\""
    "GT5P_CODE_END=${GT5P_CODE_END}u"
    "GT5P_BOOT_FROM=\"${GT5P_BOOT_FROM}\"")
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

if(WIN32)
    target_link_libraries(gt5p PRIVATE
        ws2_32 xinput ole32 bcrypt
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
