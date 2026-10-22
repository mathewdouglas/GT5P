# Xbox and keyboard button prompts

Assessment: 2026-10-19. **Implemented in Phase 119 (2026-10-22)** with
Kenney's CC0 art. Measured steps 1-4 and 6 are covered (`src/gt5p_glyphs.cpp`,
`assets/glyphs/`, F1 "Button prompts"). Step 5, the keyboard alongside a
connected pad, is not done: the keyboard is still a fallback. The text below
is the original plan.
The requested behaviour is automatic in-game PlayStation/Xbox/keyboard prompts,
with an explicit style override. The guest continues to receive PS3 actions.

## What exists

`libs/input/cellPad.c` already maps Xbox A/B/X/Y to PS3 Cross/Circle/Square/
Triangle. That changes input, not the artwork the game draws. The Windows SDL
backend loads SDL2 dynamically and owns controller operations on its SDL thread.
It currently imports controller names, not `SDL_GameControllerGetType`.
XInput is used when the SDL path is unavailable. The keyboard poll currently
runs only without a connected port-0 controller, except for automated PAD_HOLD
scripts. Thus simply observing keyboard presses to change the icons would
produce misleading prompts unless keyboard/controller input arbitration changes
too.

The current Windows bindings, measured from the keyboard map in that file:

| PS3 action | Xbox prompt | Keyboard prompt |
| --- | --- | --- |
| Cross | A | Z |
| Circle | B | X |
| Square | X | A |
| Triangle | Y | S |
| L1 / R1 | LB / RB | Q / W |
| L2 / R2 | LT / RT | 1 / 2 |
| Start | Menu | Enter |
| Select | View | Tab |
| D-pad | D-pad directions | Arrow keys |

Enter is currently Start, not the Cross/confirm action. Glyph labels should be
derived from the binding table, so a later rebinding feature cannot leave stale
hard-coded labels. Keyboard L3/R3 and stick-motion prompts have no equivalent
in the current binding table; do not invent a usable key for them.

## Proposed implementation

1. **Identify the actual prompts.** Capture a screen with visible confirm/back
   prompts at 720p and 1080p; identify their draws and sources. No prompt atlas,
   texture region or font codepoint has been identified yet. Prompts could be
   sprites in an atlas, font symbols, or more than one path. The game has both
   texture-based UI and stencil-built text, so the implementation must follow
   the measured source. Existing loading-font fixes are not proof of the
   button-symbol path.
2. **Create original glyph assets.** Keep editable vector sources for Xbox
   buttons and keyboard keycaps, rasterizing to a renderer-neutral resource
   where needed. Match the existing prompt footprint, baseline, alpha and
   readability; use compact Enter/Tab symbols where a full word will not fit.
   Do not track extracted game textures, font data or repacked game archives.
3. **Replace the correct source.** For sprite prompts, substitute known atlas
   cells while preserving unrelated content, or replace their identified
   sprite draws. Match a verified asset identity and region, not an unstable
   guest address or all circles/X characters. If the prompts are font symbols,
   hook their identified symbol/glyph construction instead. A normal text X
   must remain text. Unmatched or unsupported prompts keep their original
   rendering. Keep the logical replacement mapping outside D3D12-specific code
   so a future Vulkan backend can consume it too.
4. **Track active input.** Add an input snapshot/query with the selected player,
   device family and last meaningful activity. SDL controller classification
   must happen on the existing SDL owner thread; expose a small thread-safe
   result to rendering. XInput implies Xbox-style prompts. Treat controller
   names only as a fallback, and allow manual selection for unknown devices
   or controller-emulation software. A connection alone is not activity.
5. **Allow real switching.** Poll keyboard and controller independently while
   the game is focused and select the active input source on meaningful new
   input. Use button/key edges and movement thresholds/hysteresis, not idle
   reports or analog drift. Release stale state when switching or losing
   focus. Preserve PAD_HOLD precedence for tests; scripted input must not
   masquerade as physical device activity. Scope prompts to the player whose
   controls they describe.
6. **Expose the choice.** Proposed F1 setting: Button prompts = Original /
   Auto / PlayStation / Xbox / Keyboard. Original should remain available as
   a direct fallback. A proposed `GT5P_GLYPHS=original` kill switch restores
   the stock path; the name is not implemented yet. Make style switching live
   once resource lifetime and cache invalidation are handled. Record effective
   style/device in the existing opt-in debug export.

A safe first implementation slice is a manually forced Xbox replacement of
identified confirm/back prompts on one menu page. Then expand symbol coverage,
add keyboard labels, and finally enable automatic switching after real keyboard
input works alongside a connected pad. Avoid exposing a settings option that
only changes a stored value without changing visible prompts.

## Acceptance checks

- Forced Original reproduces stock prompts; Xbox shows A/B for confirm/back;
  Keyboard shows the actual bound keys rather than assumed PC defaults.
- Arrow/D-pad, shoulders, triggers, Start/Select and unsupported stick actions
  have deliberate coverage or a documented fallback.
- Auto works for a real Xbox pad, a PlayStation pad and the keyboard, including
  keyboard use while a controller remains connected. Unknown/emulated devices
  can be corrected with the manual override.
- Analog drift and unchanged held inputs do not make styles alternate.
  Disconnect/reconnect, focus changes and automated runs do not leave stuck
  controls or misleading labels.
- Layout remains legible in menu, dealer, pit, pause/replay and race UI at
  720p/1080p, without changing ordinary text, icons or unrelated atlas cells.
- Renderer/resource changes preserve depth, alpha and texture caching, and do
  not require editing or distributing GT.VOL or other original game data.

SDL's official [SDL_GameControllerGetType documentation](https://wiki.libsdl.org/SDL2/SDL_GameControllerGetType)
provides controller-family classification (available since SDL 2.0.12). The
Windows dynamic import should be optional for older SDL2 DLLs, with a documented
fallback; the existing required imports need not become unavailable merely
because this classification function is missing.
