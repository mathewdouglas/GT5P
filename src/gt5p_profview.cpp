/* Live profiler view (GT5P_PROFVIEW).
 *
 * A small window kept over the top-left corner of the game window: the frame
 * rate, a graph of the last frames' intervals, what the present thread spent
 * each frame on (FIFO walk, present, the rest), and CPU per thread over the
 * last second. F3 shows and hides it.
 *
 *   GT5P_PROFVIEW unset  the view exists, hidden until F3
 *   GT5P_PROFVIEW=1      shown from the start
 *   GT5P_PROFVIEW=0      nothing: no thread, no window
 *
 * It is a separate GDI window rather than something drawn by the D3D12
 * backend, so it cannot disturb what the backend renders or its timing beyond
 * one thread waking ten times a second. The present thread reports each frame
 * through gt5p_pv_frame(); thread CPU comes from GetThreadTimes on a thread
 * snapshot taken twice a second. The job manager's lanes are threads made per
 * dispatch that exit within the second, so they show as the process total
 * minus the threads still alive ("exited threads").
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <tlhelp32.h>
#include <windowsx.h>
#include "gt5p_debug_export.h"

#include "ppu_context.h"
#include "sys_ppu_thread.h"

/* The GPU's own time for the last frame (rsx_d3d12_backend.c, RSX_GPU_TIME). */
extern "C" volatile double g_rsx_gpu_ms_last;

namespace {

/* One entry per present: when it happened, and what the present thread spent
 * since the previous one. Written by the present thread only; the view reads
 * it unlocked and tolerates a torn entry for one repaint. */
struct Frame { double t, fifo, pres, pump, vblank, flip, wait; };
const int kFrames = 512;
Frame s_fr[kFrames];
volatile LONG s_fr_n = 0;
double s_qf;

double now_s()
{
    LARGE_INTEGER c; QueryPerformanceCounter(&c);
    return (double)c.QuadPart / s_qf;
}

struct ThreadRow { DWORD tid; char name[64]; double pct; };
const int kRows = 64;
ThreadRow s_rows[kRows];
int s_nrows;
double s_proc_pct, s_exited_pct;
CRITICAL_SECTION s_rows_cs;

unsigned long long ft64(FILETIME f) { return ((unsigned long long)f.dwHighDateTime << 32) | f.dwLowDateTime; }

/* Name of a thread: the guest's name for a guest PPU thread, else the host
 * thread description, else its id. */
void thread_name(DWORD tid, HANDLE h, char* out, size_t n)
{
    for (int i = 0; i < PPU_THREAD_MAX; i++) {
        const ppu_thread_info* t = &g_ppu_threads[i];
        if (t->state != PPU_THREAD_STATE_FREE && t->host_tid == tid) {
            snprintf(out, n, "%s", t->name[0] ? t->name : "guest");
            return;
        }
    }
    typedef HRESULT (WINAPI *GetDesc)(HANDLE, PWSTR*);
    static GetDesc get = (GetDesc)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "GetThreadDescription");
    PWSTR w = NULL;
    if (get && SUCCEEDED(get(h, &w)) && w && w[0]) {
        WideCharToMultiByte(CP_UTF8, 0, w, -1, out, (int)n, NULL, NULL);
        LocalFree(w);
        return;
    }
    if (w) LocalFree(w);
    snprintf(out, n, "tid %lu", (unsigned long)tid);
}

/* CPU per thread since the previous call, in percent of one core. */
void sample_threads()
{
    struct Prev { DWORD tid; unsigned long long t; };
    static Prev prev[1024]; static int nprev;
    static unsigned long long prev_proc, prev_wall;

    FILETIME c, e, k, u, wall;
    GetSystemTimeAsFileTime(&wall);
    GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u);
    unsigned long long proc = ft64(k) + ft64(u), w = ft64(wall);

    static Prev cur[1024]; int ncur = 0;
    ThreadRow rows[kRows]; int nrows = 0;
    double live = 0, dw = (double)(w - prev_wall);
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    THREADENTRY32 te; te.dwSize = sizeof te;
    DWORD pid = GetCurrentProcessId();
    for (BOOL ok = Thread32First(snap, &te); ok; ok = Thread32Next(snap, &te)) {
        if (te.th32OwnerProcessID != pid || ncur >= 1024) continue;
        HANDLE h = OpenThread(THREAD_QUERY_LIMITED_INFORMATION, FALSE, te.th32ThreadID);
        if (!h) continue;
        if (GetThreadTimes(h, &c, &e, &k, &u)) {
            unsigned long long t = ft64(k) + ft64(u), d = t;
            for (int i = 0; i < nprev; i++)
                if (prev[i].tid == te.th32ThreadID) { d = t - prev[i].t; break; }
            cur[ncur].tid = te.th32ThreadID; cur[ncur].t = t; ncur++;
            if (prev_wall && dw > 0) {
                double pct = 100.0 * (double)d / dw;
                live += pct;
                if (pct >= 1.0 && nrows < kRows) {
                    rows[nrows].tid = te.th32ThreadID; rows[nrows].pct = pct;
                    thread_name(te.th32ThreadID, h, rows[nrows].name, sizeof rows[nrows].name);
                    nrows++;
                }
            }
        }
        CloseHandle(h);
    }
    CloseHandle(snap);
    for (int i = 0; i < nrows; i++)          /* busiest first */
        for (int j = i + 1; j < nrows; j++)
            if (rows[j].pct > rows[i].pct) { ThreadRow x = rows[i]; rows[i] = rows[j]; rows[j] = x; }

    double proc_pct = (prev_wall && dw > 0) ? 100.0 * (double)(proc - prev_proc) / dw : 0;
    EnterCriticalSection(&s_rows_cs);
    memcpy(s_rows, rows, sizeof(ThreadRow) * nrows); s_nrows = nrows;
    s_proc_pct = proc_pct;
    s_exited_pct = proc_pct > live ? proc_pct - live : 0;
    LeaveCriticalSection(&s_rows_cs);
    memcpy(prev, cur, sizeof(Prev) * ncur); nprev = ncur;
    prev_proc = proc; prev_wall = w;
}

HWND s_wnd, s_game;
int s_shown;
const int kW = 460, kH = 510;
const RECT kExport = {8, 432, 258, 460}, kFolder = {266, 432, 452, 460};

BOOL CALLBACK find_game(HWND h, LPARAM)
{
    DWORD pid; GetWindowThreadProcessId(h, &pid);
    if (pid != GetCurrentProcessId() || h == s_wnd || !IsWindowVisible(h) ||
        GetWindow(h, GW_OWNER) != NULL)
        return TRUE;
    /* The console can report this process as its owner. */
    char cls[64] = "";
    GetClassNameA(h, cls, sizeof cls);
    if (!strcmp(cls, "ConsoleWindowClass") || !strcmp(cls, "PseudoConsoleWindow"))
        return TRUE;
    s_game = h;
    return FALSE;
}

void text(HDC dc, int x, int y, COLORREF col, const char* fmt, ...)
{
    char b[256]; va_list a; va_start(a, fmt); vsnprintf(b, sizeof b, fmt, a); va_end(a);
    SetTextColor(dc, col);
    TextOutA(dc, x, y, b, (int)strlen(b));
}

void fill(HDC dc, int x0, int y0, int x1, int y1, COLORREF col)
{
    RECT r = { x0, y0, x1, y1 };
    HBRUSH b = CreateSolidBrush(col); FillRect(dc, &r, b); DeleteObject(b);
}

/* Bars for the last frames: height ms / scale, newest on the right. */
const COLORREF kFifo = RGB(240, 150, 40), kPres = RGB(70, 140, 240),
               kPump = RGB(170, 90, 200), kRest = RGB(90, 90, 90), kInt = RGB(80, 200, 120);

void paint(HDC dc)
{
    fill(dc, 0, 0, kW, kH, RGB(16, 16, 20));
    SetBkMode(dc, TRANSPARENT);
    HFONT f = CreateFontA(14, 0, 0, 0, FW_NORMAL, 0, 0, 0, ANSI_CHARSET, 0, 0, 0, FIXED_PITCH, "Consolas");
    HFONT of = (HFONT)SelectObject(dc, f);

    LONG n = s_fr_n;
    int have = n < kFrames ? (int)n : kFrames;
    /* Frame rate and interval statistics over the last second. */
    double tnow = now_s(), sum = 0, worst = 0, fifo = 0, pres = 0, pump = 0; int cnt = 0;
    for (int i = 1; i < have; i++) {
        const Frame& a = s_fr[(n - i) % kFrames];
        const Frame& b = s_fr[(n - i - 1) % kFrames];
        if (tnow - a.t > 1.0) break;
        double dt = a.t - b.t; sum += dt; cnt++; if (dt > worst) worst = dt;
        fifo += a.fifo; pres += a.pres; pump += a.pump;
    }
    double avg = cnt ? sum / cnt : 0;
    text(dc, 8, 6, RGB(255, 255, 255), "%5.1f fps  frame %5.1f avg %5.1f worst  gpu %4.1f ms",
         cnt ? cnt / (sum > 0 ? sum : 1) : 0.0, avg * 1e3, worst * 1e3, (double)g_rsx_gpu_ms_last);
    text(dc, 8, 22, RGB(200, 200, 200), "present thread per frame: fifo %4.1f  present %4.1f  pump %4.1f ms",
         cnt ? fifo / cnt * 1e3 : 0, cnt ? pres / cnt * 1e3 : 0, cnt ? pump / cnt * 1e3 : 0);

    /* Graph 1: frame interval. Graph 2: the present thread's frame, stacked. */
    const int gx = 8, gw = kW - 16, gh = 90, bars = gw / 2;
    const double full = 0.100;                       /* 100 ms at the top */
    for (int g = 0; g < 2; g++) {
        int gy = 44 + g * (gh + 22);
        fill(dc, gx, gy, gx + gw, gy + gh, RGB(28, 28, 34));
        static const double lines[] = { 1 / 60.0, 1 / 30.0, 1 / 20.0 };
        static const char* labels[] = { "60", "30", "20" };
        for (int L = 0; L < 3; L++) {
            int y = gy + gh - (int)(gh * lines[L] / full);
            fill(dc, gx, y, gx + gw, y + 1, RGB(70, 70, 80));
            text(dc, gx + gw - 18, y - 13, RGB(120, 120, 130), "%s", labels[L]);
        }
        for (int i = 0; i < bars && i + 1 < have; i++) {
            const Frame& a = s_fr[(n - 1 - i) % kFrames];
            const Frame& b = s_fr[(n - 2 - i) % kFrames];
            int x = gx + gw - 2 * (i + 1);
            double dt = a.t - b.t;
            if (g == 0) {
                int h = (int)(gh * (dt < full ? dt : full) / full);
                /* Coloured by how many 60 Hz vblanks the frame took. */
                COLORREF c = dt <= 1.05 / 60 ? kInt : dt <= 2.05 / 60 ? RGB(190, 210, 60)
                           : dt <= 3.05 / 60 ? RGB(240, 150, 40) : RGB(230, 70, 60);
                fill(dc, x, gy + gh - h, x + 2, gy + gh, c);
            } else {
                double parts[4] = { a.fifo, a.pres, a.pump, dt - a.fifo - a.pres - a.pump };
                COLORREF cols[4] = { kFifo, kPres, kPump, kRest };
                int y = gy + gh;
                for (int p = 0; p < 4; p++) {
                    double v = parts[p] > 0 ? parts[p] : 0;
                    int h = (int)(gh * v / full);
                    if (y - h < gy) h = y - gy;
                    fill(dc, x, y - h, x + 2, y, cols[p]); y -= h;
                }
            }
        }
        if (g == 0) text(dc, gx + 4, gy + 2, RGB(160, 160, 170), "frame interval (ms, 100 at top)");
        else {
            text(dc, gx + 4, gy + 2, kFifo, "fifo");
            text(dc, gx + 44, gy + 2, kPres, "present");
            text(dc, gx + 112, gy + 2, kPump, "pump");
            text(dc, gx + 156, gy + 2, RGB(150, 150, 150), "idle/sleep");
        }
    }

    /* Thread CPU over the last second. */
    int ty = 44 + 2 * (gh + 22) + 2;
    EnterCriticalSection(&s_rows_cs);
    text(dc, 8, ty, RGB(255, 255, 255), "CPU, %% of a core: process %.0f, job lanes (exited) %.0f",
         s_proc_pct, s_exited_pct);
    for (int i = 0; i < s_nrows && i < 8; i++) {
        int y = ty + 18 + i * 16;
        double pct = s_rows[i].pct;
        fill(dc, 200, y + 2, 200 + (int)(2.4 * (pct < 100 ? pct : 100)), y + 13,
             pct > 90 ? RGB(200, 70, 60) : RGB(70, 120, 180));
        text(dc, 8, y, RGB(220, 220, 220), "%-24.24s %4.0f%%", s_rows[i].name, pct);
    }
    LeaveCriticalSection(&s_rows_cs);
    char message[256]; int state = gt5p_debug_status(message, sizeof message);
    if (state) {
        fill(dc, kExport.left, kExport.top, kExport.right, kExport.bottom,
            state == 2 ? RGB(55, 55, 65) : RGB(40, 75, 110));
        text(dc, 16, 439, RGB(240, 240, 250), "Export debug report [F8]");
        fill(dc, kFolder.left, kFolder.top, kFolder.right, kFolder.bottom, RGB(45, 50, 60));
        text(dc, 274, 439, RGB(220, 220, 230), "Open reports folder");
    }
    RECT status_rect = {8, 465, kW - 8, 494};
    SetTextColor(dc, state == -1 ? RGB(255, 140, 120) : RGB(170, 190, 180));
    DrawTextA(dc, message, -1, &status_rect, DT_WORDBREAK | DT_NOPREFIX);
    text(dc, 8, kH - 15, RGB(110, 110, 120), "F3 hides  |  GT5P_PROFVIEW=0 disables");
    SelectObject(dc, of); DeleteObject(f);
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
    if (m == WM_NCHITTEST) {
        POINT p = {GET_X_LPARAM(l), GET_Y_LPARAM(l)}; ScreenToClient(h, &p);
        return gt5p_debug_enabled() && (PtInRect(&kExport, p) || PtInRect(&kFolder, p)) ? HTCLIENT : HTTRANSPARENT;
    }
    if (m == WM_MOUSEACTIVATE) return MA_NOACTIVATE;
    if (m == WM_LBUTTONUP && gt5p_debug_enabled()) {
        POINT p = {GET_X_LPARAM(l), GET_Y_LPARAM(l)};
        if (PtInRect(&kExport, p)) gt5p_debug_request(s_game);
        else if (PtInRect(&kFolder, p)) gt5p_debug_open_folder();
        return 0;
    }
    if (m == WM_ERASEBKGND) return 1;
    return DefWindowProcA(h, m, w, l);
}

DWORD WINAPI view_thread(LPVOID)
{
    WNDCLASSA wc = {};
    wc.lpfnWndProc = wndproc; wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "gt5p_profview"; wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassA(&wc);
    /* Wait for the game window, then own the view by it so it stays above it. */
    while (!s_game) { Sleep(500); EnumWindows(find_game, 0); }
    s_wnd = CreateWindowExA(WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
                            wc.lpszClassName, "GT5P profiler", WS_POPUP, 0, 0, kW, kH,
                            s_game, NULL, wc.hInstance, NULL);
    SetLayeredWindowAttributes(s_wnd, 0, 225, LWA_ALPHA);
    if (s_shown) ShowWindow(s_wnd, SW_SHOWNOACTIVATE);
    ULONGLONG last_sample = 0;
    int f3_was = 0, f8_was = 0;
    for (;;) {
        MSG msg;
        while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageA(&msg); }
        if (!IsWindow(s_game)) return 0;
        /* F3 while the game window has focus. */
        int f3 = (GetAsyncKeyState(VK_F3) & 0x8000) != 0;
        if (f3 && !f3_was && GetForegroundWindow() == s_game) {
            s_shown = !s_shown;
            ShowWindow(s_wnd, s_shown ? SW_SHOWNOACTIVATE : SW_HIDE);
        }
        f3_was = f3;
        SHORT f8_key = GetAsyncKeyState(VK_F8);
        int f8 = (f8_key & 0x8000) != 0;
        if (((f8_key & 1) || (f8 && !f8_was)) && s_shown && GetForegroundWindow() == s_game)
            gt5p_debug_request(s_game);
        f8_was = f8;
        ULONGLONG t = GetTickCount64();
        if (t - last_sample >= 1000) { sample_threads(); last_sample = t; }
        LONG frames = s_fr_n;
        if (frames > 0) gt5p_debug_watchdog((unsigned)frames, (now_s() - s_fr[(frames - 1) % kFrames].t) * 1000.0);
        if (s_shown) {
            POINT p = { 8, 8 }; ClientToScreen(s_game, &p);
            SetWindowPos(s_wnd, NULL, p.x, p.y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
            InvalidateRect(s_wnd, NULL, FALSE);
        }
        Sleep(100);
    }
}

}  // namespace

static int s_pv_on = -1;

/* Called by the present thread after each present, with its running totals
 * (seconds) of FIFO walk, present and message pump. */
extern "C" void gt5p_pv_frame(double fifo_total, double pres_total, double pump_total,
                             double vblank_total, double flip_total, double wait_total)
{
    if (s_pv_on <= 0) return;
    static double lf, lp, lm, lv, lb, lw;
    LONG n = s_fr_n;
    Frame& f = s_fr[n % kFrames];
    f.t = now_s(); f.fifo = fifo_total - lf; f.pres = pres_total - lp; f.pump = pump_total - lm;
    f.vblank = vblank_total - lv; f.flip = flip_total - lb; f.wait = wait_total - lw;
    lf = fifo_total; lp = pres_total; lm = pump_total;
    lv = vblank_total; lb = flip_total; lw = wait_total;
    InterlockedIncrement(&s_fr_n);
}

/* Start the view unless GT5P_PROFVIEW=0. Needs a window, so not headless. */
extern "C" void gt5p_start_profview(void)
{
    const char* e = getenv("GT5P_PROFVIEW");
    if ((e && e[0] == '0') || getenv("PS3_HEADLESS")) { s_pv_on = 0; return; }
    LARGE_INTEGER q; QueryPerformanceFrequency(&q); s_qf = (double)q.QuadPart;
    InitializeCriticalSection(&s_rows_cs);
    s_shown = e && e[0] == '1';
    s_pv_on = 1;
    HANDLE h = CreateThread(NULL, 256 * 1024, view_thread, NULL, 0, NULL);
    if (h) CloseHandle(h);
}

extern "C" void gt5p_pv_export(FILE* out)
{
    if (s_pv_on <= 0) { fprintf(out, "Profiler disabled\n"); return; }
    LONG n = s_fr_n; int have = n < kFrames ? (int)n : kFrames;
    double now = now_s();
    fprintf(out, "Total presents: %ld; last present age: %.3f s; last GPU time (may be stale): %.3f ms\n",
        n, have ? now - s_fr[(n - 1) % kFrames].t : -1.0, (double)g_rsx_gpu_ms_last);
    fprintf(out, "age_s,fifo_ms,present_ms,pump_ms,vblank_ms,flip_ms,idle_wait_ms\n");
    for (int i = have; i > 0; i--) {
        Frame f = s_fr[(n - i) % kFrames];
        fprintf(out, "%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f\n", now - f.t,
            f.fifo * 1000, f.pres * 1000, f.pump * 1000, f.vblank * 1000, f.flip * 1000, f.wait * 1000);
    }
    if (TryEnterCriticalSection(&s_rows_cs)) {
        fprintf(out, "CPU percent of one core: process=%.2f exited=%.2f\n", s_proc_pct, s_exited_pct);
        for (int i = 0; i < s_nrows; i++) fprintf(out, "hosttid=%lu %.2f%% %.63s\n", s_rows[i].tid, s_rows[i].pct, s_rows[i].name);
        LeaveCriticalSection(&s_rows_cs);
    } else fprintf(out, "CPU sample busy\n");
}
