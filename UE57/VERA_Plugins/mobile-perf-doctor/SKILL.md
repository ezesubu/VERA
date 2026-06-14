# Mobile / Performance Doctor

VERA ships a **mobile and performance doctor**: a small set of read-only tools that
audit the project for things that hurt — or outright break — a mobile build. Use it
proactively whenever the user is about to package for mobile, complains about device
crashes, or worries about GPU/shader cost.

## When to use which tool

- **`check_mobile_compat`** — run this **BEFORE packaging for mobile**. It scans the
  project's materials via the AssetRegistry and returns an OK-vs-flagged report.
- **`find_expensive_materials`** — run this alongside `check_mobile_compat` to see the
  heaviest shaders ranked by cost (instruction + sampler heuristic). Pass `limit` to
  control how many (default 10).
- **`profile_level`** — run this to sanity-check the cost of the currently open level:
  actor/light/static-mesh counts, an approximate triangle total, and obvious red flags
  (e.g. too many dynamic lights for mobile).

A good pre-package routine: `check_mobile_compat` → `find_expensive_materials` →
`profile_level`, then summarize the risks for the user before they build.

## The headline offender: gFur / PCW-GFur_Advanced

On THIS project the **gFur / PCW-GFur_Advanced fur shader is a known crash source**.
It **fails to compile on UE5.7**, which leaves a **null material**, and that null
material **dereferences to a SIGSEGV crash on mobile**. `check_mobile_compat`
specifically flags any material whose name matches `gFur` / `PCW-GFur_Advanced`.
If it shows up flagged, treat it as a blocker: the material must be replaced or
removed before a mobile package can be trusted.

## Honesty about the heuristics

These tools are **heuristic, not a certification**:

- `check_mobile_compat` flags by name pattern (the strongest, reliable signal for the
  gFur case) plus reachable instruction/sampler stats. **Absence of flags does NOT
  guarantee mobile safety** — it only means nothing matched the known patterns.
- Instruction and sampler counts depend on the editor's Python API surface in the
  running build; when a stat is unreadable the tools degrade gracefully and say so
  (e.g. `instr=?`, `stats unreachable`) rather than crashing.
- `profile_level` triangle totals are LOD0, static-mesh-actor only, and may be partial
  if some meshes can't be read; treat the number as an order-of-magnitude signal.

All three tools run curated Python inside the live Unreal editor over the bridge and
are read-only (non-destructive). If the editor bridge is unreachable they return a
clear error instead of failing silently.
