"""analyze_project tool: wrap the existing ProjectAnalyzerAgent.

Filesystem-based — it reads the on-disk UE project (Content/, Plugins/, the
.uproject and the engine's .uplugin files). No editor bridge required.
"""
from vera.agent.tool import Tool, ToolContext, ToolResult


class AnalyzeProjectTool(Tool):
    name = "analyze_project"
    description = (
        "Analyze the on-disk Unreal project and return an overview: the engine it "
        "targets, which plugins are active, which are available to enable, which are "
        "missing, plus a high-level asset overview. Reads the filesystem directly "
        "(no editor needed). Use this BEFORE reasoning about the project or proposing "
        "changes (adding features, enabling plugins, planning work) so your "
        "conclusions match reality."
    )
    input_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        try:
            from vera.core.blackboard import Blackboard
            from vera.core.project_analyzer_agent import ProjectAnalyzerAgent

            result = ProjectAnalyzerAgent(Blackboard()).analyze()
        except Exception as e:
            return ToolResult(
                content=f"analyze_project failed: {type(e).__name__}: {e}",
                is_error=True,
            )

        summary = (result or {}).get("summary")
        if not summary:
            return ToolResult(
                content="analyze_project ran but produced no summary.",
                is_error=False,
            )
        return ToolResult(content=summary)
