/* Player settings: gt5p_settings.toml. See gt5p_settings.h. */
#include "gt5p_settings.h"
#include "gt5p_keymap.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <optional>
#include <string>
#include <string_view>
#include <system_error>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

/* toml++ reports parse errors through its result type instead of throwing,
 * so a broken file can never take the game down with it. */
#define TOML_EXCEPTIONS 0
#include "toml.hpp"

namespace fs = std::filesystem;

namespace {

constexpr const char* kFileName = "gt5p_settings.toml";

Gt5pSettings g_settings;
Gt5pSettings g_file;     /* as the file has them: what the settings page saves */
std::string  g_path;     /* UTF-8 */
bool         g_enabled = false;

/* The variables a setting maps to; those set before the file is applied
 * override it, and the settings page says so. */
const char* const kEnvNames[] = {
    "GT5P_RESOLUTION", "RSX_MSAA", "RSX_PRESENT_SYNC", "RSX_SHADER_CACHE", "GT5P_SHADER_INDICATOR",
    "PAD_NO_SDL", "PAD_NO_KEYBOARD", "PS3_VERBOSE",
    "GT5P_VBLANK_HZ", "SPURS_LANE_PIN", "SPURS_JL_SPU3", "RSX_SHADER_ASYNC", "RSX_SHADER_WARMUP", "RSX_PSO_ASYNC", "RSX_RACE_PREWARM", "PAD_SKIP_MOVIE",
};
bool g_env_set[sizeof kEnvNames / sizeof kEnvNames[0]];

/* fs::path <-> UTF-8 std::string, the same in C++17 and C++20 (where
 * u8string() returns std::u8string). */
std::string to_utf8(const fs::path& p)
{
    const auto s = p.u8string();
    return std::string(s.begin(), s.end());
}

fs::path from_utf8(const std::string& s)
{
#if defined(__cpp_char8_t)
    return fs::path(std::u8string(s.begin(), s.end()));
#else
    return fs::u8path(s);
#endif
}

void warn(const std::string& msg)
{
    fprintf(stderr, "[settings] %s\n", msg.c_str());
}

fs::path exe_dir()
{
    std::error_code ec;
#ifdef _WIN32
    wchar_t buf[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, buf, MAX_PATH);
    if (!n || n >= MAX_PATH) return fs::current_path(ec);
    return fs::path(buf).parent_path();
#else
    fs::path p = fs::read_symlink("/proc/self/exe", ec);
    return ec ? fs::current_path(ec) : p.parent_path();
#endif
}

/* Only when unset: anything already in the environment wins over the file. */
void set_default_env(const char* name, const char* value)
{
    if (getenv(name)) return;
#ifdef _WIN32
    _putenv_s(name, value);
#else
    setenv(name, value, 0);
#endif
}

/* GT5P_SETTINGS names the file outright. Otherwise the first existing file in
 * the exe's folder and up to five folders above it, then the working directory.
 * With none, a new file goes in the first of those folders that holds the game
 * (input/EMAIN.ELF), else beside the exe. `exists` says which case it was. */
fs::path find_settings_file(bool& exists)
{
    std::error_code ec;
    if (const char* forced = getenv("GT5P_SETTINGS"); forced && *forced) {
        exists = fs::exists(forced, ec);
        return fs::path(forced);
    }

    const fs::path start = exe_dir();
    fs::path game_root;
    fs::path dir = start;
    for (int up = 0; up <= 5 && !dir.empty(); up++) {
        if (fs::exists(dir / kFileName, ec)) { exists = true; return dir / kFileName; }
        if (game_root.empty() && fs::exists(dir / "input" / "EMAIN.ELF", ec)) game_root = dir;
        fs::path parent = dir.parent_path();
        if (parent == dir) break;
        dir = parent;
    }
    const fs::path cwd = fs::current_path(ec);
    if (!ec && fs::exists(cwd / kFileName, ec)) { exists = true; return cwd / kFileName; }
    if (game_root.empty() && !ec && fs::exists(cwd / "input" / "EMAIN.ELF", ec)) game_root = cwd;

    exists = false;
    return (game_root.empty() ? start : game_root) / kFileName;
}

/* ---- reading values: wrong type or out of range keeps the default ---- */

void read_resolution(toml::node_view<const toml::node> v, int& out)
{
    if (!v) return;
    if (auto s = v.value<std::string>()) {
        if (*s == "720p" || *s == "720")   { out = 720;  return; }
        if (*s == "1080p" || *s == "1080") { out = 1080; return; }
    } else if (auto n = v.value<int64_t>()) {
        if (*n == 720 || *n == 1080) { out = (int)*n; return; }
    }
    warn("video.resolution must be \"720p\" or \"1080p\"; keeping " +
         std::to_string(out) + "p");
}

void read_msaa(toml::node_view<const toml::node> v, int& out)
{
    if (!v) return;
    if (auto n = v.value<int64_t>()) {
        if (*n == 0 || *n == 1) { out = 1;       return; }
        if (*n == 2 || *n == 4 || *n == 8) { out = (int)*n; return; }
    }
    warn("video.msaa must be 1 (off), 2, 4 or 8; keeping " + std::to_string(out));
}

void read_vblank(toml::node_view<const toml::node> v, int& out)
{
    if (!v) return;
    double hz = 0;
    if (auto d = v.value<double>()) hz = *d;
    if (hz > 59.0 && hz < 61.0)  { out = 5994; return; }
    if (hz > 62.0 && hz < 63.0)  { out = 6250; return; }
    warn("performance.vblank_hz must be 59.94 or 62.5; keeping " + std::to_string(out / 100.0));
}

void read_lane_cores(toml::node_view<const toml::node> v, int& out)
{
    if (!v) return;
    if (auto s = v.value<std::string>()) {
        if (*s == "off")    { out = 0; return; }
        if (*s == "hint")   { out = 1; return; }
        if (*s == "strict") { out = 2; return; }
    }
    warn("performance.lane_pinning must be \"off\", \"hint\" or \"strict\"; keeping the default");
}

void read_bool(toml::node_view<const toml::node> v, const char* key, bool& out)
{
    if (!v) return;
    if (auto b = v.value_exact<bool>()) { out = *b; return; }
    warn(std::string(key) + " must be true or false; keeping " + (out ? "true" : "false"));
}

void read_tristate(toml::node_view<const toml::node> v, const char* key, int& out)
{
    if (!v) return;
    if (auto b = v.value_exact<bool>()) { out = *b ? 1 : 0; return; }
    if (auto s = v.value<std::string>(); s && *s == "auto") { out = -1; return; }
    warn(std::string(key) + " must be \"auto\", true or false; keeping the default");
}

/* Keys this version knows, so a misspelt one is reported instead of ignored. */
bool known_key(std::string_view section, std::string_view key)
{
    static const struct { const char* section; const char* key; } kKnown[] = {
        {"video", "resolution"},     {"video", "msaa"},
        {"video", "vsync"},          {"video", "shader_cache"},
        {"video", "shader_indicator"}, {"video", "shader_precompile"}, {"video", "shader_warmup"}, {"video", "pipeline_async"}, {"video", "race_preload"},
        {"input", "sdl_controllers"}, {"input", "keyboard"}, {"input", "button_prompts"},
        {"game", "skip_movie"},
        {"performance", "vblank_hz"}, {"performance", "lane_pinning"},
        {"performance", "fifth_spu_lane"},
        {"performance", "lane_cores"},   /* the old key (off by default then): read no more */
        {"debug", "verbose_log"},
        {"debug", "export_enabled"},
    };
    for (const auto& k : kKnown)
        if (section == k.section && key == k.key) return true;
    if (section == "keyboard")
        for (int i = 0; i < GT5P_KEY_BUTTONS; i++)
            if (key == gt5p_key_button(i).key) return true;
    return false;
}

void report_unknown_keys(const toml::table& tbl)
{
    for (const auto& [section, node] : tbl) {
        const toml::table* sub = node.as_table();
        if (!sub) {
            warn("unknown setting \"" + std::string(section.str()) + "\" (outside any [section])");
            continue;
        }
        for (const auto& [key, value] : *sub) {
            (void)value;
            if (!known_key(section.str(), key.str()))
                warn("unknown setting " + std::string(section.str()) + "." +
                     std::string(key.str()) + " -- ignored");
        }
    }
}

/* Button prompt styles by name, as GT5P_GLYPHS takes them (index = code). */
const char* const kPromptNames[] = { "auto", "playstation", "xbox", "nintendo", "keyboard" };
int prompt_code(const char* v)
{
    for (int i = 0; i < 5; i++) if (_stricmp(v, kPromptNames[i]) == 0) return i;
    return -1;
}

void read_prompts(toml::node_view<const toml::node> n, int& out)
{
    if (!n) return;
    if (auto v = n.value<std::string>()) {
        const int c = prompt_code(v->c_str());
        if (c >= 0) { out = c; return; }
    }
    warn("input.button_prompts must be \"auto\", \"playstation\", \"xbox\", \"nintendo\" or \"keyboard\"; keeping the default");
}

void parse_into(const toml::table& tbl, Gt5pSettings& s)
{
    report_unknown_keys(tbl);
    read_resolution(tbl["video"]["resolution"], s.resolution);
    read_msaa(tbl["video"]["msaa"], s.msaa);
    read_bool(tbl["video"]["vsync"], "video.vsync", s.vsync);
    read_bool(tbl["video"]["shader_cache"], "video.shader_cache", s.shader_cache);
    read_bool(tbl["video"]["shader_indicator"], "video.shader_indicator", s.shader_indicator);
    read_bool(tbl["video"]["shader_warmup"], "video.shader_warmup", s.shader_warmup);
    read_bool(tbl["video"]["pipeline_async"], "video.pipeline_async", s.pipeline_async);
    read_bool(tbl["video"]["race_preload"], "video.race_preload", s.race_preload);
    read_bool(tbl["video"]["shader_precompile"], "video.shader_precompile", s.shader_precompile);
    read_bool(tbl["input"]["sdl_controllers"], "input.sdl_controllers", s.sdl_controllers);
    read_bool(tbl["input"]["keyboard"], "input.keyboard", s.keyboard);
    read_prompts(tbl["input"]["button_prompts"], s.button_prompts);
    for (int i = 0; i < GT5P_KEY_BUTTONS; i++) {
        const char* k = gt5p_key_button(i).key;
        auto n = tbl["keyboard"][k];
        if (!n) continue;
        const auto v = n.value<std::string>();
        const int vk = v ? gt5p_key_from_name(v->c_str()) : -1;
        if (vk >= 0) s.keys[i] = vk;
        else warn(std::string("keyboard.") + k + ": not a key this port can bind; keeping the default");
    }
    read_bool(tbl["game"]["skip_movie"], "game.skip_movie", s.skip_movie);
    read_vblank(tbl["performance"]["vblank_hz"], s.vblank_hz100);
    read_lane_cores(tbl["performance"]["lane_pinning"], s.lane_cores);
    read_bool(tbl["performance"]["fifth_spu_lane"], "performance.fifth_spu_lane", s.fifth_spu_lane);
    read_tristate(tbl["debug"]["verbose_log"], "debug.verbose_log", s.verbose_log);
    read_bool(tbl["debug"]["export_enabled"], "debug.export_enabled", s.debug_export);
}

/* Hand the settings the runtime reads from the environment over to it. */
void apply_env(const Gt5pSettings& s)
{
    char buf[16];
    snprintf(buf, sizeof buf, "%d", s.msaa);
    set_default_env("RSX_MSAA", buf);
    set_default_env("RSX_PRESENT_SYNC", s.vsync ? "1" : "0");
    /* "0" turns the cache off; when on, leave RSX_SHADER_CACHE unset so the
     * backend keeps its own default folder. */
    if (!s.shader_cache) set_default_env("RSX_SHADER_CACHE", "0");
    if (!s.shader_indicator) set_default_env("GT5P_SHADER_INDICATOR", "0");
    set_default_env("RSX_SHADER_WARMUP", s.shader_warmup ? "1" : "0");
    set_default_env("RSX_SHADER_ASYNC", s.shader_precompile ? "1" : "0");
    set_default_env("RSX_PSO_ASYNC", s.pipeline_async ? "1" : "0");
    set_default_env("RSX_RACE_PREWARM", s.race_preload ? "1" : "0");
    /* The pad switches test for presence, so only the "off" case sets one. */
    if (!s.sdl_controllers) set_default_env("PAD_NO_SDL", "1");
    if (!s.keyboard)        set_default_env("PAD_NO_KEYBOARD", "1");
    set_default_env("PAD_KEYMAP", gt5p_keymap_format(s.keys).c_str());
    set_default_env("GT5P_GLYPHS", kPromptNames[s.button_prompts >= 0 && s.button_prompts < 5 ? s.button_prompts : 0]);
    /* The screen whose first read starts the presses (cellPad.c). */
    if (s.skip_movie)       set_default_env("PAD_SKIP_MOVIE", "MovieRoot");
    if (s.verbose_log >= 0) set_default_env("PS3_VERBOSE", s.verbose_log ? "1" : "0");
    set_default_env("GT5P_VBLANK_HZ", s.vblank_hz100 == 6250 ? "62.5" : "59.94");
    set_default_env("SPURS_LANE_PIN", s.lane_cores == 2 ? "2" : s.lane_cores == 1 ? "1" : "0");
    /* SPU 3 only gets jobs if its lane is sent every time. */
    if (s.fifth_spu_lane) { set_default_env("SPURS_JL_SPU3", "1"); set_default_env("SPURS_LANE_PRUNE", "0"); }
}

/* After apply_env: make the struct say what is actually in effect, so code
 * reading gt5p_settings() agrees with the runtime when a variable overrode
 * the file. Values the runtime itself would reject are left as they were. */
void reflect_env(Gt5pSettings& s)
{
    if (const char* e = getenv("RSX_MSAA")) {
        const int n = atoi(e);
        s.msaa = (n == 2 || n == 4 || n == 8) ? n : (n <= 1 ? 1 : 4);   /* as rsx_msaa_samples() */
    }
    if (const char* e = getenv("RSX_PRESENT_SYNC")) s.vsync = atoi(e) != 0;   /* as the backend reads it */
    if (const char* e = getenv("RSX_SHADER_CACHE")) s.shader_cache = !(e[0] == '0' && !e[1]);
    if (const char* e = getenv("GT5P_SHADER_INDICATOR")) s.shader_indicator = e[0] != '0';
    if (const char* e = getenv("RSX_SHADER_WARMUP")) s.shader_warmup = e[0] == '1';
    if (const char* e = getenv("RSX_PSO_ASYNC")) s.pipeline_async = e[0] != '0';
    if (const char* e = getenv("RSX_RACE_PREWARM")) s.race_preload = e[0] != '0';
    if (const char* e = getenv("RSX_SHADER_ASYNC")) s.shader_precompile = e[0] == '1';
    s.sdl_controllers = getenv("PAD_NO_SDL") == nullptr;
    s.keyboard        = getenv("PAD_NO_KEYBOARD") == nullptr;
    if (const char* e = getenv("GT5P_GLYPHS")) { const int c = prompt_code(e); if (c >= 0) s.button_prompts = c; }
    if (const char* e = getenv("PAD_KEYMAP")) gt5p_keymap_parse(e, s.keys);
    { const char* e = getenv("PAD_SKIP_MOVIE"); s.skip_movie = e && *e && strcmp(e, "0") != 0; }
    if (const char* e = getenv("PS3_VERBOSE")) s.verbose_log = (e[0] && e[0] != '0') ? 1 : 0;
    if (const char* e = getenv("GT5P_VBLANK_HZ")) s.vblank_hz100 = atof(e) > 62.0 ? 6250 : 5994;
    if (const char* e = getenv("SPURS_LANE_PIN")) s.lane_cores = atoi(e) >= 2 ? 2 : atoi(e) == 1 ? 1 : 0;
    s.fifth_spu_lane = getenv("SPURS_JL_SPU3") != nullptr;
}

}  // namespace

const Gt5pSettings& gt5p_settings() { return g_settings; }
const std::string& gt5p_settings_path() { return g_path; }
const Gt5pSettings& gt5p_settings_file() { return g_file; }
bool gt5p_settings_enabled() { return g_enabled; }

bool gt5p_settings_overridden(const char* env_name)
{
    if (!env_name || !*env_name) return false;
    for (size_t i = 0; i < sizeof kEnvNames / sizeof kEnvNames[0]; i++)
        if (!strcmp(kEnvNames[i], env_name)) return g_env_set[i];
    return false;
}

bool gt5p_settings_store(const Gt5pSettings& s)
{
    if (!g_enabled || g_path.empty()) return false;
    if (!gt5p_settings_save(s, g_path)) return false;
    g_file = s;
    return true;
}

/* The [keyboard] section's key = "name" lines. */
static std::string keyboard_lines(const Gt5pSettings& s)
{
    std::string out;
    for (int i = 0; i < GT5P_KEY_BUTTONS; i++) {
        const char* n = gt5p_key_name(s.keys[i]);
        out += std::string(gt5p_key_button(i).key) + " = \"" + (n ? n : "None") + "\"\n";
    }
    return out;
}

bool gt5p_settings_save(const Gt5pSettings& s, const std::string& path)
{
    std::ofstream f(from_utf8(path), std::ios::binary | std::ios::trunc);
    if (!f) return false;
    const char* verbose = s.verbose_log < 0 ? "\"auto\"" : s.verbose_log ? "true" : "false";
    f << "# Gran Turismo 5 Prologue (ps3recomp) settings.\n"
         "# Read when the game starts. Press F1 in the game (or the PS button on a\n"
         "# controller) to change them there; some take effect only after a restart.\n"
         "# A setting also given as an environment variable (shown in brackets)\n"
         "# takes the variable's value instead. Delete this file to get the defaults back.\n"
         "\n"
         "[video]\n"
         "# Display mode the game is told it has, and the window size:\n"
         "# \"720p\" (1280x720) or \"1080p\" (1920x1080). The game renders natively at it.\n"
         "resolution = \"" << s.resolution << "p\"\n"
         "# Antialiasing samples for what the game antialiases: 1 (off), 2, 4 or 8.\n"
         "# The console used 2. [RSX_MSAA]\n"
         "msaa = " << s.msaa << "\n"
         "# Wait for the monitor's refresh when showing a frame. false can tear,\n"
         "# but never holds the game back. [RSX_PRESENT_SYNC]\n"
         "vsync = " << (s.vsync ? "true" : "false") << "\n"
         "# Keep compiled shaders in the shadercache folder so they aren't rebuilt\n"
         "# every run (the first visit to a screen can stutter while they are).\n"
         "# [RSX_SHADER_CACHE, \"0\" = off]\n"
         "shader_cache = " << (s.shader_cache ? "true" : "false") << "\n"
         "# Show \"Compiling shaders\" over the game while it is building them.\n"
         "# [GT5P_SHADER_INDICATOR]\n"
         "shader_indicator = " << (s.shader_indicator ? "true" : "false") << "\n"
         "# Compile shaders the game has not shown before on background threads, all\n"
         "# at once, instead of stopping the picture to build them one by one. A new\n"
         "# screen appears at once and its last details a moment later. Needs the\n"
         "# shader cache. [RSX_SHADER_ASYNC]\n"
         "shader_precompile = " << (s.shader_precompile ? "true" : "false") << "\n"
         "# Prepare learned menu, then race pipelines while the game starts.\n"
         "# New tracks/cars/effects may still compile later; first run learns records.\n"
         "# Needs shader cache. [RSX_SHADER_WARMUP]\n"
         "shader_warmup = " << (s.shader_warmup ? "true" : "false") << "\n"
         "# Build unexpected driver pipelines in the background. [RSX_PSO_ASYNC]\n"
         "pipeline_async = " << (s.pipeline_async ? "true" : "false") << "\n"
         "# Prepare learned race pipelines during loading; needs background pipelines\n"
         "# and shader cache. First visits still learn new states. [RSX_RACE_PREWARM]\n"
         "race_preload = " << (s.race_preload ? "true" : "false") << "\n"
         "\n"
         "[input]\n"
         "# PlayStation, Switch and other controllers through SDL2.dll beside the exe.\n"
         "# Xbox controllers work either way. [PAD_NO_SDL]\n"
         "sdl_controllers = " << (s.sdl_controllers ? "true" : "false") << "\n"
         "# Keyboard as controller 1 when none is connected. [PAD_NO_KEYBOARD]\n"
         "keyboard = " << (s.keyboard ? "true" : "false") << "\n"
         "# Button prompts: \"auto\" follows the controller in use (Xbox, Switch or\n"
         "# keyboard art; a PlayStation pad keeps the game's own), or one of\n"
         "# \"playstation\", \"xbox\", \"nintendo\", \"keyboard\". [GT5P_GLYPHS]\n"
         "button_prompts = \"" << kPromptNames[s.button_prompts >= 0 && s.button_prompts < 5 ? s.button_prompts : 0] << "\"\n"
         "\n"
         "[keyboard]\n"
         "# The key for each button when playing with the keyboard (also the F1 page's\n"
         "# Keyboard tab). Letters, digits, Up Down Left Right, Enter, Tab, Space,\n"
         "# Backspace, Shift, Ctrl, Alt, Insert, Delete, Home, End, PageUp, PageDown,\n"
         "# Apostrophe, Comma, Period, Minus, Equals, Semicolon, Slash, Backquote,\n"
         "# LeftBracket, Backslash, RightBracket, or None. [PAD_KEYMAP]\n"
         << keyboard_lines(s) <<
         "\n"
         "[game]\n"
         "# Skip the opening movie (it plays only when the TV content is installed):\n"
         "# Cross is pressed for you once it starts. [PAD_SKIP_MOVIE]\n"
         "skip_movie = " << (s.skip_movie ? "true" : "false") << "\n"
         "\n"
         "[performance]\n"
         "# The game paces its frames to the vblank. 59.94 is the console's rate\n"
         "# (30 fps at most); 62.5 is the port's old clock (31.25 fps at most, but a\n"
         "# frame that only just misses two vblanks drops to 20). [GT5P_VBLANK_HZ]\n"
         "vblank_hz = " << (s.vblank_hz100 == 6250 ? "62.5" : "59.94") << "\n"
         "# Give each SPU render lane a CPU core of its own: \"strict\" (the default)\n"
         "# runs the lanes about 14% faster (Ferrari page 28 fps against 25);\n"
         "# \"hint\" (no gain) or \"off\" leaves them to Windows. [SPURS_LANE_PIN]\n"
         "lane_pinning = \"" << (s.lane_cores == 2 ? "strict" : s.lane_cores == 1 ? "hint" : "off") << "\"\n"
         "# Experimental. Let the render jobs use a fifth SPU lane, as many as the\n"
         "# console has. Freezes the dealer pages: SPU 3's own bookkeeping row is the\n"
         "# render lists' progress row (Phase 64). For testing only. [SPURS_JL_SPU3]\n"
         "fifth_spu_lane = " << (s.fifth_spu_lane ? "true" : "false") << "\n"
         "\n"
         "[debug]\n"
         "# Full runtime log: \"auto\" (off for all launch methods), true or false.\n"
         "# On makes the game stutter. Debug export works with it off. [PS3_VERBOSE]\n"
         "verbose_log = " << verbose << "\n"
         "# Keep up to 2 MiB of recent output per stream and enable F3 debug ZIP exports.\n"
         "# Applies immediately in F1. Off by default; GT5P_DEBUG_EXPORT=0 disables it.\n"
         "export_enabled = " << (s.debug_export ? "true" : "false") << "\n";
    return (bool)f.flush();
}

/* GT5P_RESOLUTION overrides the file, like the runtime's own variables. */
static void apply_resolution_env(Gt5pSettings& s)
{
    if (const char* r = getenv("GT5P_RESOLUTION"); r && *r) {
        if (!strcmp(r, "1080p") || !strcmp(r, "1080")) s.resolution = 1080;
        else if (!strcmp(r, "720p") || !strcmp(r, "720")) s.resolution = 720;
        else warn(std::string("GT5P_RESOLUTION=\"") + r + "\" is not 720p or 1080p; ignored");
    }
}

void gt5p_settings_load()
{
    g_settings = Gt5pSettings{};
    g_file = Gt5pSettings{};
    g_path.clear();
    for (size_t i = 0; i < sizeof kEnvNames / sizeof kEnvNames[0]; i++)
        g_env_set[i] = getenv(kEnvNames[i]) != nullptr;
    if (getenv("GT5P_NO_SETTINGS")) {
        /* Test runs still choose the display mode: no runtime variable can. */
        apply_resolution_env(g_settings);
        printf("[settings] GT5P_NO_SETTINGS: built-in defaults, file ignored (resolution=%dp)\n",
               g_settings.resolution);
        return;
    }
    g_enabled = true;

    bool exists = false;
    const fs::path path = find_settings_file(exists);
    g_path = to_utf8(path);

    if (!exists) {
        if (gt5p_settings_save(g_settings, g_path))
            printf("[settings] wrote defaults to %s\n", g_path.c_str());
        else
            warn("could not write " + g_path + "; using defaults");
    } else {
        /* Read it here rather than with toml::parse_file, which opens a
         * narrow path and so fails on a non-ASCII folder name on Windows. */
        std::ifstream f(path, std::ios::binary);
        std::string text((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
        toml::parse_result res = toml::parse(text, g_path);
        if (!res) {
            const auto& err = res.error();
            warn(g_path + ":" + std::to_string(err.source().begin.line) + ": " +
                 std::string(err.description()) + " -- using defaults");
        } else {
            parse_into(res.table(), g_settings);
        }
    }

    g_file = g_settings;

    apply_resolution_env(g_settings);

    apply_env(g_settings);
    reflect_env(g_settings);
    printf("[settings] %s: resolution=%dp msaa=%d vsync=%d shader_cache=%d sdl_controllers=%d keyboard=%d\n",
           g_path.c_str(), g_settings.resolution, g_settings.msaa,
           g_settings.vsync ? 1 : 0, g_settings.shader_cache ? 1 : 0,
           g_settings.sdl_controllers ? 1 : 0, g_settings.keyboard ? 1 : 0);
}
