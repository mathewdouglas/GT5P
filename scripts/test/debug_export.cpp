/* Integration harness for the production exporter and settings parser.
 * No game, runtime, memory dump or GPU required. */
#include "gt5p_debug_export.h"
#include "gt5p_settings.h"
#include <assert.h>
#include <string>
#include <atomic>

static bool s_fault;
static HANDLE s_snapshot_entered, s_snapshot_release;
static std::atomic<HWND> s_hung_window{nullptr};
static HANDLE s_hung_entered;
static LRESULT CALLBACK hung_proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_APP) { SetEvent(s_hung_entered); Sleep(10000); return 0; }
    if (m == WM_PRINT || m == WM_PRINTCLIENT) { Sleep(10000); return 0; }
    return DefWindowProcW(h, m, w, l);
}
static DWORD WINAPI hung_window(void*) {
    WNDCLASSW wc{}; wc.lpfnWndProc = hung_proc; wc.lpszClassName = L"gt5p_export_test_hung";
    wc.hInstance = GetModuleHandleW(nullptr); RegisterClassW(&wc);
    s_hung_window = CreateWindowW(wc.lpszClassName, L"Diagnostic test fixture", WS_OVERLAPPEDWINDOW,
        0, 0, 320, 240, nullptr, nullptr, wc.hInstance, nullptr);
    MSG msg; while (GetMessageW(&msg, nullptr, 0, 0) > 0) DispatchMessageW(&msg);
    return 0;
}
extern "C" void gt5p_debug_snapshot(FILE* out) {
    fprintf(out, "test snapshot marker\n");
    if (s_snapshot_release) {
        SetEvent(s_snapshot_entered);
        assert(WaitForSingleObject(s_snapshot_release, 3000) == WAIT_OBJECT_0);
    }
    if (s_fault) RaiseException(0xE0424242, 0, 0, nullptr);
}
extern "C" void gt5p_pv_export(FILE* out) { fprintf(out, "test frame marker\n"); }

static void wait_report(int expected) {
    char message[256];
    for (int i = 0; i < 100; i++) {
        int state = gt5p_debug_status(message, sizeof message);
        if (state != 2) { assert(state == expected); return; }
        Sleep(50);
    }
    assert(!"export timed out");
}
int main(int argc, char** argv) {
    assert(argc == 2);
    std::string mode = argv[1];
    s_fault = mode == "fault";
    gt5p_settings_load();
    if (mode == "pipeline-settings") {
        const bool file = std::string(getenv("TEST_PIPELINE_FILE")) == "1";
        const bool effective = std::string(getenv("TEST_PIPELINE_EFFECTIVE")) == "1";
        assert(gt5p_settings_file().pipeline_async == file);
        assert(gt5p_settings_file().race_preload == file);
        assert(gt5p_settings().pipeline_async == effective);
        assert(gt5p_settings().race_preload == effective);
        if (gt5p_settings_enabled()) {
            auto saved = gt5p_settings_file(); saved.pipeline_async = saved.race_preload = !file;
            assert(gt5p_settings_store(saved));
            assert(gt5p_settings_file().pipeline_async == !file);
            assert(gt5p_settings_file().race_preload == !file);
        }
        return 0;
    }
    if (mode == "warmup-settings") {
        const bool file = std::string(getenv("TEST_WARMUP_FILE")) == "1";
        const bool effective = std::string(getenv("TEST_WARMUP_EFFECTIVE")) == "1";
        assert(gt5p_settings_file().shader_warmup == file);
        assert(gt5p_settings().shader_warmup == effective);
        if (gt5p_settings_enabled()) {
            auto saved = gt5p_settings_file(); saved.shader_warmup = !file;
            assert(gt5p_settings_store(saved));
            assert(gt5p_settings_file().shader_warmup == !file);
        }
        return 0;
    }
    gt5p_debug_init();
    if (mode == "off") {
        assert(!gt5p_debug_enabled());
        gt5p_debug_enable(1); assert(!gt5p_debug_enabled());
        gt5p_debug_request(nullptr); Sleep(100);
        printf("disabled stdout marker\n"); fprintf(stderr, "disabled stderr marker\n");
    } else {
        assert(gt5p_debug_enabled());
        printf("begin overwritten marker\n"); fprintf(stderr, "begin overwritten marker\n");
        std::string block(16384, 'L');
        for (int i = 0; i < 192; i++) { fwrite(block.data(), 1, block.size(), stdout); fwrite(block.data(), 1, block.size(), stderr); }
        printf("\nexport stdout tail\n"); fprintf(stderr, "\nexport stderr tail\n");
        fflush(stdout); fflush(stderr); Sleep(200);
        if (mode == "enabled") {
            gt5p_debug_watchdog(300, 1000); Sleep(200);
            gt5p_debug_watchdog(300, 1200); /* same gap is not recorded twice */
        }
        if (mode == "epoch") {
            s_snapshot_entered = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            s_snapshot_release = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            assert(s_snapshot_entered && s_snapshot_release);
            gt5p_debug_watchdog(301, 1000);
            assert(WaitForSingleObject(s_snapshot_entered, 1000) == WAIT_OBJECT_0);
            auto s = gt5p_settings_file(); s.debug_export = false;
            assert(gt5p_settings_store(s)); gt5p_debug_enable(0);
            s.debug_export = true; assert(gt5p_settings_store(s)); gt5p_debug_enable(1);
            SetEvent(s_snapshot_release); Sleep(200);
            printf("export stdout tail\n"); fprintf(stderr, "export stderr tail\n");
            fflush(stdout); fflush(stderr); Sleep(100);
        }
        HWND game = nullptr;
        if (mode == "hung") {
            s_hung_entered = CreateEventW(nullptr, TRUE, FALSE, nullptr); assert(s_hung_entered);
            HANDLE h = CreateThread(nullptr, 0, hung_window, nullptr, 0, nullptr); assert(h); CloseHandle(h);
            for (int i = 0; !s_hung_window.load() && i < 100; i++) Sleep(10);
            game = s_hung_window.load(); assert(game);
            PostMessageW(game, WM_APP, 0, 0);
            assert(WaitForSingleObject(s_hung_entered, 1000) == WAIT_OBJECT_0);
        }
        ULONGLONG requested = GetTickCount64();
        gt5p_debug_request(game); gt5p_debug_request(game);
        wait_report(mode == "failure" ? -1 : 3);
        if (mode == "hung") assert(GetTickCount64() - requested < 4000);
        if (mode == "enabled") {
            gt5p_debug_request(nullptr); wait_report(3);
            auto s = gt5p_settings_file(); s.debug_export = false;
            assert(gt5p_settings_store(s)); gt5p_debug_enable(0);
            assert(!gt5p_debug_enabled()); gt5p_debug_request(nullptr); Sleep(100);
            printf("disabled interval marker\n"); fflush(stdout); Sleep(100);
            s.debug_export = true; assert(gt5p_settings_store(s)); gt5p_debug_enable(1);
            printf("fresh capture marker\n"); fflush(stdout); Sleep(100);
            gt5p_debug_request(nullptr); wait_report(3);
        }
    }
    fflush(stdout); fflush(stderr); Sleep(100);
    printf("shutdown stdout tail\n"); fprintf(stderr, "shutdown stderr tail\n");
    gt5p_debug_shutdown();
    /* Reader threads intentionally live for the process lifetime, as in game. */
    ExitProcess(0);
}
