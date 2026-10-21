/* Bounded recent logs and a shareable, manually requested diagnostic report.
 * No collection before the settings option is enabled. Standard output still
 * reaches its original console/file/pipe. No guest memory dump or shader data.
 */
#include "gt5p_debug_export.h"
#include "gt5p_settings.h"
#include "gt5p_build_info.h"
#include <shellapi.h>
#include <psapi.h>
#include <io.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
namespace fs = std::filesystem;
constexpr size_t kLogBytes = 2 * 1024 * 1024;
std::atomic<bool> s_enabled{false};
std::mutex s_control, s_status_lock;
std::atomic<bool> s_started{false};
bool s_capture_ok;
int s_status = 1;
std::string s_message = "Ready";
fs::path s_folder;
std::atomic<ULONGLONG> s_since{0};
std::atomic<LONG> s_busy{0};
std::atomic<unsigned> s_serial{0};
std::mutex s_hitch_lock;
struct Hitch { unsigned frame; double age; ULONGLONG at; std::string state; };
std::vector<Hitch> s_hitches;
std::atomic<bool> s_hitch_busy{false};
std::atomic<unsigned> s_generation{0};
std::atomic<unsigned> s_hitch_frame{0};

struct Log {
    std::mutex lock;
    std::vector<char> ring;
    size_t end = 0, used = 0;
    unsigned long long bytes = 0;
    int read_fd = -1, forward_fd = -1;
    HANDLE thread = nullptr;
    void append(const char* p, size_t n) {
        std::lock_guard<std::mutex> guard(lock);
        if (!s_enabled.load()) return;
        bytes += n;
        for (size_t done = 0; done < n;) {
            size_t take = (std::min)(n - done, kLogBytes - end);
            memcpy(ring.data() + end, p + done, take);
            end = (end + take) % kLogBytes; done += take;
        }
        used = (std::min)(kLogBytes, used + n);
    }
    void clear() {
        std::lock_guard<std::mutex> guard(lock);
        end = used = 0; bytes = 0;
    }
    std::string snapshot() {
        std::lock_guard<std::mutex> guard(lock);
        std::string out = "Recent log; total captured bytes=" + std::to_string(bytes) +
            ", retained=" + std::to_string(used) + "\n";
        size_t start = (end + kLogBytes - used) % kLogBytes;
        size_t first = (std::min)(used, kLogBytes - start);
        if (used) { out.append(ring.data() + start, first); out.append(ring.data(), used - first); }
        return out;
    }
} s_logs[2];

DWORD WINAPI log_reader(void* ptr) {
    Log& log = *static_cast<Log*>(ptr);
    char b[16384];
    for (;;) {
        int n = _read(log.read_fd, b, sizeof b);
        if (n <= 0) break;
        log.append(b, (size_t)n);
        for (int at = 0; log.forward_fd >= 0 && at < n;) {
            int wrote = _write(log.forward_fd, b + at, n - at);
            if (wrote <= 0) { _close(log.forward_fd); log.forward_fd = -1; break; }
            at += wrote;
        }
    }
    return 0;
}

bool start_log(Log& log, FILE* stream) {
    int fds[2];
    if (_pipe(fds, 65536, _O_BINARY | _O_NOINHERIT)) return false;
    log.ring.resize(kLogBytes);
    log.read_fd = fds[0];
    log.forward_fd = _dup(_fileno(stream));
    /* Start the consumer before publishing the pipe to writers. */
    HANDLE h = CreateThread(nullptr, 0, log_reader, &log, 0, nullptr);
    if (!h) { _close(fds[0]); _close(fds[1]); if (log.forward_fd >= 0) _close(log.forward_fd); return false; }
    log.thread = h;
    fflush(stream);
    bool ok = _dup2(fds[1], _fileno(stream)) == 0;
    _close(fds[1]);
    return ok;
}

void status(int code, const std::string& text) {
    std::lock_guard<std::mutex> guard(s_status_lock);
    s_status = code; s_message = text;
}

struct Entry { std::string name, data; };
/* Plain ZIP entries, no archiver process or dependency needed. Sizes are
 * bounded by the log rings and the optional game-window image. */
uint32_t crc32(const std::string& data) {
    uint32_t crc = ~0u;
    for (unsigned char c : data) {
        crc ^= c;
        for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}
bool zip(FILE* f, const std::vector<Entry>& entries) {
    auto u16 = [f](uint16_t v) { unsigned char b[] = {(unsigned char)v, (unsigned char)(v >> 8)}; fwrite(b, 1, 2, f); };
    auto u32 = [f](uint32_t v) { unsigned char b[] = {(unsigned char)v, (unsigned char)(v >> 8), (unsigned char)(v >> 16), (unsigned char)(v >> 24)}; fwrite(b, 1, 4, f); };
    struct Index { uint32_t crc, offset; };
    std::vector<Index> index;
    SYSTEMTIME st; GetLocalTime(&st);
    uint16_t time = (st.wHour << 11) | (st.wMinute << 5) | (st.wSecond / 2);
    uint16_t date = ((st.wYear - 1980) << 9) | (st.wMonth << 5) | st.wDay;
    for (const auto& e : entries) {
        Index i{crc32(e.data), (uint32_t)ftell(f)}; index.push_back(i);
        u32(0x04034B50); u16(20); u16(0); u16(0); u16(time); u16(date); u32(i.crc);
        u32((uint32_t)e.data.size()); u32((uint32_t)e.data.size()); u16((uint16_t)e.name.size()); u16(0);
        fwrite(e.name.data(), 1, e.name.size(), f); fwrite(e.data.data(), 1, e.data.size(), f);
    }
    uint32_t start = (uint32_t)ftell(f);
    for (size_t n = 0; n < entries.size(); n++) {
        const auto& e = entries[n]; const auto& i = index[n];
        u32(0x02014B50); u16(20); u16(20); u16(0); u16(0); u16(time); u16(date); u32(i.crc);
        u32((uint32_t)e.data.size()); u32((uint32_t)e.data.size()); u16((uint16_t)e.name.size());
        u16(0); u16(0); u16(0); u16(0); u32(0); u32(i.offset); fwrite(e.name.data(), 1, e.name.size(), f);
    }
    uint32_t end = (uint32_t)ftell(f);
    u32(0x06054B50); u16(0); u16(0); u16((uint16_t)entries.size()); u16((uint16_t)entries.size());
    u32(end - start); u32(start); u16(0);
    return !ferror(f) && fflush(f) == 0;
}

std::string from_file(FILE* f) {
    fflush(f); rewind(f);
    std::string result; char b[8192]; size_t n;
    while ((n = fread(b, 1, sizeof b, f))) result.append(b, n);
    return result;
}

/* Kept in its own function: SEH has no C++ objects to unwind. One damaged
 * guest pointer should not prevent the rest of a report being saved. */
void guarded_snapshot(FILE* out) {
    __try { gt5p_debug_snapshot(out); }
    __except(EXCEPTION_EXECUTE_HANDLER) { fprintf(out, "\nSnapshot interrupted: exception 0x%08lX\n", GetExceptionCode()); }
}
void guarded_profiler(FILE* out) {
    __try { gt5p_pv_export(out); }
    __except(EXCEPTION_EXECUTE_HANDLER) { fprintf(out, "\nProfiler snapshot unavailable\n"); }
}

struct HitchRequest { unsigned frame, generation; double age; ULONGLONG at; };
DWORD WINAPI hitch_worker(void* ptr) {
    HitchRequest* request = static_cast<HitchRequest*>(ptr);
    try {
        FILE* f = tmpfile();
        if (f) {
            guarded_snapshot(f);
            guarded_profiler(f);
            std::string state = from_file(f); fclose(f);
            std::lock_guard<std::mutex> lock(s_hitch_lock);
            if (s_enabled.load() && request->generation == s_generation.load()) {
                if (s_hitches.size() == 8) s_hitches.erase(s_hitches.begin());
                s_hitches.push_back({request->frame, request->age, request->at, std::move(state)});
            }
        }
    } catch (...) { /* A diagnostic failure must not affect the game. */ }
    delete request; s_hitch_busy = false; return 0;
}

std::string hitch_history() {
    std::lock_guard<std::mutex> lock(s_hitch_lock);
    std::string result = "Automatic hitch snapshots: last 8 gaps over 250 ms, sampled while Debug export is On.\n"
        "These are live samples, not proof of a cause; GT5P_HITCH_CAPTURE=0 disables collection.\n";
    for (const auto& h : s_hitches) {
        result += "\n=== frame " + std::to_string(h.frame) + " age_ms=" + std::to_string(h.age) +
            " since_enable_ms=" + std::to_string(h.at) + " ===\n" + h.state;
    }
    if (s_hitches.empty()) result += "No hitch snapshot retained in this capture interval.\n";
    return result;
}

std::string report(HWND game) {
    FILE* f = tmpfile();
    if (!f) throw std::runtime_error("Could not create report scratch file");
    SYSTEMTIME st; GetLocalTime(&st);
    wchar_t exe[32768] = L""; GetModuleFileNameW(nullptr, exe, 32768);
    WIN32_FILE_ATTRIBUTE_DATA attr{}; GetFileAttributesExW(exe, GetFileExInfoStandard, &attr);
    SYSTEM_INFO si; GetNativeSystemInfo(&si);
    MEMORYSTATUSEX mem{}; mem.dwLength = sizeof mem; GlobalMemoryStatusEx(&mem);
    fprintf(f, "GT5P debug report v2\nLocal time: %04u-%02u-%02u %02u:%02u:%02u\n"
        "Source: %s; target: %s; compiled: %s %s\nProcess id: %lu\n"
        "Log capture enabled for: %llu ms\nGame window handle: %p\n"
        "Executable bytes: %llu; last-write FILETIME: %08lX%08lX\n"
        "Logical CPUs: %lu; RAM: %llu MB total, %llu MB available\n"
        "Snapshots are sampled live; they are not an atomic save state.\n\n",
        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
        GT5P_REPORT_REVISION, GT5P_REPORT_TARGET, __DATE__, __TIME__, GetCurrentProcessId(),
        GetTickCount64() - s_since.load(), game,
        ((unsigned long long)attr.nFileSizeHigh << 32) | attr.nFileSizeLow,
        attr.ftLastWriteTime.dwHighDateTime, attr.ftLastWriteTime.dwLowDateTime,
        si.dwNumberOfProcessors, mem.ullTotalPhys >> 20, mem.ullAvailPhys >> 20);
    /* Whether this process is short of memory: a working set well under the
     * private size, with little RAM available, means pages were trimmed and
     * any thread touching them waits on the disk. */
    PROCESS_MEMORY_COUNTERS_EX pmc{}; pmc.cb = sizeof pmc;
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS*)&pmc, sizeof pmc))
        /* Private includes the page-file backing the driver reserves for
         * every GPU allocation (measured 1:1 on NVIDIA, never resident), so
         * the working set is the RAM actually in use (Phase 104). */
        fprintf(f, "Process memory: working set %llu MB (RAM in use; peak %llu MB), private %llu MB "
            "(includes GPU allocations' backing), page faults %lu; system commit %llu of %llu MB\n\n",
            (unsigned long long)(pmc.WorkingSetSize >> 20), (unsigned long long)(pmc.PeakWorkingSetSize >> 20),
            (unsigned long long)(pmc.PrivateUsage >> 20), pmc.PageFaultCount,
            (mem.ullTotalPageFile - mem.ullAvailPageFile) >> 20, mem.ullTotalPageFile >> 20);
    const auto& s = gt5p_settings();
    fprintf(f, "Loaded settings: resolution=%d msaa=%d vsync=%d shader_cache=%d async=%d "
        "sdl=%d keyboard=%d vblank=%d lane_cores=%d warmup=%d\nSettings file: %s\n",
        s.resolution, s.msaa, s.vsync, s.shader_cache, s.shader_precompile,
        s.sdl_controllers, s.keyboard, s.vblank_hz100, s.lane_cores, s.shader_warmup, gt5p_settings_path().c_str());
    /* Explicit allowlist: never dump the process environment, keys or game files. */
    static const char* names[] = {"GT5P_RESOLUTION", "RSX_MSAA", "RSX_SSAA", "RSX_PRESENT_SYNC",
        "RSX_SHADER_CACHE", "RSX_SHADER_ASYNC", "RSX_SHADER_WARMUP", "RSX_SHADER_WARMUP_BACKGROUND", "RSX_PSO_RECIPES", "RSX_PSO_ASYNC", "RSX_RACE_PREWARM", "RSX_RACE_PREWARM_WAIT_MS",
        "RSX_SHADER_LIBRARY", "RSX_SHADER_LIBRARY_LIMIT", "RSX_SHADER_LIBRARY_PROFILES", "RSX_SHADER_PROFILES",
        "RSX_SHADER_LIBRARY_PROFILE_LIMIT", "RSX_SHADER_LIBRARY_BROAD", "RSX_SHADER_ERRORS", "RSX_SHADER_JOB_SLOTS",
        "RSX_TEX_SLOTS", "RSX_DEPTH_KEEP", "RSX_TEX3D", "RSX_TEX_DIMDBG", "RSX_PSO_HITCH_MS", "RSX_DEPTH_CLEAR_REUSE", "RSX_CLEAR_TRACE", "RSX_TEX_EXPAND",
        "RSX_RT_LOCATION", "RSX_BC_MIP_LIMIT", "RSX_TEX_MIP_VIEWS", "RSX_UNNORM_HI", "RSX_MASK_STATE_RESET", "RSX_FP_SOURCE_RANGE",
        "RSX_VRAM_FRAME", "RSX_GPU_UPLOAD", "SPURS_SINGLE_ASYNC", "GT5P_SPIN_YIELD", "GT5P_SPIN_SLEEP_US",
        "GT5P_VBLANK_THREAD", "RSX_VPVB_MB", "RSX_SHADER_PACK", "RSX_SHADER_PACK_MB", "RSX_PSO_RACE_EVICT",
        "RSX_DRAW_CAP", "GT5P_FRAME_LOG", "GCM_WALK_FAST", "GT5P_SAMPLE_DLL", "GCM_NOP_PARK", "GCM_NOPRUN_DBG", "GCM_WALK_STATS",
        "GT5P_PACER_PAD", "PS3_USLEEP_SKIP_LR", "PS3_USLEEP_LONG", "GT5P_SAMPLE_WID", "VM_INLINE", "RSX_DRAWPROF", "RSX_HOT_METHODS", "RSX_IMM_MASK", "RSX_FPK_FAST",
        "RSX_TEX_UPLOAD_KEEP", "RSX_PSO_RESIDENT_MAX", "RSX_PSO_RETAIN_DEMAND", "RSX_PSO_RECIPE_KEEP_DAYS", "RSX_SHADER_WARMUP_SCAN",
        "GT5P_VBLANK_HZ", "GT5P_PRESENT_SLEEP", "GT5P_STALL_DUMP", "GT5P_PROFVIEW",
        "GT5P_DEBUG_EXPORT", "SPURS_LANE_PIN", "SPURS_LANE_PRUNE", "SPURS_READY_GATE",
        "GT5P_HITCH_CAPTURE", "GT5P_MAINSTACK", "GT5P_SAMPLE", "RSX_PRESENT_THREAD", "RSX_WINDOW_THREAD",
        "SPURS_READY_COH", "SPURS_JL_SPU3", "SPURS_PM_ARG64", "PS3_PPU_CORES", "PS3_PPU_PRIO_SCHED",
        "PS3_VERBOSE", "PS3_COND_DEFER_GCM", "PS3_COND_TRACE_ID", "PS3_SC_CONTEXT",
        "GT5P_STALL_MS", "GT5P_STALL_STACKS",
        "D3D12_DBG", "D3D12_IQ", "PAD_NO_SDL", "PAD_NO_KEYBOARD",
        "PAD_HOTPLUG", "PAD_HOLD_MERGE", "SPU_FTZ", "SPU_CHAIN_BACK", "SPU_IRQSTAT", "SPU_EXP_AB", "GT5P_SPU_NATIVE", "GT5P_SPU_NATIVE_STATS", "SPU_IBHIST", "RSX_FP_SATLOG", "RSX_FP_SAT_OPS", "RSX_FP_SAT_PROG", "RSX_FP_SAT_VIS", "RSX_PSO_KEY_RS", "AUDIO_HOTPLUG", "AUDIO_HOTPLUG_POLL", "GT5P_AUDIO_NATIVE", "AUDIO_RATE", "AUDIO_GAPDBG", "AUDIO_LEADDBG",
        "SPURS_JC_STATS", "SPURS_JC_SAMPLE", "SPURS_JC_NORMAL_PRIO", "SPURS_JG_GAPDBG", "SCREEN_AS_TEX"};
    for (const char* name : names) if (const char* value = getenv(name)) fprintf(f, "%s=%s\n", name, value);
    fprintf(f, "\nCURRENT STATE\n"); guarded_snapshot(f);
    fprintf(f, "\nFRAME AND CPU HISTORY\n"); guarded_profiler(f);
    std::string result = from_file(f); fclose(f); return result;
}

/* PrintWindow is allowed to hang on a blocked game window. Give it a separate
 * thread, a two-second budget, and at most one outstanding capture. */
struct Shot { HWND game; std::atomic<int> refs{2}; std::string bmp; };
std::atomic<bool> s_shot_busy{false};
void release(Shot* shot) { if (--shot->refs == 0) delete shot; }
DWORD WINAPI take_shot(void* p) {
    Shot* shot = static_cast<Shot*>(p);
    RECT r{}; GetClientRect(shot->game, &r);
    int w = r.right, h = r.bottom;
    if (w > 0 && h > 0 && w <= 4096 && h <= 4096 && (uint64_t)w * h <= 8 * 1024 * 1024) {
        HDC dc = GetDC(shot->game), mem = CreateCompatibleDC(dc);
        BITMAPINFO bi{}; bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h;
        bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
        void* pixels = nullptr;
        HBITMAP bm = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &pixels, nullptr, 0);
        if (bm && mem) {
            HGDIOBJ old = SelectObject(mem, bm);
            if (PrintWindow(shot->game, mem, 3)) {
                BITMAPFILEHEADER fh{}; fh.bfType = 0x4D42;
                fh.bfOffBits = sizeof fh + sizeof(BITMAPINFOHEADER); fh.bfSize = fh.bfOffBits + w * h * 4;
                shot->bmp.append((const char*)&fh, sizeof fh);
                shot->bmp.append((const char*)&bi.bmiHeader, sizeof(BITMAPINFOHEADER));
                shot->bmp.append((const char*)pixels, (size_t)w * h * 4);
            }
            SelectObject(mem, old);
        }
        if (bm) DeleteObject(bm); if (mem) DeleteDC(mem); if (dc) ReleaseDC(shot->game, dc);
    }
    s_shot_busy = false; release(shot); return 0;
}
std::string screenshot(HWND game) {
    if (!game || s_shot_busy.exchange(true)) return {};
    Shot* shot = new Shot; shot->game = game;
    HANDLE h = CreateThread(nullptr, 0, take_shot, shot, 0, nullptr);
    if (!h) { s_shot_busy = false; release(shot); release(shot); return {}; }
    std::string result;
    if (WaitForSingleObject(h, 2000) == WAIT_OBJECT_0) result = shot->bmp;
    CloseHandle(h); release(shot); return result;
}

DWORD WINAPI export_worker(void* ptr) {
    try {
        if (!s_enabled.load()) { s_busy = 0; return 0; }
        HWND game = static_cast<HWND>(ptr);
        std::vector<Entry> entries;
        entries.push_back({"report.txt", report(game)});
        entries.push_back({"hitches.txt", hitch_history()});
        std::string bmp = screenshot(game);
        if (!bmp.empty()) entries.push_back({"game-window.bmp", std::move(bmp)});
        entries.push_back({"stdout.log", s_logs[0].snapshot()});
        entries.push_back({"stderr.log", s_logs[1].snapshot()});
        entries.push_back({"README.txt", "Attach this ZIP and describe the track, screen, actions and wait time.\r\n"
            "Logs contain only recent output since Debug export was enabled (up to 2 MiB per stream).\r\n"
            "hitches.txt retains up to eight live state samples taken during gaps over 250 ms while enabled.\r\n"
            "No game files, shader code, full memory dump or save data are included.\r\n"
            "The optional image is only the game client window; it may be unavailable or blank on a hung renderer.\r\n"
            "The snapshot does not pause the game; fields may change while being sampled.\r\n"});
        /* Serialize the final write with Off: once the setting is off, a
         * pending request cannot publish a new archive. */
        std::lock_guard<std::mutex> control(s_control);
        if (!s_enabled.load()) { status(1, "Cancelled: Debug export was switched off"); s_busy = 0; return 0; }
        std::error_code ec; fs::create_directories(s_folder, ec);
        if (ec) throw std::runtime_error("Cannot create reports folder: " + ec.message());
        SYSTEMTIME t; GetLocalTime(&t); char name[100];
        snprintf(name, sizeof name, "gt5p-debug-%04u%02u%02u-%02u%02u%02u-%03u-%lu-%u.zip",
            t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, t.wMilliseconds,
            GetCurrentProcessId(), ++s_serial);
        fs::path path = s_folder / name, partial = path; partial += L".partial";
        FILE* f = _wfopen(partial.c_str(), L"wb");
        if (!f) throw std::runtime_error("Cannot write reports folder");
        bool ok = zip(f, entries); if (fclose(f)) ok = false;
        if (!ok) { fs::remove(partial, ec); throw std::runtime_error("Could not finish ZIP (disk full or write error)"); }
        fs::rename(partial, path, ec);
        if (ec) { fs::remove(partial); throw std::runtime_error("Cannot finish report: " + ec.message()); }
        status(3, std::string("Saved: ") + name);
        fprintf(stderr, "[debug-export] saved logs/debug/%s\n", name);
    } catch (const std::exception& e) { status(-1, e.what()); }
    catch (...) { status(-1, "Could not save debug report"); }
    s_busy = 0; return 0;
}
} // namespace

void gt5p_debug_init() { gt5p_debug_enable(gt5p_settings_file().debug_export ? 1 : 0); }
void gt5p_debug_enable(int on) {
    std::lock_guard<std::mutex> control(s_control);
    const char* kill = getenv("GT5P_DEBUG_EXPORT");
    bool enabled = on && gt5p_settings_enabled() && gt5p_settings_file().debug_export && !(kill && *kill == '0');
    if (!enabled) {
        s_enabled = false;
        ++s_generation;
        for (auto& log : s_logs) log.clear();
        { std::lock_guard<std::mutex> lock(s_hitch_lock); s_hitches.clear(); }
        return;
    }
    if (s_enabled.load()) return;
    s_hitch_frame = 0;
    if (!s_started.load()) {
        s_folder = fs::absolute("logs/debug");
        /* Logs only go to the player's reports folder. No env value can opt in. */
        s_started = true;
        bool out = start_log(s_logs[0], stdout), err = start_log(s_logs[1], stderr);
        s_capture_ok = out && err;
        atexit(gt5p_debug_shutdown);
    }
    if (!s_capture_ok) { status(-1, "Could not start recent-log capture"); return; }
    s_since = GetTickCount64(); s_enabled = true;
    status(1, "Ready - recent logs are being kept");
}
bool gt5p_debug_enabled() { return s_enabled.load(); }
bool gt5p_debug_logs_active() { return s_enabled.load(); }
void gt5p_debug_watchdog(unsigned frames, double age) {
    const unsigned generation = s_generation.load();
    const char* e = getenv("GT5P_HITCH_CAPTURE");
    if (!s_enabled.load() || (e && *e == '0') || frames < 200 || age < 250.0) return;
    /* Called on one owner thread; do not take any game/renderer locks. */
    if (s_hitch_frame == frames || s_hitch_busy.exchange(true)) return;
    s_hitch_frame = frames;
    auto* r = new (std::nothrow) HitchRequest{frames, generation, age, GetTickCount64() - s_since.load()};
    if (!r) { s_hitch_busy = false; return; }
    HANDLE h = CreateThread(nullptr, 0, hitch_worker, r, 0, nullptr);
    if (h) CloseHandle(h); else { delete r; s_hitch_busy = false; }
}
void gt5p_debug_shutdown() {
    std::lock_guard<std::mutex> control(s_control);
    if (!s_started.load()) return;
    s_enabled = false;
    fflush(stdout); fflush(stderr);
    for (int i = 0; i < 2; i++) {
        Log& log = s_logs[i];
        if (log.forward_fd >= 0) _dup2(log.forward_fd, i + 1);
        /* Closing the pipe's final writer lets the reader forward its tail.
         * A blocked original output must not hold up closing the game. */
        if (log.thread) { WaitForSingleObject(log.thread, 500); CloseHandle(log.thread); log.thread = nullptr; }
    }
    s_started = false;
}
void gt5p_debug_request(HWND game) {
    if (!s_enabled.load() || s_busy.exchange(1)) return;
    status(2, "Saving debug report...");
    HANDLE h = CreateThread(nullptr, 0, export_worker, game, 0, nullptr);
    if (h) CloseHandle(h); else { status(-1, "Could not start export worker"); s_busy = 0; }
}
int gt5p_debug_status(char* text, size_t size) {
    if (!s_enabled.load()) {
        const char* kill = getenv("GT5P_DEBUG_EXPORT");
        snprintf(text, size, "%s", kill && *kill == '0' ? "Debug export disabled by GT5P_DEBUG_EXPORT=0" :
            "Enable Debug export in F1 settings");
        return 0;
    }
    std::lock_guard<std::mutex> guard(s_status_lock);
    snprintf(text, size, "%s", s_message.c_str()); return s_status;
}
void gt5p_debug_open_folder() {
    if (!s_enabled.load()) return;
    std::error_code ec; fs::create_directories(s_folder, ec);
    if (ec || (INT_PTR)ShellExecuteW(nullptr, L"open", s_folder.c_str(), nullptr, nullptr, SW_SHOWNORMAL) <= 32)
        status(-1, "Could not open logs/debug");
}
