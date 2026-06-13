"""Trivial example tool shipped by the example-hello studio plugin.

Demonstrates how a plugin contributes a Tool: a file under the plugin's
`tools/` directory with a subclass of Tool. The plugin loader discovers it.
"""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult


class StudioHelloTool(Tool):
    name = "studio_hello"
    description = (
        "Returns a friendly greeting from the studio plugin. Use this to confirm "
        "that the example-hello plugin is loaded and its tools are reachable."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "who": {
                "type": "string",
                "description": "Optional name to greet.",
            }
        },
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        who = (args.get("who") or "studio").strip()
        return ToolResult(f"Hello, {who}! VERA's example plugin is online.")
