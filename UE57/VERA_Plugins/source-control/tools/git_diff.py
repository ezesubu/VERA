"""git_diff tool: inspect the exact changes before committing."""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult

from _git import GitError, run_git

MAX_DIFF_CHARS = 4000


class GitDiffTool(Tool):
    name = "git_diff"
    description = (
        "Show the line-by-line diff of changes (git diff). Use this to review "
        "exactly what changed before writing a commit. Pass `staged=true` to "
        "see staged changes (git diff --staged), or `path` to limit the diff to "
        "a single file or directory. Output is truncated to ~4000 chars."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional file or directory to limit the diff to.",
            },
            "staged": {
                "type": "boolean",
                "description": "If true, diff staged changes (git diff --staged).",
            },
        },
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        argv = ["diff"]
        if args.get("staged"):
            argv.append("--staged")
        path = (args.get("path") or "").strip()
        if path:
            argv += ["--", path]

        try:
            code, out, err = run_git(argv)
        except GitError as exc:
            return ToolResult(f"git_diff failed: {exc}", is_error=True)

        if code != 0:
            return ToolResult(
                f"git diff failed: {(err or out).strip() or 'unknown error'}",
                is_error=True,
            )

        if not out.strip():
            scope = "staged" if args.get("staged") else "working-tree"
            extra = f" for {path}" if path else ""
            return ToolResult(f"No {scope} changes{extra}.")

        if len(out) > MAX_DIFF_CHARS:
            truncated = out[:MAX_DIFF_CHARS]
            return ToolResult(
                f"{truncated}\n\n... [diff truncated at {MAX_DIFF_CHARS} chars; "
                "narrow it with `path` to see the rest]"
            )
        return ToolResult(out)
