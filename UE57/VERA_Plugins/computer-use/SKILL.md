# Computer Use

Screen capture + click for editor UI that has **no Python API**. This is a last
resort — it is fragile and needs the editor window in the foreground.

## When to use
- A control lives in a panel/menu/dialog you cannot reach via the `unreal` module
  or a dedicated tool (e.g. some Project Settings pages, a third-party plugin's
  window, a modal that blocks scripting).

## When NOT to use
- Anything reachable via the `unreal` Python API (actors, assets, levels, most
  settings, CVars) — use `run_ue_python` or a dedicated tool. It is reliable and
  does not depend on window focus or pixel positions.
- Creating Blueprints — use the Blueprint Forge plugin (Graph API, no clicking).

## How
1. `screen_capture` to take a screenshot — you read it directly (you are
   multimodal; no OCR). Locate the target control and read its pixel position.
2. `screen_click` with absolute screen `x`/`y` to click it. It asks for
   confirmation (it changes editor state).

Re-capture after each click to confirm the result before the next action.
