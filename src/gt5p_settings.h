/* Player settings, read from gt5p_settings.toml at start-up.
 *
 * The file lives beside the game: the first gt5p_settings.toml found in the
 * exe's folder or the folders above it (where input\EMAIN.ELF is), else the
 * working directory. If there is none, one is written with the defaults and
 * a comment on every key, so there is always a file to edit.
 *
 * Most settings are switches the runtime already reads from the environment
 * (RSX_MSAA, PAD_NO_SDL, ...). Loading sets those variables, but only when
 * they are not set already: a variable set by hand or by a script still wins
 * over the file. The rest are read through gt5p_settings().
 *
 *   GT5P_SETTINGS=<path>  read this file instead (written if missing)
 *   GT5P_NO_SETTINGS=1    ignore the file; built-in defaults, nothing applied.
 *                         For measurement runs that must not depend on it.
 */
#pragma once

#include <string>

struct Gt5pSettings {
    /* [video] */
    int resolution = 720;       /* 720 or 1080: the display mode the game is told */
    int msaa       = 4;         /* samples for targets the game antialiases: 1 (off), 2, 4, 8 */
    bool vsync        = true;   /* wait for the monitor's vblank when presenting */
    bool shader_cache = true;   /* keep compiled shaders in shadercache/ between runs */
    bool shader_indicator = true;   /* "Compiling shaders" over the game while it is busy */
    bool shader_precompile = true;  /* compile new shaders on background threads, all at once */

    /* [input] */
    bool sdl_controllers = true;    /* PlayStation / Switch / generic pads via SDL2.dll */
    bool keyboard        = true;    /* keyboard as pad 1 when no controller is connected */

    /* [game] */
    bool skip_movie = false;    /* press through the opening movie (PAD_SKIP_MOVIE) */

    /* [performance] */
    int vblank_hz100 = 5994;    /* the vblank clock, in 1/100 Hz: 5994 (console) or 6250 */
    int lane_cores   = 2;       /* SPU render lanes on cores of their own: 0 off, 1 hint, 2 strict */
    bool fifth_spu_lane = false;    /* let the render lists use SPU 3 too (experimental) */

    /* [debug] */
    int verbose_log = -1;       /* -1 auto (quiet when started by hand), 0 off, 1 on */
    bool debug_export = false;  /* opt in to bounded recent logs and F3 reports */
};

/* The settings in effect, environment overrides included. Built-in defaults
 * until gt5p_settings_load(). */
const Gt5pSettings& gt5p_settings();

/* The file loaded or created, or "" when none was used. */
const std::string& gt5p_settings_path();

/* Find, parse and apply the file. Call first thing in main(), before anything
 * reads the environment or starts a thread. Never fails: a missing key keeps
 * its default, and a bad file or value is reported on stderr and skipped. */
void gt5p_settings_load();

/* Write `s` to `path` in the commented layout. Returns false on I/O failure.
 * For a settings screen to persist changes; load uses it for the default file. */
bool gt5p_settings_save(const Gt5pSettings& s, const std::string& path);

/* For the in-game settings page (F1, gt5p_settings_ui.cpp). */

/* The values as the file has them, before environment overrides: what the
 * page edits and saves. Built-in defaults when there is no file. */
const Gt5pSettings& gt5p_settings_file();

/* True when `env_name` (RSX_MSAA, PAD_NO_SDL, GT5P_RESOLUTION, ...) was
 * already set when the file was loaded, so it overrides the file's value. */
bool gt5p_settings_overridden(const char* env_name);

/* False under GT5P_NO_SETTINGS: there is no file to save to. */
bool gt5p_settings_enabled();

/* Save `s` as the file's values (and remember them as such). */
bool gt5p_settings_store(const Gt5pSettings& s);
