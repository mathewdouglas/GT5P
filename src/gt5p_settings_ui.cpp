/* In-game settings page: F1 (or the PS button on a controller) over the game.
 *
 * Shows every setting of gt5p_settings.toml, changes it, and saves the file
 * at once. Settings the runtime can change while running (vsync, the keyboard
 * as a controller) take effect immediately; the rest say "after restart", and
 * a "Restart now" row relaunches the game with the new file.
 *
 * The page is drawn into the game's own picture: it is painted with GDI into
 * a bitmap at the backbuffer's scale (layout units are 1280 x 720 pixels),
 * and the D3D12 backend blends that over each frame before present
 * (rsx_d3d12_overlay_set). So it shows in fullscreen and in captures, and
 * keyboard and mouse are read while the game window has the focus.
 * GT5P_SETTINGS_UI_LEGACY=1 (or RSX_OVERLAY=0) keeps the older form: a GDI
 * window of its own over the game window, like the F3 profiler.
 * While it is open the game sees every controller at rest
 * (g_pad_input_blocked, cellPad.c), and the page reads the controllers itself.
 *
 *   keyboard    Up/Down select, Left/Right change, Enter/Space change or
 *               press, Esc/F1/Backspace close (Escape does not close the
 *               game while the page is up)
 *   controller  D-pad, Cross change or press, Circle close, PS opens/closes
 *   mouse       click a row to select it, click its value to change it
 *
 * GT5P_SETTINGS_UI=0: no page; =1: open it as soon as the window is up (for
 * testing). Under GT5P_NO_SETTINGS the page opens but
 * cannot save.
 *
 * To add a setting: a field in Gt5pSettings, its key in gt5p_settings.cpp
 * (read, known_key, save), and a row in items() below.
 */
#include <windows.h>
#include <windowsx.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <vector>

#include "gt5p_settings.h"
#include "gt5p_debug_export.h"

extern "C" {
extern volatile int g_pad_input_blocked;        /* cellPad.c */
extern volatile uint32_t g_pad_menu_buttons;    /* cellPad.c: bit 16 = PS button */
void pad_set_keyboard_enabled(int on);          /* cellPad.c */
void rsx_d3d12_set_present_sync(int interval);  /* rsx_d3d12_backend.c */
void gt5p_shader_indicator_enable(int on);      /* gt5p_shaderbusy.cpp */
extern void (*g_pad_screen_hook)(const char*);  /* cellPad.c: every file the title opens */
int  rsx_d3d12_overlay_available(void);         /* rsx_d3d12_backend.c */
void rsx_d3d12_backbuffer_size(int* w, int* h);
void rsx_d3d12_overlay_set(const void* bgra, int w, int h, int x, int y);
}

namespace {

/* CELL_PAD_CTRL_* (cellPad.h) */
const uint32_t kSelect = 1u << 0, kUp = 1u << 4, kRight = 1u << 5, kDown = 1u << 6, kLeft = 1u << 7,
               kCircle = 1u << 13, kCross = 1u << 14, kPs = 1u << 16;

struct Choice { int value; const wchar_t* label; };

struct Item {
    const wchar_t* section;
    const wchar_t* label;
    const wchar_t* help;
    const char* env;                         /* variable that overrides it */
    std::vector<Choice> choices;
    int  (*get)(const Gt5pSettings&);
    void (*set)(Gt5pSettings&, int);
    void (*apply)(int);                      /* live; nullptr: after a restart */
};

const std::vector<Choice> kOnOff = { {1, L"On"}, {0, L"Off"} };

const std::vector<Item>& items()
{
    static const std::vector<Item> v = {
        { L"VIDEO", L"Resolution",
          L"The display mode the game is told it has, and the window size. The game renders "
          L"natively at it.",
          "GT5P_RESOLUTION", { {720, L"1280 x 720"}, {1080, L"1920 x 1080"} },
          [](const Gt5pSettings& s) { return s.resolution; },
          [](Gt5pSettings& s, int v) { s.resolution = v; }, nullptr },
        { L"VIDEO", L"Antialiasing",
          L"Multisampling for what the game antialiases. The console used 2x; 4x is smoother "
          L"and costs a little speed.",
          "RSX_MSAA", { {1, L"Off"}, {2, L"2x"}, {4, L"4x"}, {8, L"8x"} },
          [](const Gt5pSettings& s) { return s.msaa; },
          [](Gt5pSettings& s, int v) { s.msaa = v; }, nullptr },
        { L"VIDEO", L"Vsync",
          L"Wait for the monitor's refresh when showing a frame. Off can tear, but never holds "
          L"the game back.",
          "RSX_PRESENT_SYNC", kOnOff,
          [](const Gt5pSettings& s) { return s.vsync ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.vsync = v != 0; },
          [](int v) { rsx_d3d12_set_present_sync(v ? 1 : 0); } },
        { L"VIDEO", L"Shader cache",
          L"Keep compiled shaders in the shadercache folder, so a screen seen before does not "
          L"stutter while they are rebuilt.",
          "RSX_SHADER_CACHE", kOnOff,
          [](const Gt5pSettings& s) { return s.shader_cache ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.shader_cache = v != 0; }, nullptr },
        { L"VIDEO", L"Shader compile indicator",
          L"Show \"Compiling shaders\" in the corner while the game builds shaders.",
          "GT5P_SHADER_INDICATOR", kOnOff,
          [](const Gt5pSettings& s) { return s.shader_indicator ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.shader_indicator = v != 0; },
          [](int v) { gt5p_shader_indicator_enable(v); } },
        { L"VIDEO", L"Background shader compilation",
          L"Build new shaders on background threads, all at once, instead of stopping the "
          L"picture to build them one by one. A new screen shows at once, its last details a "
          L"moment later. Needs the shader cache.",
          "RSX_SHADER_ASYNC", kOnOff,
          [](const Gt5pSettings& s) { return s.shader_precompile ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.shader_precompile = v != 0; }, nullptr },
        { L"VIDEO", L"Preload known shaders",
          L"Prepare learned menu, then race pipelines while the game starts and the movie "
          L"plays. Live draws take priority. First visits still learn. Needs shader cache "
          L"and background pipelines; uses more memory.",
          "RSX_SHADER_WARMUP", kOnOff,
          [](const Gt5pSettings& s) { return s.shader_warmup ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.shader_warmup = v != 0; }, nullptr },
        { L"VIDEO", L"Background pipeline creation",
          L"Build driver pipelines on a background worker to reduce render stalls. "
          L"First-seen details can appear a moment later while preparation finishes.",
          "RSX_PSO_ASYNC", kOnOff,
          [](const Gt5pSettings& s) { return s.pipeline_async ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.pipeline_async = v != 0; }, nullptr },
        { L"VIDEO", L"Prepare race pipelines",
          L"Prepare the race pipelines learned on earlier visits during loading. "
          L"First visits can still compile new states. Needs background pipeline creation "
          L"and shader cache; may extend loading and use more memory.",
          "RSX_RACE_PREWARM", kOnOff,
          [](const Gt5pSettings& s) { return s.race_preload ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.race_preload = v != 0; }, nullptr },
        { L"INPUT", L"PlayStation / other controllers",
          L"Read DualSense, DualShock, Switch and other controllers through SDL2.dll. Xbox "
          L"controllers work either way.",
          "PAD_NO_SDL", kOnOff,
          [](const Gt5pSettings& s) { return s.sdl_controllers ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.sdl_controllers = v != 0; }, nullptr },
        { L"INPUT", L"Keyboard as controller",
          L"Arrows, Z/X/A/S for Cross/Circle/Square/Triangle, Q/W for L1/R1, 1/2 for L2/R2, "
          L"Enter for Start, Tab for Select. Used when no controller is connected.",
          "PAD_NO_KEYBOARD", kOnOff,
          [](const Gt5pSettings& s) { return s.keyboard ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.keyboard = v != 0; },
          [](int v) { pad_set_keyboard_enabled(v); } },
        { L"GAME", L"Skip opening movie",
          L"Press through the opening movie as soon as it starts. It only plays when the TV "
          L"content is installed.",
          "PAD_SKIP_MOVIE", kOnOff,
          [](const Gt5pSettings& s) { return s.skip_movie ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.skip_movie = v != 0; }, nullptr },
        { L"PERFORMANCE", L"Frame clock",
          L"The vblank the game paces its frames to. 59.94 Hz is the console's (30 fps at "
          L"most). 62.5 Hz allows 31 fps, but a frame that just misses two vblanks drops to 20.",
          "GT5P_VBLANK_HZ", { {5994, L"59.94 Hz"}, {6250, L"62.5 Hz"} },
          [](const Gt5pSettings& s) { return s.vblank_hz100; },
          [](Gt5pSettings& s, int v) { s.vblank_hz100 = v; }, nullptr },
        { L"PERFORMANCE", L"SPU lanes on own cores",
          L"Keep each SPU render lane on a CPU core of its own. Strict (the default) is about "
          L"14% faster; Hint gains nothing; Off leaves them to Windows.",
          "SPURS_LANE_PIN", { {0, L"Off"}, {1, L"Hint"}, {2, L"Strict"} },
          [](const Gt5pSettings& s) { return s.lane_cores; },
          [](Gt5pSettings& s, int v) { s.lane_cores = v; }, nullptr },
        /* "Fifth SPU lane" (fifth_spu_lane, SPURS_JL_SPU3) is left off the page:
         * it cannot work, as SPU 3's own bookkeeping row is the render lists'
         * progress row (Phase 64). The file key stays, for testing. */
        { L"DEBUG", L"Runtime log",
          L"The full runtime log. Auto keeps it off for all launch methods. On makes "
          L"the game stutter.",
          "PS3_VERBOSE", { {-1, L"Auto"}, {0, L"Off"}, {1, L"On"} },
          [](const Gt5pSettings& s) { return s.verbose_log; },
          [](Gt5pSettings& s, int v) { s.verbose_log = v; }, nullptr },
        { L"DEBUG", L"Debug export",
          L"Keep recent logs and enable Export debug report in F3 (or F8 while F3 is open). "
          L"Saves a ZIP to logs/debug to attach to bug reports. Capture starts when enabled.",
          nullptr, kOnOff,
          [](const Gt5pSettings& s) { return s.debug_export ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.debug_export = v != 0; },
          [](int v) { gt5p_debug_enable(v); } },
    };
    return v;
}

/* Two columns, VIDEO on the left and the other sections on the right; the
 * "Restart now" and "Close" rows span both underneath. Fits 1280 x 720. */
const int kColW = 520, kGap = 16, kMargin = 18;
const int kW = 2 * kMargin + 2 * kColW + kGap, kH = 584;
const int kTop = 70, kRowH = 30, kSectionH = 26, kValOff = 360;   /* value area, from a column's left */

int column_of(const wchar_t* section) { return wcscmp(section, L"VIDEO") ? 1 : 0; }

HWND s_game, s_wnd;
bool s_open;
bool s_overlay;                 /* drawn into the game's picture (this open) */
double s_scale = 1;             /* overlay: backbuffer pixels per layout unit */
int s_ox, s_oy;                 /* overlay: its top left in the backbuffer */
int s_sel;
Gt5pSettings s_edit;   /* what the page shows and saves */
Gt5pSettings s_boot;   /* the file as this run started with it */
std::wstring s_status;

enum { kRowRestart = -1, kRowClose = -2 };

bool restart_pending()
{
    for (const Item& it : items())
        if (!it.apply && !gt5p_settings_overridden(it.env) && it.get(s_edit) != it.get(s_boot))
            return true;
    return false;
}

/* Rows in order: the items, then "Restart now" when needed, then "Close". */
std::vector<int> rows()
{
    std::vector<int> r;
    for (int i = 0; i < (int)items().size(); i++) r.push_back(i);
    if (restart_pending()) r.push_back(kRowRestart);
    r.push_back(kRowClose);
    return r;
}

/* Layout: where each row sits, with section headers above the first row of
 * each section in its column. `head` is set on a row that starts a section. */
struct Slot { int x0, x1, y; bool head; };
std::vector<Slot> layout(const std::vector<int>& r)
{
    std::vector<Slot> out;
    int col_y[2] = { kTop, kTop };
    const wchar_t* sec[2] = { nullptr, nullptr };
    int at = -1;
    for (int id : r) {
        if (id >= 0) {
            const wchar_t* s = items()[id].section;
            const int c = column_of(s), x0 = kMargin + c * (kColW + kGap);
            const bool head = s != sec[c];
            if (head) { sec[c] = s; col_y[c] += kSectionH; }
            out.push_back({ x0, x0 + kColW, col_y[c], head });
            col_y[c] += kRowH;
        } else {
            if (at < 0) at = (col_y[0] > col_y[1] ? col_y[0] : col_y[1]) + 14;
            out.push_back({ kMargin, kW - kMargin, at, false });
            at += kRowH;
        }
    }
    return out;
}

int choice_index(const Item& it)
{
    const int v = it.get(s_edit);
    for (int i = 0; i < (int)it.choices.size(); i++) if (it.choices[i].value == v) return i;
    return 0;
}

std::wstring widen(const std::string& s)
{
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, nullptr, 0);
    std::wstring w(n > 0 ? n - 1 : 0, L'\0');
    if (n > 1) MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, &w[0], n);
    return w;
}

void relaunch()
{
    /* The environment holds the variables loading the old file set; the new
     * process must read the new file instead. Clear the ones it set. */
    for (const Item& it : items())
        if (it.env && !gt5p_settings_overridden(it.env)) _putenv_s(it.env, "");
    wchar_t exe[MAX_PATH];
    GetModuleFileNameW(NULL, exe, MAX_PATH);
    std::wstring cmd = GetCommandLineW();
    STARTUPINFOW si = {}; si.cb = sizeof si;
    PROCESS_INFORMATION pi = {};
    if (CreateProcessW(exe, &cmd[0], NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
        fflush(stdout); fflush(stderr);
        TerminateProcess(GetCurrentProcess(), 0);
    }
    s_status = L"Could not start the game again; restart it by hand.";
}

void set_open(bool open);

void change(int id, int dir)
{
    if (id == kRowClose) { set_open(false); return; }
    if (id == kRowRestart) { relaunch(); return; }
    const Item& it = items()[id];
    const int n = (int)it.choices.size();
    const int v = it.choices[(choice_index(it) + dir + n) % n].value;
    it.set(s_edit, v);
    const bool over = gt5p_settings_overridden(it.env);
    if (!gt5p_settings_enabled()) s_status = L"GT5P_NO_SETTINGS is set: changes are not saved.";
    else if (!gt5p_settings_store(s_edit)) s_status = L"Could not write " + widen(gt5p_settings_path());
    else s_status = L"Saved.";
    if (over) s_status += L"  " + widen(it.env) + L" is set in the environment and wins over this.";
    else if (it.apply) { it.apply(v); s_status += L"  Applied."; }
    else if (it.get(s_edit) != it.get(s_boot)) s_status += L"  Takes effect after a restart.";
}

/* ---- drawing ---- */

const COLORREF kBg = RGB(26, 26, 28), kKey = RGB(255, 0, 255);

void fill(HDC dc, int x0, int y0, int x1, int y1, COLORREF c)
{
    RECT r = { x0, y0, x1, y1 };
    HBRUSH b = CreateSolidBrush(c); FillRect(dc, &r, b); DeleteObject(b);
}

void rounded(HDC dc, int x0, int y0, int x1, int y1, int rad, COLORREF c)
{
    HBRUSH b = CreateSolidBrush(c); HPEN p = CreatePen(PS_SOLID, 1, c);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, p);
    RoundRect(dc, x0, y0, x1, y1, rad, rad);
    SelectObject(dc, ob); SelectObject(dc, op); DeleteObject(b); DeleteObject(p);
}

void text(HDC dc, HFONT f, int x, int y, COLORREF c, const std::wstring& s, UINT align = TA_LEFT)
{
    HGDIOBJ o = SelectObject(dc, f);
    SetTextColor(dc, c); SetTextAlign(dc, align | TA_TOP);
    TextOutW(dc, x, y, s.c_str(), (int)s.size());
    SelectObject(dc, o);
}

HFONT font(int h, int weight)
{
    return CreateFontW(-h, 0, 0, 0, weight, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                       L"Segoe UI");
}

void paint(HDC dc)
{
    static HFONT fTitle = font(26, FW_SEMIBOLD), fRow = font(17, FW_NORMAL),
                 fSmall = font(13, FW_SEMIBOLD), fHelp = font(15, FW_NORMAL);
    SetBkMode(dc, TRANSPARENT);
    if (s_overlay) {
        /* A rounded panel: outside it is the key colour (clear), and its
         * plain background is see-through (render_overlay). */
        fill(dc, 0, 0, kW, kH, kKey);
        rounded(dc, 0, 0, kW + 1, kH + 1, 26, kBg);
        fill(dc, 22, 0, kW - 22, 3, RGB(196, 30, 36));
    } else {
        fill(dc, 0, 0, kW, kH, kBg);
        fill(dc, 0, 0, kW, 3, RGB(196, 30, 36));
    }
    text(dc, fTitle, 28, 18, RGB(240, 242, 248), L"Settings");
    text(dc, fHelp, kW - 28, 26, RGB(120, 126, 140),
         s_overlay ? L"F1, Esc or PS button to close" : L"F1 or PS button to close", TA_RIGHT);

    const std::vector<int> r = rows();
    const std::vector<Slot> sl = layout(r);
    if (s_sel >= (int)r.size()) s_sel = (int)r.size() - 1;
    for (size_t i = 0; i < r.size(); i++) {
        const int id = r[i], top = sl[i].y, x0 = sl[i].x0, x1 = sl[i].x1, vx = x0 + kValOff;
        const bool sel = (int)i == s_sel;
        if (sl[i].head) text(dc, fSmall, x0 + 12, top - kSectionH + 8, RGB(110, 118, 135), items()[id].section);
        if (sel) {   /* grey bar with a red rim, like the game's own buttons */
            rounded(dc, x0, top, x1, top + kRowH - 4, 10, RGB(196, 30, 36));
            rounded(dc, x0 + 2, top + 2, x1 - 2, top + kRowH - 6, 8, RGB(70, 70, 74));
        }
        if (id == kRowRestart) {
            text(dc, fRow, x0 + 12, top + 6, RGB(255, 210, 120), L"Restart now to apply");
            continue;
        }
        if (id == kRowClose) {
            text(dc, fRow, x0 + 12, top + 6, RGB(220, 224, 232), L"Close");
            continue;
        }
        const Item& it = items()[id];
        const bool over = gt5p_settings_overridden(it.env);
        const bool later = !it.apply && !over && it.get(s_edit) != it.get(s_boot);
        text(dc, fRow, x0 + 12, top + 6, over ? RGB(130, 134, 145) : RGB(225, 228, 236), it.label);
        std::wstring val = it.choices[choice_index(it)].label;
        COLORREF vc = over ? RGB(130, 134, 145) : RGB(255, 255, 255);
        text(dc, fRow, (vx + x1 - 12) / 2, top + 6, vc, val, TA_CENTER);
        text(dc, fRow, vx, top + 6, sel ? RGB(240, 110, 110) : RGB(90, 90, 96), L"‹");
        text(dc, fRow, x1 - 12, top + 6, sel ? RGB(240, 110, 110) : RGB(90, 90, 96), L"›", TA_RIGHT);
        if (later) text(dc, fSmall, vx - 12, top + 9, RGB(255, 190, 90), L"after restart", TA_RIGHT);
        else if (over) text(dc, fSmall, vx - 12, top + 9, RGB(150, 150, 160),
                            L"set by " + widen(it.env), TA_RIGHT);
    }

    /* The selected item's help, the last status, the controls. */
    const int hy = kH - 108;
    fill(dc, kMargin, hy - 8, kW - kMargin, hy - 7, RGB(40, 44, 54));
    if (s_sel >= 0 && s_sel < (int)r.size() && r[s_sel] >= 0) {
        RECT rc = { 30, hy, kW - 30, hy + 44 };
        HGDIOBJ o = SelectObject(dc, fHelp);
        SetTextColor(dc, RGB(170, 176, 190)); SetTextAlign(dc, TA_LEFT | TA_TOP);
        DrawTextW(dc, items()[r[s_sel]].help, -1, &rc, DT_WORDBREAK | DT_NOPREFIX);
        SelectObject(dc, o);
    }
    if (!s_status.empty()) text(dc, fHelp, 30, kH - 58, RGB(140, 200, 140), s_status);
    text(dc, fHelp, 30, kH - 32, RGB(110, 116, 130),
         L"↑↓ select    ←→ change    Esc close    "
         L"·  Controller: D-pad, ✕ change, ○ close");
}

void activate(int dir);

/* A click at layout position (mx, my): select the row, and change its value
 * when the click is on the value (left half back, right half on). */
void click(int mx, int my)
{
    const std::vector<int> r = rows();
    const std::vector<Slot> sl = layout(r);
    for (size_t i = 0; i < r.size(); i++)
        if (my >= sl[i].y && my < sl[i].y + kRowH - 4 && mx >= sl[i].x0 && mx < sl[i].x1) {
            s_sel = (int)i;
            const int vx = sl[i].x0 + kValOff;
            if (r[i] < 0 || mx >= vx) activate(r[i] >= 0 && mx < (vx + sl[i].x1 - 12) / 2 ? -1 : +1);
            break;
        }
}

/* Overlay: paint at the backbuffer's scale into a 32-bit bitmap, make it
 * premultiplied BGRA (the key colour clear, the panel's plain background
 * see-through, everything drawn on it opaque) and hand it to the backend,
 * centred. */
void push_image(int lw, int lh, void (*painter)(HDC), bool corner)
{
    int bw = 0, bh = 0;
    rsx_d3d12_backbuffer_size(&bw, &bh);
    if (bw <= 0 || bh <= 0) return;
    double sc = bh / 720.0;
    if (lw * sc > bw) sc = bw / (double)lw;
    const int w = (int)(lw * sc + 0.5), h = (int)(lh * sc + 0.5);
    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    HDC dc = CreateCompatibleDC(NULL);
    HBITMAP bm = dc ? CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, NULL, 0) : NULL;
    if (!bm || !bits) { if (bm) DeleteObject(bm); if (dc) DeleteDC(dc); return; }
    HGDIOBJ o = SelectObject(dc, bm);
    SetGraphicsMode(dc, GM_ADVANCED);
    XFORM x = { (FLOAT)sc, 0, 0, (FLOAT)sc, 0, 0 };
    SetWorldTransform(dc, &x);
    painter(dc);
    GdiFlush();
    static int alpha = -1;   /* GT5P_SETTINGS_UI_ALPHA: the background's opacity, 0-255 */
    if (alpha < 0) { const char* e = getenv("GT5P_SETTINGS_UI_ALPHA"); alpha = e ? atoi(e) & 255 : 236; }
    const uint32_t key = ((uint32_t)GetRValue(kKey) << 16) | ((uint32_t)GetGValue(kKey) << 8) | GetBValue(kKey);
    const uint32_t bg = ((uint32_t)GetRValue(kBg) << 16) | ((uint32_t)GetGValue(kBg) << 8) | GetBValue(kBg);
    const uint32_t bgp = ((uint32_t)alpha << 24) | ((GetRValue(kBg) * alpha / 255u) << 16) |
                         ((GetGValue(kBg) * alpha / 255u) << 8) | (GetBValue(kBg) * alpha / 255u);
    uint32_t* p = (uint32_t*)bits;
    for (int i = 0, n = w * h; i < n; i++) {
        const uint32_t c = p[i] & 0xFFFFFFu;
        p[i] = c == key ? 0 : c == bg ? bgp : c | 0xFF000000u;
    }
    if (corner) {   /* bottom right, in the game's own margin */
        rsx_d3d12_overlay_set(bits, w, h, bw - w - (int)(40 * sc), bh - h - (int)(34 * sc));
    } else {
        s_scale = sc; s_ox = (bw - w) / 2; s_oy = (bh - h) / 2;
        rsx_d3d12_overlay_set(bits, w, h, s_ox, s_oy);
    }
    SelectObject(dc, o); DeleteObject(bm); DeleteDC(dc);
}

void render_overlay()
{
    if (s_open && s_overlay) push_image(kW, kH, paint, false);
}

/* The game's Options screen: a tag in its bottom right saying the port's
 * settings are a button away. GT5P_OPTIONS_HINT=0: no tag, and Select does
 * not open the page. */
const int kHintW = 214, kHintH = 34;
void paint_hint(HDC dc)
{
    static HFONT fBtn = font(13, FW_BOLD), fLbl = font(16, FW_NORMAL);
    SetBkMode(dc, TRANSPARENT);
    fill(dc, 0, 0, kHintW, kHintH, kKey);
    rounded(dc, 0, 0, kHintW + 1, kHintH + 1, 14, kBg);
    rounded(dc, 10, 8, 78, kHintH - 7, 8, RGB(196, 30, 36));
    rounded(dc, 11, 9, 77, kHintH - 8, 7, RGB(70, 70, 74));
    text(dc, fBtn, 44, 10, RGB(240, 240, 244), L"SELECT", TA_CENTER);
    text(dc, fLbl, 90, 7, RGB(225, 228, 236), L"PC settings");
}

bool hint_enabled()
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("GT5P_OPTIONS_HINT"); on = !(e && e[0] == '0'); }
    return on != 0;
}

volatile int s_in_options;     /* the title's Options screen is up */
bool s_hint_shown;

/* Which screen the title is on, from the screen scripts (.gpb) it reads.
 * GT5P_SETTINGS_UI_DBG=1 prints each one. */
volatile int s_dbg_screens = -1;
void screen_seen(const char* b)
{
    const size_t n = strlen(b);
    if (n < 5 || strcmp(b + n - 4, ".gpb")) return;
    if (s_dbg_screens < 0) { const char* e = getenv("GT5P_SETTINGS_UI_DBG"); s_dbg_screens = e && e[0] == '1'; }
    if (s_dbg_screens) fprintf(stderr, "[settings-ui] %llu ms screen %s\n", GetTickCount64(), b);
    /* Entering Options reads OptionRoot (then the gadget layer, DLSGadgetRoot);
     * leaving it reads the top menu's scripts again (TopRoot,
     * TopMenuTemplate); any other screen root also means it has gone. */
    if (!strcmp(b, "OptionRoot.gpb")) s_in_options = 1;
    else if (strcmp(b, "DLSGadgetRoot.gpb") &&
             (strstr(b, "Root.gpb") || strstr(b, "Template.gpb"))) s_in_options = 0;
}

/* Redraw whichever form is open. */
void redraw()
{
    if (!s_open) return;
    if (s_overlay) render_overlay();
    else InvalidateRect(s_wnd, NULL, FALSE);
}

/* ---- window ---- */

/* Centre the page over the game. Only when it moved, and asynchronously:
 * the game window belonged to the present thread (with RSX_WINDOW_THREAD=0
 * it still does), and a synchronous
 * SetWindowPos every tick waited on it whenever the game was busy (a shader
 * compile), freezing the page for seconds. An owned window stays above its
 * owner, so the z-order is left alone. */
void place(bool force = false)
{
    static POINT last = { -100000, -100000 };
    RECT rc; GetClientRect(s_game, &rc);
    POINT p = { (rc.right - kW) / 2, (rc.bottom - kH) / 2 };
    if (p.x < 0) p.x = 0;
    if (p.y < 0) p.y = 0;
    ClientToScreen(s_game, &p);
    if (!force && p.x == last.x && p.y == last.y) return;
    last = p;
    SetWindowPos(s_wnd, NULL, p.x, p.y, 0, 0,
                 SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
}

bool s_release_wait;     /* closed; the title's input waits for all buttons up */

bool legacy_ui()
{
    static int legacy = -1;
    if (legacy < 0) { const char* e = getenv("GT5P_SETTINGS_UI_LEGACY"); legacy = e && e[0] == '1'; }
    return legacy != 0;
}

void set_open(bool open)
{
    if (open == s_open) return;
    s_open = open;
    s_hint_shown = false;   /* the page's image replaces the tag, and closing clears both */
    /* Closing keeps the title's pads at rest until every button is let go
     * (the loop below): the Circle or Cross that closed the page must not
     * reach the game as a new press. */
    if (open) g_pad_input_blocked = 1;
    else s_release_wait = true;
    if (open) {
        s_edit = gt5p_settings_file();
        s_sel = 0;
        s_status = gt5p_settings_enabled() ? L"" : L"GT5P_NO_SETTINGS is set: changes are not saved.";
        s_overlay = !legacy_ui() && rsx_d3d12_overlay_available();
        if (s_overlay) { render_overlay(); return; }
        place(true);
        ShowWindow(s_wnd, SW_SHOW);
        SetForegroundWindow(s_wnd);
        SetFocus(s_wnd);
        InvalidateRect(s_wnd, NULL, FALSE);
    } else if (s_overlay) {
        rsx_d3d12_overlay_set(nullptr, 0, 0, 0, 0);
    } else {
        ShowWindow(s_wnd, SW_HIDE);
        SetForegroundWindow(s_game);
    }
}

void move_sel(int d)
{
    const int n = (int)rows().size();
    s_sel = (s_sel + d + n) % n;
}

void activate(int dir)
{
    const std::vector<int> r = rows();
    if (s_sel >= 0 && s_sel < (int)r.size()) change(r[s_sel], dir);
}

LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_PAINT: {
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
    case WM_ERASEBKGND: return 1;
    case WM_KEYDOWN:
        switch (w) {
        case VK_UP:    move_sel(-1); break;
        case VK_DOWN:  move_sel(+1); break;
        case VK_LEFT:  activate(-1); break;
        case VK_RIGHT: case VK_RETURN: case VK_SPACE: activate(+1); break;
        case VK_ESCAPE: case VK_F1: case VK_BACK: set_open(false); break;
        default: return 0;
        }
        redraw();   /* keys posted to this window drive the overlay too (tests) */
        return 0;
    case WM_LBUTTONDOWN:
        click(GET_X_LPARAM(l), GET_Y_LPARAM(l));
        InvalidateRect(h, NULL, FALSE);
        return 0;
    case WM_ACTIVATE:
        /* Clicking the game behind the page closes it. */
        if (LOWORD(w) == WA_INACTIVE && s_open && (HWND)l == s_game) set_open(false);
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

BOOL CALLBACK find_game(HWND h, LPARAM)
{
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid != GetCurrentProcessId() || !IsWindowVisible(h) || GetWindow(h, GW_OWNER) != NULL)
        return TRUE;
    wchar_t cls[64] = L"";
    GetClassNameW(h, cls, 64);
    if (!wcscmp(cls, L"ConsoleWindowClass") || !wcscmp(cls, L"PseudoConsoleWindow") ||
        !wcscmp(cls, L"gt5p_settings") || !wcscmp(cls, L"gt5p_profview"))
        return TRUE;
    s_game = h;
    return FALSE;
}

DWORD WINAPI ui_thread(LPVOID)
{
    WNDCLASSW wc = {};
    wc.lpfnWndProc = wndproc; wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"gt5p_settings"; wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassW(&wc);
    while (!s_game) { Sleep(500); EnumWindows(find_game, 0); }
    s_wnd = CreateWindowExW(WS_EX_LAYERED | WS_EX_TOOLWINDOW, wc.lpszClassName, L"GT5P settings",
                            WS_POPUP, 0, 0, kW, kH, s_game, NULL, wc.hInstance, NULL);
    SetLayeredWindowAttributes(s_wnd, 0, 242, LWA_ALPHA);
    fprintf(stderr, "[settings-ui] page ready over window %p (%s): F1 or the PS button\n",
            (void*)s_game, s_wnd ? "ok" : "CreateWindow failed");
    s_boot = gt5p_settings_file();
    g_pad_screen_hook = screen_seen;
    { const char* e = getenv("GT5P_SETTINGS_UI"); if (e && e[0] == '1') set_open(true); }

    int f1_was = 0;
    uint32_t pad_was = 0;
    ULONGLONG repeat_at = 0;
    for (;;) {
        MSG msg;
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        if (!IsWindow(s_game)) return 0;

        /* F1 over the game opens it (inside the legacy window, WM_KEYDOWN
         * closes it; the overlay reads its keys below). */
        const bool game_fg = GetForegroundWindow() == s_game;
        const int f1 = (GetAsyncKeyState(VK_F1) & 0x8000) != 0;
        if (f1 && !f1_was && game_fg) {
            if (!s_open) set_open(true);
            else if (s_overlay) set_open(false);
        }
        f1_was = f1;

        /* Overlay: the keyboard and mouse while the game window has the
         * focus, a held arrow repeating. */
        static uint8_t key_was[256];
        static ULONGLONG key_repeat_at;
        if (s_open && s_overlay && game_fg) {
            static const int keys[] = { VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT, VK_RETURN, VK_SPACE,
                                        VK_ESCAPE, VK_BACK, VK_LBUTTON };
            const ULONGLONG t = GetTickCount64();
            bool changed = false;
            for (int vk : keys) {
                const bool held = (GetAsyncKeyState(vk) & 0x8000) != 0;
                const bool arrow = vk == VK_UP || vk == VK_DOWN || vk == VK_LEFT || vk == VK_RIGHT;
                bool hit = held && !key_was[vk];
                if (hit && arrow) key_repeat_at = t + 380;
                else if (held && key_was[vk] && arrow && t >= key_repeat_at) { hit = true; key_repeat_at = t + 110; }
                key_was[vk] = held;
                if (!hit || !s_open) continue;
                changed = true;
                switch (vk) {
                case VK_UP:    move_sel(-1); break;
                case VK_DOWN:  move_sel(+1); break;
                case VK_LEFT:  activate(-1); break;
                case VK_RIGHT: case VK_RETURN: case VK_SPACE: activate(+1); break;
                case VK_ESCAPE: case VK_BACK: set_open(false); break;
                case VK_LBUTTON: {
                    /* Client pixels to backbuffer pixels (the swap chain is
                     * stretched over the window), then to layout units. A
                     * click on the game outside the page closes it. */
                    POINT c; GetCursorPos(&c); ScreenToClient(s_game, &c);
                    RECT rc; GetClientRect(s_game, &rc);
                    int bw = 0, bh = 0; rsx_d3d12_backbuffer_size(&bw, &bh);
                    if (rc.right <= 0 || rc.bottom <= 0 || bw <= 0 ||
                        c.x < 0 || c.y < 0 || c.x >= rc.right || c.y >= rc.bottom) break;
                    const double bx = c.x * (double)bw / rc.right, by = c.y * (double)bh / rc.bottom;
                    const int lx = (int)((bx - s_ox) / s_scale), ly = (int)((by - s_oy) / s_scale);
                    if (lx < 0 || ly < 0 || lx >= kW || ly >= kH) set_open(false);
                    else click(lx, ly);
                    break;
                }
                }
            }
            if (changed) redraw();
        } else if (s_open && s_overlay) {
            memset(key_was, 1, sizeof key_was);   /* a key still held on return is not a press */
        } else memset(key_was, 0, sizeof key_was);

        /* Controllers: PS toggles; while open, the d-pad and face buttons
         * drive the page, a held direction repeating. The buttons come from
         * the game's own pad polls (every frame); polling here as well would
         * run SDL's controller update on two threads at once. */
        const uint32_t pad = g_pad_menu_buttons, down = pad & ~pad_was;
        const ULONGLONG now = GetTickCount64();
        { static int dbg = -1;   /* GT5P_SETTINGS_UI_DBG=1: the buttons the page sees */
          if (dbg < 0) { const char* e = getenv("GT5P_SETTINGS_UI_DBG"); dbg = e && e[0] == '1'; }
          if (dbg && pad != pad_was) fprintf(stderr, "[settings-ui] %llu ms pad %05X\n", now, pad); }
        if ((down & kSelect) && !s_open && s_in_options && hint_enabled() && game_fg) set_open(true);
        else if ((down & kPs) && (s_open || GetForegroundWindow() == s_game)) set_open(!s_open);
        else if (s_open) {
            const uint32_t dirs = kUp | kDown | kLeft | kRight;
            uint32_t act = down;
            if (pad & dirs & pad_was) { if (now >= repeat_at) { act |= pad & dirs; repeat_at = now + 110; } }
            else if (down & dirs) repeat_at = now + 380;
            if (act & kUp) move_sel(-1);
            if (act & kDown) move_sel(+1);
            if (act & kLeft) activate(-1);
            if (act & (kRight | kCross)) activate(+1);
            if (act & kCircle) set_open(false);
            if (act && s_open) redraw();
        }
        pad_was = pad;
        if (s_release_wait && !s_open && !(pad & 0xFFFFu)) { g_pad_input_blocked = 0; s_release_wait = false; }
        else if (s_open) s_release_wait = false;

        /* The title's Options screen: show the tag while the page is closed. */
        const bool want_hint = s_in_options && !s_open && hint_enabled() && !legacy_ui() &&
                               rsx_d3d12_overlay_available();
        if (want_hint != s_hint_shown) {
            if (want_hint) push_image(kHintW, kHintH, paint_hint, true);
            else rsx_d3d12_overlay_set(nullptr, 0, 0, 0, 0);
            s_hint_shown = want_hint;
        }

        if (s_open && !s_overlay) place();
        Sleep(16);
    }
}

}  // namespace

/* Start the page unless GT5P_SETTINGS_UI=0. Needs a window, so not headless. */
extern "C" void gt5p_start_settings_ui(void)
{
    const char* e = getenv("GT5P_SETTINGS_UI");
    if ((e && e[0] == '0') || getenv("PS3_HEADLESS")) return;
    HANDLE h = CreateThread(NULL, 256 * 1024, ui_thread, NULL, 0, NULL);
    fprintf(stderr, "[settings-ui] thread %s\n", h ? "started" : "FAILED");
    if (h) CloseHandle(h);
}
