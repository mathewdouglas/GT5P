# Ultrawide (2560x1080, 21:9)

Plan: 2026-10-22. Step 1 is done (Phase 121). Step 2 stage A, anamorphic,
is done (Phase 122): run it with `GT5P_ULTRAWIDE=1 GT5P_RESOLUTION=1080p`.

The PS3 has no 21:9 output mode, and the game is told 1920x1080 at 16:9.
The port keeps telling it that. It widens the picture in the renderer and
gives the game a 21:9 aspect ratio.

## What is known (Phase 121)

- **The aspect ratio:** it comes from one table entry, `aspect_16_9_float`
  (`0x01287DD0`, BCUS98158). The setup in `func_007AE548` reads it once at
  boot, picked by a mode byte (presumably cellVideoOut's aspect).
- **What the patch does:** writing 64/27 there at load gives the race camera
  a 21:9 projection with the same vertical field of view, and the race HUD
  then lays itself out centred.
- **Menus:** their 2D layout does not use it.
- **Race scene target:** at 1080p the race scene is drawn 1280x1080 into
  `0x01980000` and stretched to 1920 by the game.
- **Culling:** it appears to follow the projection. Objects reached the edges
  of a squeezed 21:9 image. Confirm once the frame is wide.

## Steps

1. **Measure** (done): the aspect source, its readers, what it drives.
2. **Prototype.**
   - **Stage A (done, Phase 122):** the aspect patch plus a 21:9 window,
     with the swap chain stretching the 16:9 frame. The race and dealer
     pages are correct, nothing is culled at the edges, and menu 2D is
     stretched.
   - **Stage B, native width:**
   - a 2560x1080 swap chain and window;
   - the full-screen targets rendered 4/3 wider, with full-width viewports
     and scissors scaled to match;
   - the aspect table patched at load.

   Then follow what draws in pixels: MSAA resolves, the depth copy, frame
   copies, NV3089 blits, texel-addressed sampling and write-backs. Look for
   pop-in at the screen edges.
3. **2D** (done, Phase 123): the game centres menus itself once its UI
   aspect constant is patched (`ui_aspect_16_9_float`). Full-screen
   untextured or gradient layers have their 16:9 edges stretched to the
   screen in the vertex shader. Open: the My Page label cut-off, and the F1
   page and movie still stretched. Original plan: menus and other full-width 2D. Class each draw as 2D (pillarbox
   it to the middle 1920 by scaling clip x by 3/4) or as a full-screen
   post-processing pass (keep the full width). The race HUD needs nothing,
   since it centres itself. Check the menus, dealer pages, pit, pause,
   replays, loading screens and the opening movie.
4. **Finish** (done, Phase 124): F1 VIDEO > Aspect ratio and
   `video.aspect`. Original plan: a setting (resolution "2560x1080 (21:9)", with an env switch),
   docs, and the frame test at 2560x1080.

## Ruled out

Making the game itself render 2560 wide by patching its surface sizes. Its
surfaces sit at fixed video-memory offsets, and the renderer matches them by
offset, so wider surfaces would overlap their neighbours.

## Diagnostics from step 1

- `RSX_CAP_VPC=<target>` with `RSX_CAP_VPFULL=1`: the main camera's
  constants in a capture manifest.
- `GT5P_POKE=<milestone>+<ms>:addr=value[,!addr=value]`: write guest words at
  run time.
- `GT5P_POKE_BOOT=addr=value[,...]`: write them into the loaded image
  before the game starts.
- `GT5P_WATCH`, `GT5P_MEMSNAP` and `PPU_WWATCH`, as before.
