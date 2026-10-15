/* "Compiling shaders" indicator over the game window.
 *
 * The D3D12 backend compiles a guest program's shaders, and builds its
 * pipeline, on the thread that replays frames, so the picture stops while it
 * does: about 9 s the first time the showroom is entered without a shader
 * cache, and short stalls whenever a new screen needs new pipelines. This
 * shows a small badge in the corner of the game window while that happens,
 * from a thread and window of its own (like the F3 profiler), so it keeps
 * animating while the game's own frame is frozen.
 *
 * The backend counts the work (g_rsx_shader_busy and totals,
 * rsx_d3d12_backend.c). The badge appears once the work has gone on for
 * 0.2 s, so a single quick pipeline does not flash it, and stays until 0.7 s
 * after the last compile, so a burst reads as one. It counts the shaders
 * and pipelines of the burst.
 *
 * [video] shader_indicator in gt5p_settings.toml, the F1 page, or
 * GT5P_SHADER_INDICATOR=0 turn it off.
 */
#include <windows.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>

extern "C" {
extern volatile LONG g_rsx_shader_busy;       /* rsx_d3d12_backend.c */
extern volatile LONG g_rsx_shaders_compiled;
extern volatile LONG g_rsx_pipelines_built;
}

namespace {

const int kW = 236, kH = 38, kMargin = 16;
HWND s_game, s_wnd;
volatile LONG s_enabled = 1;
bool s_shown;
LONG s_burst;          /* shaders + pipelines since the badge's burst began */
int s_phase;           /* spinner step */

BOOL CALLBACK find_game(HWND h, LPARAM)
{
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid != GetCurrentProcessId() || !IsWindowVisible(h) || GetWindow(h, GW_OWNER) != NULL)
        return TRUE;
    wchar_t cls[64] = L"";
    GetClassNameW(h, cls, 64);
    if (!wcscmp(cls, L"ConsoleWindowClass") || !wcscmp(cls, L"PseudoConsoleWindow") ||
        !wcsncmp(cls, L"gt5p_", 5))
        return TRUE;
    s_game = h;
    return FALSE;
}

void paint(HDC dc)
{
    static HFONT f = CreateFontW(-15, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
                                 CLEARTYPE_QUALITY, 0, L"Segoe UI");
    RECT all = { 0, 0, kW, kH };
    HBRUSH bg = CreateSolidBrush(RGB(0, 0, 0)); FillRect(dc, &all, bg); DeleteObject(bg);
    /* The pill: everything black outside it is keyed out (LWA_COLORKEY). */
    HBRUSH pb = CreateSolidBrush(RGB(20, 23, 30)); HPEN pp = CreatePen(PS_SOLID, 1, RGB(52, 120, 220));
    HGDIOBJ ob = SelectObject(dc, pb), op = SelectObject(dc, pp);
    RoundRect(dc, 0, 0, kW, kH, kH, kH);
    SelectObject(dc, ob); SelectObject(dc, op); DeleteObject(pb); DeleteObject(pp);

    /* Spinner: eight dots round a circle, the lit one moving. */
    const int cx = 22, cy = kH / 2, r = 8;
    for (int i = 0; i < 8; i++) {
        const double a = i * 3.14159265 / 4;
        const int x = cx + (int)lround(r * cos(a)), y = cy + (int)lround(r * sin(a));
        const int age = (s_phase - i + 8) % 8;
        const int v = age == 0 ? 255 : age == 1 ? 170 : age == 2 ? 110 : 60;
        HBRUSH d = CreateSolidBrush(RGB(v * 52 / 255 + 10, v * 140 / 255 + 10, v));
        HPEN np = (HPEN)GetStockObject(NULL_PEN);
        HGDIOBJ o1 = SelectObject(dc, d), o2 = SelectObject(dc, np);
        Ellipse(dc, x - 2, y - 2, x + 3, y + 3);
        SelectObject(dc, o1); SelectObject(dc, o2); DeleteObject(d);
    }

    SetBkMode(dc, TRANSPARENT);
    HGDIOBJ of = SelectObject(dc, f);
    SetTextColor(dc, RGB(230, 233, 240));
    std::wstring s = L"Compiling shaders";
    if (s_burst > 1) s += L"  (" + std::to_wstring(s_burst) + L")";
    TextOutW(dc, 42, (kH - 18) / 2, s.c_str(), (int)s.size());
    SelectObject(dc, of);
}

LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    if (m == WM_PAINT) {
        PAINTSTRUCT ps; HDC dc = BeginPaint(h, &ps);
        HDC mem = CreateCompatibleDC(dc);
        HBITMAP bm = CreateCompatibleBitmap(dc, kW, kH);
        HGDIOBJ o = SelectObject(mem, bm);
        paint(mem);
        BitBlt(dc, 0, 0, kW, kH, mem, 0, 0, SRCCOPY);
        SelectObject(mem, o); DeleteObject(bm); DeleteDC(mem);
        EndPaint(h, &ps);
        return 0;
    }
    if (m == WM_NCHITTEST) return HTTRANSPARENT;
    if (m == WM_ERASEBKGND) return 1;
    return DefWindowProcW(h, m, w, l);
}

/* Bottom-right of the game's client area. Asynchronous and only on a change:
 * the game window's thread is the very one that is busy compiling. */
void place(UINT show_flag)
{
    static POINT last = { -100000, -100000 };
    RECT rc; GetClientRect(s_game, &rc);
    POINT p = { rc.right - kW - kMargin, rc.bottom - kH - kMargin };
    ClientToScreen(s_game, &p);
    if (!show_flag && p.x == last.x && p.y == last.y) return;
    last = p;
    SetWindowPos(s_wnd, NULL, p.x, p.y, 0, 0,
                 SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS | show_flag);
}

DWORD WINAPI badge_thread(LPVOID)
{
    WNDCLASSW wc = {};
    wc.lpfnWndProc = wndproc; wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"gt5p_shaderbusy"; wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassW(&wc);
    while (!s_game) { Sleep(500); EnumWindows(find_game, 0); }
    s_wnd = CreateWindowExW(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
                            wc.lpszClassName, L"GT5P shaders", WS_POPUP, 0, 0, kW, kH,
                            s_game, NULL, wc.hInstance, NULL);
    SetLayeredWindowAttributes(s_wnd, RGB(0, 0, 0), 235, LWA_COLORKEY | LWA_ALPHA);

    LONG last_total = g_rsx_shaders_compiled + g_rsx_pipelines_built, burst_base = last_total;
    ULONGLONG act_start = 0, last_act = 0, last_spin = 0;
    for (;;) {
        MSG msg;
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        if (!IsWindow(s_game)) return 0;

        const ULONGLONG now = GetTickCount64();
        const LONG total = g_rsx_shaders_compiled + g_rsx_pipelines_built;
        const bool act = g_rsx_shader_busy > 0 || total != last_total;
        last_total = total;
        if (act) {
            if (!act_start) { act_start = now; burst_base = total - (g_rsx_shader_busy > 0 ? 0 : 1); }
            last_act = now;
        } else if (act_start && now - last_act > 700) {
            act_start = 0;
        }
        const bool want = s_enabled && act_start && now - act_start >= 200;
        if (want != s_shown) {
            static ULONGLONG shown_at;
            s_shown = want;
            place(want ? SWP_SHOWWINDOW : SWP_HIDEWINDOW);
            if (want) shown_at = now;
            else fprintf(stderr, "[shader-badge] shown %.1f s: %ld shaders and pipelines\n",
                         (now - shown_at) / 1000.0, (long)s_burst);
        }
        if (s_shown) {
            place(0);
            s_burst = total - burst_base;
            if (now - last_spin >= 90) { last_spin = now; s_phase = (s_phase + 1) % 8; }
            InvalidateRect(s_wnd, NULL, FALSE);
        }
        Sleep(30);
    }
}

}  // namespace

/* The settings page switches it while running. */
extern "C" void gt5p_shader_indicator_enable(int on) { s_enabled = on ? 1 : 0; }

/* Start the badge's thread (it stays hidden until there is work), unless
 * there is no window. GT5P_SHADER_INDICATOR=0 starts it disabled. */
extern "C" void gt5p_start_shader_indicator(void)
{
    if (getenv("PS3_HEADLESS")) return;
    const char* e = getenv("GT5P_SHADER_INDICATOR");
    s_enabled = !(e && e[0] == '0');
    HANDLE h = CreateThread(NULL, 128 * 1024, badge_thread, NULL, 0, NULL);
    if (h) CloseHandle(h);
}
