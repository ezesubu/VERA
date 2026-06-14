"""Layer 0 (bash-core): run arbitrary Python inside the UE editor."""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class RunUEPythonTool(Tool):
    name = "run_ue_python"
    description = (
        "Runs Python code inside the Unreal Engine editor (main-thread safe) "
        "via the bridge. Use this for ANY editor operation that has no dedicated "
        "tool: create/modify actors, read the level, adjust settings, etc. "
        "The `unreal` module is already available. Use print() to return data."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to run in the editor.",
            }
        },
        "required": ["code"],
    }
    destructive = True  # MVP decision: destructive by default (always asks for OK)

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        code = (args.get("code") or "").strip()
        if not code:
            return ToolResult("Error: the 'code' argument is empty.", is_error=True)
        ctx.report("UEPython", "running script in the editor")
        try:
            resp = send_json(ctx.bridge_port, {"script": code})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not run in the editor: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or "(no output)")
        return ToolResult(resp.get("error") or "unknown editor failure", is_error=True)
