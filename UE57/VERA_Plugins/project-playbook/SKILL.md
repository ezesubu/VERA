# PCW Studio knowledge

You are working inside **PCW**, Ezequiel's Unreal Engine project (an Aztec-themed
action game, with cyberpunk experiments). Treat the facts below as ground truth so
you don't rediscover them every session. When you learn something new and durable,
`remember` it (the Memory plugin) so this knowledge keeps growing.

## Engine & frameworks
- The big project (PCWMaster) runs on a **source-built engine** at
  `E:/PCW/UnrealCore/UnrealEngine` — not the Epic launcher build. Some launcher-only
  assumptions won't hold.
- **ACF (Advanced Character Framework)** is the core gameplay framework for characters,
  combat, abilities and weapons. Prefer ACF patterns over hand-rolled ones.
- **Niagara** and **Chaos Physics** are active. **GAS** and **Animation** plugins are
  available but may be toggled off — check before assuming.

## Known gotchas (don't relearn these)
- **gFur is dead.** `PCW-GFur_Advanced` (and gFur generally) is **abandoned and
  incompatible with UE5.7**: it fails to compile, which yields a **null material →
  SIGSEGV crash on mobile**. This was the root cause of the mobile APK crash (same bug
  ~28×). Do NOT rely on gFur; re-materialize fur by hand with mobile-safe materials.
- **Mutable skeletons are transient.** On PCWMaster, Mutable-generated characters have
  **transient skeletons that bypass the asset registry** — registry/asset-scan tools
  may not see them. Inspect the live actor instead of trusting a registry lookup.
- **Mobile builds are the fragile path.** PC PIE can be valid while the mobile build
  crashes. Always check mobile material/shader compatibility before packaging for
  Android (use the Mobile/Perf Doctor plugin if enabled).

## Content conventions
- The Aztec bestiary scales **Lv 1 → 10** (bosses like Huitzilopochtli, Tezcatlipoca,
  Tlacuache, etc.). Aztec/boss characters generally use the **UE5 Manny skeleton**.
- A clean "solo capture / showcase" lighting recipe (the **S.A.M** recipe): white
  directional light ~5.0, no shadows, exposure 1.0, bloom 0 — use it when capturing a
  single actor so renders come out in true color.
- `capture_actor` uses a SceneCapture2D + show-only set, which sidesteps UE5.7's
  background-throttling problem for screenshots (the editor must otherwise have focus).

## How to work here
- Before proposing changes, understand the current state (`analyze_project`,
  `inspect_level`, `recall`). Verify in PIE; the mobile path needs extra care.
- Default to the minimal fix Ezequiel asked for; show progress visually when you can.
- Keep new code, comments and UI copy in **English**.
