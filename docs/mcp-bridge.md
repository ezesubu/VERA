# VERA MCP Bridge — usage

Claude Code controls the Unreal editor via the `vera-ue` MCP server (registered
in `.mcp.json`). Tools: `ue_exec`, `ue_screenshot`, `ue_log`, `ue_status`,
`vera_command`.

## Requirements

1. The `UE57` project open in the editor (the bridge auto-starts via
   `Content/Python/init_unreal.py`; requires the "Python Editor Script
   Plugin" enabled).
   - If the editor was already open when the bridge was installed, load it
     once by hand: in the Output Log, Python tab, run `import vera_bridge`.
2. `pip install -e .[dev]` in `E:\PCW\VERA` (installs `mcp`).
3. Optional for `vera_command`: backend running — `python -m vera.core.vera_server`.

## Security

The bridge runs ARBITRARY Python without authentication on `127.0.0.1:9878`:
any local process can control the editor while it's open. This is an accepted
design for a local development tool — do not use it on shared/multi-user
machines. Never change the bind to `0.0.0.0`.

## Note about the interpreter

`.mcp.json` uses the ABSOLUTE path to Python 3.14
(`C:/Users/ezesu/AppData/Local/Programs/Python/Python314/python.exe`): this
machine has several `python.exe` on the PATH (including the Microsoft Store
stub) and Claude Code launches the server from its own environment, not from
your venv. If you move the project to another machine, update that path.

## Smoke test (manual, with the editor open)

From a Claude Code session in this repo (restarted so it loads `.mcp.json`):

1. `ue_status` → bridge online, engine version visible.
2. `ue_exec("import unreal\nprint(unreal.SystemLibrary.get_engine_version())")`
   → prints the version.
3. `ue_screenshot()` → returns a PNG of the viewport. ⚠️ Requires the editor
   to have focus or be rendering (UE throttles rendering in the background and
   the async capture never materializes — known limitation, fix pending).
4. `ue_log(50)` → last lines of the Output Log.

## Acceptance test — "loop with eyes"

Ask Claude Code: *"Build a glass bridge between the two platforms and visually
verify that it turned out right."* Claude must: run scripts with `ue_exec`,
look at the result with `ue_screenshot`, diagnose with `ue_log` if something
fails, and fix it without user intervention.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VERA_UE_PROJECT_DIR` | `<repo>/UE57` | Locates `Saved/Logs` and `Saved/Screenshots` |
| `VERA_BRIDGE_PORT` | `9878` | Bridge port in the editor |
| `VERA_BACKEND_PORT` | `9880` | Agent backend port |
| `VERA_BRIDGE_NO_AUTOSTART` | (empty) | If set, `vera_bridge` does not auto-start (tests) |

## Behavior details

- `ue_exec` is stateless: each call uses a fresh namespace (variables and
  imports do not persist between calls).
- If a script exceeds the client timeout, the bridge does NOT abort it (UE's
  main thread cannot be interrupted); `ue_exec` returns `TIMEOUT:` and the
  script keeps running. The bridge has its own 120 s timeout for tick stalls
  (modal dialogs).
- Screenshots accumulate in `UE57/Saved/Screenshots/WindowsEditor/`
  (`vera_*.png`); cleanup is pending as a future improvement.
