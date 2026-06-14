"""git_log tool: read recent commit history."""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult

from _git import GitError, run_git

MAX_LIMIT = 100


class GitLogTool(Tool):
    name = "git_log"
    description = (
        "Show recent commits as a one-line-per-commit list (git log --oneline). "
        "Use this to see the project's recent history, find a commit hash, or "
        "understand the conventional-commit style used in this repo before "
        "writing your own commit message. Defaults to the last 10 commits."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many commits to show (default 10, max 100).",
                "minimum": 1,
                "maximum": MAX_LIMIT,
            }
        },
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        limit = args.get("limit", 10)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(MAX_LIMIT, limit))

        try:
            code, out, err = run_git(["log", "--oneline", "-n", str(limit)])
        except GitError as exc:
            return ToolResult(f"git_log failed: {exc}", is_error=True)

        if code != 0:
            return ToolResult(
                f"git log failed: {(err or out).strip() or 'unknown error'}",
                is_error=True,
            )

        if not out.strip():
            return ToolResult("No commits yet in this repository.")
        return ToolResult(out.rstrip())
