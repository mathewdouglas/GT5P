/* Button prompts in the style of the controller in use (gt5p_glyphs.cpp).
 *
 * The title draws its PlayStation button symbols from ordinary textures. The
 * backend offers each small texture to a replacer by a hash of its bytes
 * (rsx_tex_set_replacer); the ones listed in assets/glyphs/textures.txt get
 * Kenney's input prompts (CC0, assets/glyphs/kenney/) painted over their
 * button cells, for the device on port 0: an Xbox or other pad, a Switch pad,
 * or the keyboard's bound keys. A PlayStation pad keeps the game's own art.
 *
 *   GT5P_GLYPHS=auto|playstation|xbox|nintendo|keyboard   style (auto: the
 *                       device on port 0; settings "Button prompts")
 *   GT5P_GLYPHS=0       off: the game's art always, no replacer installed
 *   GT5P_GLYPHS_DBG=1   log style changes and each texture replaced
 *   GT5P_GLYPHS_CYCLE=<ms>  step through the styles every <ms> (tests)
 */
#pragma once

#include <vector>

/* Style codes, as the settings page stores them. */
enum { GT5P_GLYPHS_AUTO = 0, GT5P_GLYPHS_PLAYSTATION = 1, GT5P_GLYPHS_XBOX = 2,
       GT5P_GLYPHS_NINTENDO = 3, GT5P_GLYPHS_KEYBOARD = 4 };

/* Installs the replacer and starts the watcher. After the backend exists. */
void gt5p_glyphs_init();

/* The settings page: a new style choice, live. */
void gt5p_glyphs_set_style(int style);

/* A keyboard binding changed (gt5p_keymap.cpp): redraw the key art. */
void gt5p_glyphs_keys_changed();

/* The Select button as the settings tag on the game's Options screen shows
 * it (gt5p_settings_ui.cpp): Create on a DualSense, Share on a DualShock 4,
 * View, minus or the bound key in the other styles. The icon is hpx pixels
 * high, at most maxw wide, as premultiplied BGRA; returns its width, or 0 for
 * the original "SELECT" pill. select_id changes whenever the icon would. */
int gt5p_glyphs_select_icon(int hpx, int maxw, std::vector<unsigned char>& bgra);
int gt5p_glyphs_select_id();

/* The style in effect now (never AUTO), for reports. */
int gt5p_glyphs_effective();
