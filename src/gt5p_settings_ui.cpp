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
#include "gt5p_glyphs.h"
#include "gt5p_keymap.h"

extern "C" {
extern volatile int g_pad_input_blocked;        /* cellPad.c */
extern volatile uint32_t g_pad_menu_buttons;    /* cellPad.c: bit 16 = PS button */
extern volatile uint32_t g_pad_inject_buttons;  /* cellPad.c: pressed for the title on port 0 */
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
const uint32_t kSelect = 1u << 0, kStart = 1u << 3, kUp = 1u << 4, kRight = 1u << 5, kDown = 1u << 6, kLeft = 1u << 7,
               kCircle = 1u << 13, kCross = 1u << 14, kPs = 1u << 16,
               kL1 = 1u << 10, kR1 = 1u << 11;

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
    int key = -1;                            /* a keyboard binding: its button (gt5p_keymap.h) */
};

const std::vector<Choice> kOnOff = { {1, L"On"}, {0, L"Off"} };

/* Keyboard bindings: one item per button, the value a virtual-key code. */
template <int N> int key_get(const Gt5pSettings& s) { return s.keys[N]; }
template <int N> void key_set(Gt5pSettings& s, int v) { s.keys[N] = v; }
template <int N> void key_apply(int v) { gt5p_keymap_apply_one(N, v); }
const wchar_t* const kKeyHelp =
    L"Cross or Enter, then press the key for this button. Escape cancels. A key another "
    L"button has moves to it. Used when no controller is connected.";
#define KEY_ITEM(n, label) { L"KEYBOARD", label, kKeyHelp, "PAD_KEYMAP", {}, key_get<n>, key_set<n>, key_apply<n>, n }

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
        { L"SHADERS", L"Shader cache",
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
        { L"SHADERS", L"Background shader compilation",
          L"Build new shaders on background threads, all at once, instead of stopping the "
          L"picture to build them one by one. A new screen shows at once, its last details a "
          L"moment later. Needs the shader cache.",
          "RSX_SHADER_ASYNC", kOnOff,
          [](const Gt5pSettings& s) { return s.shader_precompile ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.shader_precompile = v != 0; }, nullptr },
        { L"SHADERS", L"Preload known shaders",
          L"Prepare learned menu, then race pipelines while the game starts and the movie "
          L"plays. Live draws take priority. First visits still learn. Needs shader cache "
          L"and background pipelines; uses more memory.",
          "RSX_SHADER_WARMUP", kOnOff,
          [](const Gt5pSettings& s) { return s.shader_warmup ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.shader_warmup = v != 0; }, nullptr },
        { L"SHADERS", L"Background pipeline creation",
          L"Build driver pipelines on a background worker to reduce render stalls. "
          L"First-seen details can appear a moment later while preparation finishes.",
          "RSX_PSO_ASYNC", kOnOff,
          [](const Gt5pSettings& s) { return s.pipeline_async ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.pipeline_async = v != 0; }, nullptr },
        { L"SHADERS", L"Prepare race pipelines",
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
          L"Play with the keyboard when no controller is connected. The keys are on the "
          L"Keyboard page (Z Cross, X Circle, Enter Start, arrows ... unless changed there).",
          "PAD_NO_KEYBOARD", kOnOff,
          [](const Gt5pSettings& s) { return s.keyboard ? 1 : 0; },
          [](Gt5pSettings& s, int v) { s.keyboard = v != 0; },
          [](int v) { pad_set_keyboard_enabled(v); } },
        { L"INPUT", L"Button prompts",
          L"The button symbols the game shows. Auto follows the controller in use: Xbox and "
          L"other pads, Switch pads and the keyboard get their own (Kenney's art); a "
          L"PlayStation pad keeps the game's.",
          "GT5P_GLYPHS", { {0, L"Auto"}, {1, L"PlayStation"}, {2, L"Xbox"}, {3, L"Nintendo"}, {4, L"Keyboard"} },
          [](const Gt5pSettings& s) { return s.button_prompts; },
          [](Gt5pSettings& s, int v) { s.button_prompts = v; },
          [](int v) { gt5p_glyphs_set_style(v); } },
        KEY_ITEM(0, L"Cross"),  KEY_ITEM(1, L"Circle"), KEY_ITEM(2, L"Square"), KEY_ITEM(3, L"Triangle"),
        KEY_ITEM(4, L"L1"),     KEY_ITEM(5, L"R1"),     KEY_ITEM(6, L"L2"),     KEY_ITEM(7, L"R2"),
        KEY_ITEM(8, L"L3"), KEY_ITEM(9, L"R3"), KEY_ITEM(10, L"Start"), KEY_ITEM(11, L"Select"),
        KEY_ITEM(12, L"Up"),    KEY_ITEM(13, L"Down"),  KEY_ITEM(14, L"Left"),  KEY_ITEM(15, L"Right"),
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
 * The page is one of the game's settings popups (its "Steering Settings"
 * dialog), and the quit question its "Confirmation" popup: a flat grey-28
 * panel over the dimmed scene, a centred title, rows of a right-aligned label,
 * a black value box with a grey underline and a square drop-down button (red
 * ring on the selected row), dotted rules between rows, and pill buttons
 * between two grey-76 rules. Sections are pages, switched with L1/R1 (Q/W,
 * Page Up/Down) or on the bar under the title. Units are 1280 x 720 (the
 * backbuffer's pixels over 1.5 at 1080p); sizes and greys were measured from
 * the game's screens (Phases 115-116). */
const int kW = 1280, kH = 720;
const int kPx0 = 250, kPx1 = 1030, kPy0 = 84, kPy1 = 640;     /* the panel */
const int kBarY = 124, kBarH = 30, kRule1 = 168;              /* section bar, rule under it */
const int kRowY = 186, kRowH = 54;                            /* first row, pitch */
const int kFieldX = 650, kFieldW = 250, kFieldH = 32, kDropW = 33;
const int kHelpY = 468, kRule2 = 536;
const int kBtnW = 157, kBtnH = 37, kBtnY = 556, kBtnGap = 16;

HWND s_game, s_wnd;
bool s_open;
bool s_overlay;                 /* drawn into the game's picture (this open) */
double s_scale = 1;             /* overlay: backbuffer pixels per layout unit */
int s_ox, s_oy;                 /* overlay: its top left in the backbuffer */
int s_sel;                      /* row: 0 the section bar, then items, then buttons */
int s_section;                  /* the page shown */
bool s_drop;                    /* the selected item's list is open */
int s_drop_sel;                 /* the highlighted choice in it */
Gt5pSettings s_edit;   /* what the page shows and saves */
Gt5pSettings s_boot;   /* the file as this run started with it */
std::wstring s_status;
bool s_quit;                    /* the quit question is up */
int s_quit_sel;                 /* 0 Cancel, 1 OK */
volatile LONG s_quit_req;       /* Escape pressed in the game window */
int s_capture = -1;             /* a key item waiting for its new key */
uint8_t s_cap_was[256];         /* keys held when the wait began */

enum { kRowRestart = -1, kRowClose = -2, kRowHead = -3, kRowDefaults = -4 };
bool is_button(int id) { return id == kRowRestart || id == kRowClose || id == kRowDefaults; }

/* The Keyboard page: sixteen bindings in two columns of eight. */
const int kKeyY = 180, kKeyH = 34, kKeyFieldW = 130;
bool keyboard_page();

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

/* The sections, in the order they first appear in items(). */
const std::vector<const wchar_t*>& sections()
{
    static std::vector<const wchar_t*> v;
    if (v.empty())
        for (const Item& it : items()) {
            bool seen = false;
            for (const wchar_t* s : v) seen |= !wcscmp(s, it.section);
            if (!seen) v.push_back(it.section);
        }
    return v;
}

/* Rows in order: the section bar, this page's items, then the buttons
 * ("Restart" when needed, "Close"). */
std::vector<int> rows()
{
    std::vector<int> r = { kRowHead };
    const wchar_t* sec = sections()[s_section];
    for (int i = 0; i < (int)items().size(); i++) if (!wcscmp(items()[i].section, sec)) r.push_back(i);
    if (restart_pending()) r.push_back(kRowRestart);
    if (keyboard_page()) r.push_back(kRowDefaults);
    r.push_back(kRowClose);
    return r;
}

bool keyboard_page() { return !wcscmp(sections()[s_section], L"KEYBOARD"); }

/* Where each row sits: items down the panel, buttons side by side, centred. */
struct Slot { int x0, x1, y; };
std::vector<Slot> layout(const std::vector<int>& r)
{
    std::vector<Slot> out;
    int nbtn = 0, y = kRowY;
    for (int id : r) nbtn += is_button(id);
    int bx = kW / 2 - (nbtn * kBtnW + (nbtn - 1) * kBtnGap) / 2;
    for (int id : r) {
        if (id == kRowHead) out.push_back({ kPx0 + 40, kPx1 - 40, kBarY });
        else if (id >= 0 && items()[id].key >= 0) {
            const int k = items()[id].key, col = k / 8;
            const int x0 = col ? kW / 2 + 10 : kPx0 + 30;
            out.push_back({ x0, x0 + (kPx1 - kPx0) / 2 - 40, kKeyY + (k % 8) * kKeyH });
        }
        else if (id >= 0) { out.push_back({ kPx0 + 40, kPx1 - 40, y }); y += kRowH; }
        else { out.push_back({ bx, bx + kBtnW, kBtnY }); bx += kBtnW + kBtnGap; }
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
void set_value(int id, int v);

void reset_keys();

void change(int id, int dir)
{
    if (id == kRowClose) { set_open(false); return; }
    if (id == kRowRestart) { relaunch(); return; }
    if (id == kRowDefaults) { reset_keys(); return; }
    const Item& it = items()[id];
    if (it.key >= 0) return;
    const int n = (int)it.choices.size();
    set_value(id, it.choices[(choice_index(it) + dir + n) % n].value);
}

/* Store an item's new value, apply it when it can be live, and say so. */
void set_value(int id, int v)
{
    const Item& it = items()[id];
    it.set(s_edit, v);
    const bool over = gt5p_settings_overridden(it.env);
    if (!gt5p_settings_enabled()) s_status = L"GT5P_NO_SETTINGS is set: changes are not saved.";
    else if (!gt5p_settings_store(s_edit)) s_status = L"Could not write " + widen(gt5p_settings_path());
    else s_status = L"Saved.";
    if (over) s_status += L"  " + widen(it.env) + L" is set in the environment and wins over this.";
    else if (it.apply) { it.apply(v); s_status += L"  Applied."; }
    else if (it.get(s_edit) != it.get(s_boot)) s_status += L"  Takes effect after a restart.";
}

/* The item for button `k`'s binding. */
int key_item(int k)
{
    for (int i = 0; i < (int)items().size(); i++) if (items()[i].key == k) return i;
    return -1;
}

/* Bind button k to vk; a button that had vk gets k's old key. */
void assign_key(int k, int vk)
{
    const int old = s_edit.keys[k];
    std::wstring moved;
    for (int j = 0; j < GT5P_KEY_BUTTONS; j++)
        if (j != k && vk && gt5p_key_normalize(s_edit.keys[j]) == gt5p_key_normalize(vk)) {
            set_value(key_item(j), old);
            moved = widen(gt5p_key_name(vk)) + L" moved from " + gt5p_key_button(j).label + L"; " +
                    gt5p_key_button(j).label + L" is now " + widen(gt5p_key_name(old) ? gt5p_key_name(old) : "None") + L".  ";
        }
    set_value(key_item(k), vk);
    if (!moved.empty()) s_status = moved + s_status;
}

void reset_keys()
{
    for (int k = 0; k < GT5P_KEY_BUTTONS; k++) set_value(key_item(k), gt5p_key_button(k).default_vk);
    s_status = L"Default keys.  " + s_status;
}

/* The key-wait's result: a key, Escape to cancel, or a key the port keeps. */
void capture_key(int vk)
{
    if (s_capture < 0) return;
    if (vk == VK_ESCAPE) { s_capture = -1; s_status = L"Not changed."; return; }
    vk = gt5p_key_normalize(vk);
    if (!gt5p_key_name(vk)) { s_status = L"That key cannot be bound (Escape and F1-F12 belong to the port)."; return; }
    const int k = items()[s_capture].key;
    s_capture = -1;
    assign_key(k, vk);
}

void begin_capture(int id)
{
    s_capture = id;
    for (int vk = 0; vk < 256; vk++) s_cap_was[vk] = (GetAsyncKeyState(vk) & 0x8000) != 0;
    s_status = L"";
}

/* ---- drawing ---- */

/* The clear parts of a popup or tag; push_image paints them black, then white. */
COLORREF kKey = RGB(255, 0, 255);
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

/* A triangle shaded between grey values at its corners, rasterised in device
 * pixels with 4x4 coverage at its edges, blended over what is there. */
void shaded_tri(HDC dc, const double (&p)[3][2], const int (&g)[3])
{
    DeviceSpace ds(dc);
    const double s = s_paint_scale;
    double X[3], Y[3];
    for (int k = 0; k < 3; k++) { X[k] = p[k][0] * s; Y[k] = p[k][1] * s; }
    const double area = (X[1] - X[0]) * (Y[2] - Y[0]) - (X[2] - X[0]) * (Y[1] - Y[0]);
    if (fabs(area) < 1e-6) return;
    auto bary = [&](double x, double y, double* w) {
        w[0] = ((X[1] - x) * (Y[2] - y) - (X[2] - x) * (Y[1] - y)) / area;
        w[1] = ((X[2] - x) * (Y[0] - y) - (X[0] - x) * (Y[2] - y)) / area;
        w[2] = 1 - w[0] - w[1];
    };
    const int x0 = (int)floor(fmin(X[0], fmin(X[1], X[2]))), x1 = (int)ceil(fmax(X[0], fmax(X[1], X[2])));
    const int y0 = (int)floor(fmin(Y[0], fmin(Y[1], Y[2]))), y1 = (int)ceil(fmax(Y[0], fmax(Y[1], Y[2])));
    for (int y = y0; y < y1; y++)
        for (int x = x0; x < x1; x++) {
            int in = 0;
            double w[3];
            for (int sy = 0; sy < 4; sy++)
                for (int sx = 0; sx < 4; sx++) {
                    bary(x + (sx + 0.5) / 4, y + (sy + 0.5) / 4, w);
                    in += w[0] >= 0 && w[1] >= 0 && w[2] >= 0;
                }
            if (!in) continue;
            bary(x + 0.5, y + 0.5, w);
            for (double& v : w) v = v < 0 ? 0 : v;
            const double sum = w[0] + w[1] + w[2];
            const int v = (int)((w[0] * g[0] + w[1] * g[1] + w[2] * g[2]) / sum + 0.5);
            const double a = in / 16.0;
            const COLORREF old = GetPixel(dc, x, y);
            auto mix = [&](int o) { return (int)(o * (1 - a) + v * a + 0.5); };
            SetPixelV(dc, x, y, RGB(mix(GetRValue(old)), mix(GetGValue(old)), mix(GetBValue(old))));
        }
}

/* The game's arrow cursor (from the user's screenshot of it, ~28 x 42 pixels
 * at 1080p): a bevelled arrowhead with a tail on its left, tip at (x, y). Its
 * left face is dark with a lighter rim, its right face bright at the tip and
 * greying towards the notch, all inside a thin grey outline. */
void cursor(HDC dc, int x, int y)
{
    /* Tip, end of the left tail, the notch, the right wing. */
    const double T[2] = { x + 0.0, y + 0.0 }, A[2] = { x + 1.3, y + 28.0 },
                 N[2] = { x + 6.2, y + 20.4 }, R[2] = { x + 18.7, y + 20.6 };
    /* The outline: the same shape grown about its middle. */
    const double cx = x + 6.5, cy = y + 17.0;
    auto grow = [&](const double (&q)[2], double k, double* o) { o[0] = cx + (q[0] - cx) * k; o[1] = cy + (q[1] - cy) * k; };
    double t[2], a[2], n[2], r[2];
    /* A black edge outside the outline, so it reads over light lists. */
    grow(T, 1.17, t); grow(A, 1.17, a); grow(N, 1.17, n); grow(R, 1.17, r);
    t[1] -= 1.2;
    shaded_tri(dc, { { t[0], t[1] }, { a[0], a[1] }, { n[0], n[1] } }, { 0, 0, 0 });
    shaded_tri(dc, { { t[0], t[1] }, { n[0], n[1] }, { r[0], r[1] } }, { 0, 0, 0 });
    grow(T, 1.09, t); grow(A, 1.09, a); grow(N, 1.09, n); grow(R, 1.09, r);
    t[1] -= 0.6;
    shaded_tri(dc, { { t[0], t[1] }, { a[0], a[1] }, { n[0], n[1] } }, { 140, 140, 120 });
    shaded_tri(dc, { { t[0], t[1] }, { n[0], n[1] }, { r[0], r[1] } }, { 160, 120, 150 });
    shaded_tri(dc, { { T[0], T[1] }, { A[0], A[1] }, { N[0], N[1] } }, { 70, 115, 4 });       /* left face */
    shaded_tri(dc, { { T[0], T[1] }, { N[0], N[1] }, { R[0], R[1] } }, { 252, 90, 205 });     /* right face */
}

/* Text centred in a box, both ways (the button labels). */
void text_in(HDC dc, HFONT f, int x0, int y0, int x1, int y1, COLORREF c, const wchar_t* s, UINT fmt = DT_CENTER)
{
    HGDIOBJ o = SelectObject(dc, f);
    SetTextColor(dc, c); SetTextAlign(dc, TA_LEFT | TA_TOP);
    RECT r = { x0, y0, x1, y1 };
    DrawTextW(dc, s, -1, &r, fmt | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
    SelectObject(dc, o);
}

/* A pill button with its label. */
void button(HDC dc, int x0, int y, const wchar_t* label, bool focused)
{
    static HFONT f = font(21, FW_NORMAL);
    pill(dc, x0, y, x0 + kBtnW, y + kBtnH, focused);
    text_in(dc, f, x0, y, x0 + kBtnW, y + kBtnH - 2, grey(232), label);
}

/* The popup's frame: the scene dimmed around it (key colour), a black edge,
 * flat grey 28, and the dark header gradient at its top. */
void panel(HDC dc, int x0, int y0, int x1, int y1)
{
    fill(dc, 0, 0, kW, kH, kKey);
    fill(dc, x0 - 1, y0 - 1, x1 + 1, y1 + 1, grey(0));
    fill(dc, x0, y0, x1, y1, grey(28));
    vgrad(dc, x0, y0, x1, y0 + 26, [](double t) {
        return t < 0.04 ? RGB(45, 45, 48) : t < 0.1 ? grey(27) : t < 0.3 ? grey(lerp(9, 4, (t - 0.1) / 0.2))
                                                                          : grey(lerp(4, 28, (t - 0.3) / 0.7)); });
}

/* A section bar like the Options screen's "General", with the L1 and R1
 * knobs that switch pages; red rules when it is the selected row. */
void section_bar(HDC dc, int x0, int x1, int y, const wchar_t* title, bool sel)
{
    static HFONT f = font(19, FW_SEMIBOLD), fk = font(9, FW_BOLD);
    fill(dc, x0, y, x1, y + 1, sel ? RGB(168, 0, 0) : grey(70));
    vgrad(dc, x0, y + 1, x1, y + kBarH - 1, [](double t) { return grey(lerp(3, 34, t)); });
    fill(dc, x0, y + kBarH - 1, x1, y + kBarH, sel ? RGB(168, 0, 0) : grey(70));
    for (int k = 0; k < 2; k++) {
        const int cx = k ? x1 - 22 : x0 + 22, cy = y + kBarH / 2;
        stadium(dc, cx - 10, cy - 10, cx + 10, cy + 10, [](double t) { return grey(lerp(80, 18, t)); });
        stadium(dc, cx - 8.5, cy - 8.5, cx + 8.5, cy + 8.5, [](double t) { return grey(lerp(14, 44, t)); });
        text_in(dc, fk, cx - 10, cy - 10, cx + 10, cy + 10, grey(170), k ? L"R1" : L"L1");
    }
    std::wstring s = title;
    for (size_t i = 1; i < s.size(); i++) s[i] = (wchar_t)towlower(s[i]);   /* VIDEO -> Video */
    text_in(dc, f, x0, y, x1, y + kBarH - 1, grey(180), s.c_str());
}

/* The square drop-down button: black edge (red ring, selected), glass face,
 * white triangle. */
void drop_button(HDC dc, int x, int y, bool sel)
{
    const int s = kDropW;
    fill(dc, x, y, x + s, y + s, sel ? grey(66) : grey(5));
    fill(dc, x + 1, y + 1, x + s - 1, y + s - 1, sel ? RGB(168, 0, 0) : grey(0));
    vgrad(dc, x + 3, y + 3, x + s - 3, y + s - 3, [](double t) {
        if (t < 0.5) { const double u = t / 0.5; return RGB(lerp(123, 74, u), lerp(121, 73, u), lerp(132, 74, u)); }
        const double u = (t - 0.5) / 0.5;
        return grey(u < 0.6 ? lerp(10, 3, u / 0.6) : lerp(3, 38, (u - 0.6) / 0.4)); });
    POINT tri[] = { {x + s / 2 - 7, y + s / 2 - 3}, {x + s / 2 + 7, y + s / 2 - 3}, {x + s / 2, y + s / 2 + 5} };
    HBRUSH b = CreateSolidBrush(grey(231)); HPEN p = CreatePen(PS_SOLID, 1, grey(231));
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, p);
    Polygon(dc, tri, 3);
    SelectObject(dc, ob); SelectObject(dc, op); DeleteObject(b); DeleteObject(p);
}

/* The open list, over the rows: light grey entries, the highlighted one a
 * pale blue gradient, a dash before the current value. Placed so the
 * current value sits on the value box. */
const int kDropItemH = 38;
int drop_top(int row_y, int cur, int n)
{
    int y = row_y - 3 - cur * kDropItemH;
    if (y + n * kDropItemH > kRule2) y = kRule2 - n * kDropItemH;
    if (y < kRule1) y = kRule1;
    return y;
}
void drop_list(HDC dc, const Item& it, int row_y)
{
    static HFONT f = font(19, FW_NORMAL);
    const int n = (int)it.choices.size(), cur = choice_index(it);
    const int y0 = drop_top(row_y, cur, n);
    const int x0 = kFieldX, x1 = kFieldX + kFieldW;
    fill(dc, x0 + 3, y0 + 3, x1 + 3, y0 + n * kDropItemH + 3, grey(14));   /* shadow */
    for (int i = 0; i < n; i++) {
        const int y = y0 + i * kDropItemH;
        if (i == s_drop_sel)
            vgrad(dc, x0, y, x1, y + kDropItemH, [](double t) {
                return RGB(lerp(154, 222, t), lerp(181, 244, t), lerp(206, 250, t)); });
        else fill(dc, x0, y, x1, y + kDropItemH, grey(204));
        fill(dc, x0, y + kDropItemH - 1, x1, y + kDropItemH, grey(127));
        if (i == cur) fill(dc, x0 + 13, y + kDropItemH / 2, x0 + 20, y + kDropItemH / 2 + 2, grey(115));
        text_in(dc, f, x0 + 30, y, x1 - 8, y + kDropItemH - 2, grey(51), it.choices[i].label, DT_LEFT);
    }
}

/* The page: one of the game's settings popups. */
void paint(HDC dc)
{
    static HFONT fTitle = font(22, FW_NORMAL), fRow = font(19, FW_NORMAL), fTag = font(12, FW_SEMIBOLD),
                 fHelp = font(15, FW_NORMAL), fStatus = font(13, FW_NORMAL);
    SetBkMode(dc, TRANSPARENT);
    panel(dc, kPx0, kPy0, kPx1, kPy1);
    text_in(dc, fTitle, kPx0, kPy0 + 4, kPx1, kPy0 + 34, grey(178), L"PC Settings");

    const std::vector<int> r = rows();
    const std::vector<Slot> sl = layout(r);
    if (s_sel >= (int)r.size()) s_sel = (int)r.size() - 1;
    fill(dc, kPx0, kRule1, kPx1, kRule1 + 1, grey(76));
    fill(dc, kPx0, kRule2, kPx1, kRule2 + 1, grey(76));
    int drop_row = -1;
    for (size_t i = 0; i < r.size(); i++) {
        const int id = r[i], y = sl[i].y;
        const bool sel = (int)i == s_sel;
        if (id == kRowHead) { section_bar(dc, sl[i].x0, sl[i].x1, y, sections()[s_section], sel); continue; }
        if (id < 0) {
            button(dc, sl[i].x0, y, id == kRowRestart ? L"Restart" : id == kRowDefaults ? L"Defaults" : L"Close", sel);
            if (sel) cursor(dc, sl[i].x0 + kBtnW / 2 + 2, y + 18);
            continue;
        }
        const Item& it = items()[id];
        const bool over = gt5p_settings_overridden(it.env);
        if (it.key >= 0) {
            /* A binding: the button's name, then its key in a box. */
            const int x0 = sl[i].x0, fx = x0 + 160;
            text_in(dc, fRow, x0, y, fx - 16, y + kKeyH - 6, over ? grey(100) : grey(190), it.label, DT_RIGHT);
            fill(dc, fx - 1, y - 1, fx + kKeyFieldW + 1, y + kKeyH - 5, sel ? RGB(168, 0, 0) : grey(5));
            fill(dc, fx, y, fx + kKeyFieldW, y + kKeyH - 6, RGB(0, 4, 0));
            const char* kn = gt5p_key_name(it.get(s_edit));
            const std::wstring v = s_capture == id ? L"Press a key" : kn ? widen(kn) : L"?";
            text_in(dc, fRow, fx + 12, y, fx + kKeyFieldW - 6, y + kKeyH - 7,
                    s_capture == id ? RGB(237, 60, 60) : over ? grey(100) : grey(204), v.c_str(), DT_LEFT);
            if (sel && s_capture != id) cursor(dc, fx + kKeyFieldW - 18, y + 8);
            continue;
        }
        const bool later = !it.apply && !over && it.get(s_edit) != it.get(s_boot);
        /* A dotted rule under every row but the last. */
        if (i + 1 < r.size() && r[i + 1] >= 0)
            for (int x = kPx0 + 26; x < kPx1 - 26; x += 7)
                fill(dc, x, y + kFieldH + 11, x + 2, y + kFieldH + 12, grey(96));
        text_in(dc, fRow, kPx0 + 20, y, kFieldX - 24, y + kFieldH - 2, over ? grey(100) : grey(190), it.label, DT_RIGHT);
        fill(dc, kFieldX, y, kFieldX + kFieldW, y + kFieldH, RGB(0, 4, 0));
        fill(dc, kFieldX, y + kFieldH - 1, kFieldX + kFieldW, y + kFieldH, RGB(99, 101, 107));
        text_in(dc, fRow, kFieldX + 14, y, kFieldX + kFieldW - 8, y + kFieldH - 2, over ? grey(100) : grey(204),
                it.choices[choice_index(it)].label, DT_LEFT);
        /* Notes sit in the row's empty left side. */
        if (later)
            text_in(dc, fTag, kPx0 + 30, y, kFieldX, y + kFieldH - 2, RGB(237, 60, 60), L"after restart", DT_LEFT);
        else if (over)
            text_in(dc, fTag, kPx0 + 30, y, kFieldX, y + kFieldH - 2, grey(110),
                    (L"set by " + widen(it.env)).c_str(), DT_LEFT);
        drop_button(dc, kFieldX + kFieldW + 12, y, sel);
        if (sel && !s_drop) cursor(dc, kFieldX + kFieldW + 12 + kDropW / 2 + 1, y + kDropW / 2 + 2);
        if (sel && s_drop) drop_row = (int)i;
    }

    /* The selected item's help. */
    if (s_sel >= 0 && s_sel < (int)r.size() && r[s_sel] >= 0) {
        RECT rc = { kPx0 + 40, kHelpY, kPx1 - 40, kRule2 - 6 };
        HGDIOBJ o = SelectObject(dc, fHelp);
        SetTextColor(dc, grey(150)); SetTextAlign(dc, TA_LEFT | TA_TOP);
        std::wstring help = items()[r[s_sel]].help;
        if (s_capture >= 0)
            help = std::wstring(L"Press the key for ") + items()[s_capture].label +
                   L". Escape (or Circle) cancels.";
        DrawTextW(dc, help.c_str(), -1, &rc, DT_WORDBREAK | DT_NOPREFIX | DT_CENTER);
        SelectObject(dc, o);
    } else if (s_sel == 0) {
        text_in(dc, fHelp, kPx0, kHelpY, kPx1, kHelpY + 24, grey(150), L"L1 / R1, or Left / Right here: the other settings pages");
    }
    if (!s_status.empty()) text_in(dc, fStatus, kPx0, kBtnY + kBtnH + 4, kPx1, kPy1 - 2, grey(130), s_status.c_str());
    if (drop_row >= 0) {
        const Item& it = items()[r[drop_row]];
        drop_list(dc, it, sl[drop_row].y);
        const int y0 = drop_top(sl[drop_row].y, choice_index(it), (int)it.choices.size());
        cursor(dc, kFieldX + kFieldW - 70, y0 + s_drop_sel * kDropItemH + 18);
    }
}

/* The quit question, a copy of the game's "Confirmation" popup. */
const int kQx0 = 360, kQx1 = 920, kQy0 = 175, kQy1 = 547, kQbtnY = 480;
const int kQbtnX[2] = { 475, 648 };
void paint_quit(HDC dc)
{
    static HFONT fTitle = font(22, FW_NORMAL), fMsg = font(22, FW_NORMAL);
    SetBkMode(dc, TRANSPARENT);
    panel(dc, kQx0, kQy0, kQx1, kQy1);
    text_in(dc, fTitle, kQx0, kQy0 + 4, kQx1, kQy0 + 34, grey(178), L"Confirmation");
    text_in(dc, fMsg, kQx0, 300, kQx1, 342, grey(236), L"Quit Gran Turismo 5 Prologue?");
    fill(dc, kQx0, 448, kQx1, 449, grey(76));
    button(dc, kQbtnX[0], kQbtnY, L"Cancel", s_quit_sel == 0);
    button(dc, kQbtnX[1], kQbtnY, L"OK", s_quit_sel == 1);
    cursor(dc, kQbtnX[s_quit_sel] + kBtnW / 2 + 2, kQbtnY + 18);
}

void activate(int dir);
void press();
void switch_section(int dir);
void drop_pick();

/* A click at layout position (mx, my). With the list open: pick the entry
 * under it, or close the list. Otherwise: the section bar's knobs switch
 * pages, a value box or drop-down button opens its list, a button presses. */
void click(int mx, int my)
{
    const std::vector<int> r = rows();
    const std::vector<Slot> sl = layout(r);
    if (s_drop) {
        if (s_sel >= 0 && s_sel < (int)r.size() && r[s_sel] >= 0) {
            const Item& it = items()[r[s_sel]];
            const int n = (int)it.choices.size(), y0 = drop_top(sl[s_sel].y, choice_index(it), n);
            if (mx >= kFieldX && mx < kFieldX + kFieldW && my >= y0 && my < y0 + n * kDropItemH) {
                s_drop_sel = (my - y0) / kDropItemH;
                drop_pick();
                return;
            }
        }
        s_drop = false;
        return;
    }
    for (size_t i = 0; i < r.size(); i++) {
        const int id = r[i], y = sl[i].y;
        if (id == kRowHead) {
            if (my >= y && my < y + kBarH && mx >= sl[i].x0 && mx < sl[i].x1) {
                s_sel = 0;
                if (mx < sl[i].x0 + 60) switch_section(-1);
                else if (mx >= sl[i].x1 - 60) switch_section(+1);
                return;
            }
        } else if (id < 0) {
            if (my >= y && my < y + kBtnH && mx >= sl[i].x0 && mx < sl[i].x1) { s_sel = (int)i; press(); return; }
        } else if (items()[id].key >= 0) {
            if (my >= y && my < y + kKeyH - 4 && mx >= sl[i].x0 && mx < sl[i].x1) { s_sel = (int)i; press(); return; }
        } else if (my >= y && my < y + kFieldH && mx >= kPx0 && mx < kFieldX + kFieldW + 12 + kDropW) {
            s_sel = (int)i;
            if (mx >= kFieldX) press();
            return;
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

/* GT5P_SETTINGS_UI_ALPHA: how far the scene around the popups is dimmed,
 * 0-255 (default 186: the game's own popups leave it at about 27%). */
int dim_alpha()
{
    static int a = -1;
    if (a < 0) { const char* e = getenv("GT5P_SETTINGS_UI_ALPHA"); a = e ? atoi(e) & 255 : 186; }
    return a;
}

void render_overlay()
{
    if (s_quit) push_image(kW, kH, paint_quit, false, dim_alpha());
    else if (s_open && s_overlay) push_image(kW, kH, paint, false, dim_alpha());
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
volatile int s_in_race;        /* a race is loaded (RaceRoot until another screen) */
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
    /* A race reads RaceRoot with its layers (OnboardMeterRoot, the mode's
     * QuickArcadeRoot, DLSGadgetRoot); any other screen root ends it. A mode
     * whose race root is not listed just never counts as racing. */
    if (!strcmp(b, "RaceRoot.gpb")) s_in_race = 1;
    else if (strcmp(b, "DLSGadgetRoot.gpb") && strcmp(b, "OnboardMeterRoot.gpb") &&
             strcmp(b, "QuickArcadeRoot.gpb") &&
             (strstr(b, "Root.gpb") || strstr(b, "Template.gpb"))) s_in_race = 0;
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

/* ---- memory snapshots (a diagnostic) ----
 *
 * GT5P_MEMSNAP=<milestone>+<ms>[,...]: save every committed page of guest
 * memory once at each of those times, and on F9 over the game, to
 * scratch/memsnap/snapNN.bin as records of [u32 guest address, u32 length,
 * bytes]. Comparing snapshots taken in two states (paused and running, say)
 * finds the variable that tells them apart (scripts/diag/memsnap_diff.py).
 * The files hold game memory: they stay in the gitignored scratch folder. */
extern "C" uint8_t* vm_base;
extern "C" long long pad_milestone_age_ms(const char* name);

void memsnap_write()
{
    static int n = 0;
    CreateDirectoryA("scratch", NULL);
    CreateDirectoryA("scratch\\memsnap", NULL);
    char path[96];
    snprintf(path, sizeof path, "scratch\\memsnap\\snap%02d.bin", n++);
    FILE* f = fopen(path, "wb");
    if (!f || !vm_base) { if (f) fclose(f); return; }
    unsigned long long total = 0;
    for (unsigned long long a = 0; a < 0x100000000ull;) {
        MEMORY_BASIC_INFORMATION mi;
        if (!VirtualQuery(vm_base + a, &mi, sizeof mi)) break;
        const unsigned long long end = (unsigned long long)((uint8_t*)mi.BaseAddress + mi.RegionSize - vm_base);
        if (mi.State == MEM_COMMIT && !(mi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) {
            for (unsigned long long p = a; p < end && p < 0x100000000ull; p += 0x1000000) {
                const uint32_t len = (uint32_t)((end - p) < 0x1000000 ? (end - p) : 0x1000000);
                const uint32_t ga = (uint32_t)p;
                fwrite(&ga, 4, 1, f); fwrite(&len, 4, 1, f); fwrite(vm_base + p, 1, len, f);
                total += len;
            }
        }
        a = end;
    }
    fclose(f);
    fprintf(stderr, "[memsnap] %s: %llu MB at %llu ms\n", path, total >> 20, GetTickCount64());
}

void memsnap_poll()
{
    static int on = -1;
    static std::vector<std::pair<std::string, long long>> at;
    static std::vector<bool> done;
    static bool f9_was;
    if (on < 0) {
        const char* e = getenv("GT5P_MEMSNAP");
        on = e && *e;
        if (on) {
            std::string s = e;
            size_t i = 0;
            while (i < s.size()) {
                size_t j = s.find(',', i); if (j == std::string::npos) j = s.size();
                std::string tok = s.substr(i, j - i);
                size_t plus = tok.find('+');
                if (plus != std::string::npos) at.push_back({ tok.substr(0, plus), atoll(tok.c_str() + plus + 1) });
                i = j + 1;
            }
            done.assign(at.size(), false);
        }
    }
    if (!on) return;
    for (size_t k = 0; k < at.size(); k++)
        if (!done[k] && pad_milestone_age_ms(at[k].first.c_str()) >= at[k].second) { done[k] = true; memsnap_write(); }
    const bool f9 = (GetAsyncKeyState(VK_F9) & 0x8000) != 0;
    if (f9 && !f9_was && GetForegroundWindow() == s_game) memsnap_write();
    f9_was = f9;
}

/* GT5P_SETTINGS_TOGGLE_AT=<milestone>+<ms>[,...]: open or close the page at
 * those times, for scripted runs (F1 and the PS button cannot be scripted). */
void set_open(bool open);
void toggle_poll()
{
    static int on = -1;
    static std::vector<std::pair<std::string, long long>> at;
    static std::vector<bool> done;
    if (on < 0) {
        const char* e = getenv("GT5P_SETTINGS_TOGGLE_AT");
        on = e && *e;
        for (std::string sv = on ? e : ""; !sv.empty();) {
            size_t j = sv.find(','); std::string tok = sv.substr(0, j);
            size_t plus = tok.find('+');
            if (plus != std::string::npos) at.push_back({ tok.substr(0, plus), atoll(tok.c_str() + plus + 1) });
            sv = j == std::string::npos ? "" : sv.substr(j + 1);
        }
        done.assign(at.size(), false);
    }
    if (!on) return;
    for (size_t k = 0; k < at.size(); k++)
        if (!done[k] && pad_milestone_age_ms(at[k].first.c_str()) >= at[k].second) { done[k] = true; set_open(!s_open); }
}

/* GT5P_WATCH=addr[,addr...]: print each guest word there whenever it
 * changes (checked every UI tick, ~16 ms), to confirm a candidate found by
 * memsnap_diff.py. addr>off follows a pointer: the word at (word at addr)+off. */
uint32_t guest_word(uint32_t a)
{
    uint32_t w;
    memcpy(&w, vm_base + a, 4);
    return _byteswap_ulong(w);
}

void watch_poll()
{
    static int on = -1;
    /* addr>off: the word at (the word at addr) + off, when that is mapped. */
    static std::vector<uint32_t> addr, offs, last;
    static std::vector<bool> deref;
    if (on < 0) {
        const char* e = getenv("GT5P_WATCH");
        on = e && *e && vm_base;
        for (const char* p = e; on && p && *p;) {
            char* q = nullptr;
            addr.push_back((uint32_t)strtoul(p, &q, 16));
            deref.push_back(q && *q == '>');
            offs.push_back(q && *q == '>' ? (uint32_t)strtoul(q + 1, nullptr, 16) : 0);
            last.push_back(0xDEADBEEF);
            p = strchr(p, ','); if (p) p++;
        }
    }
    if (!on) return;
    for (size_t k = 0; k < addr.size(); k++) {
        uint32_t a = addr[k];
        if (deref[k]) {
            const uint32_t b = guest_word(a);
            if (!b || b >= 0xF0000000u) continue;
            a = b + offs[k];
        }
        const uint32_t v = guest_word(a);
        if (v != last[k]) {
            if (deref[k]) fprintf(stderr, "[watch] %llu ms %08X>%X (%08X) = %08X\n", GetTickCount64(), addr[k], offs[k], a, v);
            else fprintf(stderr, "[watch] %llu ms %08X = %08X\n", GetTickCount64(), addr[k], v);
            last[k] = v;
        }
    }
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

/* ---- pausing a race (Phase 117) ----
 *
 * Opening the page during a race first presses Start for the title, which
 * pauses it and shows its pause bar. Start toggles, so not when the title is
 * already in a menu: the pause bar and the starting grid's menu are mListBox
 * widgets whose word at +4 (past the vtable) is 3, and whose word at +8 is 7
 * while shown, 3 while hidden (measured with GT5P_MEMSNAP and
 * scripts/diag/memsnap_diff.py; the vtable is menu_listbox_vtable in
 * config/targets.json). They live on the heap, so the page scans guest
 * memory for them when it opens (tens of milliseconds).
 * GT5P_SETTINGS_PAUSE=0: never press Start. */
enum { kRaceUnknown = -1, kRaceRunning = 0, kRaceInMenu = 1 };
int race_menu_state()
{
    static uint32_t vt = 1;
    if (vt == 1) { const char* e = getenv("GT5P_LISTBOX_VTABLE"); vt = e ? (uint32_t)strtoul(e, nullptr, 16) : 0; }
    if (!vt || !vm_base) return kRaceUnknown;
    int hidden = 0, shown = 0;
    for (unsigned long long a = 0x20000000ull; a < 0x40000000ull;) {
        MEMORY_BASIC_INFORMATION mi;
        if (!VirtualQuery(vm_base + a, &mi, sizeof mi)) break;
        const unsigned long long end = (unsigned long long)((uint8_t*)mi.BaseAddress + mi.RegionSize - vm_base);
        if (mi.State == MEM_COMMIT && !(mi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) {
            const uint32_t want = _byteswap_ulong(vt);
            const uint32_t* w = (const uint32_t*)(vm_base + a);
            const size_t n = (size_t)((end - a) / 4);
            for (size_t i = 0; i + 2 < n; i++)
                if (w[i] == want && _byteswap_ulong(w[i + 1]) == 3) {
                    const uint32_t st = _byteswap_ulong(w[i + 2]);
                    shown += st == 7; hidden += st == 3;
                }
        }
        a = end;
    }
    if (s_dbg_screens > 0) fprintf(stderr, "[settings-ui] race menus: %d shown, %d hidden%c", shown, hidden, 10);
    return shown ? kRaceInMenu : hidden ? kRaceRunning : kRaceUnknown;
}

ULONGLONG s_inject_until;      /* press Start for the title until then */

void pause_race_if_running()
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("GT5P_SETTINGS_PAUSE"); on = !(e && e[0] == '0'); }
    if (!on || !s_in_race) return;
    if (race_menu_state() != kRaceRunning) return;
    s_inject_until = GetTickCount64() + 150;
    g_pad_inject_buttons = kStart;
    if (s_dbg_screens > 0) fprintf(stderr, "[settings-ui] race running: Start pressed to pause it%c", 10);
}

void set_open(bool open)
{
    if (open == s_open) return;
    s_open = open;
    s_hint_shown = false;   /* the page's image replaces the tag, and closing clears both */
    /* Closing keeps the title's pads at rest until every button is let go
     * (the loop below): the Circle or Cross that closed the page must not
     * reach the game as a new press. */
    if (open) { pause_race_if_running(); g_pad_input_blocked = 1; }
    else s_release_wait = true;
    if (open) {
        s_edit = gt5p_settings_file();
        s_sel = 1;          /* the page's first item */
        s_drop = false;
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

/* The first button's row (the buttons are last). */
int first_button(const std::vector<int>& r)
{
    int nb = 0;
    for (int id : r) nb += is_button(id);
    return (int)r.size() - nb;
}

/* Up/Down through the rows: the section bar, the items, the buttons as one
 * stop. From a button Down wraps to the bar and Up returns to the last item.
 * With the list open, through its entries. */
void move_sel(int d)
{
    if (s_drop) {
        const std::vector<int> r = rows();
        const int n = (int)items()[r[s_sel]].choices.size();
        s_drop_sel = (s_drop_sel + d + n) % n;
        return;
    }
    const std::vector<int> r = rows();
    const int n = (int)r.size(), fb = first_button(r);
    if (s_sel >= fb) s_sel = d > 0 ? 0 : fb - 1;
    else s_sel = (s_sel + d + n) % n;
    if (s_sel > fb) s_sel = fb;
}

/* L1/R1: the previous or next page. */
void switch_section(int dir)
{
    const int n = (int)sections().size();
    s_section = (s_section + dir + n) % n;
    s_drop = false;
    s_capture = -1;
    if (s_sel != 0) s_sel = 1;
}

/* Left/Right: on the bar, switch pages; on an item, step its value; between
 * the buttons, move. Nothing while the list is open. */
void activate(int dir)
{
    if (s_drop) return;
    const std::vector<int> r = rows();
    if (s_sel < 0 || s_sel >= (int)r.size()) return;
    if (r[s_sel] == kRowHead) { switch_section(dir); return; }
    if (r[s_sel] >= 0 && items()[r[s_sel]].key >= 0) {   /* the other column, same line */
        const int other = key_item((items()[r[s_sel]].key + 8) % 16);
        for (int i = 0; i < (int)r.size(); i++) if (r[i] == other) s_sel = i;
        return;
    }
    if (r[s_sel] >= 0) { change(r[s_sel], dir); return; }
    const int fb = first_button(r), nb = (int)r.size() - fb;
    s_sel = fb + ((s_sel - fb + dir + nb) % nb);
}

/* The highlighted list entry becomes the value. */
void drop_pick()
{
    const std::vector<int> r = rows();
    s_drop = false;
    if (s_sel < 0 || s_sel >= (int)r.size() || r[s_sel] < 0) return;
    const Item& it = items()[r[s_sel]];
    if (s_drop_sel >= 0 && s_drop_sel < (int)it.choices.size() && s_drop_sel != choice_index(it))
        set_value(r[s_sel], it.choices[s_drop_sel].value);
}

/* Cross/Enter: on an item, open its list (or, open, pick); on the bar, the
 * next page; on a button, press it. */
void press()
{
    if (s_drop) { drop_pick(); return; }
    const std::vector<int> r = rows();
    if (s_sel < 0 || s_sel >= (int)r.size()) return;
    if (r[s_sel] == kRowHead) { switch_section(+1); return; }
    if (r[s_sel] >= 0 && items()[r[s_sel]].key >= 0) { begin_capture(r[s_sel]); return; }
    if (r[s_sel] >= 0) { s_drop = true; s_drop_sel = choice_index(items()[r[s_sel]]); return; }
    change(r[s_sel], +1);
}

/* Circle/Escape: close the list if it is open, else the page. */
void back()
{
    if (s_capture >= 0) { s_capture = -1; s_status = L"Not changed."; }
    else if (s_drop) s_drop = false;
    else set_open(false);
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
        kKey = RGB(0, 0, 0);   /* the window has no scene behind it */
        paint(mem);
        kKey = RGB(255, 0, 255);
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
        if (s_capture >= 0) { capture_key((int)w); redraw(); return 0; }
        switch (w) {
        case VK_UP:    move_sel(-1); break;
        case VK_DOWN:  move_sel(+1); break;
        case VK_LEFT:  activate(-1); break;
        case VK_RIGHT: activate(+1); break;
        case VK_RETURN: case VK_SPACE: press(); break;
        case VK_PRIOR: switch_section(-1); break;
        case VK_NEXT:  switch_section(+1); break;
        case VK_ESCAPE: case VK_BACK: back(); break;
        case VK_F1: set_open(false); break;
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
                                    VK_ESCAPE, VK_BACK, VK_LBUTTON, VK_PRIOR, VK_NEXT, 'Q', 'W' };
        static uint8_t key_was[256];
        static ULONGLONG key_repeat_at;
        const bool modal = s_quit || (s_open && s_overlay);
        if (modal && !modal_was)
            for (int vk : keys) key_was[vk] = (GetAsyncKeyState(vk) & 0x8000) != 0;
        modal_was = modal;
        /* Waiting for a binding's key: every key, its first new press. */
        if (s_capture >= 0 && s_open && s_overlay && game_fg) {
            for (int vk = 8; vk < 256; vk++) {
                const bool held = (GetAsyncKeyState(vk) & 0x8000) != 0;
                const bool hit = held && !s_cap_was[vk];
                s_cap_was[vk] = held;
                if (hit && s_capture >= 0) { capture_key(vk); redraw(); }
            }
            if (s_capture < 0)   /* the key that ended the wait is not a page press */
                for (int vk : keys) key_was[vk] = (GetAsyncKeyState(vk) & 0x8000) != 0;
        } else if (modal && game_fg) {
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
                case VK_ESCAPE: case VK_BACK: back(); break;
                case VK_PRIOR: case 'Q': switch_section(-1); break;   /* Q/W: the game's L1/R1 keys */
                case VK_NEXT:  case 'W': switch_section(+1); break;
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
        else if (s_open && s_capture >= 0) {
            if (act & kCircle) { back(); redraw(); }
        }
        else if (s_open) {
            if (act & kUp) move_sel(-1);
            if (act & kDown) move_sel(+1);
            if (act & kLeft) activate(-1);
            if (act & kRight) activate(+1);
            if (act & kCross) press();
            if (act & kL1) switch_section(-1);
            if (act & kR1) switch_section(+1);
            if (act & kCircle) back();
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

        if (s_inject_until && GetTickCount64() >= s_inject_until) { g_pad_inject_buttons = 0; s_inject_until = 0; }
        memsnap_poll();
        watch_poll();
        toggle_poll();
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
