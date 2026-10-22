/* The keyboard's bindings. See gt5p_keymap.h. */
#include "gt5p_keymap.h"
#include "gt5p_settings.h"
#include "gt5p_glyphs.h"

#define NOMINMAX
#include <windows.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

extern "C" void pad_keyboard_set_vk(unsigned btn, int vk);   /* cellPad.c */

namespace {

const Gt5pKeyButton kButtons[GT5P_KEY_BUTTONS] = {
    { "cross",    L"Cross",    1u << 14, 'Z' },
    { "circle",   L"Circle",   1u << 13, 'X' },
    { "square",   L"Square",   1u << 15, 'A' },
    { "triangle", L"Triangle", 1u << 12, 'S' },
    { "l1",       L"L1",       1u << 10, 'Q' },
    { "r1",       L"R1",       1u << 11, 'W' },
    { "l2",       L"L2",       1u << 8,  '1' },
    { "r2",       L"R2",       1u << 9,  '2' },
    { "l3",       L"L3",       1u << 1,  0 },
    { "r3",       L"R3",       1u << 2,  0 },
    { "start",    L"Start",    1u << 3,  VK_RETURN },
    { "select",   L"Select",   1u << 0,  VK_TAB },
    { "up",       L"Up",       1u << 4,  VK_UP },
    { "down",     L"Down",     1u << 6,  VK_DOWN },
    { "left",     L"Left",     1u << 7,  VK_LEFT },
    { "right",    L"Right",    1u << 5,  VK_RIGHT },
};

/* Keys that can be bound, other than letters and digits: name, code, art. */
const struct { const char* name; int vk; const char* art; } kKeys[] = {
    { "Up", VK_UP, "arrow_up" },          { "Down", VK_DOWN, "arrow_down" },
    { "Left", VK_LEFT, "arrow_left" },    { "Right", VK_RIGHT, "arrow_right" },
    { "Enter", VK_RETURN, "enter" },      { "Tab", VK_TAB, "tab" },
    { "Space", VK_SPACE, "space" },       { "Backspace", VK_BACK, "backspace" },
    { "Shift", VK_SHIFT, "shift" },       { "Ctrl", VK_CONTROL, "ctrl" },
    { "Alt", VK_MENU, "alt" },            { "Insert", VK_INSERT, "insert" },
    { "Delete", VK_DELETE, "delete" },    { "Home", VK_HOME, "home" },
    { "End", VK_END, "end" },             { "PageUp", VK_PRIOR, "page_up" },
    { "PageDown", VK_NEXT, "page_down" }, { "Apostrophe", VK_OEM_7, "apostrophe" },
    { "Comma", VK_OEM_COMMA, "comma" },   { "Period", VK_OEM_PERIOD, "period" },
    { "Minus", VK_OEM_MINUS, "minus" },   { "Equals", VK_OEM_PLUS, "equals" },
    { "Semicolon", VK_OEM_1, "semicolon" }, { "Slash", VK_OEM_2, "slash_forward" },
    { "Backquote", VK_OEM_3, "tilde" },   { "LeftBracket", VK_OEM_4, "bracket_open" },
    { "Backslash", VK_OEM_5, "slash_back" }, { "RightBracket", VK_OEM_6, "bracket_close" },
};

/* Letters and digits: their art stems, one character each. */
char g_alnum[36][2];

}  // namespace

const Gt5pKeyButton& gt5p_key_button(int i) { return kButtons[i < 0 || i >= GT5P_KEY_BUTTONS ? 0 : i]; }

int gt5p_key_normalize(int vk)
{
    switch (vk) {
    case VK_LSHIFT: case VK_RSHIFT: return VK_SHIFT;
    case VK_LCONTROL: case VK_RCONTROL: return VK_CONTROL;
    case VK_LMENU: case VK_RMENU: return VK_MENU;
    default: return vk;
    }
}

const char* gt5p_key_name(int vk)
{
    vk = gt5p_key_normalize(vk);
    if (vk == 0) return "None";
    static char names[36][2];
    if ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9')) {
        const int i = vk <= '9' ? vk - '0' : 10 + vk - 'A';
        names[i][0] = (char)vk;
        return names[i];
    }
    for (const auto& k : kKeys) if (k.vk == vk) return k.name;
    return nullptr;
}

int gt5p_key_from_name(const char* name)
{
    if (!name || !*name) return -1;
    if (!_stricmp(name, "None")) return 0;
    if (!name[1]) {
        const char c = (char)toupper((unsigned char)name[0]);
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) return c;
    }
    for (const auto& k : kKeys) if (!_stricmp(k.name, name)) return k.vk;
    return -1;
}

const char* gt5p_key_art(int vk)
{
    vk = gt5p_key_normalize(vk);
    if ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9')) {
        const int i = vk <= '9' ? vk - '0' : 10 + vk - 'A';
        g_alnum[i][0] = (char)tolower(vk);
        return g_alnum[i];
    }
    for (const auto& k : kKeys) if (k.vk == vk) return k.art;
    return nullptr;
}

std::string gt5p_keymap_format(const int keys[GT5P_KEY_BUTTONS])
{
    std::string s;
    for (int i = 0; i < GT5P_KEY_BUTTONS; i++) {
        const char* n = gt5p_key_name(keys[i]);
        if (i) s += ",";
        s += kButtons[i].key; s += "="; s += n ? n : "None";
    }
    return s;
}

bool gt5p_keymap_parse(const char* s, int keys[GT5P_KEY_BUTTONS])
{
    bool ok = true;
    std::string all = s ? s : "";
    size_t at = 0;
    while (at < all.size()) {
        size_t end = all.find(',', at);
        if (end == std::string::npos) end = all.size();
        const std::string part = all.substr(at, end - at);
        at = end + 1;
        const size_t eq = part.find('=');
        if (eq == std::string::npos) { if (!part.empty()) ok = false; continue; }
        const std::string b = part.substr(0, eq), k = part.substr(eq + 1);
        int idx = -1;
        for (int i = 0; i < GT5P_KEY_BUTTONS; i++) if (!_stricmp(b.c_str(), kButtons[i].key)) idx = i;
        const int vk = gt5p_key_from_name(k.c_str());
        if (idx < 0 || vk < 0) { ok = false; continue; }
        keys[idx] = vk;
    }
    return ok;
}

void gt5p_keymap_apply_one(int button, int vk)
{
    if (button < 0 || button >= GT5P_KEY_BUTTONS) return;
    pad_keyboard_set_vk(kButtons[button].pad_bit, vk);
    gt5p_glyphs_keys_changed();
}

void gt5p_keymap_init()
{
    int keys[GT5P_KEY_BUTTONS];
    memcpy(keys, gt5p_settings().keys, sizeof keys);
    if (const char* e = getenv("PAD_KEYMAP"))
        if (!gt5p_keymap_parse(e, keys))
            fprintf(stderr, "[keymap] PAD_KEYMAP: some of \"%s\" was not understood\n", e);
    for (int i = 0; i < GT5P_KEY_BUTTONS; i++) pad_keyboard_set_vk(kButtons[i].pad_bit, keys[i]);
}
