/* The keyboard's bindings: which key presses each PS3 button (gt5p_keymap.cpp).
 *
 * Sixteen buttons, in the order of Gt5pSettings::keys and the glyph table:
 * Cross Circle Square Triangle L1 R1 L2 R2 L3 R3 Start Select Up Down Left
 * Right. They come from the settings file's [keyboard] section, or from
 *   PAD_KEYMAP=cross=Z,circle=X,...   (any subset; key names as in the file)
 * which wins over the file. The F1 page's Keyboard tab rebinds them live.
 * Keys the port itself uses (Escape, F1-F12) cannot be bound.
 */
#pragma once

#include <string>

enum { GT5P_KEY_BUTTONS = 16 };

struct Gt5pKeyButton {
    const char* key;        /* settings file key and PAD_KEYMAP name: "cross" */
    const wchar_t* label;   /* the settings page's: L"Cross" */
    unsigned pad_bit;       /* CELL_PAD_CTRL_* */
    int default_vk;
};

const Gt5pKeyButton& gt5p_key_button(int i);

/* A bindable key's name ("Z", "Enter", "Comma"), "None" for 0, nullptr for a
 * key that cannot be bound. Left/right Shift, Ctrl and Alt read as one. */
const char* gt5p_key_name(int vk);
/* The virtual-key code for a name (any case), 0 for "None", -1 unknown. */
int gt5p_key_from_name(const char* name);
/* The same key with left/right variants folded (VK_LSHIFT -> VK_SHIFT). */
int gt5p_key_normalize(int vk);
/* Its Kenney art (assets/glyphs/kenney/keyboard_<stem>.png), nullptr if none. */
const char* gt5p_key_art(int vk);

/* "cross=Z,circle=X,..." for all sixteen. */
std::string gt5p_keymap_format(const int keys[GT5P_KEY_BUTTONS]);
/* Sets the entries the string names; false if any part was not understood. */
bool gt5p_keymap_parse(const char* s, int keys[GT5P_KEY_BUTTONS]);

/* Into effect: cellPad's table and the keyboard prompts. */
void gt5p_keymap_apply_one(int button, int vk);
/* At start-up: the settings' keys, PAD_KEYMAP over them. */
void gt5p_keymap_init();
