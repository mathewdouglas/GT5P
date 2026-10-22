/* Button prompts in the style of the controller in use. See gt5p_glyphs.h.
 *
 * The title's button symbols are textures of their own (the Cross beside
 * "Enter" is a 52x52 DXT5) or cells of a larger picture (the controller
 * diagram of Options > Change Button Assignments, 460x720 DXT5). The backend
 * hashes each small texture it uploads and asks rsx_replace() whether to use
 * other bytes. A texture listed in assets/glyphs/textures.txt is decoded,
 * each listed cell is cleared (the button's own pixels, found by a flood from
 * the cell's centre) and Kenney's art for the same action is drawn to fit
 * where the button was; the result is encoded back to DXT5, mips included, so
 * the upload keeps the game's format and size. Labels baked into a picture
 * ("SELECT", "START") are cleared for the other styles.
 *
 * Port 0's device comes from cellPad (g_pad_device_family): SDL's controller
 * type or name, XInput meaning Xbox, otherwise the keyboard. A watcher thread
 * re-resolves the style four times a second; a change bumps the backend's
 * replacement generation and the listed textures upload again. Keyboard art
 * names the key cellPad has bound to each button (pad_keyboard_vk). */
#include "gt5p_glyphs.h"
#include "gt5p_settings.h"
#include "gt5p_keymap.h"

#define NOMINMAX
#include <windows.h>
#include <wincodec.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#pragma comment(lib, "windowscodecs.lib")

extern "C" {
/* rsx_d3d12_backend.h (u64/u32 spelled out: that header needs the runtime's types). */
typedef int (*gt5p_repl_fn)(unsigned long long hash, unsigned w, unsigned h, unsigned fmt,
                            unsigned levels, unsigned nbytes, const void* src, const void** out);
void rsx_tex_set_replacer(gt5p_repl_fn fn);
void rsx_tex_replace_invalidate(void);
/* cellPad.c */
extern volatile int g_pad_device_family;
extern volatile int g_pad_device_type;
int pad_keyboard_vk(unsigned btn);
}

namespace {

/* Actions a cell can show. */
enum Btn { B_CROSS, B_CIRCLE, B_SQUARE, B_TRIANGLE, B_L1, B_R1, B_L2, B_R2, B_L3, B_R3,
           B_START, B_SELECT, B_UP, B_DOWN, B_LEFT, B_RIGHT, B_LABEL, B_N };
const char* const kBtnName[B_N] = { "cross", "circle", "square", "triangle", "l1", "r1",
    "l2", "r2", "l3", "r3", "start", "select", "up", "down", "left", "right", "label" };
/* The cellPad.h bit of each pad action, for the keyboard's bound key. */
const unsigned kBtnPad[B_N] = { 1u << 14, 1u << 13, 1u << 15, 1u << 12, 1u << 10, 1u << 11,
    1u << 8, 1u << 9, 1u << 1, 1u << 2, 1u << 3, 1u << 0, 1u << 4, 1u << 6, 1u << 7, 1u << 5, 0 };

/* Kenney files (assets/glyphs/kenney/<name>.png) per style; "" keeps the
 * game's art for that action. D-pad arms keep it on pads: the shape is the
 * same everywhere. */
const char* const kXbox[B_N] = { "xbox_button_color_a", "xbox_button_color_b",
    "xbox_button_color_x", "xbox_button_color_y", "xbox_lb", "xbox_rb", "xbox_lt", "xbox_rt",
    "xbox_ls", "xbox_rs", "xbox_button_menu", "xbox_button_view", "", "", "", "", "" };
/* SDL reads Switch pads by their labels (A is the right-hand button), and
 * cellPad gives SDL's A to Cross, so Cross shows A here too. */
const char* const kNintendo[B_N] = { "switch_button_a", "switch_button_b", "switch_button_x",
    "switch_button_y", "switch_button_l", "switch_button_r", "switch_button_zl",
    "switch_button_zr", "switch_stick_l_press", "switch_stick_r_press", "switch_button_plus",
    "switch_button_minus", "", "", "", "", "" };

struct Img {
    int w = 0, h = 0;
    std::vector<uint8_t> px;   /* RGBA, straight alpha */
};

struct Cell { int btn, x, y, w, h, fx, fy, fw, fh; };   /* f*: box to fit the art in, 0 = the button's own */
/* A texture with button cells, or (outline) the game's highlight ring for one
 * button of a picture: cells[0] is then that button's box in the picture. */
struct Entry { unsigned w, h; std::vector<Cell> cells; int inset = 0, ring = 5; bool outline = false; };

std::map<unsigned long long, Entry> g_table;
Img g_art[5][B_N];                     /* [style][button], empty = keep */
Img g_ps_select[2];                    /* Select on a DualShock 4 (Share), a DualSense (Create) */
bool g_enabled;                        /* the module runs (GT5P_GLYPHS is not 0) */
std::mutex g_cache_mu;
std::map<std::pair<unsigned long long, int>, std::vector<uint8_t>> g_cache;
std::atomic<int> g_choice{GT5P_GLYPHS_AUTO};
std::atomic<int> g_eff{GT5P_GLYPHS_PLAYSTATION};
std::atomic<bool> g_keys_dirty{false};   /* a binding changed: reload the keyboard art */
int g_keygen;                            /* cache generation of the keyboard art (g_cache_mu) */
bool g_dbg = false;

/* ---- PNG through WIC ---------------------------------------------------- */

bool load_png(const std::string& path, Img& out)
{
    IWICImagingFactory* f = nullptr;
    if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&f))))
        return false;
    bool ok = false;
    std::wstring wp(path.begin(), path.end());
    IWICBitmapDecoder* dec = nullptr;
    IWICBitmapFrameDecode* fr = nullptr;
    IWICFormatConverter* cv = nullptr;
    UINT w = 0, h = 0;
    if (SUCCEEDED(f->CreateDecoderFromFilename(wp.c_str(), nullptr, GENERIC_READ,
                                               WICDecodeMetadataCacheOnDemand, &dec)) &&
        SUCCEEDED(dec->GetFrame(0, &fr)) && SUCCEEDED(f->CreateFormatConverter(&cv)) &&
        SUCCEEDED(cv->Initialize(fr, GUID_WICPixelFormat32bppRGBA, WICBitmapDitherTypeNone,
                                 nullptr, 0.0, WICBitmapPaletteTypeCustom)) &&
        SUCCEEDED(cv->GetSize(&w, &h)) && w && h && w <= 1024 && h <= 1024) {
        out.w = (int)w; out.h = (int)h;
        out.px.assign((size_t)w * h * 4, 0);
        ok = SUCCEEDED(cv->CopyPixels(nullptr, w * 4, (UINT)out.px.size(), out.px.data()));
    }
    if (cv) cv->Release();
    if (fr) fr->Release();
    if (dec) dec->Release();
    f->Release();
    return ok;
}

/* ---- DXT5 ---------------------------------------------------------------- */

void rgb565(uint16_t c, int* r, int* g, int* b)
{
    int r5 = (c >> 11) & 31, g6 = (c >> 5) & 63, b5 = c & 31;
    *r = (r5 << 3) | (r5 >> 2); *g = (g6 << 2) | (g6 >> 4); *b = (b5 << 3) | (b5 >> 2);
}

void decode_bc3(const uint8_t* src, int w, int h, Img& out)
{
    out.w = w; out.h = h; out.px.assign((size_t)w * h * 4, 0);
    const int bw = (w + 3) / 4, bh = (h + 3) / 4;
    for (int by = 0; by < bh; by++)
        for (int bx = 0; bx < bw; bx++) {
            const uint8_t* b = src + ((size_t)by * bw + bx) * 16;
            int a[8]; a[0] = b[0]; a[1] = b[1];
            if (a[0] > a[1]) for (int i = 2; i < 8; i++) a[i] = ((8 - i) * a[0] + (i - 1) * a[1]) / 7;
            else { for (int i = 2; i < 6; i++) a[i] = ((6 - i) * a[0] + (i - 1) * a[1]) / 5; a[6] = 0; a[7] = 255; }
            uint64_t ai = 0;
            for (int i = 0; i < 6; i++) ai |= (uint64_t)b[2 + i] << (8 * i);
            const uint16_t c0 = (uint16_t)(b[8] | (b[9] << 8)), c1 = (uint16_t)(b[10] | (b[11] << 8));
            int p[4][3];
            rgb565(c0, &p[0][0], &p[0][1], &p[0][2]);
            rgb565(c1, &p[1][0], &p[1][1], &p[1][2]);
            for (int k = 0; k < 3; k++) {     /* DXT3/5 colour is always four-colour */
                p[2][k] = (2 * p[0][k] + p[1][k]) / 3;
                p[3][k] = (p[0][k] + 2 * p[1][k]) / 3;
            }
            const uint32_t ci = (uint32_t)b[12] | ((uint32_t)b[13] << 8) | ((uint32_t)b[14] << 16) | ((uint32_t)b[15] << 24);
            for (int i = 0; i < 16; i++) {
                const int x = bx * 4 + (i & 3), y = by * 4 + (i >> 2);
                if (x >= w || y >= h) continue;
                uint8_t* d = &out.px[((size_t)y * w + x) * 4];
                const int c = (ci >> (2 * i)) & 3;
                d[0] = (uint8_t)p[c][0]; d[1] = (uint8_t)p[c][1]; d[2] = (uint8_t)p[c][2];
                d[3] = (uint8_t)a[(ai >> (3 * i)) & 7];
            }
        }
}

uint16_t to565(int r, int g, int b)
{
    return (uint16_t)((((r * 31 + 127) / 255) << 11) | (((g * 63 + 127) / 255) << 5) | ((b * 31 + 127) / 255));
}

/* One block: alpha by its min and max (eight levels), colour along the two
 * visible texels furthest apart. Enough for flat button art. */
void encode_block(const uint8_t px[16][4], uint8_t* out)
{
    int amin = 255, amax = 0;
    for (int i = 0; i < 16; i++) { amin = std::min(amin, (int)px[i][3]); amax = std::max(amax, (int)px[i][3]); }
    out[0] = (uint8_t)amax; out[1] = (uint8_t)amin;
    uint64_t ai = 0;
    if (amax > amin) {
        int pal[8]; pal[0] = amax; pal[1] = amin;
        for (int i = 2; i < 8; i++) pal[i] = ((8 - i) * amax + (i - 1) * amin) / 7;
        for (int i = 0; i < 16; i++) {
            int best = 0, bd = 1 << 30;
            for (int k = 0; k < 8; k++) { int d = std::abs(pal[k] - px[i][3]); if (d < bd) { bd = d; best = k; } }
            ai |= (uint64_t)best << (3 * i);
        }
    }
    for (int i = 0; i < 6; i++) out[2 + i] = (uint8_t)(ai >> (8 * i));

    int e0 = -1, e1 = -1, fd = -1;
    for (int i = 0; i < 16; i++) {
        if (px[i][3] < 8) continue;
        if (e0 < 0) { e0 = e1 = i; fd = 0; }
        for (int j = i + 1; j < 16; j++) {
            if (px[j][3] < 8) continue;
            int d = 0;
            for (int k = 0; k < 3; k++) { int t = px[i][k] - px[j][k]; d += t * t; }
            if (d > fd) { fd = d; e0 = i; e1 = j; }
        }
    }
    uint16_t c0 = 0, c1 = 0;
    if (e0 >= 0) { c0 = to565(px[e0][0], px[e0][1], px[e0][2]); c1 = to565(px[e1][0], px[e1][1], px[e1][2]); }
    int p[4][3];
    rgb565(c0, &p[0][0], &p[0][1], &p[0][2]);
    rgb565(c1, &p[1][0], &p[1][1], &p[1][2]);
    for (int k = 0; k < 3; k++) { p[2][k] = (2 * p[0][k] + p[1][k]) / 3; p[3][k] = (p[0][k] + 2 * p[1][k]) / 3; }
    uint32_t ci = 0;
    if (c0 != c1)
        for (int i = 0; i < 16; i++) {
            int best = 0, bd = 1 << 30;
            for (int c = 0; c < 4; c++) {
                int d = 0;
                for (int k = 0; k < 3; k++) { int t = p[c][k] - px[i][k]; d += t * t; }
                if (d < bd) { bd = d; best = c; }
            }
            ci |= (uint32_t)best << (2 * i);
        }
    out[8] = (uint8_t)c0; out[9] = (uint8_t)(c0 >> 8); out[10] = (uint8_t)c1; out[11] = (uint8_t)(c1 >> 8);
    out[12] = (uint8_t)ci; out[13] = (uint8_t)(ci >> 8); out[14] = (uint8_t)(ci >> 16); out[15] = (uint8_t)(ci >> 24);
}

void encode_bc3(const Img& im, uint8_t* out)
{
    const int bw = (im.w + 3) / 4, bh = (im.h + 3) / 4;
    for (int by = 0; by < bh; by++)
        for (int bx = 0; bx < bw; bx++) {
            uint8_t px[16][4];
            for (int i = 0; i < 16; i++) {   /* edge blocks repeat the last row/column */
                const int x = std::min(bx * 4 + (i & 3), im.w - 1), y = std::min(by * 4 + (i >> 2), im.h - 1);
                memcpy(px[i], &im.px[((size_t)y * im.w + x) * 4], 4);
            }
            encode_block(px, out + ((size_t)by * bw + bx) * 16);
        }
}

size_t bc3_size(int w, int h) { return (size_t)((w + 3) / 4) * ((h + 3) / 4) * 16; }

/* Half size, box filtered with alpha weighting. */
Img half(const Img& s)
{
    Img d; d.w = std::max(1, s.w / 2); d.h = std::max(1, s.h / 2);
    d.px.assign((size_t)d.w * d.h * 4, 0);
    for (int y = 0; y < d.h; y++)
        for (int x = 0; x < d.w; x++) {
            double c[4] = {0, 0, 0, 0};
            for (int j = 0; j < 2; j++)
                for (int i = 0; i < 2; i++) {
                    const uint8_t* p = &s.px[((size_t)std::min(y * 2 + j, s.h - 1) * s.w + std::min(x * 2 + i, s.w - 1)) * 4];
                    const double a = p[3] / 255.0;
                    for (int k = 0; k < 3; k++) c[k] += p[k] * a;
                    c[3] += a;
                }
            uint8_t* o = &d.px[((size_t)y * d.w + x) * 4];
            for (int k = 0; k < 3; k++) o[k] = (uint8_t)(c[3] > 0 ? std::lround(c[k] / c[3]) : 0);
            o[3] = (uint8_t)std::lround(c[3] / 4 * 255);
        }
    return d;
}

/* ---- composition --------------------------------------------------------- */

bool alpha_bbox(const Img& im, int thr, int* x0, int* y0, int* x1, int* y1)
{
    *x0 = im.w; *y0 = im.h; *x1 = -1; *y1 = -1;
    for (int y = 0; y < im.h; y++)
        for (int x = 0; x < im.w; x++)
            if (im.px[((size_t)y * im.w + x) * 4 + 3] > thr) {
                *x0 = std::min(*x0, x); *y0 = std::min(*y0, y); *x1 = std::max(*x1, x); *y1 = std::max(*y1, y);
            }
    return *x1 >= 0;
}

/* Premultiplied bilinear sample. */
void sample(const Img& s, double u, double v, double o[4])
{
    u -= 0.5; v -= 0.5;
    const int x0 = (int)std::floor(u), y0 = (int)std::floor(v);
    const double fx = u - x0, fy = v - y0;
    o[0] = o[1] = o[2] = o[3] = 0;
    for (int j = 0; j < 2; j++)
        for (int i = 0; i < 2; i++) {
            const int x = x0 + i, y = y0 + j;
            if (x < 0 || y < 0 || x >= s.w || y >= s.h) continue;
            const double wgt = (i ? fx : 1 - fx) * (j ? fy : 1 - fy);
            const uint8_t* p = &s.px[((size_t)y * s.w + x) * 4];
            const double a = p[3] / 255.0;
            for (int k = 0; k < 3; k++) o[k] += wgt * p[k] * a;
            o[3] += wgt * a;
        }
}

/* Draw the visible part of `art` scaled to fit the box, centred, over `dst`. */
void draw_fit(Img& dst, double bx, double by, double bw, double bh, const Img& art)
{
    int ax0, ay0, ax1, ay1;
    if (!alpha_bbox(art, 8, &ax0, &ay0, &ax1, &ay1)) return;
    const double aw = ax1 - ax0 + 1, ah = ay1 - ay0 + 1;
    const double s = std::min(bw / aw, bh / ah);
    const double dw = aw * s, dh = ah * s, ox = bx + (bw - dw) / 2, oy = by + (bh - dh) / 2;
    const int N = 4;
    for (int y = std::max(0, (int)std::floor(oy)); y < std::min(dst.h, (int)std::ceil(oy + dh)); y++)
        for (int x = std::max(0, (int)std::floor(ox)); x < std::min(dst.w, (int)std::ceil(ox + dw)); x++) {
            double acc[4] = {0, 0, 0, 0};
            for (int j = 0; j < N; j++)
                for (int i = 0; i < N; i++) {
                    const double sx = x + (i + 0.5) / N, sy = y + (j + 0.5) / N;
                    if (sx < ox || sy < oy || sx >= ox + dw || sy >= oy + dh) continue;
                    double c[4];
                    sample(art, ax0 + (sx - ox) / s, ay0 + (sy - oy) / s, c);
                    for (int k = 0; k < 4; k++) acc[k] += c[k];
                }
            for (int k = 0; k < 4; k++) acc[k] /= N * N;
            if (acc[3] <= 0) continue;
            uint8_t* d = &dst.px[((size_t)y * dst.w + x) * 4];
            const double da = d[3] / 255.0, oa = acc[3] + da * (1 - acc[3]);
            for (int k = 0; k < 3; k++) {
                const double pc = acc[k] + d[k] * da * (1 - acc[3]);
                d[k] = (uint8_t)std::clamp(std::lround(oa > 0 ? pc / oa : 0), 0L, 255L);
            }
            d[3] = (uint8_t)std::clamp(std::lround(oa * 255), 0L, 255L);
        }
}

/* The button's own pixels in a cell: a flood from the cell's centre over
 * texels more than faintly opaque, then grown by two texels for the soft
 * edge. Cleared to transparent; returns their box (before growing). */
bool clear_button(Img& im, const Cell& c, int* bx0, int* by0, int* bx1, int* by1)
{
    const int x0 = std::max(0, c.x), y0 = std::max(0, c.y);
    const int x1 = std::min(im.w, c.x + c.w), y1 = std::min(im.h, c.y + c.h);
    if (x1 <= x0 || y1 <= y0) return false;
    const int cw = x1 - x0, ch = y1 - y0;
    std::vector<uint8_t> m((size_t)cw * ch, 0);
    auto opaque = [&](int x, int y) { return im.px[((size_t)y * im.w + x) * 4 + 3] > 40; };
    int sx = x0 + cw / 2, sy = y0 + ch / 2;
    if (!opaque(sx, sy)) {      /* the centre may be a hole: nearest opaque texel */
        int bd = 1 << 30;
        for (int y = y0; y < y1; y++)
            for (int x = x0; x < x1; x++)
                if (opaque(x, y)) { int d = (x - sx) * (x - sx) + (y - sy) * (y - sy); if (d < bd) { bd = d; sx = x; sy = y; } }
        if (bd == 1 << 30) return false;
    }
    std::vector<std::pair<int, int>> st{{sx, sy}};
    m[(size_t)(sy - y0) * cw + (sx - x0)] = 1;
    *bx0 = sx; *by0 = sy; *bx1 = sx; *by1 = sy;
    while (!st.empty()) {
        auto [x, y] = st.back(); st.pop_back();
        *bx0 = std::min(*bx0, x); *by0 = std::min(*by0, y); *bx1 = std::max(*bx1, x); *by1 = std::max(*by1, y);
        const int nx[4] = {x + 1, x - 1, x, x}, ny[4] = {y, y, y + 1, y - 1};
        for (int k = 0; k < 4; k++) {
            if (nx[k] < x0 || ny[k] < y0 || nx[k] >= x1 || ny[k] >= y1) continue;
            uint8_t& mm = m[(size_t)(ny[k] - y0) * cw + (nx[k] - x0)];
            if (mm || !opaque(nx[k], ny[k])) continue;
            mm = 1; st.push_back({nx[k], ny[k]});
        }
    }
    for (int y = y0; y < y1; y++)
        for (int x = x0; x < x1; x++) {
            bool hit = false;
            for (int j = -2; j <= 2 && !hit; j++)
                for (int i = -2; i <= 2 && !hit; i++) {
                    const int u = x + i - x0, v = y + j - y0;
                    hit = u >= 0 && v >= 0 && u < cw && v < ch && m[(size_t)v * cw + u];
                }
            if (hit) memset(&im.px[((size_t)y * im.w + x) * 4], 0, 4);
        }
    return true;
}

/* A highlight ring redrawn around the new art. The game draws the ring's
 * texture centred over its button at the picture's scale, so the art is
 * placed where build() put it in the picture, shifted into the ring's frame;
 * the ring is the texels 1 to e.ring texels outside its silhouette, in the
 * original ring's colour. False when the style keeps this button's art. */
bool outline_ring(const Entry& e, int style, Img& im)
{
    const Cell& c = e.cells[0];
    const Img& art = g_art[style][c.btn];
    if (art.px.empty()) return false;
    double col[3] = {0, 0, 0}, n = 0;
    for (size_t i = 0; i < im.px.size(); i += 4)
        if (im.px[i + 3] > 128) { for (int k = 0; k < 3; k++) col[k] += im.px[i + k]; n++; }
    if (n == 0) { col[0] = 255; n = 1; }
    double fx = c.x + e.inset, fy = c.y + e.inset, fw = c.w - 2.0 * e.inset, fh = c.h - 2.0 * e.inset;
    if (c.fw > 0) { fx = c.fx; fy = c.fy; fw = c.fw; fh = c.fh; }
    const double ox = (im.w - c.w) / 2.0 - c.x, oy = (im.h - c.h) / 2.0 - c.y;
    Img sil; sil.w = im.w; sil.h = im.h; sil.px.assign(im.px.size(), 0);
    draw_fit(sil, fx + ox, fy + oy, fw, fh, art);
    /* Letters cut through the art are holes, not outside: fill whatever a
     * flood from the border cannot reach, or the ring is drawn in them too. */
    {
        std::vector<uint8_t> out((size_t)im.w * im.h, 0);
        std::vector<std::pair<int, int>> st;
        auto solid = [&](int x, int y) { return sil.px[((size_t)y * im.w + x) * 4 + 3] > 128; };
        for (int x = 0; x < im.w; x++) { st.push_back({x, 0}); st.push_back({x, im.h - 1}); }
        for (int y = 0; y < im.h; y++) { st.push_back({0, y}); st.push_back({im.w - 1, y}); }
        while (!st.empty()) {
            auto [x, y] = st.back(); st.pop_back();
            if (x < 0 || y < 0 || x >= im.w || y >= im.h) continue;
            uint8_t& o = out[(size_t)y * im.w + x];
            if (o || solid(x, y)) continue;
            o = 1;
            st.push_back({x + 1, y}); st.push_back({x - 1, y}); st.push_back({x, y + 1}); st.push_back({x, y - 1});
        }
        for (size_t i = 0; i < out.size(); i++) if (!out[i]) sil.px[i * 4 + 3] = 255;
    }
    const int R = e.ring + 1;
    for (int y = 0; y < im.h; y++)
        for (int x = 0; x < im.w; x++) {
            double d2 = 1e9;
            if (sil.px[((size_t)y * im.w + x) * 4 + 3] > 128) d2 = 0;
            else
                for (int j = -R; j <= R; j++)
                    for (int i = -R; i <= R; i++) {
                        const int u = x + i, v = y + j;
                        if (u < 0 || v < 0 || u >= im.w || v >= im.h) continue;
                        if (sil.px[((size_t)v * im.w + u) * 4 + 3] > 128) d2 = std::min(d2, (double)(i * i + j * j));
                    }
            const double d = std::sqrt(d2);
            const double a = std::clamp(d - 1.0 + 0.5, 0.0, 1.0) * std::clamp(e.ring - d + 0.5, 0.0, 1.0);
            uint8_t* p = &im.px[((size_t)y * im.w + x) * 4];
            for (int k = 0; k < 3; k++) p[k] = (uint8_t)(col[k] / n);
            p[3] = (uint8_t)std::lround(a * 255);
        }
    return true;
}

/* The replacement bytes for one listed texture in one style, or empty. */
std::vector<uint8_t> build(const Entry& e, int style, unsigned w, unsigned h, unsigned fmt,
                           unsigned levels, unsigned nbytes, const uint8_t* src)
{
    if ((fmt & 0x9F) != 0x88 || w != e.w || h != e.h) return {};   /* DXT5 only */
    if (nbytes < bc3_size((int)w, (int)h)) return {};
    Img im;
    decode_bc3(src, (int)w, (int)h, im);
    if (e.outline) {
        if (e.cells.empty() || !outline_ring(e, style, im)) return {};
        std::vector<uint8_t> out(src, src + nbytes);
        size_t at = 0;
        Img lv = im;
        for (unsigned l = 0; l < std::max(1u, levels); l++) {
            const size_t sz = bc3_size(lv.w, lv.h);
            if (at + sz > nbytes) break;
            encode_bc3(lv, out.data() + at);
            at += sz;
            if (lv.w == 1 && lv.h == 1) break;
            lv = half(lv);
        }
        return out;
    }
    bool changed = false;
    for (const Cell& c : e.cells) {
        if (c.btn == B_LABEL) {
            for (int y = std::max(0, c.y); y < std::min(im.h, c.y + c.h); y++)
                for (int x = std::max(0, c.x); x < std::min(im.w, c.x + c.w); x++)
                    memset(&im.px[((size_t)y * im.w + x) * 4], 0, 4);
            changed = true;
            continue;
        }
        const Img& art = g_art[style][c.btn];
        if (art.px.empty()) continue;
        int x0, y0, x1, y1;
        if (!clear_button(im, c, &x0, &y0, &x1, &y1)) continue;
        if (c.fw > 0) draw_fit(im, c.fx, c.fy, c.fw, c.fh, art);
        else draw_fit(im, x0 + e.inset, y0 + e.inset, x1 - x0 + 1 - 2 * e.inset,
                      y1 - y0 + 1 - 2 * e.inset, art);
        changed = true;
    }
    if (!changed) return {};
    std::vector<uint8_t> out(src, src + nbytes);   /* anything not rewritten stays the game's */
    size_t at = 0;
    Img lv = im;
    for (unsigned l = 0; l < std::max(1u, levels); l++) {
        const size_t sz = bc3_size(lv.w, lv.h);
        if (at + sz > nbytes) break;
        encode_bc3(lv, out.data() + at);
        at += sz;
        if (lv.w == 1 && lv.h == 1) break;
        lv = half(lv);
    }
    return out;
}

/* ---- the backend's callback ---------------------------------------------- */

int rsx_replace(unsigned long long hash, unsigned w, unsigned h, unsigned fmt, unsigned levels,
                unsigned nbytes, const void* src, const void** out)
{
    *out = nullptr;
    auto it = g_table.find(hash);
    if (it == g_table.end()) return 0;
    const int style = g_eff.load();
    if (style == GT5P_GLYPHS_PLAYSTATION) return 1;
    std::lock_guard<std::mutex> lk(g_cache_mu);
    auto key = std::make_pair(hash, style | (style == GT5P_GLYPHS_KEYBOARD ? g_keygen << 4 : 0));
    auto c = g_cache.find(key);
    if (c == g_cache.end()) {
        c = g_cache.emplace(key, build(it->second, style, w, h, fmt, levels, nbytes,
                                       (const uint8_t*)src)).first;
        if (g_dbg)
            fprintf(stderr, "[glyphs] %016llX %ux%u fmt 0x%02X levels %u: %s for style %d%c",
                    hash, w, h, fmt, levels, c->second.empty() ? "kept" : "replaced", style, 10);
    }
    if (c->second.size() == nbytes) *out = c->second.data();
    return 1;
}

/* ---- setup ----------------------------------------------------------------- */

int btn_from(const std::string& s)
{
    for (int b = 0; b < B_N; b++) if (s == kBtnName[b]) return b;
    return -1;
}

/* assets/glyphs/textures.txt: "<hash> <w>x<h> [inset=N] [ring=N] [outline:]<button>@x,y,w,h[/x,y,w,h] ..." per line. */
void load_table()
{
    std::ifstream f("assets/glyphs/textures.txt");
    if (!f) { fprintf(stderr, "[glyphs] assets/glyphs/textures.txt not found%c", 10); return; }
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ls(line);
        std::string hs, dim, cell;
        if (!(ls >> hs >> dim)) continue;
        Entry e{};
        if (sscanf(dim.c_str(), "%ux%u", &e.w, &e.h) != 2) continue;
        while (ls >> cell) {
            if (cell[0] == '#') break;
            if (!cell.compare(0, 6, "inset=")) { e.inset = atoi(cell.c_str() + 6); continue; }
            if (!cell.compare(0, 5, "ring=")) { e.ring = atoi(cell.c_str() + 5); continue; }
            if (!cell.compare(0, 8, "outline:")) { e.outline = true; cell.erase(0, 8); }
            const size_t at = cell.find('@');
            Cell c{};
            if (at == std::string::npos || (c.btn = btn_from(cell.substr(0, at))) < 0 ||
                sscanf(cell.c_str() + at + 1, "%d,%d,%d,%d/%d,%d,%d,%d", &c.x, &c.y, &c.w, &c.h,
                       &c.fx, &c.fy, &c.fw, &c.fh) < 4) {
                fprintf(stderr, "[glyphs] bad cell \"%s\"%c", cell.c_str(), 10);
                continue;
            }
            e.cells.push_back(c);
        }
        g_table[strtoull(hs.c_str(), nullptr, 16)] = e;
    }
}

void load_one(int style, int b, const std::string& name)
{
    g_art[style][b] = Img();
    if (name.empty()) return;
    const std::string path = "assets/glyphs/kenney/" + name + ".png";
    if (!load_png(path, g_art[style][b])) fprintf(stderr, "[glyphs] cannot read %s%c", path.c_str(), 10);
}

/* The keyboard's art follows the keys bound now (an unbound button keeps the
 * game's art). */
void load_keyboard_art()
{
    for (int b = 0; b < B_N; b++) {
        const int vk = kBtnPad[b] ? pad_keyboard_vk(kBtnPad[b]) : 0;
        const char* stem = vk ? gt5p_key_art(vk) : nullptr;
        load_one(GT5P_GLYPHS_KEYBOARD, b, stem ? std::string("keyboard_") + stem : "");
    }
}

void load_art()
{
    if (!load_png("assets/glyphs/kenney/playstation4_button_share.png", g_ps_select[0]) ||
        !load_png("assets/glyphs/kenney/playstation5_button_create.png", g_ps_select[1]))
        fprintf(stderr, "[glyphs] cannot read the PlayStation Select art%c", 10);
    for (int b = 0; b < B_N; b++) {
        load_one(GT5P_GLYPHS_XBOX, b, kXbox[b]);
        load_one(GT5P_GLYPHS_NINTENDO, b, kNintendo[b]);
    }
    load_keyboard_art();
}

int resolve()
{
    const int c = g_choice.load();
    if (c != GT5P_GLYPHS_AUTO) return c;
    switch (g_pad_device_family) {
    case 1: return GT5P_GLYPHS_KEYBOARD;
    case 2: case 5: return GT5P_GLYPHS_XBOX;
    case 4: return GT5P_GLYPHS_NINTENDO;
    default: return GT5P_GLYPHS_PLAYSTATION;   /* a PlayStation pad, or nothing */
    }
}

const char* style_name(int s)
{
    static const char* const n[] = { "auto", "playstation", "xbox", "nintendo", "keyboard" };
    return s >= 0 && s <= 4 ? n[s] : "?";
}

}  // namespace

void gt5p_glyphs_set_style(int style)
{
    if (style < GT5P_GLYPHS_AUTO || style > GT5P_GLYPHS_KEYBOARD) style = GT5P_GLYPHS_AUTO;
    g_choice = style;
}

int gt5p_glyphs_effective() { return g_eff.load(); }

void gt5p_glyphs_keys_changed() { g_keys_dirty = true; }

namespace {
/* The art for Select in the style in effect, or nullptr for the original
 * "SELECT" (a PS3 pad, or nothing known). Under g_cache_mu. */
const Img* select_art()
{
    if (!g_enabled) return nullptr;
    const Img* a = nullptr;
    switch (g_eff.load()) {
    case GT5P_GLYPHS_PLAYSTATION:
        a = g_pad_device_type == 4 ? &g_ps_select[0] : g_pad_device_type == 7 ? &g_ps_select[1] : nullptr;
        break;
    case GT5P_GLYPHS_XBOX: a = &g_art[GT5P_GLYPHS_XBOX][B_SELECT]; break;
    case GT5P_GLYPHS_NINTENDO: a = &g_art[GT5P_GLYPHS_NINTENDO][B_SELECT]; break;
    case GT5P_GLYPHS_KEYBOARD: a = &g_art[GT5P_GLYPHS_KEYBOARD][B_SELECT]; break;
    }
    return a && !a->px.empty() ? a : nullptr;
}
}  // namespace

int gt5p_glyphs_select_id()
{
    std::lock_guard<std::mutex> lk(g_cache_mu);
    const Img* a = select_art();
    return a ? (int)(1 + g_eff.load() + 8 * g_pad_device_type + 256 * g_keygen) : 0;
}

int gt5p_glyphs_select_icon(int hpx, int maxw, std::vector<uint8_t>& bgra)
{
    std::lock_guard<std::mutex> lk(g_cache_mu);
    const Img* a = select_art();
    int x0, y0, x1, y1;
    if (!a || hpx <= 0 || !alpha_bbox(*a, 8, &x0, &y0, &x1, &y1)) return 0;
    const double aspect = (double)(x1 - x0 + 1) / (y1 - y0 + 1);
    const int w = std::max(1, std::min(maxw, (int)std::lround(hpx * aspect)));
    Img im; im.w = w; im.h = hpx; im.px.assign((size_t)w * hpx * 4, 0);
    draw_fit(im, 0, 0, w, hpx, *a);
    bgra.resize(im.px.size());
    for (size_t i = 0; i < im.px.size(); i += 4) {   /* premultiplied BGRA, for AlphaBlend */
        const unsigned al = im.px[i + 3];
        bgra[i + 0] = (uint8_t)(im.px[i + 2] * al / 255);
        bgra[i + 1] = (uint8_t)(im.px[i + 1] * al / 255);
        bgra[i + 2] = (uint8_t)(im.px[i + 0] * al / 255);
        bgra[i + 3] = (uint8_t)al;
    }
    return w;
}

void gt5p_glyphs_init()
{
    const char* e = getenv("GT5P_GLYPHS");
    if (e && (!strcmp(e, "0") || !_stricmp(e, "off"))) return;
    g_enabled = true;
    g_dbg = getenv("GT5P_GLYPHS_DBG") != nullptr;
    /* The variable wins, also under GT5P_NO_SETTINGS (test runs). */
    int style = gt5p_settings().button_prompts;
    if (e) {
        static const char* const n[] = { "auto", "playstation", "xbox", "nintendo", "keyboard" };
        for (int i = 0; i < 5; i++) if (!_stricmp(e, n[i])) style = i;
    }
    gt5p_glyphs_set_style(style);
    std::thread([] {
        CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        load_table();
        load_art();
        g_eff = resolve();
        if (g_table.empty()) return;
        printf("[glyphs] %zu textures listed; style %s%c", g_table.size(), style_name(g_eff.load()), 10);
        rsx_tex_set_replacer(rsx_replace);
        /* GT5P_GLYPHS_CYCLE=<ms>: step through the styles (tests the re-upload). */
        const char* cy = getenv("GT5P_GLYPHS_CYCLE");
        const int cycle = cy ? atoi(cy) : 0;
        for (int tick = 0;; tick++) {
            Sleep(250);
            if (cycle > 0 && tick % std::max(1, cycle / 250) == 0)
                g_choice = 1 + (tick / std::max(1, cycle / 250)) % 4;
            if (g_keys_dirty.exchange(false)) {
                { std::lock_guard<std::mutex> lk(g_cache_mu); load_keyboard_art(); g_keygen++; }
                if (g_eff.load() == GT5P_GLYPHS_KEYBOARD) rsx_tex_replace_invalidate();
            }
            const int s = resolve();
            if (s == g_eff.load()) continue;
            g_eff = s;
            if (g_dbg) fprintf(stderr, "[glyphs] style %s (device family %d)%c", style_name(s), g_pad_device_family, 10);
            rsx_tex_replace_invalidate();
        }
    }).detach();
}
