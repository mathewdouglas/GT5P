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
 * It is styled after the game's own screens (Options, its Confirmation
 * popup). Escape in the game window asks "Quit Gran Turismo 5 Prologue?" in
 * a copy of that popup instead of closing at once (GT5P_ESC_CONFIRM=0: close
 * at once; GT5P_QUIT_UI=1 asks at start, for tests).
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
#include <math.h>
#include <wctype.h>

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
extern int (*rsx_d3d12_on_escape)(void);      /* Escape in the game window */
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

/* ---- layout ----
 *
 * The page fills the screen like the game's own Options screen, and the quit
 * question copies its "Confirmation" popup. Units are 1280 x 720 (the
 * backbuffer's pixels over 1.5 at 1080p); sizes and greys were measured from
 * the game's 1080p screens (Phase 115). VIDEO is the left column, the other
 * sections the right; the pill buttons sit between two rules at the bottom. */
const int kW = 1280, kH = 720;
const int kColX[2] = { 91, 648 }, kColW = 541;
const int kTop = 158, kBarH = 28, kRowH = 27, kValOff = 330;
const int kBtnW = 157, kBtnH = 37, kBtnY = 581, kBtnGap = 16;

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
bool s_quit;                    /* the quit question is up */
int s_quit_sel;                 /* 0 Cancel, 1 OK */
volatile LONG s_quit_req;       /* Escape pressed in the game window */

enum { kRowRestart = -1, kRowClose = -2 };

bool legacy_ui_flag()
{
    static int legacy = -1;
    if (legacy < 0) { const char* e = getenv("GT5P_SETTINGS_UI_LEGACY"); legacy = e && e[0] == '1'; }
    return legacy != 0;
}

bool restart_pending()
{
    for (const Item& it : items())
        if (!it.apply && !gt5p_settings_overridden(it.env) && it.get(s_edit) != it.get(s_boot))
            return true;
    return false;
}

/* Rows in order: the items, then the buttons ("Restart" when needed, "Close"). */
std::vector<int> rows()
{
    std::vector<int> r;
    for (int i = 0; i < (int)items().size(); i++) r.push_back(i);
    if (restart_pending()) r.push_back(kRowRestart);
    r.push_back(kRowClose);
    return r;
}

/* Where each row sits; `head` is set on a row that starts a section (its bar
 * is drawn above it). Buttons are side by side, centred. */
struct Slot { int x0, x1, y; bool head; };
std::vector<Slot> layout(const std::vector<int>& r)
{
    std::vector<Slot> out;
    int col_y[2] = { kTop, kTop };
    const wchar_t* sec[2] = { nullptr, nullptr };
    int nbtn = 0;
    for (int id : r) nbtn += id < 0;
    int bx = kW / 2 - (nbtn * kBtnW + (nbtn - 1) * kBtnGap) / 2;
    for (int id : r) {
        if (id >= 0) {
            const wchar_t* s = items()[id].section;
            const int c = column_of(s), x0 = kColX[c];
            const bool head = s != sec[c];
            if (head) { if (sec[c]) col_y[c] += 10; sec[c] = s; col_y[c] += kBarH + 4; }
            out.push_back({ x0, x0 + kColW, col_y[c], head });
            col_y[c] += kRowH;
        } else {
            out.push_back({ bx, bx + kBtnW, kBtnY, false });
            bx += kBtnW + kBtnGap;
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

/* The clear parts of a popup or tag; push_image paints them black, then white. */
COLORREF kKey = RGB(255, 0, 255);
int page_alpha();
double s_paint_scale = 1;       /* device pixels per unit while painting */

COLORREF grey(int v) { return RGB(v, v, v); }

void fill(HDC dc, int x0, int y0, int x1, int y1, COLORREF c)
{
    RECT r = { x0, y0, x1, y1 };
    HBRUSH b = CreateSolidBrush(c); FillRect(dc, &r, b); DeleteObject(b);
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
    return CreateFontW(-h, 0, 0, 0, weight, 0, 0, 0, DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0,
                       L"Segoe UI");
}

/* Draw in device pixels for the duration of a shape: gradients and round
 * caps are filled row by row at full resolution. */
struct DeviceSpace {
    HDC dc; XFORM saved;
    explicit DeviceSpace(HDC d) : dc(d) {
        GetWorldTransform(dc, &saved);
        XFORM id = { 1, 0, 0, 1, 0, 0 }; SetWorldTransform(dc, &id);
    }
    ~DeviceSpace() { SetWorldTransform(dc, &saved); }
};

/* A vertical gradient over a rectangle, one device row at a time. */
template <class F> void vgrad(HDC dc, double x0, double y0, double x1, double y1, F colour)
{
    DeviceSpace ds(dc);
    const double s = s_paint_scale;
    const int X0 = (int)(x0 * s + 0.5), X1 = (int)(x1 * s + 0.5);
    const int Y0 = (int)(y0 * s + 0.5), Y1 = (int)(y1 * s + 0.5);
    for (int y = Y0; y < Y1; y++) fill(dc, X0, y, X1, y + 1, colour((y + 0.5 - Y0) / (Y1 - Y0)));
}

/* A stadium (rectangle with half-circle ends), filled row by row, its
 * colour a function of the height through it. */
template <class F> void stadium(HDC dc, double x0, double y0, double x1, double y1, F colour)
{
    DeviceSpace ds(dc);
    const double s = s_paint_scale;
    const double X0 = x0 * s, X1 = x1 * s, Y0 = y0 * s, Y1 = y1 * s, r = (Y1 - Y0) / 2, cy = Y0 + r;
    for (int y = (int)Y0; y < (int)(Y1 + 0.999); y++) {
        const double yc = y + 0.5, dy = yc - cy;
        if (dy * dy > r * r) continue;
        const double half = sqrt(r * r - dy * dy);
        fill(dc, (int)(X0 + r - half + 0.5), y, (int)(X1 - r + half + 0.5), y + 1,
             colour((yc - Y0) / (Y1 - Y0)));
    }
}

int lerp(int a, int b, double t) { return (int)(a + (b - a) * (t < 0 ? 0 : t > 1 ? 1 : t)); }

/* The game's pill button: a grey edge, a black (or, focused, red) ring, and a
 * glass face: light grey-blue fading down to the middle, then near-black
 * rising again at the bottom edge. */
void pill(HDC dc, double x0, double y0, double x1, double y1, bool focused)
{
    stadium(dc, x0, y0, x1, y1, [](double) { return grey(46); });
    stadium(dc, x0 + 1, y0 + 1, x1 - 1, y1 - 1, [&](double) { return focused ? RGB(237, 0, 0) : grey(0); });
    stadium(dc, x0 + 3, y0 + 3, x1 - 3, y1 - 3, [](double t) {
        if (t < 0.5) { const double u = t / 0.5;
            return RGB(lerp(123, 57, u), lerp(125, 56, u), lerp(140, 57, u)); }
        const double u = (t - 0.5) / 0.5;
        const int v = u < 0.6 ? lerp(19, 3, u / 0.6) : lerp(3, 60, (u - 0.6) / 0.4);
        return grey(v);
    });
}

/* The arrow cursor the game draws over the focused button. */
void cursor(HDC dc, int x, int y)
{
    POINT p[] = { {x, y}, {x, y + 17}, {x + 4, y + 13}, {x + 7, y + 20}, {x + 10, y + 19},
                  {x + 7, y + 12}, {x + 12, y + 12} };
    HBRUSH b = CreateSolidBrush(grey(235)); HPEN pen = CreatePen(PS_SOLID, 1, grey(20));
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, pen);
    Polygon(dc, p, 7);
    SelectObject(dc, ob); SelectObject(dc, op); DeleteObject(b); DeleteObject(pen);
}

/* A section bar like the Options screen's "General": rules of grey 70 above
 * and below a dark gradient, a knob at each end, the title centred. */
void section_bar(HDC dc, int x0, int x1, int y, const wchar_t* title)
{
    static HFONT f = font(19, FW_SEMIBOLD);
    fill(dc, x0, y, x1, y + 1, grey(70));
    vgrad(dc, x0, y + 1, x1, y + kBarH - 1, [](double t) { return grey(lerp(3, 34, t)); });
    fill(dc, x0, y + kBarH - 1, x1, y + kBarH, grey(70));
    for (int k = 0; k < 2; k++) {
        const int cx = k ? x1 - 22 : x0 + 22, cy = y + kBarH / 2;
        stadium(dc, cx - 8, cy - 8, cx + 8, cy + 8, [](double t) { return grey(lerp(70, 18, t)); });
        stadium(dc, cx - 6.5, cy - 6.5, cx + 6.5, cy + 6.5, [](double t) { return grey(lerp(14, 44, t)); });
    }
    std::wstring s = title;
    for (auto& c : s) c = (wchar_t)(c == L'_' ? L' ' : c);
    /* "VIDEO" -> "Video": the game titles its bars in mixed case. */
    for (size_t i = 1; i < s.size(); i++) if (s[i - 1] != L' ') s[i] = (wchar_t)towlower(s[i]);
    text(dc, f, (x0 + x1) / 2, y + 2, grey(180), s, TA_CENTER);
}

/* A button glyph like the game's: a dark disc with a light rim and the
 * symbol, for the prompts at the top right. */
void button_glyph(HDC dc, int cx, int cy, bool cross)
{
    stadium(dc, cx - 12, cy - 12, cx + 12, cy + 12, [](double t) { return grey(lerp(120, 50, t)); });
    stadium(dc, cx - 10.5, cy - 10.5, cx + 10.5, cy + 10.5, [](double t) { return grey(lerp(10, 40, t)); });
    HPEN p = CreatePen(PS_SOLID, 2, cross ? RGB(110, 140, 220) : RGB(230, 90, 90));
    HGDIOBJ op = SelectObject(dc, p), ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    if (cross) { MoveToEx(dc, cx - 6, cy - 6, NULL); LineTo(dc, cx + 6, cy + 6);
                 MoveToEx(dc, cx + 6, cy - 6, NULL); LineTo(dc, cx - 6, cy + 6); }
    else Ellipse(dc, cx - 6, cy - 6, cx + 7, cy + 7);
    SelectObject(dc, op); SelectObject(dc, ob); DeleteObject(p);
}

/* The page, after the game's Options screen. */
void paint(HDC dc)
{
    static HFONT fHdrB = font(17, FW_BOLD), fHdrL = font(17, FW_LIGHT), fTitle = font(66, FW_NORMAL),
                 fPrompt = font(21, FW_NORMAL), fRow = font(17, FW_NORMAL), fTag = font(12, FW_SEMIBOLD),
                 fHelp = font(16, FW_NORMAL), fBtn = font(22, FW_NORMAL), fStatus = font(14, FW_NORMAL);
    SetBkMode(dc, TRANSPARENT);
    /* Black, lifting to grey 24 over the bottom fifth. A translucent page
     * (GT5P_SETTINGS_UI_ALPHA) paints the black as the key, at that alpha. */
    fill(dc, 0, 0, kW, 580, s_overlay && page_alpha() < 255 ? kKey : grey(0));
    vgrad(dc, 0, 580, kW, kH, [](double t) { return grey(lerp(0, 24, t)); });

    /* Header, title and its rule. */
    { SIZE a, b; HGDIOBJ o = SelectObject(dc, fHdrB);
      GetTextExtentPoint32W(dc, L"GRAN TURISMO 5 ", 15, &a); SelectObject(dc, fHdrL);
      GetTextExtentPoint32W(dc, L"Prologue ", 9, &b); SelectObject(dc, o);
      text(dc, fHdrB, 69, 42, grey(132), L"GRAN TURISMO 5 ");
      text(dc, fHdrL, 69 + a.cx, 42, grey(132), L"Prologue ");
      text(dc, fHdrB, 69 + a.cx + b.cx, 42, grey(132), L"spec III"); }
    text(dc, fTitle, 99, 62, RGB(62, 64, 68), L"Settings");
    fill(dc, 64, 130, 1216, 131, grey(180));
    /* Prompts, top right. */
    button_glyph(dc, 960, 42, true);  text(dc, fPrompt, 980, 29, grey(212), L"Change");
    button_glyph(dc, 1090, 42, false); text(dc, fPrompt, 1110, 29, grey(212), L"Back");
    /* Dotted rule between the columns, as between the Options panels. */
    for (int y = 158; y < 540; y += 7) fill(dc, 640, y, 641, y + 2, grey(74));

    const std::vector<int> r = rows();
    const std::vector<Slot> sl = layout(r);
    if (s_sel >= (int)r.size()) s_sel = (int)r.size() - 1;
    for (size_t i = 0; i < r.size(); i++) {
        const int id = r[i], top = sl[i].y, x0 = sl[i].x0, x1 = sl[i].x1, vx = x0 + kValOff;
        const bool sel = (int)i == s_sel;
        if (id < 0) {
            pill(dc, x0, top, x1, top + kBtnH, sel);
            text(dc, fBtn, (x0 + x1) / 2, top + 5, grey(232), id == kRowRestart ? L"Restart" : L"Close", TA_CENTER);
            if (sel) cursor(dc, (x0 + x1) / 2 + 2, top + 17);
            continue;
        }
        if (sl[i].head) section_bar(dc, x0, x1, top - kBarH - 4, items()[id].section);
        if (sel) pill(dc, x0 + 4, top + 1, x1 - 4, top + kRowH - 1, true);
        const Item& it = items()[id];
        const bool over = gt5p_settings_overridden(it.env);
        const bool later = !it.apply && !over && it.get(s_edit) != it.get(s_boot);
        const COLORREF lc = over ? grey(96) : sel ? grey(240) : grey(160);
        text(dc, fRow, x0 + 24, top + 3, lc, it.label);
        const std::wstring val = it.choices[choice_index(it)].label;
        text(dc, fRow, (vx + x1 - 20) / 2, top + 3, over ? grey(96) : grey(232), val, TA_CENTER);
        const COLORREF ac = sel ? grey(235) : grey(90);
        text(dc, fRow, vx, top + 3, ac, L"‹");
        text(dc, fRow, x1 - 20, top + 3, ac, L"›", TA_RIGHT);
        if (later) text(dc, fTag, vx - 10, top + 7, RGB(237, 60, 60), L"after restart", TA_RIGHT);
        else if (over) text(dc, fTag, vx - 10, top + 7, grey(110), L"set by " + widen(it.env), TA_RIGHT);
    }

    /* The selected item's help, centred like the Options descriptions. */
    if (s_sel >= 0 && s_sel < (int)r.size() && r[s_sel] >= 0) {
        RECT rc = { 160, 520, kW - 160, 568 };
        HGDIOBJ o = SelectObject(dc, fHelp);
        SetTextColor(dc, grey(160)); SetTextAlign(dc, TA_LEFT | TA_TOP);
        DrawTextW(dc, items()[r[s_sel]].help, -1, &rc, DT_WORDBREAK | DT_NOPREFIX | DT_CENTER);
        SelectObject(dc, o);
    }
    /* Buttons between the game's two bottom rules. */
    fill(dc, 91, 574, 1189, 575, grey(70));
    fill(dc, 64, 626, 1216, 627, grey(180));
    if (!s_status.empty()) text(dc, fStatus, kW / 2, 640, grey(140), s_status, TA_CENTER);
}

/* The quit question, a copy of the game's "Confirmation" popup: the scene
 * dimmed (key colour), a flat grey-28 panel with a dark header gradient,
 * the question, a rule, Cancel and OK. */
const int kQx0 = 360, kQx1 = 920, kQy0 = 175, kQy1 = 547, kQbtnY = 480;
const int kQbtnX[2] = { 475, 648 };
void paint_quit(HDC dc)
{
    static HFONT fTitle = font(23, FW_NORMAL), fMsg = font(23, FW_NORMAL), fBtn = font(24, FW_NORMAL);
    SetBkMode(dc, TRANSPARENT);
    fill(dc, 0, 0, kW, kH, kKey);
    fill(dc, kQx0 - 1, kQy0 - 1, kQx1 + 1, kQy1 + 1, grey(0));
    fill(dc, kQx0, kQy0, kQx1, kQy1, grey(28));
    vgrad(dc, kQx0, kQy0, kQx1, kQy0 + 26, [](double t) {
        return t < 0.04 ? RGB(45, 45, 48) : t < 0.1 ? grey(27) : t < 0.3 ? grey(lerp(9, 4, (t - 0.1) / 0.2))
                                                                          : grey(lerp(4, 28, (t - 0.3) / 0.7)); });
    text(dc, fTitle, (kQx0 + kQx1) / 2, kQy0 + 6, grey(222), L"Confirmation", TA_CENTER);
    text(dc, fMsg, (kQx0 + kQx1) / 2, 307, grey(236), L"Quit Gran Turismo 5 Prologue?", TA_CENTER);
    fill(dc, kQx0, 448, kQx1, 449, grey(76));
    static const wchar_t* const label[2] = { L"Cancel", L"OK" };
    for (int k = 0; k < 2; k++) {
        const int x0 = kQbtnX[k], x1 = x0 + kBtnW;
        pill(dc, x0, kQbtnY, x1, kQbtnY + kBtnH, s_quit_sel == k);
        text(dc, fBtn, (x0 + x1) / 2, kQbtnY + 5, grey(232), label[k], TA_CENTER);
    }
    cursor(dc, kQbtnX[s_quit_sel] + kBtnW / 2 + 2, kQbtnY + 18);
}

void activate(int dir);

/* A click at layout position (mx, my): select the row, and change its value
 * when the click is on the value (left half back, right half on). */
void click(int mx, int my)
{
    const std::vector<int> r = rows();
    const std::vector<Slot> sl = layout(r);
    for (size_t i = 0; i < r.size(); i++) {
        const int h = r[i] < 0 ? kBtnH : kRowH;
        if (my >= sl[i].y && my < sl[i].y + h && mx >= sl[i].x0 && mx < sl[i].x1) {
            s_sel = (int)i;
            const int vx = sl[i].x0 + kValOff;
            if (r[i] < 0) change(r[i], +1);
            else if (mx >= vx) activate(mx < (vx + sl[i].x1 - 20) / 2 ? -1 : +1);
            break;
        }
    }
}

/* Overlay: paint at the backbuffer's scale and hand the backend premultiplied
 * BGRA: full screen, or a tag in the corner. Painted twice, its clear parts
 * (kKey) black and then white: the black pass is the premultiplied colour,
 * and the difference between the passes is how much shows through, exact at
 * antialiased text edges. The clear parts then get black at `dim` alpha. */
void push_image(int lw, int lh, void (*painter)(HDC), bool corner, int dim)
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
    void* pass[2] = { nullptr, nullptr };
    HBITMAP bm[2] = { NULL, NULL };
    HDC dc = CreateCompatibleDC(NULL);
    for (int k = 0; k < 2 && dc; k++) bm[k] = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &pass[k], NULL, 0);
    if (!bm[0] || !bm[1]) {
        for (HBITMAP b : bm) if (b) DeleteObject(b);
        if (dc) DeleteDC(dc);
        return;
    }
    HGDIOBJ o = SelectObject(dc, bm[0]);
    SetGraphicsMode(dc, GM_ADVANCED);
    XFORM x = { (FLOAT)sc, 0, 0, (FLOAT)sc, 0, 0 };
    SetWorldTransform(dc, &x);
    s_paint_scale = sc;
    for (int k = 0; k < 2; k++) {
        SelectObject(dc, bm[k]);
        kKey = k ? RGB(255, 255, 255) : RGB(0, 0, 0);
        painter(dc);
    }
    kKey = RGB(255, 0, 255);
    s_paint_scale = 1;
    GdiFlush();
    uint32_t* p = (uint32_t*)pass[0];
    const uint32_t* q = (const uint32_t*)pass[1];
    for (int i = 0, n = w * h; i < n; i++) {
        const uint32_t c = p[i] & 0xFFFFFFu;
        const int through = (int)((q[i] >> 8) & 255) - (int)((c >> 8) & 255);   /* green channel */
        const uint32_t a = (uint32_t)(255 - (through < 0 ? 0 : through));
        /* over black at `dim`: colour stays, alpha a + (1 - a) * dim */
        const uint32_t out_a = a + (255 - a) * (uint32_t)dim / 255;
        p[i] = (out_a << 24) | c;
    }
    SelectObject(dc, o);
    DeleteObject(bm[1]);
    void* bits = pass[0];
    if (corner) {   /* bottom right, in the game's own margin */
        rsx_d3d12_overlay_set(bits, w, h, bw - w - (int)(40 * sc), bh - h - (int)(34 * sc));
    } else {
        s_scale = sc; s_ox = (bw - w) / 2; s_oy = (bh - h) / 2;
        rsx_d3d12_overlay_set(bits, w, h, s_ox, s_oy);
    }
    DeleteObject(bm[0]); DeleteDC(dc);
}

int page_alpha();

/* GT5P_SETTINGS_UI_ALPHA: the page's opacity, 0-255 (default 255, opaque as
 * the game's screens; lower lets the scene show through). */
int page_alpha()
{
    static int a = -1;
    if (a < 0) { const char* e = getenv("GT5P_SETTINGS_UI_ALPHA"); a = e ? atoi(e) & 255 : 255; }
    return a;
}

void render_overlay()
{
    if (s_quit) { push_image(kW, kH, paint_quit, false, 186); return; }   /* scene at ~27%, as measured */
    if (s_open && s_overlay) push_image(kW, kH, paint, false, page_alpha());
}

/* The game's Options screen: a tag in its bottom right saying the port's
 * settings are a button away. GT5P_OPTIONS_HINT=0: no tag, and Select does
 * not open the page. */
const int kHintW = 200, kHintH = 37;
void paint_hint(HDC dc)
{
    static HFONT fBtn = font(16, FW_SEMIBOLD), fLbl = font(18, FW_NORMAL);
    SetBkMode(dc, TRANSPARENT);
    fill(dc, 0, 0, kHintW, kHintH, kKey);
    pill(dc, 0, 4, 82, kHintH - 4, false);
    text(dc, fBtn, 41, 9, grey(232), L"SELECT", TA_CENTER);
    text(dc, fLbl, 92, 8, grey(212), L"PC settings");
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

/* Escape in the game window (rsx_d3d12_backend.c calls this on its window
 * thread): ask first, unless GT5P_ESC_CONFIRM=0 or the page cannot be drawn
 * into the picture. Returns 1 when it will ask (the window then stays open). */
int esc_pressed(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("GT5P_ESC_CONFIRM"); on = !(e && e[0] == '0'); }
    if (!on || legacy_ui_flag() || !rsx_d3d12_overlay_available()) return 0;
    InterlockedExchange(&s_quit_req, 1);
    return 1;
}

/* Redraw whichever form is open. */
void redraw()
{
    if (s_quit) { render_overlay(); return; }
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
        s_overlay = !legacy_ui_flag() && rsx_d3d12_overlay_available();
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

void set_quit(bool q)
{
    if (q == s_quit) return;
    s_quit = q;
    s_hint_shown = false;
    if (q) { g_pad_input_blocked = 1; s_quit_sel = 0; render_overlay(); }
    else { s_release_wait = true; rsx_d3d12_overlay_set(nullptr, 0, 0, 0, 0); }
}

void quit_choose(int k)
{
    if (k == 1) { set_quit(false); PostMessageW(s_game, WM_CLOSE, 0, 0); }
    else set_quit(false);
}

/* Up/Down through the rows. The buttons count as one stop: from the items
 * Down lands on the first button, from a button Down wraps to the top and
 * Up returns to the last item. */
void move_sel(int d)
{
    const std::vector<int> r = rows();
    const int n = (int)r.size();
    int nb = 0;
    for (int id : r) nb += id < 0;
    const int first_btn = n - nb;
    if (s_sel >= first_btn) s_sel = d > 0 ? 0 : first_btn - 1;
    else s_sel = (s_sel + d + n) % n;
    if (s_sel > first_btn) s_sel = first_btn;
}

/* Left/Right: change an item's value, or move between the buttons. */
void activate(int dir)
{
    const std::vector<int> r = rows();
    if (s_sel < 0 || s_sel >= (int)r.size()) return;
    if (r[s_sel] >= 0) { change(r[s_sel], dir); return; }
    const int n = (int)r.size();
    int nb = 0;
    for (int id : r) nb += id < 0;
    const int first_btn = n - nb;
    s_sel = first_btn + ((s_sel - first_btn + dir + nb) % nb);
}

/* Cross/Enter: change an item forward, or press a button. */
void press()
{
    const std::vector<int> r = rows();
    if (s_sel < 0 || s_sel >= (int)r.size()) return;
    change(r[s_sel], +1);
}

LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_PAINT: {
        PAINTSTRUCT ps; HDC dc = BeginPaint(h, &ps);
        HDC mem = CreateCompatibleDC(dc);
        HBITMAP bm = CreateCompatibleBitmap(dc, kW, kH);
        HGDIOBJ o = SelectObject(mem, bm);
        SetGraphicsMode(mem, GM_ADVANCED);
        paint(mem);
        BitBlt(dc, 0, 0, kW, kH, mem, 0, 0, SRCCOPY);
        SelectObject(mem, o); DeleteObject(bm); DeleteDC(mem);
        EndPaint(h, &ps);
        return 0;
    }
    case WM_ERASEBKGND: return 1;
    case WM_KEYDOWN:
        /* Keys posted to this window drive the overlay and the quit question
         * too (tests). */
        if (s_quit) {
            switch (w) {
            case VK_LEFT: case VK_RIGHT: s_quit_sel ^= 1; break;
            case VK_RETURN: case VK_SPACE: quit_choose(s_quit_sel); return 0;
            case VK_ESCAPE: case VK_BACK: set_quit(false); return 0;
            default: return 0;
            }
            redraw();
            return 0;
        }
        switch (w) {
        case VK_UP:    move_sel(-1); break;
        case VK_DOWN:  move_sel(+1); break;
        case VK_LEFT:  activate(-1); break;
        case VK_RIGHT: activate(+1); break;
        case VK_RETURN: case VK_SPACE: press(); break;
        case VK_ESCAPE: case VK_F1: case VK_BACK: set_open(false); break;
        default: return 0;
        }
        redraw();
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

/* The game window's mouse position in layout units, or false when outside. */
bool mouse_units(int* lx, int* ly)
{
    POINT c; GetCursorPos(&c); ScreenToClient(s_game, &c);
    RECT rc; GetClientRect(s_game, &rc);
    int bw = 0, bh = 0; rsx_d3d12_backbuffer_size(&bw, &bh);
    if (rc.right <= 0 || rc.bottom <= 0 || bw <= 0 ||
        c.x < 0 || c.y < 0 || c.x >= rc.right || c.y >= rc.bottom) return false;
    /* Client pixels to backbuffer pixels (the swap chain is stretched over
     * the window), then to layout units. */
    const double bx = c.x * (double)bw / rc.right, by = c.y * (double)bh / rc.bottom;
    *lx = (int)((bx - s_ox) / s_scale); *ly = (int)((by - s_oy) / s_scale);
    return true;
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
    rsx_d3d12_on_escape = esc_pressed;
    { const char* e = getenv("GT5P_SETTINGS_UI"); if (e && e[0] == '1') set_open(true); }
    { const char* e = getenv("GT5P_QUIT_UI"); if (e && e[0] == '1') InterlockedExchange(&s_quit_req, 1); }

    int f1_was = 0;
    uint32_t pad_was = 0;
    ULONGLONG repeat_at = 0;
    bool modal_was = false;
    for (;;) {
        MSG msg;
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        if (!IsWindow(s_game)) return 0;

        /* Escape from the game window: the quit question (not over the page,
         * which Escape closes). */
        if (InterlockedExchange(&s_quit_req, 0) && !s_open) set_quit(true);

        /* F1 over the game opens the page (inside the legacy window,
         * WM_KEYDOWN closes it; the overlay reads its keys below). */
        const bool game_fg = GetForegroundWindow() == s_game;
        const int f1 = (GetAsyncKeyState(VK_F1) & 0x8000) != 0;
        if (f1 && !f1_was && game_fg && !s_quit) {
            if (!s_open) set_open(true);
            else if (s_overlay) set_open(false);
        }
        f1_was = f1;

        /* Overlay and quit question: the keyboard and mouse while the game
         * window has the focus, a held arrow repeating. A key already held
         * when either opens (the Escape that asked) is not a press. */
        static const int keys[] = { VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT, VK_RETURN, VK_SPACE,
                                    VK_ESCAPE, VK_BACK, VK_LBUTTON };
        static uint8_t key_was[256];
        static ULONGLONG key_repeat_at;
        const bool modal = s_quit || (s_open && s_overlay);
        if (modal && !modal_was)
            for (int vk : keys) key_was[vk] = (GetAsyncKeyState(vk) & 0x8000) != 0;
        modal_was = modal;
        if (modal && game_fg) {
            const ULONGLONG t = GetTickCount64();
            bool changed = false;
            for (int vk : keys) {
                const bool held = (GetAsyncKeyState(vk) & 0x8000) != 0;
                const bool arrow = vk == VK_UP || vk == VK_DOWN || vk == VK_LEFT || vk == VK_RIGHT;
                bool hit = held && !key_was[vk];
                if (hit && arrow) key_repeat_at = t + 380;
                else if (held && key_was[vk] && arrow && t >= key_repeat_at) { hit = true; key_repeat_at = t + 110; }
                key_was[vk] = held;
                if (!hit) continue;
                if (s_quit) {
                    changed = true;
                    switch (vk) {
                    case VK_LEFT: case VK_RIGHT: s_quit_sel ^= 1; break;
                    case VK_RETURN: case VK_SPACE: quit_choose(s_quit_sel); break;
                    case VK_ESCAPE: case VK_BACK: set_quit(false); break;
                    case VK_LBUTTON: {
                        int lx, ly;
                        if (!mouse_units(&lx, &ly)) break;
                        for (int k = 0; k < 2; k++)
                            if (lx >= kQbtnX[k] && lx < kQbtnX[k] + kBtnW && ly >= kQbtnY && ly < kQbtnY + kBtnH)
                                quit_choose(k);
                        break;
                    }
                    default: changed = false;
                    }
                    continue;
                }
                if (!s_open) continue;
                changed = true;
                switch (vk) {
                case VK_UP:    move_sel(-1); break;
                case VK_DOWN:  move_sel(+1); break;
                case VK_LEFT:  activate(-1); break;
                case VK_RIGHT: activate(+1); break;
                case VK_RETURN: case VK_SPACE: press(); break;
                case VK_ESCAPE: case VK_BACK: set_open(false); break;
                case VK_LBUTTON: {
                    int lx, ly;
                    if (mouse_units(&lx, &ly)) click(lx, ly);
                    break;
                }
                }
            }
            if (changed) redraw();
        }

        /* Controllers: PS toggles the page; while the page or the question is
         * up, the d-pad and face buttons drive it, a held direction
         * repeating. The buttons come from the game's own pad polls (every
         * frame); polling here as well would run SDL's controller update on
         * two threads at once. */
        const uint32_t pad = g_pad_menu_buttons, down = pad & ~pad_was;
        const ULONGLONG now = GetTickCount64();
        { static int dbg = -1;   /* GT5P_SETTINGS_UI_DBG=1: the buttons the page sees */
          if (dbg < 0) { const char* e = getenv("GT5P_SETTINGS_UI_DBG"); dbg = e && e[0] == '1'; }
          if (dbg && pad != pad_was) fprintf(stderr, "[settings-ui] %llu ms pad %05X\n", now, pad); }
        const uint32_t dirs = kUp | kDown | kLeft | kRight;
        uint32_t act = down;
        if (pad & dirs & pad_was) { if (now >= repeat_at) { act |= pad & dirs; repeat_at = now + 110; } }
        else if (down & dirs) repeat_at = now + 380;
        if (s_quit) {
            if (act & (kLeft | kRight)) { s_quit_sel ^= 1; redraw(); }
            if (act & kCross) quit_choose(s_quit_sel);
            else if (act & kCircle) set_quit(false);
        } else if ((down & kSelect) && !s_open && s_in_options && hint_enabled() && game_fg) set_open(true);
        else if ((down & kPs) && (s_open || game_fg)) set_open(!s_open);
        else if (s_open) {
            if (act & kUp) move_sel(-1);
            if (act & kDown) move_sel(+1);
            if (act & kLeft) activate(-1);
            if (act & kRight) activate(+1);
            if (act & kCross) press();
            if (act & kCircle) set_open(false);
            if (act && s_open) redraw();
        }
        pad_was = pad;
        if (s_release_wait && !s_open && !s_quit && !(pad & 0xFFFFu)) { g_pad_input_blocked = 0; s_release_wait = false; }
        else if (s_open || s_quit) s_release_wait = false;

        /* The title's Options screen: show the tag while nothing else is up. */
        const bool want_hint = s_in_options && !s_open && !s_quit && hint_enabled() && !legacy_ui_flag() &&
                               rsx_d3d12_overlay_available();
        if (want_hint != s_hint_shown) {
            if (want_hint) push_image(kHintW, kHintH, paint_hint, true, 0);
            else if (!s_open && !s_quit) rsx_d3d12_overlay_set(nullptr, 0, 0, 0, 0);
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
