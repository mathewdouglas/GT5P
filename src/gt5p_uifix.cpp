/* Menu label fade mask in ultrawide (scripts/ui_mask_patch.py).
 *
 * The text renderer computes the mask origin as rect.x / (W/2) - one, which
 * assumes the 16:9 layout fills the screen width W. Laid out centred in a
 * wider screen, the offset is the layout's share of it, (H * 16/9) / W; at
 * 16:9 that is 1 and nothing changes. GT5P_UI_MASK_FIX=0: always `one`. */
#include <stdlib.h>

extern "C" double gt5p_ui_mask_x(double w, double h, double one)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("GT5P_UI_MASK_FIX"); on = !(e && e[0] == '0'); }
    if (!on || !(w > 0.0) || !(h > 0.0)) return one;
    const double share = h * (16.0 / 9.0) / w;
    return share < 0.999 ? one * share : one;
}
