# Scene Vibe

VERA can set the **cinematic mood** of the level currently open in the Unreal editor in
a single command — perfect right before taking a showcase screenshot or recording a demo
of a game. Pick a mood, capture the beauty shot, then restore the level.

## Tools

### `set_vibe` (destructive, reversible)
Apply a cinematic mood to the open level. Argument:

- `mood` — one of the 5 moods below.

It spawns (or reuses, if already present) a **tagged DirectionalLight** and a **tagged,
unbound PostProcessVolume**, then applies curated color grading (saturation, contrast,
gain, split-tone shadows/highlights), exposure bias, bloom, vignette and — where the
build supports it — film grain, plus a matching sun color, intensity and angle. It is
**idempotent**: calling it again (even with a different mood) reuses the same two actors
instead of stacking new ones.

### `clear_vibe` (destructive, reversible)
Remove the vibe. Destroys every actor tagged `VERA_Vibe` (the DirectionalLight and the
PostProcessVolume that `set_vibe` added) and leaves everything you authored untouched,
restoring the level's original look. Safe to call even when no vibe is active.

## The 5 moods

- **cyberpunk** — cool teal/blue shadows with magenta highlights, high contrast, bloom
  turned up, a slight vignette; dim cool directional light.
- **horror** — very dark and desaturated, cold tint, heavy vignette, low exposure; weak
  reddish directional light.
- **golden_hour** — warm orange sun low on the horizon, soft and gentle bloom, warm tint.
- **noir** — near-monochrome (very low saturation), high contrast, strong vignette; hard
  white key light.
- **aztec_dusk** — warm amber and purple split-tone, atmospheric, medium exposure; orange
  sun low on the horizon.

## How VERA uses it

1. Call `set_vibe` with the mood that fits the shot (e.g. `cyberpunk` for a neon city).
2. Take the showcase screenshot or start the recording.
3. Call `clear_vibe` to restore the level when done.

**Fully reversible** — the vibe is just two tagged actors, and `clear_vibe` removes them.
Every editor operation is individually guarded, so an unavailable property degrades
gracefully and the rest of the look still applies; the tools never crash the editor.
