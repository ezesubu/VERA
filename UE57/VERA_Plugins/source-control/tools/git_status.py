"""git_status tool: show what has changed in the repository."""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult

from _git import GitError, current_branch, run_git


class GitStatusTool(Tool):
    name = "git_status"
    description = (
        "Show the current git branch and a concise list of changed/untracked "
        "files (git status --short). Use this BEFORE committing to see exactly "
        "what is modified, and whenever you need to know the working-tree state "
        "or which branch you are on."
    )
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        try:
            branch = current_branch()
            code, out, err = run_git(["status", "--short"])
        except GitError as exc:
            return ToolResult(f"git_status failed: {exc}", is_error=True)

        if code != 0:
            return ToolResult(
                f"git status failed: {(err or out).strip() or 'unknown error'}",
                is_error=True,
            )

        lines = [ln for ln in out.splitlines() if ln.strip()]
        header = f"Branch: {branch}"
        if not lines:
            return ToolResult(f"{header}\nWorking tree clean (no changes).")

        shown = lines[:200]
        body = "\n".join(shown)
        note = ""
        if len(lines) > len(shown):
            note = f"\n... ({len(lines) - len(shown)} more changed entries not shown)"
        return ToolResult(
            f"{header}\n{len(lines)} changed/untracked entries:\n{body}{note}"
        )
